"""UI language support (English / Simplified Chinese).

Keys are the English source strings themselves, so English needs no table
and code stays readable: ``t("Spot")`` -> "Spot" or "标的价格".
Templates use ``str.format`` placeholders: ``t("{n} trading days", n=5)``.
Internal data / column keys are never translated, only displayed text.

The current language lives in ``st.session_state["lang"]`` ("en" | "zh"),
set by the sidebar toggle in ``dashboard.py``; outside Streamlit it is "en".
"""

from __future__ import annotations

from .i18n_zh import ZH

LANGS = {"en": "English", "zh": "中文"}
DEFAULT_LANG = "en"


def get_lang() -> str:
    try:
        import streamlit as st
        lang = st.session_state.get("lang", DEFAULT_LANG)
    except Exception:  # noqa: BLE001 - no Streamlit runtime (scripts, tests)
        return DEFAULT_LANG
    return lang if lang in LANGS else DEFAULT_LANG


def t(text: str, lang: str | None = None, **kwargs) -> str:
    """Translate an English UI string; unknown strings fall back to English."""
    lang = lang or get_lang()
    out = ZH.get(text, text) if lang == "zh" else text
    return out.format(**kwargs) if kwargs else out


def language_toggle(container) -> str:
    """English / 中文 switch; stores the code in session_state['lang']."""
    import streamlit as st
    st.session_state.setdefault("lang", DEFAULT_LANG)
    choice = container.radio("Language / 语言", list(LANGS), format_func=LANGS.get, horizontal=True,
                             key="lang_choice", index=list(LANGS).index(st.session_state["lang"]))
    st.session_state["lang"] = choice
    return choice
