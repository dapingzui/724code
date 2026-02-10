<p align="center">
  <h1 align="center">724code</h1>
  <p align="center">
    Control Claude Code from your phone via Telegram
    <br />
    <a href="#中文说明">中文说明</a> · <a href="#installation">Installation</a> · <a href="#usage">Usage</a>
  </p>
</p>

---

**724code** turns your home server (NAS, Linux box, or any always-on machine) into a remote coding workstation. Send a message on Telegram, and Claude Code executes it on your machine — read files, write code, run git, manage projects, all from your phone.

## Why?

- You're away from your desk but need to push a fix
- Your NAS has the code, your phone has the idea
- You want Claude Code's full power without opening a laptop

## Features

| Category | Commands |
|----------|----------|
| **AI Coding** | Send any text → Claude Code executes it with full CLI access |
| **Natural Language** | 🆕 Use plain language instead of slash commands: "show repos", "switch to test1", "check status" |
| **Projects** | `/projects` `/cd` `/newproject` `/clone` `/repos` `/addproject` `/rmproject` |
| **Git** | `/diff` `/commit` `/push` `/pull` `/branch` `/log` `/gs` |
| **Files** | `/cat` (with line ranges) `/tree` (directory view) |
| **Sessions** | `/new` `/status` `/model` `/abort` |
| **Memory** | `/memory` `/search` — per-project execution history with context injection |
| **GitHub** | Auto-create repos on `/newproject`, clone with `/clone`, browse with `/repos` |

## Architecture

```
Phone (Telegram) → Telegram API ←(Polling)← Your Server (Python) → Claude Code CLI
```

- **Polling mode** — no public IP needed, no port forwarding, works behind NAT
- **Proxy support** — HTTP/SOCKS5 for both Telegram API and Claude Code
- **Per-project memory** — each project stores its own execution history in `.724code/memories.db`
- **Output compression** — long outputs are intelligently truncated for mobile reading

## Requirements

| Tool | Required | Install |
|------|----------|---------|
| Python 3.11+ | Yes | [python.org](https://www.python.org/downloads/) |
| Git | Yes | [git-scm.com](https://git-scm.com/downloads) |
| Claude Code CLI | Yes | `npm install -g @anthropic-ai/claude-code` |
| GitHub CLI | Optional | [cli.github.com](https://cli.github.com/) |

## Installation

### One-line install (Linux/macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/dapingzui/724code/main/install.sh | bash
```

### Manual install

```bash
git clone https://github.com/dapingzui/724code.git
cd 724code
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml with your Telegram bot token and settings
```

### Configure

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and get the token
2. Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot)
3. Edit `config.yaml`:

```yaml
telegram:
  token: "YOUR_BOT_TOKEN"
  allowed_users:
    - YOUR_USER_ID

projects:
  workspace_root: "/home/you/projects"
```

### Run

```bash
# Development
python main.py

# Production (systemd)
sudo cp 724code.service /etc/systemd/system/
sudo systemctl enable --now 724code
```

## Usage

Open your Telegram bot and start sending messages:

### Natural Language Commands (New!)

```
You: 仓库                    # or "show repos", "my repositories"
Bot: [Lists your GitHub repos]

You: 项目列表                # or "list projects"
Bot: [Shows all registered projects]

You: 切换到myapp             # or "switch to myapp"
Bot: ✅ 已切换到: myapp

You: 查看变更                # or "show changes", "diff"
Bot: [Git diff output]

You: 状态                    # or "status", "current state"
Bot: [Session info]

You: 提交修复登录bug          # or "commit fix login bug"
Bot: ✅ [bot] 修复登录bug
```

### Traditional Slash Commands

```
You: /newproject myapp 一个新的web应用
Bot: ✅ 已创建项目: myapp
     GitHub 仓库已创建: https://github.com/...

You: /clone owner/repo
Bot: ✅ 已克隆并注册: repo

You: 看一下项目结构
Bot: [Claude Code analyzes and responds]
```

## Configuration

See [`config.example.yaml`](config.example.yaml) for all options with comments.

Key sections:
- **proxy** — HTTP/SOCKS5 proxy URL (required if behind firewall)
- **telegram** — bot token + whitelist
- **projects** — workspace root, GitHub integration toggle
- **claude** — model, timeout, allowed tools
- **git** — user identity, protected branches

## Security

- **Whitelist only** — only configured Telegram user IDs can interact
- **Path escape protection** — file operations are confined to project directories
- **Protected branches** — configurable branches that block direct push
- **No secrets in repo** — `config.yaml` is gitignored

## License

MIT

---

<a id="中文说明"></a>

## 中文说明

**724code** 把你的家用服务器（NAS、Linux 主机等）变成远程编码工作站。在 Telegram 上发消息，Claude Code 就在你的机器上执行——读文件、写代码、操作 Git，全部用手机完成。

### 为什么需要？

- 人不在电脑前，但需要推一个修复
- NAS 上有代码，手机上有灵感
- 想用 Claude Code 的全部能力，不想开电脑

### 核心特性

- **Telegram 控制** — Polling 模式，不需要公网 IP，NAT 后面直接用
- **代理支持** — Telegram API 和 Claude Code 都走代理
- **项目管理** — 多项目切换，GitHub 仓库自动创建/克隆
- **Git 集成** — diff/commit/push/pull/branch 全套
- **记忆系统** — 每个项目独立存储执行历史，新会话自动注入上下文
- **输出压缩** — 长输出智能截断，适配手机阅读

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/dapingzui/724code/main/install.sh | bash
```

### 手动安装

```bash
git clone https://github.com/dapingzui/724code.git
cd 724code
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入 Telegram Bot Token 等配置
python main.py
```

### 必备工具

| 工具 | 必需 | 安装方式 |
|------|------|----------|
| Python 3.11+ | 是 | [python.org](https://www.python.org/downloads/) |
| Git | 是 | `apt install git` / [git-scm.com](https://git-scm.com/) |
| Claude Code | 是 | `npm install -g @anthropic-ai/claude-code` |
| GitHub CLI | 可选 | [cli.github.com](https://cli.github.com/)（用于 /clone, /repos, /newproject 自动建仓） |

### systemd 部署

```bash
sudo cp 724code.service /etc/systemd/system/
sudo systemctl enable --now 724code
sudo journalctl -u 724code -f  # 查看日志
```
