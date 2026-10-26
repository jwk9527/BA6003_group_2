"""Page 1 ("Live"): realtime option-chain analytics from iFinD.

Enter an iFinD token, paste the front-month (and optionally next-month)
contract codes and save the archive once, then turn on Live refresh. A
background worker thread fetches the realtime chain on the chosen interval and
runs the analytics; the page only reads the latest result every few seconds,
so the UI never blocks on the network. Without a token nothing is fetched and
the page shows a usage guide (no sample or simulated data).

Page 1 ("Live") of the multipage app; run via:
    uv run streamlit run dashboard.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from project_option_chain.analytics import merge_exposure  # noqa: E402
from project_option_chain.archive import (  # noqa: E402
    build_archive_with_next,
    load_archive,
    parse_codes,
    save_archive,
)
from project_option_chain import session_log as SL  # noqa: E402
from project_option_chain.config import DATA_DIR, SHIBOR_PATH, archive_persist_mode  # noqa: E402
from project_option_chain.charts import (  # noqa: E402
    gamma_exposure_figure,
    intraday_figure,
    volatility_smile_figure,
)
from project_option_chain.live_worker import LiveState, LiveWorker  # noqa: E402
from project_option_chain.market_hours import market_status  # noqa: E402
from project_option_chain.i18n import get_lang, t  # noqa: E402
from project_option_chain.i18n_zh import GUIDE_ZH  # noqa: E402

ARCHIVE_DIR = DATA_DIR / "archives"
LIVE_DIR = DATA_DIR / "live"  # realtime snapshots (one CSV per underlying)
INTERVAL_SECONDS = {"10s": 10, "30s": 30, "60s": 60, "15 min": 900, "30 min": 1800, "60 min": 3600}
UI_POLL = "2s"  # how often the page re-reads the worker store (no network)
from project_option_chain.charts import PLOTLY_CONFIG  # noqa: E402

SPOT_OPTIONS = ["588000.SH", "510050.SH", "510300.SH", "510500.SH", "159915.SZ"]



def known_archives() -> list[str]:
    """Spot codes that already have a saved archive (built-ins first)."""
    codes = [p.stem for p in ARCHIVE_DIR.glob("*.json")]
    extra = sorted(set(codes) - set(SPOT_OPTIONS))
    return list(SPOT_OPTIONS) + extra


def fmt(value: object, spec: str = ".3f") -> str:
    """Format a metric value, tolerating NaN/None (shown as em-dash)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return format(value, spec)


def pct_from_spot(level: object, spot: float) -> str | None:
    """Delta label for a price level: (level − spot) / spot."""
    if level is None or (isinstance(level, float) and pd.isna(level)) or not spot:
        return None
    return t("{pct}% vs spot", pct=f"{(float(level) - spot) / spot * 100:+.2f}")


def metric_row(cards: list[tuple[str, str, str | None, str]], per_row: int = 6) -> None:
    """cards = (label, value, delta or None, help). Deltas are coloured neutrally."""
    for i in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for col, (label, value, delta, help_text) in zip(cols, cards[i:i + per_row]):
            col.metric(label, value, delta, delta_color="off", help=help_text)


