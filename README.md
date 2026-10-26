# A-share ETF Option-Chain Dashboard (v0.5.3)


---
## 0.5.3 Update:

- Add CN translation
- Add input_contract_list.py into project file
---
## 0.5.2 Version

[English](#english) · [中文简介](#中文简介)

<a id="english"></a>
## English

### What it is

A Streamlit dashboard for A-share ETF options (510050, 510300, 510500, 588000, 588080). It is for research and education only. It shows definitions and computed figures and gives no trading advice.

- **History** (default page): daily option-chain metrics for 5 ETFs since listing. Metrics: net GEX, zero gamma, call/put walls, max pain, ATM IV, call/put IV smiles with a previous-day overlay, 25Δ skew, 30-day VIX (CBOE method), HV30/60/90 and VRP30. It also has an optional AI summary of the current view (OpenRouter).
- **Live**: the realtime main-contract (front-month) chain from iFinD. It needs your own iFinD token and shows ① OI & GEX, ② implied volatility, ③ VIX/VRP, plus a downloadable session log.

### Our Benchmarks

- openvlab.cn: providing partial A-share ETF options info with premium required. still WIP
- Futu app: providing sufficiently mature option chains info, but does not cover the A-share
- unusualwhales.com: providing advanced option chain analysis with premium required.
- SpotGamma.com: providing US option info, with premium required
  
### Our Uniqueness
- A-share ETF oriented, providing open dashboard and transparent pipeline, back-testing supported.

### For dashboard users

**Install and run locally (recommended)**

```bash
uv sync                                  # Python 3.13
uv run streamlit run dashboard.py
# or: python -m venv .venv && pip install -r requirements.txt && streamlit run dashboard.py
```

The AI summary is optional. To use it, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY=...` (default model `deepseek/deepseek-v4.1-flash`, usage cap 10,000 calls). `.env` is git-ignored.

**History page**

1. Sidebar: choose the **ETF**. At the bottom are the VIX setting **Roll near month at <7 DTE** (off by default) and the data coverage.
2. **Single-day view**: pick a date to see the main-contract cards. The **volatility smile** can overlay the previous 1–5 trading days; untick **Overlay previous days** to show only the single day N trading days back. The selected day is a solid, thick line; earlier days are thinner, fainter dashed lines in the same colour. Vertical lines show each day's ETF close. Below is the **contract lifetime** chart.
3. **Date-range view**: pick a range and either the main contract only or chosen expiry months. You get price & net GEX, VIX vs HV and VRP30, plus a data preview with CSV download and the optional AI summary.
4. **AI summary — use your own LLM API**: turn on *Summarize current view (AI)* and open **Use your own LLM API**. Enter an API key for any OpenAI-compatible endpoint, plus optional **Model** (default `deepseek/deepseek-v4.1-flash`) and **Base URL** (default `https://openrouter.ai/api/v1`). The key stays only in this browser session; it is never saved, logged or shown. Leave it empty to use the app default key from `.env` / Secrets; a caption shows "Using your key" or "Using app default key". The 10,000-call usage cap applies only to the app default key; calls time out after 45 s.

**Live page**

1. Enter your personal **iFinD access token** in the sidebar. It stays in this browser session and is never stored in the repo or in logs.
1a. The page header shows whether the A-share market is open (Asia/Shanghai time: call auction, open, lunch break, closed, weekend; exchange holidays are not covered).
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

**Formulas (as implemented in `src/project_option_chain/`)**

Notation: $S$ spot (ETF close or last), $K_i$ strike, $OI_i$ open interest, $M$ contract multiplier, $\Gamma_i$ vendor gamma, $\sigma_i$ implied volatility, $\mathbb{1}_C=+1$ for calls and $-1$ for puts, $N$ calendar days to expiry.

*Gamma exposure (GEX, per contract and net; `analytics.py`)*

$$\mathrm{GEX}_i = \mathbb{1}_C\,\Gamma_i\,OI_i\,M\,S^2\times 0.01,\qquad \mathrm{NetGEX}=\frac{1}{10^6}\sum_i \mathrm{GEX}_i\ \text{(shown in millions)}$$

*GEX curve and zero gamma.* Call and put smiles are cubic splines $\hat\sigma_C(m),\hat\sigma_P(m)$ in moneyness $m=K/S$. On a grid $s\in[\max(S-2\,\mathrm{sd}(K),K_{\min}),\ \min(S+2\,\mathrm{sd}(K),K_{\max})]$ with step $0.005$, $\tau=N/360$ and $r=$ Shibor at tenor $N$:

$$\sigma_i(s)=\mathrm{clip}\big(\hat\sigma(K_i/s),\,0.01,\,5\big),\quad d_1=\frac{\ln(s/K_i)+(r+\tfrac12\sigma_i^2)\tau}{\sigma_i\sqrt\tau},\quad \Gamma_i^{BS}(s)=\frac{\varphi(d_1)}{s\,\sigma_i\sqrt\tau}$$

$$G(s)=\sum_i \mathbb{1}_C\,\Gamma_i^{BS}(s)\,OI_i\,M\,s^2\times0.01,\qquad \text{ZeroGamma}=\arg\min_{s_j:\ G(s_j)G(s_{j-1})<0}|s_j-S|$$

(The merged front+next view sums one such curve per expiry, each with its own $\tau$, $r$ and smile.)

*Walls and max pain*

$$\text{CallWall}=\arg\max_K\sum_{i\in C,K_i=K}OI_i,\qquad \text{PutWall}=\arg\max_K\sum_{i\in P,K_i=K}OI_i$$

$$\text{MaxPain}=\arg\min_{K^{\ast}}\Big[\sum_{i\in C}OI_i\max(0,K^{\ast}-K_i)+\sum_{i\in P}OI_i\max(0,K_i-K^{\ast})\Big]$$

*ATM IV.* $\bar\sigma(K)$ = mean of the call and put IVs ($>0$) at strike $K$; with $K_{lo}=\max\{K\le S\}$, $K_{hi}=\min\{K\ge S\}$:

$$\sigma_{ATM}=w\,\bar\sigma(K_{lo})+(1-w)\,\bar\sigma(K_{hi}),\qquad w=\frac{K_{hi}-S}{K_{hi}-K_{lo}}$$

(if $S$ is on a strike or outside the strike range, $\bar\sigma$ of the nearest strike is used).

*25Δ skew.* With $c^{\ast}=\arg\min_{i\in C}|\Delta_i-0.25|$ and $p^{\ast}=\arg\min_{i\in P}|\Delta_i+0.25|$:

$$\text{Skew}_{25\Delta}=\sigma_{c^{\ast}}-\sigma_{p^{\ast}}$$

*VIX (CBOE method; `vix.py`).* For each expiry $j$: $T_j=N_j/365$, $R_j$ = Shibor at $N_j$. Option price = mid(bid, ask), else last, else settlement (History uses settlement only).

$$F_j=K^{\ast}+e^{R_jT_j}\,(C(K^{\ast})-P(K^{\ast})),\quad K^{\ast}=\arg\min_K|C(K)-P(K)|,\qquad K_0=\max\{K_i\le F_j\}$$

$$Q(K_i)=\begin{cases}P(K_i)&K_i<K_0\\ \tfrac12\,(C(K_0)+P(K_0))&K_i=K_0\\ C(K_i)&K_i>K_0\end{cases}\qquad \Delta K_i=\frac{K_{i+1}-K_{i-1}}{2}\ \ (\text{one-sided at the ends})$$

$$\sigma_j^2=\frac{2}{T_j}\sum_i\frac{\Delta K_i}{K_i^2}\,e^{R_jT_j}\,Q(K_i)-\frac{1}{T_j}\Big(\frac{F_j}{K_0}-1\Big)^2$$

30-day constant maturity (linear in total variance; extrapolation if both expiries lie on one side of 30 days):

$$\mathrm{VIX}=100\sqrt{\Big[T_1\sigma_1^2\frac{N_2-N_{30}}{N_2-N_1}+T_2\sigma_2^2\frac{N_{30}-N_1}{N_2-N_1}\Big]\frac{365}{N_{30}}},\qquad N_{30}=30$$

With a single usable expiry, $\mathrm{VIX}\approx100\,\sigma_1$. **No roll** (`vix30`, default, and Live): expiries 1, 2 are the two nearest. **Roll 7** (`vix30_roll7`, History toggle): if $N_1<7$ and a third expiry exists, expiries 2 and 3 are used.

*Historical volatility and VRP (`history_build.py`).* With $r_t=\ln(S_t/S_{t-1})$ and window $n\in\{30,60,90\}$ trading days:

$$\mathrm{HV}_n=100\sqrt{252}\;\sqrt{\frac{1}{n-1}\sum_{t}(r_t-\bar r)^2},\qquad \mathrm{VRP}_{30}=\mathrm{VIX}_{30}-\mathrm{HV}_{30}$$

*Shibor tenor interpolation (`rates.py`).* Latest fixing on or before the valuation date; nodes $d\in\{1,7,14,30,90,180,270,365\}$ days (O/N…1Y), flat beyond the ends:

$$r(N)=r(d_k)+\frac{N-d_k}{d_{k+1}-d_k}\big(r(d_{k+1})-r(d_k)\big),\qquad d_k\le N\le d_{k+1}$$

**Deployment (Streamlit Community Cloud)**

- Main file `dashboard.py`, Python 3.13, dependencies from `uv.lock` / `requirements.txt` (no akshare).
- Secrets: `OPENROUTER_API_KEY` (optional `OPENROUTER_MODEL`, `AI_USAGE_CAP`, `ARCHIVE_PERSIST`); see `.streamlit/secrets.toml.example`.
- **Archive persistence**: `ARCHIVE_PERSIST=file|session`. The default is `session` on Streamlit Cloud (detected by `/mount/src` path or `appuser` user) and `file` elsewhere. In session mode a saved archive lives only in the browser session; use **Download archive json** and commit it to make it the built-in one.
- The AI usage counter (`ai_usage.json`) resets when the cloud container restarts. The iFinD API may require a mainland-China network, so Live may not work on the cloud.
- Never commit `.env`, `.streamlit/secrets.toml`, tokens or raw CSVs; they are git-ignored.

### v0.5.3 update
- **Language toggle (English / 中文)**: a switch at the top of the sidebar (below the page menu) changes the whole UI — page titles, sidebar controls, metric cards, tooltips (definitions only), chart titles and axes, messages and the Live usage guide. The default is English; the choice is kept in the browser session. The History **AI summary** follows the UI language (Simplified Chinese output in 中文 mode, same conservative rules). Strings live in `src/project_option_chain/i18n.py` (`t()` helper) and `i18n_zh.py`; data and column keys are unchanged.
- **Developer console `input_contract_list.py`**: updates a Live contract archive from the terminal instead of the sidebar form. It asks for the underlying (`588000SH`, `588000.SH`, `588000` or `159915SZ` are all accepted), the two expiry tags (front and next month, e.g. `2611`, `2612`) and the option codes of each month (one per line or comma/space separated, finish with an empty line). It checks the code format and exchange, removes duplicates, orders the two months, optionally verifies the codes with iFinD (token read from the `IFIND_TOKEN` environment variable only, never typed or printed), shows a summary and asks before overwriting `data/archives/<spot>.json`. The old file is backed up to `data/archives/backup/` (git-ignored). New codes need the iFinD check, because contract names, strikes and expiries come from iFinD.

```bash
read -s IFIND_TOKEN && export IFIND_TOKEN     # paste the token; nothing is echoed
.venv/bin/python input_contract_list.py
# Underlying code: 588000SH
# Front-month expiry tag: 2611
# Next-month expiry tag:  2612
# Option codes for 2611: <paste codes, then an empty line>
# Option codes for 2612: <paste codes, then an empty line>
# Check codes with iFinD? y  ->  summary  ->  Overwrite data/archives/588000.SH.json? y
```

---

<a id="中文简介"></a>
## 中文简介

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

AI 总结是可选功能。如需使用，把 `.env.example` 复制为 `.env`，填写 `OPENROUTER_API_KEY=...`（默认模型 `deepseek/deepseek-v4.1-flash`，调用上限 10,000 次）。`.env` 不会进入 git。

**History 页面**

1. 侧边栏：选择 **ETF**。底部是 VIX 设置 **Roll near month at <7 DTE**（默认关闭）和数据覆盖范围。
2. **单日视图**：选择日期，查看主力合约指标卡。**波动率微笑**可叠加前 1–5 个交易日（取消勾选 **Overlay previous days** 则只显示往前第 N 个交易日）：当日为粗实线，越早的日期为越细、越淡的同色虚线；竖线表示各日的 ETF 收盘价。下方是**合约生命周期**图。
3. **区间视图**：选择日期区间，以及“仅主力合约”或指定到期月份，查看价格与净 GEX、VIX 与 HV 和 VRP30；还有数据预览、CSV 下载和可选的 AI 总结。
4. **AI 总结——使用自己的 LLM API**：打开 *Summarize current view (AI)*，展开 **Use your own LLM API**，填写任意 OpenAI 兼容接口的 API key，可选填 **Model**（默认 `deepseek/deepseek-v4.1-flash`）和 **Base URL**（默认 `https://openrouter.ai/api/v1`）。key 只保存在当前浏览器会话中，不会写入文件、日志或显示出来。留空则使用 `.env` / Secrets 中的应用默认 key；页面会提示 “Using your key” 或 “Using app default key”。10,000 次调用上限只对应用默认 key 生效；单次请求超时 45 秒。

**Live 页面**

1. 在侧边栏输入个人 **iFinD access token**。它只保留在当前浏览器会话中，不会写入仓库或日志。
1a. 页首提示 A 股当前是否开盘（上海时间：集合竞价、交易中、午休、收盘、周末；不含交易所节假日）。
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

**计算公式（与 `src/project_option_chain/` 代码一致）**

记号：$S$ 标的价格，$K_i$ 行权价，$OI_i$ 持仓量，$M$ 合约乘数，$\Gamma_i$ 数据商 gamma，$\sigma_i$ 隐含波动率，$\mathbb{1}_C$ 认购取 $+1$、认沽取 $-1$，$N$ 剩余自然日。

*GEX（单合约与净值）*

$$\mathrm{GEX}_i = \mathbb{1}_C\,\Gamma_i\,OI_i\,M\,S^2\times 0.01,\qquad \mathrm{NetGEX}=\frac{1}{10^6}\sum_i \mathrm{GEX}_i\ \text{（单位：百万）}$$

*GEX 曲线与 zero gamma*：认购、认沽分别以 $m=K/S$ 拟合三次样条 $\hat\sigma_C,\hat\sigma_P$；模拟价格网格 $s\in[\max(S-2\,\mathrm{sd}(K),K_{\min}),\ \min(S+2\,\mathrm{sd}(K),K_{\max})]$，步长 $0.005$，$\tau=N/360$，$r$ 为对应期限 Shibor：

$$\sigma_i(s)=\mathrm{clip}\big(\hat\sigma(K_i/s),\,0.01,\,5\big),\quad d_1=\frac{\ln(s/K_i)+(r+\tfrac12\sigma_i^2)\tau}{\sigma_i\sqrt\tau},\quad \Gamma_i^{BS}(s)=\frac{\varphi(d_1)}{s\,\sigma_i\sqrt\tau}$$

$$G(s)=\sum_i \mathbb{1}_C\,\Gamma_i^{BS}(s)\,OI_i\,M\,s^2\times0.01,\qquad \text{ZeroGamma}=\arg\min_{s_j:\ G(s_j)G(s_{j-1})<0}|s_j-S|$$

（近月+次月合并视图对每个到期月各算一条曲线后相加，各自使用自己的 $\tau$、$r$ 和微笑。）

*认购/认沽墙与 max pain*

$$\text{CallWall}=\arg\max_K\sum_{i\in C,K_i=K}OI_i,\qquad \text{PutWall}=\arg\max_K\sum_{i\in P,K_i=K}OI_i$$

$$\text{MaxPain}=\arg\min_{K^{\ast}}\Big[\sum_{i\in C}OI_i\max(0,K^{\ast}-K_i)+\sum_{i\in P}OI_i\max(0,K_i-K^{\ast})\Big]$$

*ATM IV*：$\bar\sigma(K)$ 为该行权价认购与认沽 IV（$>0$）的均值；$K_{lo}=\max\{K\le S\}$，$K_{hi}=\min\{K\ge S\}$：

$$\sigma_{ATM}=w\,\bar\sigma(K_{lo})+(1-w)\,\bar\sigma(K_{hi}),\qquad w=\frac{K_{hi}-S}{K_{hi}-K_{lo}}$$

（现价恰在某行权价上或超出行权价范围时，取最近行权价的 $\bar\sigma$。）

*25Δ skew*：$c^{\ast}=\arg\min_{i\in C}|\Delta_i-0.25|$，$p^{\ast}=\arg\min_{i\in P}|\Delta_i+0.25|$：

$$\text{Skew}_{25\Delta}=\sigma_{c^{\ast}}-\sigma_{p^{\ast}}$$

*VIX（CBOE 方法）*：每个到期月 $j$：$T_j=N_j/365$，$R_j$ 为 $N_j$ 期限 Shibor；期权价格取买卖中间价，否则最新价，否则结算价（History 只用结算价）。

$$F_j=K^{\ast}+e^{R_jT_j}\,(C(K^{\ast})-P(K^{\ast})),\quad K^{\ast}=\arg\min_K|C(K)-P(K)|,\qquad K_0=\max\{K_i\le F_j\}$$

$$Q(K_i)=\begin{cases}P(K_i)&K_i<K_0\\ \tfrac12\,(C(K_0)+P(K_0))&K_i=K_0\\ C(K_i)&K_i>K_0\end{cases}\qquad \Delta K_i=\frac{K_{i+1}-K_{i-1}}{2}\ \ (\text{两端取单侧差})$$

$$\sigma_j^2=\frac{2}{T_j}\sum_i\frac{\Delta K_i}{K_i^2}\,e^{R_jT_j}\,Q(K_i)-\frac{1}{T_j}\Big(\frac{F_j}{K_0}-1\Big)^2$$

30 天恒定期限（总方差线性插值；两个到期月都在 30 天同一侧时为外推）：

$$\mathrm{VIX}=100\sqrt{\Big[T_1\sigma_1^2\frac{N_2-N_{30}}{N_2-N_1}+T_2\sigma_2^2\frac{N_{30}-N_1}{N_2-N_1}\Big]\frac{365}{N_{30}}},\qquad N_{30}=30$$

只有一个可用到期月时 $\mathrm{VIX}\approx100\,\sigma_1$。**不换月**（`vix30`，默认，Live 亦然）：取最近两个到期月。**7 天换月**（`vix30_roll7`，History 开关）：若 $N_1<7$ 且存在第三个到期月，则改用第 2、3 个到期月。

*历史波动率与 VRP*：$r_t=\ln(S_t/S_{t-1})$，窗口 $n\in\{30,60,90\}$ 个交易日：

$$\mathrm{HV}_n=100\sqrt{252}\;\sqrt{\frac{1}{n-1}\sum_{t}(r_t-\bar r)^2},\qquad \mathrm{VRP}_{30}=\mathrm{VIX}_{30}-\mathrm{HV}_{30}$$

*Shibor 期限插值*：取估值日当天或之前最近一次报价；节点 $d\in\{1,7,14,30,90,180,270,365\}$ 天（隔夜…1 年），两端外取端点值：

$$r(N)=r(d_k)+\frac{N-d_k}{d_{k+1}-d_k}\big(r(d_{k+1})-r(d_k)\big),\qquad d_k\le N\le d_{k+1}$$

**部署（Streamlit Community Cloud）**

- 主文件 `dashboard.py`，Python 3.13，依赖来自 `uv.lock` / `requirements.txt`（不含 akshare）。
- Secrets：`OPENROUTER_API_KEY`（可选 `OPENROUTER_MODEL`、`AI_USAGE_CAP`、`ARCHIVE_PERSIST`），参见 `.streamlit/secrets.toml.example`。
- **合约档案保存方式**：`ARCHIVE_PERSIST=file|session`。在 Streamlit Cloud 上默认是 `session`（通过 `/mount/src` 路径或 `appuser` 用户识别），其他环境默认是 `file`。session 模式下，保存的档案只存在于当前浏览器会话；可点 **Download archive json** 下载，再提交到仓库作为内置档案。
- 云端容器重启后，AI 调用计数（`ai_usage.json`）会清零。iFinD 接口可能需要中国大陆网络，因此 Live 在云端可能无法使用。
- 切勿提交 `.env`、`.streamlit/secrets.toml`、任何 token 或原始 CSV；这些都已加入 `.gitignore`。

### v0.5.3 更新说明
- **语言切换（English / 中文）**：侧边栏顶部（页面菜单下方）新增切换按钮，可切换整个界面：页面标题、侧边栏控件、指标卡片、tooltip（仅定义）、图表标题和坐标轴、提示信息以及 Live 使用说明。默认英文，选择保存在当前浏览器会话中。History 页的 **AI 摘要** 跟随界面语言（中文模式下输出简体中文，保守解读规则不变）。界面文字集中在 `src/project_option_chain/i18n.py`（`t()` 函数）和 `i18n_zh.py`；数据和列名不变。
- **开发者操作台 `input_contract_list.py`**：在终端更新 Live 合约存档，代替侧边栏表单。依次输入标的代码（`588000SH`、`588000.SH`、`588000`、`159915SZ` 均可）、两个到期标志（近月和次月，如 `2611`、`2612`），以及每个月的期权代码（每行一个，或用逗号 / 空格分隔，以空行结束）。程序会校验代码格式和交易所、去重、自动排定前后月，可选用 iFinD 核对（令牌只从环境变量 `IFIND_TOKEN` 读取，不需输入也不会打印），显示摘要并确认后才覆盖 `data/archives/<spot>.json`。旧文件备份到 `data/archives/backup/`（已加入 gitignore）。新代码需要 iFinD 核对，因为合约名称、行权价和到期日来自 iFinD。

```bash
read -s IFIND_TOKEN && export IFIND_TOKEN     # 粘贴令牌，屏幕不回显
.venv/bin/python input_contract_list.py
# Underlying code: 588000SH
# Front-month expiry tag: 2611
# Next-month expiry tag:  2612
# Option codes for 2611: <粘贴代码后输入空行>
# Option codes for 2612: <粘贴代码后输入空行>
# Check codes with iFinD? y  ->  摘要  ->  Overwrite data/archives/588000.SH.json? y
```
