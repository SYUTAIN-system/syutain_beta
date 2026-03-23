"""
SYUTAINβ V25 ストレージツール
設計書 第2章 2.4準拠

PostgreSQL/SQLiteヘルパー関数。
全ての中間成果物をDBに保存し、途中停止しても資産化できるようにする（CLAUDE.mdルール18）。
"""

import os
import json
import sqlite3
import asyncio
import logging
from typing import Optional, Any
from pathlib import Path
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.storage_tools")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


# ===== PostgreSQLヘルパー =====

class PgHelper:
    """PostgreSQL非同期ヘルパー"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None or self._pool._closed:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    async def execute(self, query: str, *args) -> Optional[str]:
        """SQL実行"""
        pool = await self.get_pool()
        if not pool:
            return None
        try:
            async with pool.acquire() as conn:
                return await conn.execute(query, *args)
        except Exception as e:
            logger.error(f"SQL実行失敗: {e}")
            return None

    async def fetch(self, query: str, *args) -> list:
        """SELECT結果を取得"""
        pool = await self.get_pool()
        if not pool:
            return []
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"SQLフェッチ失敗: {e}")
            return []

    async def fetchval(self, query: str, *args) -> Any:
        """単一値を取得"""
        pool = await self.get_pool()
        if not pool:
            return None
        try:
            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        except Exception as e:
            logger.error(f"SQLフェッチ値失敗: {e}")
            return None

    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """単一行を取得"""
        pool = await self.get_pool()
        if not pool:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"SQLフェッチ行失敗: {e}")
            return None

    async def close(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")


# ===== SQLiteヘルパー =====

class SqliteHelper:
    """SQLite同期ヘルパー（ノードローカル用）"""

    def __init__(self, db_path: Optional[str] = None):
        node_name = os.getenv("THIS_NODE", "alpha")
        self.db_path = db_path or str(Path(f"data/local_{node_name}.db"))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute(self, query: str, params: tuple = ()) -> Optional[int]:
        """SQL実行（INSERT/UPDATE/DELETE）"""
        try:
            conn = self._connect()
            cursor = conn.execute(query, params)
            conn.commit()
            lastrowid = cursor.lastrowid
            conn.close()
            return lastrowid
        except Exception as e:
            logger.error(f"SQLite実行失敗: {e}")
            return None

    def fetch(self, query: str, params: tuple = ()) -> list:
        """SELECT結果を取得"""
        try:
            conn = self._connect()
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"SQLiteフェッチ失敗: {e}")
            return []

    def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        """単一行を取得"""
        try:
            conn = self._connect()
            row = conn.execute(query, params).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"SQLiteフェッチ行失敗: {e}")
            return None


# ===== 中間成果物ストレージ（CLAUDE.mdルール18）=====

class ArtifactStorage:
    """
    中間成果物をDBに保存し、途中停止しても資産化できるようにする。
    PostgreSQLに保存。接続不可時はSQLiteにフォールバック。
    """

    def __init__(self):
        self._pg = PgHelper()
        self._sqlite = SqliteHelper()
        # SQLiteにもartifactsテーブルを作成
        self._sqlite.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_id TEXT UNIQUE,
                goal_id TEXT,
                task_id TEXT,
                artifact_type TEXT,
                content TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

    async def save(
        self,
        artifact_id: str,
        content: Any,
        artifact_type: str = "intermediate",
        goal_id: str = "",
        task_id: str = "",
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        成果物を保存

        Args:
            artifact_id: 一意ID
            content: 保存内容（dict/str/list）
            artifact_type: 種別 (intermediate / draft / final / analysis / data)
            goal_id: 関連Goal ID
            task_id: 関連Task ID
            metadata: 追加メタデータ
        """
        content_str = json.dumps(content, ensure_ascii=False, default=str) if not isinstance(content, str) else content
        metadata_str = json.dumps(metadata or {}, ensure_ascii=False)

        # PostgreSQL優先
        try:
            result = await self._pg.execute(
                """
                INSERT INTO tasks (id, goal_id, type, status, output_data, artifacts)
                VALUES ($1, $2, $3, 'artifact', $4::jsonb, $5::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    output_data = $4::jsonb,
                    artifacts = $5::jsonb,
                    updated_at = NOW()
                """,
                artifact_id, goal_id or "artifact", artifact_type,
                content_str, metadata_str,
            )
            if result:
                logger.info(f"成果物保存 (PostgreSQL): {artifact_id}")
                return True
        except Exception as e:
            logger.warning(f"PostgreSQL保存失敗、SQLiteフォールバック: {e}")

        # SQLiteフォールバック
        try:
            self._sqlite.execute(
                """
                INSERT OR REPLACE INTO artifacts (artifact_id, goal_id, task_id, artifact_type, content, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, goal_id, task_id, artifact_type, content_str, metadata_str),
            )
            logger.info(f"成果物保存 (SQLite): {artifact_id}")
            return True
        except Exception as e:
            logger.error(f"成果物保存失敗 (両方): {e}")
            return False

    async def load(self, artifact_id: str) -> Optional[dict]:
        """成果物を読み込み"""
        # PostgreSQL優先
        try:
            row = await self._pg.fetchrow(
                "SELECT * FROM tasks WHERE id = $1",
                artifact_id,
            )
            if row:
                return row
        except Exception:
            pass

        # SQLiteフォールバック
        row = self._sqlite.fetchone(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        )
        return row

    async def list_by_goal(self, goal_id: str) -> list:
        """Goal IDに紐づく成果物を一覧"""
        try:
            rows = await self._pg.fetch(
                "SELECT id, type, status, created_at FROM tasks WHERE goal_id = $1 ORDER BY created_at DESC",
                goal_id,
            )
            if rows:
                return rows
        except Exception:
            pass

        return self._sqlite.fetch(
            "SELECT * FROM artifacts WHERE goal_id = ? ORDER BY created_at DESC",
            (goal_id,),
        )

    async def close(self) -> None:
        await self._pg.close()


# ===== シングルトン =====

_pg_helper: Optional[PgHelper] = None
_sqlite_helper: Optional[SqliteHelper] = None
_artifact_storage: Optional[ArtifactStorage] = None


def get_pg() -> PgHelper:
    global _pg_helper
    if _pg_helper is None:
        _pg_helper = PgHelper()
    return _pg_helper


def get_sqlite() -> SqliteHelper:
    global _sqlite_helper
    if _sqlite_helper is None:
        _sqlite_helper = SqliteHelper()
    return _sqlite_helper


def get_artifact_storage() -> ArtifactStorage:
    global _artifact_storage
    if _artifact_storage is None:
        _artifact_storage = ArtifactStorage()
    return _artifact_storage
