"""Option-chain dashboard — multipage entry point.

Pages:
- Live     (app_pages/live.py):    realtime / static option-chain analytics.
- History  (app_pages/history.py): ETF option history (GEX & volatility).

Run:
    uv run streamlit run dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

st.set_page_config(page_title="Option-Chain Dashboard", layout="wide")

nav = st.navigation([
    st.Page("app_pages/live.py", title="Live", icon="📡", default=True, url_path="live"),
    st.Page("app_pages/history.py", title="History", icon="📈", url_path="history"),
])
nav.run()
