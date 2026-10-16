"""ETF option history: data loading, 30-day VIX selection, history charts.

Data layout: ``<DATA_ROOT>/<ETF>/{matrix.parquet,gex.parquet}`` with
``DATA_ROOT`` = ``data/history`` (override with env var ``ETF_HIST_DATA``).
Both files are produced locally by ``scripts/build_history.py`` and committed;
every metric uses the same functions as the Live page.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .charts import CALL, CURVE, MAX_PAIN, MONTH_COLORS, PUT, SPOT, ZERO_G
from .config import HISTORY_DIR

DATA_ROOT = Path(os.environ.get("ETF_HIST_DATA", HISTORY_DIR))
NAMES = {"510050": "ChinaAMC SSE 50 ETF", "510300": "Huatai-PB CSI 300 ETF", "510500": "China Southern CSI 500 ETF",
         "588000": "ChinaAMC STAR 50 ETF", "588080": "E Fund STAR 50 ETF"}
ROLL_LABEL = "Roll near month at <7 DTE"


def fmt(v, spec=".3f", suffix=""):
    return "—" if v is None or pd.isna(v) else f"{format(float(v), spec)}{suffix}"


def month_label(m) -> str:
    s = str(int(m)).zfill(4)
    return f"20{s[:2]}-{s[2:]}"


def _manifest() -> dict:
    try:
        return json.loads((DATA_ROOT / "data_integrity.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _check_file(path: Path) -> None:
    """Compare size/sha256 with ``data_integrity.json`` (raises only on mismatch)."""
    rel = f"{path.parent.name}/{path.name}"
    rec = next((r for r in _manifest().get("files", []) if r.get("path") == rel), None)
    if not rec:
        return
    if path.stat().st_size != rec["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != rec["sha256"]:
        raise ValueError(f"{rel}: file does not match the integrity manifest (truncated or modified).")


def available_etfs() -> list[str]:
    found = {p.parent.name for p in DATA_ROOT.glob("*/matrix.parquet") if not p.parent.name.startswith(".")}
    return [c for c in NAMES if c in found] + sorted(found - set(NAMES))


def load_matrix(code: str, mtime: float = 0.0) -> pd.DataFrame:
    """matrix.parquet for one ETF (``mtime`` is only a cache key for callers)."""
    path = DATA_ROOT / code / "matrix.parquet"
    _check_file(path)
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["month"] = df["month"].astype(int)
    df["is_front"] = df["is_front"].astype(bool)
    return df.drop_duplicates(["date", "month"]).sort_values(["date", "days_to_expiry"]).reset_index(drop=True)


def gex_path(code: str) -> Path:
    return DATA_ROOT / code / "gex.parquet"


def load_smiles(code: str, mtime: float, month: int, dates: tuple[pd.Timestamp, ...]) -> pd.DataFrame:
    """Contract rows for one expiry month and a few trading days (reads only those rows)."""
    df = pd.read_parquet(gex_path(code), filters=[("month", "==", int(month)), ("date", "in", list(dates))])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


def vix_30d(matrix: pd.DataFrame, roll: bool = False) -> pd.DataFrame:
    """One row per date: 30-day VIX (stored by the build), HV and VRP30.

    ``roll`` selects ``vix30_roll7`` (near month skipped when < 7 days to expiry)
    instead of ``vix30`` (always the two nearest expiries).
    """
    sfx = "_roll7" if roll else ""
    front = matrix.loc[matrix["is_front"]]
    out = front[["date", f"vix30{sfx}", f"vix_method{sfx}", "hv30", "hv60", "hv90"]].rename(
        columns={f"vix30{sfx}": "vix30", f"vix_method{sfx}": "vix_method"})
    out["vrp30_calc"] = out["vix30"] - out["hv30"]
    return out.sort_values("date").reset_index(drop=True)


HELP = {
    "spot": "ETF closing price on the selected date.",
    "net_gex": "Σ gamma × open interest × multiplier × spot² × 1%, calls +, puts −; "
               "million CNY per 1% move of the underlying (vendor gamma).",
    "zero_gamma": "Price where the aggregate GEX curve changes sign (crossing nearest to spot). Curve: Black-Scholes "
                  "gamma re-computed on a grid of simulated spot prices (step 0.005) with the fitted call/put IV "
                  "smiles, OI fixed, T = days/360, rate = Shibor at the expiry tenor; — if no crossing.",
    "call_wall": "Strike with the largest call open interest.",
    "put_wall": "Strike with the largest put open interest.",
    "max_pain": "Strike minimising the total intrinsic value of all open calls and puts at expiry.",
    "atm_iv": "Main contract, in %. At each strike take the mean of call and put IV (IV > 0); then weight the two "
              "strikes bracketing spot inversely to their distance from spot: IV = w·IV(K_lo) + (1−w)·IV(K_hi), "
              "w = (K_hi − S)/(K_hi − K_lo). Nearest strike's IV if spot is outside the strike range.",
    "skew": "IV of the call with delta ≈ +0.25 − IV of the put with delta ≈ −0.25, in vol points.",
    "hv30": "Annualised sample standard deviation of the underlying's daily log returns over the last 30 trading "
            "days (× √252), in %.",
    "vix": "30-day volatility index, CBOE method on daily settlement prices: per expiry "
           "σ² = (2/T) Σ ΔK/K² · e^{RT} · Q(K) − (1/T)(F/K0 − 1)², T = calendar days/365, R = Shibor at the tenor, "
           "F from put-call parity at min |C−P|, K0 = largest strike ≤ F, Q = OTM settlement price; the two "
           "nearest expiries are interpolated linearly in total variance to 30 days.",
    "vix_roll": " With 'Roll near month at <7 DTE' on, a near expiry with fewer than 7 calendar days left is skipped "
                "and the next two expiries are used.",
    "vrp": "VRP30 = VIX (30-day) − HV30, in vol points.",
    "dte": "Calendar days to expiry of the main contract (is_front).",
}


# ---------------------------------------------------------------------------
# Charts (styled by the shared template from charts.py)
# ---------------------------------------------------------------------------
def smile_figure(detail: pd.DataFrame, days: list[pd.Timestamp], spot: float) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=("Call IV", "Put IV"))
    sel = days[-1]
    for col, (kind, color) in enumerate((("C", CALL), ("P", PUT)), start=1):
        for i, d in enumerate(days):
            sub = detail[(detail["date"] == d) & (detail["option_type"] == kind) & (detail["iv"] > 0)]
            sub = sub.sort_values("strike")
            if sub.empty:
                continue
            age = len(days) - 1 - i  # 0 = selected day
            is_sel = d == sel
            fig.add_trace(go.Scatter(
                x=sub["strike"], y=sub["iv"] * 100, mode="lines+markers" if is_sel else "lines",
                name=f"{d:%m-%d}" + (" (selected)" if is_sel else f" (−{age}d)"),
                legendgroup=str(d.date()), showlegend=col == 1,
                line=dict(color=color, width=2.6 if is_sel else 1.4, dash="solid" if is_sel else "dash"),
                opacity=1.0 if is_sel else max(0.25, 0.8 - 0.12 * age),
                marker=dict(size=7),
                hovertemplate=f"{d:%Y-%m-%d}<br>K %{{x:.3f}} · IV %{{y:.2f}}%<extra></extra>"),
                row=1, col=col)
        fig.add_vline(x=spot, line=dict(color=SPOT, dash="dot", width=1.5), row=1, col=col,
                      annotation_text=f"Spot {spot:.3f}", annotation_position="top right",
                      annotation_font_color=SPOT)
        fig.update_xaxes(title_text="Strike price", row=1, col=col)
    fig.update_yaxes(title_text="Implied volatility (%)", row=1, col=1)
    fig.update_layout(hovermode="closest", legend=dict(y=1.1))
    return fig


def lifetime_figure(life: pd.DataFrame, sel: pd.Timestamp) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.05)
    for col, name, color, dash in (("ETF_close", "ETF close", SPOT, "solid"),
                                   ("call_wall", "Call wall", CALL, "dot"),
                                   ("put_wall", "Put wall", PUT, "dot"),
                                   ("max_pain", "Max pain", MAX_PAIN, "dash"),
                                   ("zero_gamma", "Zero gamma", ZERO_G, "dash")):
        fig.add_trace(go.Scatter(x=life["date"], y=life[col], name=name, mode="lines",
                                 line=dict(color=color, dash=dash, width=2.4 if col == "ETF_close" else 1.6),
                                 line_shape="hv" if col in ("call_wall", "put_wall", "max_pain") else "linear",
                                 hovertemplate=f"{name} %{{y:.3f}}<extra></extra>"), row=1, col=1)
    gex = life["net_gex_million"]
    fig.add_trace(go.Bar(x=life["date"], y=gex, name="Net GEX (M CNY)",
                         marker_color=np.where(gex >= 0, CALL, PUT), opacity=0.75,
                         hovertemplate="Net GEX %{y:.2f}M<extra></extra>"), row=2, col=1)
    for r in (1, 2):
        fig.add_vline(x=sel, line=dict(color=CURVE, width=1, dash="dot"), row=r, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Net GEX (M CNY)", row=2, col=1)
    return fig


def price_gex_figure(price: pd.DataFrame, gex: pd.DataFrame, by_month: bool) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.05)
    fig.add_trace(go.Scatter(x=price["date"], y=price["ETF_close"], name="ETF close", mode="lines",
                             line=dict(color=CURVE, width=1.8),
                             hovertemplate="Close %{y:.3f}<extra></extra>"), row=1, col=1)
    if by_month:
        for i, (m, g) in enumerate(gex.groupby("month")):
            fig.add_trace(go.Scatter(x=g["date"], y=g["net_gex_million"], name=month_label(m), mode="lines",
                                     line=dict(color=MONTH_COLORS[i % len(MONTH_COLORS)], width=1.6),
                                     hovertemplate=month_label(m) + " %{y:.2f}<extra></extra>"), row=2, col=1)
    else:
        v = gex["net_gex_million"]
        fig.add_trace(go.Bar(x=gex["date"], y=v, name="Main contract net GEX", marker_color=np.where(v >= 0, CALL, PUT),
                             marker_line_width=0, hovertemplate="Net GEX %{y:.2f}M<extra></extra>"), row=2, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Net GEX (M CNY)", row=2, col=1)
    fig.update_layout(bargap=0)
    return fig


def vol_figure(v: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Scatter(x=v["date"], y=v["vix30"], name="VIX (30-day)", mode="lines",
                             line=dict(color=ZERO_G, width=2), hovertemplate="VIX %{y:.2f}<extra></extra>"), row=1, col=1)
    for col, name, color, dash, width in (("hv30", "HV30", SPOT, "solid", 1.8),
                                          ("hv60", "HV60", "#90a4ae", "dash", 1.1),
                                          ("hv90", "HV90", "#607d8b", "dash", 1.1)):
        fig.add_trace(go.Scatter(x=v["date"], y=v[col], name=name, mode="lines",
                                 line=dict(color=color, dash=dash, width=width),
                                 hovertemplate=f"{name} %{{y:.2f}}<extra></extra>"), row=1, col=1)
    r = v["vrp30_calc"]
    fig.add_trace(go.Bar(x=v["date"], y=r, name="VRP30", marker_color=np.where(r >= 0, CALL, PUT),
                         marker_line_width=0, hovertemplate="VRP30 %{y:.2f}<extra></extra>"), row=2, col=1)
    fig.update_yaxes(title_text="Volatility (%)", row=1, col=1)
    fig.update_yaxes(title_text="VRP30", row=2, col=1)
    fig.update_layout(bargap=0)
    return fig
