"""Real-time adapter for the iFinD quantapi ``real_time_quotation`` endpoint.

Owns ONLY the live (RQ) side: given an archive (static registry built by
``archive.build_archive``), it fetches the live chain and returns a canonical
DataFrame for the analytics module.

Vendor format — VERIFIED against a real REST response (2026-10-05 probe):
- request body: ``{"codes": "...", "indicators": "openInterest,impliedVolatility,delta,gamma"}`` —
  **comma-separated** ENGLISH indicator names. Semicolon / pipe separators are
  rejected by the backend ("no data"). The notebook's ``date_sequence`` calls
  use the ``indipara`` list form instead — the two endpoints differ.
- response: ``{"tables": [{"thscode": "...", "time": ["YYYY-MM-DD HH:MM:SS"],
  "table": {"openInterest": [11826.0], ...}}]}``;
- on a non-trading day the endpoint returns the previous close (time = last
  trading day) — same behaviour as the user's THS_RQ probe;
- the underlying is fetched separately with ``indicators="latest"`` and read
  from ``table["latest"][0]``.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from .ifind import BASE_URL, headers as _headers
import requests

REALTIME_URL = f"{BASE_URL}/real_time_quotation"

RT_SPOT_INDICATOR = "latest"
# Comma-separated: the backend REJECTS semicolons/pipe ("no data"). Verified
# against a real response — openInterest/impliedVolatility/delta/gamma all
# return values on a non-trading day (previous close).
RT_OPT_INDICATORS = "openInterest,impliedVolatility,delta,gamma,latest,bid1,ask1"
# latest/bid1/ask1 verified 2026-10-16 (option last price and best quotes);
# used by the VIX module. Prices are optional: missing ones never fail a fetch.

CANONICAL_COLUMNS = [
    "date", "ETF_close", "thscode", "oi", "iv", "delta", "gamma", "mul",
    "DTE_n", "hv30", "hv60", "hv90", "name", "option_type", "strike", "expiry",
    "last", "bid", "ask", "month",
]


def archive_codes(archive: dict) -> dict[str, dict]:
    """All contracts in an archive: front month (``codes``) + optional ``next``.

    Each entry gets ``month`` = "front" | "next". Old archives (no ``next``)
    simply return the front month.
    """
    out = {c: {**m, "month": "front"} for c, m in archive["codes"].items()}
    for c, m in (archive.get("next") or {}).get("codes", {}).items():
        out.setdefault(c, {**m, "month": "next"})
    return out




def fetch_realtime(token: str, spot_code: str, archive: dict) -> pd.DataFrame:
    """Front-month live chain only (backward-compatible entry point)."""
    df = fetch_realtime_all(token, spot_code, archive)
    return df[df["month"] == "front"].reset_index(drop=True)


def fetch_realtime_all(token: str, spot_code: str, archive: dict) -> pd.DataFrame:
    """Fetch the live chain for every archived expiry (front + next)."""
    spot_response = requests.post(
        REALTIME_URL,
        json={"codes": spot_code, "indicators": RT_SPOT_INDICATOR},
        headers=_headers(token),
        timeout=20,
    )
    spot_response.raise_for_status()
    try:
        spot_price = float(spot_response.json()["tables"][0]["table"]["latest"][0])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Spot price lookup failed for {spot_code!r} "
            f"(indicators={RT_SPOT_INDICATOR!r}). "
            f"Raw response: {json.dumps(spot_response.json(), ensure_ascii=False)[:500]}"
        ) from exc

    registry = archive_codes(archive)
    codes = list(registry.keys())
    opt_response = requests.post(
        REALTIME_URL,
        json={"codes": ",".join(codes), "indicators": RT_OPT_INDICATORS},
        headers=_headers(token),
        timeout=20,
    )
    opt_response.raise_for_status()

    rows: list[dict] = []
    for item in opt_response.json()["tables"]:
        code = item["thscode"]
        meta = registry.get(code)
        if meta is None:
            # Defensive: if iFinD ever returns a code outside the archive
            # (e.g. aliases), skip it instead of crashing the whole loop.
            continue
        table = item["table"]
        expiry = date.fromisoformat(meta["expiry"])
        # RQ stamps every row with the data timestamp (last trading day on
        # holidays) — use it as the valuation date so date/DTE stay consistent.
        data_time = (item.get("time") or [None])[0]
        if data_time is None:
            data_time = date.today().isoformat()
        data_date = date.fromisoformat(str(data_time)[:10])
        rows.append({
            "date": data_date.isoformat(),
            "ETF_close": spot_price,
            "thscode": code,
            "oi": table.get("openInterest", [None])[0],
            "iv": table.get("impliedVolatility", [None])[0],
            "delta": table.get("delta", [None])[0],
            "gamma": table.get("gamma", [None])[0],
            "mul": archive["mul"],
            "DTE_n": (expiry - data_date).days,
            "hv30": archive["hv30"],
            "hv60": archive["hv60"],
            "hv90": archive["hv90"],
            "name": meta["name"],
            "option_type": meta["option_type"],
            "strike": meta["strike"],
            "expiry": meta["expiry"],
            "last": table.get("latest", [None])[0],
            "bid": table.get("bid1", [None])[0],
            "ask": table.get("ask1", [None])[0],
            "month": meta["month"],
        })
    if not rows:
        raise RuntimeError(
            "Realtime endpoint returned no option rows. "
            f"indicators={RT_OPT_INDICATORS!r}. "
            f"Raw response: {json.dumps(opt_response.json(), ensure_ascii=False)[:500]}"
        )

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)
    market_cols = ["oi", "iv", "delta", "gamma"]
    n_incomplete = int(df[market_cols].isna().any(axis=1).sum())
    if n_incomplete:
        raise RuntimeError(
            f"{n_incomplete} of {len(df)} option rows are missing market fields "
            f"(oi/iv/delta/gamma) — check the RQ indicator separator and names. "
            f"Current indicators={RT_OPT_INDICATORS!r}. "
            f"Raw response: {json.dumps(opt_response.json(), ensure_ascii=False)[:500]}"
        )
    return df
