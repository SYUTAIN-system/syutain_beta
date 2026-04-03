"""
SYUTAINβ V25 ベクトル化ツール
Jina Embeddings API v3でテキストをベクトル化しpgvectorに保存。
"""

import os
import json
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.embedding")

JINA_API_KEY = os.getenv("JINA_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
EMBEDDING_MODEL = "jina-embeddings-v3"
EMBEDDING_DIM = 1024


_last_429_at: float = 0.0  # モジュールレベルのレートリミット追跡

# 日次呼び出しカウンタ（レートリミット回避用）
JINA_EMBEDDING_DAILY_LIMIT = int(os.getenv("JINA_EMBEDDING_DAILY_LIMIT", "500"))
_embedding_daily_count: int = 0
_embedding_counter_date: str = ""  # ISO date string for reset check

# 指数バックオフの待機秒数（429時: 5s → 10s → 20s）
_BACKOFF_WAITS = [5, 10, 20]
_MAX_RETRIES = len(_BACKOFF_WAITS)


async def get_embedding(text: str, _retry: int = 0) -> Optional[list]:
    """テキストをJina Embeddings APIでベクトル化（指数バックオフ付き）"""
    import asyncio, time
    from datetime import date as _date

    if not JINA_API_KEY:
        logger.warning("JINA_API_KEY未設定")
        return None

    # 日次カウンタリセット
    global _embedding_daily_count, _embedding_counter_date, _last_429_at
    today_str = _date.today().isoformat()
    if today_str != _embedding_counter_date:
        _embedding_daily_count = 0
        _embedding_counter_date = today_str

    # 日次上限チェック
    if _embedding_daily_count >= JINA_EMBEDDING_DAILY_LIMIT:
        logger.warning(
            f"Jina Embedding日次上限到達: {_embedding_daily_count}/{JINA_EMBEDDING_DAILY_LIMIT}、スキップ"
        )
        return None

    # 直近429から60秒以内は即スキップ（連続429防止）
    if _last_429_at and (time.time() - _last_429_at) < 60:
        logger.debug("Jina API rate limit cooldown中、スキップ")
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.jina.ai/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {JINA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": EMBEDDING_MODEL, "input": [text[:8000]]},
            )
            if resp.status_code == 200:
                _embedding_daily_count += 1
                # Jina Embeddings v3 コスト追跡（約¥0.01/call推定）
                try:
                    from tools.budget_guard import get_budget_guard
                    bg = get_budget_guard()
                    await bg.record_spend(
                        amount_jpy=0.01, model="jina-embeddings-v3",
                        tier="L", goal_id="embedding", is_info_collection=False,
                    )
                except Exception:
                    pass
                return resp.json()["data"][0]["embedding"]
            if resp.status_code == 429:
                _last_429_at = time.time()
                if _retry < _MAX_RETRIES:
                    wait = _BACKOFF_WAITS[_retry]
                    # Retry-Afterヘッダがあればそちらを優先（上限30秒）
                    retry_after = resp.headers.get("retry-after")
                    if retry_after:
                        wait = min(float(retry_after), 30)
                    logger.warning(
                        f"Jina 429 rate limit（リトライ {_retry + 1}/{_MAX_RETRIES}）、{wait}秒後にリトライ"
                    )
                    await asyncio.sleep(wait)
                    return await get_embedding(text, _retry=_retry + 1)
                logger.warning("Jina 429 リトライ上限到達（3回）、スキップ")
                return None
            logger.error(f"Jina Embeddings API error: {resp.status_code}")
    except Exception as e:
        logger.error(f"Embedding取得失敗: {e}")
    return None


async def embed_and_store_persona(persona_id: int, text: str):
    """persona_memoryレコードをベクトル化してembeddingカラムに保存"""
    embedding = await get_embedding(text)
    if not embedding:
        return False
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # pgvectorのvector型にはカンマ区切り角括弧形式の文字列を渡す
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            await conn.execute(
                "UPDATE persona_memory SET embedding = $1::vector WHERE id = $2",
                embedding_str, persona_id,
            )
            return True
    except Exception as e:
        logger.error(f"persona embedding保存失敗: {e}")
        return False


async def search_similar_persona(query: str, limit: int = 5) -> list:
    """persona_memoryからクエリに類似するレコードをベクトル検索"""
    embedding = await get_embedding(query)
    if not embedding:
        return []
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            embedding_str = str(embedding)
            rows = await conn.fetch(
                """SELECT id, category, content, reasoning,
                    1 - (embedding <=> $1::vector) as similarity
                FROM persona_memory
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2""",
                embedding_str, limit,
            )
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"persona類似検索失敗: {e}")
        return []
