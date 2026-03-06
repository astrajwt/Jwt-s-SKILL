# Jwt-s-SKILL

Jwt 的 Claude Code 自定义 Skill 合集。

---

## Skills 列表

### [`paper-daily`](./paper-daily/SKILL.md)

每日论文追踪系统，三段式工作流：**收集 + 下载 → 通读评分 → 精读产出**。

- 数据源：arXiv + HuggingFace Daily Papers
- 输出：结构化 Obsidian 笔记（summaries / deep-reads / 日报）
- 支持按天/周/月/季度生成报告
- 评分校准、72 小时去重、精读优先级（Agent RL > kernel/system > distributed training）

触发词：`论文日报`、`paper daily`、`fetch today's papers`、`arxiv`、`huggingface papers`

---

### [`github-issue-reader`](./github-issue-reader/SKILL.md)

GitHub Issue 全量阅读、归纳分析与中文技术文档写作。

- 5 阶段工作流：范围确认 → 逐 issue 深读 → 聚类主题地图 → 时间线演进 → 可发布文档
- 证据驱动：每个结论附 issue 编号 / 评论链接 / PR 引用
- 输出：结构化 Obsidian 笔记或中文博客文章

触发词：`读 issues`、`issue 归纳`、`开源项目调研`、`技术债分析`

---

### [`github-repo-monitor`](./github-repo-monitor/SKILL.md)

监控目标 GitHub 仓库的最新 PR 和 Issue 动态，识别贡献机会。

- 当前监控仓库：`shader-slang/slang`、`vllm-project/vllm`
- 过滤过去 1 小时内的更新
- 识别 `good-first-issue`、`help-wanted`、无人认领的 bug
- 输出：Markdown 摘要文件 + 对话内通知

---

## 使用方法

将任意 skill 目录放到 `.claude/skills/` 下即可被 Claude Code 自动加载，或在对话中直接描述触发词。

```
~/.claude/skills/
├── paper-daily/
│   └── SKILL.md
├── github-issue-reader/
│   └── SKILL.md
└── github-repo-monitor/
    └── SKILL.md
```
