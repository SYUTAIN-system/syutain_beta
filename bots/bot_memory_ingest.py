"""ユーザー発言の永続化 — 島原大知が会話内で宣言した事実を persona_memory に記録

目的: 過去254件の会話ログで繰り返し発生した「大知さんが伝えた事実を Brain-β が無視する」
問題を構造的に解決する。例:
  - 「エラー解消しておいた」→ 次の status 照会で再度同じエラー報告
  - 「Win11 は Tailscale 入ってない」→ 次の照会で「取得データに情報なし」
  - 「CHARLIE は Ubuntu 復帰済み」→ 2回説明する羽目になる

解決策: statement intent を検出したら即座に persona_memory に priority_tier=8 で記録し、
以降の status_check/chat prompt に working facts として注入する。
"""
import logging
from datetime import datetime, timezone
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.bot_memory_ingest")


async def ingest_user_statement(content: str, channel_id: str = "discord") -> None:
    """大知さんの事実宣言を persona_memory に working fact として記録。
    category='working_fact' でフィルタ可能。24h 経過後は priority_tier を下げる想定（別ジョブ）。"""
    if not content or len(content.strip()) < 3:
        return
    snippet = content.strip()[:500]
    try:
        async with get_connection() as conn:
            # 同一内容の重複を避ける（直近24h）
            dup = await conn.fetchval(
                """SELECT id FROM persona_memory
                   WHERE category='working_fact' AND content = $1
                   AND created_at > NOW() - INTERVAL '24 hours' LIMIT 1""",
                snippet,
            )
            if dup:
                # 既存レコードの updated_at だけ更新
                await conn.execute(
                    "UPDATE persona_memory SET updated_at=NOW() WHERE id=$1", dup
                )
                return
            await conn.execute(
                """INSERT INTO persona_memory
                   (category, context, content, source, session_id, priority_tier, created_at)
                   VALUES ('working_fact', $1, $2, 'discord_chat', $3, 8, NOW())""",
                "大知さんがチャットで宣言した事実",
                snippet,
                channel_id,
            )
        logger.info(f"working_fact ingested: {snippet[:60]}")
    except Exception as e:
        logger.warning(f"working_fact ingest 失敗: {e}")


async def get_recent_working_facts(limit: int = 10) -> list[str]:
    """直近24hの大知さん宣言ファクトを取得。chat prompt 注入用。"""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT content, created_at FROM persona_memory
                   WHERE category='working_fact'
                   AND created_at > NOW() - INTERVAL '24 hours'
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return [r["content"] for r in rows]
    except Exception as e:
        logger.debug(f"working_facts 取得失敗: {e}")
        return []
