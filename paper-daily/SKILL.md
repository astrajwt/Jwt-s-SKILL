---
name: paper-daily
description: >
  Daily research paper tracker and analyzer for arxiv and HuggingFace. ALWAYS use this skill
  when the user wants to: fetch, summarize, deep-read, or manage research papers; run the daily
  paper pipeline; generate paper reports (daily/weekly/monthly/quarterly); track AI/ML/Systems
  research trends; maintain a paper knowledge base in Notion; backfill historical papers from
  2023 onward; or ask about "论文日报", "paper daily", "今天有什么新论文", "arxiv", "huggingface papers",
  or anything about research paper tracking. Also trigger when user says "run paper daily",
  "fetch today's papers", "what papers dropped today", or "generate paper report".
---

# Paper Daily — 自动化三段式工作流

每日论文追踪系统，**全自动执行，Claude 负责审阅和质检**。

---

## 目录结构

**路径格式**：`YYYY/MonthName/YYYY-MM-DD/`（MonthName 为英文全称，如 `March`、`January`）

```
PaperDaily/
├── 2026/
│   ├── quarterly-report-2026-Q1.md
│   ├── monthly-report-2026-01.md
│   └── March/
│       └── 2026-03-03/
│           ├── daily-report-2026-03-03.md   # 主日报（由 generate_digest.py 生成）
│           ├── scoring.json                  # LLM 评分结果
│           ├── summaries/                    # 每篇论文摘要笔记（由 score_papers.py 生成）
│           │   └── {arxiv_id}_{slug}.md
│           └── deep-reads/                   # 精读笔记（由 deep_read.py 生成）
│               └── {arxiv_id}_{slug}_deepread.md
```

---

## 一键运行（推荐）

```bash
cd ~/Documents/JwtVault/03_paper/paper-daily
python scripts/main.py --date today --full-auto
```

`--full-auto` 依次执行：Phase 1 Fetch → Phase 2 Score → Phase 3 Digest + DeepRead → Phase 4 聚合报告（自动判断）→ Phase 5 Notion 同步（自动，需配置 token）

---

## Phase 1 — 收集 & 去重

```bash
python scripts/main.py --date DATE
# DATE = "today" | "yesterday" | "YYYY-MM-DD"
```

- 抓取 HuggingFace Daily Papers + arxiv（72 小时窗口，避免处理延迟）
- SQLite 去重，合并评分
- 输出：`/tmp/paper-daily/DATE/prepared.json`

---

## Phase 2 — LLM 批量评分

```bash
python scripts/score_papers.py \
  --prepared /tmp/paper-daily/DATE/prepared.json \
  --output /path/to/PaperDaily/YYYY/MonthName/YYYY-MM-DD/scoring.json
```

**工作方式**：
- 读取 `prepared.json` 中的所有论文（title + abstract）
- 将 `interests.json` 关键词展平后注入评分 prompt
- 调用 Claude API（`prompts/score_papers.txt`），一次调用评分全部论文
- 输出 `scoring.json` + `summaries/*.md`

**评分标准（校准！不要虚高）**：

| 分 | 含义 |
|----|------|
| 9–10 | 突破性工作，改变 practice，将成引用锚点 |
| 7–8 | 强工作，评估扎实，值得完整阅读 |
| 5–6 | 扎实增量，诚实改进，领域意识用 |
| 3–4 | 窄范围，baseline 有问题，创新有限 |
| 1–2 | 建议跳过，偏题，或已被超越 |

加分：HF trending (+1~2)；顶会接收；代码开源；用户关键词高度匹配
减分：无消融；cherry-pick 迹象；无代码；baseline 不公平

**`scoring.json` 格式**：
```json
[
  {
    "id": "arxiv:2503.18773",
    "title": "BitDecoding: ...",
    "score": 9,
    "reason": "HPCA 2026; Tensor Core + INT4 KV; H100 8.9× vs FP16",
    "summary": "用 Tensor Core 实现低比特 KV Cache attention，H100 上实现 8.9× decode 加速。",
    "hf_upvotes": 47,
    "deep_read": true
  }
]
```

---

## Phase 3a — 精读（Top 20）

```bash
python scripts/deep_read.py \
  --scoring /path/to/scoring.json \
  --output-dir /path/to/deep-reads/ \
  --top-n 20
```

