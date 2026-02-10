# Claude Code Remote Control Bot — 完整设计方案

## 1. 项目概述

### 1.1 目标

通过 Telegram / 飞书机器人远程操控家中电脑上的 Claude Code，实现：

- 手机端发送编码指令，Claude Code 执行后返回结果
- 多项目、多会话管理
- 跨会话的长期记忆系统
- 适配手机阅读的智能输出压缩

### 1.2 核心架构

```
┌─────────┐     ┌──────────────────────────────────────────────┐
│  手机端  │     │              家中电脑 (Server)                │
│         │     │                                              │
│ Telegram │────▶│  Bot Server (Python)                         │
│   App   │◀────│    ├── 消息路由 & 鉴权                        │
│         │     │    ├── 会话管理器 (Session Manager)            │
│  飞书    │────▶│    ├── 记忆系统 (Memory System)               │
│   App   │◀────│    ├── 输出处理器 (Output Processor)          │
│         │     │    └── Claude Code CLI 调用层                  │
└─────────┘     │                                              │
                │  Claude Code CLI                              │
                │    ├── CLAUDE.md (项目级记忆)                  │
                │    └── 各项目工作目录                           │
                └──────────────────────────────────────────────┘
```

---

## 2. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态丰富、异步支持好、Bot SDK 成熟 |
| 飞书 SDK | `lark-oapi` (官方) | WebSocket 长连接，本地即可开发测试，无需公网 IP |
| Telegram SDK | `python-telegram-bot` v20+ | Phase 2 扩展，Polling 模式同样无需公网 |
| 进程管理 | `asyncio.subprocess` | 非阻塞调用 Claude Code |
| 记忆存储 | SQLite + JSONL | 轻量、无需额外服务、支持全文搜索 |
| 配置管理 | YAML | 可读性好，适合多项目配置 |
| 部署 | systemd（生产）/ 直接运行（本地测试） | 自动重启、开机启动 |

---

## 3. 模块设计

### 3.1 整体模块图

```
bot/
├── config.yaml              # 全局配置（不含项目列表）
├── main.py                  # 入口
├── adapters/                # 消息平台适配层
│   ├── base.py              # 抽象基类
│   ├── telegram_adapter.py  # Telegram 实现
│   └── feishu_adapter.py    # 飞书实现
├── core/
│   ├── router.py            # 命令路由（元命令 vs Claude Code 指令）
│   ├── executor.py          # Claude Code 调用执行器
│   ├── session_manager.py   # 会话生命周期管理
│   ├── output_processor.py  # 输出格式化与压缩
│   ├── project_manager.py   # 项目生命周期管理（注册/新建/删除/列表）
│   ├── git_ops.py           # Git 操作（commit/push/pr/rollback）
│   └── file_manager.py      # 文件查看、上传、下载
├── memory/
│   ├── store.py             # 记忆存储引擎 (SQLite)
│   ├── compressor.py        # 记忆压缩（分层摘要）
│   ├── archiver.py          # 压缩前原始记录归档（JSONL 冷存储）
│   ├── injector.py          # 上下文注入（拼接 prompt）
│   └── claude_md_sync.py    # CLAUDE.md 自动维护
├── utils/
│   ├── security.py          # 白名单鉴权
│   └── logger.py            # 日志
└── data/
    ├── projects.yaml         # 项目注册表（运行时动态读写）
    ├── memories.db           # SQLite 数据库（活跃记忆）
    ├── archives/             # 压缩前的原始记录归档
    │   └── {project}_{date}.jsonl
    └── logs/                 # 执行日志
```

### 3.2 配置文件 `config.yaml`

```yaml
# ============ 平台配置 ============
telegram:
  token: "YOUR_TELEGRAM_BOT_TOKEN"
  allowed_users:
    - 123456789           # 你的 Telegram user ID

feishu:
  app_id: "YOUR_APP_ID"
  app_secret: "YOUR_APP_SECRET"
  allowed_users:
    - "ou_xxxxxxxxxxxx"   # 你的飞书 open_id

# ============ 项目配置 ============
projects:
  workspace_root: "/home/jake/projects"  # /newproject 默认在此目录下创建
  projects_file: "./data/projects.yaml"  # 项目注册表（运行时动态读写）
  default: "my-webapp"                   # 默认活跃项目
  scaffold_on_create: true               # /newproject 时是否让 Claude 搭脚手架
  init_git_on_create: true               # /newproject 时是否自动 git init

# ============ Claude Code 配置 ============
claude:
  model: "claude-sonnet-4-20250514"   # 默认模型
  max_turns: 25                        # 单次最大 agentic 轮数
  timeout: 300                         # 超时秒数
  allowed_tools:                       # 允许的工具
    - "Read"
    - "Write"
    - "Edit"
    - "Bash"
    - "Grep"
    - "WebSearch"
    - "WebFetch"

# ============ 输出配置 ============
output:
  mode: "smart"             # smart | full | summary
  max_message_length: 3500  # Telegram 单条上限留一些余量
  save_full_log: true       # 是否保存完整输出到本地

# ============ 记忆配置 ============
memory:
  db_path: "./data/memories.db"
  recent_entries: 15          # 注入最近 N 条记忆
  compress_threshold: 50      # 超过 N 条触发压缩
  max_context_tokens: 4000    # 记忆注入的 token 上限
  archive:
    enabled: true
    path: "./data/archives"   # 归档目录
    format: "jsonl"           # jsonl | sqlite
    retention_days: 365       # 归档保留天数（0 = 永久）

# ============ Git 配置 ============
git:
  auto_commit: false          # 是否每次执行后自动 commit
  auto_push: false            # 是否 commit 后自动 push
  default_branch: "main"
  commit_prefix: "[bot]"      # commit message 前缀
  protected_branches:         # 禁止直接 push 的分支
    - "main"
    - "production"

# ============ 文件管理配置 ============
files:
  max_cat_lines: 200          # /cat 最多显示行数
  max_file_size_mb: 10        # 发送文件的大小上限
  allowed_download_ext:       # 允许下载的文件类型
    - ".py"
    - ".js"
    - ".ts"
    - ".tsx"
    - ".json"
    - ".yaml"
    - ".md"
    - ".csv"
    - ".log"
    - ".pdf"
    - ".png"
    - ".jpg"
```

### 3.3 项目注册表 `data/projects.yaml`

**设计原则**：`config.yaml` 是静态配置（手动编辑，重启生效），`projects.yaml` 是动态数据（Bot 运行时读写，手机上通过命令管理）。

```yaml
# data/projects.yaml — 由 Bot 自动管理，也可手动编辑
# /addproject、/newproject 会自动追加条目
# /rmproject 会移除条目

my-webapp:
  path: "/home/jake/projects/my-webapp"
  description: "主要 Web 项目"
  created_at: "2025-02-01T10:00:00"
  git_initialized: true
  tags: ["web", "nextjs"]

trading-bot:
  path: "/home/jake/projects/trading-bot"
  description: "量化交易系统"
  created_at: "2025-02-05T14:30:00"
  git_initialized: true
  tags: ["python", "quant"]
```

---

## 4. 核心模块详细设计

### 4.1 消息平台适配层 (`adapters/`)

**设计目标**：统一不同平台的消息收发接口，核心逻辑与平台解耦。

```python
# adapters/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class IncomingMessage:
    """统一的入站消息格式"""
    platform: str          # "telegram" | "feishu"
    user_id: str
    chat_id: str
    text: str
    reply_to_msg_id: Optional[str] = None
    attachments: list = None  # 未来扩展：发送文件给 Claude

@dataclass
class OutgoingMessage:
    """统一的出站消息格式"""
    chat_id: str
    text: str
    parse_mode: str = "Markdown"  # Markdown | HTML | plain
    reply_to_msg_id: Optional[str] = None

class BotAdapter(ABC):
    """消息平台适配器基类"""

    @abstractmethod
    async def start(self):
        """启动 Bot 轮询/Webhook"""

    @abstractmethod
    async def send_message(self, msg: OutgoingMessage):
        """发送消息"""

    @abstractmethod
    async def send_file(self, chat_id: str, filepath: str, caption: str = ""):
        """发送文件（用于发送 diff、日志等）"""

    @abstractmethod
    async def send_typing_action(self, chat_id: str):
        """发送"正在输入"状态"""
```

```python
# adapters/telegram_adapter.py（核心实现片段）
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters

class TelegramAdapter(BotAdapter):
    def __init__(self, config, message_handler):
        self.config = config
        self.app = Application.builder().token(config["token"]).build()
        self.message_handler = message_handler  # core.router 的回调

        # 注册消息处理
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

    async def _on_message(self, update: Update, context):
        user_id = update.effective_user.id
        if user_id not in self.config["allowed_users"]:
            return  # 静默忽略非白名单用户

        msg = IncomingMessage(
            platform="telegram",
            user_id=str(user_id),
            chat_id=str(update.effective_chat.id),
            text=update.message.text,
        )
        # 交给路由层处理
        await self.message_handler(msg, self)

    async def send_message(self, msg: OutgoingMessage):
        """分段发送长消息"""
        text = msg.text
        chunks = self._split_message(text, self.config.get("max_length", 3500))
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i+1}/{len(chunks)}]\n{chunk}"
            await self.app.bot.send_message(
                chat_id=msg.chat_id,
                text=chunk,
                parse_mode=msg.parse_mode,
            )

    def _split_message(self, text: str, max_len: int) -> list[str]:
        """智能分割：优先在代码块边界或换行处切"""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # 优先在代码块结束处切
            cut = text.rfind("```\n", 0, max_len)
            if cut > max_len * 0.5:
                cut += 4  # 包含 ```\n
            else:
                # 其次在双换行处切
                cut = text.rfind("\n\n", 0, max_len)
            if cut == -1 or cut < max_len * 0.3:
                # 最后在单换行处切
                cut = text.rfind("\n", 0, max_len)
            if cut == -1:
                cut = max_len

            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")

        return chunks
```

```python
# adapters/feishu_adapter.py（第一阶段主力适配器）
#
# 飞书长连接模式：
# - Bot 通过 WebSocket 主动连接飞书服务器
# - 本地开发环境直接运行即可，无需公网 IP / 域名 / 内网穿透
# - SDK 内置鉴权和加密，无需手动处理
#
import json
import threading
import asyncio
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

