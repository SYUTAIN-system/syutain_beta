"""Discord対話履歴の保存・取得"""
import json, logging
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.bot_memory")

async def save_message(channel_id: str, author: str, content: str, intent: str = None, metadata: dict = None):
    """対話メッセージをDBに保存"""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "INSERT INTO discord_chat_history (channel_id, author, content, intent, metadata) VALUES ($1,$2,$3,$4,$5)",
                channel_id, author, content, intent, json.dumps(metadata or {}, ensure_ascii=False),
            )
    except Exception as e:
        logger.warning(f"メッセージ保存失敗: {e}")

async def get_recent_history(channel_id: str, limit: int = 20) -> list[dict]:
    """直近の対話履歴を取得"""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                "SELECT author, content, created_at FROM discord_chat_history WHERE channel_id=$1 ORDER BY created_at DESC LIMIT $2",
                channel_id, limit,
            )
            return [{"author": r["author"], "content": r["content"], "at": r["created_at"].isoformat()} for r in reversed(rows)]
    except Exception:
        return []
