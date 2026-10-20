"""Option-chain dashboard — multipage entry point.

Pages:
- History  (app_pages/history.py): ETF option history (GEX & volatility) — default page.
- Live     (app_pages/live.py):    realtime option-chain analytics (iFinD token required).

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
    st.Page("app_pages/history.py", title="History", icon="📈", default=True, url_path="history"),
    st.Page("app_pages/live.py", title="Live", icon="📡", url_path="live"),
])
nav.run()