**工作方式**：
- 取 `scoring.json` 前 20 高分论文
- 为每篇爬取 `https://arxiv.org/html/{arxiv_id}` 全文（抽取正文 + figure captions）
- 调用 Claude API（`prompts/deep_read.txt`），传入 abstract + HTML 全文
- 输出 `deep-reads/{arxiv_id}_{slug}_deepread.md`

**精读笔记格式**：
```markdown
---
title: "{paper title}"
arxiv_id: "{id}"
date: YYYY-MM-DD
score: N
type: deep-read
tags: [paper/deep-read, topic/X, ...]
---

# 📖 {Title}

## TL;DR
一句话：做/证明了什么 + 最重要的结果数字。

## 核心贡献
2–3 句。到底什么是新的？方法名、数据集、指标、关键数字。

## 方法
- **{关键技术决策 1}**: 为什么重要，与 prior work 机制层的区别
- **{关键技术决策 2}**: ...

## 实验结果
- **Benchmarks**: {列举}
- **Headline**: 精确数字 vs 最强 baseline
- **关键消融**: {如有}
- **可疑缺失**: {什么没报告？}

## 工程启示
1–2 句。"用 X 实现 Y" 句式，从业者能直接采用的。

## 局限性
1–2 句。范围、算力、可复现性、生产失效模式。

## 相关工作
- [[Paper A]] — {为什么相关，一句话}
```

---

## Phase 3b — 日报合成

```bash
python scripts/generate_digest.py \
  --scoring /path/to/scoring.json \
  --prepared /tmp/paper-daily/DATE/prepared.json \
  --output /path/to/daily-report-DATE.md
```

**工作方式**：
- 读取 `scoring.json`（评分 + reason + summary）
- 可选附加：HF trending 信号、arxiv HTML 片段
- 调用 Claude API（`prompts/daily_digest.txt`）
- 输出 `daily-report-YYYY-MM-DD.md`

**日报格式**（`prompts/daily_digest.txt` 控制）：

```markdown
# 📰 论文日报 — YYYY-MM-DD

> 过去 72 小时 · **N 篇** · 精读 **M 篇** · HF 热榜 **K 篇** · 覆盖 {主要类别}

---

## 今日叙事 / Today's Story
{3–5 句叙事段落，讲清楚今天这批论文的故事脉络}

---

## 研究温度计 / Field Pulse

| 方向 | 今日篇数 | 温度 | 信号质量 | HF热度 |
|------|---------|------|---------|--------|
| 推理训练 / RL-for-Reasoning | N | 🔴 沸腾 | ★★★★ | 🔥 |
| 多模态视觉 / Multimodal Vision | N | 🟠 升温 | ★★★☆ | 🔥 |
| ...

（⚡ 标注新兴方向，连续出现 ≥3 天的非关注领域方向）

---

## 精选论文 / Curated Papers
（评分 ≥ 7 展开，评分 ≤ 5 只写一行）

每篇精选论文格式：
**[N]. {Title}**
[arXiv](https://arxiv.org/abs/ID) · [PDF](https://arxiv.org/pdf/ID) · 🤗 [HuggingFace](https://huggingface.co/papers/ID) N赞（如有HF数据）
[[摘要链接]] · [[📖精读链接]]（如有精读）

{评分、核心创新、工程要点、局限}

**相关工作**
- [[内部精读链接|Title]] — 一句话说明关联
- [外部论文Title](https://arxiv.org/abs/ID) — 一句话说明关联

---

## 社区信号 / Community Signal

{HF trending 论文按 upvotes 排序的表格，标注与用户关注方向的关联度}

| # | 论文 | HF赞 | 关联度 | 备注 |
|---|------|------|--------|------|
| 1 | [Title](arxiv_link) | N赞 | ✅ 核心方向 | 简短评注 |
| 2 | [Title](arxiv_link) | N赞 | ⚠️ 相关 | |
| 3 | [Title](arxiv_link) | N赞 | ❌ 不相关 | |

（✅ 核心关注方向 · ⚠️ 边缘相关 · ❌ 超出关注领域）

{2–3 句分析：HF社区热度与AI Infra技术质量的匹配/偏差情况}

---

## 超出关注领域 / Beyond Your Interests

{按方向聚类，每个方向 2–5 篇，只写一行+trend判断}

### {方向名，如 Multimodal Vision} · N篇 · HF N赞
- [Title](arxiv_link) — 一句话摘要
- ...
**趋势判断**：{首次出现/持续升温/可能进入视野 + 是否建议关注}

---

## 开放问题 / What's Still Unsettled
{今日论文背后领域仍在争论的核心问题}

---

## 今日批次质量 / Batch Quality
{如果只能读一篇，读哪篇？为什么？}
```

