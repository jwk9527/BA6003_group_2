"""Unified font stack: UI CSS injected once in dashboard.py; Plotly template uses same stack."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_option_chain import charts  # noqa: E402
from project_option_chain.fonts import FONT_STACK, UI_CSS  # noqa: E402


def test_stack_order():
    assert FONT_STACK.index("Source Sans") < FONT_STACK.index("PingFang SC") < FONT_STACK.index("Microsoft YaHei")
    assert FONT_STACK.rstrip().endswith("sans-serif")
    assert FONT_STACK in UI_CSS and "<style>" in UI_CSS


def test_plotly_template_fonts():
    lay = charts.pio.templates[charts.TEMPLATE_NAME].layout
    assert lay.font.family == FONT_STACK
    assert lay.hoverlabel.font.family == FONT_STACK
    assert lay.legend.font.family == FONT_STACK
    assert lay.annotationdefaults.font.family == FONT_STACK


def test_dashboard_injects_css():
    assert "inject_ui_fonts(st)" in (ROOT / "dashboard.py").read_text()


if __name__ == "__main__":
    test_stack_order(); test_plotly_template_fonts(); test_dashboard_injects_css(); print("ok")
