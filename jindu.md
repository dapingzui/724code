# 724code 开发进度

## 2026-02-10: V2 实施计划已确定 — Kimi 引擎 + 飞书适配器

### 状态：计划完成，尚未开始编码

### V2 总体目标
1. **Kimi Code 双引擎** — 让用户通过 `/engine kimi` 切换到 Kimi Code CLI（优先）
2. **飞书适配器** — WebSocket 长连接模式，NAS 无需公网 IP

### Phase 1: Kimi Code 双引擎（优先实施）

**新建文件（按顺序）：**

| # | 文件 | 用途 | 行数 |
|---|------|------|------|
| 1 | `core/base_executor.py` | 执行器 ABC + ExecutionResult（从 executor.py 提取） | ~50 |
| 2 | `core/kimi_executor.py` | Kimi CLI 执行器，解析 JSONL 输出 | ~180 |
| 3 | `core/engine_manager.py` | 引擎注册表，按名称获取执行器 | ~40 |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `core/executor.py` | 继承 BaseExecutor，移除 ExecutionResult 定义 |
| `core/session_manager.py` | Session 增加 `engine`、`kimi_session_id` 字段；SessionManager 增加 `set_engine()` |
| `core/router.py` | executor → engine_mgr；`_handle_claude` → `_handle_code`；新增 `/engine` 命令；`/model` 按引擎区分别名；`/status` 显示引擎 |
| `main.py` | 初始化双引擎 + EngineManager；check_prerequisites 加 kimi（可选）|
| `config.example.yaml` | 新增 `kimi:` 和 `engine:` 配置段 |

**关键设计：**
- Claude CLI: `claude -p "prompt" --output-format json --model X --resume SID --allowedTools R W`
- Kimi CLI: `kimi --print -p "prompt" --output-format stream-json -m X -S SID --yolo -w CWD`
- Kimi 输出每行一个 JSON（`{role, content}`），取最后一条 assistant 消息作为结果
- Kimi 无 session_id/cost 返回，需外部管理
- `/engine kimi` 切换引擎，会话重置

**实施顺序：**
1. `core/base_executor.py` — 创建 ABC + ExecutionResult
2. `core/executor.py` — 改为继承 BaseExecutor
3. `core/kimi_executor.py` — Kimi 执行器
4. `core/engine_manager.py` — 引擎注册表
5. `core/session_manager.py` — 增加引擎字段
6. `core/router.py` — 引擎无关化 + /engine 命令
7. `config.example.yaml` — Kimi 配置段
8. `main.py` — 双引擎初始化
9. 测试 + NAS 部署

### Phase 2: 飞书适配器

**新建文件：**
- `adapters/feishu_adapter.py` — 飞书 WebSocket 适配器 (~180行)

**修改文件：**
- `main.py` — 多适配器支持，按 config 条件初始化 Telegram/飞书
- `config.example.yaml` — 新增 `feishu:` 配置段（app_id, app_secret, allowed_users）
- `requirements.txt` — 添加 `lark-oapi>=1.0.0`

**关键设计：**
- `lark-oapi` 的 `ws.Client` 在后台线程运行，通过 `asyncio.run_coroutine_threadsafe()` 桥接到主 asyncio 事件循环
- Telegram + 飞书可同时运行，共享同一个 Router
- 按 config 中是否配置 token/app_id 决定启用哪些适配器

### 当前代码架构快照（V1 完成状态）

```
main.py          → 入口，初始化所有模块
adapters/base.py → BotAdapter ABC + IncomingMessage/OutgoingMessage
adapters/telegram_adapter.py → Telegram Polling
core/router.py   → 命令路由（直接持有 ClaudeExecutor）
core/executor.py → ClaudeExecutor + ExecutionResult（JSON 输出解析）
core/session_manager.py → Session（chat_id/project/model/claude_session_id）
core/project_manager.py → 项目 CRUD
core/output_processor.py → compress_output
core/git_ops.py  → Git 命令封装
core/file_manager.py → /cat, /tree
memory/store.py  → SQLite + FTS5
memory/injector.py → 上下文注入
```

### 验证标准
- 现有 29 项测试全部通过（向后兼容）
- 新增 `/engine` 切换测试
- Kimi 编码流程测试（写文件、运行、编辑）
- 飞书消息收发测试
- 双平台并行运行测试

---

## 2026-02-10: Stage 5 完成 — Git 操作 + 文件查看

### 完成内容
- `core/git_ops.py` — Git 操作：/diff, /commit, /push, /pull, /branch, /log, /gs
- `core/file_manager.py` — 文件查看：/cat（带行号+行范围）, /tree（纯 Python 跨平台）
- 安全保护：路径逃逸拦截（`_is_within_project`）、保护分支禁止直接 push
- Router 集成：`_require_project` 复用检查，git/file 命令全部接入
- 全部 13 项集成测试通过

