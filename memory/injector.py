"""上下文注入 — 将记忆拼接到发给 Claude Code 的 prompt 中"""

import logging
from memory.store import MemoryStore

logger = logging.getLogger(__name__)


class ContextInjector:
    def __init__(self, config: dict):
        self.recent_n = config.get("recent_entries", 15)
        self.max_tokens = config.get("max_context_tokens", 4000)

    def build_augmented_prompt(self, store: MemoryStore, project: str, user_message: str) -> str:
        """将记忆上下文注入到用户 prompt 中（仅新会话第一条消息调用）"""
        recent = store.get_recent(project, n=self.recent_n)

        if not recent:
            return user_message

        # 构建上下文
        recent_text = "\n".join([
            f"- [{e['time'][:16]}] {e['task'][:80]} -> {e['summary'][:100]}"
            for e in recent
        ])

        context = f"## 近期工作记录（最近 {len(recent)} 条）\n{recent_text}"

        # Token 预算检查（粗略：1 中文字 ≈ 2 tokens）
        estimated_tokens = len(context) * 2
        if estimated_tokens > self.max_tokens:
            max_chars = self.max_tokens // 2
            context = context[:max_chars] + "\n... (部分记录已截断)"

        return f"""{context}

---

## 当前任务
{user_message}

请基于上面的项目背景执行当前任务。如果近期记录中有相关上下文，请参考。"""
