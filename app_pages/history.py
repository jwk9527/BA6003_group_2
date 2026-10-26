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
from project_option_chain.i18n import get_lang, t  # noqa: E402
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


def h(key: str) -> str:
    """Metric definition (tooltip) in the current UI language."""
    return H.help_text(key, get_lang())


def show(fig, key: str, height: int, dates: bool = False) -> None:
    show_figure(st, fig, key, height, dates)


CSS = """
<style>
section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebar"] > div > div { padding-top: 1.2rem; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 1.1rem; }
[data-testid="stMetric"] { padding: 0.6rem 0.9rem; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
                           background: rgba(255,255,255,0.02); }
.main .block-container, [data-testid="stMainBlockContainer"] { padding-top: 2.2rem; padding-bottom: 4rem; }
h2 { margin-top: 1.6rem !important; }
</style>
"""
CARDS_PER_ROW = 4


def spacer(px: int = 18) -> None:
    st.markdown(f"<div style='height:{px}px'></div>", unsafe_allow_html=True)


def card_grid(cards) -> None:
    for i in range(0, len(cards), CARDS_PER_ROW):
        cols = st.columns(CARDS_PER_ROW, gap="medium")
        for c, (label, value, h) in zip(cols, cards[i:i + CARDS_PER_ROW]):
            c.metric(label, value, help=h)
        spacer(6)


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(t("ETF Option History: GEX & Volatility"))
    etfs = available_etfs()
    if not etfs:
        st.error(t("No history data found under {root}/<ETF>/matrix.parquet — build it with "
                   "scripts/build_history.py (see README) or set ETF_HIST_DATA.", root=DATA_ROOT))
        st.stop()
    st.sidebar.header(t("History"))
    st.sidebar.subheader(t("Underlying"))
    code = st.sidebar.selectbox("ETF", etfs, format_func=lambda c: f"{c} · {t(NAMES.get(c, c))}", key="hist_etf")
    path = DATA_ROOT / code / "matrix.parquet"
    try:
        matrix = load_matrix(code, path.stat().st_mtime)
    except Exception as exc:
        st.error(t("Could not read matrix for {code}: {exc}", code=code, exc=exc))
        st.stop()
    gex_file = gex_path(code)
    gex_mtime = gex_file.stat().st_mtime if gex_file.is_file() else 0.0
    front = matrix[matrix["is_front"]].set_index("date")
    dates = list(front.index)
    # bottom of the sidebar: VIX setting + data coverage
    st.sidebar.divider()
    st.sidebar.subheader(t("VIX settings"))
    roll = st.sidebar.toggle(t(ROLL_LABEL), value=False, key="hist_vix_roll",
                             help=t("VIX (30-day) normally uses the two nearest expiries. When on, a near expiry with "
                                    "fewer than 7 calendar days left is skipped and the next two expiries are used. "
                                    "Affects the VIX card, VRP30 and the VIX chart."))
    st.sidebar.divider()
    st.sidebar.caption(t("Data {a} — {b} · {n} trading days", a=f"{dates[0]:%Y-%m-%d}", b=f"{dates[-1]:%Y-%m-%d}",
                         n=len(dates)))
    vix = load_vix(code, path.stat().st_mtime, roll)
    vix_help = h("vix") + (h("vix_roll") if roll else "")

    # ================= Module 1: single day =================
    st.header(t("① Single-day view"), divider="gray")
    sel = pd.Timestamp(st.date_input(t("Date"), value=dates[-1], min_value=dates[0], max_value=dates[-1],
                                     key="hist_day", help=t("Data exists for trading days only; a non-trading day falls back to the previous trading day.")))
    pos = int(np.searchsorted(np.array(dates, dtype="datetime64[ns]"), np.datetime64(sel), side="right")) - 1
    day = dates[max(pos, 0)]
    if day != sel:
        st.caption(t("{a} is not a trading day; showing {b}.", a=f"{sel:%Y-%m-%d}", b=f"{day:%Y-%m-%d}"))
    row = front.loc[day]
    month = int(row["month"])
    vrow = vix.set_index("date").loc[day]
    st.subheader(t("Main contract (is_front) {m} · {d}", m=month_label(month), d=f"{day:%Y-%m-%d}"),
                 help=t("Main contract = the expiry month flagged is_front=True in matrix (the month with the fewest days to expiry on that date)."))
    cards = [
        (t("Spot"), fmt(row["ETF_close"]), h("spot")),
        (t("Net GEX (M CNY)"), fmt(row["net_gex_million"], ".2f"), h("net_gex")),
        (t("Zero gamma"), fmt(row["zero_gamma"]), h("zero_gamma")),
        (t("Call wall"), fmt(row["call_wall"]), h("call_wall")),
        (t("Put wall"), fmt(row["put_wall"]), h("put_wall")),
        (t("Max pain"), fmt(row["max_pain"]), h("max_pain")),
        (t("ATM IV"), fmt(row["atm_iv"] * 100, ".2f", "%"), h("atm_iv")),
        (t("25Δ skew"), fmt(row["call25_put25_iv_skew"] * 100, "+.2f"), h("skew")),
        ("HV30", fmt(row["hv30"], ".2f", "%"), h("hv30")),
        (t("VIX (30-day)"), fmt(vrow["vix30"], ".2f"), vix_help + t(" Method on this date: {m}.", m=vrow['vix_method'])),
        ("VRP30", fmt(vrow["vrp30_calc"], "+.2f"), h("vrp")),
        (t("Days to expiry"), fmt(row["days_to_expiry"], ".0f"), h("dte")),
    ]
    with st.container(border=True):
        card_grid(cards)
    spacer()

    # --- volatility smile
    month_dates = list(matrix.loc[matrix["month"] == month, "date"])
    k = month_dates.index(day)
    c1, c2 = st.columns([3, 1], gap="large", vertical_alignment="bottom")
    c1.subheader(t("Volatility smile"), help=t("Implied volatility by strike for the main contract on the selected date "
                                  "(contract detail; IV ≤ 0 not drawn). Left: calls, right: puts. Dashed lines: the same "
                                  "expiry month on the previous N trading days (same colour, thinner and fainter = earlier). Vertical lines: ETF close "
                                  "of each shown day, styled like that day's curve. Untick Overlay previous days to draw only the day N trading days back."))
    n_prev = c2.select_slider(t("Previous N trading days"), options=list(range(6)), value=0, key="hist_prev",
                              help=t("How many trading days back (same expiry month) the smile reaches."))
    overlay = c2.checkbox(t("Overlay previous days"), value=True, key="hist_overlay",
                          help=t("On: the selected day plus the previous N trading days are drawn together. "
                                 "Off: only the single day N trading days back is drawn, with that day's ETF close line."))
    smile_days = month_dates[max(0, k - n_prev):k + 1]          # loaded (also feeds the AI summary)
    plot_days = smile_days if overlay else [smile_days[0]]       # overlay off: only day N back
    smile_day = plot_days[-1]
    detail = None
    if not gex_file.is_file():
        st.info(t("No gex.parquet detail for this ETF; smile unavailable."))
    else:
        try:
            with st.spinner(t("Loading detail…")):
                detail = load_smiles(code, gex_mtime, month, tuple(smile_days))
            if detail[detail["date"] == smile_day].empty:
                st.warning(t("No contract detail in gex.parquet for {d} / {m}.", d=f"{smile_day:%Y-%m-%d}", m=month_label(month)))
            else:
                closes = matrix.drop_duplicates("date").set_index("date")["ETF_close"]
                spots = closes[closes.index.isin(plot_days)].to_dict()
                spot_sel = float(spots.get(smile_day, row["ETF_close"]))
                if not overlay and smile_day != day:
                    st.caption(t("Overlay off: showing only {d} ({n} trading day(s) before the selected date).",
                                 d=f"{smile_day:%Y-%m-%d}", n=n_prev))
                show(smile_figure(detail[detail["date"].isin(plot_days)], plot_days, spot_sel, spots), "hist_smile", 500)
        except Exception as exc:
            st.error(t("Could not read gex detail: {exc}", exc=exc))

    # --- main contract lifetime
    spacer()
    life = matrix[matrix["month"] == month]
    st.subheader(t("{m} contract lifetime: key levels", m=month_label(month)),
                 help=t("All trading days on which this expiry month exists in matrix. Top: ETF close, call wall, put wall, "
                      "max pain, zero gamma. Bottom: this month's net GEX (M CNY). Vertical line: selected date."))
    show(lifetime_figure(life, day), "hist_life", 580, dates=True)
    spacer(28)

    # ================= Module 2: date range =================
    st.header(t("② Date-range view"), divider="gray")
    c1, c2 = st.columns([2, 3], gap="large")
    default_start = max(dates[0], dates[-1] - pd.DateOffset(years=1))
    rng = c1.date_input(t("Date range"), value=(default_start, dates[-1]), min_value=dates[0], max_value=dates[-1],
                        key="hist_range")
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.info(t("Select a start and an end date."))
        st.stop()
    start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    in_range = matrix[(matrix["date"] >= start) & (matrix["date"] <= end)]
    mode = c2.radio(t("Contracts"), ["Main contract only (is_front)", "Choose expiry months"], horizontal=True,
                    key="hist_mode", format_func=t)
    picked = []
    if mode.startswith("Main"):
        sub = in_range[in_range["is_front"]]
    else:
        months = sorted(in_range["month"].unique())
        picked = c2.multiselect(t("Expiry months"), months, default=months[-3:], format_func=month_label, key="hist_months")
        sub = in_range[in_range["month"].isin(picked)]
    if sub.empty:
        st.info(t("No data for the selected range / months."))
        st.stop()
    price = in_range[in_range["is_front"]][["date", "ETF_close"]]

    st.subheader(t("ETF price & net GEX"), help=t("Top: ETF close. Bottom: net GEX (M CNY): with main contract only, a "
                                       "continuous series of each day's main month (switches month at expiry); with "
                                       "chosen months, one line per expiry month."))
    spacer()
    show(price_gex_figure(price, sub, by_month=not mode.startswith("Main")), "hist_price_gex", 580, dates=True)
    spacer()

    v = vix[(vix["date"] >= start) & (vix["date"] <= end)]
    st.subheader(t("VIX vs historical volatility"), help=t(
        "Top: VIX (30-day, CBOE method on settlement prices, see Metric definitions{roll}), HV30 (solid), "
        "HV60/HV90 (dashed). Bottom: VRP30 = VIX − HV30. All in %; not affected by the contract filter.",
        roll=t("; near month rolled at <7 DTE") if roll else ""))
    show(vol_figure(v), "hist_vol", 540, dates=True)
    spacer()

    with st.expander(t("Data preview & download")):
        drop = ["vix30", "vix_method", "vrp30"] if roll else ["vix30_roll7", "vix_method_roll7", "vrp30_roll7"]
        table = sub.drop(columns=drop).sort_values(["date", "days_to_expiry"])
        st.dataframe(table, hide_index=True, height=380)
        st.download_button(t("Download CSV"), table.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{code}_{start:%Y%m%d}_{end:%Y%m%d}.csv", mime="text/csv")

    render_ai_summary(code, day, month, cards, detail, smile_days, row, life, start, end, mode, picked, sub, v)

    with st.expander(t("Metric definitions")):
        st.markdown("\n".join(t(line) for line in [
            "- **Main contract (is_front)**: the expiry month flagged `is_front=True` in matrix, i.e. the month with the fewest days to expiry (not selected by volume), held until expiry.",
            "- **Net GEX (M CNY)**: Σ gamma × OI × multiplier × spot² × 1%, calls +, puts −.",
            "- **Call wall / Put wall**: strike with the largest call / put open interest. **Max pain**: strike minimising total intrinsic value of open options at expiry.",
            t("- **Zero gamma**: ") + h("zero_gamma"),
            t("- **ATM IV**: ") + h("atm_iv"),
            "- **IV**: stored as a decimal, shown in %. **HV** and **VIX** are stored in %.",
            t("- **HV30/60/90**: ") + h("hv30_n"),
            t("- **VIX (30-day)**: ") + h("vix") + h("vix_roll") + t(" (toggle in the sidebar, default off)."),
            "- **VRP30**: VIX (30-day) − HV30.",
            "- **Risk-free rate**: Shibor (O/N … 1Y) linearly interpolated to each expiry's days to expiry.",
            "- All metrics use the same functions as the Live page.",
        ]))


def render_ai_summary(code, day, month, cards, detail, smile_days, row, life, start, end, mode, picked, sub, v):
    """Optional LLM summary of exactly what is on screen (History page only)."""
    st.header(t("AI summary"), divider="gray")
    lang = get_lang()
    if not st.toggle(t("Summarize current view (AI)"), key="hist_ai_on",
                     help=t("Sends only the aggregated figures shown on this page (cards with their definitions, "
                          "smile statistics, contract-lifetime and date-range summaries; no raw contract detail) "
                          "to the configured LLM (app default via OpenRouter, or your own key), on request.")):
        return
    with st.expander(t("Use your own LLM API"), expanded=False):
        st.text_input(t("API key"), type="password", key="ai_user_key", placeholder="sk-…",
                      help=t("Any OpenAI-compatible API key. Kept only in this browser session (st.session_state); "
                             "never written to a file or log. Leave empty to use the app default key."))
        st.text_input(t("Model"), key="ai_user_model", placeholder=AI.DEFAULT_MODEL,
                      help=t("Model id at the chosen endpoint. Default: {m}.", m=AI.DEFAULT_MODEL))
        st.text_input("Base URL", key="ai_user_base", placeholder=AI.BASE_URL,
                      help=t("OpenAI-compatible endpoint. Default: {u}.", u=AI.BASE_URL))
        st.caption(t("Model and base URL apply only to your own key. Your key is not counted against the app usage cap."))
    cfg = AI.resolve_llm_config(st.session_state.get("ai_user_key", ""), st.session_state.get("ai_user_model", ""),
                                st.session_state.get("ai_user_base", ""))
    api_key = cfg["api_key"]
    if cfg["source"] == "user":
        st.caption(t("Using your key · model {m} · {u}", m=cfg['model'], u=cfg['base_url']))
    elif cfg["source"] == "default":
        st.caption(t("Using app default key · model {m}", m=cfg['model']))
    main_only = mode.startswith("Main")
    signature = (code, str(day.date()), len(smile_days), str(start.date()), str(end.date()),
                 "main" if main_only else ",".join(map(str, picked)), cfg["model"], cfg["base_url"], lang)
    store = st.session_state.setdefault("hist_ai_results", {})
    if not api_key:
        st.info(t("No API key available yet. Enter your own key under **Use your own LLM API** above, or add "
                  "`OPENROUTER_API_KEY=...` to the project's `.env` (or the app's Secrets on Streamlit Cloud) and restart."))
    remaining = AI.usage_remaining() if cfg["count_usage"] else 1
    if remaining <= 0:
        st.warning(t("App default key usage cap reached ({n} calls). Enter your own key to continue.", n=f"{AI.USAGE_CAP:,}"))
    clicked = st.button(t("Generate summary"), key="hist_ai_go", disabled=not api_key or remaining <= 0)
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
        with st.spinner(t("Asking {m}…", m=cfg['model'])):
            try:
                store[signature] = AI.generate_view_summary(
                    api_key, view_text, view_df, defs,
                    meta={"etf": code, "date": str(day.date()), "range": f"{start.date()}..{end.date()}",
                          "contracts": signature[5], "key_source": cfg["source"]},
                    model=cfg["model"], base_url=cfg["base_url"], count_usage=cfg["count_usage"], language=lang)
            except Exception as exc:
                msg = AI.friendly_error(exc, cfg["model"]).replace(api_key, "***")
                st.error(t("AI summary failed: {msg}", msg=msg))
    result = store.get(signature)
    if result:
        with st.container(border=True):
            st.markdown(result["text"])
            st.caption(t("AI-generated, based only on figures shown; not investment advice · model {m} · {time}",
                         m=result['model'], time=result['time']))
    elif api_key and not clicked:
        st.caption(t("Click **Generate summary** to summarise the current view (one API call per view)."))


main()
