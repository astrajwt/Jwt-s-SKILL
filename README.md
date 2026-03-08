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

### [`feishu-hook-notify`](./feishu-hook-notify/SKILL.md)

Claude Code 任务完成后自动推送飞书卡片通知，基于飞书开放平台应用型机器人。

- 任务完成时发绿色卡片：电脑名、工作目录、耗时、工具调用统计、操作文件、Claude 最后回复
- 任务运行超 1 小时每小时发橙色心跳卡片
- 通过手机号自动查询 open_id，首次运行后缓存，无需手动配置
- 纯标准库实现，无第三方依赖，macOS SSL 自动兼容

触发词：`飞书通知`、`配置飞书`、`任务完成提醒`、`飞书 hook`、`feishu notify`、`feishu hook`

---

### [`book-reader`](./book-reader/SKILL.md)

技术书籍 PDF 深度阅读，生成工程师视角的高质量读书笔记。

- 以系统性能专家 + AI Infrastructure 工程师双重视角阅读
- 主动联系 GPU / LLM / 分布式系统场景展开分析
- 输出结构化 Markdown 笔记，含 Mermaid 图示、伪代码、性能分析

触发词：`读书`、`读 PDF`、`书籍笔记`、`read book`、`read pdf`、`深度阅读`、`生成读书笔记`

---

### [`skill-recorder`](./skill-recorder/SKILL.md)

Skill 创建与同步工具，帮助将新 skill 录入本地并备份到 Jwt-s-SKILL 仓库。

- 引导填写 name、description、触发词和工作流
- 自动写入 `~/.claude/skills/{name}/SKILL.md`
- 自动同步副本到 `Jwt-s-SKILL/{name}/SKILL.md`
- 自动更新本 README

触发词：`记录skill`、`创建skill`、`新建skill`、`同步skill`、`record skill`、`create skill`

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
