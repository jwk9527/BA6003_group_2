"""Background live-data worker for the dashboard.

A single daemon thread per (spot, token, interval) fetches the realtime chain
from iFinD (token required; there is no sample/simulation fallback), runs the analytics and publishes the result to a thread-safe store.
The Streamlit page only *reads* the store, so the UI never waits on network.

Data-source states (``LiveState.source``):
- ``LIVE``        latest fetch succeeded.
- ``STALE``       latest fetch failed; the last good LIVE data is kept and
                  shown with the error. Never silently swapped for sample data.
- ``WAITING``     no snapshot yet (first fetch running or failed).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import pandas as pd

from .analytics import analyze_option_chain_frame, prepare_options
from .archive import load_archive
from .live import fetch_realtime_all
from .vix import VixResult, compute_vix
from .models import ChainAnalysis

HISTORY_COLUMNS = ["time", "source", "spot", "net_gex_million", "zero_gamma", "atm_iv", "call_wall", "put_wall"]
MAX_HISTORY = 5000
IDLE_STOP_SECONDS = 60.0  # stop when no page polled the worker for this long


@dataclass(frozen=True)
class LiveState:
    source: str = "WAITING"
    analysis: ChainAnalysis | None = None
    chain: pd.DataFrame | None = None          # front month (modules 1 & 2)
    full_chain: pd.DataFrame | None = None     # all fetched expiries (VIX)
    vix: VixResult | None = None
    data_time: pd.Timestamp | None = None      # when the shown data was fetched
    last_attempt: pd.Timestamp | None = None
    last_error: str | None = None
    fetch_seconds: float | None = None
    n_snapshots: int = 0
    history: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=HISTORY_COLUMNS))


class LiveWorker:
    def __init__(self, spot_code: str, token: str, interval_s: float, archive: "Path | dict",
                 shibor_path: Path, live_dir: Path,
                 fetcher: Callable[[str, str, dict], pd.DataFrame] = fetch_realtime_all) -> None:
        self.spot_code, self._token, self.interval_s = spot_code, token, float(interval_s)
        if not token:
            raise ValueError("An iFinD access token is required for live data.")
        # archive: a saved JSON path, or an in-memory dict (session-only archive on Cloud)
        self._archive = archive
        self.shibor_path = shibor_path
        self._last_read = time.monotonic()
        self.live_dir, self._fetcher = live_dir, fetcher
        self._lock = threading.Lock()
        self._state = LiveState(source="WAITING")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.snapshot_path = live_dir / f"{spot_code}.csv"
        self.intraday_path = live_dir / f"{spot_code}_intraday.csv"
        self._history_rows: list[dict] = self._load_today_history()
        self._thread = threading.Thread(target=self._run, name=f"live-{spot_code}", daemon=True)

    # ------------------------------------------------------------- public API
    def start(self) -> "LiveWorker":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh_now(self) -> None:
        self._wake.set()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def snapshot(self) -> LiveState:
        self._last_read = time.monotonic()  # page is alive (watchdog)
        with self._lock:
            return self._state

    # ------------------------------------------------------------- internals
    def _load_today_history(self) -> list[dict]:
        if not self.intraday_path.is_file():
            return []
        try:
            df = pd.read_csv(self.intraday_path, parse_dates=["time"])
        except Exception:
            return []
        today = pd.Timestamp.now().normalize()
        df = df[df["time"] >= today]
        return df.to_dict("records")

    def _fetch_chain(self) -> pd.DataFrame:
        archive = self._archive if isinstance(self._archive, dict) else load_archive(self._archive)
        return self._fetcher(self._token, self.spot_code, archive)

    def _tick(self) -> None:
        now = pd.Timestamp.now()
        t0 = time.perf_counter()
        try:
            full = self._fetch_chain()
            chain = full[full["month"] == "front"].reset_index(drop=True) if "month" in full else full
            analysis = analyze_option_chain_frame(chain, self.shibor_path)
            try:
                vix = compute_vix(prepare_options(full), self.shibor_path, roll_days=0)
            except Exception as exc:  # VIX is a bonus module; never fail the snapshot
                vix = VixResult(None, None, None, "unavailable", f"VIX failed: {exc}")
        except Exception as exc:  # keep last good data, mark stale
            err = f"{type(exc).__name__}: {exc}"
            with self._lock:
                prev = self._state
                src = prev.source
                if prev.analysis is not None and src in ("LIVE", "STALE"):
                    src = "STALE"
                elif prev.analysis is None:
                    src = "WAITING"
                self._state = replace(prev, source=src, last_attempt=now, last_error=err,
                                      fetch_seconds=time.perf_counter() - t0)
            return

        elapsed = time.perf_counter() - t0
        source = "LIVE"
        m = analysis.metrics.iloc[0]
        row = {"time": now, "source": source, **{k: m[k] for k in HISTORY_COLUMNS[2:]}}
        self._history_rows.append(row)
        del self._history_rows[:-MAX_HISTORY]
        self._persist(full, row)
        history = pd.DataFrame(self._history_rows, columns=HISTORY_COLUMNS)
        with self._lock:
            prev = self._state
            self._state = LiveState(source=source, analysis=analysis, chain=chain, full_chain=full, vix=vix, data_time=now,
                                    last_attempt=now, last_error=None, fetch_seconds=elapsed,
                                    n_snapshots=prev.n_snapshots + 1, history=history)

    def _persist(self, chain: pd.DataFrame, row: dict) -> None:
        try:
            self.live_dir.mkdir(parents=True, exist_ok=True)
            chain.to_csv(self.snapshot_path, index=False, encoding="utf-8-sig")
            header = not self.intraday_path.is_file()
            pd.DataFrame([row], columns=HISTORY_COLUMNS).to_csv(
                self.intraday_path, mode="a", header=header, index=False)
        except Exception:
            pass  # persistence is best-effort; never kill the worker

    def _run(self) -> None:
        while not self._stop.is_set():
            if time.monotonic() - self._last_read > IDLE_STOP_SECONDS:
                break  # no page has read the store for a while (tab closed) -> stop fetching
            started = time.monotonic()
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover - defensive
                with self._lock:
                    self._state = replace(self._state, last_error=f"worker: {exc}")
            wait = max(0.5, self.interval_s - (time.monotonic() - started))
            # long intervals: wake every few seconds to honour stop() / idle watchdog promptly
            deadline = time.monotonic() + wait
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._wake.wait(min(5.0, max(0.0, deadline - time.monotonic()))):
                    break
                if time.monotonic() - self._last_read > IDLE_STOP_SECONDS:
                    break
            self._wake.clear()
