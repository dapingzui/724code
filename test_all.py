"""724code 全命令集成测试"""

import asyncio
import os
import shutil
import stat
import sys
import tempfile

# 修复 Windows 控制台编码
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from adapters.base import BotAdapter, IncomingMessage, OutgoingMessage
from main import check_prerequisites
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

    async def send_typing_action(self, chat_id: str):
        pass

    def last(self):
        return self.sent[-1] if self.sent else ""

    def all_text(self):
        return " ".join(self.sent)

    def clear(self):
        self.sent.clear()


def msg(text, chat_id="test_chat", user_id="test_user"):
    return IncomingMessage(
        platform="test", user_id=user_id, chat_id=chat_id, text=text
    )


passed = 0
failed = 0
total = 0


async def test(name, text, expect_in=None, expect_not_in=None, router=None, chat_id="test_chat"):
    global passed, failed, total
    total += 1
    adapter = MockAdapter()
    await router.handle(msg(text, chat_id=chat_id), adapter)
    reply = adapter.all_text()

    ok = True
    issues = []

    if expect_in:
        for s in (expect_in if isinstance(expect_in, list) else [expect_in]):
            if s not in reply:
                ok = False
                issues.append(f"missing: {s!r}")

    if expect_not_in:
        for s in (expect_not_in if isinstance(expect_not_in, list) else [expect_not_in]):
            if s in reply:
                ok = False
                issues.append(f"unexpected: {s!r}")

    if not ok:
        failed += 1
        print(f"  [FAIL] {name}")
        for i in issues:
            print(f"         {i}")
        print(f"         got: {reply[:300]}")
    else:
        passed += 1
        print(f"  [PASS] {name}")


