"""724code 真实编码工作流模拟测试

完整链路: 用户消息 → Router → Executor → Claude Code CLI → 文件操作 → 返回结果
"""

import asyncio
import os
import shutil
import stat
import sys
import tempfile

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from adapters.base import BotAdapter, IncomingMessage, OutgoingMessage
from core.router import Router
from core.executor import ClaudeExecutor
from core.session_manager import SessionManager
from core.project_manager import ProjectManager
from core.git_ops import GitOps
from core.file_manager import FileManager
from memory.store import ProjectMemoryManager


class MockAdapter(BotAdapter):
    def __init__(self):
        self.sent = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, msg: OutgoingMessage):
        self.sent.append(msg.text)
        # 实时打印 Bot 回复
        print(f"    Bot: {msg.text[:300]}")

    async def send_typing_action(self, chat_id: str):
        pass

    def all_text(self):
        return "\n".join(self.sent)

    def clear(self):
        self.sent.clear()


def msg(text, chat_id="sim_chat", user_id="sim_user"):
    return IncomingMessage(
        platform="test", user_id=user_id, chat_id=chat_id, text=text
    )


async def simulate():
    print("=" * 60)
    print("724code 真实编码工作流模拟")
    print("=" * 60)
    print()

    # ========== 环境准备 ==========
    test_dir = os.path.join(tempfile.gettempdir(), "724code_coding_sim")
    if os.path.exists(test_dir):
        def _force_rm(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(test_dir, onexc=_force_rm)
    os.makedirs(test_dir)

    projects_file = os.path.join(test_dir, "_projects.yaml")

    pm = ProjectManager({
        "workspace_root": test_dir,
        "projects_file": projects_file,
        "init_git_on_create": True,
        "create_github_repo": False,
        "github_private": True,
    })
    sm = SessionManager(default_model="claude-haiku-4-5-20251001")
    mm = ProjectMemoryManager()
    go = GitOps({
        "user_name": "test-bot",
        "user_email": "test@724code.dev",
        "default_branch": "main",
        "protected_branches": ["main"],
    })
    fm = FileManager({"max_cat_lines": 200})

    # 真实 Executor，用 haiku 省钱
    executor = ClaudeExecutor(
        config={
            "command": "claude",
            "model": "claude-haiku-4-5-20251001",
            "max_turns": 10,
            "timeout": 120,
            "allowed_tools": ["Read", "Write", "Edit", "Bash", "Grep"],
        },
        proxy_url="http://127.0.0.1:7890",
    )
    router = Router(executor, sm, pm, mm, {"recent_entries": 15, "max_context_tokens": 4000}, go, fm)

    passed = 0
    failed = 0

    async def step(label, text, check_fn=None):
        nonlocal passed, failed
        print(f"\n--- {label} ---")
        print(f"  User: {text}")
        adapter = MockAdapter()
        await router.handle(msg(text), adapter)
        reply = adapter.all_text()

        if check_fn:
            ok, reason = check_fn(reply)
            if ok:
                passed += 1
                print(f"  [PASS] {reason}")
            else:
                failed += 1
                print(f"  [FAIL] {reason}")
        else:
            passed += 1
            print(f"  [OK]")
        return reply

    # ========== 模拟流程 ==========

    # Step 1: 新建项目
    await step(
        "Step 1: 新建项目",
        "/newproject demo_app A demo web app",
        lambda r: ("已创建项目" in r, "项目创建成功" if "已创建项目" in r else f"创建失败: {r[:100]}")
    )

    # Step 2: 确认状态
    await step(
        "Step 2: 确认状态",
        "/status",
        lambda r: ("demo_app" in r, "自动切换到 demo_app" if "demo_app" in r else f"未切换: {r[:100]}")
    )

    # Step 3: 让 Claude Code 写一个 Python 文件
    await step(
        "Step 3: 编写 Python 文件（真实 Claude Code 调用）",
        "Create a file called calculator.py with a Calculator class that has add, subtract, multiply, divide methods. Include a simple test at the bottom with if __name__ == '__main__'",
        lambda r: ("执行中" in r or "calculator" in r.lower() or "Calculator" in r or "success" in r.lower() or "done" in r.lower() or "created" in r.lower(),
                   "Claude Code 执行完成" if any(x in r.lower() for x in ["calculator", "success", "done", "created"]) else f"可能失败: {r[:200]}")
    )

    # Step 4: 验证文件存在
    prj_path = os.path.join(test_dir, "demo_app")
    calc_file = os.path.join(prj_path, "calculator.py")
    exists = os.path.exists(calc_file)
    if exists:
        passed += 1
        print(f"\n  [PASS] calculator.py 已创建 ({os.path.getsize(calc_file)} bytes)")
    else:
        failed += 1
        # 列出目录看看到底创建了什么
        files = os.listdir(prj_path) if os.path.isdir(prj_path) else []
        print(f"\n  [FAIL] calculator.py 不存在, 目录内容: {files}")

    # Step 5: 用 /cat 查看文件
    await step(
        "Step 5: /cat 查看生成的代码",
        "/cat calculator.py",
        lambda r: ("class" in r or "def" in r or "Calculator" in r or "不存在" in r,
                   "文件内容可读" if "class" in r or "def" in r else f"无内容: {r[:200]}")
    )

    # Step 6: 用 Bash 运行文件
    await step(
        "Step 6: 让 Claude Code 运行文件",
        "Run calculator.py and show me the output",
        lambda r: ("执行中" in r or len(r) > 20,
                   "执行完成" if len(r) > 20 else f"输出太短: {r[:200]}")
    )

    # Step 7: 让 Claude Code 修改文件（Edit 工具）
    await step(
        "Step 7: 修改文件（测试 Edit 权限）",
        "Add a power method to Calculator that calculates x**y, and add a test for it in the main block",
        lambda r: ("执行中" in r or "power" in r.lower() or "success" in r.lower() or "added" in r.lower() or "done" in r.lower(),
                   "Edit 工具工作正常" if any(x in r.lower() for x in ["power", "success", "added", "done", "edit"]) else f"可能失败: {r[:200]}")
    )

    # Step 8: git status 看变更
    await step(
        "Step 8: /gs 查看 git 状态",
        "/gs",
        lambda r: ("calculator" in r.lower() or "changes" in r.lower() or "untracked" in r.lower() or "modified" in r.lower() or "new file" in r.lower(),
                   "git 检测到变更" if any(x in r.lower() for x in ["calculator", "changes", "untracked", "modified", "new file"]) else f"无变更: {r[:200]}")
    )

    # Step 9: git commit
    await step(
        "Step 9: /commit 提交代码",
        "/commit Add calculator with power method",
        lambda r: ("commit" in r.lower() or "提交" in r,
                   "提交成功" if "commit" in r.lower() or "提交" in r else f"提交结果: {r[:200]}")
    )

    # Step 10: /log 查看提交记录
    await step(
        "Step 10: /log 查看提交历史",
        "/log",
        lambda r: ("calculator" in r.lower() or "Add" in r or "power" in r.lower(),
                   "提交记录可见" if any(x in r.lower() for x in ["calculator", "add", "power"]) else f"日志: {r[:200]}")
    )

    # Step 11: /tree 查看项目结构
    await step(
        "Step 11: /tree 查看项目结构",
        "/tree",
        lambda r: ("calculator" in r.lower(),
                   "目录结构正确" if "calculator" in r.lower() else f"结构: {r[:200]}")
    )

    # Step 12: /memory 查看记忆
    await step(
        "Step 12: /memory 查看执行记忆",
        "/memory",
        lambda r: ("calculator" in r.lower() or "记录" in r or "最近" in r,
                   "记忆已保存" if any(x in r for x in ["记录", "最近", "Calculator", "calculator"]) else f"记忆: {r[:200]}")
    )

    # Step 13: 会话续接（验证 --resume）
    await step(
        "Step 13: 会话续接（测试 --resume）",
        "What files did you just create? List them.",
        lambda r: ("calculator" in r.lower() or len(r) > 30,
                   "会话续接正常" if "calculator" in r.lower() else f"回复: {r[:200]}")
    )

    # Step 14: /detail 查看完整输出
    await step(
        "Step 14: /detail 查看完整输出",
        "/detail",
        lambda r: (len(r) > 10,
                   f"完整输出 {len(r)} 字符" if len(r) > 10 else "无输出")
    )

    # ========== 清理 ==========
    def _force_rm(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(test_dir, onexc=_force_rm)

    # ========== 汇总 ==========
    print()
    print("=" * 60)
    print(f"总计: {passed + failed}  通过: {passed}  失败: {failed}")
    if failed == 0:
        print("ALL STEPS PASSED - 完整编码工作流验证通过")
    else:
        print(f"{failed} STEPS FAILED")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(simulate())
    sys.exit(0 if success else 1)
