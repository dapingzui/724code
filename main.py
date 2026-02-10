"""724code — 入口文件

通过 Telegram Bot 远程操控 Claude Code CLI。
Stage 5: Git 操作 + 文件查看 + GitHub 集成
"""

import asyncio
import logging
import os
import shutil
import signal
import sys

import yaml

from adapters.telegram_adapter import TelegramAdapter
from core.executor import ClaudeExecutor
from core.router import Router
from core.session_manager import SessionManager
from core.project_manager import ProjectManager
from core.git_ops import GitOps
from core.file_manager import FileManager
from memory.store import ProjectMemoryManager
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


def load_config(path: str = None) -> dict:
    """加载配置文件"""
    if path is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "config.yaml")

    if not os.path.exists(path):
        logger.error(f"配置文件不存在: {path}")
        logger.error("请复制 config.example.yaml 为 config.yaml 并填入实际值")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    token = config.get("telegram", {}).get("token", "")
    if not token or "YOUR_" in token:
        logger.error("请在 config.yaml 中填入 Telegram Bot Token")
        sys.exit(1)

    return config


def build_telegram_config(config: dict) -> dict:
    """从全局配置中提取 Telegram 相关配置"""
    tg = config.get("telegram", {})
    proxy = config.get("proxy", {})
    output = config.get("output", {})

    result = {
        "token": tg["token"],
        "allowed_users": tg.get("allowed_users", []),
        "max_message_length": output.get("max_message_length", 4000),
    }

    proxy_url = proxy.get("url", "")
    if proxy_url:
        result["proxy_url"] = proxy_url

    return result


def check_prerequisites():
    """检查必备工具是否已安装，缺失则给出安装指引"""
    checks = {
        "git": {
            "cmd": "git",
            "help": "安装 Git: https://git-scm.com/downloads",
            "required": True,
        },
        "gh": {
            "cmd": "gh",
            "help": "安装 GitHub CLI: https://cli.github.com/\n  然后运行: gh auth login",
            "required": False,
        },
        "claude": {
            "cmd": "claude",
            "help": "安装 Claude Code: npm install -g @anthropic-ai/claude-code",
            "required": True,
        },
    }

    missing_required = []
    missing_optional = []

    for name, info in checks.items():
        path = shutil.which(info["cmd"])
        if path:
            logger.info(f"✅ {name}: {path}")
        elif info["required"]:
            logger.error(f"❌ {name} 未安装（必需）")
            logger.error(f"   {info['help']}")
            missing_required.append(name)
        else:
            logger.warning(f"⚠️ {name} 未安装（可选，部分功能不可用）")
            logger.warning(f"   {info['help']}")
            missing_optional.append(name)

    if missing_required:
        logger.error(f"缺少必备工具: {', '.join(missing_required)}，无法启动")
        sys.exit(1)

    return missing_optional


async def main():
    setup_logging("INFO")
    logger.info("724code 启动中...")

    # 环境检查
    missing = check_prerequisites()
    if missing:
        logger.warning(f"可选工具缺失: {', '.join(missing)}（/clone, /newproject GitHub 功能不可用）")

    config = load_config()
    tg_config = build_telegram_config(config)
    proxy_url = config.get("proxy", {}).get("url", "")

    # 基准目录（用于解析相对路径）
    base_dir = os.path.dirname(os.path.abspath(__file__))

    def resolve_path(p: str) -> str:
        """将相对路径解析为基于项目根目录的绝对路径"""
        if not os.path.isabs(p):
            return os.path.join(base_dir, p)
        return p

    # 初始化各模块
    executor = ClaudeExecutor(
        config=config.get("claude", {}),
        proxy_url=proxy_url,
    )
    session_mgr = SessionManager(
        default_model=config.get("claude", {}).get("model", "claude-sonnet-4-20250514"),
    )

    # 解析 projects_file 的相对路径
    projects_config = dict(config.get("projects", {}))
    projects_file = projects_config.get("projects_file", "./data/projects.yaml")
    projects_config["projects_file"] = resolve_path(projects_file)
    project_mgr = ProjectManager(projects_config)

    # 记忆系统（按项目独立存储）
    memory_mgr = ProjectMemoryManager()

    # Git + 文件管理
    git_ops = GitOps(config.get("git", {}))
    file_mgr = FileManager(config.get("files", {}))

    router = Router(
        executor, session_mgr, project_mgr,
        memory_mgr, config.get("memory", {}),
        git_ops, file_mgr,
    )
    adapter = TelegramAdapter(tg_config, router.handle)

    # 优雅关闭
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("收到停止信号，正在关闭...")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        pass

    await adapter.start()
    logger.info("724code 已就绪，等待消息...")

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt，正在关闭...")
    finally:
        await adapter.stop()

    logger.info("724code 已停止")


if __name__ == "__main__":
    asyncio.run(main())
