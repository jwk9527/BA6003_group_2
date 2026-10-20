"""In-session Live log: one summary row per successful refresh + full-chain snapshots.

Pure functions on a plain dict kept in ``st.session_state`` (never on disk), so
the data disappears when the browser session ends. The worker thread never
touches this dict: the page reads the worker's immutable ``LiveState`` and
appends here, which keeps the handoff thread-safe.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd

MAX_SNAPSHOTS = 200      # full-chain snapshots kept in memory (oldest dropped first)
MAX_ROWS = 10_000        # summary rows kept
SUMMARY_COLUMNS = ["time", "spot", "net_gex_million", "zero_gamma", "call_wall", "put_wall", "max_pain",
                   "atm_iv_pct", "skew_25d_pts", "vix30", "vrp30"]


def new_log() -> dict:
    return {"rows": [], "snapshots": [], "last_n": 0, "dropped_snapshots": 0}


def _f(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def summary_row(state) -> dict:
    """One row from a LiveState with a fresh analysis."""
    m = state.analysis.metrics.iloc[0]
    vix = _f(getattr(state.vix, "vix", None)) if state.vix is not None else None
    hv30 = _f(m.get("hv30"))
    atm, skew = _f(m.get("atm_iv")), _f(m.get("call25_put25_iv_skew"))
    return {
        "time": pd.Timestamp(state.data_time).strftime("%Y-%m-%d %H:%M:%S"),
        "spot": _f(m["spot"]), "net_gex_million": _f(m["net_gex_million"]), "zero_gamma": _f(m["zero_gamma"]),
        "call_wall": _f(m["call_wall"]), "put_wall": _f(m["put_wall"]), "max_pain": _f(m["max_pain"]),
        "atm_iv_pct": None if atm is None else round(atm * 100, 4),
        "skew_25d_pts": None if skew is None else round(skew * 100, 4),
        "vix30": vix, "vrp30": None if vix is None or hv30 is None else round(vix - hv30, 4),
    }


def append(log: dict, state) -> bool:
    """Append the state's snapshot if it is new (by snapshot counter). Returns True if appended."""
    if state is None or state.analysis is None or state.source != "LIVE" or state.n_snapshots <= log["last_n"]:
        return False
    log["last_n"] = state.n_snapshots
    row = summary_row(state)
    log["rows"].append(row)
    del log["rows"][:-MAX_ROWS]
    chain = state.full_chain if state.full_chain is not None else state.chain
    if chain is not None:
        log["snapshots"].append((row["time"], chain.copy()))
        if len(log["snapshots"]) > MAX_SNAPSHOTS:
            log["dropped_snapshots"] += len(log["snapshots"]) - MAX_SNAPSHOTS
            del log["snapshots"][:-MAX_SNAPSHOTS]
    return True


def summary_frame(log: dict) -> pd.DataFrame:
    return pd.DataFrame(log["rows"], columns=SUMMARY_COLUMNS)


def summary_csv(log: dict) -> bytes:
    return summary_frame(log).to_csv(index=False).encode("utf-8-sig")


def snapshots_zip(log: dict, prefix: str = "live") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{prefix}_summary.csv", summary_csv(log))
        for t, chain in log["snapshots"]:
            stamp = t.replace("-", "").replace(":", "").replace(" ", "_")
            z.writestr(f"chains/{prefix}_chain_{stamp}.csv", chain.to_csv(index=False).encode("utf-8-sig"))
    return buf.getvalue()
