"""Developer console input_contract_list.py: parsing, normalisation, checks, backup+write.
Run: .venv/bin/python -m pytest tests/test_input_contract_list.py"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import input_contract_list as C  # noqa: E402

BUILTIN = json.loads((ROOT / "data" / "archives" / "588000.SH.json").read_text("utf-8"))


@pytest.mark.parametrize("raw,want", [("588000SH", "588000.SH"), ("588000.SH", "588000.SH"), ("588000", "588000.SH"),
                                      ("159915SZ", "159915.SZ"), ("159915", "159915.SZ"), (" 510300.sh ", "510300.SH"),
                                      ("512100", "512100.SH")])
def test_normalize_underlying(raw, want):
    assert C.normalize_underlying(raw) == want


@pytest.mark.parametrize("raw", ["58800", "588000.SS", "abc", "159915.SH", "300750"])
def test_normalize_underlying_rejects(raw):
    with pytest.raises(ValueError):
        C.normalize_underlying(raw)


def test_tags():
    assert C.parse_tag(" 2611 ") == "2611"
    for bad in ("261", "2613", "26-11"):
        with pytest.raises(ValueError):
            C.parse_tag(bad)
    assert C.order_tags("2611", "2612") == ("2611", "2612", [])
    f, n, w = C.order_tags("2612", "2611")
    assert (f, n) == ("2611", "2612") and w
    assert C.order_tags("2611", "2611")[2]


def test_parse_option_codes():
    text = "'10012363.SH,10012364.SH'\n10012364.SH 10012365\n90006001.SZ, junk"
    codes, invalid, dups = C.parse_option_codes(text, "SH")
    assert codes == ["10012363.SH", "10012364.SH", "10012365.SH"]
    assert dups == ["10012364.SH"] and invalid == ["90006001.SZ", "junk"]


def test_last_weekday():
    assert C.last_weekday(date(2026, 10, 31)) == date(2026, 10, 30)  # Saturday -> Friday
    assert C.last_weekday(date(2026, 10, 27)) == date(2026, 10, 27)


def _fake_archive():
    front = {c: m for c, m in list(BUILTIN["codes"].items())[:4]}
    nxt = {c: m for c, m in list(BUILTIN["next"]["codes"].items())[:4]}
    return {**{k: BUILTIN[k] for k in ("hv30", "hv60", "hv90", "mul")}, "spot_code": "588000.SH",
            "as_of_date": "2026-10-27", "codes": front, "next": {"expiry": BUILTIN["next"]["expiry"], "codes": nxt}}


def test_check_archive():
    arc = _fake_archive()
    assert C.check_archive(arc, "2610", "2611") == []
    probs = C.check_archive(arc, "2611", "2612")
    assert any("expected 11" in p for p in probs) and any("expected 12" in p for p in probs)
    arc["missing"] = ["10099999.SH"]
    assert any("not found by iFinD" in p for p in C.check_archive(arc, "2610", "2611"))


def test_offline_archive_and_schema():
    front, nxt = list(BUILTIN["codes"])[:3], list(BUILTIN["next"]["codes"])[:3]
    arc, unknown = C.offline_archive(BUILTIN, "588000.SH", front, nxt, "2026-10-27")
    assert unknown == [] and set(arc) == {"spot_code", "as_of_date", "hv30", "hv60", "hv90", "mul", "codes", "next"}
    assert arc["as_of_date"] == "2026-10-27" and list(arc["codes"]) == front and list(arc["next"]["codes"]) == nxt
    assert set(arc["next"]) == {"expiry", "codes"}
    assert C.offline_archive(BUILTIN, "588000.SH", front + ["10099999.SH"], nxt, "2026-10-27") == (None, ["10099999.SH"])


def test_backup_and_save(tmp_path):
    path, backup_dir = tmp_path / "588000.SH.json", tmp_path / "backup"
    assert C.backup_and_save(path, {"a": 1}, backup_dir) is None          # new file, nothing to back up
    b = C.backup_and_save(path, _fake_archive(), backup_dir, now=datetime(2026, 10, 27, 9, 30))
    assert b.name == "588000.SH_20261027_093000.json" and json.loads(b.read_text()) == {"a": 1}
    assert json.loads(path.read_text("utf-8"))["as_of_date"] == "2026-10-27"


def test_main_offline_flow(tmp_path, monkeypatch):
    """Whole console with scripted input, no iFinD (codes reused from the archive)."""
    src = tmp_path / "588000.SH.json"
    src.write_text(json.dumps(BUILTIN, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(C, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(C, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.delenv("IFIND_TOKEN", raising=False)
    front, nxt = list(BUILTIN["codes"])[:2], list(BUILTIN["next"]["codes"])[:2]
    answers = iter(["588000SH", "2611", "2610", "\n".join(front), "", ",".join(nxt), "", "n", "y"])  # reversed tags -> swapped
    assert C.main(inp=lambda *_: next(answers)) == 0
    out = json.loads(src.read_text("utf-8"))
    assert list(out["codes"]) == front and list(out["next"]["codes"]) == nxt
    assert len(list((tmp_path / "backup").glob("588000.SH_*.json"))) == 1