---

## 完整 main.py 调用链（--full-auto）

```
Phase 1: main.py fetch        → /tmp/paper-daily/DATE/prepared.json
Phase 2: score_papers.py      → scoring.json + summaries/*.md
Phase 3a: deep_read.py        → deep-reads/*_deepread.md (top 20)
Phase 3b: generate_digest.py  → daily-report-DATE.md
Phase 4: report_aggregator.py → 聚合报告（自动判断当日是否触发）
Phase 5: notion_sync.py       → 推送到 Notion（需 NOTION_TOKEN + NOTION_ROOT_PAGE_ID）
```

---

## 聚合报告（Phase 4）自动触发规则

`--full-auto` 跑完日报后，自动调用 `report_aggregator.py --type auto`，按当日日期判断：

| 报告类型 | 触发条件 | 输出文件 |
|---------|---------|---------|
| 周报 | 每周**最后一天**（周日） | `YYYY/MonthName/weekly-report-YYYY-WNN.md` |
| 月报 | 每月**最后一天** | `YYYY/monthly-report-YYYY-MM.md` |
| 季报 | 每季度最后一天（3/31、6/30、9/30、12/31） | `YYYY/quarterly-report-YYYY-QN.md` |
| 年报 | 12 月 31 日 | `YYYY/yearly-report-YYYY.md` |

**数据来源层级**：
- 周报 ← 当周各日 `daily-report-*.md` 摘要（叙事 + 温度计 + 批次质量）
- 月报 ← 当月各日日报摘要
- 季报 ← 当季三个月的 `monthly-report-*.md`（缺失则 fallback 到日报）
- 年报 ← 四个季度的 `quarterly-report-*.md`（缺失则 fallback 到月报）

**手动触发**：
```bash
# 自动检测（推荐）
python scripts/report_aggregator.py --type auto --date 2026-03-30

# 指定类型
python scripts/report_aggregator.py --type weekly  --date 2026-03-09
python scripts/report_aggregator.py --type monthly --date 2026-03-31
python scripts/report_aggregator.py --type quarterly --date 2026-03-31
python scripts/report_aggregator.py --type yearly  --date 2026-12-31

# 强制覆盖已有报告
python scripts/report_aggregator.py --type monthly --date 2026-03-31 --force
```

---

## 核心原则

1. **脚本全自动**：评分、精读、日报全部由 Claude API 调用完成，无需 Claude Code 手动生成
2. **Claude 负责审阅**：运行完成后，Claude Code 可对输出进行质检和小修
3. **校准评分**：5 分是中位，不是差评。每天不会全是 9-10
4. **明确指出**：benchmark 过拟合、p-hacking、baseline 不公平、模糊声明
5. **工程视角优先**：工程启示必须可操作
6. **HF 热度 ≠ 质量**：HF 社区信号与技术质量评估必须分开呈现，trending 但与关键词不相关的明确标注
7. **72 小时窗口**：每日覆盖过去三天提交的论文，SQLite 去重，trending >3 次跳过
8. **HTML 优先**：deep_read.py 优先使用 arxiv HTML 全文，fallback 到 abstract only
9. **路径格式**：vault 目录用 `YYYY/MonthName/YYYY-MM-DD/`，由 `file_manager.py` 自动处理
10. **始终附链接**：每篇精选论文必须附 arXiv + PDF 链接；HF trending 论文附 HuggingFace 链接 + 赞数；精读论文附相关工作的内外链
11. **非关注领域聚类**：非关注方向的论文按方向聚类后在「超出关注领域」section 汇总，不混入主列表
12. **领域趋势检测**：若某个非关注方向连续 **3 天**出现 **≥5 篇**论文，在日报中标注 ⚡ 并在当日报末附建议：`⚡ 建议将 [{方向名}] 加入 interests.json`

---

## Notion 同步（Phase 5）

pipeline 每天跑完后自动触发，将以下内容推送到 Notion：

