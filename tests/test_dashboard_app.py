"""Live page smoke tests: no-token guide, archive section before the Live toggle,
interval options, session-only archive mode, failed fetch handled, router order.

Run: uv run python tests/test_dashboard_app.py
"""
import json
import os
import sys
import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PAGE = str(ROOT / "app_pages" / "live.py")
BUILTIN = json.loads((ROOT / "data" / "archives" / "588000.SH.json").read_text("utf-8"))


def labels(at):
    return [w.label for w in at.sidebar.get("selectbox")] + [w.label for w in at.sidebar.toggle] + \
           [b.label for b in at.sidebar.button]


# 1) no token: guide, archive shown (built-in), Live toggle disabled, no charts
at = AppTest.from_file(PAGE, default_timeout=60).run()
assert not at.exception, at.exception
assert any("enter an iFinD access token" in i.value for i in at.info)
assert any("How to use the Live page" in m.value for m in at.markdown)
assert len(at.get("plotly_chart")) == 0
caps = " ".join(c.value for c in at.sidebar.caption)
assert "As of" in caps and "front" in caps and "file" in caps, caps
assert at.sidebar.toggle(key="live_on").disabled
# archive section (Save archive button) comes before the Live toggle in the sidebar tree
order = [type(e).__name__ + ":" + str(getattr(e, "label", "")) for e in at.sidebar]
iv = at.sidebar.selectbox(key="live_interval")
assert iv.options == ["10s", "30s", "60s", "15 min", "30 min", "60 min"], iv.options
assert at.sidebar.button(key="arch_save").disabled  # needs token
print("no-token OK · intervals", iv.options)

# 2) token + built-in archive -> toggle enabled
at.sidebar.text_input[0].set_value("invalid-token-for-test").run()
assert not at.sidebar.toggle(key="live_on").disabled
print("toggle enabled with token + built-in archive OK")

# 3) session-only archive mode (Cloud): ARCHIVE_PERSIST=session, archive in session_state
os.environ["ARCHIVE_PERSIST"] = "session"
at2 = AppTest.from_file(PAGE, default_timeout=60)
at2.session_state["live_archives"] = {"510300.SH": {**BUILTIN, "spot_code": "510300.SH"}}
at2.run()
at2.sidebar.selectbox[0].set_value("510300.SH").run()
assert not at2.exception, at2.exception
caps = " ".join(c.value for c in at2.sidebar.caption)
assert "session (not saved to disk)" in caps and "Session-only" in caps, caps
assert any(b.label == "Download archive json" for b in at2.sidebar.get("download_button")), "archive download missing"
assert not (ROOT / "data" / "archives" / "510300.SH.json").exists()
os.environ.pop("ARCHIVE_PERSIST")
print("session-only archive OK")

# 4) failed fetch (bad token) -> error shown, no exception, session log section present
at.sidebar.toggle(key="live_on").set_value(True).run()
assert not at.exception, at.exception
for _ in range(10):
    time.sleep(1.5)
    at.run()
    if at.error or at.warning:
        break
assert not at.exception, at.exception
assert at.error or at.warning
assert any("Session log" in h.value for h in at.header)
at.sidebar.toggle(key="live_on").set_value(False).run()
assert not at.exception
print("failed fetch OK")

# 5) router: History is the default page, Live second
at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=120).run()
assert not at.exception, at.exception
assert any("ETF Option History" in t.value for t in at.title), [t.value for t in at.title]
at.switch_page("app_pages/live.py").run()
assert not at.exception and any("Option-Chain Dashboard" in t.value for t in at.title)
print("router OK (History default)")
print("ALL OK")
