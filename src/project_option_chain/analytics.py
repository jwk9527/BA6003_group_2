"""Single-expiry option-chain metrics and gamma-exposure calculations."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

from .config import GEX_CURVE_STEP, GEX_PRICE_PADDING_STD_MULTIPLIER
from .models import ChainAnalysis, ChainMetadata
from .rates import get_shibor_rate

REQUIRED_COLUMNS = {"date",         #查询日期
                    "ETF_close",    #标的现价（收盘价）
                     "oi",          #持仓量
                     "iv",          #隐含波动率
                     "delta",       #delta
                     "gamma",       #gamma
                     "mul",         #乘数
                     "DTE_n",       #剩余到期日（自然日）
                     "name",        #期权合约名称 （！这里需要在数据库添加flag：购/沽）
                     "hv30",        #30日历史波动率    （有就粘贴，没有填1）
                     "hv60",        #60日历史波动率
                     "hv90"}        #90日历史波动率

# Columns that MUST have values for the calculations to run. Historical
# volatility (hv30/60/90) is only an output/reference column — GEX, IV smile,
# walls and max pain do not need it — so rows may keep running when HV is
# missing (e.g. the live iFinD adapter could not fetch it).
HARD_COLUMNS = tuple(REQUIRED_COLUMNS - {"hv30", "hv60", "hv90"})


def parse_contract_name(name: str) -> tuple[int, int, float]:
    text = str(name)
    is_call = int("购" in text)
    is_put = int("沽" in text)
    strikes = re.findall(r"\d+", text)
    return is_call, is_put, float(strikes[-1]) / 1000 if strikes else np.nan


def prepare_options(options: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical chain table and derive is_call/is_put/strike_price.

    Prefers explicit ``option_type``/``strike`` columns (canonical 15-column
    schema); falls back to parsing the contract name (original notebook
    behaviour) when those columns are absent.
    """
    options = options.dropna(subset=list(HARD_COLUMNS)).copy()
    missing = REQUIRED_COLUMNS.difference(options.columns)
    if missing:
        raise ValueError(f"Option-chain data is missing columns: {', '.join(sorted(missing))}")
    if options.empty:
        raise ValueError("Option-chain data has no complete records.")

    if {"option_type", "strike"}.issubset(options.columns):
        mapping = {"c": 1, "p": 0, "购": 1, "沽": 0, "call": 1, "put": 0}
        is_call = options["option_type"].astype(str).str.strip().str.lower().map(mapping)
        if is_call.isna().any():
            raise ValueError("Unrecognised option_type value in one or more rows.")
        options["is_call"] = is_call.astype(int)
        options["is_put"] = 1 - options["is_call"]
        options["strike_price"] = options["strike"].astype(float)
    else:
        parsed = options["name"].map(parse_contract_name)
        options[["is_call", "is_put", "strike_price"]] = pd.DataFrame(parsed.tolist(), index=options.index)
        if options[["is_call", "is_put", "strike_price"]].isna().any().any() or not (options["is_call"] | options["is_put"]).all():
            raise ValueError("Could not parse option type or strike price from one or more contract names.")
    return options


def _max_pain(options: pd.DataFrame) -> float:
    strikes = np.sort(options["strike_price"].unique())
    calls = options.loc[options["is_call"] == 1]
    puts = options.loc[options["is_put"] == 1]
    pain = [
        (strike, (calls["oi"] * np.maximum(0, strike - calls["strike_price"])).sum() + (puts["oi"] * np.maximum(0, puts["strike_price"] - strike)).sum())
        for strike in strikes
    ]
    return float(min(pain, key=lambda item: item[1])[0])


def fit_iv_smiles(options: pd.DataFrame, spot: float) -> tuple[CubicSpline, CubicSpline]:
    """Fit separate call and put IV smiles using the 1c CubicSpline method."""
    def spline_for(option_type: int) -> CubicSpline:
        subset = options.loc[options["is_call"] == option_type, ["strike_price", "iv"]].groupby("strike_price", as_index=False).mean().sort_values("strike_price")
        if len(subset) < 2:
            raise ValueError("At least two strikes are required for each option type to fit the IV smile.")
        return CubicSpline(subset["strike_price"].to_numpy() / spot, subset["iv"].to_numpy(), extrapolate=True)

    return spline_for(1), spline_for(0)


