"""Built-in Live archives load and are consistent; Live lists and loads all six.
Run: uv run python tests/test_archives.py"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from project_option_chain.archive import load_archive  # noqa: E402

# spot: (front n, next n, name prefix, as_of)
EXPECT = {
    "588000.SH": (34, 32, "科创50", "2026-10-21"),
    "588080.SH": (34, 32, "科创板50", "2026-10-21"),
    "510050.SH": (26, 24, "50ETF", "2026-10-22"),
    "510300.SH": (28, 26, "300ETF", "2026-10-22"),
    "510500.SH": (28, 26, "500ETF", "2026-10-22"),
    "159915.SZ": (36, 38, "创业板ETF", "2026-10-22"),
}
for spot, (n_front, n_next, prefix, as_of) in EXPECT.items():
    a = load_archive(ROOT / "data" / "archives" / f"{spot}.json")
    assert a["spot_code"] == spot and a["mul"] == 10000 and a["as_of_date"] == as_of, spot
    assert all(a[h] > 0 for h in ("hv30", "hv60", "hv90")), spot
    suffix = spot.split(".")[1]
    for block, n, month, exp in ((a["codes"], n_front, "10月", "2026-10-28"),
                                 (a["next"]["codes"], n_next, "11月", "2026-11-25")):
        assert len(block) == n, (spot, len(block))
        assert all(c.endswith("." + suffix) for c in block), spot
        types = Counter(m["option_type"] for m in block.values())
        assert types["C"] == types["P"] == n // 2, (spot, types)
        ks = {t: sorted(m["strike"] for m in block.values() if m["option_type"] == t) for t in "CP"}
        assert ks["C"] == ks["P"], spot
        assert {m["expiry"] for m in block.values()} == {exp}, spot
        assert all(m["name"].startswith(prefix) and month in m["name"] for m in block.values()), spot
    assert not set(a["codes"]) & set(a["next"]["codes"]), spot
print("archives OK:", len(EXPECT))

# Live page: dropdown lists all six; each loads its built-in archive without errors
from streamlit.testing.v1 import AppTest  # noqa: E402
at = AppTest.from_file(str(ROOT / "app_pages" / "live.py"), default_timeout=120).run()
sb = next(s for s in at.sidebar.selectbox if s.label == "Underlying ETF")
assert set(EXPECT) <= set(sb.options), sb.options
for spot, (n_front, n_next, *_ ) in EXPECT.items():
    sb.set_value(spot)
    at.run()
    assert not at.exception, (spot, at.exception)
    sb = next(s for s in at.sidebar.selectbox if s.label == "Underlying ETF")
    text = " ".join(c.value for c in at.sidebar.caption) + " ".join(m.value for m in at.sidebar.markdown)
    assert f"front {n_front} contracts" in text and f"({n_next})" in text, (spot, text[:300])
print("live dropdown OK")
