"""SYUTAINβ エージェントコンテキスト注入 — intel情報+persona+対話学習を統合して各エージェントに提供"""
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
    "perceiver": "for_content",
    "planner": "for_proposals",
    "executor": "for_content",
}

# エージェント別のコンテキスト長制限
AGENT_CONTEXT_LIMIT = {
    "content_pipeline": 2000,  # note記事生成用に長めに
    "sns_batch": 800,
    "proposal_engine": 1200,
    "perceiver": 1000,
    "planner": 1000,
}


async def build_agent_context(agent_name: str) -> str:
    """エージェント向け統合コンテキストを構築（intel_digest + actionable intel + persona学習）"""
    field = AGENT_DIGEST_MAP.get(agent_name, "for_content")
    max_len = AGENT_CONTEXT_LIMIT.get(agent_name, 800)
    parts = []

    try:
        async with get_connection() as conn:
            # 1. intel_digestから当日のダイジェスト
            try:
                row = await conn.fetchrow(
                    "SELECT summary, " + field + " as agent_data FROM intel_digest WHERE digest_date = $1",
                    date.today(),
                )
                if row and row["agent_data"]:
                    items = json.loads(row["agent_data"]) if isinstance(row["agent_data"], str) else (row["agent_data"] or [])
                    if items:
                        parts.append(f"【今日のダイジェスト({len(items)}件)】{(row['summary'] or '')[:100]}")
                        for item in items[:5]:
                            parts.append(f"- {item.get('title','')[:80]} (重要度{item.get('score',0):.1f})")
            except Exception:
                pass

            # 2. actionableなintel_itemsを直接参照（最新10件）
            try:
                actionable = await conn.fetch(
                    """SELECT title, summary, source, importance_score FROM intel_items
                       WHERE review_flag = 'actionable'
                       ORDER BY importance_score DESC, created_at DESC LIMIT 10"""
                )
                if actionable:
                    parts.append(f"\n【活用可能な情報({len(actionable)}件）】")
                    for a in actionable:
                        parts.append(f"- [{a['source']}] {a['title'][:70]}: {(a['summary'] or '')[:100]}")
            except Exception:
                pass

            # 3. 直近のreviewedなintel_items（トレンド把握用）
            try:
                recent = await conn.fetch(
                    """SELECT title, source, importance_score FROM intel_items
                       WHERE review_flag = 'reviewed' AND importance_score >= 0.3
                       AND created_at > NOW() - INTERVAL '48 hours'
                       ORDER BY importance_score DESC LIMIT 5"""
                )
                if recent:
                    parts.append(f"\n【直近48hのトレンド({len(recent)}件）】")
                    for r in recent:
                        parts.append(f"- [{r['source']}] {r['title'][:60]} (重要度{r['importance_score']:.1f})")
            except Exception:
                pass

            # 4. 直近24時間の対話学習（島原の最新の好み・指摘）
            try:
                learnings = await conn.fetch(
                    """SELECT content FROM persona_memory
                       WHERE (reasoning LIKE '%Discord%' OR reasoning LIKE '%対話%')
                       AND created_at > NOW() - INTERVAL '48 hours'
                       ORDER BY created_at DESC LIMIT 5"""
                )
                if learnings:
                    parts.append("\n【島原の最新の好み・指摘】")
                    for l in learnings:
                        parts.append(f"- {l['content'][:80]}")
            except Exception:
                pass

            # 5. proposal_historyの直近承認提案（成功パターン学習用）
            if agent_name in ("proposal_engine", "content_pipeline", "planner"):
                try:
                    approved = await conn.fetch(
                        """SELECT title, primary_channel FROM proposal_history
                           WHERE adopted = true
                           ORDER BY created_at DESC LIMIT 3"""
                    )
                    if approved:
                        parts.append("\n【最近承認された提案】")
                        for p in approved:
                            parts.append(f"- {p['title'][:60]} ({p['primary_channel']})")
                except Exception:
                    pass

            context = "\n".join(parts)
            return context[:max_len] if context else ""

    except Exception as e:
        logger.debug(f"agent_context取得失敗: {e}")
        return ""
