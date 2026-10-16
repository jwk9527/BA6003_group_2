"""Project paths and calculation defaults."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SHIBOR_PATH = DATA_DIR / "rates" / "shibor.parquet"
HISTORY_DIR = DATA_DIR / "history"

GEX_CURVE_STEP = 0.005
GEX_PRICE_PADDING_STD_MULTIPLIER = 2.0
DEFAULT_MULTIPLIER = 10_000
