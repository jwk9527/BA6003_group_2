"""A-share trading-session status (Asia/Shanghai clock).

Weekday sessions only: exchange holidays (Spring Festival, National Day, ...)
are NOT covered, because no exchange calendar is bundled with the project.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

SH_TZ = ZoneInfo("Asia/Shanghai")

# (start, end, state, is_open, description)
SESSIONS = [
    (time(9, 15), time(9, 25), "Opening call auction", False, "orders accepted, matched at 09:25"),
    (time(9, 25), time(9, 30), "Pre-open", False, "auction matched; continuous trading starts 09:30"),
    (time(9, 30), time(11, 30), "Open", True, "morning continuous trading 09:30–11:30"),
    (time(11, 30), time(13, 0), "Lunch break", False, "afternoon session starts 13:00"),
    (time(13, 0), time(14, 57), "Open", True, "afternoon continuous trading 13:00–14:57"),
    (time(14, 57), time(15, 0), "Closing call auction", True, "closing price set by call auction 14:57–15:00"),
]


@dataclass(frozen=True)
class MarketStatus:
    state: str
    is_open: bool
    detail: str
    now: datetime


def market_status(now: datetime | None = None) -> MarketStatus:
    """Session state at ``now`` (default: current time), evaluated in Asia/Shanghai."""
    now = (now or datetime.now(SH_TZ)).astimezone(SH_TZ)
    if now.weekday() >= 5:
        return MarketStatus("Weekend", False, "market closed Saturday and Sunday", now)
    t = now.time()
    for start, end, state, is_open, desc in SESSIONS:
        if start <= t < end:
            return MarketStatus(state, is_open, desc, now)
    if t < time(9, 15):
        return MarketStatus("Closed", False, "before the 09:15 opening call auction", now)
    return MarketStatus("Closed", False, "trading day ended at 15:00", now)
