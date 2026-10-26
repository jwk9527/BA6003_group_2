"""Developer console: update a Live contract archive (data/archives/<spot>.json).

Interactive terminal tool replacing the manual "paste codes -> Save archive"
step. Run from the project root:

    .venv/bin/python input_contract_list.py      # or: uv run python input_contract_list.py

Steps:
1. underlying code   e.g. 588000SH / 588000.SH / 588000 / 159915SZ
2. two expiry tags   e.g. 2611 and 2612 (YYMM; earlier = front month, later = next month)
3. option codes for each month (multi-line or comma/space separated; finish with an empty line)
4. optional iFinD check (token read from the IFIND_TOKEN environment variable only;
   it is never prompted for, printed or written anywhere)
5. summary -> confirm -> the old json is backed up to data/archives/backup/ and the
   whole archive is overwritten.

The archive schema is the one the Live page uses (``archive.build_archive_with_next``):
front month at the top level + ``next`` = {"expiry", "codes"[, "missing"]}.
Contract names / strikes / expiries come from iFinD ``date_sequence``; without a
token only codes already present in the current archive can be reused.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from project_option_chain.archive import (  # noqa: E402
    build_archive_with_next,
    load_archive,
    parse_codes,
    save_archive,
)
from project_option_chain.config import DATA_DIR  # noqa: E402

ARCHIVE_DIR = DATA_DIR / "archives"
BACKUP_DIR = ARCHIVE_DIR / "backup"
OPTION_CODE_RE = re.compile(r"^\d{8}\.(SH|SZ)$")
TAG_RE = re.compile(r"^\d{2}(0[1-9]|1[0-2])$")

# Known underlyings; anything else is inferred from the code prefix
# (SSE funds start with 5, SZSE funds with 1).
KNOWN_UNDERLYINGS = {"588000": "SH", "588080": "SH", "510050": "SH", "510300": "SH",
                     "510500": "SH", "159915": "SZ", "159919": "SZ", "159922": "SZ", "159901": "SZ"}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_input_contract_list.py)
# ---------------------------------------------------------------------------
def normalize_underlying(text: str) -> str:
    """'588000SH' / '588000.sh' / '588000' / '159915SZ' -> '588000.SH' / '159915.SZ'."""
    m = re.fullmatch(r"\s*(\d{6})\s*\.?\s*(SH|SZ)?\s*", text.upper())
    if not m:
        raise ValueError(f"Not an ETF code: {text!r} (expected 6 digits, optionally followed by SH/SZ)")
    num, exch = m.group(1), m.group(2)
    inferred = KNOWN_UNDERLYINGS.get(num) or {"5": "SH", "1": "SZ"}.get(num[0])
    if exch is None:
        if inferred is None:
            raise ValueError(f"Cannot infer the exchange for {num}; add .SH or .SZ")
        exch = inferred
    elif num in KNOWN_UNDERLYINGS and KNOWN_UNDERLYINGS[num] != exch:
        raise ValueError(f"{num} is listed on {KNOWN_UNDERLYINGS[num]}, not {exch}")
    return f"{num}.{exch}"


def parse_tag(text: str) -> str:
    tag = text.strip()
    if not TAG_RE.match(tag):
        raise ValueError(f"Expiry tag must be YYMM, e.g. 2611 (got {text!r})")
    return tag


def order_tags(a: str, b: str) -> tuple[str, str, list[str]]:
    """(front, next, warnings): sorted by month; warns if equal or entered in reverse."""
    warnings = []
    if a == b:
        warnings.append(f"Both expiry tags are {a}; front and next month must differ.")
    elif a > b:
        warnings.append(f"Entered front {a} >= next {b}; swapped to front {b}, next {a}.")
        a, b = b, a
    return a, b, warnings


def parse_option_codes(text: str, exchange: str) -> tuple[list[str], list[str], list[str]]:
    """Split pasted codes -> (valid unique codes in input order, invalid tokens, duplicates).

    Uses ``archive.parse_codes`` (strips quotes, splits on commas/whitespace). Bare
    8-digit codes get the underlying's exchange suffix; codes on the other exchange
    are rejected.
    """
    valid, invalid, dups = [], [], []
    for raw in parse_codes(text):
        code = raw.upper()
        if re.fullmatch(r"\d{8}", code):
            code = f"{code}.{exchange}"
        if not OPTION_CODE_RE.match(code) or not code.endswith("." + exchange):
            invalid.append(raw)
        elif code in valid:
            dups.append(code)
        else:
            valid.append(code)
    return valid, invalid, dups


def last_weekday(today: date | None = None) -> date:
    """Nearest weekday <= today (date_sequence only returns rows on trading days;
    exchange holidays are not known here)."""
    d = today or date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def month_of_name(name: str) -> int | None:
    m = re.search(r"(\d{1,2})月", name or "")
    return int(m.group(1)) if m else None


def check_archive(archive: dict, front_tag: str, next_tag: str) -> list[str]:
    """Problems with a built archive: codes iFinD did not return, names whose month
    does not match the tag, or contracts of a different underlying (name prefix)."""
    problems = []
    sections = [("front", front_tag, archive.get("codes", {}), archive.get("missing", []))]
    nxt = archive.get("next") or {}
    sections.append(("next", next_tag, nxt.get("codes", {}), nxt.get("missing", [])))
    prefixes = set()
    for label, tag, codes, missing in sections:
        if missing:
            problems.append(f"{label} {tag}: {len(missing)} code(s) not found by iFinD: {', '.join(missing)}")
        if not codes:
            problems.append(f"{label} {tag}: no contracts in the archive")
        want = int(tag[2:])
        for code, meta in codes.items():
            got = month_of_name(meta.get("name", ""))
            if got != want:
                problems.append(f"{label} {tag}: {code} {meta.get('name')!r} is month {got}, expected {want}")
            prefix = re.split(r"[购沽]", meta.get("name", ""))[0]
            if prefix:
                prefixes.add(prefix)
    if len(prefixes) > 1:
        problems.append(f"contract names have different underlyings: {sorted(prefixes)}")
    return problems


def offline_archive(current: dict | None, spot: str, front: list[str], nxt: list[str],
                    as_of: str) -> tuple[dict | None, list[str]]:
    """Rebuild the archive without iFinD from metadata already in ``current``.
    Returns (archive or None, codes with no known metadata)."""
    known: dict[str, dict] = {}
    if current:
        known.update(current.get("codes", {}))
        known.update((current.get("next") or {}).get("codes", {}))
    unknown = [c for c in front + nxt if c not in known]
    if unknown or not current:
        return None, unknown if current else front + nxt
    next_codes = {c: known[c] for c in nxt}
    expiries = sorted({m["expiry"] for m in next_codes.values()})
    archive = {k: current[k] for k in ("hv30", "hv60", "hv90", "mul") if k in current}
    archive = {"spot_code": spot, "as_of_date": as_of, **archive, "codes": {c: known[c] for c in front}}
    archive["next"] = {"expiry": expiries[0] if expiries else None, "codes": next_codes}
    return archive, []


def backup_and_save(path: Path, archive: dict, backup_dir: Path, now: datetime | None = None) -> Path | None:
    """Copy the old json to backup_dir/<name>_<YYYYmmdd_HHMMSS>.json, then overwrite via
    ``archive.save_archive``. Returns the backup path (None if there was no old file)."""
    backup = None
    if path.is_file():
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{path.stem}_{stamp}.json"
        backup.write_bytes(path.read_bytes())
    save_archive(path, archive)
    return backup


def summarize(archive: dict, front_tag: str, next_tag: str) -> str:
    nxt = archive.get("next") or {}
    f_exp = sorted({m.get("expiry") for m in archive.get("codes", {}).values()})
    return (f"  spot_code   {archive['spot_code']}\n"
            f"  as_of_date  {archive['as_of_date']}\n"
            f"  front {front_tag}  {len(archive.get('codes', {}))} contracts · expiry {', '.join(map(str, f_exp)) or '—'}\n"
            f"  next  {next_tag}  {len(nxt.get('codes', {}))} contracts · expiry {nxt.get('expiry') or '—'}\n"
            f"  mul {archive.get('mul')} · hv30 {archive.get('hv30')}")


# ---------------------------------------------------------------------------
# Interactive console
# ---------------------------------------------------------------------------
def ask(prompt: str, parse=lambda s: s, inp=input):
    while True:
        try:
            return parse(inp(prompt))
        except ValueError as exc:
            print(f"  ! {exc}")


def yes(prompt: str, default: bool = False, inp=input) -> bool:
    ans = inp(prompt + (" [Y/n] " if default else " [y/N] ")).strip().lower()
    return default if not ans else ans in ("y", "yes")


def read_block(prompt: str, inp=input) -> str:
    print(prompt + " (paste codes; finish with an empty line)")
    lines = []
    while True:
        line = inp()
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


def main(inp=input) -> int:
    print("=== Contract archive console (data/archives/<spot>.json) ===")
    spot = ask("Underlying code (e.g. 588000SH, 159915.SZ): ", normalize_underlying, inp)
    exch = spot.split(".")[1]
    path = ARCHIVE_DIR / f"{spot}.json"
    current = load_archive(path) if path.is_file() else None
    if current:
        n_next = len((current.get("next") or {}).get("codes", {}))
        print(f"  current archive: as_of {current.get('as_of_date')} · front {len(current.get('codes', {}))} · next {n_next}")
    else:
        print("  no archive yet for this underlying (a new file will be created)")

    a = ask("Front-month expiry tag (YYMM, e.g. 2611): ", parse_tag, inp)
    b = ask("Next-month expiry tag  (YYMM, e.g. 2612): ", parse_tag, inp)
    front_tag, next_tag, warns = order_tags(a, b)
    for w in warns:
        print(f"  ! {w}")
    if front_tag == next_tag:
        print("Aborted: two different months are required.")
        return 1

    lists = {}
    for tag in (front_tag, next_tag):
        while True:
            codes, invalid, dups = parse_option_codes(read_block(f"Option codes for {tag}", inp), exch)
            print(f"  {tag}: {len(codes)} valid · {len(dups)} duplicate(s) removed · {len(invalid)} invalid")
            if invalid:
                print(f"  ! invalid (expected 8 digits + .{exch}): {', '.join(invalid)}")
            if not codes:
                print(f"  ! {tag} is empty — paste the codes again.")
                continue
            if invalid and not yes("  Continue without the invalid tokens?", inp=inp):
                continue
            lists[tag] = codes
            break
    overlap = set(lists[front_tag]) & set(lists[next_tag])
    if overlap:
        print(f"  ! {len(overlap)} code(s) appear in both months: {', '.join(sorted(overlap))}")
        if not yes("  Continue anyway?", inp=inp):
            return 1

    as_of = last_weekday().isoformat()
    archive = None
    if yes("Check codes with iFinD (token from env IFIND_TOKEN)?", inp=inp):
        token = os.environ.get("IFIND_TOKEN", "").strip()
        if not token:
            print("  IFIND_TOKEN is not set; skipping the iFinD check. Set it in this shell first, e.g.\n"
                  "    read -s IFIND_TOKEN && export IFIND_TOKEN")
        else:
            print(f"  querying iFinD date_sequence for {as_of} ...")
            try:
                archive = build_archive_with_next(token, spot, lists[front_tag], lists[next_tag], as_of)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! iFinD request failed: {str(exc).replace(token, '***')}")
            if archive is not None:
                problems = check_archive(archive, front_tag, next_tag)
                for p in problems:
                    print(f"  ! {p}")
                if not problems:
                    print("  iFinD check passed: all codes found, months and underlying match.")
                elif not yes("  Continue with these mismatches?", inp=inp):
                    return 1
    if archive is None:
        archive, unknown = offline_archive(current, spot, lists[front_tag], lists[next_tag], as_of)
        if archive is None:
            print(f"  ! {len(unknown)} code(s) have no name/strike/expiry in the current archive, and those "
                  "fields can only come from iFinD. Set IFIND_TOKEN and rerun with the iFinD check.")
            return 1
        print("  built offline from metadata already in the current archive.")
        problems = check_archive(archive, front_tag, next_tag)
        for p in problems:
            print(f"  ! {p}")
        if problems and not yes("  Continue with these mismatches?", inp=inp):
            return 1

    print("\nSummary:\n" + summarize(archive, front_tag, next_tag))
    if not yes(f"Overwrite {path.relative_to(ROOT)} (old file is backed up)?", inp=inp):
        print("Nothing written.")
        return 1
    backup = backup_and_save(path, archive, BACKUP_DIR)
    print(f"Saved {path.relative_to(ROOT)}" + (f" · backup {backup.relative_to(ROOT)}" if backup else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing written.")
        sys.exit(1)
