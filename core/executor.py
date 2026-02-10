"""Claude Code CLI 执行器

通过 asyncio.subprocess 调用 claude CLI，
解析 JSON 输出，支持会话续接和代理。
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field

from core.output_processor import compress_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """Claude Code 执行结果"""
    success: bool
    session_id: str
    full_output: str          # 原始完整输出
    summary: str              # 简短摘要（用于记忆系统）
    formatted_output: str     # 适合手机阅读的格式化输出
    files_changed: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str = ""


class ClaudeExecutor:
    def __init__(self, config: dict, proxy_url: str = ""):
        self.config = config
        self.proxy_url = proxy_url
        self.current_process: asyncio.subprocess.Process | None = None

    def _build_env(self) -> dict[str, str]:
        """构建子进程环境变量，注入代理"""
        env = os.environ.copy()
        if self.proxy_url:
            env["HTTPS_PROXY"] = self.proxy_url
            env["HTTP_PROXY"] = self.proxy_url
            env["https_proxy"] = self.proxy_url
            env["http_proxy"] = self.proxy_url
        return env

    def _build_command(
        self,
        prompt: str,
        cwd: str,
        session_id: str = "",
        use_continue: bool = False,
        model: str = "",
    ) -> list[str]:
        """构建 claude CLI 命令"""
        active_model = model or self.config.get("model", "claude-sonnet-4-20250514")
        cmd = [
            self.config.get("command", "claude"),
            "-p", prompt,
            "--output-format", "json",
            "--model", active_model,
            "--max-turns", str(self.config.get("max_turns", 25)),
        ]

        # 会话续接
        if session_id:
            cmd.extend(["--resume", session_id])
        elif use_continue:
            cmd.append("--continue")

        # 工具权限
        allowed_tools = self.config.get("allowed_tools", [])
        if allowed_tools:
            for tool in allowed_tools:
                cmd.extend(["--allowedTools", tool])

        return cmd

    async def run(
        self,
        prompt: str,
        cwd: str,
        session_id: str = "",
        use_continue: bool = False,
        model: str = "",
    ) -> ExecutionResult:
        """执行 Claude Code CLI 命令"""
        cmd = self._build_command(prompt, cwd, session_id, use_continue, model)
        env = self._build_env()
        timeout = self.config.get("timeout", 300)

        logger.info(f"执行 Claude Code: cwd={cwd}, prompt={prompt[:80]}...")
        logger.debug(f"命令: {' '.join(cmd)}")

        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self.current_process.communicate(),
                timeout=timeout,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return_code = self.current_process.returncode

            if stderr:
                logger.debug(f"stderr: {stderr[:500]}")

            return self._parse_output(stdout, stderr, return_code)

        except asyncio.TimeoutError:
            if self.current_process:
                self.current_process.terminate()
                try:
                    await asyncio.wait_for(self.current_process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.current_process.kill()

            return ExecutionResult(
                success=False,
                session_id=session_id,
                full_output="",
                summary="执行超时",
                formatted_output=f"执行超时（{timeout}秒），请拆分为更小的任务",
                error="timeout",
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                session_id="",
                full_output="",
                summary="claude 命令未找到",
                formatted_output="claude CLI 未安装或不在 PATH 中\n请先安装: npm install -g @anthropic-ai/claude-code",
                error="command_not_found",
            )
        except Exception as e:
            logger.error(f"执行异常: {e}")
            return ExecutionResult(
                success=False,
                session_id=session_id,
                full_output="",
                summary=f"执行异常: {str(e)[:100]}",
                formatted_output=f"执行异常: {e}",
                error=str(e),
            )
        finally:
            self.current_process = None

    def _parse_output(self, stdout: str, stderr: str, return_code: int) -> ExecutionResult:
        """解析 Claude Code 的 JSON 输出"""
        try:
            data = json.loads(stdout)
            result_text = data.get("result", "")
            session_id = data.get("session_id", "")
            cost = data.get("cost_usd", 0) or data.get("total_cost_usd", 0)
            duration = data.get("duration_ms", 0)
            is_error = data.get("is_error", False)

            formatted = compress_output(
                result_text, cost=cost, duration_ms=duration, is_error=is_error
            )

            return ExecutionResult(
                success=not is_error,
                session_id=session_id,
                full_output=result_text,
                summary=self._generate_summary(result_text),
                formatted_output=formatted,
                cost_usd=cost,
                duration_ms=duration,
                error="" if not is_error else result_text[:200],
            )
        except json.JSONDecodeError:
            # 非 JSON 输出（可能是错误信息）
            output = stdout.strip() or stderr.strip()
            is_ok = return_code == 0

            return ExecutionResult(
                success=is_ok,
                session_id="",
                full_output=output,
                summary=output[:200],
                formatted_output=output[:3500] if is_ok else f"错误:\n{output[:3500]}",
                error="" if is_ok else output[:200],
            )

    def _generate_summary(self, text: str) -> str:
        """生成简短摘要（用于记忆系统）"""
        lines = text.strip().split("\n")
        summary_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                summary_lines.append(stripped)
            if len(" ".join(summary_lines)) > 200:
                break
        return " ".join(summary_lines)[:200]

    async def abort(self) -> bool:
        """终止当前执行"""
        if self.current_process:
            self.current_process.terminate()
            return True
        return False
