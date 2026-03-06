---
name: skill-recorder
description: >
  Skill manager for creating, recording, and syncing Claude Code custom skills.
  ALWAYS use this skill when the user wants to: create a new skill, record a skill,
  document a skill, add a skill to their collection, save a skill, sync a skill to
  Jwt-s-SKILL, update the skill registry, or asks about managing their skill library.
  Trigger keywords: "记录skill", "创建skill", "新建skill", "添加skill", "保存skill",
  "同步skill", "skill录入", "写一个skill", "record skill", "create skill", "new skill",
  "add skill", "save skill", "sync skill".
---

# Skill Recorder — Skill 创建与同步工作流

帮助用户创建新的 Claude Code Skill，并自动同步到 `~/.claude/skills/` 和 `Jwt-s-SKILL` 仓库。

---

## 目录结构

```
~/.claude/skills/
└── {skill-name}/
    └── SKILL.md

~/Documents/Jwt-s-SKILL/
├── README.md          ← 自动更新
└── {skill-name}/
    └── SKILL.md       ← 自动同步
```

---

## 工作流

### Step 1 — 收集信息

向用户确认以下信息（如果用户未提供）：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | Skill 唯一标识，小写连字符 | `paper-daily` |
| `description` | 一句话描述 + 触发场景 | "每日论文追踪，触发词：论文日报…" |
| 触发词 | 中英文关键词列表 | `"论文日报"、"paper daily"` |
| 功能描述 | 这个 skill 做什么，工作流是什么 | 分阶段描述 |

### Step 2 — 生成 SKILL.md

按以下模板生成 `SKILL.md` 内容：

```markdown
---
name: {name}
description: >
  {一段完整的 description，包含触发场景和关键词}
---

# {Name} — {一句话定义}

{简短介绍}

---

## 工作流 / Workflow

{按阶段描述每个步骤}

---

## 触发词 / Trigger Keywords

{列出所有触发关键词}
```

### Step 3 — 写入 `~/.claude/skills/`

```bash
mkdir -p ~/.claude/skills/{name}
# 将生成的 SKILL.md 写入
```

写入路径：`~/.claude/skills/{name}/SKILL.md`

### Step 4 — 同步到 Jwt-s-SKILL

```bash
JWTSKILL_DIR=~/Documents/Jwt-s-SKILL
mkdir -p "$JWTSKILL_DIR/{name}"
cp ~/.claude/skills/{name}/SKILL.md "$JWTSKILL_DIR/{name}/SKILL.md"
```

### Step 5 — 更新 Jwt-s-SKILL README

读取 `Jwt-s-SKILL/README.md`，在 `## Skills 列表` 下追加新 skill 条目：

```markdown
### [`{name}`](./{name}/SKILL.md)

{一句话描述，突出核心功能}

- {核心特性 1}
- {核心特性 2}

触发词：{列出主要触发词，用反引号包裹}

---
```

### Step 6 — 确认完成

输出完成摘要：

```
✓ 已创建：~/.claude/skills/{name}/SKILL.md
✓ 已同步：Jwt-s-SKILL/{name}/SKILL.md
✓ 已更新：Jwt-s-SKILL/README.md
```

---

## 核心原则

1. **description 要完整**：YAML frontmatter 中的 description 决定 skill 何时被触发，必须包含所有触发场景和关键词
2. **name 全局唯一**：创建前检查 `~/.claude/skills/` 下是否已存在同名目录
3. **同步幂等**：多次运行不会产生重复条目，README 更新前检查是否已存在
4. **先写 `~/.claude/skills/`，再同步**：始终以本地 skills 目录为主副本，Jwt-s-SKILL 为备份/展示仓库

---

## 触发词 / Trigger Keywords

`记录skill`、`创建skill`、`新建skill`、`添加skill`、`保存skill`、`同步skill`、
`skill录入`、`写一个skill`、`record skill`、`create skill`、`new skill`、
`add skill`、`save skill`、`sync skill`
