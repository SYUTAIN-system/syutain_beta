"""SYUTAINβ エージェントコンテキスト注入 — intel_digestから各エージェント向け情報を取得"""
import json, logging
from datetime import date
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.agent_context")

AGENT_DIGEST_MAP = {
    "content_multiplier": "for_content",
    "content_pipeline": "for_content",
    "sns_batch": "for_social",
    "proposal_engine": "for_proposals",
    "verifier": "for_quality",
    "competitive_analyzer": "for_competitive",
}

async def build_agent_context(agent_name: str) -> str:
    """エージェント向けintel_digestを取得（最大500文字）"""
    field = AGENT_DIGEST_MAP.get(agent_name, "for_content")
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT summary, " + field + " as agent_data FROM intel_digest WHERE digest_date = $1",
                date.today(),
            )
            if not row:
                return ""
            items = json.loads(row["agent_data"]) if isinstance(row["agent_data"], str) else (row["agent_data"] or [])
            if not items:
                return ""
            context = f"【今日の情報({len(items)}件)】{row['summary']}\n"
            for item in items[:5]:
                context += f"- {item.get('title','')[:60]} (重要度{item.get('score',0):.1f})\n"

            # 直近24時間の対話学習を追加
            try:
                learnings = await conn.fetch(
                    """SELECT content FROM persona_memory
                       WHERE reasoning = 'Discord対話から自動抽出'
                       AND created_at > NOW() - INTERVAL '24 hours'
                       ORDER BY created_at DESC LIMIT 3"""
                )
                if learnings:
                    context += "\n【島原の最新の好み・指摘】\n"
                    for l in learnings:
                        context += f"- {l['content'][:60]}\n"
            except Exception:
                pass

            return context[:500]
    except Exception as e:
        logger.debug(f"agent_context取得失敗: {e}")
        return ""
