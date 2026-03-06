---
name: paper-daily
description: >
  Daily research paper tracker and analyzer for arxiv and HuggingFace. ALWAYS use this skill
  when the user wants to: fetch, summarize, deep-read, or manage research papers; run the daily
  paper pipeline; generate paper reports (daily/weekly/monthly/quarterly); track AI/ML/Systems
  research trends; maintain a paper knowledge base in Obsidian; backfill historical papers from
  2023 onward; or ask about "论文日报", "paper daily", "今天有什么新论文", "arxiv", "huggingface papers",
  or anything about research paper tracking. Also trigger when user says "run paper daily",
  "fetch today's papers", "what papers dropped today", or "generate paper report".
---

# Paper Daily — 三段式工作流

每日论文追踪系统，**三步走**：收集+下载 → 通读评分 → 精读产出。

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
│           ├── daily-report-2026-03-03.md  # 主日报（HF + arXiv 合并）
│           ├── originals/                   # 原始 PDF（Phase 1）
│           │   ├── {arxiv_id}.pdf
│           │   └── {arxiv_id}_meta.json
│           ├── summaries/                   # 每篇论文摘要笔记（Phase 2）
│           │   └── {arxiv_id}_{slug}.md
│           ├── deep-reads/                  # 精读笔记（Phase 3）
│           │   └── {arxiv_id}_{slug}_deepread.md
│           └── figures/                     # 从 arxiv HTML 提取的图片
```

**summary 文件命名**：`{arxiv_id}_{title_slug}.md`（slug = 标题小写下划线，截至 ~60 字符）

---

## Phase 1 — 收集 & 下载 PDF

### 1a. 运行主编排脚本

```bash
python scripts/main.py --date DATE
# DATE = "today" | "yesterday" | "YYYY-MM-DD"
```

这会获取 HuggingFace Daily Papers + arxiv，合并评分，输出：
`/tmp/paper-daily/DATE/prepared.json`

### 1b. 下载 PDF

```bash
python scripts/download_pdfs.py \
  --prepared /tmp/paper-daily/DATE/prepared.json \
  --output /path/to/PaperDaily/YYYY/MonthName/YYYY-MM-DD/originals/
```

- 每篇论文保存 `{arxiv_id}.pdf` + `{arxiv_id}_meta.json`
- 失败的记录到 `failed.txt`，不中断流程
- **网络受限时**（沙箱/代理阻断）：脚本打印 `[SKIP]`，Claude 改用 WebFetch 读 arxiv HTML 版本作为全文

### 1c. 建目录

```bash
python scripts/file_manager.py --setup --date DATE
```

---

## Phase 2 — 通读评分（全量，快）

对 `prepared.json` 中**每一篇**论文（不分层级）：

1. 读 abstract（必须）
2. 尝试读 `https://arxiv.org/html/{arxiv_id}` 摘要段（如可访问）
3. 给出结构化评分

**输出 `scoring.json`**（严格 JSON 数组，无 markdown 围栏）：
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

---

## Phase 3 — 精读 + 日报合成

**触发精读**：按评分从高到低取前 10 篇，同分按 HF 热度排序；上限 10 篇/天。重点关注 Agent RL、推理训练、系统性能优化方向。

### 3a. 摘要笔记（每篇均生成，Phase 2 产出）

保存到 `summaries/{arxiv_id}_{slug}.md`，采用 vault 格式：

```markdown
---
title: "..."
arxiv_id: "..."
date: YYYY-MM-DD
authors: "..."
source: arxiv   # 或 huggingface
url: "https://arxiv.org/abs/..."
pdf: "https://arxiv.org/pdf/..."
tags: [paper, source/arxiv, topic/...]
score: N
---
# {Title}

## 核心贡献 (Key Contributions)
{2–3 句，具体说新在哪里}

## 方法概述 (Method)
{3–4 条要点，技术机制}

## 实验结果 (Results)
{关键数字 + benchmark + 主要消融}

## 为什么值得关注 (Why It Matters)
{对工程实践的影响}

## 相关论文 (Related Work in Vault)
- [[MonthName/YYYY-MM-DD/slug|Title]] — 一句话关联说明
```

### 3b. 精读笔记（top 10 精读，每篇一个 .md 文件）

保存到 `deep-reads/{arxiv_id}_{slug}_deepread.md`：

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
（3–5 条）

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
- [[Paper B]] — {一句话}
```

400–600 词。不要逐字复制摘要。

### 3c. 主日报格式

保存到 `daily-report-YYYY-MM-DD.md`（存于当日目录根路径）。

**日报的灵魂**：不是列举论文，而是帮读者建立认知地图——**今天发生了什么，为什么重要，下一步是什么**。写法上，像一个每天跟踪这个领域的资深工程师在向你汇报，有温度、有判断、有态度。

```markdown
# 📰 论文日报 — YYYY-MM-DD

