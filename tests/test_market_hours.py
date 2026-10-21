"""Market-status classifier (Asia/Shanghai). Run: uv run python tests/test_market_hours.py"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from project_option_chain.market_hours import market_status  # noqa: E402

SH = ZoneInfo("Asia/Shanghai")
cases = {
    (2026, 10, 21, 9, 0): ("Closed", False), (2026, 10, 21, 9, 20): ("Opening call auction", False),
    (2026, 10, 21, 9, 27): ("Pre-open", False), (2026, 10, 21, 10, 0): ("Open", True),
    (2026, 10, 21, 12, 0): ("Lunch break", False), (2026, 10, 21, 13, 0): ("Open", True),
    (2026, 10, 21, 14, 58): ("Closing call auction", True), (2026, 10, 21, 15, 0): ("Closed", False),
    (2026, 10, 24, 10, 0): ("Weekend", False),
}
for args, (state, is_open) in cases.items():
    ms = market_status(datetime(*args, tzinfo=SH))
    assert (ms.state, ms.is_open) == (state, is_open), (args, ms)
# timezone conversion: 10:00 Singapore = 10:00 Shanghai (both UTC+8); 02:00 UTC = 10:00 Shanghai
assert market_status(datetime(2026, 10, 21, 2, 0, tzinfo=ZoneInfo("UTC"))).state == "Open"
print("market_hours OK")
