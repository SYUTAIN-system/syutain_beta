"""
SYUTAINβ V25 グローバルDB接続プール
asyncpg.connect()の直接使用を廃止し、接続プールで管理する。
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg

logger = logging.getLogger("syutain.db_pool")

_pool: Optional[asyncpg.Pool] = None


async def init_pool(min_size: int = 2, max_size: int = 15) -> asyncpg.Pool:
    """起動時に1回だけ呼ぶ。FastAPIのlifespan等から"""
    global _pool
    if _pool is None or _pool._closed:
        dsn = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
        _pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        logger.info(f"DB接続プール初期化完了 (min={min_size}, max={max_size})")
    return _pool


async def close_pool():
    """シャットダウン時に呼ぶ"""
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        logger.info("DB接続プール終了")
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """プール取得。未初期化なら自動初期化"""
    global _pool
    if _pool is None or _pool._closed:
        await init_pool()
    return _pool


@asynccontextmanager
async def get_connection():
    """コネクション取得のコンテキストマネージャ"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