def render_module_chain(analysis, key_prefix: str, next_chain: pd.DataFrame | None = None) -> None:
    st.header(t("① Option chain: open interest & gamma exposure"), divider="gray")
    has_next = next_chain is not None and not next_chain.empty
    include_next = st.toggle(
        t("Include next month"), key=f"{key_prefix}_include_next", disabled=not has_next,
        help=t("Merge next-month contracts into module ① only (OI/GEX by strike, aggregate GEX curve, "
               "zero gamma, walls, max pain, net GEX). Modules ② and ③ are unaffected.")
        if has_next else
        t("No next-month data: available in Live mode when the archive has next-month codes."),
    )
    scope = t("front month")
    if include_next and has_next:
        try:
            analysis = merge_exposure(analysis, next_chain, SHIBOR_PATH)
            exp = sorted(next_chain["expiry"].dropna().unique()) if "expiry" in next_chain else []
            scope = t("front + next month") + (f" ({exp[0]})" if exp else "")
        except Exception as exc:
            st.error(t("Could not merge next month: {exc}", exc=exc))
    elif not has_next:
        st.caption(t("Next-month merge unavailable: no next-month contracts in the current data "
                     "(Live mode with next-month codes saved in the archive)."))
    m = analysis.metrics.iloc[0]
    spot = float(m["spot"])
    sfx = t(" [Computed on: {scope}.]", scope=scope)
    cards = [
        (t("Spot"), fmt(m["spot"]), None,
         t("Latest price of the underlying ETF used for all calculations.")),
        (t("Net GEX (M CNY)"), fmt(m["net_gex_million"], ".2f"), None,
         t("Σ over contracts of gamma × OI × multiplier × spot² × 1% , calls +, puts −; "
           "in million CNY per 1% spot move.")),
        (t("Zero gamma"), fmt(m["zero_gamma"]), pct_from_spot(m["zero_gamma"], spot),
         t("Price where the simulated aggregate GEX curve changes sign (nearest crossing to spot). "
           "Curve: re-price gamma at simulated spots with the fitted IV smile, OI fixed. "
           "— if no crossing in the simulated range.")),
        (t("Call wall"), fmt(m["call_wall"]), pct_from_spot(m["call_wall"], spot),
         t("Strike with the largest call open interest.")),
        (t("Put wall"), fmt(m["put_wall"]), pct_from_spot(m["put_wall"], spot),
         t("Strike with the largest put open interest.")),
        (t("Max pain"), fmt(m["max_pain"]), pct_from_spot(m["max_pain"], spot),
         t("Strike minimising total intrinsic value of all open calls and puts at expiry "
           "(Σ OI × payoff evaluated at each strike).")),
    ]
    metric_row([(lbl, val, dlt, hlp if i == 0 else hlp + sfx) for i, (lbl, val, dlt, hlp) in enumerate(cards)])
    st.caption(t("Expiry in {n} calendar days · risk-free (Shibor, tenor-interpolated) {r}%",
                 n=int(m['days_to_expiry']), r=f"{m['risk_free_rate'] * 100:.3f}"))
    st.subheader(t("Open interest and GEX by strike · {scope}", scope=scope), help=t(
        "Top: call and put open interest per strike, with call wall, put wall, max pain and spot markers. "
        "Bottom: bars = GEX per strike (gamma × OI × multiplier × spot² × 1%, calls +, puts −; right axis); "
        "line = aggregate GEX curve re-computed at simulated spot prices (left axis); "
        "vertical lines = zero gamma and spot. With 'Include next month' on, OI and GEX are summed over both "
        "expiries at each strike and the curve sums each expiry's contribution using its own smile fit, "
        "time to expiry and Shibor rate."))
    st.plotly_chart(gamma_exposure_figure(analysis), width="stretch",
                    key=f"{key_prefix}_gex", config=PLOTLY_CONFIG)


def render_module_iv(analysis, key_prefix: str) -> None:
    m = analysis.metrics.iloc[0]
    st.header(t("② Implied volatility"), divider="gray")
    atm_iv = m["atm_iv"]
    hv30 = m["hv30"]
    spread = None if atm_iv is None or hv30 is None or pd.isna(hv30) else float(atm_iv) * 100 - float(hv30)
    hv_help = t("Historical (realised) volatility of the underlying over the last {n} trading days, "
                "annualised, in vol points (from iFinD).")
    metric_row([
        (t("ATM IV"), fmt(None if atm_iv is None else float(atm_iv) * 100, ".2f"), None,
         t("Front month, vol points. At each strike take the mean of call and put IV; then weight the two "
         "strikes bracketing spot inversely to their distance from spot: "
         "IV = w·IV(K_lo) + (1−w)·IV(K_hi), w = (K_hi − S)/(K_hi − K_lo). "
         "If spot is outside the strike range, the nearest strike's IV is used.")),
        (t("ATM strike"), fmt(m["atm_strike"]), None,
         t("Listed strike nearest to spot (reference only; ATM IV interpolates between the two bracketing strikes).")),
        (t("25Δ skew"), fmt(m["call25_put25_iv_skew"] * 100, "+.2f"), None,
         t("IV(call with delta closest to +0.25) − IV(put with delta closest to −0.25), in vol points.")),
        (t("25Δ IV ratio"), fmt(m["call25_put25_iv_ratio"], ".3f"), None,
         t("IV(25-delta call) ÷ IV(25-delta put).")),
        (t("25Δ strike gap"), fmt(m["put25_minus_call25_strike"], "+.3f"), None,
         t("Strike of the 25-delta put − strike of the 25-delta call.")),
        (t("ATM IV − HV30"), fmt(spread, "+.2f"), None,
         t("ATM IV (vol points) minus 30-day historical volatility (vol points).")),
        ("HV30", fmt(m["hv30"], ".2f"), None, hv_help.format(n=30)),
        ("HV60", fmt(m["hv60"], ".2f"), None, hv_help.format(n=60)),
        ("HV90", fmt(m["hv90"], ".2f"), None, hv_help.format(n=90)),
    ])
    st.subheader(t("Volatility smile"), help=t(
        "Market implied volatility of each listed call (left) and put (right) against strike. "
        "Dashed lines: CubicSpline fitted separately to calls and puts in moneyness K/S "
        "(the same fit used to build the aggregate GEX curve). Dotted line: spot (ATM)."))
    st.plotly_chart(volatility_smile_figure(analysis), width="stretch",
                    key=f"{key_prefix}_smile", config=PLOTLY_CONFIG)


