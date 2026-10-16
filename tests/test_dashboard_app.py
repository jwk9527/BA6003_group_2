"""Smoke test: Live page without a token shows the usage guide (no sample/simulated data),
and a bad token / failed fetch is reported without crashing.

Run: uv run python tests/test_dashboard_app.py
"""
import sys
import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PAGE = str(ROOT / "app_pages" / "live.py")

at = AppTest.from_file(PAGE, default_timeout=60).run()
assert not at.exception, at.exception
assert any("enter an iFinD access token" in i.value for i in at.info), [i.value for i in at.info]
assert any("How to use the Live page" in m.value for m in at.markdown)
assert len(at.get("plotly_chart")) == 0, "no charts without live data"
assert at.sidebar.toggle[0].disabled, "Live refresh must be disabled without a token"
print("no-token guide OK")

# Failed fetch: fake token + saved archive -> worker errors, page shows an error, no exception.
from project_option_chain import live as LIVE  # noqa: E402

at = AppTest.from_file(PAGE, default_timeout=60).run()
at.sidebar.text_input[0].set_value("invalid-token-for-test").run()
at.sidebar.toggle[0].set_value(True).run()
assert not at.exception, at.exception
for _ in range(10):
    time.sleep(1.5)
    at.run()
    if at.error or at.warning:
        break
assert not at.exception, at.exception
msgs = [e.value for e in at.error] + [w.value for w in at.warning] + [i.value for i in at.info]
print("failed-fetch messages:", [m[:90] for m in msgs])
assert at.error or at.warning or any("archive" in m for m in msgs)
print("ALL OK")
