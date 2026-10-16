"""Contract archive management — the static "middle layer" between iFinD's
two endpoints.

iFinD splits option data across two interfaces:
- ``date_sequence`` (DS): static attributes — contract short name, last
  strike date (expiry), underlying HV, contract multiplier. These barely
  change (only when the front-month rolls), so we fetch them ONCE and store
  them in ``data/archives/<spot_code>.json``.
- ``real_time_quotation`` (RQ): live market data — openInterest,
  impliedVolatility, delta, gamma, spot price. These change constantly and
  are fetched by ``live.fetch_realtime`` on every refresh.

This module owns the DS side and the JSON registry; ``live.py`` owns the RQ
side. The two talk through the archive dict, exactly like the notebook's
``option_code_map.json`` did.

KNOWN GOTCHAS (fixed):
- The pasted code list often carries stray quotes (``'...'``) → ``parse_codes``
  strips them; otherwise iFinD silently skips the quoted codes.
- HV indicators only return values when queried ON option codes, not on the
  spot code — the archive now takes hv30/60/90 + multiplier from the option
  rows instead of a separate spot query.
- ``date_sequence`` only returns rows for TRADING days — pass the nearest
  trading day (e.g. 2026-09-30), not today when today is a weekend/holiday.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import requests

from .analytics import parse_contract_name
from .ifind import BASE_URL, headers as _headers

DATE_SEQUENCE_URL = f"{BASE_URL}/date_sequence"

ARCHIVE_OPT_INDICATORS = (
    "ths_option_short_name_option",         # 合约名称（1a 实测有效）
    "ths_contract_type_option",             # 购/沽类型（THS_DS 实测有效，先存参考字段）
    "ths_remain_trade_days",                # 剩余交易日（THS_DS 实测有效，参考字段）
    "ths_surplus_duration_calendar_option", # 剩余日历天数（THS_DS 实测有效，参考字段）
    "ths_underlying_volatility_30d_option", # 标的历史波动率 30 日——实测：挂期权合约查才有效
    "ths_underlying_volatility_60d_option", # 60 日
    "ths_underlying_volatility_90d_option", # 90 日
    "ths_contract_multiplier",              # 合约乘数（实测：合约行可取到 10000）
)




def parse_codes(text: str) -> list[str]:
    """Split pasted contract codes on commas / whitespace / newlines.

    Also strips stray quote characters: the front-month list is usually
    copied from a console/notebook as ``'10012363.SH,...10012419.SH'`` with
    leading/trailing single quotes. Left in place, iFinD silently skips
    those two "codes", which is exactly the archive bug we fixed.
    """
    return [
        c.strip().strip("'\"")
        for c in re.split(r"[\s,，;；]+", text)
        if c.strip().strip("'\"")
    ]


def _fourth_wednesday(year: int, month: int) -> date:
    """ETF-option expiry rule: the 4th Wednesday of the contract month."""
    first = date(year, month, 1)
    days_ahead = (2 - first.weekday()) % 7  # Wednesday == 2
    return first + timedelta(days=days_ahead) + timedelta(weeks=3)


def expiry_from_name(name: str, today: date | None = None) -> str:
    """Fallback: derive the expiry date from the contract name's month.

    iFinD's option short name is e.g. "科创50购10月1700". We take the month
    and the next 4th-Wednesday from today (front-month contracts are always
    the not-yet-expired month, so the year is unambiguous).
    """
    today = today or date.today()
    match = re.search(r"(\d{1,2})月", name)
    if not match:
        raise ValueError(f"Cannot parse expiry month from contract name: {name!r}")
    month = int(match.group(1))
    for year in (today.year, today.year + 1):
        expiry = _fourth_wednesday(year, month)
        if expiry >= today:
            return expiry.isoformat()
    raise ValueError(f"Cannot find a future 4th-Wednesday for month {month} of {name!r}")


def _post_daily(token: str, codes: str, indicators: tuple[str, ...],
                as_of_date: str) -> dict:
    """Call the daily ``date_sequence`` endpoint (same format as 1a/1b).

    NOTE: ``date_sequence`` only returns rows for TRADING days — pass the
    nearest trading day (e.g. 2026-09-30), not today when today is a weekend
    or holiday, or the name/expiry arrays come back empty.
    """
    payload = {
        "codes": codes,
        "startdate": as_of_date,
        "enddate": as_of_date,
        "indipara": [{"indicator": x, "indiparams": []} for x in indicators],
    }
    response = requests.post(
        DATE_SEQUENCE_URL, json=payload, headers=_headers(token), timeout=20
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("tables"):
        raise RuntimeError(
            "date_sequence returned no rows for "
            f"{codes[:60]!r} (indicators={list(indicators)}, date={as_of_date}). "
            f"Raw response: {json.dumps(data, ensure_ascii=False)[:400]}"
        )
    return data


def _first_value(table: dict, indicator: str) -> object | None:
    """First non-None value for an indicator column, or None."""
    rows = table.get(indicator) or []
    for value in rows:
        if value is not None:
            return value
    return None


def _build_archive_from_tables(data: dict, spot_code: str, codes: list[str],
                               as_of_date: str) -> dict:
    """Turn one DS response (option rows with the ARCHIVE_OPT_INDICATORS
    columns) into the archive dict. Pure function → unit-testable.

    - name is the anchor: if DS has no name row for a code, that code goes
      to ``missing`` instead of blocking the archive;
    - HV / multiplier are the same for every contract of one underlying, so
      they are taken from the first row that has a value (fallback None /
      10_000);
    - option_type / strike / expiry come from the name parser as before;
      the raw iFinD fields (contract_type, remain days) are stored for
      reference until their value mapping is verified.
    """
    archive_codes: dict[str, dict] = {}
    hv30 = hv60 = hv90 = None
    mul = 10_000

    for item in data.get("tables", []):
        code = item["thscode"]
        table = item.get("table") or {}
        name_rows = table.get("ths_option_short_name_option") or []
        if not name_rows:
            continue  # DS returned no name row for this code → missing
        name = str(name_rows[0])
        try:
            is_call, _is_put, strike = parse_contract_name(name)
        except ValueError:
            continue  # cannot anchor the contract without a parseable name
        expiry = expiry_from_name(name)

        hv30 = hv30 if hv30 is not None else _first_value(table, "ths_underlying_volatility_30d_option")
        hv60 = hv60 if hv60 is not None else _first_value(table, "ths_underlying_volatility_60d_option")
        hv90 = hv90 if hv90 is not None else _first_value(table, "ths_underlying_volatility_90d_option")
        row_mul = _first_value(table, "ths_contract_multiplier")
        if row_mul is not None:
            mul = row_mul

        entry: dict = {
            "name": name,
            "option_type": "C" if is_call else "P",
            "strike": strike,
            "expiry": expiry,
        }
        # Reference fields (value mapping not yet verified — keep raw).
        for ref_key, indicator in (
            ("contract_type", "ths_contract_type_option"),
            ("remain_trade_days", "ths_remain_trade_days"),
            ("surplus_duration_days", "ths_surplus_duration_calendar_option"),
        ):
            ref_value = _first_value(table, indicator)
            if ref_value is not None:
                entry[ref_key] = ref_value
        archive_codes[code] = entry

    missing = [c for c in codes if c not in archive_codes]
    archive = {
        "spot_code": spot_code,
        "as_of_date": as_of_date,
        "hv30": hv30,
        "hv60": hv60,
        "hv90": hv90,
        "mul": mul,
        "codes": archive_codes,
    }
    if missing:
        archive["missing"] = missing
    return archive


def build_archive(token: str, spot_code: str, codes: list[str],
                  as_of_date: str | None = None) -> dict:
    """One-time contract registry: name/type/strike/expiry + underlying stats.

    Uses the daily endpoint so the real-time loop never has to; call it once
    when the user pastes a new set of front-month contract codes.
    ``as_of_date`` should be the nearest trading day (see ``_post_daily``);
    defaults to today for convenience but returns empty on non-trading days.
    """
    as_of_date = as_of_date or date.today().isoformat()
    data = _post_daily(token, ",".join(codes), ARCHIVE_OPT_INDICATORS, as_of_date)
    return _build_archive_from_tables(data, spot_code, codes, as_of_date)


def build_archive_with_next(token: str, spot_code: str, codes: list[str],
                            next_codes: list[str] | None, as_of_date: str | None = None) -> dict:
    """Front-month archive (backward-compatible top level) + optional
    ``next`` = {"expiry", "codes", "missing"} for the next-month (VIX only)."""
    archive = build_archive(token, spot_code, codes, as_of_date)
    if next_codes:
        nxt = build_archive(token, spot_code, next_codes, as_of_date)
        expiries = sorted({m["expiry"] for m in nxt["codes"].values()})
        archive["next"] = {"expiry": expiries[0] if expiries else None, "codes": nxt["codes"]}
        if nxt.get("missing"):
            archive["next"]["missing"] = nxt["missing"]
    return archive


def save_archive(path: Path, archive: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")


def load_archive(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