VIX_HELP = ("σ² = (2/T) Σ ΔK/K² · e^{RT} · Q(K) − (1/T)(F/K0 − 1)², T = calendar days/365, "
            "Q = OTM option price (mid of bid/ask, else last), F from put-call parity at min |C−P|, "
            "K0 = largest strike ≤ F, R = Shibor at the expiry tenor.")


VRP_HELP = ("VRP30 = VIX (30-day, this module) − HV30 (iFinD 30-day historical volatility), in vol points. "
            "Definition only.")


def render_module_vix(vix, key_prefix: str, hv30=None) -> None:
    st.header(t("③ 30-day volatility index (VIX method)"), divider="gray")
    if vix is None or vix.near is None:
        st.info(t("VIX unavailable: {note}", note=vix.note if vix else t("no data")))
        return
    vix_help = t(VIX_HELP)

    def ev_cards(ev, tag):
        tg = t(tag)
        if ev is None:
            return [(t("{tag} expiry", tag=tg), "—", None, t("No contracts for this month in the archive.")),
                    (t("{tag} σ", tag=tg), "—", None, vix_help)]
        return [
            (t("{tag} expiry", tag=tg), ev.expiry, t("{n} days", n=ev.days),
             t("{tag}-month expiry date and calendar days to expiry.", tag=tg)),
            (t("{tag} σ", tag=tg), f"{ev.sigma * 100:.2f}", f"σ² = {ev.variance:.4f}",
             t("√σ² × 100 for the {tag}-month expiry. ", tag=tg.lower()) + vix_help),
            (t("{tag} forward", tag=tg), f"{ev.forward:.4f}", f"K0 {ev.k0:.3f}",
             t("F = K* + e^(RT)(C − P) at the strike K* with the smallest |C − P|; K0 = largest strike ≤ F.")),
        ]
    label = {"interpolated": t("VIX (30d, interpolated)"), "extrapolated": t("VIX (30d, extrapolated)"),
             "single-month": t("VIX (1-month approx.)")}.get(vix.method, "VIX")
    metric_row(ev_cards(vix.near, "Near") + ev_cards(vix.next, "Next") + [
        (label, fmt(vix.vix, ".2f"), None,
         t("100 × √{[T1σ1²·(N2−30)/(N2−N1) + T2σ2²·(30−N1)/(N2−N1)] × 365/30}, N = calendar days. "
         "With only one expiry: 100 × σ_near (no term interpolation). Near and next month are always the "
         "two nearest archived expiries (no roll).")),
        ("VRP30", fmt(None if vix.vix is None or hv30 is None or pd.isna(hv30) else float(vix.vix) - float(hv30), "+.2f"),
         None, t(VRP_HELP)),
        ("HV30", fmt(hv30, ".2f"), None, t("Historical (realised) volatility of the underlying over the last {n} "
                                           "trading days, annualised, in vol points (from iFinD).", n=30)),
    ], per_row=3)
    if vix.method != "interpolated":
        st.warning(t(vix.note))
    else:
        st.caption(t(vix.note))


def render_analysis(analysis, source_label: str, key_prefix: str, vix=None,
                    next_chain: pd.DataFrame | None = None) -> None:
    """Three modules top to bottom: ① chain / GEX, ② IV, ③ VIX."""
    row = analysis.metrics.iloc[0]
    st.caption(t("Data as of {d} · source: {src}", d=row['date'], src=source_label))
    render_module_chain(analysis, key_prefix, next_chain)
    render_module_iv(analysis, key_prefix)
    render_module_vix(vix, key_prefix, row["hv30"])
    with st.expander(t("Metrics & strike details")):
        st.dataframe(analysis.metrics)
        st.dataframe(analysis.strike_gex)
        st.dataframe(analysis.gex_curve)


