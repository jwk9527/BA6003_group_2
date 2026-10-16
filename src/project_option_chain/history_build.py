"""History build library (run locally by ``scripts/build_history.py``).

Turns raw iFinD daily option exports into the two slim tables read by the
History page. Every metric is computed with the SAME functions as the Live
page (``analytics.analyze_option_chain_frame`` and ``vix.compute_vix``), so
History and Live share one definition:

* GEX / net GEX, walls, max pain, zero gamma, ATM IV (interpolated), 25Δ skew:
  ``analytics`` (rate = Shibor at the expiry tenor; τ = DTE/360 for the GEX curve).
* VIX (30-day): ``vix.compute_vix`` (CBOE method) on SETTLEMENT prices,
  T = DTE/365, rate = Shibor; stored without roll (``vix30``) and with a 7-day
  near-month roll (``vix30_roll7``).
* HV30/60/90: sample std of daily log returns × √252 × 100 (percent).

Output per ETF (``data/history/<ETF>/``):
* ``matrix.parquet`` — one row per (date, expiry month).
* ``gex.parquet``    — one row per contract per day, slim columns for the smile chart.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import analyze_option_chain_frame
from .config import DEFAULT_MULTIPLIER
from .vix import compute_vix

TRADING_DAYS_PER_YEAR = 252
ROLL_DAYS = 7
RAW_PATTERN = re.compile(r"期权行情历史.*_20\d{2}(前|后)\.csv$")
MONTH_PATTERN = re.compile(r"[CP](\d{4})")

# raw iFinD export column -> canonical column
COLUMN_MAP = {
    "交易日期": "date",
    "期权标的收盘价": "ETF_close",
    "持仓量(手)": "oi",
    "隐含波动率(%)": "iv_pct",
    "Delta": "delta",
    "Gamma": "gamma",
    "距到期日剩余天数": "DTE_n",
    "合约简称": "name",
    "认购(C)认沽(P)类型": "option_type",
    "行权价(元)": "strike",
    "到期日": "expiry",
    "结算价(元)": "settle",
}
MULTIPLIER_COLUMNS = ("合约单位", "合约乘数")  # used when the export has one

GEX_SLIM_COLUMNS = ["date", "month", "option_type", "strike", "iv", "oi", "ETF_close"]
MATRIX_COLUMNS = [
    "date", "month", "days_to_expiry", "ETF_close", "rate", "multiplier", "contracts",
    "net_gex_million", "call_wall", "put_wall", "max_pain", "zero_gamma",
    "atm_iv", "atm_strike", "call25_put25_iv_skew", "call25_put25_iv_ratio",
    "hv30", "hv60", "hv90",
    "vix30", "vix_method", "vix30_roll7", "vix_method_roll7", "vrp30", "vrp30_roll7",
    "vix_pctile", "is_front",
]


def read_csv_any(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: unrecognised encoding (tried UTF-8 / GB18030)")


def load_raw(path: Path) -> pd.DataFrame:
    """Read one raw iFinD export and map it to canonical columns."""
    df = read_csv_any(path)
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    out = df.rename(columns=COLUMN_MAP)
    for c in ("oi", "delta", "gamma", "strike", "ETF_close", "settle", "DTE_n"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["iv"] = pd.to_numeric(out["iv_pct"], errors="coerce") / 100.0
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    mul_col = next((c for c in MULTIPLIER_COLUMNS if c in df.columns), None)
    out["mul"] = pd.to_numeric(out[mul_col], errors="coerce").fillna(DEFAULT_MULTIPLIER) if mul_col else DEFAULT_MULTIPLIER
    out["month"] = out["合约交易代码"].astype(str).map(
        lambda code: (int(m.group(1)) if (m := MONTH_PATTERN.search(code)) else None))
    out["option_type"] = out["option_type"].astype(str).str.strip().str.upper().map(
        {"C": "C", "P": "P", "购": "C", "沽": "P"})
    if out["option_type"].isna().any():
        raise ValueError(f"{path.name}: unrecognised call/put flag")
    keep = ["合约代码", "date", "month", "name", "option_type", "strike", "expiry", "DTE_n",
            "ETF_close", "oi", "iv", "delta", "gamma", "settle", "mul"]
    return out[keep]


def load_symbol(dir_path: Path) -> pd.DataFrame:
    """Merge every raw export of one ETF (dedupe on date + contract code)."""
    files = sorted(f for f in dir_path.glob("*.csv") if RAW_PATTERN.match(f.name))
    if not files:
        raise FileNotFoundError(f"no raw exports in {dir_path}")
    df = pd.concat([load_raw(f) for f in files], ignore_index=True)
    df = df.drop_duplicates(subset=["date", "合约代码"]).dropna(subset=["month"])
    df["month"] = df["month"].astype(int)
    return df.sort_values(["date", "month", "strike"]).reset_index(drop=True)


def compute_hv(df: pd.DataFrame, windows: tuple[int, ...] = (30, 60, 90)) -> pd.DataFrame:
    """Rolling HV of the underlying: sample std of daily log returns × √252 × 100."""
    spot = df[["date", "ETF_close"]].dropna().drop_duplicates("date").sort_values("date").set_index("date")["ETF_close"]
    log_ret = np.log(spot / spot.shift(1))
    hv = pd.DataFrame({f"hv{w}": log_ret.rolling(w).std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
                       for w in windows}).reset_index()
    return df.merge(hv, on="date", how="left")


def group_metrics(g: pd.DataFrame, shibor_path: Path) -> dict:
    """Live analytics on one (date, month) chain."""
    a = analyze_option_chain_frame(g, shibor_path)
    m = a.metrics.iloc[0]
    return {
        "days_to_expiry": int(m["days_to_expiry"]), "ETF_close": float(m["spot"]),
        "rate": float(m["risk_free_rate"]), "multiplier": float(a.metadata.multiplier), "contracts": len(g),
        **{k: m[k] for k in ("net_gex_million", "call_wall", "put_wall", "max_pain", "zero_gamma", "atm_iv",
                              "atm_strike", "call25_put25_iv_skew", "call25_put25_iv_ratio",
                              "hv30", "hv60", "hv90")},
    }


def daily_vix(day: pd.DataFrame, shibor_path: Path) -> dict:
    """30-day VIX from settlement prices for one date: no roll and 7-day roll."""
    chain = day.loc[day["DTE_n"] > 0, ["date", "DTE_n", "expiry", "option_type", "strike", "settle"]].copy()
    chain["is_call"] = (chain["option_type"] == "C").astype(int)
    chain["strike_price"] = chain["strike"]
    out = {}
    for suffix, roll in (("", 0), ("_roll7", ROLL_DAYS)):
        try:
            r = compute_vix(chain, shibor_path, roll_days=roll)
            out[f"vix30{suffix}"], out[f"vix_method{suffix}"] = r.vix, r.method
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop the build
            out[f"vix30{suffix}"], out[f"vix_method{suffix}"] = None, f"error: {exc}"
    return out


def build_tables(df: pd.DataFrame, shibor_path: Path, log=print) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw canonical rows of one ETF -> (matrix, gex_slim)."""
    df = compute_hv(df)
    vix_rows = []
    for d, day in df.groupby("date", sort=True):
        vix_rows.append({"date": d, **daily_vix(day.dropna(subset=["settle", "strike"]), shibor_path)})
    vix = pd.DataFrame(vix_rows)

    calc = df.dropna(subset=["oi", "iv", "delta", "gamma", "strike", "ETF_close"])
    calc = calc[calc["DTE_n"] > 0]
    if len(calc) < len(df):
        log(f"  dropped {len(df) - len(calc)} rows with missing fields or DTE ≤ 0 (mostly expiry days)")
    rows = []
    for (d, month), g in calc.groupby(["date", "month"], sort=True):
        try:
            rows.append({"date": d, "month": month, **group_metrics(g, shibor_path)})
        except Exception as exc:  # noqa: BLE001
            log(f"  [warn] {d:%Y-%m-%d} month {month}: {exc}")
    matrix = pd.DataFrame(rows).merge(vix, on="date", how="left")
    matrix["vrp30"] = matrix["vix30"] - matrix["hv30"]
    matrix["vrp30_roll7"] = matrix["vix30_roll7"] - matrix["hv30"]

    # main contract: fewest days to expiry on each date, held until expiry
    front_idx = matrix.groupby("date")["days_to_expiry"].idxmin()
    matrix["is_front"] = matrix.index.isin(front_idx)
    per_day = matrix.loc[front_idx, ["date", "vix30"]].sort_values("date").set_index("date")["vix30"]
    pct = per_day.expanding().apply(lambda x: float((x[~np.isnan(x)] <= x[-1]).mean() * 100) if not np.isnan(x[-1]) else np.nan,
                                    raw=True)
    matrix = matrix.merge(pct.rename("vix_pctile").reset_index(), on="date", how="left")
    matrix = matrix.sort_values(["date", "days_to_expiry"]).reset_index(drop=True)[MATRIX_COLUMNS]

    gex = calc[GEX_SLIM_COLUMNS].sort_values(["date", "month", "strike"]).reset_index(drop=True)
    return matrix, gex
