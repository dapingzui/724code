# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

通过 Telegram 机器人远程操控家中 NAS（群晖 Linux）上的 Claude Code CLI，用手机完成编码工作。

**GitHub 仓库名**: 724code

## 核心架构

```
手机 Telegram → Telegram API ←(Polling/代理)← NAS上的Python服务 → Claude Code CLI
```

- NAS 在 NAT 后面，无公网 IP
- Telegram Bot 使用 **Polling 模式**（NAS 主动轮询），不需要穿透工具
- NAS 网络环境需要**代理**访问 Telegram API 和 Claude Code API
- V1 仅 Claude Code 引擎，V2 扩展 Kimi Code + 飞书适配器

## 技术栈

- **语言**: Python 3.11+
- **Telegram SDK**: `python-telegram-bot` v20+（asyncio 原生，Polling 模式无需公网）
- **进程管理**: `asyncio.subprocess`
- **记忆存储**: SQLite + FTS5 全文搜索
- **配置**: YAML
- **部署**: systemd 原生部署（不用 Docker，需直接访问主机 CLI 和文件系统）
- **代理**: 支持 HTTP/SOCKS5 代理（Telegram API + Claude Code 子进程均通过代理）

## V1 功能范围

### 必须实现
- [ ] Telegram Polling 长轮询 + 白名单鉴权
- [ ] Claude Code CLI 调用（`--allowedTools` 精确控制权限）
- [ ] 代理配置（Telegram Bot + Claude Code 子进程共用）
- [ ] 输出压缩：超过 4000 字符截断，保留头尾+关键变更
- [ ] 项目管理：/addproject, /newproject, /cd, /projects, /rmproject
- [ ] 会话管理：/new, /status, /abort
- [ ] 基本记忆：SQLite 存储 + 上下文注入
- [ ] Git 操作：/diff, /commit, /push, /pull, /branch
- [ ] 文件查看：/cat, /tree
- [ ] 长消息智能分段（在代码块边界或换行处切割）

### V2 再做
- Kimi Code 双引擎 + engine_manager.py
- 飞书适配器（WebSocket 长连接模式）
- 记忆自动压缩 + JSONL 归档
- CLAUDE.md 自动维护
- 完整 Git 工作流（/pr, /rollback, /stash）
- 文件上下传（/dl, /upload）
- 危险操作检测与确认
- Web 面板查看完整输出

## 项目结构

```
724code/
├── CLAUDE.md                # 本文件
├── design.md                # 完整设计方案
├── config.example.yaml      # 配置模板
├── config.yaml              # 实际配置（gitignore）
├── requirements.txt         # Python 依赖
├── jindu.md                 # 开发进度记录
├── install.sh               # 一键安装脚本（含 systemd 配置）
├── 724code.service          # systemd 服务文件模板
├── main.py                  # 入口
├── adapters/                # 消息平台适配层
│   ├── base.py              # 抽象基类（IncomingMessage, OutgoingMessage, BotAdapter）
│   └── telegram_adapter.py  # Telegram Polling 实现
├── core/
│   ├── router.py            # 命令路由（元命令 vs Claude Code 指令）
│   ├── executor.py          # Claude Code CLI 调用执行器
│   ├── session_manager.py   # 会话生命周期管理
│   ├── output_processor.py  # 输出格式化与压缩（4000字符阈值）
│   ├── project_manager.py   # 项目生命周期管理
│   ├── git_ops.py           # Git 操作封装
│   └── file_manager.py      # 文件查看（/cat, /tree）
├── memory/
│   ├── store.py             # SQLite 存储引擎 + FTS5
│   └── injector.py          # 上下文注入（拼接 prompt）
├── utils/
│   ├── security.py          # 白名单鉴权
│   └── logger.py            # 日志
└── data/
    ├── projects.yaml        # 项目注册表（运行时动态读写）
    └── memories.db          # SQLite 数据库
```

## 关键设计决策

1. **不用 Docker，原生部署**: Bot 必须直接调用主机上的 `claude` CLI 并读写主机项目文件。Docker 会隔离文件系统和 CLI 访问，不适合本项目。所有用户（包括发布后的其他用户）统一用 `git clone + pip install + systemd` 方式部署。提供 `install.sh` 一键安装脚本。

2. **代理架构**: Telegram API 和 Claude Code API 在部分网络环境需要代理。config.yaml 统一配置代理地址，Telegram Bot 通过 `proxy_url` 参数使用，Claude Code 子进程通过 `HTTPS_PROXY` 环境变量注入。代理为可选配置，有直连条件的用户可留空。

3. **Telegram Polling vs Webhook**: 选 Polling。无需公网 IP，Bot 主动发请求，走代理出去即可，零网络配置。

4. **输出压缩**: 4000 字符阈值（Telegram 上限 4096，留余量）。Claude Code 用 `--output-format json` 返回结构化数据，提取 result、session_id、cost、duration。

5. **会话续接**: 使用 Claude Code 的 `--resume <session_id>` 和 `--continue` 参数保持对话上下文。

6. **项目注册表**: `config.yaml` = 静态配置（手动编辑），`data/projects.yaml` = 动态数据（Bot 运行时命令管理）。

7. **平台适配层**: 所有平台特定逻辑封装在 `adapters/` 下，核心模块（router/executor/memory）平台无关，V2 加飞书只需新增 adapter。

## 开发规范

- 所有异步操作使用 `asyncio`
- 代码注释用中文
- 错误信息对用户友好，带 emoji 前缀（✅ ❌ ⏳ ⚠️）
- 文件操作必须检查路径逃逸（`_is_within_project`）
- Git 操作必须检查保护分支
- 不可变模式：dataclass 创建新实例，不要 mutate

## 开发顺序

按以下顺序逐步实现，每完成一步都应该可以测试：

1. **Stage 1**: Telegram 消息收发骨架（config + adapter + main → echo 回显）
2. **Stage 2**: Claude Code 集成（executor + 代理配置 → 真实调用）
3. **Stage 3**: 命令路由 + 项目管理（router + project_manager + session_manager）
4. **Stage 4**: 输出压缩 + 记忆系统（output_processor + memory/）
5. **Stage 5**: Git 操作 + 文件查看（git_ops + file_manager）
6. **Stage 6**: 安全加固 + 部署配置（systemd + README）

## 构建与运行

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填入实际值
cp config.example.yaml config.yaml

# 开发运行
python main.py

# 生产部署（systemd）
sudo cp 724code.service /etc/systemd/system/
sudo systemctl enable --now 724code
```

## 参考

- 完整设计方案见 `design.md`
- Telegram Bot API: https://core.telegram.org/bots/api
- python-telegram-bot: https://python-telegram-bot.readthedocs.io
- Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code