async def run_all():
    global passed, failed, total

    print("=== 724code 全命令集成测试 ===")
    print()

    # ========== 1. 环境检查 ==========
    print("[1] 启动环境检查")
    total += 1
    missing = check_prerequisites()
    passed += 1
    print(f"  [PASS] check_prerequisites (missing_optional={missing})")
    print()

    # ========== Setup ==========
    test_dir = os.path.join(tempfile.gettempdir(), "724code_fulltest")
    if os.path.exists(test_dir):
        def _force_rm(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(test_dir, onexc=_force_rm)
    os.makedirs(test_dir)

    projects_file = os.path.join(test_dir, "projects.yaml")

    pm = ProjectManager({
        "workspace_root": test_dir,
        "projects_file": projects_file,
        "init_git_on_create": True,
        "create_github_repo": False,
        "github_private": True,
    })
    sm = SessionManager(default_model="claude-sonnet-4-20250514")
    mm = ProjectMemoryManager()
    go = GitOps({
        "user_name": "test",
        "user_email": "test@test.com",
        "default_branch": "main",
        "protected_branches": ["main"],
    })
    fm = FileManager({"max_cat_lines": 200})
    executor = ClaudeExecutor(config={"command": "claude", "timeout": 30}, proxy_url="")
    router = Router(executor, sm, pm, mm, {"recent_entries": 15, "max_context_tokens": 4000}, go, fm)

    t = lambda name, text, **kw: test(name, text, router=router, **kw)

    # ========== 2. 冷启动（无项目） ==========
    print("[2] 冷启动流程（无项目）")
    await t("/help", "/help", expect_in=["/clone", "/repos", "/newproject", "/commit", "/cat", "/tree"])
    await t("/start", "/start", expect_in="724code")
    await t("/projects 空", "/projects", expect_in="暂无项目")
    await t("/status 空", "/status", expect_in="未选择")
    await t("直接发文本 无项目", "你好", expect_in="请先选择项目")
    await t("/diff 无项目", "/diff", expect_in="请先选择项目")
    await t("/cat 无项目", "/cat main.py", expect_in="请先选择项目")
    await t("/tree 无项目", "/tree", expect_in="请先选择项目")
    await t("/memory 无项目", "/memory", expect_in="请先选择项目")
    await t("/gs 无项目", "/gs", expect_in="请先选择项目")
    await t("/commit 无项目", "/commit test", expect_in="请先选择项目")
    await t("/push 无项目", "/push", expect_in="请先选择项目")
    await t("/pull 无项目", "/pull", expect_in="请先选择项目")
    await t("/branch 无项目", "/branch", expect_in="请先选择项目")
    await t("/log 无项目", "/log", expect_in="请先选择项目")
    await t("/search 无项目有参数", "/search keyword", expect_in="请先选择项目")
    print()

    # ========== 3. 项目创建（async newproject） ==========
    print("[3] 项目创建 (/newproject async)")
    await t("/newproject 无参数", "/newproject", expect_in="用法")
    await t("/newproject testprj", "/newproject testprj A test project",
            expect_in=["已创建项目", "testprj"])
    await t("/status 已切换", "/status", expect_in="testprj")

    # 检查 git init
    prj_path = os.path.join(test_dir, "testprj")
    total += 1
    if os.path.isdir(os.path.join(prj_path, ".git")):
        passed += 1
        print("  [PASS] git init 目录存在")
    else:
        failed += 1
        print("  [FAIL] git init 目录不存在")

    await t("/newproject 重复", "/newproject testprj", expect_in="已存在")
    print()

    # ========== 4. 项目管理 ==========
    print("[4] 项目管理")
    await t("/projects 列表", "/projects", expect_in=["testprj", "当前"])
    await t("/addproject 缺参数", "/addproject", expect_in="用法")
    await t("/addproject 路径不存在", "/addproject fake /nonexistent/xxx", expect_in="不存在")
    await t("/rmproject 不存在", "/rmproject ghost", expect_in="不存在")
    await t("/cd 不存在", "/cd ghost", expect_in="不存在")
    await t("/cd testprj", "/cd testprj", expect_in="已切换")
    await t("/clone 无参数", "/clone", expect_in="用法")
    print()

    # ========== 5. Git 操作 ==========
    print("[5] Git 操作")

    # 创建文件
    with open(os.path.join(prj_path, "hello.txt"), "w") as f:
        f.write("hello 724code\n")

    await t("/gs 有文件", "/gs", expect_in="hello.txt")
    await t("/diff", "/diff", expect_not_in="Traceback")
    await t("/commit", "/commit Initial file", expect_in="commit")
    await t("/log", "/log", expect_in="Initial file")
    await t("/branch 列表", "/branch", expect_in="main")
    await t("/branch 新建", "/branch dev", expect_in="dev")
    await t("/push 保护分支", "/push main", expect_in="保护分支")
    print()

    # ========== 6. 文件查看 ==========
    print("[6] 文件查看")
    await t("/cat hello.txt", "/cat hello.txt", expect_in="hello 724code")
    await t("/cat 行范围", "/cat hello.txt 1", expect_in="hello")
    await t("/cat 不存在", "/cat ghost.txt", expect_in="不存在")
    await t("/tree", "/tree", expect_in="hello.txt")
    await t("/tree 深度", "/tree . 1", expect_in="hello.txt")
    print()

    # ========== 7. 记忆系统 ==========
    print("[7] 记忆系统")
    await t("/memory 空", "/memory", expect_in="暂无")
    await t("/memory stats", "/memory stats", expect_in="记录数")
    await t("/search 无参数", "/search", expect_in="用法")
    await t("/search 无结果", "/search xyznothing123", expect_in="未找到")
    print()

    # ========== 8. 会话管理 ==========
    print("[8] 会话管理")
    await t("/model 查看", "/model", expect_in=["sonnet", "opus", "haiku"])
    await t("/model 切换", "/model haiku", expect_in="haiku")
    await t("/status 验证模型", "/status", expect_in="haiku")
    await t("/new 新会话", "/new", expect_in="新建会话")
    await t("/abort", "/abort", expect_in="没有")
    await t("/detail 空", "/detail", expect_in="没有")
    print()

    # ========== 9. 边界情况 ==========
    print("[9] 边界情况")
    await t("未知命令", "/xyz", expect_in="未知命令")
    await t("@bot后缀", "/help@my_bot", expect_in="/clone")
    # 空白消息不该崩
    adapter = MockAdapter()
    await router.handle(msg("   "), adapter)
    total += 1
    if len(adapter.sent) == 0:
        passed += 1
        print("  [PASS] 空白消息静默忽略")
    else:
        failed += 1
        print(f"  [FAIL] 空白消息意外回复: {adapter.sent}")
    print()

    # ========== 10. GitHub 集成（真调 gh） ==========
    print("[10] GitHub 集成")
    await t("/repos", "/repos 3", expect_in="GitHub")
    print()

    # ========== 11. 多 chat_id 隔离 ==========
    print("[11] 多用户隔离")
    await t("用户B 无项目", "/status", expect_in="未选择", chat_id="chat_B")
    await t("用户A 仍在 testprj", "/status", expect_in="testprj", chat_id="test_chat")
    print()

    # ========== 清理 ==========
    def force_rm(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(test_dir, onexc=force_rm)

    # ========== 汇总 ==========
    print("=" * 50)
    print(f"总计: {total}  通过: {passed}  失败: {failed}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all())
