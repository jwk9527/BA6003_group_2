"""Built-in Live archives load and are consistent. Run: uv run python tests/test_archives.py"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from project_option_chain.archive import load_archive  # noqa: E402

EXPECT = {"588000.SH": (34, 32, "科创50"), "588080.SH": (34, 32, "科创板50")}
for spot, (n_front, n_next, prefix) in EXPECT.items():
    a = load_archive(ROOT / "data" / "archives" / f"{spot}.json")
    assert a["spot_code"] == spot and a["mul"] == 10000 and a["as_of_date"] == "2026-10-21"
    assert all(a[h] > 0 for h in ("hv30", "hv60", "hv90"))
    for block, n, month, exp in ((a["codes"], n_front, "10月", "2026-10-28"),
                                 (a["next"]["codes"], n_next, "11月", "2026-11-25")):
        assert len(block) == n, (spot, len(block))
        types = Counter(m["option_type"] for m in block.values())
        assert types["C"] == types["P"] == n // 2, types
        assert {m["expiry"] for m in block.values()} == {exp}
        assert all(m["name"].startswith(prefix) and month in m["name"] for m in block.values())
    assert not set(a["codes"]) & set(a["next"]["codes"])
print("archives OK")
