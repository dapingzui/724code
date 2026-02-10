"""项目管理器 — 管理项目注册表（data/projects.yaml）"""

import asyncio
import logging
import os
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)


class ProjectManager:
    def __init__(self, config: dict):
        self.workspace_root = config.get("workspace_root", os.path.expanduser("~"))
        self.projects_file = config.get("projects_file", "./data/projects.yaml")
        self.init_git_on_create = config.get("init_git_on_create", True)
        self.create_github_repo = config.get("create_github_repo", True)
        self.github_private = config.get("github_private", True)
        self.projects: dict[str, dict] = {}
        self._load()

    def _load(self):
        """从 YAML 加载项目注册表"""
        if os.path.exists(self.projects_file):
            with open(self.projects_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.projects = data
        else:
            self.projects = {}
        logger.info(f"加载 {len(self.projects)} 个项目")

    def _save(self):
        """保存项目注册表到 YAML"""
        os.makedirs(os.path.dirname(self.projects_file), exist_ok=True)
        with open(self.projects_file, "w", encoding="utf-8") as f:
            yaml.dump(self.projects, f, allow_unicode=True, default_flow_style=False)

    def list_projects(self) -> dict[str, dict]:
        return dict(self.projects)

    def get_project(self, name: str) -> dict | None:
        return self.projects.get(name)

    def get_project_path(self, name: str) -> str:
        proj = self.projects.get(name)
        if proj:
            return proj.get("path", "")
        return ""

    def add_project(self, name: str, path: str, description: str = "") -> str:
        """注册已有目录为项目"""
        if name in self.projects:
            return f"项目 '{name}' 已存在"

        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            return f"目录不存在: {abs_path}"

        self.projects[name] = {
            "path": abs_path,
            "description": description,
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        return f"已注册项目: {name} -> {abs_path}"

    async def new_project(self, name: str, description: str = "") -> str:
        """从零新建项目：本地目录 + git init + GitHub 仓库"""
        if name in self.projects:
            return f"项目 '{name}' 已存在"

        project_path = os.path.join(self.workspace_root, name)
        if os.path.exists(project_path):
            return f"目录已存在: {project_path}\n用 /addproject {name} {project_path} 注册它"

        os.makedirs(project_path, exist_ok=True)

        self.projects[name] = {
            "path": project_path,
            "description": description,
            "created_at": datetime.now().isoformat(),
        }
        self._save()

        lines = [f"已创建项目: {name}", f"路径: {project_path}"]

        # git init
        if self.init_git_on_create:
            git_dir = os.path.join(project_path, ".git")
            if not os.path.exists(git_dir):
                await _run_cmd("git", "init", "-b", "main", project_path)
                lines.append("git init 完成")

        # 创建 GitHub 仓库
        if self.create_github_repo:
            gh_result = await self._create_github_repo(name, description, project_path)
            lines.append(gh_result)

        return "\n".join(lines)

    async def _create_github_repo(self, name: str, description: str, project_path: str) -> str:
        """用 gh CLI 创建 GitHub 仓库并关联 remote"""
        # 先检查 gh 是否可用
        try:
            stdout, stderr, code = await _run_cmd("gh", "auth", "status")
            if code != 0:
                return "⚠️ gh 未登录，跳过 GitHub 仓库创建（运行 gh auth login 配置）"
        except FileNotFoundError:
            return "⚠️ gh CLI 未安装，跳过 GitHub 仓库创建"

        visibility = "--private" if self.github_private else "--public"
        args = ["gh", "repo", "create", name, visibility, "--source", project_path]
        if description:
            args.extend(["--description", description])

        stdout, stderr, code = await _run_cmd(*args)

        if code != 0:
            if "already exists" in stderr:
                return f"GitHub 仓库 {name} 已存在，跳过创建"
            return f"GitHub 创建失败: {stderr.strip()}"

        repo_url = stdout.strip()
        return f"GitHub 仓库已创建: {repo_url}"

    async def clone_project(self, repo: str, name: str = "") -> str:
        """从 GitHub 克隆仓库到 workspace_root 并注册为项目"""
        # 先检查 gh 是否可用
        try:
            _, stderr, code = await _run_cmd("gh", "auth", "status")
            if code != 0:
                return "❌ gh 未登录，请先运行: gh auth login"
        except FileNotFoundError:
            return "❌ gh CLI 未安装\n安装: https://cli.github.com/"

        # 推断项目名：用户指定 > repo 最后一段
        if not name:
            name = repo.rstrip("/").split("/")[-1]
            # 去掉 .git 后缀
            if name.endswith(".git"):
                name = name[:-4]

        if name in self.projects:
            return f"项目 '{name}' 已存在"

        target_path = os.path.join(self.workspace_root, name)
        if os.path.exists(target_path):
            return (f"目录已存在: {target_path}\n"
                    f"用 /addproject {name} {target_path} 注册它")

        # gh repo clone 支持 owner/repo 简写和完整 URL
        stdout, stderr, code = await _run_cmd(
            "gh", "repo", "clone", repo, target_path,
        )
        if code != 0:
            return f"❌ 克隆失败: {stderr.strip()}"

        self.projects[name] = {
            "path": target_path,
            "description": f"cloned from {repo}",
            "created_at": datetime.now().isoformat(),
        }
        self._save()

        return f"✅ 已克隆并注册: {name}\n路径: {target_path}"

    async def list_github_repos(self, limit: int = 20) -> str:
        """列出自己 GitHub 上的仓库（含 star 数和描述）"""
        try:
            stdout, stderr, code = await _run_cmd(
                "gh", "repo", "list", "--limit", str(limit),
                "--json", "name,description,isPrivate,updatedAt,stargazerCount,primaryLanguage",
            )
            if code != 0:
                return f"❌ 获取仓库列表失败: {stderr.strip()}"
        except FileNotFoundError:
            return "❌ gh CLI 未安装"

        import json
        repos = json.loads(stdout)
        if not repos:
            return "GitHub 上没有找到仓库"

        lines = [f"GitHub 仓库（{len(repos)} 个）:\n"]
        for r in repos:
            flag = "🔒" if r.get("isPrivate") else "🌐"
            stars = r.get("stargazerCount", 0)
            star_str = f" ⭐{stars}" if stars > 0 else ""
            lang = ""
            if r.get("primaryLanguage") and r["primaryLanguage"].get("name"):
                lang = f" [{r['primaryLanguage']['name']}]"
            desc = r.get("description", "") or ""
            if desc:
                desc = f"\n    {desc[:60]}"
            lines.append(f"  {flag} {r['name']}{star_str}{lang}{desc}")

        lines.append(f"\n用 /clone <仓库名> 克隆到本地")
        return "\n".join(lines)

    def remove_project(self, name: str) -> str:
        """取消项目注册（不删除文件）"""
        if name not in self.projects:
            return f"项目 '{name}' 不存在"

        del self.projects[name]
        self._save()
        return f"已取消注册: {name}（文件未删除）"


async def _run_cmd(*args) -> tuple[str, str, int]:
    """执行命令，返回 (stdout, stderr, returncode)"""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        proc.returncode,
    )