class FeishuAdapter(BotAdapter):
    def __init__(self, config, message_handler):
        self.config = config
        self.message_handler = message_handler  # core.router 的回调
        self.loop = None  # 主事件循环引用

        # 创建 API Client（用于发送消息）
        self.client = lark.Client.builder() \
            .app_id(config["app_id"]) \
            .app_secret(config["app_secret"]) \
            .log_level(lark.LogLevel.DEBUG) \
            .build()

        # 创建事件处理器
        # 长连接模式下两个参数填空字符串
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_message_sync) \
            .build()

        # 创建 WebSocket 长连接客户端
        self.ws_client = lark.ws.Client(
            config["app_id"],
            config["app_secret"],
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
        )

    async def start(self):
        """启动 WebSocket 长连接（在后台线程运行）"""
        self.loop = asyncio.get_event_loop()
        # ws_client.start() 是阻塞的，需要放在线程里
        thread = threading.Thread(target=self.ws_client.start, daemon=True)
        thread.start()
        print("✅ 飞书 Bot 已启动 (WebSocket 长连接模式)")

    def _on_message_sync(self, data: P2ImMessageReceiveV1) -> None:
        """
        飞书事件回调（同步函数，在 SDK 线程中执行）。

        重要：飞书要求 3 秒内确认消息，
        所以这里只做消息提取，实际处理放到异步任务中。
        """
        event = data.event
        message = event.message

        # 只处理文本消息
        if message.message_type != "text":
            return

        # 提取发送者信息
        sender_id = event.sender.sender_id.open_id

        # 白名单检查
        if sender_id not in self.config["allowed_users"]:
            return

        # 解析消息文本
        content = json.loads(message.content)
        text = content.get("text", "").strip()
        if not text:
            return

        # 构建统一消息格式
        msg = IncomingMessage(
            platform="feishu",
            user_id=sender_id,
            chat_id=message.chat_id,
            text=text,
            reply_to_msg_id=message.message_id,
        )

        # 在主事件循环中异步执行消息处理
        # （因为当前在 SDK 的同步回调线程中）
        asyncio.run_coroutine_threadsafe(
            self.message_handler(msg, self),
            self.loop,
        )

    async def send_message(self, msg: OutgoingMessage):
        """发送文本消息到飞书"""
        text = msg.text
        # 飞书单条消息无硬性字符限制，但太长影响阅读，仍然分段
        chunks = self._split_message(text, max_len=4000)

        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i+1}/{len(chunks)}]\n{chunk}"

            # 构造飞书消息体
            content = json.dumps({"text": chunk})

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("text")
                    .content(content)
                    .build()
                ).build()

            response = self.client.im.v1.message.create(request)
            if not response.success():
                print(f"❌ 飞书发送失败: {response.code} - {response.msg}")

    async def send_file(self, chat_id: str, filepath: str, caption: str = ""):
        """发送文件到飞书"""
        import os
        filename = os.path.basename(filepath)

        # 先上传文件到飞书
        with open(filepath, "rb") as f:
            upload_request = CreateFileRequest.builder() \
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type("stream")
                    .file_name(filename)
                    .file(f)
                    .build()
                ).build()
            upload_resp = self.client.im.v1.file.create(upload_request)

            if not upload_resp.success():
                print(f"❌ 文件上传失败: {upload_resp.msg}")
                return

        # 然后发送文件消息
        file_key = upload_resp.data.file_key
        content = json.dumps({"file_key": file_key})

        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("file")
                .content(content)
                .build()
            ).build()

        self.client.im.v1.message.create(request)

        if caption:
            await self.send_message(OutgoingMessage(chat_id=chat_id, text=caption))

    async def send_typing_action(self, chat_id: str):
        """飞书没有原生的 typing 状态，用一条提示代替"""
        # 可选：不发，或者发一条会被后续消息覆盖的提示
        pass

    def _split_message(self, text: str, max_len: int) -> list[str]:
        """智能分割（与 Telegram 共用逻辑，后续抽到 base 里）"""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            cut = text.rfind("```\n", 0, max_len)
            if cut > max_len * 0.5:
                cut += 4
            else:
                cut = text.rfind("\n\n", 0, max_len)
            if cut == -1 or cut < max_len * 0.3:
                cut = text.rfind("\n", 0, max_len)
            if cut == -1:
                cut = max_len
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks
```

### 4.2 命令路由 (`core/router.py`)

**设计目标**：区分元命令（控制 Bot 自身行为）和 Claude Code 指令。

```python
# core/router.py

# 元命令前缀用 /，普通文本直接发给 Claude Code
META_COMMANDS = {
    # ---- 项目管理 ----
    "/projects":    "列出所有注册项目",
    "/cd":          "切换到已有项目 (/cd <name>)",
    "/addproject":  "注册已有目录为项目 (/addproject <name> <path> [description])",
    "/newproject":  "从零新建项目 (/newproject <name> [description])",
    "/rmproject":   "取消项目注册 (/rmproject <name>)",
    "/initproject": "初始化当前项目 (git init + CLAUDE.md)",

    # ---- 会话管理 ----
    "/status":   "当前状态（项目、会话、模型）",
    "/new":      "开始新会话（清除 continue 状态）",
    "/model":    "切换模型 (sonnet/opus)",
    "/abort":    "终止当前执行",
    "/help":     "显示帮助",

    # ---- 输出查看 ----
    "/detail":   "查看上次完整输出",
    "/log":      "查看最近 N 条操作记录",
    "/memory":   "查看/搜索项目记忆",
    "/archive":  "搜索归档历史记录",

    # ---- 文件管理 ----
    "/cat":      "查看文件内容 (/cat path [start-end])",
    "/tree":     "查看目录结构 (/tree [path] [depth])",
    "/dl":       "下载文件到手机 (/dl path)",
    "/upload":   "上传手机文件到项目 (回复文件消息 + /upload [target_path])",

    # ---- Git 操作 ----
    "/diff":     "查看 git diff (/diff [ref])",
    "/commit":   "提交变更 (/commit [-m message])",
    "/push":     "推送到远程 (/push [branch])",
    "/pull":     "拉取远程更新",
    "/pr":       "创建 Pull Request (/pr [title])",
    "/branch":   "查看/切换分支 (/branch [name])",
    "/stash":    "暂存当前修改 (/stash [pop])",
    "/rollback": "回滚上次操作 (/rollback [commit_count])",
    "/gitlog":   "查看 git log (/gitlog [n])",
}

class Router:
    def __init__(self, executor, session_mgr, memory_store, git_ops, file_mgr, project_mgr):
        self.executor = executor
        self.session_mgr = session_mgr
        self.memory = memory_store
        self.git = git_ops
        self.files = file_mgr
        self.projects = project_mgr
        self._last_full_output = {}  # chat_id -> str

    async def handle(self, msg: IncomingMessage, adapter: BotAdapter):
        text = msg.text.strip()

        # ---- 元命令 ----
        if text.startswith("/"):
            cmd_parts = text.split(maxsplit=1)
            cmd = cmd_parts[0].lower()
            arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

            handlers = {
                # 项目管理
                "/projects":    lambda: self._handle_projects(msg, adapter),
                "/cd":          lambda: self._handle_cd(msg, adapter, arg),
                "/addproject":  lambda: self._handle_addproject(msg, adapter, arg),
                "/newproject":  lambda: self._handle_newproject(msg, adapter, arg),
                "/rmproject":   lambda: self._handle_rmproject(msg, adapter, arg),
                "/initproject": lambda: self._handle_initproject(msg, adapter),
                # 会话管理
                "/status":   lambda: self._handle_status(msg, adapter),
                "/new":      lambda: self._handle_new_session(msg, adapter),
                "/model":    lambda: self._handle_model(msg, adapter, arg),
                "/abort":    lambda: self._handle_abort(msg, adapter),
                "/help":     lambda: self._handle_help(msg, adapter),
                # 输出查看
                "/detail":   lambda: self._handle_detail(msg, adapter),
                "/log":      lambda: self._handle_log(msg, adapter, arg),
                "/memory":   lambda: self._handle_memory(msg, adapter, arg),
                "/archive":  lambda: self._handle_archive(msg, adapter, arg),
                # 文件管理
                "/cat":      lambda: self._handle_cat(msg, adapter, arg),
                "/tree":     lambda: self._handle_tree(msg, adapter, arg),
                "/dl":       lambda: self._handle_download(msg, adapter, arg),
                "/upload":   lambda: self._handle_upload(msg, adapter, arg),
                # Git 操作
                "/diff":     lambda: self._handle_diff(msg, adapter, arg),
                "/commit":   lambda: self._handle_commit(msg, adapter, arg),
                "/push":     lambda: self._handle_push(msg, adapter, arg),
                "/pull":     lambda: self._handle_pull(msg, adapter),
                "/pr":       lambda: self._handle_pr(msg, adapter, arg),
                "/branch":   lambda: self._handle_branch(msg, adapter, arg),
                "/stash":    lambda: self._handle_stash(msg, adapter, arg),
                "/rollback": lambda: self._handle_rollback(msg, adapter, arg),
                "/gitlog":   lambda: self._handle_gitlog(msg, adapter, arg),
            }

            handler = handlers.get(cmd)
            if handler:
                return await handler()
            return await adapter.send_message(OutgoingMessage(
                chat_id=msg.chat_id,
                text=f"未知命令: {cmd}\n输入 /help 查看可用命令"
            ))

        # ---- Claude Code 指令 ----
        await self._execute_claude(msg, adapter, text)

    async def _execute_claude(self, msg, adapter, user_text):
        """核心流程：注入记忆 → 调用 Claude Code → 处理输出 → 保存记忆"""
        chat_id = msg.chat_id
        session = self.session_mgr.get_session(chat_id)
        project = session.current_project

        # 1. 发送"执行中"状态
        await adapter.send_typing_action(chat_id)
        await adapter.send_message(OutgoingMessage(
            chat_id=chat_id,
            text=f"⏳ 执行中... [{project.name}]"
        ))

        # 2. 注入记忆上下文
        memory_context = self.memory.build_context(project.name)
        augmented_prompt = self._build_prompt(memory_context, user_text)

        # 3. 调用 Claude Code
        result = await self.executor.run(
            prompt=augmented_prompt,
            cwd=project.path,
            session_id=session.claude_session_id,  # 用于 --resume
            use_continue=session.has_history,        # 用于 --continue
        )

        # 4. 保存完整输出到本地（供 /detail 调取）
        self._last_full_output[chat_id] = result.full_output

        # 5. 保存记忆
        self.memory.save_entry(
            project=project.name,
            user_msg=user_text,
            result_summary=result.summary,
            files_changed=result.files_changed,
            session_id=result.session_id,
        )

        # 6. 更新会话状态
        session.claude_session_id = result.session_id
        session.has_history = True

        # 7. 发送处理后的输出
        await adapter.send_message(OutgoingMessage(
            chat_id=chat_id,
            text=result.formatted_output,
        ))
