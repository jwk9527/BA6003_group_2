"""Shibor lookup and tenor interpolation (shared by Live and History).

Source: ``data/rates/shibor.parquet`` — one row per fixing date, columns
``Date`` + O/N, 1W, 2W, 1M, 3M, 6M, 9M, 1Y in percent. The file is refreshed
locally by ``scripts/build_history.py`` (akshare) and committed to the repo.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

SHIBOR_DAYS = np.array([1, 7, 14, 30, 90, 180, 270, 365], dtype=float)
SHIBOR_COLUMNS = ("O/N", "1W", "2W", "1M", "3M", "6M", "9M", "1Y")


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> tuple[np.ndarray, np.ndarray]:
    p = Path(path)
    if p.suffix == ".parquet":
        rates = pd.read_parquet(p)
    else:  # CSV with the same columns
        rates = pd.read_csv(p)
    rates["Date"] = pd.to_datetime(rates["Date"], errors="coerce")
    rates = rates.dropna(subset=["Date"]).sort_values("Date")
    if rates.empty:
        raise ValueError(f"The Shibor file contains no valid dated observations: {p.name}")
    values = rates[list(SHIBOR_COLUMNS)].apply(pd.to_numeric, errors="coerce").ffill().bfill().to_numpy(float) / 100.0
    return rates["Date"].to_numpy("datetime64[ns]"), values


def load_shibor(shibor_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(dates, decimal rates [n_dates × 8 tenors]); cached per file version."""
    if not shibor_path.is_file():
        raise FileNotFoundError(f"Shibor file was not found: {shibor_path}")
    return _load(str(shibor_path), shibor_path.stat().st_mtime)


def get_shibor_rate(shibor_path: Path, valuation_date: date, days_to_expiry: int) -> float:
    """Decimal annualised Shibor, linearly interpolated to the option tenor.

    Uses the latest fixing on or before ``valuation_date``; if the file starts
    later, its oldest fixing is used (and its newest if the date is past the end).
    """
    dates, values = load_shibor(shibor_path)
    i = int(np.searchsorted(dates, np.datetime64(pd.Timestamp(valuation_date)), side="right")) - 1
    row = values[max(i, 0)]
    return float(np.interp(days_to_expiry, SHIBOR_DAYS, row))
