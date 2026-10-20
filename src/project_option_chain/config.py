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


def _setting(name: str) -> str:
    """Env var / .env first, then Streamlit secrets; '' if unset."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass
    value = os.environ.get(name, "")
    if not value:
        try:
            import streamlit as st
            value = str(st.secrets.get(name, "") or "")
        except Exception:  # noqa: BLE001 - no secrets file / not under Streamlit
            value = ""
    return value.strip()


def running_on_streamlit_cloud() -> bool:
    """Heuristics for Streamlit Community Cloud (apps run from /mount/src as user 'appuser')."""
    import os
    return (str(PROJECT_ROOT).startswith("/mount/src")
            or os.environ.get("HOME") == "/home/appuser"
            or os.environ.get("USER") == "appuser"
            or bool(os.environ.get("STREAMLIT_CLOUD")))


def archive_persist_mode() -> str:
    """'file' (write data/archives/<spot>.json) or 'session' (st.session_state only).

    Set ARCHIVE_PERSIST=file|session in .env / Secrets; default: 'session' on
    Streamlit Community Cloud, 'file' elsewhere.
    """
    mode = _setting("ARCHIVE_PERSIST").lower()
    if mode in ("file", "session"):
        return mode
    return "session" if running_on_streamlit_cloud() else "file"
