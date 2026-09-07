# SoccerAN

**中文为主 / English below**

五大联赛（英超 / 西甲 / 意甲 / 德甲 / 法甲）的 **Poisson + Elo** 足球赛果基线模型。  
数据来自 [football-data.co.uk](https://www.football-data.co.uk/) 公开 CSV（稳定、免费、无需 API Key）。

> ⚠️ **研究 / 分析用途声明**：本项目仅供学习与数据分析，**不是投注建议**。作者不对任何使用结果负责。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **Elo** | 初始 1500，默认 K=20，主场优势约 65 Elo；按时间顺序逐场更新；默认按联赛独立计分 |
| **Poisson** | 估计球队进攻/防守强度（或 Elo→xG）；独立泊松计算 P(主胜)/P(平)/P(客胜) 与 xG |
| **CLI** | `fetch` / `update` / `predict` |
| **每日更新** | `make daily` 或 `scripts/daily_update.sh` |

联赛代码（football-data.co.uk）：`E0` 英超、`SP1` 西甲、`I1` 意甲、`D1` 德甲、`F1` 法甲。

---

## 安装

需要 Python **3.11+**。

```bash
git clone https://github.com/GaoGeng12138/SoccerAN.git
cd SoccerAN
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# 或: pip install -r requirements.txt && pip install -e .
```

---

## 数据说明

### 主数据源：football-data.co.uk

季节 CSV 模式：

```text
https://www.football-data.co.uk/mmz4281/{YY}{YY+1}/{CODE}.csv
```

例如：`https://www.football-data.co.uk/mmz4281/2425/E0.csv`（2024–25 英超）。

配置见 `config.yaml`：默认拉取最近 **3** 个赛季（含当前赛季），缓存到 `data/raw/{CODE}_{season}.csv`。

### 可选参考：soccerdata

[soccerdata](https://github.com/probberechts/soccerdata) 是优秀的足球数据工具库（多源抓取）。  
**v1 不依赖** soccerdata，也不使用脆弱的网页爬虫；如需扩展赛程/球员数据，可自行安装作可选依赖。

---

## 命令

```bash
# 下载 CSV 到 data/raw/
python -m socceran fetch

# 下载（可选）+ 拟合 Elo + Poisson，写入 out/*_state.json
python -m socceran update
python -m socceran update --no-fetch   # 仅用本地缓存重拟合

# 写出预测 out/predictions_YYYYMMDD.csv 与 .json
python -m socceran predict
python -m socceran predict --mode hypothetical

# 查看缓存比赛统计
python -m socceran status
```

安装后也可用入口：`socceran fetch|update|predict`。

### 每日更新

```bash
make daily
# 或
./scripts/daily_update.sh
```

流程：`fetch` → `update` → `predict`。

---

## 配置

编辑 `config.yaml`：

- `elo.k` / `elo.home_advantage` / `elo.scope`（`per_league` | `global`）
- `poisson.mode`：`goals`（默认，攻防强度）或 `elo`（Elo 映射 xG）
- `seasons.count`：拉取赛季数量

---

## 测试

离线单元测试（含 `tests/fixtures/sample_matches.csv`）：

```bash
pytest -q
```

---

## 项目结构

```text
SoccerAN/
  config.yaml
  pyproject.toml
  requirements.txt
  Makefile
  scripts/daily_update.sh
  src/socceran/          # fetch / elo / poisson / predict / cli
  tests/
  data/raw/              # 缓存 CSV（git 忽略内容）
  out/                   # 状态与预测输出
```

---

## English (short)

Poisson + Elo baseline for the Big Five European leagues. Data from **football-data.co.uk** season CSVs (cached under `data/raw/`). Optional inspiration: [soccerdata](https://github.com/probberechts/soccerdata) — **not required** for v1.

```bash
pip install -e ".[dev]"
python -m socceran fetch && python -m socceran update && python -m socceran predict
pytest -q
```

**Disclaimer:** research / analytics only — **not betting advice**.

---

MIT License · GaoGeng12138
