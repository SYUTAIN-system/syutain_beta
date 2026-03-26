"""
Brain-β → Brain-α エスカレーション共通ヘルパー
claude_code_queue / brain_handoff へのレコード挿入を一元化。
"""

import json
import logging
from typing import Optional

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.escalation")


async def escalate_to_queue(
    category: str,
    description: str,
    priority: str = "medium",
    source_agent: str = "",
    auto_solvable: bool = False,
    context_files: list = None,
    suggested_prompt: str = None,
) -> Optional[int]:
    """claude_code_queueにエスカレーションを追加"""
    try:
        async with get_connection() as conn:
            row_id = await conn.fetchval(
                """INSERT INTO claude_code_queue
                   (priority, category, description, auto_solvable,
                    context_files, suggested_prompt, source_agent, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
                   RETURNING id""",
                priority, category, description, auto_solvable,
                json.dumps(context_files or [], ensure_ascii=False),
                suggested_prompt, source_agent,
            )
            logger.info(f"エスカレーション: {source_agent} → queue#{row_id} ({category})")
            return row_id
    except Exception as e:
        logger.error(f"エスカレーション失敗: {e}")
        return None


async def handoff_to_alpha(
    category: str,
    title: str,
    detail: str = "",
    source_agent: str = "",
    context: dict = None,
) -> Optional[int]:
    """brain_handoffにβ→αハンドオフを追加"""
    try:
        async with get_connection() as conn:
            row_id = await conn.fetchval(
                """INSERT INTO brain_handoff
                   (direction, category, source_agent, title, detail, context, status)
                   VALUES ('beta_to_alpha', $1, $2, $3, $4, $5, 'pending')
                   RETURNING id""",
                category, source_agent, title, detail,
                json.dumps(context or {}, ensure_ascii=False),
            )
            logger.info(f"ハンドオフβ→α: {source_agent} → handoff#{row_id} ({title})")
            return row_id
    except Exception as e:
        logger.error(f"ハンドオフβ→α失敗: {e}")
        return None


async def get_alpha_directives(category: str = None, status: str = "pending") -> list:
    """brain_handoffからα→β指令を取得"""
    try:
        async with get_connection() as conn:
            if category:
                rows = await conn.fetch(
                    """SELECT id, category, title, detail, context, status, created_at
                       FROM brain_handoff
                       WHERE direction = 'alpha_to_beta' AND status = $1 AND category = $2
                       ORDER BY created_at DESC LIMIT 10""",
                    status, category,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, category, title, detail, context, status, created_at
                       FROM brain_handoff
                       WHERE direction = 'alpha_to_beta' AND status = $1
                       ORDER BY created_at DESC LIMIT 10""",
                    status,
                )
            return [
                {
                    "id": r["id"],
                    "category": r["category"],
                    "title": r["title"],
                    "detail": r["detail"],
                    "context": json.loads(r["context"]) if isinstance(r["context"], str) else r["context"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"α指令取得失敗: {e}")
        return []


async def acknowledge_directive(handoff_id: int) -> bool:
    """指令をacknowledged状態に更新"""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE brain_handoff SET status = 'acknowledged', acknowledged_at = NOW() WHERE id = $1",
                handoff_id,
            )
            return True
    except Exception as e:
        logger.error(f"指令acknowledge失敗: {e}")
        return False