### 新增命令
| 命令 | 功能 |
|------|------|
| `/diff [ref]` | 查看变更（stat + 详细 diff） |
| `/commit [消息]` | git add -A + commit |
| `/push [分支]` | 推送（保护分支拦截） |
| `/pull` | 拉取 |
| `/branch [名称]` | 查看/创建/切换分支 |
| `/log [数量]` | 最近 commit 记录 |
| `/gs` | git status |
| `/cat <文件> [行范围]` | 查看文件（带行号，支持 5-10 或 100） |
| `/tree [路径] [深度]` | 目录结构（默认深度 2） |

---

## 2026-02-10: Stage 4 完成 — 输出压缩 + 记忆系统

### 完成内容
- `core/output_processor.py` — 输出压缩（4000字符阈值，头60%+尾30%策略）
- `memory/store.py` — SQLite + FTS5 全文搜索，中文 LIKE 回退
- `memory/injector.py` — 上下文注入（最近记录拼接到 prompt）
- executor 改用 `compress_output` 替代内联格式化
- router 集成记忆：执行后自动保存，prompt 自动注入上下文
- 新增命令：`/memory`（最近记录）、`/memory stats`（统计）、`/search <关键词>`
- 修复：FTS5 SQL 语法错误、相对路径解析（projects_file/db_path）
- 全部 11 项集成测试通过（/help → /projects → /cd → 执行 → /memory → /search → /detail）

### 关键修复
- FTS5 `WHERE fts MATCH` → `WHERE memories_fts MATCH`
- config.yaml 中相对路径统一用 `resolve_path()` 基于项目根目录解析
- 中文搜索 FTS5 分词不佳，自动回退 LIKE 模糊搜索

### Max 套餐说明
- 用户使用 Claude Max 订阅，CLI 使用包含在订阅内
- Bot 显示的费用仅用于跟踪用量，不额外扣款

---

## 2026-02-10: Stage 3 完成 — 命令路由 + 项目管理 + 模型切换

### 完成内容
- `core/router.py` — 元命令分发 vs Claude Code 指令
- `core/session_manager.py` — 会话状态（项目/模型/session_id）
- `core/project_manager.py` — 项目注册表 CRUD (data/projects.yaml)
- `/model sonnet|opus|haiku` — 模型切换，默认 Sonnet，日常用 Haiku 省钱
- 所有命令 Telegram 测试通过

---

## 2025-02-10: Stage 1 & 2 完成

### Stage 1 — Telegram 消息收发骨架
- Telegram Polling 模式 + 代理 + 白名单鉴权，echo 回显测试通过

### Stage 2 — Claude Code CLI 集成
- `core/executor.py` 完成：asyncio.subprocess 调用 `claude -p`，JSON 输出解析
- 代理通过 `HTTPS_PROXY` 环境变量注入子进程
- 端到端测试通过：发 "1+1" → 返回 "2"（5.7s, $0.0273）

---

## 2025-02-10: 确定部署方案 — 不用 Docker

### 决策
- Bot 必须直接调用主机 `claude` CLI + 读写主机项目文件
- Docker 隔离文件系统和 CLI，不适合本项目
- **所有用户统一原生部署**：`git clone + pip install + systemd`
- 提供 `install.sh` 一键安装脚本

### 原因
- Claude Code CLI 需要访问主机文件系统（项目源码、git 仓库）
- 需要调用主机上安装的工具（git、node、python 等）
- 自己和发布给别人的部署方式完全一致，无需维护两套方案

---

## 2025-02-10: 项目文档统一

### 完成内容
- 统一技术方案：Telegram 优先（替代飞书），NAS 群晖 Linux 部署
- V1 仅 Claude Code 引擎，Kimi Code 和飞书适配器移入 V2
- 新增代理架构设计：Telegram Bot API + Claude Code 子进程共用代理
- 更新文档：CLAUDE.md, config.example.yaml, requirements.txt, .gitignore

### 关键决策
- **平台**: Telegram Polling（主动轮询，走代理，无需公网 IP）
- **代理**: config.yaml 统一配置，Telegram 用 `proxy_url` 参数，Claude Code 用 `HTTPS_PROXY` 环境变量
- **部署**: 原生 systemd，不用 Docker
- **依赖**: `python-telegram-bot[socks]` + `httpx[socks]` + `pyyaml`

### 开发阶段规划
| Stage | 内容 | 状态 |
|-------|------|------|
| 1 | Telegram 消息收发骨架 (echo 回显) | 待开始 |
| 2 | Claude Code CLI 集成 + 代理 | 待开始 |
| 3 | 命令路由 + 项目管理 + 会话管理 | 待开始 |
| 4 | 输出压缩 + 记忆系统 | 待开始 |
| 5 | Git 操作 + 文件查看 | 待开始 |
| 6 | 安全加固 + systemd 部署 | 待开始 |

---

## 待办 / 下一步
- **V2 Phase 1**: Kimi Code 双引擎（按上述实施顺序 1-9 逐步完成）
- **V2 Phase 2**: 飞书适配器
- Stage 6：安全加固 + systemd 部署 + install.sh + README
