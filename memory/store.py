"""记忆存储引擎 — SQLite + FTS5 全文搜索

每个项目独立存储在 <project_path>/.724code/memories.db
"""

import json
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


class ProjectMemoryManager:
    """按项目路径管理 MemoryStore 实例"""

    def __init__(self):
        self._stores: dict[str, MemoryStore] = {}

    def get_store(self, project_path: str) -> MemoryStore:
        """获取项目对应的 MemoryStore（自动创建）"""
        if project_path not in self._stores:
            db_path = os.path.join(project_path, ".724code", "memories.db")
            self._stores[project_path] = MemoryStore(db_path)
        return self._stores[project_path]


class MemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """创建表和索引"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_msg TEXT NOT NULL,
                summary TEXT NOT NULL,
                files_changed TEXT DEFAULT '[]',
                session_id TEXT DEFAULT '',
                cost_usd REAL DEFAULT 0,
                model TEXT DEFAULT ''
            )
        """)
        # FTS5 全文搜索索引
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(user_msg, summary, content=memories, content_rowid=id)
        """)
        conn.commit()
        conn.close()
        logger.info(f"记忆数据库就绪: {self.db_path}")

    def save_entry(
        self,
        project: str,
        user_msg: str,
        summary: str,
        files_changed: list[str] = None,
        session_id: str = "",
        cost_usd: float = 0,
        model: str = "",
    ):
        """保存一条记忆"""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO memories
               (project, timestamp, user_msg, summary, files_changed, session_id, cost_usd, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project,
                datetime.now().isoformat(),
                user_msg,
                summary,
                json.dumps(files_changed or []),
                session_id,
                cost_usd,
                model,
            )
        )
        # 同步 FTS 索引
        conn.execute(
            """INSERT INTO memories_fts(rowid, user_msg, summary)
               VALUES (?, ?, ?)""",
            (cursor.lastrowid, user_msg, summary)
        )
        conn.commit()
        conn.close()

    def get_recent(self, project: str, n: int = 15) -> list[dict]:
        """获取项目最近 N 条记忆"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT timestamp, user_msg, summary, files_changed, cost_usd, model
               FROM memories WHERE project = ?
               ORDER BY id DESC LIMIT ?""",
            (project, n)
        ).fetchall()
        conn.close()
        return [
            {
                "time": r[0],
                "task": r[1],
                "summary": r[2],
                "files": json.loads(r[3]),
                "cost": r[4],
                "model": r[5],
            }
            for r in reversed(rows)  # 按时间正序返回
        ]

    def search(self, query: str, project: str = "", limit: int = 10) -> list[dict]:
        """全文搜索记忆（FTS5 优先，中文回退 LIKE）"""
        conn = self._get_conn()
        rows = self._fts_search(conn, query, project, limit)
        # FTS5 对中文分词不佳，无结果时回退 LIKE
        if not rows:
            rows = self._like_search(conn, query, project, limit)
        conn.close()
        return [
            {"time": r[0], "task": r[1], "summary": r[2], "project": r[3]}
            for r in rows
        ]

    def _fts_search(self, conn, query: str, project: str, limit: int) -> list:
        """FTS5 全文搜索"""
        try:
            if project:
                return conn.execute(
                    """SELECT m.timestamp, m.user_msg, m.summary, m.project
                       FROM memories_fts fts
                       JOIN memories m ON fts.rowid = m.id
                       WHERE memories_fts MATCH ? AND m.project = ?
                       ORDER BY rank LIMIT ?""",
                    (query, project, limit)
                ).fetchall()
            else:
                return conn.execute(
                    """SELECT m.timestamp, m.user_msg, m.summary, m.project
                       FROM memories_fts fts
                       JOIN memories m ON fts.rowid = m.id
                       WHERE memories_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit)
                ).fetchall()
        except Exception:
            return []

    def _like_search(self, conn, query: str, project: str, limit: int) -> list:
        """LIKE 模糊搜索（中文回退）"""
        pattern = f"%{query}%"
        if project:
            return conn.execute(
                """SELECT timestamp, user_msg, summary, project
                   FROM memories
                   WHERE (user_msg LIKE ? OR summary LIKE ?) AND project = ?
                   ORDER BY id DESC LIMIT ?""",
                (pattern, pattern, project, limit)
            ).fetchall()
        else:
            return conn.execute(
                """SELECT timestamp, user_msg, summary, project
                   FROM memories
                   WHERE user_msg LIKE ? OR summary LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                (pattern, pattern, limit)
            ).fetchall()

    def get_stats(self, project: str = "") -> dict:
        """获取记忆统计"""
        conn = self._get_conn()
        if project:
            row = conn.execute(
                "SELECT COUNT(*), SUM(cost_usd) FROM memories WHERE project = ?",
                (project,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*), SUM(cost_usd) FROM memories"
            ).fetchone()
        conn.close()
        return {
            "count": row[0] or 0,
            "total_cost": round(row[1] or 0, 4),
        }