def _gex_curve(options: pd.DataFrame, spot: float, multiplier: float, tau: float, rate: float) -> pd.DataFrame:
    call_smile, put_smile = fit_iv_smiles(options, spot)
    strikes = options["strike_price"].to_numpy(dtype=float)
    types = options["is_call"].to_numpy(dtype=bool)
    open_interest = options["oi"].to_numpy(dtype=float)
    padding = options["strike_price"].std() * GEX_PRICE_PADDING_STD_MULTIPLIER
    low = max(round(spot - padding, 3), float(strikes.min()))
    high = min(round(spot + padding, 3), float(strikes.max()))
    prices = np.round(np.arange(low, high + GEX_CURVE_STEP / 2, GEX_CURVE_STEP), 3)
    sqrt_tau = np.sqrt(tau)
    records: list[dict[str, float]] = []

    for simulated_spot in prices:
        moneyness = strikes / simulated_spot
        iv = np.where(types, call_smile(moneyness), put_smile(moneyness))
        iv = np.clip(iv, 0.01, 5.0)
        d1 = (np.log(simulated_spot / strikes) + (rate + 0.5 * iv**2) * tau) / (iv * sqrt_tau)
        gamma = np.exp(-0.5 * d1**2) / (np.sqrt(2 * np.pi) * simulated_spot * iv * sqrt_tau)
        signs = np.where(types, 1.0, -1.0)
        total_gex = (gamma * open_interest * multiplier * simulated_spot**2 * 0.01 * signs).sum()
        records.append({"test_price": simulated_spot, "total_gex": total_gex})
    return pd.DataFrame.from_records(records)


def _zero_gamma(curve: pd.DataFrame, spot: float) -> float | None:
    gex = curve["total_gex"]
    crossings = curve.loc[gex.mul(gex.shift()).lt(0)].copy()
    if crossings.empty:
        return None
    crossings["distance"] = (crossings["test_price"] - spot).abs()
    return float(crossings.loc[crossings["distance"].idxmin(), "test_price"])


def atm_iv_interpolated(options: pd.DataFrame, spot: float) -> tuple[float, float]:
    """ATM IV = distance-weighted average of the two strikes bracketing spot.

    At each strike the IV is the mean of the call and put IV (whichever exist,
    IV > 0). With K_lo <= S <= K_hi: w_lo = (K_hi - S)/(K_hi - K_lo), w_hi = 1 - w_lo.
    If spot is outside the strike range (or sits on a strike) the nearest
    strike's IV is used. Returns (atm_iv, reference strike nearest to spot).
    """
    valid = options.loc[options["iv"] > 0]
    by_strike = valid.groupby("strike_price")["iv"].mean().sort_index()
    ks = by_strike.index.to_numpy(dtype=float)
    nearest = float(ks[np.abs(ks - spot).argmin()])
    lo, hi = ks[ks <= spot], ks[ks >= spot]
    if len(lo) == 0 or len(hi) == 0 or lo.max() == hi.min():
        return float(by_strike[nearest]), nearest
    k_lo, k_hi = float(lo.max()), float(hi.min())
    w_lo = (k_hi - spot) / (k_hi - k_lo)
    return float(w_lo * by_strike[k_lo] + (1 - w_lo) * by_strike[k_hi]), nearest


def _nearest_iv(options: pd.DataFrame, spot: float) -> tuple[float, float, float, float, float]:
    calls = options.loc[options["is_call"] == 1]
    puts = options.loc[options["is_put"] == 1]
    call_25 = calls.loc[(calls["delta"] - 0.25).abs().idxmin()]
    put_25 = puts.loc[(puts["delta"] + 0.25).abs().idxmin()]
    atm_iv, atm_strike = atm_iv_interpolated(options, spot)
    call_iv, put_iv = float(call_25["iv"]), float(put_25["iv"])
    return atm_iv, call_iv - put_iv, call_iv / put_iv, float(put_25["strike_price"] - call_25["strike_price"]), atm_strike


def _gex_curve_multi(options: pd.DataFrame, spot: float, multiplier: float,
                     shibor_path: Path, valuation_date) -> pd.DataFrame:
    """Aggregate GEX curve over several expiries: each expiry gets its own
    smile fit, time to expiry (DTE/360, as in the single-month curve) and
    Shibor rate at its tenor; the per-expiry curves are summed on a common grid."""
    groups = list(options.groupby("DTE_n"))
    strikes = options["strike_price"].to_numpy(dtype=float)
    padding = options["strike_price"].std() * GEX_PRICE_PADDING_STD_MULTIPLIER
    low = max(round(spot - padding, 3), float(strikes.min()))
    high = min(round(spot + padding, 3), float(strikes.max()))
    prices = np.round(np.arange(low, high + GEX_CURVE_STEP / 2, GEX_CURVE_STEP), 3)
    total = np.zeros_like(prices, dtype=float)
    for dte, grp in groups:
        dte = int(dte)
        if dte <= 0:
            continue
        tau = dte / 360.0
        rate = get_shibor_rate(shibor_path, valuation_date, dte)
        call_smile, put_smile = fit_iv_smiles(grp, spot)
        k = grp["strike_price"].to_numpy(dtype=float)
        types = grp["is_call"].to_numpy(dtype=bool)
        oi = grp["oi"].to_numpy(dtype=float)
        signs = np.where(types, 1.0, -1.0)
        for i, s_sim in enumerate(prices):
            iv = np.clip(np.where(types, call_smile(k / s_sim), put_smile(k / s_sim)), 0.01, 5.0)
            d1 = (np.log(s_sim / k) + (rate + 0.5 * iv**2) * tau) / (iv * np.sqrt(tau))
            gamma = np.exp(-0.5 * d1**2) / (np.sqrt(2 * np.pi) * s_sim * iv * np.sqrt(tau))
            total[i] += (gamma * oi * multiplier * s_sim**2 * 0.01 * signs).sum()
    return pd.DataFrame({"test_price": prices, "total_gex": total})