BADGE = {
    "LIVE": ("#1b5e20", "#a5d6a7", "● LIVE"),
    "STALE": ("#5d1010", "#ef9a9a", "▲ STALE · showing last good live data"),
    "WAITING": ("#263238", "#b0bec5", "… WAITING for first snapshot"),
}


def source_badge(state: LiveState) -> None:
    bg, fg, text = BADGE.get(state.source, BADGE["WAITING"])
    text = t(text)
    age = ""
    if state.data_time is not None:
        secs = (pd.Timestamp.now() - state.data_time).total_seconds()
        age = t(" · data {time} ({secs}s ago)", time=f"{state.data_time:%H:%M:%S}", secs=f"{secs:.0f}")
    st.markdown(
        f"<div style='background:{bg};color:{fg};padding:8px 14px;border-radius:6px;"
        f"font-weight:600;font-size:1.05rem;border:1px solid {fg}55'>{text}"
        f"<span style='font-weight:400;opacity:.85'>{age}</span></div>",
        unsafe_allow_html=True,
    )
    if state.last_error:
        st.error(t("Last fetch failed at {time}: {err}", time=f"{state.last_attempt:%H:%M:%S}", err=state.last_error))


@st.cache_resource(max_entries=4)
def get_worker(spot: str, token_hash: str, interval_s: int, archive_key: str, _token: str,
               _archive: dict) -> LiveWorker:
    """One background worker per (spot, token, interval, archive); older ones are stopped."""
    reg = _worker_registry()
    for old in list(reg):
        old.stop()
        reg.remove(old)
    worker = LiveWorker(spot, _token, interval_s, _archive, SHIBOR_PATH, LIVE_DIR).start()
    reg.append(worker)
    return worker


@st.cache_resource
def _worker_registry() -> list[LiveWorker]:
    """Process-wide list of running workers (survives script reruns)."""
    return []


def stop_all_workers() -> None:
    reg = _worker_registry()
    for w in list(reg):
        w.stop()
        reg.remove(w)
    get_worker.clear()


def current_archive(spot: str) -> tuple[dict | None, str]:
    """(archive, source): session archive first, then data/archives/<spot>.json."""
    sess = st.session_state.setdefault("live_archives", {})
    if spot in sess:
        return sess[spot], t("session (not saved to disk)")
    path = ARCHIVE_DIR / f"{spot}.json"
    if path.is_file():
        try:
            return load_archive(path), t("file `data/archives/{name}`", name=path.name)
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(t("Saved archive could not be read: {exc}", exc=exc))
    return None, ""


def session_log_section(log: dict, key: str) -> None:
    """Session log table + downloads (data lives only in this browser session)."""
    st.header(t("Session log"), divider="gray")
    st.caption(t("One row per successful refresh while Live is on. Kept only in this browser session "
                 "(memory, not saved on the server); cleared when the page is reloaded or the tab is closed. "
                 "Full-chain snapshots: last {n} kept", n=SL.MAX_SNAPSHOTS)
               + (t(" ({n} older snapshots dropped).", n=log['dropped_snapshots']) if log["dropped_snapshots"] else "."))
    if not log["rows"]:
        st.info(t("No refreshes logged yet."))
        return
    st.dataframe(SL.summary_frame(log).iloc[::-1], hide_index=True, height=260)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button(t("Download summary CSV"), SL.summary_csv(log), file_name=f"live_summary_{stamp}.csv",
                       mime="text/csv", key=f"{key}_dl_csv")
    c2.download_button(t("Download snapshots ZIP ({n} chains + summary)", n=len(log['snapshots'])), SL.snapshots_zip(log),
                       file_name=f"live_snapshots_{stamp}.zip", mime="application/zip", key=f"{key}_dl_zip")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
