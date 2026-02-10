"""文件管理器 — /cat 查看文件, /tree 查看目录结构"""

import logging
import os

logger = logging.getLogger(__name__)

# tree 时忽略的目录
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".next", "venv", ".venv", "dist", ".mypy_cache", ".pytest_cache"}


class FileManager:
    def __init__(self, config: dict):
        self.max_cat_lines = config.get("max_cat_lines", 200)
        self.max_file_size = config.get("max_file_size_mb", 10) * 1024 * 1024

    async def cat_file(self, project_path: str, file_arg: str) -> str:
        """
        查看文件内容。

        用法:
          /cat src/main.py          → 完整文件（限制行数）
          /cat src/main.py 20-50    → 第 20-50 行
          /cat src/main.py 100      → 从第 100 行开始
        """
        if not file_arg.strip():
            return "用法: /cat <文件路径> [行范围]\n示例: /cat main.py 10-30"

        parts = file_arg.strip().split()
        filepath = parts[0]
        line_range = parts[1] if len(parts) > 1 else None

        full_path = os.path.join(project_path, filepath)

        if not _is_within_project(project_path, full_path):
            return "禁止访问项目目录外的文件"

        if not os.path.isfile(full_path):
            return f"文件不存在: {filepath}"

        if os.path.getsize(full_path) > self.max_file_size:
            size_mb = os.path.getsize(full_path) / 1024 / 1024
            return f"文件过大: {size_mb:.1f}MB (上限 {self.max_file_size // 1024 // 1024}MB)"

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return f"读取失败: {e}"

        total_lines = len(lines)

        # 解析行范围
        start, end = 1, min(total_lines, self.max_cat_lines)
        if line_range:
            try:
                if "-" in line_range:
                    s, e = line_range.split("-", 1)
                    start = max(1, int(s))
                    end = min(total_lines, int(e))
                else:
                    start = max(1, int(line_range))
                    end = min(total_lines, start + self.max_cat_lines - 1)
            except ValueError:
                return f"行范围格式错误: {line_range}\n示例: 10-30 或 50"

        selected = lines[start - 1:end]

        # 带行号输出
        header = f"{filepath} ({total_lines} 行, 显示 {start}-{end})\n"
        content = ""
        for i, line in enumerate(selected, start=start):
            content += f"{i:4d} | {line}"

        if end < total_lines:
            content += f"\n... 还有 {total_lines - end} 行 (/cat {filepath} {end + 1})"

        return header + content

    async def tree(self, project_path: str, arg: str) -> str:
        """
        查看目录结构（纯 Python 实现，跨平台）。

        用法:
          /tree              → 项目根目录，深度 2
          /tree src          → 指定子目录
          /tree src 4        → 指定深度
        """
        parts = arg.strip().split() if arg.strip() else []
        subpath = parts[0] if parts else "."
        try:
            depth = int(parts[1]) if len(parts) > 1 else 2
        except ValueError:
            depth = 2

        target = os.path.join(project_path, subpath)

        if not _is_within_project(project_path, target):
            return "禁止访问项目目录外的路径"

        if not os.path.isdir(target):
            return f"目录不存在: {subpath}"

        lines = [f"{subpath}/"]
        _build_tree(target, lines, prefix="", depth=depth, max_lines=80)

        if len(lines) >= 80:
            lines.append("... 目录过大，已截断")

        return "\n".join(lines)


def _is_within_project(project_path: str, target: str) -> bool:
    """安全检查：确保路径不会逃逸出项目目录"""
    real_project = os.path.realpath(project_path)
    real_target = os.path.realpath(target)
    return real_target.startswith(real_project)


def _build_tree(path: str, lines: list, prefix: str, depth: int, max_lines: int):
    """递归构建目录树"""
    if depth <= 0 or len(lines) >= max_lines:
        return

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return

    # 过滤忽略目录
    entries = [e for e in entries if e not in IGNORE_DIRS]

    dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(path, e))]

    all_items = dirs + files
    for i, name in enumerate(all_items):
        if len(lines) >= max_lines:
            return

        is_last = (i == len(all_items) - 1)
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        full = os.path.join(path, name)
        if os.path.isdir(full):
            lines.append(f"{prefix}{connector}{name}/")
            _build_tree(full, lines, prefix + child_prefix, depth - 1, max_lines)
        else:
            lines.append(f"{prefix}{connector}{name}")