def merge_exposure(analysis: ChainAnalysis, extra: pd.DataFrame, shibor_path: Path) -> ChainAnalysis:
    """Module-1 view with extra expiries (e.g. next month) merged in.

    Recomputes OI/GEX by strike, call/put walls, max pain, net GEX, aggregate
    GEX curve (per-contract expiry & rate) and zero gamma on front + extra.
    Spot, IV and other metrics are left untouched (module 2 stays front-month).
    """
    meta = analysis.metadata
    extra = prepare_options(extra)
    extra["gex_amount"] = (extra["gamma"] * extra["oi"] * meta.multiplier * meta.spot**2 * 0.01
                           * np.where(extra["is_call"] == 1, 1, -1))
    options = pd.concat([analysis.options, extra[analysis.options.columns.intersection(extra.columns)]],
                        ignore_index=True)
    strike_gex = options.groupby("strike_price", as_index=False)["gex_amount"].sum().sort_values("strike_price")
    curve = _gex_curve_multi(options, meta.spot, meta.multiplier, shibor_path, meta.valuation_date)
    zero_gamma = _zero_gamma(curve, meta.spot)
    metrics = analysis.metrics.copy()
    metrics.loc[0, "call_wall"] = round(float(options.loc[options["is_call"] == 1].groupby("strike_price")["oi"].sum().idxmax()), 3)
    metrics.loc[0, "put_wall"] = round(float(options.loc[options["is_put"] == 1].groupby("strike_price")["oi"].sum().idxmax()), 3)
    metrics.loc[0, "max_pain"] = round(_max_pain(options), 3)
    metrics.loc[0, "net_gex_million"] = round(options["gex_amount"].sum() / 1_000_000, 2)
    metrics["zero_gamma"] = metrics["zero_gamma"].astype(object)
    metrics.loc[0, "zero_gamma"] = None if zero_gamma is None else round(zero_gamma, 3)
    return ChainAnalysis(meta, metrics, options, strike_gex, curve)


def analyze_option_chain_frame(options: pd.DataFrame, shibor_path: Path) -> ChainAnalysis:
    """Calculate core 1c metrics from an in-memory canonical chain table."""
    options = prepare_options(options)
    first = options.iloc[0]
    valuation_date = pd.Timestamp(first["date"]).date()
    spot, multiplier, dte = float(first["ETF_close"]), float(first["mul"]), int(first["DTE_n"])
    if dte <= 0:
        raise ValueError("Days to expiry must be positive (expiry day or expired chain).")
    tau = dte / 360.0
    rate = get_shibor_rate(shibor_path, valuation_date, dte)

    call_wall = options.loc[options["is_call"] == 1].groupby("strike_price")["oi"].sum().idxmax()
    put_wall = options.loc[options["is_put"] == 1].groupby("strike_price")["oi"].sum().idxmax()
    options["gex_amount"] = options["gamma"] * options["oi"] * multiplier * spot**2 * 0.01 * np.where(options["is_call"] == 1, 1, -1)
    strike_gex = options.groupby("strike_price", as_index=False)["gex_amount"].sum().sort_values("strike_price")
    try:
        curve = _gex_curve(options, spot, multiplier, tau, rate)
        zero_gamma = _zero_gamma(curve, spot)
    except ValueError:  # fewer than two strikes on one side -> no smile fit, no curve
        curve, zero_gamma = pd.DataFrame(columns=["test_price", "total_gex"]), None
    atm_iv, skew, volatility_ratio, risk_reversal, atm_strike = _nearest_iv(options, spot)

    def _to_float(value: object) -> float | None:
        """float() that tolerates None/NaN (HV is optional in live mode)."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)

    metrics = pd.DataFrame([{
        "date": valuation_date.isoformat(), "spot": round(spot, 3), "risk_free_rate": rate,
        "days_to_expiry": dte, "call_wall": round(float(call_wall), 3), "put_wall": round(float(put_wall), 3),
        "max_pain": round(_max_pain(options), 3), "net_gex_million": round(options["gex_amount"].sum() / 1_000_000, 2),
        "zero_gamma": None if zero_gamma is None else round(zero_gamma, 3), "atm_iv": atm_iv,
        "atm_strike": atm_strike, "call25_put25_iv_skew": skew, "call25_put25_iv_ratio": volatility_ratio,
        "put25_minus_call25_strike": risk_reversal, "hv30": _to_float(first["hv30"]), "hv60": _to_float(first["hv60"]), "hv90": _to_float(first["hv90"]),
    }])
    metadata = ChainMetadata(valuation_date, spot, multiplier, dte, rate)
    return ChainAnalysis(metadata, metrics, options, strike_gex, curve)


def analyze_option_chain(csv_path: Path, shibor_path: Path) -> ChainAnalysis:
    """Load a chain CSV and compute core 1c metrics (file entry point)."""
    return analyze_option_chain_frame(pd.read_csv(csv_path), shibor_path)