GUIDE = """
**How to use the Live page**

1. **iFinD token** – paste your iFinD (同花顺 iFinD HTTP API) access token in the sidebar.
   It is kept in this browser session only; it is never stored in the repo or written to logs.
2. **Underlying** – pick the ETF (e.g. `588000.SH`).
3. **Contract archive** – a built-in archive is used when available (as-of date and contract count are shown).
   To change contracts open **Update contract codes**, paste the iFinD codes of the **front-month** expiry
   (optionally the **next-month** codes, needed for the 30-day VIX interpolation and the next-month GEX view),
   pick a trading day and click **Save archive**.
4. **Refresh interval** – 10 s to 60 min, then turn on **Live refresh**. The page shows ① OI & GEX,
   ② implied volatility and ③ VIX/VRP, updated in the background, plus a downloadable **session log**.

Refreshing stops when Live is turned off or the browser tab is closed. If a fetch fails, the error is shown and
the last good snapshot (if any) is kept, marked **STALE**. Historical analytics are on the **History** page.
"""

persist = archive_persist_mode()
log = st.session_state.setdefault("live_log", SL.new_log())

st.sidebar.header(t("Live settings"))
token = st.sidebar.text_input(
    t("iFinD access token"),
    type="password",
    help=t("Entered here only; never stored in the repo or written to logs."),
).strip()
spot_code = st.sidebar.selectbox(t("Underlying ETF"), known_archives())

st.sidebar.divider()
st.sidebar.subheader(t("Contract archive"))
archive, archive_src = current_archive(spot_code)
if archive:
    n_next = len((archive.get("next") or {}).get("codes", {}))
    st.sidebar.caption(t("Source: {src}  \nAs of {d} · front {n} contracts", src=archive_src,
                         d=archive.get('as_of_date', '—'), n=len(archive.get('codes', {})))
                       + (t(" · next {exp} ({n})", exp=archive['next'].get('expiry', ''), n=n_next) if n_next
                          else t(" · no next month")))
else:
    st.sidebar.warning(t("No archive for this underlying yet — add contract codes below."))

