# A-share ETF Option-Chain Dashboard (v5.1)

[English](#english) · [简体中文](#简体中文)

<a id="english"></a>
## English

### What it is

A Streamlit dashboard for A-share ETF options (510050, 510300, 510500, 588000, 588080). It is for research and education only. It shows definitions and computed figures and gives no trading advice.

- **History** (default page): daily option-chain metrics for 5 ETFs since listing. Metrics: net GEX, zero gamma, call/put walls, max pain, ATM IV, call/put IV smiles with a previous-day overlay, 25Δ skew, 30-day VIX (CBOE method), HV30/60/90 and VRP30. It also has an optional AI summary of the current view (OpenRouter).
- **Live**: the realtime main-contract (front-month) chain from iFinD. It needs your own iFinD token and shows ① OI & GEX, ② implied volatility, ③ VIX/VRP, plus a downloadable session log.

### For dashboard users

**Install and run locally (recommended)**

```bash
uv sync                                  # Python 3.13
uv run streamlit run dashboard.py
# or: python -m venv .venv && pip install -r requirements.txt && streamlit run dashboard.py
```

The AI summary is optional. To use it, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY=...` (default model `openai/gpt-4o-mini`, usage cap 10,000 calls). `.env` is git-ignored.

**History page**

1. Sidebar: choose the **ETF**. At the bottom are the VIX setting **Roll near month at <7 DTE** (off by default) and the data coverage.
2. **Single-day view**: pick a date to see the main-contract cards. The **volatility smile** can overlay the previous 1–5 trading days. The selected day is a solid, thick line; earlier days are thinner, fainter dashed lines in the same colour. Vertical lines show each day's ETF close. Below is the **contract lifetime** chart.
3. **Date-range view**: pick a range and either the main contract only or chosen expiry months. You get price & net GEX, VIX vs HV and VRP30, plus a data preview with CSV download and the optional AI summary.

**Live page**

1. Enter your personal **iFinD access token** in the sidebar. It stays in this browser session and is never stored in the repo or in logs.
2. Choose the **underlying** and review the **contract archive**: its source (built-in json, saved file, or session), `as_of` date and contract count.
3. When contracts roll or new strikes are listed, open **Update contract codes**. Paste the current **front-month** codes (and **next-month** codes, needed for the VIX interpolation and the next-month GEX view), pick a trading day, then click **Save archive**.
4. Pick a **refresh interval** (10 s, 30 s, 60 s, 15 / 30 / 60 min) and turn on **Live refresh**. The toggle is only enabled when a token and an archive are both available.
5. The **Session log** under the modules gets one row per successful refresh: time, spot, net GEX, zero gamma, walls, max pain, ATM IV, 25Δ skew, VIX30, VRP30. You can download a **summary CSV** or a **ZIP of the full-chain snapshots** (last 200) plus the summary, while Live runs or after you stop it.
6. The log lives only in browser-session memory and is **cleared when you reload the page**. Refreshing stops when Live is turned off or the browser tab is closed (the worker stops after about 60 s without a page reading it).

### For developers / maintainers

**Monthly history update (local only)**

1. Export the raw iFinD daily option history into a raw-data folder **outside the repo**, one folder per ETF named `<name>_<code>`, e.g. `historical_data/华夏科创50ETF期权_588000/`. File names follow `期权行情历史(...)_<year>前.csv` / `_<year>后.csv`. Required columns: 交易日期, 期权标的收盘价, 持仓量(手), 隐含波动率(%), Delta, Gamma, 距到期日剩余天数, 合约简称, 合约交易代码, 合约代码, 认购(C)认沽(P)类型, 行权价(元), 到期日, 结算价(元).
2. Build:
   ```bash
   uv sync --group local                      # once: installs akshare (not used on the cloud)
   uv run python scripts/build_history.py --raw /path/to/historical_data
   # options: --symbol 588000 · --list · --skip-shibor (reuse data/rates/shibor.parquet)
   ```
   This refreshes Shibor via akshare and rebuilds `data/history/<ETF>/{matrix,gex}.parquet` and `data/history/data_integrity.json`.
3. Run the tests, then commit the parquet files, `data_integrity.json` and `data/rates/shibor.parquet`.
4. Each month, also refresh the built-in Live archive `data/archives/<spot>.json`: run the app locally, save new codes, then commit the json.

**Tests**

```bash
for t in tests/test_*.py; do uv run python "$t" || break; done
```

The test files are `test_metrics`, `test_session_log`, `test_dashboard_app`, `test_history_app` and `test_ai_summary`.

**Structure**

```
dashboard.py                 router (History default, Live second)
app_pages/history.py, live.py
src/project_option_chain/    analytics, vix, rates, history, history_build, charts,
                             ifind, archive, live, live_worker, session_log, ai_summary, config, models
scripts/build_history.py     monthly local build · scripts/check_chain_csv.py
tests/                       script-style tests + fixtures
data/history/<ETF>/*.parquet, data/rates/shibor.parquet, data/archives/*.json
legacy/notebooks/            original research notebooks (reference)
```

**Metric conventions (shared by Live and History)**

- GEX = vendor gamma × OI × multiplier × spot² × 1%, calls +, puts −.
- Zero gamma: Black-Scholes gamma on a simulated spot grid (step 0.005, ±2σ of strikes) from spline IV smiles, T = DTE/**360**, rate = Shibor at the tenor; the reported value is the sign change nearest to spot.
- Walls: strike with the largest call / put OI. Max pain: strike minimising the total intrinsic value of open options.
- ATM IV: mean of call and put IV per strike, distance-weighted between the two strikes bracketing spot. 25Δ skew = IV(call Δ≈+0.25) − IV(put Δ≈−0.25).
- VIX30: CBOE formula with T = DTE/**365**, two nearest expiries interpolated in total variance to 30 days, **no roll by default**.
  - History prices options at the **settlement price** and also stores a 7-day-roll variant (`vix30_roll7`).
  - Live uses bid/ask mid (fallback last) and never rolls.
- HV: History = sample std of daily log returns × √252; Live = iFinD vendor HV. VRP30 = VIX30 − HV30.
- Rates: Shibor O/N…1Y, linearly interpolated to days to expiry.

**Deployment (Streamlit Community Cloud)**

- Main file `dashboard.py`, Python 3.13, dependencies from `uv.lock` / `requirements.txt` (no akshare).
- Secrets: `OPENROUTER_API_KEY` (optional `OPENROUTER_MODEL`, `AI_USAGE_CAP`, `ARCHIVE_PERSIST`); see `.streamlit/secrets.toml.example`.
- **Archive persistence**: `ARCHIVE_PERSIST=file|session`. The default is `session` on Streamlit Cloud (detected by `/mount/src` path or `appuser` user) and `file` elsewhere. In session mode a saved archive lives only in the browser session; use **Download archive json** and commit it to make it the built-in one.
- The AI usage counter (`ai_usage.json`) resets when the cloud container restarts. The iFinD API may require a mainland-China network, so Live may not work on the cloud.
- Never commit `.env`, `.streamlit/secrets.toml`, tokens or raw CSVs; they are git-ignored.

---

<a id="简体中文"></a>
## 简体中文

### 项目简介

A 股 ETF 期权（510050、510300、510500、588000、588080）Streamlit 看板。仅供研究与教学，只展示定义和计算结果，不构成任何交易建议。

- **History（历史，默认页）**：5 只 ETF 上市以来的每日期权链指标，包括净 GEX、zero gamma、认购/认沽墙、max pain、ATM IV、认购/认沽 IV 微笑（可叠加前几日）、25Δ skew、30 日 VIX（CBOE 方法）、HV30/60/90 和 VRP30；还可选用 AI 总结当前视图（OpenRouter）。
- **Live（实时）**：通过 iFinD 获取主力合约（近月）的实时期权链。需要个人 iFinD token，页面显示 ① 持仓量与 GEX、② 隐含波动率、③ VIX/VRP，并提供可下载的会话日志。

### 看板用户

**本地安装与运行（推荐）**

```bash
uv sync                                  # Python 3.13
uv run streamlit run dashboard.py
# 或：python -m venv .venv && pip install -r requirements.txt && streamlit run dashboard.py
```

AI 总结是可选功能。如需使用，把 `.env.example` 复制为 `.env`，填写 `OPENROUTER_API_KEY=...`（默认模型 `openai/gpt-4o-mini`，调用上限 10,000 次）。`.env` 不会进入 git。

**History 页面**

1. 侧边栏：选择 **ETF**。底部是 VIX 设置 **Roll near month at <7 DTE**（默认关闭）和数据覆盖范围。
2. **单日视图**：选择日期，查看主力合约指标卡。**波动率微笑**可叠加前 1–5 个交易日：当日为粗实线，越早的日期为越细、越淡的同色虚线；竖线表示各日的 ETF 收盘价。下方是**合约生命周期**图。
3. **区间视图**：选择日期区间，以及“仅主力合约”或指定到期月份，查看价格与净 GEX、VIX 与 HV 和 VRP30；还有数据预览、CSV 下载和可选的 AI 总结。

**Live 页面**

1. 在侧边栏输入个人 **iFinD access token**。它只保留在当前浏览器会话中，不会写入仓库或日志。
2. 选择**标的**，查看**合约档案**：来源（内置 json、已保存文件或会话）、`as_of` 日期和合约数量。
3. 合约换月或新增行权价时，展开 **Update contract codes**，粘贴当前**近月**代码（以及**次月**代码，VIX 插值和次月 GEX 视图需要），选择一个交易日，再点击 **Save archive**。
4. 选择**刷新间隔**（10 秒、30 秒、60 秒、15/30/60 分钟），然后打开 **Live refresh**。只有同时具备 token 和合约档案时，开关才可用。
5. 模块下方的 **Session log** 每次刷新成功记一行：时间、现价、净 GEX、zero gamma、认购/认沽墙、max pain、ATM IV、25Δ skew、VIX30、VRP30。运行中或停止后都可以下载**汇总 CSV**，或下载包含**全链快照**（最近 200 次）和汇总的 **ZIP**。
6. 日志只保存在浏览器会话内存中，**刷新页面即清空**。关闭 Live 或关闭浏览器标签页后刷新停止（约 60 秒无页面读取后，后台线程自动停止）。

### 开发者 / 维护者

**每月更新历史数据（仅本地）**

1. 把 iFinD 导出的原始日线期权数据放到**仓库以外**的原始数据目录，每个 ETF 一个文件夹，命名为 `<名称>_<代码>`，例如 `historical_data/华夏科创50ETF期权_588000/`。文件名为 `期权行情历史(...)_<年份>前.csv` 或 `_<年份>后.csv`。必需列：交易日期、期权标的收盘价、持仓量(手)、隐含波动率(%)、Delta、Gamma、距到期日剩余天数、合约简称、合约交易代码、合约代码、认购(C)认沽(P)类型、行权价(元)、到期日、结算价(元)。
2. 构建：
   ```bash
   uv sync --group local                      # 首次：安装 akshare（云端不使用）
   uv run python scripts/build_history.py --raw /path/to/historical_data
   # 选项：--symbol 588000 · --list · --skip-shibor（沿用现有 shibor.parquet）
   ```
   这一步会通过 akshare 更新 Shibor，并重建 `data/history/<ETF>/{matrix,gex}.parquet` 和 `data_integrity.json`。
3. 运行测试，然后提交 parquet 文件、`data_integrity.json` 和 `data/rates/shibor.parquet`。
4. 每月还要更新 Live 内置合约档案 `data/archives/<spot>.json`：在本地运行看板并保存新代码，然后提交该 json。

**测试**

```bash
for t in tests/test_*.py; do uv run python "$t" || break; done
```

**目录结构**：与英文部分相同（`dashboard.py` 路由，History 为默认页；`app_pages/`；`src/project_option_chain/`；`scripts/`；`tests/`；`data/`；`legacy/notebooks/`）。

**指标口径（Live 与 History 共用）**

- GEX = 数据商 gamma × 持仓量 × 合约乘数 × 现价² × 1%，认购为正、认沽为负。
- Zero gamma：用样条拟合的 IV 微笑，在模拟现价网格（步长 0.005，行权价 ±2σ）上重新计算 Black-Scholes gamma，T = 剩余天数/**360**，利率取对应期限的 Shibor；取离现价最近的变号点。
- 认购/认沽墙：认购/认沽持仓量最大的行权价。Max pain：使全部未平仓期权到期内在价值总和最小的行权价。
- ATM IV：每个行权价取认购和认沽 IV 的均值，在现价两侧的两个行权价之间按距离加权。25Δ skew = IV(认购 Δ≈+0.25) − IV(认沽 Δ≈−0.25)。
- VIX30：CBOE 公式，T = 剩余天数/**365**，最近两个到期月按总方差插值到 30 天，**默认不换月**。
  - History 用**结算价**计算，另外保存 7 天换月版本（`vix30_roll7`）。
  - Live 用买卖价中间价（缺失时用最新价），且始终不换月。
- HV：History 为日对数收益样本标准差 × √252；Live 使用 iFinD 提供的 HV。VRP30 = VIX30 − HV30。
- 利率：Shibor 隔夜至 1 年，按剩余天数线性插值。

**部署（Streamlit Community Cloud）**

- 主文件 `dashboard.py`，Python 3.13，依赖来自 `uv.lock` / `requirements.txt`（不含 akshare）。
- Secrets：`OPENROUTER_API_KEY`（可选 `OPENROUTER_MODEL`、`AI_USAGE_CAP`、`ARCHIVE_PERSIST`），参见 `.streamlit/secrets.toml.example`。
- **合约档案保存方式**：`ARCHIVE_PERSIST=file|session`。在 Streamlit Cloud 上默认是 `session`（通过 `/mount/src` 路径或 `appuser` 用户识别），其他环境默认是 `file`。session 模式下，保存的档案只存在于当前浏览器会话；可点 **Download archive json** 下载，再提交到仓库作为内置档案。
- 云端容器重启后，AI 调用计数（`ai_usage.json`）会清零。iFinD 接口可能需要中国大陆网络，因此 Live 在云端可能无法使用。
- 切勿提交 `.env`、`.streamlit/secrets.toml`、任何 token 或原始 CSV；这些都已加入 `.gitignore`。
