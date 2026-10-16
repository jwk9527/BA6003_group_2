"""Monthly local build of the History data (NOT run on Streamlit Cloud).

Steps
-----
1. Refresh Shibor (O/N … 1Y) via akshare -> ``data/rates/shibor.parquet``.
2. For every ETF folder under the raw-data root (folder name ends with the
   6-digit code, e.g. ``华夏科创50ETF期权_588000``), merge all raw iFinD exports
   ``期权行情历史(...)_<year>前/后.csv`` and compute every metric with the same
   functions as the Live page (see ``project_option_chain.history_build``).
3. Write ``data/history/<code>/matrix.parquet`` + ``gex.parquet`` and
   ``data/history/data_integrity.json``. Commit these files; raw CSVs stay local.

Usage
-----
    uv sync --group local                               # once: installs akshare
    uv run python scripts/build_history.py --raw /path/to/historical_data
    uv run python scripts/build_history.py --raw ... --symbol 588000
    uv run python scripts/build_history.py --raw ... --list
    uv run python scripts/build_history.py --raw ... --skip-shibor   # offline: use existing shibor.parquet

The raw root may also be given by the env var ``HIST_RAW_DIR``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_option_chain import history_build as HB  # noqa: E402
from project_option_chain.config import HISTORY_DIR, SHIBOR_PATH  # noqa: E402
from project_option_chain.rates import SHIBOR_COLUMNS  # noqa: E402

AK_TENORS = {"O/N": "隔夜", "1W": "1周", "2W": "2周", "1M": "1月", "3M": "3月", "6M": "6月", "9M": "9月", "1Y": "1年"}


# ---------------------------------------------------------------- Shibor
def fetch_shibor() -> pd.DataFrame:
    """All Shibor fixings (percent) via akshare: rate_interbank per tenor, fallback macro_china_shibor_all."""
    try:
        import akshare as ak
    except ImportError:
        sys.exit("akshare is required to refresh Shibor (local only): run `uv sync --group local` "
                 "or `pip install akshare`, or pass --skip-shibor to reuse data/rates/shibor.parquet.")
    try:
        cols = []
        for col, ind in AK_TENORS.items():
            d = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator=ind)
            s = d.rename(columns={"报告日": "Date", "利率": col})[["Date", col]]
            s["Date"] = pd.to_datetime(s["Date"])
            cols.append(s.set_index("Date")[col])
            time.sleep(0.5)
        out = pd.concat(cols, axis=1).sort_index().reset_index()
        source = "rate_interbank"
    except Exception as exc:  # noqa: BLE001
        print(f"  rate_interbank failed ({exc}); falling back to macro_china_shibor_all")
        d = ak.macro_china_shibor_all()
        out = d.rename(columns={"日期": "Date", **{f"{c}-定价": c for c in SHIBOR_COLUMNS}})[["Date", *SHIBOR_COLUMNS]]
        out["Date"] = pd.to_datetime(out["Date"])
        source = "macro_china_shibor_all"
    out = out.dropna(subset=list(SHIBOR_COLUMNS), how="all").sort_values("Date").reset_index(drop=True)
    print(f"  Shibor via {source}: {len(out)} fixings {out['Date'].min():%Y-%m-%d} … {out['Date'].max():%Y-%m-%d}")
    return out


def update_shibor() -> None:
    new = fetch_shibor()
    if SHIBOR_PATH.is_file():  # keep older fixings the API may no longer return
        old = pd.read_parquet(SHIBOR_PATH)
        new = pd.concat([old, new]).drop_duplicates("Date", keep="last").sort_values("Date")
    SHIBOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    new.reset_index(drop=True).to_parquet(SHIBOR_PATH, index=False, compression="zstd")
    print(f"  -> {SHIBOR_PATH.relative_to(ROOT)} ({len(new)} rows)")


# ---------------------------------------------------------------- ETFs
def discover(raw_root: Path) -> dict[str, Path]:
    out = {}
    for d in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        code = d.name[-6:]
        if code.isdigit() and any(HB.RAW_PATTERN.match(f.name) for f in d.glob("*.csv")):
            out[code] = d
    return out


def build_one(code: str, raw_dir: Path) -> dict:
    t0 = time.time()
    print(f"\n===== {code} ({raw_dir.name}) =====")
    df = HB.load_symbol(raw_dir)
    print(f"  raw rows {len(df)} · {df['date'].nunique()} trading days "
          f"{df['date'].min():%Y-%m-%d} … {df['date'].max():%Y-%m-%d}")
    matrix, gex = HB.build_tables(df, SHIBOR_PATH)
    out = HISTORY_DIR / code
    out.mkdir(parents=True, exist_ok=True)
    for name, table in (("matrix", matrix), ("gex", gex)):
        tmp = out / f"{name}.parquet.tmp"
        table.to_parquet(tmp, index=False, compression="zstd", row_group_size=50_000)
        tmp.replace(out / f"{name}.parquet")
    print(f"  matrix {len(matrix)} rows · gex {len(gex)} rows · {time.time() - t0:.0f}s")
    return {"etf": code, "first_date": f"{matrix['date'].min():%Y-%m-%d}",
            "last_date": f"{matrix['date'].max():%Y-%m-%d}", "trading_days": int(matrix["date"].nunique())}


def write_manifest(info: dict[str, dict]) -> None:
    path = HISTORY_DIR / "data_integrity.json"
    try:
        old = {r["etf"]: r for r in json.loads(path.read_text("utf-8")).get("etfs", [])}
    except (OSError, ValueError, AttributeError):
        old = {}
    old.update(info)
    files = []
    for f in sorted(HISTORY_DIR.glob("*/*.parquet")):
        files.append({"path": f"{f.parent.name}/{f.name}", "bytes": f.stat().st_size,
                      "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    path.write_text(json.dumps({"built_at": datetime.now().isoformat(timespec="seconds"),
                                "etfs": sorted(old.values(), key=lambda r: r["etf"]), "files": files},
                               ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  -> {path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build History parquet files from raw iFinD exports (local, monthly).")
    ap.add_argument("--raw", type=Path, default=os.environ.get("HIST_RAW_DIR"),
                    help="raw data root containing one folder per ETF (or env HIST_RAW_DIR)")
    ap.add_argument("--symbol", help="only build ETFs whose code contains this text, e.g. 588000")
    ap.add_argument("--list", action="store_true", help="only list the ETF folders found")
    ap.add_argument("--skip-shibor", action="store_true", help="do not refresh Shibor (use existing parquet)")
    args = ap.parse_args()
    if not args.raw or not Path(args.raw).is_dir():
        sys.exit("Raw data root not found: pass --raw /path/to/historical_data (or set HIST_RAW_DIR).")
    symbols = discover(Path(args.raw))
    if args.symbol:
        symbols = {k: v for k, v in symbols.items() if args.symbol in k}
    if not symbols:
        sys.exit(f"No ETF folders with raw exports found under {args.raw}")
    print("ETFs:", ", ".join(f"{k} ({v.name})" for k, v in symbols.items()))
    if args.list:
        return
    if args.skip_shibor:
        if not SHIBOR_PATH.is_file():
            sys.exit(f"{SHIBOR_PATH} missing; run once without --skip-shibor.")
    else:
        print("\nRefreshing Shibor …")
        update_shibor()
    info = {}
    for code, d in symbols.items():
        try:
            info[code] = build_one(code, d)
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {code}: {exc}")
    write_manifest(info)
    print("Done. Commit data/history/*/*.parquet, data/history/data_integrity.json and data/rates/shibor.parquet.")


if __name__ == "__main__":
    main()
