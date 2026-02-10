"""消息平台适配层 — 抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class IncomingMessage:
    """统一的入站消息格式"""
    platform: str          # "telegram" | "feishu"
    user_id: str
    chat_id: str
    text: str
    message_id: str = ""
    reply_to_msg_id: Optional[str] = None


@dataclass(frozen=True)
class OutgoingMessage:
    """统一的出站消息格式"""
    chat_id: str
    text: str
    parse_mode: str = "Markdown"
    reply_to_msg_id: Optional[str] = None


class BotAdapter(ABC):
    """消息平台适配器基类"""

    @abstractmethod
    async def start(self):
        """启动 Bot"""

    @abstractmethod
    async def stop(self):
        """停止 Bot"""

    @abstractmethod
    async def send_message(self, msg: OutgoingMessage):
        """发送消息"""

    @abstractmethod
    async def send_typing_action(self, chat_id: str):
        """发送"正在输入"状态"""
