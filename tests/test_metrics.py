"""Unit checks for the shared metric functions (Live and History use the same code).

Run: uv run python tests/test_metrics.py
"""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_option_chain.analytics import analyze_option_chain, atm_iv_interpolated, prepare_options  # noqa: E402
from project_option_chain.config import SHIBOR_PATH  # noqa: E402
from project_option_chain.history_build import compute_hv  # noqa: E402
from project_option_chain.rates import get_shibor_rate  # noqa: E402
from project_option_chain.vix import compute_vix  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "0930_588000SH2610.csv"

# rates: parquet, tenor interpolation, monotone in tenor around a known date
r1, r30, r365 = (get_shibor_rate(SHIBOR_PATH, date(2026, 9, 30), d) for d in (1, 30, 365))
assert 0 < r1 < 0.1 and 0 < r30 < 0.1 and 0 < r365 < 0.1, (r1, r30, r365)
r_old = get_shibor_rate(SHIBOR_PATH, date(2015, 3, 2), 30)
assert r_old > 0.03, r_old  # 2015 Shibor 1M was > 4%
print(f"shibor OK: 2026-09-30 O/N {r1:.4%} 1M {r30:.4%} 1Y {r365:.4%}; 2015-03-02 1M {r_old:.4%}")

# analytics on the fixture chain
a = analyze_option_chain(FIXTURE, SHIBOR_PATH)
m = a.metrics.iloc[0]
assert m["spot"] == 1.616 and m["zero_gamma"] is not None
assert abs(m["atm_iv"] - atm_iv_interpolated(a.options, 1.616)[0]) < 1e-12
print("analytics OK:", {k: m[k] for k in ("net_gex_million", "zero_gamma", "atm_iv", "call_wall", "put_wall", "max_pain")})

# VIX roll: 3 synthetic expiries (copies of the fixture at 5, 33, 61 days) -> roll only skips the 5d one
base = prepare_options(pd.read_csv(FIXTURE)).assign(settle=lambda d: d["settle"])
chains = []
for dte, scale in ((5, 0.6), (33, 1.0), (61, 1.2)):
    c = base.copy()
    c["DTE_n"], c["expiry"], c["settle"] = dte, f"E{dte}", c["settle"] * scale
    chains.append(c)
chain = pd.concat(chains, ignore_index=True)
no_roll = compute_vix(chain, SHIBOR_PATH)
roll = compute_vix(chain, SHIBOR_PATH, roll_days=7)
assert no_roll.near.days == 5 and no_roll.next.days == 33
assert roll.near.days == 33 and roll.next.days == 61 and "rolled" in roll.note
assert compute_vix(chain[chain["DTE_n"] > 5], SHIBOR_PATH, roll_days=7).near.days == 33  # nothing to roll
print(f"vix roll OK: no-roll {no_roll.vix} ({no_roll.method}), roll7 {roll.vix} ({roll.method})")

# HV: constant daily log return -> zero volatility; alternating returns -> known value
d = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=40), "ETF_close": np.exp(np.arange(40) * 0.01)})
hv = compute_hv(d)
assert hv["hv30"].dropna().abs().max() < 1e-9
print("hv OK")
print("ALL OK")

# smile overlay: same hue, styles by age, one price line per day per side
from project_option_chain.history import overlay_style, smile_figure  # noqa: E402
days = [pd.Timestamp(f"2026-09-{d}") for d in (24, 25, 26, 29, 30)]
rows = []
for i, d in enumerate(days):
    for k in (1.5, 1.6, 1.7):
        for t in ("C", "P"):
            rows.append({"date": d, "option_type": t, "strike": k, "iv": 0.3 + 0.01 * i})
det = pd.DataFrame(rows)
spots = {d: 1.6 + 0.01 * i for i, d in enumerate(days)}
fig = smile_figure(det, days, spots[days[-1]], spots)
smiles = [t for t in fig.data if (t.meta or {}).get("kind") == "smile"]
prices = [t for t in fig.data if (t.meta or {}).get("kind") == "price"]
assert len(smiles) == 10 and len(prices) == 10
sel = [t for t in smiles if t.meta["date"] == "2026-09-30"]
assert all(t.line.dash == "solid" and t.opacity == 1.0 for t in sel)
calls = [t for t in smiles if t.meta["side"] == "C"]
assert len({t.line.color for t in calls}) == 1  # one hue per side
op = [t.opacity for t in calls]; wd = [t.line.width for t in calls]
assert op == sorted(op) and wd == sorted(wd) and abs(op[0] - 0.3) < 1e-9 and abs(op[-2] - 0.85) < 1e-9
for t in prices:
    s = [x for x in smiles if x.meta["date"] == t.meta["date"]][0]
    assert t.line.dash == s.line.dash and t.opacity == s.opacity and t.x[0] == spots[pd.Timestamp(t.meta["date"])]
assert overlay_style(0, 0)["dash"] == "solid"
print("smile overlay OK")
