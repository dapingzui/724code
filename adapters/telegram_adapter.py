"""Telegram Bot 适配器 — Polling 模式，支持代理"""

import logging
from typing import Callable, Awaitable

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

from adapters.base import BotAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


class TelegramAdapter(BotAdapter):
    def __init__(self, config: dict, message_handler: Callable[[IncomingMessage, "TelegramAdapter"], Awaitable[None]]):
        self.config = config
        self.message_handler = message_handler
        self.allowed_users: set[int] = set(config.get("allowed_users", []))

        # 构建 Application（支持代理）
        proxy_url = config.get("proxy_url")
        builder = ApplicationBuilder().token(config["token"])
        if proxy_url:
            builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
            logger.info(f"Telegram Bot 使用代理: {proxy_url}")
        self.app = builder.build()

        # 注册处理器：所有文本消息（命令 + 普通文本）统一入口
        self.app.add_handler(MessageHandler(
            filters.TEXT,
            self._on_message,
        ))

    def _check_user(self, user_id: int) -> bool:
        """白名单检查，空白名单则允许所有人"""
        if not self.allowed_users:
            return True
        return user_id in self.allowed_users

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理普通文本消息"""
        if not update.effective_user or not update.message:
            return
        if not self._check_user(update.effective_user.id):
            logger.warning(f"非白名单用户: {update.effective_user.id}")
            return

        msg = IncomingMessage(
            platform="telegram",
            user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            text=update.message.text,
            message_id=str(update.message.message_id),
        )
        await self.message_handler(msg, self)

    async def start(self):
        """启动 Polling"""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Bot 已启动 (Polling 模式)")

    async def stop(self):
        """停止 Bot"""
        if self.app.updater.running:
            await self.app.updater.stop()
        if self.app.running:
            await self.app.stop()
        await self.app.shutdown()
        logger.info("Telegram Bot 已停止")

    async def send_message(self, msg: OutgoingMessage):
        """发送消息，长消息自动分段"""
        text = msg.text
        max_len = self.config.get("max_message_length", 4000)
        chunks = _split_message(text, max_len)

        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i + 1}/{len(chunks)}]\n{chunk}"
            try:
                await self.app.bot.send_message(
                    chat_id=msg.chat_id,
                    text=chunk,
                    parse_mode=None,  # 先用纯文本，避免 Markdown 解析出错
                )
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                # parse_mode 出错时降级为纯文本重试
                try:
                    await self.app.bot.send_message(
                        chat_id=msg.chat_id,
                        text=chunk,
                    )
                except Exception as e2:
                    logger.error(f"降级发送也失败: {e2}")

    async def send_typing_action(self, chat_id: str):
        """发送"正在输入"状态"""
        try:
            await self.app.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except Exception as e:
            logger.debug(f"发送 typing 状态失败: {e}")


def _split_message(text: str, max_len: int) -> list[str]:
    """智能分割长消息：优先在代码块边界或换行处切"""
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
