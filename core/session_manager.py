"""会话管理器 — 管理每个 chat 的项目、会话状态"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """单个 chat 的会话状态"""
    chat_id: str
    current_project: str = ""           # 项目名
    current_project_path: str = ""      # 项目路径
    claude_session_id: str = ""         # Claude Code 会话 ID（用于 --resume）
    has_history: bool = False           # 是否有历史对话（用于 --continue）
    model: str = ""

    def reset_claude_session(self):
        """重置 Claude Code 会话（保留项目）"""
        self.claude_session_id = ""
        self.has_history = False


class SessionManager:
    def __init__(self, default_model: str = ""):
        self.sessions: dict[str, Session] = {}
        self.default_model = default_model

    def get_session(self, chat_id: str) -> Session:
        """获取或创建会话"""
        if chat_id not in self.sessions:
            self.sessions[chat_id] = Session(
                chat_id=chat_id,
                model=self.default_model,
            )
        return self.sessions[chat_id]

    def set_project(self, chat_id: str, name: str, path: str):
        """切换项目，同时重置 Claude 会话"""
        session = self.get_session(chat_id)
        session.current_project = name
        session.current_project_path = path
        session.reset_claude_session()
        logger.info(f"[{chat_id}] 切换项目: {name} -> {path}")

    def new_session(self, chat_id: str):
        """新建 Claude Code 会话（同项目）"""
        session = self.get_session(chat_id)
        session.reset_claude_session()
        logger.info(f"[{chat_id}] 新建会话")

    def update_claude_session(self, chat_id: str, session_id: str):
        """更新 Claude Code 会话 ID（执行成功后调用）"""
        session = self.get_session(chat_id)
        if session_id:
            session.claude_session_id = session_id
            session.has_history = True