| 内容 | Notion 位置 |
|------|------------|
| 日报 `daily-report-DATE.md` | `PaperDaily / YYYY / MM_Month / 日报 DATE` |
| 精读 `deep-reads/*.md` | `PaperDaily / YYYY / MM_Month / 日报 DATE / 精读笔记 / <论文标题>` |
| 周报 | `PaperDaily / YYYY / 周报 / weekly-report-YYYY-WNN` |
| 月报 | `PaperDaily / YYYY / 月报 / monthly-report-YYYY-MM` |
| 季报 | `PaperDaily / YYYY / 季报 / quarterly-report-YYYY-QN` |
| 年报 | `PaperDaily / YYYY / yearly-report-YYYY` |

**配置（`.env` 文件）**：
```bash
NOTION_TOKEN=ntn_...                    # Notion integration token
NOTION_ROOT_PAGE_ID=xxxxxxxxxxxxxxxx    # PaperDaily 根页面 ID
```

**创建 Notion integration**：
1. 访问 https://www.notion.so/my-integrations → New integration
2. 复制 token 填入 `.env`
3. 在 Notion 里创建 "PaperDaily" 页面，点右上角 `...` → Connections → 添加你的 integration
4. 复制页面 URL 中的 UUID 作为 `NOTION_ROOT_PAGE_ID`

**手动同步**：
```bash
# 同步某天
python scripts/notion_sync.py --date 2026-03-07

# 历史回填
python scripts/notion_sync.py --date-range 2023-01-01 2026-03-07

# 强制覆盖已有页面
python scripts/notion_sync.py --date 2026-03-07 --force
```

---

## Notion 页面链接格式

deep_read.txt 和 daily_digest.txt 中的相关工作链接统一使用 markdown 外链格式：

```
[BitDecoding](https://arxiv.org/abs/2503.18773)
```

Notion sync 脚本会在推送时自动建立页面间的层级关系，不需要手动维护内链。

---

## 依赖脚本速查

| 脚本 | 作用 |
|------|------|
| `main.py` | 主编排，fetch + dedup，输出 prepared.json；`--full-auto` 调用全流程 |
| `score_papers.py` | **Phase 2**：LLM 批量评分，输出 scoring.json + summaries/ |
| `deep_read.py` | **Phase 3a**：爬取 arxiv HTML + LLM 精读，输出 deep-reads/ |
| `generate_digest.py` | **Phase 3b**：LLM 日报合成，输出 daily-report-DATE.md |
| `api_client.py` | Claude API wrapper（需要 `PAPER_DAILY_API_KEY` 或 `ANTHROPIC_API_KEY`，不能用 `ANTHROPIC_AUTH_TOKEN`）|
| `fetch_arxiv.py` | arxiv API 抓取（72 小时窗口） |
| `fetch_hf.py` | HuggingFace Daily Papers |
| `dedup.py` | SQLite 去重数据库 |
| `file_manager.py` | 目录结构管理 |
| `download_pdfs.py` | 批量下载 arxiv PDF（可选） |
| `figure_extractor.py` | 从 arxiv HTML 提取图片 |
| `report_aggregator.py` | **Phase 4**：聚合报告（周/月/季/年），`--full-auto` 结束后自动调用 |
| `notion_sync.py` | **Phase 5**：推送日报、精读、聚合报告到 Notion（需 `NOTION_TOKEN` + `NOTION_ROOT_PAGE_ID`）|
| `setup_schedule.py` | macOS launchd 定时 9:00 AM |

---

## 环境变量

```bash
# ⚠️ 重要：ANTHROPIC_AUTH_TOKEN 是 Claude Code 的内部会话 token，不能用于脚本调用
# 需要单独申请 API key：https://console.anthropic.com/

# 设置用于 paper-daily 脚本的 API key（选一个）
export PAPER_DAILY_API_KEY="sk-ant-..."        # 推荐，专用于这个工作流
export ANTHROPIC_API_KEY="sk-ant-..."          # 备用（注意不要与 Claude Code session 冲突）

# 可选：自定义 API endpoint（默认 api.anthropic.com）
export PAPER_DAILY_BASE_URL="https://..."

# 可选：指定模型（默认 claude-sonnet-4-5）
export PAPER_DAILY_MODEL="claude-sonnet-4-5"
```

## Prompt 模板

| 文件 | 作用 |
|------|------|
| `prompts/score_papers.txt` | 批量评分 prompt，`{{interest_keywords}}` + `{{papers_json}}` |
| `prompts/daily_digest.txt` | 日报合成 prompt，多个 `{{...}}` 占位符 |
| `prompts/deep_read.txt` | 单篇精读 prompt，`{{title}}` + `{{fulltext}}` + ... |
