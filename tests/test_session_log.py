"""Session log (summary rows, snapshot cap, downloads) and worker stop on long intervals.

Run: uv run python tests/test_session_log.py
"""
import io
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_option_chain import session_log as SL  # noqa: E402
from project_option_chain.analytics import analyze_option_chain  # noqa: E402
from project_option_chain.config import SHIBOR_PATH, archive_persist_mode  # noqa: E402
from project_option_chain.live_worker import LiveState, LiveWorker  # noqa: E402
from project_option_chain.vix import VixResult  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "0930_588000SH2610.csv"
a = analyze_option_chain(FIX, SHIBOR_PATH)
chain = pd.read_csv(FIX)
base = LiveState(source="LIVE", analysis=a, chain=chain, full_chain=chain,
                 vix=VixResult(None, None, 35.0, "interpolated", ""), data_time=pd.Timestamp("2026-10-21 10:00:00"),
                 n_snapshots=1)

log = SL.new_log()
assert SL.append(log, base) and not SL.append(log, base)  # same snapshot counted once
row = log["rows"][0]
assert set(SL.SUMMARY_COLUMNS) == set(row)
assert abs(row["vrp30"] - (35.0 - a.metrics.iloc[0]["hv30"])) < 1e-3 and row["atm_iv_pct"] > 1
assert not SL.append(log, replace(base, source="STALE", n_snapshots=2))  # stale data not logged
for n in range(2, SL.MAX_SNAPSHOTS + 12):
    SL.append(log, replace(base, n_snapshots=n, data_time=base.data_time + pd.Timedelta(seconds=10 * n)))
assert len(log["snapshots"]) == SL.MAX_SNAPSHOTS and log["dropped_snapshots"] == 11
csv = SL.summary_csv(log).decode("utf-8-sig")
assert csv.splitlines()[0].split(",") == SL.SUMMARY_COLUMNS and len(csv.splitlines()) == len(log["rows"]) + 1
z = zipfile.ZipFile(io.BytesIO(SL.snapshots_zip(log)))
names = z.namelist()
assert "live_summary.csv" in names and sum(n.startswith("chains/") for n in names) == SL.MAX_SNAPSHOTS
print(f"session log OK: {len(log['rows'])} rows, {len(log['snapshots'])} snapshots, zip {len(names)} files")

# worker: 60-min interval, stop() returns promptly
calls = []
def fetcher(token, spot, archive):
    calls.append(time.time())
    return chain.assign(month="front")
w = LiveWorker("588000.SH", "tok", 3600, {"codes": {}}, SHIBOR_PATH, Path("/tmp/live_test"), fetcher=fetcher).start()
for _ in range(50):
    if w.snapshot().n_snapshots:
        break
    time.sleep(0.2)
assert w.snapshot().source == "LIVE", w.snapshot().last_error
t0 = time.time(); w.stop(); w._thread.join(10)
assert not w.alive and time.time() - t0 < 6, time.time() - t0
assert len(calls) == 1
print(f"worker long-interval stop OK ({time.time() - t0:.2f}s)")
assert archive_persist_mode() == "file"
print("ALL OK")
