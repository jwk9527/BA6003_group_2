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
from project_option_chain.config import DATA_DIR, SHIBOR_PATH  # noqa: E402
from project_option_chain.charts import (  # noqa: E402
    gamma_exposure_figure,
    intraday_figure,
    volatility_smile_figure,
)
from project_option_chain.live_worker import LiveState, LiveWorker  # noqa: E402

ARCHIVE_DIR = DATA_DIR / "archives"
LIVE_DIR = DATA_DIR / "live"  # realtime snapshots (one CSV per underlying)
INTERVAL_SECONDS = {"60s": 60, "30s": 30, "10s": 10}
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
    return f"{(float(level) - spot) / spot * 100:+.2f}% vs spot"


def metric_row(cards: list[tuple[str, str, str | None, str]], per_row: int = 6) -> None:
    """cards = (label, value, delta or None, help). Deltas are coloured neutrally."""
    for i in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for col, (label, value, delta, help_text) in zip(cols, cards[i:i + per_row]):
            col.metric(label, value, delta, delta_color="off", help=help_text)


def render_module_chain(analysis, key_prefix: str, next_chain: pd.DataFrame | None = None) -> None:
    st.header("① Option chain: open interest & gamma exposure", divider="gray")
    has_next = next_chain is not None and not next_chain.empty
    include_next = st.toggle(
        "Include next month", key=f"{key_prefix}_include_next", disabled=not has_next,
        help=("Merge next-month contracts into module ① only (OI/GEX by strike, aggregate GEX curve, "
              "zero gamma, walls, max pain, net GEX). Modules ② and ③ are unaffected."
              if has_next else
              "No next-month data: available in Live mode when the archive has next-month codes."),
    )
    scope = "front month"
    if include_next and has_next:
        try:
            analysis = merge_exposure(analysis, next_chain, SHIBOR_PATH)
            exp = sorted(next_chain["expiry"].dropna().unique()) if "expiry" in next_chain else []
            scope = "front + next month" + (f" ({exp[0]})" if exp else "")
        except Exception as exc:
            st.error(f"Could not merge next month: {exc}")
    elif not has_next:
        st.caption("Next-month merge unavailable: no next-month contracts in the current data "
                   "(Live mode with next-month codes saved in the archive).")
    m = analysis.metrics.iloc[0]
    spot = float(m["spot"])
    sfx = f" [Computed on: {scope}.]"
    cards = [
        ("Spot", fmt(m["spot"]), None,
         "Latest price of the underlying ETF used for all calculations."),
        ("Net GEX (M CNY)", fmt(m["net_gex_million"], ".2f"), None,
         "Σ over contracts of gamma × OI × multiplier × spot² × 1% , calls +, puts −; "
         "in million CNY per 1% spot move."),
        ("Zero gamma", fmt(m["zero_gamma"]), pct_from_spot(m["zero_gamma"], spot),
         "Price where the simulated aggregate GEX curve changes sign (nearest crossing to spot). "
         "Curve: re-price gamma at simulated spots with the fitted IV smile, OI fixed. "
         "— if no crossing in the simulated range."),
        ("Call wall", fmt(m["call_wall"]), pct_from_spot(m["call_wall"], spot),
         "Strike with the largest call open interest."),
        ("Put wall", fmt(m["put_wall"]), pct_from_spot(m["put_wall"], spot),
         "Strike with the largest put open interest."),
        ("Max pain", fmt(m["max_pain"]), pct_from_spot(m["max_pain"], spot),
         "Strike minimising total intrinsic value of all open calls and puts at expiry "
         "(Σ OI × payoff evaluated at each strike)."),
    ]
    metric_row([(lbl, val, dlt, hlp if lbl == "Spot" else hlp + sfx) for lbl, val, dlt, hlp in cards])
    st.caption(f"Expiry in {int(m['days_to_expiry'])} calendar days · risk-free (Shibor, tenor-interpolated) "
               f"{m['risk_free_rate'] * 100:.3f}%")
    st.subheader(f"Open interest and GEX by strike · {scope}", help=(
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
    st.header("② Implied volatility", divider="gray")
    atm_iv = m["atm_iv"]
    hv30 = m["hv30"]
    spread = None if atm_iv is None or hv30 is None or pd.isna(hv30) else float(atm_iv) * 100 - float(hv30)
    hv_help = ("Historical (realised) volatility of the underlying over the last {n} trading days, "
               "annualised, in vol points (from iFinD).")
    metric_row([
        ("ATM IV", fmt(None if atm_iv is None else float(atm_iv) * 100, ".2f"), None,
         "Front month, vol points. At each strike take the mean of call and put IV; then weight the two "
         "strikes bracketing spot inversely to their distance from spot: "
         "IV = w·IV(K_lo) + (1−w)·IV(K_hi), w = (K_hi − S)/(K_hi − K_lo). "
         "If spot is outside the strike range, the nearest strike's IV is used."),
        ("ATM strike", fmt(m["atm_strike"]), None,
         "Listed strike nearest to spot (reference only; ATM IV interpolates between the two bracketing strikes)."),
        ("25Δ skew", fmt(m["call25_put25_iv_skew"] * 100, "+.2f"), None,
         "IV(call with delta closest to +0.25) − IV(put with delta closest to −0.25), in vol points."),
        ("25Δ IV ratio", fmt(m["call25_put25_iv_ratio"], ".3f"), None,
         "IV(25-delta call) ÷ IV(25-delta put)."),
        ("25Δ strike gap", fmt(m["put25_minus_call25_strike"], "+.3f"), None,
         "Strike of the 25-delta put − strike of the 25-delta call."),
        ("ATM IV − HV30", fmt(spread, "+.2f"), None,
         "ATM IV (vol points) minus 30-day historical volatility (vol points)."),
        ("HV30", fmt(m["hv30"], ".2f"), None, hv_help.format(n=30)),
        ("HV60", fmt(m["hv60"], ".2f"), None, hv_help.format(n=60)),
        ("HV90", fmt(m["hv90"], ".2f"), None, hv_help.format(n=90)),
    ])
    st.subheader("Volatility smile", help=(
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
    st.header("③ 30-day volatility index (VIX method)", divider="gray")
    if vix is None or vix.near is None:
        st.info(f"VIX unavailable: {vix.note if vix else 'no data'}")
        return
    def ev_cards(ev, tag):
        if ev is None:
            return [(f"{tag} expiry", "—", None, "No contracts for this month in the archive."),
                    (f"{tag} σ", "—", None, VIX_HELP)]
        return [
            (f"{tag} expiry", ev.expiry, f"{ev.days} days", f"{tag}-month expiry date and calendar days to expiry."),
            (f"{tag} σ", f"{ev.sigma * 100:.2f}", f"σ² = {ev.variance:.4f}",
             f"√σ² × 100 for the {tag.lower()}-month expiry. " + VIX_HELP),
            (f"{tag} forward", f"{ev.forward:.4f}", f"K0 {ev.k0:.3f}",
             "F = K* + e^{RT}(C − P) at the strike K* with the smallest |C − P|; K0 = largest strike ≤ F."),
        ]
    label = {"interpolated": "VIX (30d, interpolated)", "extrapolated": "VIX (30d, extrapolated)",
             "single-month": "VIX (1-month approx.)"}.get(vix.method, "VIX")
    metric_row(ev_cards(vix.near, "Near") + ev_cards(vix.next, "Next") + [
        (label, fmt(vix.vix, ".2f"), None,
         "100 × √{[T1σ1²·(N2−30)/(N2−N1) + T2σ2²·(30−N1)/(N2−N1)] × 365/30}, N = calendar days. "
         "With only one expiry: 100 × σ_near (no term interpolation). Near and next month are always the "
         "two nearest archived expiries (no roll)."),
        ("VRP30", fmt(None if vix.vix is None or hv30 is None or pd.isna(hv30) else float(vix.vix) - float(hv30), "+.2f"),
         None, VRP_HELP),
        ("HV30", fmt(hv30, ".2f"), None, "Historical (realised) volatility of the underlying over the last 30 "
         "trading days, annualised, in vol points (from iFinD)."),
    ], per_row=3)
    if vix.method != "interpolated":
        st.warning(vix.note)
    else:
        st.caption(vix.note)


def render_analysis(analysis, source_label: str, key_prefix: str, vix=None,
                    next_chain: pd.DataFrame | None = None) -> None:
    """Three modules top to bottom: ① chain / GEX, ② IV, ③ VIX."""
    row = analysis.metrics.iloc[0]
    st.caption(f"Data as of {row['date']} · source: {source_label}")
    render_module_chain(analysis, key_prefix, next_chain)
    render_module_iv(analysis, key_prefix)
    render_module_vix(vix, key_prefix, row["hv30"])
    with st.expander("Metrics & strike details"):
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
    age = ""
    if state.data_time is not None:
        secs = (pd.Timestamp.now() - state.data_time).total_seconds()
        age = f" · data {state.data_time:%H:%M:%S} ({secs:.0f}s ago)"
    st.markdown(
        f"<div style='background:{bg};color:{fg};padding:8px 14px;border-radius:6px;"
        f"font-weight:600;font-size:1.05rem;border:1px solid {fg}55'>{text}"
        f"<span style='font-weight:400;opacity:.85'>{age}</span></div>",
        unsafe_allow_html=True,
    )
    if state.last_error:
        st.error(f"Last fetch failed at {state.last_attempt:%H:%M:%S}: {state.last_error}")


@st.cache_resource(max_entries=4)
def get_worker(spot: str, token_hash: str, interval_s: int, _token: str) -> LiveWorker:
    """One background worker per (spot, token, interval); older ones are stopped."""
    reg = _worker_registry()
    for old in list(reg):
        old.stop()
        reg.remove(old)
    worker = LiveWorker(spot, _token, interval_s, ARCHIVE_DIR / f"{spot}.json", SHIBOR_PATH,
                        LIVE_DIR).start()
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


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
GUIDE = """
**How to use the Live page**

1. **iFinD token** – paste your iFinD (同花顺 iFinD HTTP API) access token in the sidebar.
   It is kept in this browser session only; it is never stored in the repo or written to logs.
2. **Underlying** – pick the ETF (e.g. `588000.SH`).
3. **Contract codes** – turn on **Live refresh**, then paste the iFinD contract codes of the
   **front-month** expiry (comma or newline separated). Optionally paste the **next-month** codes
   (needed for the 30-day VIX interpolation and the *Include next month* GEX view).
4. **Archive query date** – a trading day (on weekends/holidays pick the last trading day),
   then click **Save archive**. This fetches names, strikes, expiry, multiplier and HV once.
5. **Refresh interval** – 10 s to 60 s. The page then shows ① OI & GEX, ② implied volatility and
   ③ VIX/VRP, updating in the background.

Live data needs network access to the iFinD API. If a fetch fails, the error is shown and the
last good snapshot (if any) is kept, marked **STALE**. Historical analytics are on the **History** page.
"""

st.sidebar.header("Live settings")
token = st.sidebar.text_input(
    "iFinD access token",
    type="password",
    help="Entered here only; never stored in the repo or written to logs.",
).strip()
spot_code = st.sidebar.selectbox("Underlying ETF", known_archives())
interval = st.sidebar.selectbox("Refresh interval", ["60s", "30s", "10s"], index=1)
live = st.sidebar.toggle("Live refresh", value=False, disabled=not token,
                         help="Requires an iFinD token." if not token else None)
live = live and bool(token)

archive_path = ARCHIVE_DIR / f"{spot_code}.json"
archive_ready = False
if live:
    st.sidebar.subheader("Contract archive")
    codes_text = st.sidebar.text_area(
        "Paste contract codes from iFinD (front-month expiry)",
        help="Comma / newline separated. Codes for the main (front-month) "
             "expiry of the selected underlying.",
    )
    next_codes_text = st.sidebar.text_area(
        "Next-month codes (for VIX)",
        help="Optional. Codes for the next expiry; used by the VIX module "
             "(30-day interpolation needs two expiries) and the next-month GEX merge.",
    )
    query_date = st.sidebar.date_input(
        "Archive query date",
        value=date.today(),
        help="date_sequence only returns name/expiry data on trading days. "
             "On weekends/holidays pick the nearest trading day, "
             "otherwise the archive comes back empty.",
    )
    if st.sidebar.button("Save archive", disabled=not codes_text.strip()):
        with st.spinner("Building archive via the daily endpoint..."):
            try:
                archive = build_archive_with_next(
                    token, spot_code, parse_codes(codes_text),
                    parse_codes(next_codes_text) if next_codes_text.strip() else None,
                    query_date.isoformat())
                save_archive(archive_path, archive)
                n_missing = len(archive.get("missing", []))
                st.sidebar.success(
                    f"Archive saved for {spot_code}: {len(archive['codes'])} contracts "
                    + (f"({n_missing} codes skipped: {', '.join(archive['missing'])})" if n_missing else "")
                    + (f" · next month {archive['next']['expiry']}: {len(archive['next']['codes'])} contracts"
                       if archive.get("next") else "")
                )
            except Exception as exc:  # noqa: BLE001
                st.sidebar.error(f"Archive failed: {exc}")
    if archive_path.is_file():
        try:
            _a = load_archive(archive_path)
            _n = _a.get("next")
            st.sidebar.caption(f"Using saved archive `{spot_code}.json` · front {len(_a['codes'])} contracts"
                               + (f" · next {_n['expiry']} ({len(_n['codes'])})" if _n else " · no next month"))
            archive_ready = True
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Saved archive could not be read: {exc}")
    else:
        st.sidebar.warning("No archive yet — paste contract codes above and click **Save archive**.")

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
st.title("Option-Chain Dashboard")

if not live:
    stop_all_workers()  # live switched off -> no background fetching
    if not token:
        st.info("No live data: enter an iFinD access token in the sidebar to start.")
    else:
        st.info("Token entered. Turn on **Live refresh** in the sidebar to set up contract codes and start.")
    st.markdown(GUIDE)
elif not archive_ready:
    st.info("Live mode needs a contract archive: paste the front-month contract codes in the sidebar "
            "and click **Save archive**.")
    st.markdown(GUIDE)
else:
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    try:
        worker = get_worker(spot_code, token_hash, INTERVAL_SECONDS[interval], token)
        if not worker.alive:  # thread died or was stopped by a newer one -> rebuild
            get_worker.clear()
            worker = get_worker(spot_code, token_hash, INTERVAL_SECONDS[interval], token)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not start the live worker: {exc}")
        st.stop()

    archive = load_archive(archive_path)
    with st.expander("Data pipeline status", expanded=False):
        dsc, rqc = st.columns(2)
        with dsc:
            st.markdown("**DS · archive**")
            missing = archive.get("missing", [])
            st.write(
                f"spot `{archive['spot_code']}` · as_of {archive.get('as_of_date', '—')}"
                f"\n\ncontracts {len(archive['codes'])}"
                + (f" · skipped {missing}" if missing else "")
                + f"\n\nmul {archive['mul']} · hv30 {archive['hv30']} · "
                  f"hv60 {archive['hv60']} · hv90 {archive['hv90']}"
            )
        with rqc:
            st.markdown("**RQ · background worker**")
            st.write(f"iFinD realtime · every {INTERVAL_SECONDS[interval]}s")
            if st.button("Fetch now"):
                worker.refresh_now()

    @st.fragment(run_every=UI_POLL)
    def live_view():
        state = worker.snapshot()  # in-memory read only, never touches the network
        source_badge(state)
        if state.fetch_seconds is not None:
            st.caption(f"Snapshots this session: {state.n_snapshots} · last fetch+calc "
                       f"{state.fetch_seconds:.2f}s · UI polls every {UI_POLL}")
        if state.analysis is None:
            if state.last_error:
                st.warning("No live data yet. Check the token, the contract codes (archive) and network access "
                           "to the iFinD API; the worker keeps retrying on the refresh interval.")
            else:
                st.info("Waiting for the background worker's first snapshot…")
            return
        try:
            st.subheader("Intraday")
            st.plotly_chart(intraday_figure(state.history), width="stretch",
                            key="live_intraday", config=PLOTLY_CONFIG)
            label = {"LIVE": f"realtime {spot_code}", "STALE": f"STALE realtime {spot_code}"}.get(
                state.source, state.source)
            render_analysis(state.analysis, f"{label} @ {state.data_time:%H:%M:%S}", "live", state.vix,
                            next_chain=(state.full_chain[state.full_chain["month"] == "next"]
                                        if state.full_chain is not None and "month" in state.full_chain else None))
            chain_df = state.chain
            display_cols = ["thscode", "name", "option_type", "strike", "expiry",
                            "oi", "iv", "delta", "gamma"]
            with st.expander("Realtime option chain (RQ)"):
                st.dataframe(chain_df[display_cols] if set(display_cols).issubset(chain_df.columns) else chain_df)
        except Exception as exc:  # noqa: BLE001 - never crash the page on a bad snapshot
            st.error(f"Could not render the live snapshot: {type(exc).__name__}: {exc}")

    live_view()