```

### 4.3 Claude Code 执行器 (`core/executor.py`)

**设计目标**：封装 CLI 调用，解析结构化输出，处理超时和错误。

```python
# core/executor.py
import asyncio
import json
from dataclasses import dataclass

@dataclass
class ExecutionResult:
    success: bool
    session_id: str
    full_output: str          # 原始完整输出
    summary: str              # 压缩摘要
    formatted_output: str     # 适合手机阅读的格式化输出
    files_changed: list[str]
    cost_usd: float
    duration_ms: int
    error: str = ""

class ClaudeExecutor:
    def __init__(self, config):
        self.config = config
        self.current_process = None  # 用于 /abort

    async def run(
        self,
        prompt: str,
        cwd: str,
        session_id: str = None,
        use_continue: bool = False,
    ) -> ExecutionResult:

        cmd = self._build_command(prompt, session_id, use_continue)

        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                self.current_process.communicate(),
                timeout=self.config["timeout"],
            )

            raw_output = stdout.decode("utf-8")
            return self._parse_output(raw_output, stderr.decode("utf-8"))

        except asyncio.TimeoutError:
            if self.current_process:
                self.current_process.terminate()
            return ExecutionResult(
                success=False,
                session_id=session_id or "",
                full_output="",
                summary="⏰ 执行超时",
                formatted_output="⏰ 执行超时，请拆分为更小的任务或增加超时时间",
                files_changed=[],
                cost_usd=0,
                duration_ms=self.config["timeout"] * 1000,
                error="timeout",
            )
        finally:
            self.current_process = None

    def _build_command(self, prompt, session_id, use_continue) -> list[str]:
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",   # JSON 输出，便于解析
            "--model", self.config["model"],
            "--max-turns", str(self.config["max_turns"]),
        ]

        # 会话续接
        if session_id:
            cmd.extend(["--resume", session_id])
        elif use_continue:
            cmd.append("--continue")

        # 工具权限
        if self.config.get("allowed_tools"):
            cmd.extend([
                "--allowedTools",
                ",".join(self.config["allowed_tools"])
            ])

        return cmd

    def _parse_output(self, stdout: str, stderr: str) -> ExecutionResult:
        """解析 Claude Code 的 JSON 输出"""
        try:
            data = json.loads(stdout)
            result_text = data.get("result", "")
            session_id = data.get("session_id", "")
            cost = data.get("total_cost_usd", 0)
            duration = data.get("duration_ms", 0)

            # 从 result 中提取文件变更信息
            files_changed = self._extract_files_changed(result_text)

            # 生成适合手机的格式化输出
            formatted = self._format_for_mobile(result_text, files_changed, cost, duration)

            return ExecutionResult(
                success=not data.get("is_error", False),
                session_id=session_id,
                full_output=result_text,
                summary=self._generate_summary(result_text),
                formatted_output=formatted,
                files_changed=files_changed,
                cost_usd=cost,
                duration_ms=duration,
            )
        except json.JSONDecodeError:
            # fallback: 非 JSON 输出
            return ExecutionResult(
                success=True,
                session_id="",
                full_output=stdout,
                summary=stdout[:200],
                formatted_output=stdout[:3000],
                files_changed=[],
                cost_usd=0,
                duration_ms=0,
            )

    def _format_for_mobile(self, text, files, cost, duration) -> str:
        """生成手机友好的输出"""
        lines = []

        # 状态栏
        duration_s = duration / 1000
        lines.append(f"✅ 完成 | ⏱ {duration_s:.1f}s | 💰 ${cost:.4f}")

        # 文件变更
        if files:
            lines.append(f"\n📁 变更文件: {len(files)}")
            for f in files[:10]:  # 最多显示 10 个
                lines.append(f"  • {f}")
            if len(files) > 10:
                lines.append(f"  ... 等 {len(files) - 10} 个文件")

        # 主要内容（截断到合理长度）
        lines.append(f"\n{text[:2500]}")
        if len(text) > 2500:
            lines.append("\n... (输入 /detail 查看完整输出)")

        return "\n".join(lines)

    def _extract_files_changed(self, text: str) -> list[str]:
        """从输出中提取被修改的文件路径"""
        files = set()
        # 常见模式: "Created file: xxx", "Modified: xxx", "Wrote to xxx"
        import re
        patterns = [
            r"(?:Created|Modified|Updated|Wrote to|Edited)\s+(?:file\s+)?[`'\"]?([^\s`'\"]+\.\w+)",
            r"Writing to\s+[`'\"]?([^\s`'\"]+\.\w+)",
        ]
        for pat in patterns:
            files.update(re.findall(pat, text))
        return sorted(files)

    def _generate_summary(self, text: str) -> str:
        """生成简短摘要（用于记忆系统）"""
        # 取前 200 字符作为基础摘要
        # 后续可以用 Claude API 做更智能的压缩
        lines = text.strip().split("\n")
        summary_lines = []
        for line in lines:
            if line.strip():
                summary_lines.append(line.strip())
            if len(" ".join(summary_lines)) > 200:
                break
        return " ".join(summary_lines)[:200]

    async def abort(self):
        """终止当前执行"""
        if self.current_process:
            self.current_process.terminate()
            return True
        return False
```

### 4.4 会话管理器 (`core/session_manager.py`)

```python
# core/session_manager.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ProjectInfo:
    name: str
    path: str
    description: str = ""

@dataclass
class Session:
    chat_id: str
    current_project: ProjectInfo
    claude_session_id: Optional[str] = None
    has_history: bool = False
    model: str = "claude-sonnet-4-20250514"

class SessionManager:
    """管理每个 chat 的会话状态"""

    def __init__(self, config):
        self.config = config
        self.sessions: dict[str, Session] = {}
        self.projects = self._load_projects(config["projects"])

    def _load_projects(self, proj_config) -> dict[str, ProjectInfo]:
        projects = {}
        for name, info in proj_config["list"].items():
            projects[name] = ProjectInfo(
                name=name,
                path=info["path"],
                description=info.get("description", ""),
            )
        return projects

    def get_session(self, chat_id: str) -> Session:
        if chat_id not in self.sessions:
            default_proj = self.config["projects"]["default"]
            self.sessions[chat_id] = Session(
                chat_id=chat_id,
                current_project=self.projects[default_proj],
            )
        return self.sessions[chat_id]

    def switch_project(self, chat_id: str, project_name: str) -> bool:
        if project_name not in self.projects:
            return False
        session = self.get_session(chat_id)
        session.current_project = self.projects[project_name]
        session.claude_session_id = None  # 切换项目时重置会话
        session.has_history = False
        return True

    def new_session(self, chat_id: str):
        """开始新的 Claude Code 会话（同项目）"""
        session = self.get_session(chat_id)
        session.claude_session_id = None
        session.has_history = False
```

### 4.5 记忆系统 (`memory/`)

**这是整个系统最关键的模块。** 分为四个子模块：

#### 4.5.1 存储引擎 (`memory/store.py`)

```python
# memory/store.py
import sqlite3
import json
from datetime import datetime

class MemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_msg TEXT NOT NULL,
                summary TEXT NOT NULL,
                files_changed TEXT DEFAULT '[]',
                session_id TEXT DEFAULT '',
                is_compressed INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compressed_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                summary TEXT NOT NULL,
                covers_from TEXT NOT NULL,
                covers_to TEXT NOT NULL,
                entry_count INTEGER NOT NULL,
                archive_path TEXT DEFAULT ''
            )
        """)
        # 全文搜索索引
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(user_msg, summary, content=memories, content_rowid=id)
        """)
        conn.commit()
        conn.close()

    def save_entry(self, project, user_msg, result_summary, files_changed, session_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO memories
               (project, timestamp, user_msg, summary, files_changed, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                project,
                datetime.now().isoformat(),
                user_msg,
                result_summary,
                json.dumps(files_changed),
                session_id,
            )
        )
        # 同步更新 FTS 索引
        conn.execute(
            """INSERT INTO memories_fts(rowid, user_msg, summary)
               VALUES (last_insert_rowid(), ?, ?)""",
            (user_msg, result_summary)
        )
        conn.commit()
        conn.close()

    def get_recent(self, project: str, n: int = 15) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT timestamp, user_msg, summary, files_changed
               FROM memories WHERE project = ?
               ORDER BY id DESC LIMIT ?""",
            (project, n)
        ).fetchall()
        conn.close()
        return [
            {
                "time": r[0],
                "task": r[1],
                "summary": r[2],
                "files": json.loads(r[3]),
            }
            for r in reversed(rows)  # 按时间正序返回
        ]

    def search(self, query: str, project: str = None, limit: int = 10) -> list[dict]:
        """全文搜索记忆"""
        conn = sqlite3.connect(self.db_path)
        sql = """
            SELECT m.timestamp, m.user_msg, m.summary, m.project
            FROM memories_fts fts
            JOIN memories m ON fts.rowid = m.id
            WHERE fts MATCH ?
        """
        params = [query]
        if project:
            sql += " AND m.project = ?"
            params.append(project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {"time": r[0], "task": r[1], "summary": r[2], "project": r[3]}
            for r in rows
        ]

    def get_compressed_summary(self, project: str) -> str:
        """获取项目的压缩历史摘要"""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT summary FROM compressed_summaries
               WHERE project = ? ORDER BY id DESC LIMIT 1""",
            (project,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""

    def count_entries(self, project: str) -> int:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE project = ? AND is_compressed = 0",
            (project,)
        ).fetchone()
        conn.close()
        return row[0]
```

#### 4.5.2 记忆压缩 (`memory/compressor.py`)

```python
# memory/compressor.py
import asyncio

