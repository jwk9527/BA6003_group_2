"""Page 2 ("History"): ETF option history — GEX & volatility. Logic lives in
``project_option_chain.history``; this file is UI only."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from project_option_chain import ai_summary as AI  # noqa: E402
from project_option_chain import history as H  # noqa: E402
from project_option_chain.charts import show_figure  # noqa: E402
from project_option_chain.history import (  # noqa: E402
    DATA_ROOT, HELP, NAMES, ROLL_LABEL, available_etfs, fmt, gex_path, lifetime_figure, month_label,
    price_gex_figure, smile_figure, vix_30d, vol_figure,
)


@st.cache_data(show_spinner=False, max_entries=8)
def load_matrix(code: str, mtime: float) -> pd.DataFrame:
    return H.load_matrix(code, mtime)


@st.cache_data(show_spinner=False, max_entries=8)
def load_vix(code: str, mtime: float, roll: bool) -> pd.DataFrame:
    return vix_30d(H.load_matrix(code, mtime), roll)


@st.cache_data(show_spinner=False, max_entries=64)
def load_smiles(code: str, mtime: float, month: int, dates: tuple) -> pd.DataFrame:
    return H.load_smiles(code, mtime, month, dates)


def show(fig, key: str, height: int, dates: bool = False) -> None:
    show_figure(st, fig, key, height, dates)


def main() -> None:
    st.title("ETF Option History: GEX & Volatility")
    etfs = available_etfs()
    if not etfs:
        st.error(f"No history data found under {DATA_ROOT}/<ETF>/matrix.parquet — build it with "
                 "scripts/build_history.py (see README) or set ETF_HIST_DATA.")
        st.stop()
    code = st.sidebar.selectbox("ETF", etfs, format_func=lambda c: f"{c} · {NAMES.get(c, c)}", key="hist_etf")
    path = DATA_ROOT / code / "matrix.parquet"
    try:
        matrix = load_matrix(code, path.stat().st_mtime)
    except Exception as exc:
        st.error(f"Could not read matrix for {code}: {exc}")
        st.stop()
    gex_file = gex_path(code)
    gex_mtime = gex_file.stat().st_mtime if gex_file.is_file() else 0.0
    roll = st.sidebar.toggle(ROLL_LABEL, value=False, key="hist_vix_roll",
                             help="VIX (30-day) normally uses the two nearest expiries. When on, a near expiry with "
                                  "fewer than 7 calendar days left is skipped and the next two expiries are used. "
                                  "Affects the VIX card, VRP30 and the VIX chart.")
    vix = load_vix(code, path.stat().st_mtime, roll)
    vix_help = HELP["vix"] + (HELP["vix_roll"] if roll else "")
    front = matrix[matrix["is_front"]].set_index("date")
    dates = list(front.index)
    st.sidebar.caption(f"Data {dates[0]:%Y-%m-%d} — {dates[-1]:%Y-%m-%d} · {len(dates)} trading days")

    # ================= Module 1: single day =================
    st.header("① Single-day view", divider="gray")
    sel = pd.Timestamp(st.date_input("Date", value=dates[-1], min_value=dates[0], max_value=dates[-1],
                                     key="hist_day", help="Data exists for trading days only; a non-trading day falls back to the previous trading day."))
    pos = int(np.searchsorted(np.array(dates, dtype="datetime64[ns]"), np.datetime64(sel), side="right")) - 1
    day = dates[max(pos, 0)]
    if day != sel:
        st.caption(f"{sel:%Y-%m-%d} is not a trading day; showing {day:%Y-%m-%d}.")
    row = front.loc[day]
    month = int(row["month"])
    vrow = vix.set_index("date").loc[day]
    st.subheader(f"Main contract (is_front) {month_label(month)} · {day:%Y-%m-%d}",
                 help="Main contract = the expiry month flagged is_front=True in matrix (the month with the fewest days to expiry on that date).")
    cards = [
        ("Spot", fmt(row["ETF_close"]), HELP["spot"]),
        ("Net GEX (M CNY)", fmt(row["net_gex_million"], ".2f"), HELP["net_gex"]),
        ("Zero gamma", fmt(row["zero_gamma"]), HELP["zero_gamma"]),
        ("Call wall", fmt(row["call_wall"]), HELP["call_wall"]),
        ("Put wall", fmt(row["put_wall"]), HELP["put_wall"]),
        ("Max pain", fmt(row["max_pain"]), HELP["max_pain"]),
        ("ATM IV", fmt(row["atm_iv"] * 100, ".2f", "%"), HELP["atm_iv"]),
        ("25Δ skew", fmt(row["call25_put25_iv_skew"] * 100, "+.2f"), HELP["skew"]),
        ("HV30", fmt(row["hv30"], ".2f", "%"), HELP["hv30"]),
        ("VIX (30-day)", fmt(vrow["vix30"], ".2f"), vix_help + f" Method on this date: {vrow['vix_method']}."),
        ("VRP30", fmt(vrow["vrp30_calc"], "+.2f"), HELP["vrp"]),
        ("Days to expiry", fmt(row["days_to_expiry"], ".0f"), HELP["dte"]),
    ]
    for i in range(0, len(cards), 6):
        for c, (label, value, h) in zip(st.columns(6), cards[i:i + 6]):
            c.metric(label, value, help=h)

    # --- volatility smile
    month_dates = list(matrix.loc[matrix["month"] == month, "date"])
    k = month_dates.index(day)
    c1, c2 = st.columns([3, 1])
    c1.subheader("Volatility smile", help="Implied volatility by strike for the main contract on the selected date "
                                  "(contract detail; IV ≤ 0 not drawn). Left: calls, right: puts. Dashed lines: the same "
                                  "expiry month on the previous N trading days (fainter = earlier). Dotted line: spot.")
    n_prev = c2.select_slider("Overlay previous N trading days", options=list(range(6)), value=0, key="hist_prev")
    smile_days = month_dates[max(0, k - n_prev):k + 1]
    detail = None
    if not gex_file.is_file():
        st.info("No gex.parquet detail for this ETF; smile unavailable.")
    else:
        try:
            with st.spinner("Loading detail…"):
                detail = load_smiles(code, gex_mtime, month, tuple(smile_days))
            if detail[detail["date"] == day].empty:
                st.warning(f"No contract detail in gex.parquet for {day:%Y-%m-%d} / {month_label(month)}.")
            else:
                show(smile_figure(detail, smile_days, float(row["ETF_close"])), "hist_smile", 430)
        except Exception as exc:
            st.error(f"Could not read gex detail: {exc}")

    # --- main contract lifetime
    life = matrix[matrix["month"] == month]
    st.subheader(f"{month_label(month)} contract lifetime: key levels",
                 help="All trading days on which this expiry month exists in matrix. Top: ETF close, call wall, put wall, "
                      "max pain, zero gamma. Bottom: this month's net GEX (M CNY). Vertical line: selected date.")
    show(lifetime_figure(life, day), "hist_life", 520, dates=True)

    # ================= Module 2: date range =================
    st.header("② Date-range view", divider="gray")
    c1, c2 = st.columns([2, 3])
    default_start = max(dates[0], dates[-1] - pd.DateOffset(years=1))
    rng = c1.date_input("Date range", value=(default_start, dates[-1]), min_value=dates[0], max_value=dates[-1],
                        key="hist_range")
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.info("Select a start and an end date.")
        st.stop()
    start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    in_range = matrix[(matrix["date"] >= start) & (matrix["date"] <= end)]
    mode = c2.radio("Contracts", ["Main contract only (is_front)", "Choose expiry months"], horizontal=True, key="hist_mode")
    picked = []
    if mode.startswith("Main"):
        sub = in_range[in_range["is_front"]]
    else:
        months = sorted(in_range["month"].unique())
        picked = c2.multiselect("Expiry months", months, default=months[-3:], format_func=month_label, key="hist_months")
        sub = in_range[in_range["month"].isin(picked)]
    if sub.empty:
        st.info("No data for the selected range / months.")
        st.stop()
    price = in_range[in_range["is_front"]][["date", "ETF_close"]]

    st.subheader("ETF price & net GEX", help="Top: ETF close. Bottom: net GEX (M CNY): with main contract only, a "
                                       "continuous series of each day's main month (switches month at expiry); with "
                                       "chosen months, one line per expiry month.")
    show(price_gex_figure(price, sub, by_month=not mode.startswith("Main")), "hist_price_gex", 520, dates=True)

    v = vix[(vix["date"] >= start) & (vix["date"] <= end)]
    st.subheader("VIX vs historical volatility", help="Top: VIX (30-day, CBOE method on settlement prices, see "
                                     "Metric definitions" + ("; near month rolled at <7 DTE" if roll else "") +
                                     "), HV30 (solid), HV60/HV90 (dashed). Bottom: VRP30 = VIX − HV30. "
                                     "All in %; not affected by the contract filter.")
    show(vol_figure(v), "hist_vol", 480, dates=True)

    with st.expander("Data preview & download"):
        drop = ["vix30", "vix_method", "vrp30"] if roll else ["vix30_roll7", "vix_method_roll7", "vrp30_roll7"]
        table = sub.drop(columns=drop).sort_values(["date", "days_to_expiry"])
        st.dataframe(table, hide_index=True, height=300)
        st.download_button("Download CSV", table.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{code}_{start:%Y%m%d}_{end:%Y%m%d}.csv", mime="text/csv")

    render_ai_summary(code, day, month, cards, detail, smile_days, row, life, start, end, mode, picked, sub, v)

    with st.expander("Metric definitions"):
        st.markdown("\n".join([
            "- **Main contract (is_front)**: the expiry month flagged `is_front=True` in matrix, i.e. the month with the fewest days to expiry (not selected by volume), held until expiry.",
            "- **Net GEX (M CNY)**: Σ gamma × OI × multiplier × spot² × 1%, calls +, puts −.",
            "- **Call wall / Put wall**: strike with the largest call / put open interest. **Max pain**: strike minimising total intrinsic value of open options at expiry.",
            "- **Zero gamma**: " + HELP["zero_gamma"],
            "- **ATM IV**: " + HELP["atm_iv"],
            "- **IV**: stored as a decimal, shown in %. **HV** and **VIX** are stored in %.",
            "- **HV30/60/90**: " + HELP["hv30"].replace("30 trading", "N trading"),
            "- **VIX (30-day)**: " + HELP["vix"] + HELP["vix_roll"] + " (toggle in the sidebar, default off).",
            "- **VRP30**: VIX (30-day) − HV30.",
            "- **Risk-free rate**: Shibor (O/N … 1Y) linearly interpolated to each expiry's days to expiry.",
            "- All metrics use the same functions as the Live page.",
        ]))


def render_ai_summary(code, day, month, cards, detail, smile_days, row, life, start, end, mode, picked, sub, v):
    """Optional LLM summary of exactly what is on screen (History page only)."""
    st.header("AI summary", divider="gray")
    if not st.toggle("Summarize current view (AI)", key="hist_ai_on",
                     help="Sends only the aggregated figures shown on this page (cards with their definitions, "
                          "smile statistics, contract-lifetime and date-range summaries; no raw contract detail) "
                          f"to {AI.resolve_model()} via OpenRouter, on request."):
        return
    api_key = AI.load_api_key()
    main_only = mode.startswith("Main")
    signature = (code, str(day.date()), len(smile_days), str(start.date()), str(end.date()),
                 "main" if main_only else ",".join(map(str, picked)), AI.resolve_model())
    store = st.session_state.setdefault("hist_ai_results", {})
    if not api_key:
        st.info("No OpenRouter API key found. Add `OPENROUTER_API_KEY=...` to the `.env` file in the project "
                "root (see `.env.example`), or to the app's Secrets on Streamlit Cloud, and restart the app.")
    remaining = AI.usage_remaining()
    if remaining <= 0:
        st.warning(f"AI usage cap reached ({AI.USAGE_CAP:,} calls). The AI summary is disabled.")
    clicked = st.button("Generate summary", key="hist_ai_go", disabled=not api_key or remaining <= 0)
    if clicked:
        smile_lines = (AI.smile_stats(detail, day, float(row["ETF_close"]), len(smile_days) - 1)
                       if detail is not None else ["Smile: not available on screen."])
        months_desc = ("main contract only (is_front)" if main_only
                       else "expiry months " + ", ".join(month_label(m) for m in picked))
        defs, view_text, view_df = AI.build_view_context(
            code, day, month_label(month), cards, smile_lines, AI.lifetime_summary(life, day),
            start, end, months_desc, sub, v, main_only,
            extra_definitions=["Main contract (is_front): expiry month with the fewest days to expiry, held until expiry.",
                               "IV values in %; HV, VIX, VRP30 in vol points / %."])
        with st.spinner(f"Asking {AI.resolve_model()}…"):
            try:
                store[signature] = AI.generate_view_summary(
                    api_key, view_text, view_df, defs,
                    meta={"etf": code, "date": str(day.date()), "range": f"{start.date()}..{end.date()}",
                          "contracts": signature[5]})
            except Exception as exc:
                st.error(f"AI summary failed: {exc}")
    result = store.get(signature)
    if result:
        with st.container(border=True):
            st.markdown(result["text"])
            st.caption(f"AI-generated, based only on figures shown; not investment advice · "
                       f"model {result['model']} · {result['time']}")
    elif api_key and not clicked:
        st.caption("Click **Generate summary** to summarise the current view (one API call per view).")


main()
