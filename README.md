# A-share ETF Option-Chain Dashboard (V4 final)

Streamlit multipage app for A-share ETF options (510050, 510300, 510500, 588000, 588080):

| Page | File | Content |
|---|---|---|
| **Live** | `app_pages/live.py` | Realtime iFinD option chain: ① OI & GEX by strike, aggregate GEX curve, zero gamma, walls, max pain (optional next-month merge); ② ATM IV, 25Δ skew, HV, volatility smile; ③ 30-day VIX (CBOE method on bid/ask mid), VRP30. Needs an iFinD token; without one the page shows a usage guide (no sample data). |
| **History** | `app_pages/history.py` | Daily history since listing: single-day cards, call/put smiles with previous-day overlay, contract-lifetime levels, price & net GEX, VIX vs HV30/60/90, VRP30, CSV download, optional AI summary of the view. |

Live and History compute every metric with the **same functions** (`src/project_option_chain/analytics.py`, `vix.py`, `rates.py`).

## Metric definitions (shared)

- **GEX per contract** = vendor gamma × OI × multiplier × spot² × 1%, calls +, puts −; net GEX in M CNY.
- **Aggregate GEX curve / zero gamma**: Black-Scholes gamma re-computed on a simulated spot grid (±2σ of strikes, step 0.005) using cubic-spline call/put IV smiles in K/S, OI fixed, T = DTE/360, rate = Shibor at the tenor; zero gamma = sign change nearest to spot.
- **Call / put wall**: strike with the largest call / put OI. **Max pain**: strike minimising the total intrinsic value of open options.
- **ATM IV**: mean of call and put IV per strike, inverse-distance weighted between the two strikes bracketing spot.
- **25Δ skew**: IV(call Δ≈+0.25) − IV(put Δ≈−0.25).
- **VIX (30-day)**: CBOE/iVIX variance formula per expiry (T = days/365, forward from put-call parity, K0 ≤ F, OTM prices), two nearest expiries interpolated in total variance to 30 days. Prices: Live = bid/ask mid (fallback last), History = daily **settlement** price. History stores both no-roll (`vix30`, default) and a 7-day near-month roll (`vix30_roll7`); the sidebar toggle *Roll near month at <7 DTE* switches between them. Live never rolls (only front + next month codes are archived).
- **HV**: History = sample std of daily log returns × √252 (30/60/90 days); Live = iFinD vendor HV.
- **VRP30** = VIX (30-day) − HV30.
- **Risk-free rate**: Shibor (O/N … 1Y) linearly interpolated to each expiry's days to expiry (`data/rates/shibor.parquet`).

## Project layout

```
dashboard.py                  # router (st.navigation)
app_pages/live.py             # Live page (UI)
app_pages/history.py          # History page (UI)
src/project_option_chain/
  analytics.py                # GEX, zero gamma, walls, max pain, ATM IV, skew
  vix.py                      # CBOE 30-day VIX (roll_days option)
  rates.py                    # Shibor lookup + tenor interpolation (cached)
  charts.py                   # Plotly figures + theme
  history.py                  # History data loading + charts
  history_build.py            # History build library (raw exports -> parquet)
  ifind.py, archive.py, live.py, live_worker.py   # iFinD API, contract archive, realtime worker
  ai_summary.py               # OpenRouter summary of the History view
  config.py, models.py
scripts/build_history.py      # LOCAL monthly build (akshare Shibor + raw CSVs -> parquet)
scripts/check_chain_csv.py    # manual validator for a chain CSV
tests/                        # script-style tests + fixtures
data/history/<ETF>/{matrix,gex}.parquet, data/history/data_integrity.json
data/rates/shibor.parquet
data/archives/<spot>.json     # saved Live contract archive (example)
legacy/notebooks/             # original research notebooks (reference only)
```

## Setup (local)

```bash
uv sync                                   # Python 3.13, runtime deps
cp .env.example .env                      # then paste OPENROUTER_API_KEY=... (optional, AI summary)
uv run streamlit run dashboard.py
```

The iFinD token is typed into the Live page sidebar and is never stored. The OpenRouter key lives only in `.env` (git-ignored) or in Streamlit Secrets.

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub (`.env`, CSVs, logs are git-ignored; only slim parquet data is committed, ~10 MB).
2. New app → main file `dashboard.py`, Python 3.13. Dependencies come from `uv.lock` / `requirements.txt` (akshare is not included).
3. App settings → Secrets: `OPENROUTER_API_KEY = "..."` (optional `OPENROUTER_MODEL`). See `.streamlit/secrets.toml.example`.
4. The AI summary has a usage cap of 10,000 calls (counter in `ai_usage.json`, git-ignored; override with `AI_USAGE_CAP`). On Cloud the counter resets when the container restarts.
5. Live data requires each user's own iFinD token and network access to the iFinD API.

## Monthly data update (developer, local)

1. Export the new daily option history from iFinD into the raw folder, one folder per ETF whose name ends with the code, e.g. `historical_data/华夏科创50ETF期权_588000/期权行情历史(华夏科创50ETF期权_588000)_2026后.csv` (append or replace the `_2026后` file; all `_<year>前/后.csv` files are merged and de-duplicated on date + contract).
2. Run the build (refreshes Shibor via akshare, rebuilds all ETFs, ~5–10 min):
   ```bash
   uv sync --group local                         # once: installs akshare
   uv run python scripts/build_history.py --raw /path/to/historical_data
   ```
   Options: `--symbol 588000`, `--list`, `--skip-shibor` (offline).
3. Run the tests, then commit `data/history/*/*.parquet`, `data/history/data_integrity.json`, `data/rates/shibor.parquet` and push. Streamlit Cloud redeploys automatically.

## Tests

```bash
for t in tests/test_*.py; do uv run python "$t" || break; done
```

`test_metrics.py` (shared metric functions), `test_dashboard_app.py` (Live page without token / failed fetch), `test_history_app.py` (all ETFs, roll toggle, reference numbers), `test_ai_summary.py` (mocked API, logging, usage cap).