class MemoryCompressor:
    """
    记忆分层压缩策略：

    层级结构：
    ┌─────────────────────────────────────────┐
    │  L0: 压缩摘要（长期记忆）               │  ← 整个项目历史的精华
    │      "项目使用 Next.js + PostgreSQL,    │
    │       已完成用户认证模块..."             │
    ├─────────────────────────────────────────┤
    │  L1: 最近 15 条详细记录（短期记忆）      │  ← 具体的操作日志
    │      [2025-02-08] 修复了登录页面 bug    │
    │      [2025-02-09] 添加了 API rate limit │
    ├─────────────────────────────────────────┤
    │  L2: JSONL 归档（冷存储）               │  ← 压缩前的原始记录完整保留
    │      archives/my-webapp_2025_02.jsonl   │     永久可追溯，支持搜索
    └─────────────────────────────────────────┘

    触发条件：未压缩记录超过 compress_threshold 时
    流程：归档原始记录 → 生成压缩摘要 → 标记已压缩
    """

    def __init__(self, memory_store, executor, archiver, config):
        self.store = memory_store
        self.executor = executor
        self.archiver = archiver
        self.threshold = config.get("compress_threshold", 50)

    async def maybe_compress(self, project: str):
        """检查是否需要压缩，如果需要则执行"""
        count = self.store.count_entries(project)
        if count <= self.threshold:
            return

        # 获取旧记录（保留最近 15 条不压缩）
        all_entries = self.store.get_recent(project, n=count)
        old_entries = all_entries[:-15]

        # ★ 先归档原始记录到 JSONL 冷存储
        archive_path = self.archiver.archive_entries(project, old_entries)

        # 获取已有的压缩摘要
        existing_summary = self.store.get_compressed_summary(project)

        # 让 Claude 压缩
        prompt = self._build_compress_prompt(existing_summary, old_entries)
        result = await self.executor.run(
            prompt=prompt,
            cwd="/tmp",  # 压缩任务不需要项目目录
            use_continue=False,
        )

        # 保存新的压缩摘要（记录归档文件路径供溯源）
        self.store.save_compressed_summary(
            project=project,
            summary=result.full_output,
            covers_from=old_entries[0]["time"],
            covers_to=old_entries[-1]["time"],
            entry_count=len(old_entries),
            archive_path=archive_path,
        )

        # 标记旧记录为已压缩（活跃 DB 中保留元数据，详情在归档里）
        self.store.mark_compressed(project, len(old_entries))

    def _build_compress_prompt(self, existing_summary, entries) -> str:
        entries_text = "\n".join([
            f"[{e['time'][:10]}] 任务: {e['task']} | 结果: {e['summary']}"
            for e in entries
        ])

        return f"""你是一个项目记忆管理系统。请将以下工作记录压缩成一份简洁的项目状态摘要。

要求：
1. 保留关键架构决策和技术选型
2. 保留未完成事项和已知问题
3. 保留重要的文件结构和模块关系
4. 删除具体的调试细节和重复操作
5. 用中文输出，简洁专业

{"已有摘要（请在此基础上更新）：" + chr(10) + existing_summary if existing_summary else "这是第一次压缩。"}

新增工作记录：
{entries_text}

请输出更新后的项目状态摘要（控制在 500 字以内）："""
```

#### 4.5.3 上下文注入 (`memory/injector.py`)

```python
# memory/injector.py

class ContextInjector:
    """
    将记忆注入到发给 Claude Code 的 prompt 中。

    注入结构：
    ┌──────────────────────────────────┐
    │  [系统上下文]                     │
    │  项目历史摘要（压缩后的长期记忆） │
    │  最近 15 条操作记录              │
    │                                  │
    │  [用户当前指令]                   │
    │  用户输入的具体任务               │
    └──────────────────────────────────┘
    """

    def __init__(self, memory_store, config):
        self.store = memory_store
        self.max_tokens = config.get("max_context_tokens", 4000)
        self.recent_n = config.get("recent_entries", 15)

    def build_augmented_prompt(self, project: str, user_message: str) -> str:
        # 获取压缩摘要
        compressed = self.store.get_compressed_summary(project)

        # 获取最近记录
        recent = self.store.get_recent(project, n=self.recent_n)

        # 构建上下文
        context_parts = []

        if compressed:
            context_parts.append(
                f"## 项目历史摘要\n{compressed}"
            )

        if recent:
            recent_text = "\n".join([
                f"- [{e['time'][:16]}] {e['task'][:80]} → {e['summary'][:100]}"
                for e in recent
            ])
            context_parts.append(
                f"## 近期工作记录（最近 {len(recent)} 条）\n{recent_text}"
            )

        if context_parts:
            context = "\n\n".join(context_parts)
            # Token 估算（粗略：1 中文字 ≈ 2 tokens）
            estimated_tokens = len(context) * 2
            if estimated_tokens > self.max_tokens:
                context = self._truncate_to_budget(context)

            return f"""{context}

---

## 当前任务
{user_message}

请基于上面的项目背景执行当前任务。如果近期记录中有相关上下文，请参考。"""

        return user_message

    def _truncate_to_budget(self, context: str) -> str:
        """超出 token 预算时，优先保留压缩摘要，裁剪近期记录"""
        max_chars = self.max_tokens // 2  # 粗略估算
        if len(context) <= max_chars:
            return context
        return context[:max_chars] + "\n... (部分历史记录已截断)"
```

#### 4.5.4 CLAUDE.md 自动维护 (`memory/claude_md_sync.py`)

```python
# memory/claude_md_sync.py
import os

class ClaudeMdSync:
    """
    自动维护项目 CLAUDE.md 文件。

    Claude Code 每次启动都会读取项目根目录的 CLAUDE.md，
    这是最自然的"长期记忆"注入点。

    策略：
    - 保留用户手写的部分（标记区分）
    - 自动更新"项目状态"和"近期变更"部分
    - 定期（每 10 次操作）触发更新
    """

    MANAGED_HEADER = "<!-- AUTO-MANAGED BY REMOTE BOT - DO NOT EDIT BELOW -->"
    MANAGED_FOOTER = "<!-- END AUTO-MANAGED SECTION -->"

    def __init__(self, memory_store):
        self.store = memory_store
        self.update_interval = 10  # 每 N 次操作更新一次
        self._counters = {}  # project -> count

    async def maybe_update(self, project_name: str, project_path: str):
        """每 N 次操作自动更新 CLAUDE.md"""
        self._counters[project_name] = self._counters.get(project_name, 0) + 1
        if self._counters[project_name] % self.update_interval != 0:
            return

        await self._update_claude_md(project_name, project_path)

    async def _update_claude_md(self, project_name: str, project_path: str):
        md_path = os.path.join(project_path, "CLAUDE.md")

        # 读取现有内容（保留用户手写部分）
        user_content = ""
        if os.path.exists(md_path):
            with open(md_path, "r") as f:
                content = f.read()
            if self.MANAGED_HEADER in content:
                user_content = content[:content.index(self.MANAGED_HEADER)].rstrip()
            else:
                user_content = content.rstrip()

        # 构建自动管理部分
        compressed = self.store.get_compressed_summary(project_name)
        recent = self.store.get_recent(project_name, n=10)

        managed_parts = [self.MANAGED_HEADER, ""]

        if compressed:
            managed_parts.append(f"## Project Status Summary\n\n{compressed}")

        if recent:
            managed_parts.append("\n## Recent Changes\n")
            for e in recent[-10:]:
                managed_parts.append(
                    f"- [{e['time'][:10]}] {e['task'][:60]}"
                )

        managed_parts.append(f"\n{self.MANAGED_FOOTER}")

        # 写入
        final_content = user_content + "\n\n" + "\n".join(managed_parts) + "\n"
        with open(md_path, "w") as f:
            f.write(final_content)
```

#### 4.5.5 记忆归档 (`memory/archiver.py`)

**设计目标**：压缩记忆时，原始记录不丢弃，而是归档到 JSONL 冷存储。活跃 DB 保持轻量，完整历史随时可追溯。

```
记忆生命周期：

  新记录写入 ──▶ memories 表（活跃）
                    │
              超过阈值触发压缩
                    │
              ┌─────┴──────┐
              ▼            ▼
     compressed_summaries   archives/{project}_{date}.jsonl
      (压缩后的摘要)          (原始记录冷存储，永久保留)
                    │
              活跃表标记 is_compressed = 1
              后续定期清理已归档的行（可选）
```

```python
# memory/archiver.py
import json
import os
from datetime import datetime

