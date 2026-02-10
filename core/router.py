"""命令路由 — 区分元命令和 Claude Code 指令"""

import logging

from adapters.base import BotAdapter, IncomingMessage, OutgoingMessage
from core.executor import ClaudeExecutor
from core.session_manager import SessionManager
from core.project_manager import ProjectManager
from core.git_ops import GitOps
from core.file_manager import FileManager
from memory.store import ProjectMemoryManager
from memory.injector import ContextInjector

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        executor: ClaudeExecutor,
        session_mgr: SessionManager,
        project_mgr: ProjectManager,
        memory_mgr: ProjectMemoryManager,
        injector_config: dict,
        git_ops: GitOps,
        file_mgr: FileManager,
    ):
        self.executor = executor
        self.session_mgr = session_mgr
        self.project_mgr = project_mgr
        self.memory_mgr = memory_mgr
        self.injector = ContextInjector(injector_config)
        self.git = git_ops
        self.file_mgr = file_mgr
        self._last_full_output: dict[str, str] = {}  # chat_id -> 完整输出

    async def handle(self, msg: IncomingMessage, adapter: BotAdapter):
        """路由入口：命令走元命令，普通文本走 Claude Code"""
        text = msg.text.strip()
        if not text:
            return

        logger.info(f"收到消息 [{msg.user_id}]: {text[:100]}")

        try:
            if text.startswith("/"):
                await self._handle_command(msg, adapter, text)
            else:
                await self._handle_claude(msg, adapter, text)
        except Exception as e:
            logger.error(f"处理消息异常: {e}", exc_info=True)
            try:
                await adapter.send_message(OutgoingMessage(
                    chat_id=msg.chat_id,
                    text=f"处理出错: {e}",
                ))
            except Exception:
                pass

    # ========== 元命令分发 ==========

    async def _handle_command(self, msg: IncomingMessage, adapter: BotAdapter, text: str):
        """解析并分发元命令"""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        # 去掉 Telegram 的 @bot_username 后缀
        if "@" in cmd:
            cmd = cmd.split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            # 项目管理
            "/projects": self._cmd_projects,
            "/cd": self._cmd_cd,
            "/addproject": self._cmd_addproject,
            "/newproject": self._cmd_newproject,
            "/clone": self._cmd_clone,
            "/repos": self._cmd_repos,
            "/rmproject": self._cmd_rmproject,
            # 会话管理
            "/status": self._cmd_status,
            "/new": self._cmd_new,
            "/model": self._cmd_model,
            "/abort": self._cmd_abort,
            "/help": self._cmd_help,
            # 输出查看
            "/detail": self._cmd_detail,
            "/start": self._cmd_start,
            # Git
            "/diff": self._cmd_diff,
            "/commit": self._cmd_commit,
            "/push": self._cmd_push,
            "/pull": self._cmd_pull,
            "/branch": self._cmd_branch,
            "/log": self._cmd_log,
            "/gs": self._cmd_gs,
            # 文件
            "/cat": self._cmd_cat,
            "/tree": self._cmd_tree,
            # 记忆系统
            "/memory": self._cmd_memory,
            "/search": self._cmd_search,
        }

        handler = handlers.get(cmd)
        if handler:
            await handler(msg, adapter, arg)
        else:
            await self._reply(adapter, msg.chat_id, f"未知命令: {cmd}\n输入 /help 查看可用命令")

    # ========== 项目管理命令 ==========

    async def _cmd_projects(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """列出所有项目"""
        projects = self.project_mgr.list_projects()
        session = self.session_mgr.get_session(msg.chat_id)

        if not projects:
            await self._reply(adapter, msg.chat_id,
                "暂无项目\n\n"
                "/newproject <名称> — 新建项目\n"
                "/addproject <名称> <路径> — 注册已有目录"
            )
            return

        lines = ["项目列表:\n"]
        for name, info in projects.items():
            marker = " <-- 当前" if name == session.current_project else ""
            desc = info.get("description", "")
            desc_str = f" ({desc})" if desc else ""
            lines.append(f"  {name}{desc_str}{marker}")

        lines.append(f"\n当前项目: {session.current_project or '未选择'}")
        lines.append("用 /cd <名称> 切换项目")
        await self._reply(adapter, msg.chat_id, "\n".join(lines))

    async def _cmd_cd(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """切换项目"""
        if not arg:
            await self._reply(adapter, msg.chat_id, "用法: /cd <项目名>")
            return

        proj = self.project_mgr.get_project(arg)
        if not proj:
            available = ", ".join(self.project_mgr.list_projects().keys())
            await self._reply(adapter, msg.chat_id,
                f"项目 '{arg}' 不存在\n可用项目: {available or '无'}")
            return

        self.session_mgr.set_project(msg.chat_id, arg, proj["path"])
        await self._reply(adapter, msg.chat_id,
            f"已切换到: {arg}\n路径: {proj['path']}")

    async def _cmd_addproject(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """注册已有目录为项目"""
        parts = arg.split(maxsplit=2)
        if len(parts) < 2:
            await self._reply(adapter, msg.chat_id,
                "用法: /addproject <名称> <路径> [描述]")
            return

        name = parts[0]
        path = parts[1]
        desc = parts[2] if len(parts) > 2 else ""
        result = self.project_mgr.add_project(name, path, desc)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_newproject(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """从零新建项目"""
        parts = arg.split(maxsplit=1)
        if not parts:
            await self._reply(adapter, msg.chat_id,
                "用法: /newproject <名称> [描述]")
            return

        name = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        result = await self.project_mgr.new_project(name, desc)
        await self._reply(adapter, msg.chat_id, result)

        # 自动切换到新项目
        proj = self.project_mgr.get_project(name)
        if proj:
            self.session_mgr.set_project(msg.chat_id, name, proj["path"])

    async def _cmd_clone(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """从 GitHub 克隆仓库"""
        parts = arg.split(maxsplit=1)
        if not parts:
            await self._reply(adapter, msg.chat_id,
                "用法: /clone <owner/repo> [本地名称]\n"
                "示例: /clone dapingzui/myapp\n"
                "查看你的仓库: /repos")
            return

        repo = parts[0]
        local_name = parts[1] if len(parts) > 1 else ""
        await self._reply(adapter, msg.chat_id, f"⏳ 正在克隆 {repo}...")
        result = await self.project_mgr.clone_project(repo, local_name)
        await self._reply(adapter, msg.chat_id, result)

        # 自动切换到克隆的项目
        name = local_name or repo.rstrip("/").split("/")[-1].removesuffix(".git")
        proj = self.project_mgr.get_project(name)
        if proj:
            self.session_mgr.set_project(msg.chat_id, name, proj["path"])

    async def _cmd_repos(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """列出 GitHub 仓库"""
        limit = 20
        if arg.isdigit():
            limit = min(int(arg), 50)
        result = await self.project_mgr.list_github_repos(limit)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_rmproject(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """取消项目注册"""
        if not arg:
            await self._reply(adapter, msg.chat_id,
                "用法: /rmproject <名称>")
            return

        result = self.project_mgr.remove_project(arg)
        await self._reply(adapter, msg.chat_id, result)

    # ========== 会话管理命令 ==========

    async def _cmd_status(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """查看当前状态"""
        session = self.session_mgr.get_session(msg.chat_id)
        lines = [
            "当前状态:\n",
            f"  项目: {session.current_project or '未选择'}",
            f"  路径: {session.current_project_path or 'N/A'}",
            f"  会话: {'有历史' if session.has_history else '新会话'}",
            f"  模型: {session.model or '默认'}",
        ]
        if session.claude_session_id:
            lines.append(f"  会话ID: {session.claude_session_id[:16]}...")
        await self._reply(adapter, msg.chat_id, "\n".join(lines))

    async def _cmd_new(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """新建 Claude Code 会话"""
        self.session_mgr.new_session(msg.chat_id)
        await self._reply(adapter, msg.chat_id, "已新建会话（项目不变）")

    async def _cmd_model(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """切换模型"""
        session = self.session_mgr.get_session(msg.chat_id)

        if not arg:
            await self._reply(adapter, msg.chat_id,
                f"当前模型: {session.model or '默认'}\n\n"
                "可用模型:\n"
                "  /model sonnet — Claude Sonnet 4.5（推荐，性价比高）\n"
                "  /model opus — Claude Opus 4.6（最强，贵）\n"
                "  /model haiku — Claude Haiku 4.5（最快最便宜）\n"
                "  /model <完整模型ID> — 自定义模型")
            return

        # 快捷别名
        aliases = {
            "sonnet": "claude-sonnet-4-5-20250929",
            "opus": "claude-opus-4-6",
            "haiku": "claude-haiku-4-5-20251001",
        }
        model_id = aliases.get(arg.lower(), arg)
        session.model = model_id
        await self._reply(adapter, msg.chat_id, f"模型已切换: {model_id}")

    async def _cmd_abort(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """终止当前执行"""
        aborted = await self.executor.abort()
        if aborted:
            await self._reply(adapter, msg.chat_id, "已终止执行")
        else:
            await self._reply(adapter, msg.chat_id, "当前没有在执行的任务")

    async def _cmd_help(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """显示帮助"""
        await self._reply(adapter, msg.chat_id, HELP_TEXT)

    async def _cmd_start(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """Telegram /start 命令"""
        await self._reply(adapter, msg.chat_id,
            "724code — 远程 Claude Code 遥控器\n\n"
            "直接发消息 = 发给 Claude Code\n"
            "输入 /help 查看所有命令")

    # ========== 输出查看命令 ==========

    async def _cmd_detail(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """查看上次完整输出"""
        full = self._last_full_output.get(msg.chat_id, "")
        if not full:
            await self._reply(adapter, msg.chat_id, "没有可查看的输出")
            return
        await self._reply(adapter, msg.chat_id, full[:4000])
        if len(full) > 4000:
            await self._reply(adapter, msg.chat_id, full[4000:8000])

    # ========== Claude Code 执行 ==========

    async def _handle_claude(self, msg: IncomingMessage, adapter: BotAdapter, text: str):
        """将文本发送给 Claude Code 执行"""
        session = self.session_mgr.get_session(msg.chat_id)

        # 确定工作目录
        cwd = session.current_project_path
        if not cwd:
            await self._reply(adapter, msg.chat_id,
                "请先选择项目:\n"
                "/projects — 查看项目列表\n"
                "/cd <名称> — 切换项目\n"
                "/newproject <名称> — 新建项目")
            return

        # 发送"执行中"提示
        await adapter.send_typing_action(msg.chat_id)
        project_label = session.current_project or "default"
        await self._reply(adapter, msg.chat_id, f"执行中... [{project_label}]")

        # 获取项目级记忆存储
        store = self.memory_mgr.get_store(cwd)

        # 新会话第一条消息注入记忆上下文，续接会话不注入（避免浪费 token）
        if session.has_history:
            prompt = text
        else:
            prompt = self.injector.build_augmented_prompt(store, project_label, text)

        # 调用 Claude Code
        result = await self.executor.run(
            prompt=prompt,
            cwd=cwd,
            session_id=session.claude_session_id,
            use_continue=session.has_history,
            model=session.model,
        )

        # 保存状态
        self._last_full_output[msg.chat_id] = result.full_output
        self.session_mgr.update_claude_session(msg.chat_id, result.session_id)

        # 保存记忆（每次都存）
        try:
            store.save_entry(
                project=project_label,
                user_msg=text,
                summary=result.summary,
                files_changed=result.files_changed,
                session_id=result.session_id,
                cost_usd=result.cost_usd,
                model=session.model,
            )
        except Exception as e:
            logger.warning(f"保存记忆失败: {e}")

        # 返回结果
        reply = result.formatted_output or "（无输出）"
        await self._reply(adapter, msg.chat_id, reply)

    # ========== Git 命令 ==========

    def _get_cwd(self, chat_id: str):
        """获取当前项目路径，未选项目返回 None"""
        session = self.session_mgr.get_session(chat_id)
        return session.current_project_path or None

    async def _require_project(self, adapter: BotAdapter, chat_id: str):
        """要求已选项目，返回 cwd 或 None（并提示用户）"""
        cwd = self._get_cwd(chat_id)
        if not cwd:
            await self._reply(adapter, chat_id,
                "请先选择项目: /projects 查看, /cd <名称> 切换")
        return cwd

    async def _cmd_diff(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.diff(cwd, ref=arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_commit(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.commit(cwd, message=arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_push(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.push(cwd, branch=arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_pull(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.pull(cwd)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_branch(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.branch(cwd, name=arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_log(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.log(cwd, count=arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_gs(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.git.status(cwd)
        await self._reply(adapter, msg.chat_id, result)

    # ========== 文件命令 ==========

    async def _cmd_cat(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.file_mgr.cat_file(cwd, arg)
        await self._reply(adapter, msg.chat_id, result)

    async def _cmd_tree(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return
        result = await self.file_mgr.tree(cwd, arg)
        await self._reply(adapter, msg.chat_id, result)

    # ========== 记忆命令 ==========

    async def _cmd_memory(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """查看记忆统计或最近记录"""
        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return

        session = self.session_mgr.get_session(msg.chat_id)
        project = session.current_project or ""
        store = self.memory_mgr.get_store(cwd)

        if arg == "stats":
            stats = store.get_stats(project)
            await self._reply(adapter, msg.chat_id,
                f"记忆统计 [{project}]:\n"
                f"  记录数: {stats['count']}\n"
                f"  累计花费: ${stats['total_cost']}")
            return

        # 默认：显示最近记录
        recent = store.get_recent(project, n=10)
        if not recent:
            await self._reply(adapter, msg.chat_id, "暂无记忆记录\n发消息给 Claude Code 后会自动记录")
            return

        lines = [f"最近记录 [{project}]:\n"]
        for e in recent[-10:]:
            time_str = e["time"][:16]
            task = e["task"][:60]
            summary = e["summary"][:80]
            lines.append(f"[{time_str}] {task}")
            lines.append(f"  -> {summary}\n")

        lines.append("/memory stats — 查看统计")
        lines.append("/search <关键词> — 搜索记忆")
        await self._reply(adapter, msg.chat_id, "\n".join(lines))

    async def _cmd_search(self, msg: IncomingMessage, adapter: BotAdapter, arg: str):
        """搜索记忆"""
        if not arg:
            await self._reply(adapter, msg.chat_id, "用法: /search <关键词>")
            return

        cwd = await self._require_project(adapter, msg.chat_id)
        if not cwd:
            return

        session = self.session_mgr.get_session(msg.chat_id)
        project = session.current_project or ""
        store = self.memory_mgr.get_store(cwd)

        results = store.search(arg, project=project, limit=10)
        if not results:
            await self._reply(adapter, msg.chat_id, f"未找到 '{arg}' 相关记录")
            return

        lines = [f"搜索 '{arg}' 结果:\n"]
        for r in results:
            lines.append(f"[{r['time'][:16]}] {r['task'][:60]}")
            lines.append(f"  -> {r['summary'][:80]}\n")

        await self._reply(adapter, msg.chat_id, "\n".join(lines))

    # ========== 工具方法 ==========

    async def _reply(self, adapter: BotAdapter, chat_id: str, text: str):
        await adapter.send_message(OutgoingMessage(chat_id=chat_id, text=text))


HELP_TEXT = """724code 命令列表:

项目管理:
  /projects — 列出所有项目
  /cd <名称> — 切换项目
  /newproject <名称> — 新建项目（+GitHub）
  /clone <owner/repo> — 从 GitHub 克隆
  /repos [数量] — 列出 GitHub 仓库
  /addproject <名称> <路径> — 注册已有目录
  /rmproject <名称> — 取消注册

会话管理:
  /status — 当前状态
  /new — 新建会话
  /model [sonnet|opus|haiku] — 切换模型
  /abort — 终止执行

Git:
  /diff [ref] — 查看变更
  /commit [消息] — 提交
  /push [分支] — 推送
  /pull — 拉取
  /branch [名称] — 分支管理
  /log [数量] — 提交记录
  /gs — git status

文件:
  /cat <文件> [行范围] — 查看文件
  /tree [路径] [深度] — 目录结构

记忆:
  /memory — 最近记录
  /search <关键词> — 搜索记忆
  /detail — 上次完整输出

直接发文本 = 发给 Claude Code 执行"""
