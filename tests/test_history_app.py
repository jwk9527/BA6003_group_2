"""AppTest smoke test: 5 ETFs x default / older date, smile overlay 0/5, range main-only / multi-month.
Run: uv run python tests/test_history_app.py"""
import time
from datetime import date
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app_pages" / "history.py")
OLD = {"510050": date(2020, 3, 16), "510300": date(2020, 6, 15), "510500": date(2023, 1, 9),
       "588000": date(2024, 2, 5), "588080": date(2024, 2, 5)}

def check(at, tag):
    assert not at.exception, (tag, at.exception)
    assert not at.error, (tag, [e.value for e in at.error])
    return len(at.get("plotly_chart"))

for code, old in OLD.items():
    t = time.time()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.sidebar.selectbox(key="hist_etf").set_value(code).run()
    n = check(at, code); t1 = time.time() - t
    days = [date(2026, 9, 30), old] if code == "510050" else [old]
    for d in days:
        t = time.time()
        at.date_input(key="hist_day").set_value(d).run(); check(at, (code, d))
        at.select_slider(key="hist_prev").set_value(5).run(); n5 = check(at, (code, d, 5))
        at.select_slider(key="hist_prev").set_value(0).run()
        print(f"{code} {d} charts={n5} {time.time()-t:.1f}s")
    at.radio(key="hist_mode").set_value("Choose expiry months").run(); nm = check(at, (code, "multi"))
    at.date_input(key="hist_range").set_value((date(2019, 1, 1), date(2026, 9, 30))).run(); check(at, (code, "wide"))
    print(f"{code} default charts={n} first-load {t1:.1f}s multi charts={nm}")
print("ALL OK")

# Router: default page (Live) renders, then switch to History.
at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=120).run()
assert not at.exception, at.exception
at.switch_page("app_pages/history.py").run()
assert not at.exception, at.exception
print("router OK; history charts", len(at.get("plotly_chart")))

# VIX roll toggle switches the VIX card / chart without errors
at = AppTest.from_file(APP, default_timeout=180).run()
at.sidebar.selectbox(key="hist_etf").set_value("588000").run()
at.date_input(key="hist_day").set_value(date(2026, 9, 30)).run()
card = {m.label: m.value for m in at.metric}
assert card["VIX (30-day)"] == "34.59", card
assert card["ATM IV"] == "32.44%", card
at.sidebar.toggle(key="hist_vix_roll").set_value(True).run(); check(at, "roll")
print("588000 2026-09-30 cards OK:", card["VIX (30-day)"], card["ATM IV"], card["VRP30"], "; roll toggle OK")
