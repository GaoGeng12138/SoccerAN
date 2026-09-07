# SoccerAN

**中文为主 / English below**

五大联赛（英超 / 西甲 / 意甲 / 德甲 / 法甲）+ **日职 J1 / 韩 K 联赛 1** 的 **Poisson + Elo** 足球赛果基线模型。

> ⚠️ **研究 / 分析用途声明**：本项目仅供学习与数据分析，**不是投注建议**。作者不对任何使用结果负责。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **Elo** | 初始 1500，默认 K=20，主场优势约 65 Elo；按时间顺序逐场更新；默认按联赛独立计分 |
| **Poisson** | 估计球队进攻/防守强度（或 Elo→xG）；独立泊松计算 P(主胜)/P(平)/P(客胜) 与 xG |
| **多源赛果** | 主源 football-data.co.uk；回退 openfootball / football-datasets / J.League HTML / K League API / OpenLigaDB / 英超镜像 |
| **未来赛程** | OpenLigaDB / openfootball / J.League / K League → `data/fixtures/`；`predict` 优先用真实赛程 |
| **CLI** | `fetch` / `fixtures` / `update` / `predict` / `names` / `status` |
| **中文队名** | 预测 CSV/JSON 含 `home_zh` / `away_zh`（`output.use_chinese_names`，默认 true） |

联赛代码：`E0` 英超、`SP1` 西甲、`I1` 意甲、`D1` 德甲、`F1` 法甲、`JP1` 日职 J1、`KR1` 韩 K 联赛 1。

---

## 安装

需要 Python **3.11+**。

```bash
git clone https://github.com/GaoGeng12138/SoccerAN.git
cd SoccerAN
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

---

## 数据源与回退顺序

配置见 `config.yaml` → `sources.order`（默认）：

1. **football_data** — [football-data.co.uk](https://www.football-data.co.uk/) 季节 CSV（主源；现时常 503）
2. **jleague** — [data.j-league.or.jp](https://data.j-league.or.jp/) HTML 日程表（**JP1** 完赛+赛程）
3. **kleague** — [kleague.com/getScheduleList.do](https://www.kleague.com/schedule.do) JSON（**KR1** 按月聚合，完赛+赛程）
4. **openfootball** — [openfootball/football.json](https://github.com/openfootball/football.json)（**I1 / F1** 完赛+赛程；JP1 日历年 JSON 仅作次选）
5. **football_datasets** — GitHub `datasets/football-datasets` CSV 镜像（**I1 / F1** 历史完赛，至 `season-2526`）
6. **openligadb** — [OpenLigaDB](https://www.openligadb.de/) API（E0/D1/SP1）
7. **england_mirror** — 仅英超 GitHub CSV（`Tier==1`）

每个 **联赛 × 赛季** 按顺序尝试，**第一个有数据的源写入缓存**（不再混拼同行）。  
赛季码仍用欧洲 `YYXX`（如 `2627`）；**JP1 / KR1** 映射为日历年 `2000+YY`（`2627` → `2026`）。

### OpenLigaDB 快捷名（实测 2026-09）

| SoccerAN | shortcut | 2024 | 2025 | 2026 | 备注 |
|----------|----------|------|------|------|------|
| D1 德甲 | `bl1` | ✅ | ✅ | ✅ | 覆盖完整 |
| E0 英超 | `PL` | ❌ | ❌ | ✅ | 2024/25 请用主源或 england_mirror |
| SP1 西甲 | `la1` | ❌ | ❌ | ✅ | 旧快捷 `PD` 近年为空 |
| I1 / F1 | — | ❌ | ❌ | ❌ | 用 **openfootball**（及 football_datasets） |
| JP1 / KR1 | — | — | — | — | 用 **jleague** / **kleague** |

### I1 / F1 / JP1 / KR1 备用源（实测 2026-09）

| 联赛 | 主备用源 | 完赛 | 未来赛程 | 备注 |
|------|----------|------|----------|------|
| I1 意甲 | openfootball `it.1.json` | 2425–2627 | ✅ 2627 | 队名多为全称（如 `AC Milan`） |
| F1 法甲 | openfootball `fr.1.json` | 2425–2627 | ✅ 2627 | 同上 |
| JP1 日职 | jleague HTML | 2024–2026 | ✅ 2026 | 日文简称（`横浜FM`）；openfootball 仅见 `2025/jp.1.json` |
| KR1 韩K1 | kleague JSON | 2024–2026 | ✅ 2026 | 韩文简称（`전북`）；需按月请求 |

赛程写入时会过滤**已过去的未完赛**行，避免过期数据进入 `predict`。

### 内部赛果 schema

所有源归一为：

`date, league, season, home, away, fthg, ftag, ftr, source`

缓存：`data/raw/{CODE}_{season}.csv`；赛程：`data/fixtures/{CODE}_{season}.csv`。

---

## 命令

```bash
# 下载赛果（主源→回退）并刷新未来赛程
python -m socceran fetch
python -m socceran fetch --force
python -m socceran fetch --skip-fixtures

# 只刷新未来赛程
python -m socceran fixtures
python -m socceran fixtures --league E0,D1 --force

# 下载（可选）+ 拟合 Elo + Poisson
python -m socceran update
python -m socceran update --no-fetch

# 预测：默认优先 data/fixtures/ 中的未完赛；若无则回退「最近完赛场次」并打日志
python -m socceran predict
python -m socceran predict --mode upcoming
python -m socceran predict --mode hypothetical

python -m socceran status
python -m socceran names --list
python -m socceran names -q "Man United"
```

预测输出保留英文队名，并增加 `home_zh` / `away_zh`。

### 每日更新

```bash
make daily
# 或 ./scripts/daily_update.sh
```

流程：`fetch` → `update` → `predict`。

---

## 配置要点

- `sources.order` / `sources.*.enabled`
- `sources.openligadb.shortcuts` / `shortcut_overrides`
- `fixtures.prefer_upcoming`（predict 是否优先真实赛程）
- `elo.*` / `poisson.mode` / `seasons.count`

---

## 测试

```bash
pytest -q
```

含 OpenLigaDB / openfootball / J.League / K League 归一化离线单测（`tests/test_sources.py`）与中文队名测试。

---

## 项目结构

```text
SoccerAN/
  config.yaml
  src/socceran/     # data / sources / elo / poisson / predict / names / cli
  tests/
  data/raw/         # 完赛缓存
  data/fixtures/    # 未来赛程
  out/              # Elo/Poisson 状态与预测
```

---

## English (short)

Poisson + Elo baseline for the Big Five **plus J1 (JP1) and K League 1 (KR1)**. **Primary:** football-data.co.uk. **Fallbacks:** openfootball JSON (Serie A / Ligue 1), football-datasets CSVs, J.League HTML, K League JSON API, OpenLigaDB, England Tier-1 mirror. Upcoming fixtures feed `predict` when present.

```bash
pip install -e ".[dev]"
python -m socceran fetch && python -m socceran update && python -m socceran predict
pytest -q
```

**Disclaimer:** research / analytics only — **not betting advice**.

---

MIT License · GaoGeng12138