class MemoryArchiver:
    """
    将被压缩的记忆原始记录归档到 JSONL 文件。

    归档文件按 {project}_{year}_{month}.jsonl 组织，
    每行一条完整的原始记录，包含所有字段。

    归档文件只追加不修改，可以安全地用于：
    - 事后审计（某天做了什么具体操作）
    - 记忆恢复（压缩摘要不够用时回溯原始记录）
    - 全文搜索（归档文件也可以被搜索）
    - 数据导出（给其他工具或团队使用）
    """

    def __init__(self, config):
        self.archive_dir = config.get("archive", {}).get("path", "./data/archives")
        self.enabled = config.get("archive", {}).get("enabled", True)
        self.retention_days = config.get("archive", {}).get("retention_days", 365)
        os.makedirs(self.archive_dir, exist_ok=True)

    def archive_entries(self, project: str, entries: list[dict]) -> str:
        """
        将一批记忆条目归档到 JSONL 文件。
        返回归档文件路径。
        """
        if not self.enabled or not entries:
            return ""

        # 按年月组织文件
        now = datetime.now()
        filename = f"{project}_{now.strftime('%Y_%m')}.jsonl"
        filepath = os.path.join(self.archive_dir, filename)

        with open(filepath, "a", encoding="utf-8") as f:
            archive_header = {
                "_type": "archive_batch",
                "_archived_at": now.isoformat(),
                "_project": project,
                "_entry_count": len(entries),
            }
            f.write(json.dumps(archive_header, ensure_ascii=False) + "\n")

            for entry in entries:
                record = {
                    "_type": "memory_entry",
                    "timestamp": entry.get("time", ""),
                    "user_msg": entry.get("task", ""),
                    "summary": entry.get("summary", ""),
                    "files_changed": entry.get("files", []),
                    "session_id": entry.get("session_id", ""),
                    "full_output": entry.get("full_output", ""),  # 如果有的话
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return filepath

    def search_archives(self, project: str, query: str, limit: int = 20) -> list[dict]:
        """
        在归档文件中搜索关键词。
        朴素的全文扫描，适合低频使用。
        """
        results = []
        query_lower = query.lower()

        # 扫描该项目的所有归档文件
        for filename in sorted(os.listdir(self.archive_dir), reverse=True):
            if not filename.startswith(project + "_"):
                continue
            filepath = os.path.join(self.archive_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if record.get("_type") != "memory_entry":
                            continue
                        # 在 user_msg 和 summary 中搜索
                        text = (record.get("user_msg", "") + " " + record.get("summary", "")).lower()
                        if query_lower in text:
                            results.append(record)
                            if len(results) >= limit:
                                return results
                    except json.JSONDecodeError:
                        continue

        return results

    def get_archive_stats(self, project: str = None) -> dict:
        """获取归档统计信息"""
        stats = {"total_files": 0, "total_size_mb": 0, "projects": {}}

        for filename in os.listdir(self.archive_dir):
            if not filename.endswith(".jsonl"):
                continue
            if project and not filename.startswith(project + "_"):
                continue

            filepath = os.path.join(self.archive_dir, filename)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            proj_name = filename.rsplit("_", 2)[0]

            stats["total_files"] += 1
            stats["total_size_mb"] += size_mb

            if proj_name not in stats["projects"]:
                stats["projects"][proj_name] = {"files": 0, "size_mb": 0}
            stats["projects"][proj_name]["files"] += 1
            stats["projects"][proj_name]["size_mb"] += size_mb

        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        return stats

    def cleanup_old_archives(self):
        """清理超过 retention_days 的归档文件"""
        if self.retention_days <= 0:  # 0 = 永久保留
            return

        cutoff = datetime.now().timestamp() - (self.retention_days * 86400)
        for filename in os.listdir(self.archive_dir):
            filepath = os.path.join(self.archive_dir, filename)
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
```

### 4.6 文件管理器 (`core/file_manager.py`)

**设计目标**：在手机上查看代码文件、目录结构，以及双向传输文件。

```python
# core/file_manager.py
import os
import asyncio

class FileManager:
    def __init__(self, config):
        self.max_cat_lines = config.get("max_cat_lines", 200)
        self.max_file_size = config.get("max_file_size_mb", 10) * 1024 * 1024
        self.allowed_ext = config.get("allowed_download_ext", [])

    async def cat_file(self, project_path: str, file_arg: str) -> str:
        """
        查看文件内容。

        用法:
          /cat src/app/page.tsx          → 完整文件（限制行数）
          /cat src/app/page.tsx 20-50    → 第 20-50 行
          /cat src/app/page.tsx 100      → 从第 100 行开始
        """
        parts = file_arg.strip().split()
        filepath = parts[0]
        line_range = parts[1] if len(parts) > 1 else None

        full_path = os.path.join(project_path, filepath)

        if not os.path.isfile(full_path):
            return f"❌ 文件不存在: {filepath}"

        if not self._is_within_project(project_path, full_path):
            return "❌ 禁止访问项目目录外的文件"

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)

        # 解析行范围
        if line_range:
            if "-" in line_range:
                start, end = line_range.split("-", 1)
                start = max(1, int(start))
                end = min(total_lines, int(end))
            else:
                start = max(1, int(line_range))
                end = min(total_lines, start + self.max_cat_lines - 1)
        else:
            start = 1
            end = min(total_lines, self.max_cat_lines)

        selected = lines[start - 1 : end]

        # 格式化输出：带行号
        header = f"📄 {filepath} ({total_lines} lines, showing {start}-{end})\n"
        content = ""
        for i, line in enumerate(selected, start=start):
            content += f"{i:4d} │ {line}"

        if end < total_lines:
            content += f"\n... 还有 {total_lines - end} 行 (/cat {filepath} {end + 1})"

        return header + f"```\n{content}\n```"

    async def tree(self, project_path: str, arg: str) -> str:
        """
        查看目录结构。

        用法:
          /tree                  → 项目根目录，深度 2
          /tree src/app          → 指定子目录
          /tree src/app 4        → 指定深度
        """
        parts = arg.strip().split() if arg.strip() else []
        subpath = parts[0] if parts else "."
        depth = int(parts[1]) if len(parts) > 1 else 2

        target = os.path.join(project_path, subpath)
        if not os.path.isdir(target):
            return f"❌ 目录不存在: {subpath}"

        # 用系统 tree 命令（更快更准）
        proc = await asyncio.create_subprocess_exec(
            "tree", "-L", str(depth), "--charset=utf-8",
            "-I", "node_modules|.git|__pycache__|.next|venv|dist",
            target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8")

        # 如果太长，截断
        lines = output.split("\n")
        if len(lines) > 80:
            output = "\n".join(lines[:80]) + f"\n... 共 {len(lines)} 行"

        return f"📁 {subpath}/\n```\n{output}\n```"

    async def prepare_download(self, project_path: str, filepath: str) -> str | None:
        """
        准备文件下载，返回完整文件路径。
        返回 None 表示不允许下载。
        """
        full_path = os.path.join(project_path, filepath)

        if not os.path.isfile(full_path):
            return None

        if not self._is_within_project(project_path, full_path):
            return None

        # 检查文件大小
        if os.path.getsize(full_path) > self.max_file_size:
            return None

        return full_path

    async def save_upload(self, project_path: str, source_path: str, target_rel: str) -> str:
        """
        保存上传的文件到项目目录。
        返回保存后的相对路径。
        """
        target_path = os.path.join(project_path, target_rel)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        import shutil
        shutil.copy2(source_path, target_path)
        return target_rel

    def _is_within_project(self, project_path: str, target: str) -> bool:
        """安全检查：确保路径不会逃逸出项目目录"""
        real_project = os.path.realpath(project_path)
        real_target = os.path.realpath(target)
        return real_target.startswith(real_project)
```

### 4.7 Git 操作 (`core/git_ops.py`)

**设计目标**：封装常用 Git 操作，带安全保护（保护分支、危险操作确认）。

```python
# core/git_ops.py
import asyncio

class GitOps:
    def __init__(self, config):
        self.config = config
        self.commit_prefix = config.get("commit_prefix", "[bot]")
        self.protected_branches = config.get("protected_branches", ["main", "production"])

    async def _run_git(self, cwd: str, *args) -> tuple[str, str, int]:
        """执行 git 命令并返回 (stdout, stderr, returncode)"""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode("utf-8"), stderr.decode("utf-8"), proc.returncode

    async def diff(self, cwd: str, ref: str = "") -> str:
        """git diff，可选指定 ref"""
        args = ["diff", "--stat"]  # 先显示文件统计
        if ref:
            args.append(ref)

        stat_out, _, _ = await self._run_git(cwd, *args)

        # 再获取详细 diff（限制长度）
        args_full = ["diff"]
        if ref:
            args_full.append(ref)

        diff_out, _, _ = await self._run_git(cwd, *args_full)

        # 截断过长的 diff
        if len(diff_out) > 3000:
            diff_out = diff_out[:3000] + "\n... (diff 过长，已截断。用 /dl 下载完整 patch)"

        if not stat_out.strip() and not diff_out.strip():
            return "✨ 没有未提交的变更"

        return f"📊 变更统计:\n```\n{stat_out}```\n\n详细 diff:\n```diff\n{diff_out}\n```"

    async def commit(self, cwd: str, message: str = "") -> str:
        """git add + commit"""
        # 先 add 所有变更
        await self._run_git(cwd, "add", "-A")

        # 检查是否有东西可以提交
        status_out, _, _ = await self._run_git(cwd, "status", "--porcelain")
        if not status_out.strip():
            return "✨ 没有需要提交的变更"

        # 生成 commit message
        if not message:
            # 用 git diff --cached 的 stat 生成一个描述性的 message
            stat_out, _, _ = await self._run_git(cwd, "diff", "--cached", "--stat")
            message = f"Update: {stat_out.strip().split(chr(10))[-1]}"

        full_message = f"{self.commit_prefix} {message}"

        out, err, code = await self._run_git(cwd, "commit", "-m", full_message)
        if code != 0:
            return f"❌ Commit 失败:\n```\n{err}\n```"

        return f"✅ 已提交\n```\n{out}\n```"

    async def push(self, cwd: str, branch: str = "") -> str:
        """git push"""
        if not branch:
            # 获取当前分支
            out, _, _ = await self._run_git(cwd, "branch", "--show-current")
            branch = out.strip()

        # 保护分支检查
        if branch in self.protected_branches:
            return (
                f"⚠️ `{branch}` 是保护分支，禁止直接 push。\n"
                f"请使用 /pr 创建 Pull Request，或先切换到开发分支。"
            )

        out, err, code = await self._run_git(cwd, "push", "origin", branch)
        if code != 0:
            return f"❌ Push 失败:\n```\n{err}\n```"
        return f"✅ 已推送到 origin/{branch}"

    async def pull(self, cwd: str) -> str:
        """git pull"""
        out, err, code = await self._run_git(cwd, "pull")
        if code != 0:
            return f"❌ Pull 失败:\n```\n{err}\n```"
        return f"✅ Pull 完成\n```\n{out}\n```"

    async def create_pr(self, cwd: str, title: str = "") -> str:
        """
        用 GitHub CLI 创建 PR。
        需要预先安装 gh 并认证。
        """
        # 获取当前分支
        branch_out, _, _ = await self._run_git(cwd, "branch", "--show-current")
        branch = branch_out.strip()

        if branch in self.protected_branches:
            return f"❌ 当前在保护分支 `{branch}` 上，请先切换到开发分支"

        if not title:
            # 用最近一次 commit message 作为 PR 标题
            log_out, _, _ = await self._run_git(cwd, "log", "-1", "--format=%s")
            title = log_out.strip()

        # 先 push
        await self._run_git(cwd, "push", "-u", "origin", branch)

        # 创建 PR
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "create",
            "--title", title,
            "--body", f"Created via Claude Code Remote Bot from branch `{branch}`",
            "--head", branch,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        out, err = await proc.communicate()

        if proc.returncode != 0:
            return f"❌ PR 创建失败:\n```\n{err.decode()}\n```\n\n确保已安装 `gh` 并完成认证"

        pr_url = out.decode().strip()
        return f"✅ PR 已创建\n🔗 {pr_url}"

    async def branch(self, cwd: str, name: str = "") -> str:
        """查看或切换分支"""
        if not name:
            out, _, _ = await self._run_git(cwd, "branch", "-a", "--format=%(refname:short) %(HEAD)")
            return f"📌 分支列表:\n```\n{out}\n```"

        out, err, code = await self._run_git(cwd, "checkout", name)
        if code != 0:
            # 尝试创建新分支
            out, err, code = await self._run_git(cwd, "checkout", "-b", name)
            if code != 0:
                return f"❌ 切换分支失败:\n```\n{err}\n```"
            return f"✅ 已创建并切换到新分支: `{name}`"
        return f"✅ 已切换到分支: `{name}`"

    async def stash(self, cwd: str, arg: str = "") -> str:
        """暂存/恢复修改"""
        if arg.strip() == "pop":
            out, err, code = await self._run_git(cwd, "stash", "pop")
        elif arg.strip() == "list":
            out, err, code = await self._run_git(cwd, "stash", "list")
        else:
            out, err, code = await self._run_git(cwd, "stash", "push", "-m",
                                                   arg or "Stashed via bot")
        if code != 0:
            return f"❌ Stash 操作失败:\n```\n{err}\n```"
        return f"✅ {out}" if out.strip() else "✅ 完成"

    async def rollback(self, cwd: str, arg: str = "") -> str:
        """
        回滚操作。
        /rollback      → 回滚最后一次 commit（保留文件变更）
        /rollback 3    → 回滚最后 3 次 commit
        /rollback hard → 彻底回滚（丢弃文件变更）⚠️
        """
        if arg.strip() == "hard":
            out, err, code = await self._run_git(cwd, "reset", "--hard", "HEAD~1")
            prefix = "⚠️ 已硬回滚（变更已丢弃）"
        else:
            count = int(arg) if arg.strip().isdigit() else 1
            out, err, code = await self._run_git(cwd, "reset", "--soft", f"HEAD~{count}")
            prefix = f"✅ 已软回滚 {count} 个 commit（文件变更保留在暂存区）"

        if code != 0:
            return f"❌ 回滚失败:\n```\n{err}\n```"
        return prefix

    async def log(self, cwd: str, n: str = "10") -> str:
        """git log"""
        count = int(n) if n.strip().isdigit() else 10
        out, _, _ = await self._run_git(
            cwd, "log", f"-{count}",
            "--format=%h %s (%cr)", "--no-decorate"
        )
        return f"📜 最近 {count} 条 commit:\n```\n{out}\n```"
```

### 4.8 Git 工作流设计

**核心原则**：手机上做决策，不做审查。

```
推荐工作流（Feature Branch 模式）：

  /branch feat/remember-me         ← 创建并切到功能分支
  给登录页加一个记住密码功能         ← Claude Code 编码
  把测试也补上                      ← 继续编码
  /diff                            ← 快速确认变更范围
  /commit -m "add remember me"     ← 提交
  /push                            ← 推送
  /pr 添加记住密码功能              ← 创建 PR

  （回到电脑后在 GitHub 上详细审查 PR）

安全工作流（需要审查再合并）：

  Claude Code 编码 → /diff 看摘要 → /commit → /push 到功能分支
  → GitHub PR → CI 自动跑测试 → 测试结果推送到 Telegram
  → 手机上看到 "✅ 通过" → 回到电脑 merge
  → 或者直接手机上 /merge（如果你配置了 gh CLI）

紧急修复流（直接推 main）：

  /branch hotfix/critical-bug
  修复这个支付接口的空指针异常
  /commit -m "hotfix: null check on payment"
  /push
  /pr 紧急修复支付接口
  （然后在 GitHub App 上快速 merge）
```

### 4.9 项目生命周期管理 (`core/project_manager.py`)

**设计目标**：在手机上完成项目的注册、新建、初始化、删除，无需手动编辑配置文件。

```
项目管理分两条路径：

路径 A：本地已有目录，注册到 Bot
  /addproject my-api /home/jake/projects/my-api 后端 API 服务
  → 检查目录存在 → 写入 projects.yaml → 检测 git/CLAUDE.md → 完成

路径 B：从零新建项目
  /newproject my-saas-app 一个 SaaS 订阅管理系统，Next.js + PostgreSQL
  → 创建目录 → git init → Claude Code 生成 CLAUDE.md → 可选搭脚手架 → 注册 → 完成
```

```python
# core/project_manager.py
import os
import yaml
import asyncio
from datetime import datetime
from dataclasses import dataclass, field

@dataclass
class ProjectInfo:
    """单个项目的注册信息"""
    name: str
    path: str
    description: str = ""
    created_at: str = ""
    git_initialized: bool = False
    tags: list = field(default_factory=list)


class ProjectManager:
    """
    管理项目注册表（data/projects.yaml）。

    职责：
    - 加载/保存项目列表
    - 注册已有目录为项目（/addproject）
    - 从零新建项目（/newproject）
    - 初始化项目环境（/initproject）
    - 移除项目注册（/rmproject）
    - 校验项目路径安全性
    """

    def __init__(self, config, executor=None):
        self.workspace_root = os.path.expanduser(
            config.get("workspace_root", "~/projects")
        )
        self.projects_file = config.get("projects_file", "./data/projects.yaml")
        self.scaffold_on_create = config.get("scaffold_on_create", True)
        self.init_git = config.get("init_git_on_create", True)
        self.executor = executor  # Claude Code 执行器，用于生成 CLAUDE.md

        # 确保目录和文件存在
        os.makedirs(os.path.dirname(self.projects_file), exist_ok=True)
        os.makedirs(self.workspace_root, exist_ok=True)
        if not os.path.exists(self.projects_file):
            self._save({})

        self._projects: dict[str, ProjectInfo] = {}
        self._load()

    # ============ 读写 projects.yaml ============

    def _load(self):
        """从 YAML 加载项目列表"""
        with open(self.projects_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._projects = {}
        for name, info in data.items():
            self._projects[name] = ProjectInfo(
                name=name,
                path=info.get("path", ""),
                description=info.get("description", ""),
                created_at=info.get("created_at", ""),
                git_initialized=info.get("git_initialized", False),
                tags=info.get("tags", []),
            )

    def _save(self, data: dict = None):
        """保存项目列表到 YAML"""
        if data is None:
            data = {}
            for name, p in self._projects.items():
                data[name] = {
                    "path": p.path,
                    "description": p.description,
                    "created_at": p.created_at,
                    "git_initialized": p.git_initialized,
                    "tags": p.tags,
                }

        with open(self.projects_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    # ============ 查询 ============

    def list_projects(self) -> list[ProjectInfo]:
        """返回所有注册项目"""
        self._load()  # 每次读最新（允许手动编辑 yaml）
        return list(self._projects.values())

    def get_project(self, name: str) -> ProjectInfo | None:
        """按名称获取项目"""
        self._load()
        return self._projects.get(name)

    def project_exists(self, name: str) -> bool:
        return name in self._projects

    # ============ 注册已有目录 ============

    async def add_project(self, name: str, path: str, description: str = "") -> str:
        """
        注册已有本地目录为项目。

        用法: /addproject <name> <path> [description]
        示例: /addproject my-api /home/jake/projects/my-api 后端 API 服务

        步骤:
        1. 校验名称未被占用
        2. 校验目录存在
        3. 检测 git 状态
        4. 检测 CLAUDE.md
        5. 写入 projects.yaml
        """
        # 校验
        if self.project_exists(name):
            return f"❌ 项目名 `{name}` 已存在，请换一个名称"

        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return f"❌ 目录不存在: {path}"

        if not self._is_safe_path(path):
            return f"❌ 目录路径不安全"

        # 检测环境
        has_git = os.path.isdir(os.path.join(path, ".git"))
        has_claude_md = os.path.isfile(os.path.join(path, "CLAUDE.md"))

        # 注册
        project = ProjectInfo(
            name=name,
            path=path,
            description=description,
            created_at=datetime.now().isoformat(),
            git_initialized=has_git,
        )
        self._projects[name] = project
        self._save()

        # 构建返回信息
        lines = [f"✅ 已注册项目: `{name}`"]
        lines.append(f"📁 路径: {path}")
        if description:
            lines.append(f"📝 描述: {description}")
        lines.append(f"🔀 Git: {'✅ 已初始化' if has_git else '⚠️ 未初始化（/initproject 可初始化）'}")
        lines.append(f"📄 CLAUDE.md: {'✅ 已存在' if has_claude_md else '⚠️ 未找到（/initproject 可生成）'}")
        lines.append(f"\n💡 用 `/cd {name}` 切换到该项目")

        return "\n".join(lines)

    # ============ 从零新建项目 ============

    async def new_project(self, name: str, description: str = "") -> str:
        """
        从零新建项目。

        用法: /newproject <name> [description]
        示例: /newproject my-saas-app SaaS 订阅管理系统，Next.js + PostgreSQL

        步骤:
        1. 校验名称
        2. 在 workspace_root 下创建目录
        3. git init
        4. 让 Claude Code 生成 CLAUDE.md（基于 description）
        5. 注册到 projects.yaml
        6. 可选：让 Claude Code 搭建脚手架
        """
        if self.project_exists(name):
            return f"❌ 项目名 `{name}` 已存在"

        if not self._is_valid_name(name):
            return f"❌ 项目名只能包含字母、数字、连字符、下划线"

        project_path = os.path.join(self.workspace_root, name)

        if os.path.exists(project_path):
            return f"❌ 目录已存在: {project_path}\n用 /addproject 注册已有目录"

        # 1. 创建目录
        os.makedirs(project_path)

        # 2. git init
        has_git = False
        if self.init_git:
            proc = await asyncio.create_subprocess_exec(
                "git", "init",
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            has_git = proc.returncode == 0

        # 3. 生成 CLAUDE.md
        if self.executor and description:
            prompt = (
                f"你正在初始化一个新项目: {name}\n"
                f"项目描述: {description}\n\n"
                f"请创建一个 CLAUDE.md 文件，包含:\n"
                f"1. 项目名称和简介\n"
                f"2. 技术栈（根据描述推断）\n"
                f"3. 项目结构规划\n"
                f"4. 开发规范\n"
                f"5. 待办事项\n\n"
                f"只创建 CLAUDE.md，不要创建其他文件。"
            )
            await self.executor.run(
                prompt=prompt,
                cwd=project_path,
                use_continue=False,
            )

        # 4. 注册
        project = ProjectInfo(
            name=name,
            path=project_path,
            description=description,
            created_at=datetime.now().isoformat(),
            git_initialized=has_git,
        )
        self._projects[name] = project
        self._save()

        # 5. 返回结果
        lines = [f"✅ 项目已创建: `{name}`"]
        lines.append(f"📁 路径: {project_path}")
        if description:
            lines.append(f"📝 描述: {description}")
        lines.append(f"🔀 Git: {'✅ 已初始化' if has_git else '❌ 未初始化'}")

        has_claude_md = os.path.isfile(os.path.join(project_path, "CLAUDE.md"))
        lines.append(f"📄 CLAUDE.md: {'✅ 已生成' if has_claude_md else '⚠️ 未生成'}")

        lines.append(f"\n💡 用 `/cd {name}` 切换到该项目，然后直接发消息开始编码")

        if self.scaffold_on_create and description:
            lines.append(f"💡 如需搭脚手架，切换后发送: 根据 CLAUDE.md 搭建项目基础结构")

        return "\n".join(lines)

    # ============ 初始化已有项目 ============

    async def init_project(self, name: str) -> str:
        """
        对已注册的项目执行初始化（补全 git / CLAUDE.md）。

        用法: 先 /cd 到项目，再 /initproject
        """
        project = self.get_project(name)
        if not project:
            return f"❌ 项目 `{name}` 未注册"

        results = []

        # git init（如果还没有）
        if not project.git_initialized:
            proc = await asyncio.create_subprocess_exec(
                "git", "init",
                cwd=project.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                project.git_initialized = True
                results.append("🔀 Git 已初始化")
            else:
                results.append("❌ Git 初始化失败")

        # CLAUDE.md（如果还没有）
        claude_md_path = os.path.join(project.path, "CLAUDE.md")
        if not os.path.isfile(claude_md_path):
            if self.executor:
                prompt = (
                    f"分析当前项目目录结构，生成一份 CLAUDE.md 文件，包含:\n"
                    f"1. 项目名称: {name}\n"
                    f"2. 项目描述: {project.description or '(请根据代码推断)'}\n"
                    f"3. 技术栈\n"
                    f"4. 目录结构说明\n"
                    f"5. 开发规范\n"
                    f"6. 已知问题和待办\n\n"
                    f"只创建 CLAUDE.md，不要修改任何现有文件。"
                )
                await self.executor.run(
                    prompt=prompt,
                    cwd=project.path,
                    use_continue=False,
                )
                if os.path.isfile(claude_md_path):
                    results.append("📄 CLAUDE.md 已生成")
                else:
                    results.append("⚠️ CLAUDE.md 生成失败")
            else:
                results.append("⚠️ 未配置执行器，无法自动生成 CLAUDE.md")
        else:
            results.append("📄 CLAUDE.md 已存在，跳过")

        # .gitignore（如果还没有）
        gitignore_path = os.path.join(project.path, ".gitignore")
        if not os.path.isfile(gitignore_path):
            if self.executor:
                prompt = (
                    f"根据项目技术栈，生成一份合适的 .gitignore 文件。\n"
                    f"只创建 .gitignore，不要修改任何现有文件。"
                )
                await self.executor.run(
                    prompt=prompt,
                    cwd=project.path,
                    use_continue=False,
                )
                results.append("📄 .gitignore 已生成")

        self._save()

        if not results:
            return f"✅ 项目 `{name}` 已经是完整初始化状态"

        return f"✅ 项目 `{name}` 初始化完成:\n" + "\n".join(results)

    # ============ 移除项目注册 ============

    async def remove_project(self, name: str, delete_files: bool = False) -> str:
        """
        从注册表中移除项目。

        默认只取消注册，不删除文件。
        文件删除是高危操作，禁止从手机远程执行。
        """
        if not self.project_exists(name):
            return f"❌ 项目 `{name}` 不存在"

        project = self._projects.pop(name)
        self._save()

        return (
            f"✅ 已取消注册项目: `{name}`\n"
            f"📁 文件保留在: {project.path}\n"
            f"💡 重新注册: /addproject {name} {project.path}"
        )

    # ============ 工具方法 ============

    def _is_valid_name(self, name: str) -> bool:
        """项目名只允许字母、数字、连字符、下划线"""
        import re
        return bool(re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', name))

    def _is_safe_path(self, path: str) -> bool:
        """安全检查：不允许注册系统关键目录"""
        real_path = os.path.realpath(path)
        dangerous = ["/", "/bin", "/usr", "/etc", "/var", "/tmp",
                     "/root", "/home", os.path.expanduser("~")]
        return real_path not in dangerous
```

**项目完整生命周期流程图：**

```
┌──────────────────────────────────────────────────────────┐
│                    项目生命周期                            │
└──────────────────────────────────────────────────────────┘

  场景 A: 注册已有项目              场景 B: 从零新建项目
  ═══════════════════              ═══════════════════════

  本地已有代码                      手机上想到一个新项目
       │                                 │
       ▼                                 ▼
  /addproject my-api                /newproject my-saas 描述...
  /home/jake/projects/my-api             │
       │                                 ▼
       ▼                           创建 workspace_root/my-saas/
  检查目录是否存在 ──No──▶ ❌               │
       │ Yes                             ▼
       ▼                            git init（自动）
  检测 .git → 记录状态                    │
  检测 CLAUDE.md → 记录状态               ▼
       │                           Claude Code 生成 CLAUDE.md
       ▼                                 │
  ┌─────────────────┐                    ▼
  │ 写入             │              写入 projects.yaml
  │ projects.yaml    │                    │
  └────────┬────────┘                    ▼
           │                       ✅ 返回结果 + 提示下一步
           ▼
  ✅ 返回结果 + 诊断信息
  (缺 git? 缺 CLAUDE.md?)
           │
           ▼
  如果有缺失 → /initproject
  一切就绪  → /cd my-api 开始干活


  日常使用:                         结束使用:
  ═══════                          ═══════

  /cd my-api                       /rmproject old-stuff
  开始编码...                       → 只取消注册，文件保留
  /cd my-saas                      → 可随时 /addproject 重新注册
  切换项目...
```

---

## 5. 安全设计

### 5.1 鉴权模型

```
消息进入 → 平台 user_id 白名单校验 → 通过才路由

安全层级：
1. Telegram/飞书 user_id 白名单（硬性，config.yaml 配置）
2. Claude Code --allowedTools 限制（防止意外执行危险命令）
3. 项目目录白名单（只能 cd 到预定义的项目）
4. 可选：指令审核模式（高危操作二次确认）
```

### 5.2 敏感操作保护

```python
# utils/security.py

# 需要二次确认的指令模式
DANGEROUS_PATTERNS = [
    r"rm\s+-rf",
    r"drop\s+table",
    r"git\s+push.*--force",
    r"git\s+reset.*--hard",
    r"sudo",
    r"chmod\s+777",
    r"DELETE\s+FROM",
    r"format\s+",
]

def check_dangerous(text: str) -> str | None:
    """返回危险操作描述，None 表示安全"""
    import re
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return f"检测到潜在危险操作: {pattern}"
    return None
```

---

## 6. 本地测试 & 部署方案

### 6.1 本地测试（5 分钟跑起来）

飞书长连接模式是为本地开发设计的，无需公网 IP、无需 ngrok、无需任何端口映射。你的电脑能访问外网就行。

**前置条件：**

```
- Python 3.11+
- Node.js 18+ (Claude Code 依赖)
- Claude Code CLI 已安装并认证
- 飞书开发者账号（免费）
```

**Step 1：飞书后台创建应用（约 3 分钟）**

```
1. 打开 https://open.feishu.cn/app → 创建企业自建应用
2. 记下 App ID 和 App Secret

3. 左侧菜单「事件与回调」：
   - 订阅方式选择 → 「使用长连接接收事件」
   - 添加事件 → 搜索 "im.message.receive_v1"（接收消息 v2.0）
   - 点击添加

4. 左侧菜单「权限管理」→ 搜索并开通：
   - im:message              （获取与发送单聊、群组消息）
   - im:message:send_as_bot  （以应用的身份发送消息）
   - im:resource              （获取与上传图片或文件资源）

5. 左侧菜单「版本管理与发布」→ 创建版本 → 发布
   （可用范围设为你自己所在部门，免审核）

6. 在飞书 App 里找到你的机器人，发送一条消息测试
```

**Step 2：安装并运行**

```bash
# 1. 克隆项目
git clone https://github.com/yourname/claude-remote-bot.git
cd claude-remote-bot

# 2. 安装依赖
python -m venv venv
source venv/bin/activate
pip install lark-oapi pyyaml

# 3. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml：
#   feishu.app_id: 你的 App ID
#   feishu.app_secret: 你的 App Secret
#   feishu.allowed_users: 你的 open_id

# 4. 确认 Claude Code 正常
claude --version
claude -p "hello" --output-format json

# 5. 启动！
python main.py
# 看到 "✅ 飞书 Bot 已启动 (WebSocket 长连接模式)" 就成功了
```

**Step 3：在飞书里测试**

```
你在飞书发送: 帮我写一个 hello world 的 Python 脚本
Bot 回复:
  ⏳ 执行中... [my-webapp]
  ✅ 完成 | ⏱ 12.3s | 💰 $0.0082
  📁 变更文件: 1
    • hello.py
  已创建 hello.py，内容为标准的 Hello World 脚本...
```

**如何获取你的 open_id（用于白名单）：**

```python
# 临时脚本：把事件回调打印出来，就能看到 sender_id
def do_p2_im_message_receive_v1(data):
    print(f"sender open_id: {data.event.sender.sender_id.open_id}")
    print(f"chat_id: {data.event.message.chat_id}")
```

先不配白名单，启动 bot，给它发一条消息，从终端日志里复制 open_id 填到 config.yaml 里。

### 6.2 飞书关键注意事项

```
⚠️ 飞书要求 3 秒内确认消息
   → 我们在回调中只做消息提取，实际处理放到异步任务
   → 先回复 "⏳ 执行中..."，处理完再发结果

⚠️ 消息去重
   → 飞书在确认超时时会重复投递消息
   → 需要用 message_id 做去重（已在 adapter 中处理）

⚠️ 长连接自动重连
   → lark-oapi SDK 内置了断线重连逻辑
   → 但网络长时间中断后可能需要重启进程
```

### 6.3 生产部署（systemd）

本地测试没问题后，用 systemd 挂成后台服务：

```ini
# /etc/systemd/system/claude-bot.service
[Unit]
Description=Claude Code Remote Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jake
WorkingDirectory=/home/jake/claude-remote-bot
ExecStart=/home/jake/claude-remote-bot/venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PATH=/home/jake/.npm-global/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable claude-bot
sudo systemctl start claude-bot
sudo systemctl status claude-bot    # 检查状态
journalctl -u claude-bot -f          # 查看日志
```

### 6.4 网络方案

```
飞书长连接模式（本项目默认）：
  ✅ 无需公网 IP
  ✅ 无需域名
  ✅ 无需端口映射 / ngrok / frp
  ✅ 本地电脑能上网就行
  → Bot 通过 WebSocket 主动连接飞书服务器，飞书推送事件过来

后续如果要加 Telegram：
  方案 A: Polling 模式（同样无需公网 IP）
  方案 B: Webhook + Tailscale 组网（响应更快）
```

---

## 7. 数据流全图

```
   ┌──────────────────────────────────────────────────────────────┐
   │                     完整请求生命周期                          │
   └──────────────────────────────────────────────────────────────┘

   手机飞书 App
       │
       │ ① 用户发送: "给 login 页面加一个记住密码的功能"
       ▼
   飞书服务器 ──WebSocket──▶ Bot Server (本地电脑)
                               │
                     ② 鉴权: user_id ∈ 白名单? ✓
                               │
                     ③ 路由: 非 / 开头 → Claude Code 指令
                               │
                     ④ 加载记忆:
                     │   ├─ 压缩摘要: "Next.js 项目，已完成基础认证..."
                     │   └─ 近期记录:
                     │       [02-08] 重构了登录组件为 React Hook Form
                     │       [02-09] 修复了 session 过期后的跳转问题
                               │
                     ⑤ 拼接 Prompt:
                     │   "## 项目历史摘要
                     │    Next.js 项目，已完成基础认证...
                     │
                     │    ## 近期工作记录
                     │    - [02-08] 重构了登录组件...
                     │    - [02-09] 修复了 session 过期...
                     │
                     │    ## 当前任务
                     │    给 login 页面加一个记住密码的功能"
                               │
                     ⑥ 调用 Claude Code:
                     │   claude -p "<prompt>" --continue \
                     │          --output-format json \
                     │          --allowedTools "Read,Write,Edit,Bash,Grep"
                     │
                     │   Claude Code 执行:
                     │     → 读取 CLAUDE.md (额外上下文)
                     │     → 阅读 src/app/login/page.tsx
                     │     → 修改组件，添加 "记住密码" checkbox
                     │     → 修改 auth service，添加 persistent session
                     │     → 运行测试
                               │
                     ⑦ 解析输出:
                     │   JSON → session_id, result, cost, files_changed
                               │
                     ⑧ 保存记忆:
                     │   DB 写入: {task, summary, files_changed, session_id}
                     │   如果超过阈值:
                     │     → 归档旧记录到 archives/my-webapp_2025_02.jsonl
                     │     → 生成压缩摘要替换旧记录
                               │
                     ⑨ 更新 CLAUDE.md (如果达到更新阈值):
                     │   追加近期变更记录到 auto-managed section
                               │
                     ⑩ 格式化输出:
                     │   "✅ 完成 | ⏱ 45.2s | 💰 $0.0342
                     │
                     │    📁 变更文件: 3
                     │      • src/app/login/page.tsx
                     │      • src/lib/auth.ts
                     │      • src/lib/session.ts
                     │
                     │    已添加"记住密码"功能：
                     │    - 登录表单增加了 checkbox
                     │    - 勾选后 session 有效期延长到 30 天
                     │    - 使用 httpOnly cookie 存储..."
                               │
                               ▼
   飞书服务器 ◀──WebSocket── Bot 发送消息到手机
       │
       ▼
   手机飞书收到结果，继续下一条指令...
```

---

## 8. 元命令使用示例

### 8.1 项目管理

```
# ===== 查看现有项目 =====

/projects
  → 📋 已注册项目 (3):
    • my-webapp     — 主要 Web 项目  ✅ git
    • trading-bot   — 量化交易系统    ✅ git
    • supply-chain  — 供应链数据分析  ⚠️ no git
    当前: my-webapp

# ===== 注册已有目录 =====

/addproject my-api /home/jake/projects/my-api 后端 API 服务
  → ✅ 已注册项目: `my-api`
    📁 路径: /home/jake/projects/my-api
    📝 描述: 后端 API 服务
    🔀 Git: ✅ 已初始化
    📄 CLAUDE.md: ⚠️ 未找到（/initproject 可生成）

    💡 用 `/cd my-api` 切换到该项目

# ===== 从零新建项目 =====

/newproject my-saas-app SaaS 订阅管理系统，用 Next.js + PostgreSQL + Stripe
  → ⏳ 创建项目中...
  → ✅ 项目已创建: `my-saas-app`
    📁 路径: /home/jake/projects/my-saas-app
    📝 描述: SaaS 订阅管理系统，用 Next.js + PostgreSQL + Stripe
    🔀 Git: ✅ 已初始化
    📄 CLAUDE.md: ✅ 已生成

    💡 用 `/cd my-saas-app` 切换到该项目，然后直接发消息开始编码
    💡 如需搭脚手架，切换后发送: 根据 CLAUDE.md 搭建项目基础结构

# ===== 切换到新项目并开始工作 =====

/cd my-saas-app
  → ✅ 已切换到 my-saas-app (/home/jake/projects/my-saas-app)

根据 CLAUDE.md 搭建项目基础结构
  → ⏳ 执行中... [my-saas-app]
  → ✅ 完成 | ⏱ 62.5s | 💰 $0.0890
    📁 变更文件: 12
      • package.json
      • tsconfig.json
      • src/app/layout.tsx
      • src/app/page.tsx
      • src/lib/db.ts
      • prisma/schema.prisma
      ...
    已搭建 Next.js 项目基础结构，包含 Prisma ORM、
    Stripe 支付集成配置、基础页面路由...

# ===== 初始化缺失环境 =====

/cd supply-chain
/initproject
  → ✅ 项目 `supply-chain` 初始化完成:
    🔀 Git 已初始化
    📄 CLAUDE.md 已生成
    📄 .gitignore 已生成

# ===== 取消注册 =====

/rmproject old-experiment
  → ✅ 已取消注册项目: `old-experiment`
    📁 文件保留在: /home/jake/projects/old-experiment
    💡 重新注册: /addproject old-experiment /home/jake/projects/old-experiment
```

### 8.2 日常工作流（完整示例）

```
# 通勤路上，用手机飞书操作

/projects                            # 看看有哪些项目
/cd trading-bot                      # 切到量化系统

/status                              # 看看上次干到哪了
  → 📊 当前状态
    项目: trading-bot
    会话: abc123 (已有 5 轮对话)
    模型: claude-sonnet-4
    记忆: 23 条活跃 + 1 份压缩摘要 + 3 个归档文件

修复那个 websocket 断线重连的 bug    # 直接用中文描述任务
  → ⏳ 执行中... [trading-bot]
  → ✅ 完成 | ⏱ 38.1s | 💰 $0.0251
    📁 变更文件: 2
      • src/ws/client.py
      • tests/test_ws_reconnect.py
    已修复 WebSocket 重连逻辑，增加了指数退避...

把测试也跑一下确认没有 break 其他功能  # 继续在同一个会话里追加任务
  → ⏳ 执行中... [trading-bot]
  → ✅ 完成 | ⏱ 15.2s | 💰 $0.0120
    All 42 tests passed ✅

/diff                                # 快速确认变更
/commit -m "fix: ws reconnect"       # 提交
/push                                # 推送

# 突然想到一个新项目

/newproject price-alert 加密货币价格预警机器人，Python + Telegram
  → ✅ 项目已创建...

/cd price-alert
用 ccxt 库实现 BTC/ETH 价格监控，超过阈值就推送 Telegram 通知
  → ⏳ 执行中...
```

### 8.3 文件管理

```
/tree src/ws
  → 📁 src/ws/
    ├── client.py
    ├── handler.py
    ├── reconnect.py
    └── __init__.py

/cat src/ws/client.py 45-80
  → 📄 src/ws/client.py (156 lines, showing 45-80)
    ```
      45 │ class WSClient:
      46 │     def __init__(self, url, **kwargs):
      47 │         self.url = url
      ...
    ```

/dl src/ws/client.py
  → 📎 [文件: client.py, 4.2KB]

（手机发送截图并回复 /upload assets/mockup.png）
  → ✅ 已保存到 assets/mockup.png
```

### 8.4 Git 操作

```
/diff
  → 📊 变更统计:
    src/ws/client.py       | 24 +++++++--
    tests/test_reconnect.py | 45 +++++++++++++++
    2 files changed, 61 insertions(+), 8 deletions(-)

    详细 diff:
    ```diff
    + async def reconnect(self, max_retries=5):
    +     backoff = 1
    ...
    ```

/branch feat/ws-reconnect
  → ✅ 已创建并切换到新分支: feat/ws-reconnect

/commit -m "fix: websocket reconnect with exponential backoff"
  → ✅ 已提交
    [bot] fix: websocket reconnect with exponential backoff
    2 files changed, 61 insertions(+), 8 deletions(-)

/push
  → ✅ 已推送到 origin/feat/ws-reconnect

/pr WebSocket 断线重连优化
  → ✅ PR 已创建
    🔗 https://github.com/jake/trading-bot/pull/42

/gitlog 5
  → 📜 最近 5 条 commit:
    a1b2c3d [bot] fix: websocket reconnect with exponential backoff (2 minutes ago)
    e4f5g6h refactor: extract ws handler (3 hours ago)
    ...

/rollback
  → ✅ 已软回滚 1 个 commit（文件变更保留在暂存区）

/stash
  → ✅ Saved working directory and index state: Stashed via bot

/stash pop
  → ✅ 恢复暂存的修改
```

### 8.5 记忆与归档

```
/memory websocket
  → 🔍 搜索结果（活跃记忆）:
    [02-08] 实现了 WebSocket 基础连接 → 完成 ws/client.py 框架
    [02-09] 添加了心跳检测 → 30s 间隔 ping/pong
    [02-09] 修复断线重连 → 指数退避，最大重试 5 次

/archive websocket
  → 🗄️ 搜索归档记录:
    [01-15] 调研了 websocket 库选型 → 选择 websockets + asyncio
    [01-16] 初始 WebSocket 模块搭建 → 基本连接和消息收发
    [01-20] WebSocket 性能测试 → 单连接 10k msg/s，可满足需求

/status
  → 📊 当前状态
    ...
    归档: 2 个文件, 共 0.34 MB
      trading-bot_2025_01.jsonl (156 条)
      trading-bot_2025_02.jsonl (23 条)
```

---

## 9. 扩展计划

### Phase 1（MVP — 飞书本地测试）
- [x] 飞书 Bot + WebSocket 长连接 + 白名单鉴权
- [x] Claude Code 基本调用（-p + --continue）
- [x] 长消息分段发送
- [x] 项目生命周期管理（/addproject, /newproject, /cd, /projects, /initproject）
- [x] 基本记忆（SQLite 存储 + 注入）
- [x] 基本 Git 操作（/diff, /commit, /push）
- [x] 文件查看（/cat, /tree）

### Phase 2（完善）
- [ ] FTS 全文搜索记忆
- [ ] 记忆自动压缩 + JSONL 归档
- [ ] CLAUDE.md 自动维护
- [ ] 完整 Git 工作流（/pr, /branch, /rollback, /stash）
- [ ] 文件上下传（/dl, /upload）
- [ ] 危险操作检测与确认
- [ ] /archive 归档搜索
- [ ] Telegram 适配器（扩展第二个平台）

### Phase 3（高级）
- [ ] 多用户支持（家人/团队成员分权限）
- [ ] 手机发截图给 Claude 分析（图片消息 → Claude Code）
- [ ] CI/CD 集成（GitHub Actions 结果推送回 Telegram）
- [ ] 定时任务（每日 git pull + 跑测试 + 汇报）
- [ ] Web Dashboard（可选，手机浏览器看详细 diff 和代码）
- [ ] MCP Server 集成（连接 GitHub、Jira 等）
- [ ] 成本追踪与预算告警
- [ ] 归档定期清理与 retention 策略
