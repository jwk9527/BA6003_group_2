"""i18n: every t("...") literal has a Chinese entry with the same placeholders;
History and Live pages render in both languages without errors.
Run: .venv/bin/python -m pytest tests/test_i18n.py  (or python tests/test_i18n.py)"""
import ast
import re
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from project_option_chain.i18n import t  # noqa: E402
from project_option_chain.i18n_zh import GUIDE_ZH, ZH, ZH_HELP  # noqa: E402
from project_option_chain.history import HELP, NAMES, ROLL_LABEL  # noqa: E402
from project_option_chain.market_hours import SESSIONS  # noqa: E402

SOURCES = [ROOT / "dashboard.py", *sorted((ROOT / "app_pages").glob("*.py")),
           *sorted((ROOT / "src" / "project_option_chain").glob("*.py"))]


def literal_keys():
    keys = set()
    for f in SOURCES:
        for n in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "t" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys.add(n.args[0].value)
    return keys


def test_every_key_has_chinese():
    missing = sorted(k for k in literal_keys() if k not in ZH)
    assert not missing, missing


def test_dynamic_keys_have_chinese():
    dynamic = [ROLL_LABEL, *NAMES.values(), "Main contract only (is_front)", "Choose expiry months",
               "Near", "Next", "E.Stabilizing", "E.Squeezing", "● LIVE",
               "▲ STALE · showing last good live data", "… WAITING for first snapshot"]
    dynamic += [s[2] for s in SESSIONS] + [s[4] for s in SESSIONS]
    assert [k for k in dynamic if k not in ZH] == []
    assert set(HELP) == set(ZH_HELP)
    assert "实时页面使用说明" in GUIDE_ZH


def test_placeholders_match_and_values_nonempty():
    for en, zh in ZH.items():
        assert zh.strip(), en
        assert sorted(re.findall(r"\{(\w+)\}", en)) == sorted(re.findall(r"\{(\w+)\}", zh)), en


def test_t_helper():
    assert t("Spot", lang="en") == "Spot"
    assert t("Spot", lang="zh") == "标的价格"
    assert t("{n} days", lang="zh", n=3) == "3 天"
    assert t("not a key", lang="zh") == "not a key"   # unknown -> English fallback
    assert t("Spot") == "Spot"                        # no Streamlit session -> English


def _run(page, lang):
    at = AppTest.from_file(str(ROOT / "app_pages" / page), default_timeout=180)
    at.session_state["lang"] = lang
    at.run()
    assert not at.exception, at.exception
    return at


def test_history_page_both_languages():
    en, zh = _run("history.py", "en"), _run("history.py", "zh")
    assert en.title[0].value == "ETF Option History: GEX & Volatility"
    assert zh.title[0].value == "ETF 期权历史：GEX 与波动率"
    assert not zh.error and len(zh.get("plotly_chart")) == len(en.get("plotly_chart")) > 0
    assert zh.radio(key="hist_mode").value == "Main contract only (is_front)"  # internal option unchanged


def test_live_page_both_languages():
    en, zh = _run("live.py", "en"), _run("live.py", "zh")
    assert any("How to use the Live page" in m.value for m in en.markdown)
    assert any("实时页面使用说明" in m.value for m in zh.markdown)
    assert zh.sidebar.text_input[0].label == "iFinD 访问令牌"
    assert any("A 股市场" in (getattr(e, "value", "") or "") for e in list(zh.success) + list(zh.warning))


def test_dashboard_language_toggle():
    at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=180).run()
    assert not at.exception, at.exception
    assert at.sidebar.radio(key="lang_choice").value == "en"
    at.sidebar.radio(key="lang_choice").set_value("zh").run()
    assert not at.exception, at.exception
    assert at.session_state["lang"] == "zh"
    assert at.title[0].value == "ETF 期权历史：GEX 与波动率"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print(name, "OK")


def test_ai_prompt_follows_language():
    from project_option_chain import ai_summary as AI
    en, zh = AI.system_prompt("en"), AI.system_prompt("zh")
    assert en == AI.SYSTEM_PROMPT and "Write in English" in en
    assert "Simplified Chinese" in zh and "Write in English" not in zh
    assert "conservative interpretations" in zh and "Do not give trading advice" in zh

    class Resp:  # minimal fake OpenAI client capturing the system prompt
        usage = None
        choices = [type("C", (), {"message": type("M", (), {"content": "摘要", "reasoning": None})(),
                                  "finish_reason": "stop"})()]
    seen = {}

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen.update(kw)
                    return Resp()
    out = AI.generate_view_summary("k", "view", None, "defs", client=Client(), count_usage=False,
                                   log_file=Path("/tmp/_ai_i18n_test.jsonl"), language="zh")
    assert out["text"] == "摘要" and "Simplified Chinese" in seen["messages"][0]["content"]