> 过去 72 小时 · **N 篇** · 精读 **M 篇** · 覆盖 {主要类别}
> _PDF 下载脚本：`pdfs/download_manual.sh`（网络限制时手动执行）_

---

## 今日叙事 / Today's Story

{3–5 句叙事段落。不是 bullet，是连续的段落。
 讲清楚：今天这批论文在说什么故事？哪些方向在同时发力？
 像你在跟一个同行朋友聊："你知道吗，这几天有意思的是……"
 要体现出领域的脉搏：正在争论什么，正在突破什么，正在走向哪里。}

---

## 研究温度计 / Field Pulse

| 方向 | 今日篇数 | 温度 | 信号质量 |
|------|---------|------|---------|
| 推理训练 / RL-for-Reasoning | N | 🔴 沸腾 | ★★★★ |
| Agent RL / 工具调用 | N | 🟠 升温 | ★★★☆ |
| 推理系统 / Inference Opt. | N | 🟡 活跃 | ★★★★ |
| 分布式训练 / Distributed | N | 🟢 稳健 | ★★★☆ |
| 其他 | N | ⚪ 杂音 | ★★☆☆ |

---

## 精选论文 / Curated Papers

---

**[N]. {Title}**
`{arxiv_id}` · {venue} · [[MonthName/YYYY-MM-DD/slug|摘要]] · [[MonthName/YYYY-MM-DD/deep-reads/slug_deepread|📖精读]]
> 💬 **背景**：{1句话：这篇为什么在这个时间点出现？领域里哪个痛点？}

- ⭐ 价值评级: **N/10** | 🔑 关键数字: {方法名 + 最重要的数字}
- 核心创新：{具体——不说"提出了一种新方法"}
- 工程要点：{用 X 实现 Y，可操作}（精读论文专用）
- 局限：{范围、代码、算力、生产风险}

（评分 ≤ 5 的论文只写 `⭐ 价值评级` 一行 + 一句背景，无需展开）

---

## 开放问题 / What's Still Unsettled

{2–3 条。今日论文背后领域仍在争论的核心问题。
 不是对论文的评价，而是读了这些论文之后你脑子里留下的未解问题。
 让读者带着问题去读，而不是带着答案离开。}

---

## 今日批次质量 / Batch Quality

{3–4 句叙事。今天整体是高信号日还是低信号日？
 信号最强的是哪个方向？有没有某篇值得深入追踪？
 如果今天只能读一篇，应该读哪篇，为什么？}
```

---

## 核心原则

1. **直接，有观点**：说出判断，不要两边都说"这很有意思"
2. **校准评分**：5 分是中位，不是差评。每天不会全是 9-10
3. **明确指出**：benchmark 过拟合、p-hacking、baseline 不公平、模糊声明
4. **工程视角优先**：工程启示必须可操作
5. **HF 热度 ≠ 质量**：HF trending 但关键词不相关的，明确标注
6. **精读优先级**：Agent RL 类 > kernel/system 类 > distributed training 类 > RLHF 类 > 其他
7. **72 小时窗口**：每日覆盖过去三天提交的论文，SQLite 去重，trending >3 次跳过
8. **有温度**：日报叙事段要有人味，帮读者建立认知地图，不只是列表
9. **路径格式**：vault 目录用 `YYYY/MonthName/YYYY-MM-DD/`（如 `2026/March/2026-03-03/`），由 `file_manager.py` 自动处理

## Obsidian 内链格式

vault 内链使用：`[[MonthName/YYYY-MM-DD/slug|Title]]`（相对于 PaperDaily/ 根目录）

例：`[[March/2026-03-03/2503.18773_bitdecoding_accelerating_large-batch_llm_decoding|BitDecoding]]`

---

## 依赖脚本速查

| 脚本 | 作用 |
|------|------|
| `main.py` | 主编排，fetch + dedup，输出 prepared.json |
| `download_pdfs.py` | 批量下载 arxiv PDF |
| `file_manager.py` | 目录结构管理 |
| `fetch_arxiv.py` | arxiv API 抓取 |
| `fetch_hf.py` | HuggingFace Daily Papers |
| `dedup.py` | SQLite 去重数据库 |
| `figure_extractor.py` | 从 arxiv HTML 提取图片 |
| `obsidian_linker.py` | 搜索 vault 关联笔记 |
| `keyword_tracker.py` | 关键词进化追踪 |
| `report_aggregator.py` | 周报/月报/季报 |
| `setup_schedule.py` | macOS launchd 定时 9:00 AM |
