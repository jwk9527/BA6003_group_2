"""Shared font stack for the UI (CSS) and Plotly charts.

Latin glyphs/digits keep Streamlit's default Source Sans; CJK glyphs fall back to
system Chinese fonts. No fonts are bundled or downloaded.
"""

from __future__ import annotations

FONT_STACK = ('"Source Sans", "Source Sans Pro", "Source Sans 3", '
              '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", '
              '"Noto Sans SC", "Noto Sans CJK SC", sans-serif')

# Plotly passes the family string straight to SVG/CSS, so the same stack works there.
PLOTLY_FONT_FAMILY = FONT_STACK

_SELECTORS = ", ".join([
    "html", "body", ".stApp", "[data-testid='stAppViewContainer']",
    "[data-testid='stSidebar']", "[data-testid='stSidebar'] *",
    "[data-testid='stMarkdownContainer']", "[data-testid='stMarkdownContainer'] *",
    "[data-testid='stMetric']", "[data-testid='stMetric'] *",
    "[data-testid='stTooltipContent']", "[data-testid='stTooltipContent'] *",
    "[data-baseweb='tooltip']", "[data-baseweb='tooltip'] *",
    "[data-baseweb='popover']", "[data-baseweb='popover'] *",
    "[data-baseweb='select'] *", "[data-baseweb='input'] *", "[data-baseweb='radio'] *",
    "[data-baseweb='tab'] *", "label", "button", "input", "textarea", "select",
    "[data-testid='stTable']", "[data-testid='stTable'] *",
    "[data-testid='stDataFrame']", "[data-testid='stExpander'] *",
    "[data-testid='stCaptionContainer']", "[data-testid='stAlert'] *",
])

# Exclude code / icon fonts so monospace and Material icons are not overridden.
UI_CSS = (
    "<style>\n"
    f":root {{ --app-font: {FONT_STACK}; }}\n"
    f"{_SELECTORS} {{ font-family: var(--app-font); }}\n"
    "code, pre, kbd, samp, code *, pre * { font-family: \"Source Code Pro\", monospace; }\n"
    "[data-testid='stIconMaterial'], .material-symbols-rounded, "
    "span[class*='material'] { font-family: \"Material Symbols Rounded\" !important; }\n"
    "</style>"
)


def inject_ui_fonts(st) -> None:
    """Inject the unified font CSS (call once per run, from dashboard.py)."""
    st.markdown(UI_CSS, unsafe_allow_html=True)
