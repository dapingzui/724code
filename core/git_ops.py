"""Git 操作封装 — /diff, /commit, /push, /pull, /branch, /log"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# 忽略的目录（不在 tree 中显示）
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".next", "venv", ".venv", "dist", ".mypy_cache"}


class GitOps:
    def __init__(self, config: dict):
        self.commit_prefix = config.get("commit_prefix", "[bot]")
        self.protected_branches = config.get("protected_branches", ["main", "production"])
        self.user_name = config.get("user_name", "")
        self.user_email = config.get("user_email", "")

    def _git_cmd(self, *args) -> list[str]:
        """构建 git 命令，注入 user 配置"""
        cmd = ["git"]
        if self.user_name:
            cmd.extend(["-c", f"user.name={self.user_name}"])
        if self.user_email:
            cmd.extend(["-c", f"user.email={self.user_email}"])
        cmd.extend(args)
        return cmd

    async def _run_git(self, cwd: str, *args) -> tuple[str, str, int]:
        """执行 git 命令，返回 (stdout, stderr, returncode)"""
        cmd = self._git_cmd(*args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            proc.returncode,
        )

    async def diff(self, cwd: str, ref: str = "") -> str:
        """git diff：先 stat 概览，再详细 diff"""
        args_stat = ["diff", "--stat"]
        args_full = ["diff"]
        if ref:
            args_stat.append(ref)
            args_full.append(ref)

        stat_out, _, _ = await self._run_git(cwd, *args_stat)
        diff_out, _, _ = await self._run_git(cwd, *args_full)

        if not stat_out.strip() and not diff_out.strip():
            return "没有未提交的变更"

        result = f"变更统计:\n{stat_out}"

        if diff_out:
            if len(diff_out) > 3000:
                diff_out = diff_out[:3000] + "\n... diff 过长，已截断"
            result += f"\n{diff_out}"

        return result

    async def commit(self, cwd: str, message: str = "") -> str:
        """git add -A + commit"""
        await self._run_git(cwd, "add", "-A")

        status_out, _, _ = await self._run_git(cwd, "status", "--porcelain")
        if not status_out.strip():
            return "没有需要提交的变更"

        if not message:
            stat_out, _, _ = await self._run_git(cwd, "diff", "--cached", "--stat")
            lines = stat_out.strip().split("\n")
            message = f"Update: {lines[-1].strip()}" if lines else "Update"

        full_message = f"{self.commit_prefix} {message}"
        out, err, code = await self._run_git(cwd, "commit", "-m", full_message)
        if code != 0:
            return f"Commit 失败:\n{err}"

        return f"已提交\n{out}"

    async def push(self, cwd: str, branch: str = "") -> str:
        """git push"""
        if not branch:
            out, _, _ = await self._run_git(cwd, "branch", "--show-current")
            branch = out.strip()

        if not branch:
            return "无法确定当前分支"

        if branch in self.protected_branches:
            return (
                f"'{branch}' 是保护分支，禁止直接 push\n"
                f"请先切换到开发分支: /branch <分支名>"
            )

        out, err, code = await self._run_git(cwd, "push", "-u", "origin", branch)
        if code != 0:
            return f"Push 失败:\n{err}"

        return f"已推送到 origin/{branch}"

    async def pull(self, cwd: str) -> str:
        """git pull"""
        out, err, code = await self._run_git(cwd, "pull")
        if code != 0:
            return f"Pull 失败:\n{err}"

        return f"Pull 完成\n{out}"

    async def branch(self, cwd: str, name: str = "") -> str:
        """查看/切换/创建分支"""
        if not name:
            out, _, _ = await self._run_git(cwd, "branch", "-a")
            return f"分支列表:\n{out}" if out.strip() else "暂无分支"

        out, err, code = await self._run_git(cwd, "checkout", name)
        if code != 0:
            out, err, code = await self._run_git(cwd, "checkout", "-b", name)
            if code != 0:
                return f"切换分支失败:\n{err}"
            return f"已创建并切换到新分支: {name}"

        return f"已切换到分支: {name}"

    async def log(self, cwd: str, count: str = "") -> str:
        """查看最近 commit 记录"""
        n = int(count) if count.strip().isdigit() else 10
        n = min(n, 30)
        out, _, code = await self._run_git(
            cwd, "log", f"-{n}", "--oneline", "--graph", "--decorate"
        )
        if code != 0 or not out.strip():
            return "暂无 commit 记录"

        return f"最近 {n} 条 commit:\n{out}"

    async def status(self, cwd: str) -> str:
        """git status 简洁版"""
        out, _, code = await self._run_git(cwd, "status", "--short")
        if code != 0:
            return "无法获取 git status"

        if not out.strip():
            return "工作区干净，没有变更"

        return f"Git 状态:\n{out}"
