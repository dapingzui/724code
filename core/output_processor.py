"""输出处理器 — 将 Claude Code 输出压缩为手机友好格式"""

import logging
import re

logger = logging.getLogger(__name__)


def compress_output(
    text: str,
    max_length: int = 3500,
    cost: float = 0,
    duration_ms: int = 0,
    is_error: bool = False,
) -> str:
    """
    将 Claude Code 输出压缩为适合 Telegram 的格式。

    策略：
    1. 短输出（< max_length）直接返回 + 状态栏
    2. 长输出：保留开头结论 + 文件变更摘要 + 末尾结论，中间截断
    """
    lines = []

    # 状态栏
    status = "出错" if is_error else "完成"
    meta_parts = [status]
    if duration_ms:
        meta_parts.append(f"{duration_ms / 1000:.1f}s")
    if cost:
        meta_parts.append(f"${cost:.4f}")
    lines.append(" | ".join(meta_parts))

    if not text:
        return "\n".join(lines)

    # 内容预算（减去状态栏）
    budget = max_length - len(lines[0]) - 50

    if len(text) <= budget:
        lines.append("")
        lines.append(text)
        return "\n".join(lines)

    # 长输出：头 + 尾 + 截断提示
    head_budget = int(budget * 0.6)
    tail_budget = int(budget * 0.3)

    head = text[:head_budget]
    tail = text[-tail_budget:]

    # 在换行处切割，避免截断代码行
    head_cut = head.rfind("\n")
    if head_cut > head_budget * 0.5:
        head = head[:head_cut]

    tail_cut = tail.find("\n")
    if tail_cut > 0 and tail_cut < tail_budget * 0.3:
        tail = tail[tail_cut + 1:]

    omitted = len(text) - len(head) - len(tail)
    lines.append("")
    lines.append(head)
    lines.append(f"\n... 省略 {omitted} 字符，/detail 查看完整输出 ...\n")
    lines.append(tail)

    return "\n".join(lines)
