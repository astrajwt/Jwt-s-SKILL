---
name: feishu-hook-notify
description: >
  Claude Code 任务完成后自动发送飞书通知的 Hook 配置向导。
  ALWAYS use this skill when the user wants to: 配置飞书通知、设置任务完成提醒、
  Claude Code hook 飞书、任务结束发消息、setup Feishu notification、
  configure Claude Code hook、飞书 hook、hook 通知、任务完成通知。
  Trigger keywords: "飞书通知", "任务完成提醒", "配置飞书", "飞书 hook",
  "feishu notify", "feishu hook", "task done notify", "claude hook 飞书",
  "完成后发飞书", "设置通知".
---

# feishu-hook-notify — Claude Code 任务完成飞书通知

通过飞书开放平台应用型机器人，在 Claude Code 完成任务时自动推送一张结构化卡片，包含：电脑名、工作目录、耗时统计、工具调用详情、操作文件列表，以及 Claude 的最后一段回复。任务运行超过 1 小时还会每小时发一次进度心跳。

---

## 前置条件

在[飞书开放平台](https://open.feishu.cn/)创建一个**企业自建应用**，并完成以下配置：

### 1. 开通权限

在应用后台 → **权限管理** 中开通：

| 权限标识 | 用途 |
|----------|------|
| `contact:user.id:readonly` | 通过手机号查询用户 open_id |
| `im:message` | 发送单聊消息 |

### 2. 开启机器人能力

应用后台 → **应用功能** → 开启**机器人**。

### 3. 发布版本

每次修改权限或功能后需重新**创建版本并发布**，否则改动不生效。

---

## 配置步骤

### Step 1 — 安装 hook 脚本

将以下脚本保存到 `~/.claude/hooks/feishu_notify.py`（或项目的 `.claude/hooks/` 目录下）：

```python
#!/usr/bin/env python3
"""
Claude Code → 飞书通知 (via Open Platform API)
- PostToolUse: 每小时发一次进度心跳
- Stop: 任务结束发完成总结卡片
"""

import sys
import json
import os
import time
import socket
import urllib.request
from pathlib import Path

APP_ID     = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
MOBILE     = os.environ.get("FEISHU_MOBILE", "")

SESSIONS_DIR  = Path.home() / ".claude" / "hook-sessions"
OPEN_ID_CACHE = Path.home() / ".claude" / "feishu_open_id.cache"
HOURLY = 3600

BASE_URL = "https://open.feishu.cn/open-apis"


def get_ssl_ctx():
    import ssl
    for cafile in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if Path(cafile).exists():
            return ssl.create_default_context(cafile=cafile)
    return ssl._create_unverified_context()


def api_post(path: str, payload: dict, token: str = "") -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, context=get_ssl_ctx(), timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[feishu_notify] API 请求失败 {path}: {e}", file=sys.stderr)
        return {}


def get_access_token() -> str:
    resp = api_post("/auth/v3/tenant_access_token/internal", {
        "app_id": APP_ID, "app_secret": APP_SECRET,
    })
    return resp.get("tenant_access_token", "")


def get_open_id(token: str) -> str:
    if OPEN_ID_CACHE.exists():
        cached = OPEN_ID_CACHE.read_text().strip()
        if cached:
            return cached
    resp = api_post("/contact/v3/users/batch_get_id", {
        "mobiles": [MOBILE], "user_id_type": "open_id",
    }, token=token)
    try:
        open_id = resp["data"]["user_list"][0]["user_id"]
        OPEN_ID_CACHE.write_text(open_id)
        return open_id
    except (KeyError, IndexError):
        print(f"[feishu_notify] 无法获取 open_id: {resp}", file=sys.stderr)
        return ""


def send_card(title: str, body: str, color: str = "blue") -> None:
    if not APP_ID or not APP_SECRET or not MOBILE:
        return
    token = get_access_token()
    if not token:
        return
    open_id = get_open_id(token)
    if not open_id:
        return
    card = {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}}
        ],
    }
    api_post("/im/v1/messages?receive_id_type=open_id", {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }, token=token)


def get_last_response(transcript_path: str) -> str:
    if not transcript_path:
        return ""
    try:
        path = Path(transcript_path)
        if not path.exists():
            return ""
        for line in reversed(path.read_text().strip().splitlines()):
            try:
                entry = json.loads(line)
                msg = entry.get("message") or entry
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "").strip()
                                if text:
                                    return text[:600]
                    elif isinstance(content, str) and content.strip():
                        return content.strip()[:600]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def load_state(sid: str) -> dict:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    f = SESSIONS_DIR / f"{sid}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    now = time.time()
    return {
        "start": now, "last_notify": now,
        "start_str": time.strftime("%H:%M:%S"),
        "tool_counts": {}, "bash_cmds": [], "files": [],
    }


def save_state(sid: str, state: dict) -> None:
    (SESSIONS_DIR / f"{sid}.json").write_text(json.dumps(state, ensure_ascii=False))


def drop_state(sid: str) -> None:
    f = SESSIONS_DIR / f"{sid}.json"
    if f.exists():
        f.unlink()


def build_body(state: dict, now: float) -> str:
    elapsed_s = int(now - state["start"])
    elapsed_m = elapsed_s // 60
    dur = f"{elapsed_m} 分钟" if elapsed_m > 0 else f"{elapsed_s} 秒"
    lines = [f"**开始**：{state['start_str']}　**已运行**：{dur}", ""]
    counts: dict = state.get("tool_counts", {})
    if counts:
        top = sorted(counts.items(), key=lambda x: -x[1])[:8]
        lines += [f"**工具调用** {sum(counts.values())} 次",
                  "　".join(f"`{k}` ×{v}" for k, v in top), ""]
    files: list = state.get("files", [])
    if files:
        lines += ["**操作文件**"] + [f"- `{f}`" for f in files[-8:]] + [""]
    cmds: list = state.get("bash_cmds", [])
    if cmds:
        lines += ["**最近命令**"] + [f"- `{c}`" for c in cmds[-5:]]
    return "\n".join(lines)


def handle_post_tool_use(data: dict) -> None:
    sid        = (data.get("session_id") or "unknown")[:12]
    tool_name  = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    state = load_state(sid)
    now   = time.time()
    counts = state.setdefault("tool_counts", {})
    counts[tool_name] = counts.get(tool_name, 0) + 1
    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "").strip()[:100]
        if cmd:
            cmds: list = state.setdefault("bash_cmds", [])
            cmds.append(cmd)
            state["bash_cmds"] = cmds[-15:]
    if tool_name in ("Write", "Edit", "Read", "NotebookEdit"):
        fp = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if fp:
            files: list = state.setdefault("files", [])
            if fp not in files:
                files.append(fp)
                state["files"] = files[-20:]
    save_state(sid, state)
    if now - state.get("last_notify", now) >= HOURLY:
        elapsed_m = int((now - state["start"]) / 60)
        send_card(f"⏰ Claude 运行中 · {elapsed_m} min",
                  build_body(state, now), color="orange")
        state["last_notify"] = now
        save_state(sid, state)


def handle_stop(data: dict) -> None:
    sid             = (data.get("session_id") or "unknown")[:12]
    transcript_path = data.get("transcript_path", "")
    now             = time.time()
    state    = load_state(sid)
    elapsed_s = int(now - state["start"])
    elapsed_m = elapsed_s // 60
    dur      = f"{elapsed_m} 分钟" if elapsed_m > 0 else f"{elapsed_s} 秒"
    end_str  = time.strftime("%H:%M:%S")
    hostname = socket.gethostname()
    cwd      = os.getcwd()
    title    = f"✅ Claude 完成　{state.get('start_str','?')} → {end_str}　共 {dur}"
    body     = build_body(state, now)
    body     = body.replace(
        f"**开始**：{state['start_str']}　**已运行**：{dur}",
        f"**开始**：{state.get('start_str','?')}　**结束**：{end_str}　**耗时**：{dur}",
    )
    body = f"**电脑**：{hostname}\n**目录**：`{cwd}`\n\n" + body
    last_reply = get_last_response(transcript_path)
    if last_reply:
        body += f"\n\n**Claude 回复**\n{last_reply}"
    send_card(title, body, color="green")
    drop_state(sid)


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    if event == "post-tool-use":
        handle_post_tool_use(data)
    elif event == "stop":
        handle_stop(data)
    sys.exit(0)
```

### Step 2 — 配置环境变量与 hook

在 `~/.claude/settings.json`（或项目的 `.claude/settings.json`）中添加：

```json
{
  "env": {
    "FEISHU_APP_ID": "cli_xxxxxxxxxxxxxxxx",
    "FEISHU_APP_SECRET": "你的 App Secret",
    "FEISHU_MOBILE": "你的飞书绑定手机号"
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/feishu_notify.py post-tool-use"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/feishu_notify.py stop"
          }
        ]
      }
    ]
  }
}
```

### Step 3 — 首次运行缓存 open_id

脚本第一次执行时会用手机号查询 open_id 并缓存到 `~/.claude/feishu_open_id.cache`，后续不再重复查询。

也可以手动预热（替换为真实 token 和手机号）：

```bash
python3 ~/.claude/hooks/feishu_notify.py stop <<< '{}'
```

---

## 通知卡片内容

**Stop 事件**（绿色卡片）：

```
✅ Claude 完成  09:12:00 → 09:18:34  共 6 分钟

电脑：MacBook-Pro.local
目录：/Users/xxx/projects/my-app

开始：09:12:00  结束：09:18:34  耗时：6 分钟

工具调用 23 次
`Bash` ×8  `Read` ×7  `Edit` ×5  `Write` ×3

操作文件
- /Users/xxx/projects/my-app/src/main.py
- /Users/xxx/projects/my-app/tests/test_main.py

最近命令
- pytest tests/
- git diff HEAD

Claude 回复
已完成所有修改，测试全部通过。主要改动：...
```

**PostToolUse 事件**（橙色卡片，每小时触发一次）：

```
⏰ Claude 运行中 · 62 min

电脑/目录/工具统计/文件列表...
```

---

## 注意事项

- `open_id` 缓存文件：`~/.claude/feishu_open_id.cache`，多台机器需分别运行一次生成
- 若更换手机号或应用，删除缓存文件后重新运行即可
- 脚本所有错误静默处理（`exit 0`），不影响 Claude Code 正常工作
- macOS 系统证书路径自动兼容，无需额外安装 SSL 证书

---

## 触发词 / Trigger Keywords

`飞书通知`、`任务完成提醒`、`配置飞书`、`飞书 hook`、`claude hook 飞书`、
`完成后发飞书`、`设置通知`、`feishu notify`、`feishu hook`、`task done notify`
