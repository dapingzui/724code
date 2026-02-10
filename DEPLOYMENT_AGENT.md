# AI Agent Deployment Guide

This guide is specifically written for AI agents (like Claude) to understand and deploy the 724code project on a new machine.

## What is 724code?

A Telegram bot that controls Claude Code CLI on a remote server (NAS/Linux), enabling mobile coding via natural language commands.

## Architecture Overview

```
User Phone (Telegram)
    ↓
Telegram API (via proxy)
    ↓
NAS Python Service (this project)
    ↓
Claude Code CLI (local installation)
    ↓
Project Files (local filesystem)
```

**Key Design Principles:**
- Polling mode (no public IP needed)
- Proxy support (HTTP/SOCKS5)
- Per-project memory with SQLite
- Natural language + slash commands

## Prerequisites Checklist

Before deploying, verify these are installed on the target machine:

| Tool | Required | Check Command | Install |
|------|----------|---------------|---------|
| Python 3.11+ | Yes | `python3 --version` | [python.org](https://python.org) |
| Git | Yes | `git --version` | [git-scm.com](https://git-scm.com) |
| Claude Code CLI | Yes | `claude --version` | `npm install -g @anthropic-ai/claude-code` |
| GitHub CLI | Optional | `gh --version` | [cli.github.com](https://cli.github.com) |
| Proxy (optional) | If behind firewall | `curl -I https://api.telegram.org` | User-dependent |

## Step-by-Step Deployment

### 1. Clone Repository

```bash
cd ~
git clone https://github.com/dapingzui/724code.git
cd 724code
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies:**
- `python-telegram-bot[socks]>=20.0` - Telegram Bot SDK with SOCKS proxy support
- `pyyaml>=6.0` - Configuration file parsing
- `httpx[socks]>=0.24.0` - HTTP client for proxy support

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

**Critical Configuration Items:**

#### Telegram Section
```yaml
telegram:
  token: "YOUR_BOT_TOKEN"        # Get from @BotFather
  allowed_users:
    - 123456789                   # Get from @userinfobot
```

#### Proxy Section (if needed)
```yaml
proxy:
  url: "http://127.0.0.1:7890"   # Your proxy address
  # or "socks5://127.0.0.1:1080"
```

#### Projects Section
```yaml
projects:
  workspace_root: "/home/user/projects"  # Change to actual path
```

#### Claude Section
```yaml
claude:
  command: "claude"
  model: "claude-sonnet-4-5-20250929"
  allowed_tools:
    - "Read"
    - "Write"
    - "Edit"
    - "Bash"
    - "Grep"
```

### 4. Authenticate Claude Code

```bash
# If behind proxy:
export HTTPS_PROXY=http://127.0.0.1:7890

# Login to Claude Code
claude auth login
```

Follow the browser OAuth flow. Your credentials will be saved to `~/.claude/.credentials.json`.

### 5. (Optional) Authenticate GitHub CLI

For `/newproject`, `/clone`, `/repos` commands:

```bash
gh auth login
```

### 6. Test Run

```bash
python main.py
```

**Expected Output:**
```
2026-02-11 12:00:00 [INFO] __main__: 724code 启动中...
2026-02-11 12:00:00 [INFO] __main__: ✅ git: /usr/bin/git
2026-02-11 12:00:00 [INFO] __main__: ✅ gh: /usr/bin/gh
2026-02-11 12:00:00 [INFO] __main__: ✅ claude: /usr/bin/claude
2026-02-11 12:00:00 [INFO] core.project_manager: 加载 0 个项目
2026-02-11 12:00:00 [INFO] adapters.telegram_adapter: Telegram Bot 使用代理: http://127.0.0.1:7890
2026-02-11 12:00:02 [INFO] adapters.telegram_adapter: Telegram Bot 已启动 (Polling 模式)
2026-02-11 12:00:02 [INFO] __main__: 724code 已就绪，等待消息...
```

### 7. Production Deployment (systemd)

```bash
# Edit service file
nano 724code.service
# Replace REPLACE_WITH_YOUR_USER and REPLACE_WITH_INSTALL_PATH

# Install service
sudo cp 724code.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable 724code
sudo systemctl start 724code

# Check status
sudo systemctl status 724code

# View logs
sudo journalctl -u 724code -f
```

## Key Files to Understand

### Core Components

| File | Purpose | Key Functions |
|------|---------|---------------|
| `main.py` | Entry point | Initializes all components, starts bot |
| `core/router.py` | Message routing | `handle()`, `_try_semantic_match()`, command handlers |
| `core/executor.py` | Claude Code wrapper | `run()` - executes Claude CLI with JSON output |
| `core/session_manager.py` | Session state | Tracks projects, models, session IDs per user |
| `core/project_manager.py` | Project CRUD | `/newproject`, `/clone`, GitHub integration |
| `adapters/telegram_adapter.py` | Telegram interface | Polling, message send/receive |
| `memory/store.py` | SQLite memory | Per-project execution history with FTS5 search |

### Configuration Files

| File | Purpose |
|------|---------|
| `config.yaml` | Runtime configuration (gitignored) |
| `config.example.yaml` | Configuration template with comments |
| `data/projects.yaml` | Dynamic project registry (created at runtime) |

## How Commands Are Processed

### Flow Diagram

```
Telegram Message
    ↓
router.handle()
    ↓
Starts with "/"?
    ├─ Yes → _handle_command() → Execute meta-command
    └─ No  → _try_semantic_match()
                ├─ Matched → Execute corresponding command
                └─ Not matched → _handle_claude() → Claude Code CLI
```

### Semantic Matching Examples

| User Input | Matched Command | Notes |
|------------|----------------|-------|
| "仓库" | `/repos` | Chinese keyword |
| "show repos" | `/repos` | English keyword |
| "切换到test1" | `/cd test1` | Extract project name |
| "提交修复bug" | `/commit 修复bug` | Extract commit message |
| "查看变更" | `/diff` | Simple match |
| "状态" | `/status` | Simple match |

**Implementation:** `core/router.py:_try_semantic_match()`

## Common Issues and Solutions

### 1. Bot Not Receiving Messages

**Symptom:** Bot starts successfully but doesn't respond to Telegram messages.

**Causes:**
- Polling loop stuck
- Multiple instances running (conflict)
- Proxy issues

**Solutions:**
```bash
# Check for multiple instances
ps aux | grep python.*main.py

# Kill all instances
pkill -f 'python.*main.py'

# Test proxy
curl --proxy http://127.0.0.1:7890 https://api.telegram.org/

# Restart bot
python main.py
```

### 2. Claude Code Authentication Failed

**Symptom:** `Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error"...`

**Solution:**
```bash
# Remove old credentials
rm ~/.claude/.credentials.json

# Re-authenticate
export HTTPS_PROXY=http://127.0.0.1:7890  # if needed
claude auth login
```

### 3. Import Error: No module named 'telegram'

**Symptom:** `ModuleNotFoundError: No module named 'telegram'`

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Or install specific package
pip install python-telegram-bot[socks]
```

### 4. FTS5 Not Available

**Symptom:** `SQLite FTS5 不可用，搜索将使用 LIKE 模糊匹配`

**Solution:** This is a warning, not an error. The system will fallback to LIKE search. FTS5 is optional.

If you want full FTS5 support, rebuild SQLite with FTS5 enabled (advanced).

### 5. GitHub Operations Not Working

**Symptom:** `/repos`, `/clone`, `/newproject` fail

**Solution:**
```bash
# Authenticate GitHub CLI
gh auth login

# Verify authentication
gh auth status
```

## Directory Structure After First Run

```
724code/
├── main.py
├── config.yaml                 # Your configuration
├── data/
│   ├── projects.yaml           # Auto-created project registry
│   └── memories.db             # Global memory (deprecated)
├── core/
├── adapters/
├── memory/
├── utils/
└── [project workspace]/        # e.g., ~/projects/
    └── myproject/
        └── .724code/
            └── memories.db     # Per-project memory
```

## Testing the Deployment

Send these messages to your Telegram bot:

1. **Basic test:** `/help`
   - Expected: Command list

2. **Natural language:** `状态`
   - Expected: Current session status

3. **Project creation:** `/newproject test "测试项目"`
   - Expected: Project created + GitHub repo created (if gh authenticated)

4. **Claude Code test:** `1+1等于几`
   - Expected: Claude Code response

5. **GitHub test:** `仓库`
   - Expected: List of your GitHub repositories

## Security Considerations

### Whitelist Configuration

**Critical:** Only whitelisted Telegram user IDs can use the bot.

```yaml
telegram:
  allowed_users:
    - 123456789    # Your user ID
    - 987654321    # Team member ID
```

Get your user ID from [@userinfobot](https://t.me/userinfobot).

### Protected Branches

Git push is blocked for protected branches (configured in `config.yaml`):

```yaml
git:
  protected_branches:
    - "main"
    - "production"
```

### Allowed Tools

Claude Code is restricted to specific tools (configured in `config.yaml`):

```yaml
claude:
  allowed_tools:
    - "Read"
    - "Write"
    - "Edit"
    - "Bash"
    - "Grep"
```

**Not allowed by default:** `Task`, `WebFetch`, `WebSearch` (to prevent uncontrolled API usage)

## Monitoring and Logs

### Log Locations

- **Development:** `stdout` (console)
- **Production (systemd):** `journalctl -u 724code`
- **Manual run:** Redirect to file: `python main.py > /tmp/724code.log 2>&1 &`

### Log Levels

```python
# In main.py
setup_logging("INFO")  # Change to "DEBUG" for verbose logs
```

### Useful Log Queries

```bash
# Real-time monitoring
tail -f /tmp/724code.log

# Filter by level
grep ERROR /tmp/724code.log

# User messages only
grep "收到消息" /tmp/724code.log

# Last 50 lines
tail -50 /tmp/724code.log
```

## Performance Optimization

### Model Selection

Configure in `config.yaml`:

```yaml
claude:
  model: "claude-sonnet-4-5-20250929"  # Recommended: Best balance
  # model: "claude-haiku-4-5-20251001"   # Fastest, cheapest
  # model: "claude-opus-4-6"             # Most capable, expensive
```

Users can switch models with `/model sonnet|opus|haiku` command.

### Output Compression

Long Claude Code outputs are compressed to fit Telegram's 4096 character limit:

```yaml
output:
  max_message_length: 4000  # Leave margin for formatting
```

- Head 60% + Tail 30% strategy
- Files changed summary preserved
- Use `/detail` to see full output

## Extending the Bot

### Adding New Commands

Edit `core/router.py`:

```python
# 1. Add to handlers dict
handlers = {
    # ... existing commands
    "/mycommand": self._cmd_mycommand,
}

# 2. Implement handler
async def _cmd_mycommand(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
    # Your logic here
    await self._reply(adapter, msg.chat_id, "Response")
```

### Adding Semantic Keywords

Edit `core/router.py:_try_semantic_match()`:

```python
# Add new pattern
if any(kw in text_lower for kw in ["我的关键词", "my keyword"]):
    await self._cmd_mycommand(msg, adapter, "")
    return True
```

### Adding New Adapters (e.g., Feishu, Slack)

1. Create `adapters/feishu_adapter.py`
2. Inherit from `adapters.base.BotAdapter`
3. Implement `start()`, `stop()`, `send_message()`
4. Initialize in `main.py`

See `adapters/telegram_adapter.py` as reference.

## Troubleshooting Checklist

If the bot doesn't work, check these in order:

- [ ] Python 3.11+ installed
- [ ] Dependencies installed (`pip list | grep telegram`)
- [ ] Config file exists and valid (`cat config.yaml`)
- [ ] Telegram token is correct
- [ ] User ID is whitelisted
- [ ] Claude Code authenticated (`claude auth status`)
- [ ] Proxy working if configured (`curl --proxy ... https://api.telegram.org`)
- [ ] No other bot instances running (`ps aux | grep main.py`)
- [ ] Logs show "已就绪，等待消息..." (`tail /tmp/724code.log`)

## Further Reading

- **CLAUDE.md** - Development guide and architecture details
- **README.md** - User-facing documentation
- **design.md** - Original design document (comprehensive)
- **SKILLS.md** - Skills and patterns used in development

## Support

- GitHub Issues: https://github.com/dapingzui/724code/issues
- Project Documentation: All `.md` files in repository root

---

**Last Updated:** 2026-02-11
**Compatible with:** 724code v1.0 (Stage 5 complete + Semantic Commands)
