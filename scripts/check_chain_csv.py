#!/usr/bin/env python3
"""Standalone manual validator for an option-chain CSV.

Checks that a chain file satisfies the analytics contract before it is fed
to the compute module:

1. every column required by the compute module (REQUIRED_COLUMNS) is present;
2. the raw row count is even, and the number of Call rows equals the number
   of Put rows.

This script is intentionally independent of the main pipeline: it is meant
to be run by hand (e.g. when a new vendor file arrives or before bulk
research), never on every computation.

Usage:
    uv run python scripts/check_chain_csv.py [path/to/chain.csv ...]
    uv run python scripts/check_chain_csv.py       # checks tests/fixtures/*.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# The compute module lives under src/ (src layout). Add it to the import path
# so this script works both with `uv run` and with plain `python`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from project_option_chain.analytics import REQUIRED_COLUMNS  # noqa: E402

CALL_VALUES = {"c", "call", "购"}
PUT_VALUES = {"p", "put", "沽"}


def _resolve(path: Path) -> Path:
    """Resolve relative paths against the project root, not the cwd."""
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _classify(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return two boolean Series marking Call and Put rows.

    Uses the explicit ``option_type`` column when present; otherwise falls
    back to parsing the contract name (the same 购/沽 convention used by
    the analytics module).
    """
    if "option_type" in df.columns:
        value = df["option_type"].astype(str).str.strip().str.lower()
        return value.isin(CALL_VALUES), value.isin(PUT_VALUES)
    if "name" in df.columns:
        name = df["name"].astype(str)
        is_call = name.str.contains("购", regex=False) | name.str.lower().str.contains("call", regex=False)
        is_put = name.str.contains("沽", regex=False) | name.str.lower().str.contains("put", regex=False)
        return is_call, is_put
    raise ValueError("CSV has neither 'option_type' nor 'name' to identify Call/Put rows.")


def check_file(path: Path) -> bool:
    """Run the two checks on one CSV file; return True if all passed."""
    problems = 0

    def report(ok: bool, label: str, detail: str = "") -> None:
        nonlocal problems
        if not ok:
            problems += 1
        detail_text = f" ({detail})" if detail else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {label}{detail_text}")

    print(f"Checking {path}")
    if not path.is_file():
        report(False, "File exists", "file not found")
        print()
        return False

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - report any parsing failure
        report(False, "Readable CSV", str(exc))
        print()
        return False

    # Check 1: required columns match the compute module.
    missing = sorted(REQUIRED_COLUMNS.difference(df.columns))
    report(not missing, "Required columns present",
           f"{len(REQUIRED_COLUMNS)}/{len(REQUIRED_COLUMNS)}" if not missing
           else f"missing: {', '.join(missing)}")

    # Check 2: even raw row count and Call/Put balance.
    raw_rows = len(df)
    report(raw_rows % 2 == 0, "Even raw row count", f"{raw_rows} rows")

    try:
        is_call, is_put = _classify(df)
    except ValueError as exc:
        report(False, "Call/Put identifiable", str(exc))
        print()
        return False

    unclassified = int((~(is_call | is_put)).sum())
    report(unclassified == 0, "Call/Put identifiable",
           f"{unclassified} row(s) unclassified" if unclassified else f"{len(df)}/{len(df)} rows")

    n_call, n_put = int(is_call.sum()), int(is_put.sum())
    report(n_call == n_put, "Call rows = Put rows", f"calls={n_call}, puts={n_put}")

    n_null = int(df.isna().sum().sum())
    if n_null:
        after_dropna = len(df.dropna())
        print(f"[WARN] {n_null} empty cell(s): analytics drops incomplete rows before "
              f"computing ({raw_rows} -> {after_dropna} rows)")

    print()
    return problems == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="One or more option-chain CSV files (defaults to tests/fixtures/*.csv).")
    args = parser.parse_args()

    paths = [_resolve(p) for p in args.paths]
    if not paths:
        paths = sorted((PROJECT_ROOT / "tests" / "fixtures").glob("*.csv"))
    if not paths:
        parser.error("No CSV files given and none found under tests/fixtures/.")

    failed = 0
    for path in paths:
        if not check_file(path):
            failed += 1

    if failed:
        print(f"{failed} file(s) FAILED")
        return 1
    print("All checked files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