with st.sidebar.expander(t("Update contract codes"), expanded=archive is None):
    codes_text = st.text_area(t("Front-month contract codes"), key="arch_front",
                              help=t("iFinD codes of the main (front-month) expiry, comma or newline separated."))
    next_codes_text = st.text_area(t("Next-month codes (optional, for VIX)"), key="arch_next",
                                   help=t("Codes of the next expiry; used by the 30-day VIX and the next-month GEX merge."))
    query_date = st.date_input(t("Archive query date"), value=date.today(), key="arch_date",
                               help=t("date_sequence only returns name/expiry data on trading days; on weekends or "
                                      "holidays pick the last trading day."))
    st.caption(t("Saving writes `data/archives/<spot>.json`.") if persist == "file" else
               t("Session-only: the archive is kept in this browser session (not written on the server). "
                 "Use **Download archive json** to keep a copy."))
    if st.button(t("Save archive"), key="arch_save", disabled=not (token and codes_text.strip()),
                 help=None if token else t("Requires the iFinD token.")):
        with st.spinner(t("Building archive via the daily endpoint...")):
            try:
                new = build_archive_with_next(
                    token, spot_code, parse_codes(codes_text),
                    parse_codes(next_codes_text) if next_codes_text.strip() else None, query_date.isoformat())
                if persist == "file":
                    save_archive(ARCHIVE_DIR / f"{spot_code}.json", new)
                    st.session_state["live_archives"].pop(spot_code, None)
                else:
                    st.session_state["live_archives"][spot_code] = new
                miss = new.get("missing", [])
                st.success(t("Archive saved ({mode}): {n} contracts", mode=persist, n=len(new['codes']))
                           + (t(", {n} codes skipped", n=len(miss)) if miss else ""))
                archive, archive_src = current_archive(spot_code)
            except Exception as exc:  # noqa: BLE001
                st.error(t("Archive failed: {exc}", exc=exc))
    if archive:
        st.download_button(t("Download archive json"), json.dumps(archive, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name=f"{spot_code}.json", mime="application/json", key="arch_dl")

st.sidebar.divider()
st.sidebar.subheader(t("Refresh"))
interval = st.sidebar.selectbox(
    t("Refresh interval"), list(INTERVAL_SECONDS), index=1, key="live_interval",
    help=t("How often the background worker fetches a new chain (10 s – 60 min). Refreshing stops when Live is "
           "turned off or when the browser tab is closed."))
can_live = bool(token) and archive is not None
live = st.sidebar.toggle(t("Live refresh"), value=False, disabled=not can_live, key="live_on",
                         help=None if can_live else t("Requires an iFinD token and a contract archive."))
live = live and can_live

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
st.title(t("Option-Chain Dashboard"))


@st.fragment(run_every="30s")
def market_status_notice() -> None:
    """A-share session state on the Asia/Shanghai clock (weekdays only; holidays not covered)."""
    ms = market_status()
    text = t("A-share market: **{state}** · {detail} · Shanghai time {now} · exchange holidays not covered",
             state=t(ms.state), detail=t(ms.detail), now=f"{ms.now:%a %Y-%m-%d %H:%M}")
    (st.success if ms.is_open else st.warning)(text, icon="🟢" if ms.is_open else "🌙")


market_status_notice()

if not live:
    stop_all_workers()  # live switched off -> no background fetching
    if not token:
        st.info(t("No live data: enter an iFinD access token in the sidebar to start."))
    elif archive is None:
        st.info(t("Add contract codes under **Update contract codes** in the sidebar, then turn on **Live refresh**."))
    else:
        st.info(t("Ready. Turn on **Live refresh** in the sidebar to start."))
    st.markdown(GUIDE_ZH if get_lang() == "zh" else GUIDE)
    if log["rows"]:
        session_log_section(log, "stopped")
else:
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    archive_key = hashlib.sha256(json.dumps(archive, sort_keys=True, default=str).encode()).hexdigest()[:16]
    try:
        worker = get_worker(spot_code, token_hash, INTERVAL_SECONDS[interval], archive_key, token, archive)
        if not worker.alive:  # thread died or was stopped by a newer one -> rebuild
            get_worker.clear()
            worker = get_worker(spot_code, token_hash, INTERVAL_SECONDS[interval], archive_key, token, archive)
    except Exception as exc:  # noqa: BLE001
        st.error(t("Could not start the live worker: {exc}", exc=exc))
        st.stop()

    with st.expander(t("Data pipeline status"), expanded=False):
        dsc, rqc = st.columns(2)
        with dsc:
            st.markdown(t("**DS · archive**"))
            missing = archive.get("missing", [])
            st.write(
                f"spot `{archive['spot_code']}` · as_of {archive.get('as_of_date', '—')}"
                f"\n\ncontracts {len(archive['codes'])}"
                + (f" · skipped {missing}" if missing else "")
                + f"\n\nmul {archive['mul']} · hv30 {archive['hv30']} · "
                  f"hv60 {archive['hv60']} · hv90 {archive['hv90']}"
            )
        with rqc:
            st.markdown(t("**RQ · background worker**"))
            st.write(t("iFinD realtime · every {interval}", interval=interval))
            if st.button(t("Fetch now")):
                worker.refresh_now()

    @st.fragment(run_every=UI_POLL)
    def live_view():
        state = worker.snapshot()  # in-memory read only, never touches the network
        SL.append(log, state)      # page-side handoff into session_state (thread-safe)
        source_badge(state)
        if state.fetch_seconds is not None:
            st.caption(t("Snapshots this session: {n} · last fetch+calc {s}s · UI polls every {poll}",
                         n=state.n_snapshots, s=f"{state.fetch_seconds:.2f}", poll=UI_POLL))
        if state.analysis is None:
            if state.last_error:
                st.warning(t("No live data yet. Check the token, the contract codes (archive) and network access "
                             "to the iFinD API; the worker keeps retrying on the refresh interval."))
            else:
                st.info(t("Waiting for the background worker's first snapshot…"))
        else:
            try:
                st.subheader(t("Intraday"))
                st.plotly_chart(intraday_figure(state.history), width="stretch",
                                key="live_intraday", config=PLOTLY_CONFIG)
                label = {"LIVE": t("realtime {code}", code=spot_code), "STALE": t("STALE realtime {code}", code=spot_code)}.get(
                    state.source, state.source)
                render_analysis(state.analysis, f"{label} @ {state.data_time:%H:%M:%S}", "live", state.vix,
                                next_chain=(state.full_chain[state.full_chain["month"] == "next"]
                                            if state.full_chain is not None and "month" in state.full_chain else None))
                chain_df = state.chain
                display_cols = ["thscode", "name", "option_type", "strike", "expiry",
                                "oi", "iv", "delta", "gamma"]
                with st.expander(t("Realtime option chain (RQ)")):
                    st.dataframe(chain_df[display_cols] if set(display_cols).issubset(chain_df.columns) else chain_df)
            except Exception as exc:  # noqa: BLE001 - never crash the page on a bad snapshot
                st.error(t("Could not render the live snapshot: {exc}", exc=f"{type(exc).__name__}: {exc}"))
        session_log_section(log, "live")

    live_view()
