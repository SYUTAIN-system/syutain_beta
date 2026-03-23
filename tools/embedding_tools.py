"""
SYUTAINβ V25 ベクトル化ツール
Jina Embeddings API v3でテキストをベクトル化しpgvectorに保存。
"""

import os
import json
import logging
from typing import Optional

import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.embedding")

JINA_API_KEY = os.getenv("JINA_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
EMBEDDING_MODEL = "jina-embeddings-v3"
EMBEDDING_DIM = 1024


async def get_embedding(text: str) -> Optional[list]:
    """テキストをJina Embeddings APIでベクトル化"""
    if not JINA_API_KEY:
        logger.warning("JINA_API_KEY未設定")
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
                data = resp.json()
                return data["data"][0]["embedding"]
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
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute(
                "UPDATE persona_memory SET embedding = $1 WHERE id = $2",
                json.dumps(embedding), persona_id,
            )
            return True
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"persona embedding保存失敗: {e}")
        return False


async def search_similar_persona(query: str, limit: int = 5) -> list:
    """persona_memoryからクエリに類似するレコードをベクトル検索"""
    embedding = await get_embedding(query)
    if not embedding:
        return []
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            rows = await conn.fetch(
                """SELECT id, category, content, reasoning,
                    1 - (embedding <=> $1::vector) as similarity
                FROM persona_memory
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2""",
                json.dumps(embedding), limit,
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"persona類似検索失敗: {e}")
        return []
