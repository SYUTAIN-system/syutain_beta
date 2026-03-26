"""SYUTAINβ 情報ダイジェスト — 全エージェント向けに要約配信"""
import json, logging
from datetime import date
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.intel_digest")

async def generate_intel_digest() -> dict:
    """直近24時間のintel_itemsからエージェント向けダイジェスト生成"""
    try:
        async with get_connection() as conn:
            items = await conn.fetch("""
                SELECT id, source, title, summary, importance_score, keyword, review_flag
                FROM intel_items
                WHERE created_at > NOW() - INTERVAL '24 hours'
                AND review_flag IN ('actionable','reviewed')
                ORDER BY importance_score DESC LIMIT 30
            """)
            if not items:
                return {"date": str(date.today()), "summary": "新着情報なし", "items_count": 0}

            # Categorize for agents
            for_content = []  # ContentMultiplier
            for_proposals = []  # ProposalEngine
            for_social = []  # SNS

            for item in items:
                entry = {"id": item["id"], "title": item["title"] or "", "source": item["source"], "score": float(item["importance_score"] or 0)}
                if item["importance_score"] and item["importance_score"] >= 0.6:
                    for_content.append(entry)
                    for_proposals.append(entry)
                for_social.append(entry)

            summary_parts = [f"{item['title'][:40]}" for item in items[:5] if item["title"]]
            summary = "今日の注目: " + " / ".join(summary_parts) if summary_parts else "新着情報あり"

            result = {
                "date": str(date.today()),
                "summary": summary[:200],
                "for_content": for_content[:10],
                "for_proposals": for_proposals[:10],
                "for_quality": [],
                "for_social": for_social[:10],
                "for_competitive": [],
                "items_count": len(items),
            }

            # Save to DB
            await conn.execute("""
                INSERT INTO intel_digest (digest_date, summary, for_content, for_proposals, for_quality, for_social, for_competitive, raw_item_ids)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (digest_date) DO UPDATE SET
                    summary = EXCLUDED.summary, for_content = EXCLUDED.for_content,
                    for_proposals = EXCLUDED.for_proposals, for_social = EXCLUDED.for_social,
                    created_at = NOW()
            """, date.today(), result["summary"],
                json.dumps(result["for_content"], ensure_ascii=False),
                json.dumps(result["for_proposals"], ensure_ascii=False),
                json.dumps(result.get("for_quality", []), ensure_ascii=False),
                json.dumps(result["for_social"], ensure_ascii=False),
                json.dumps(result.get("for_competitive", []), ensure_ascii=False),
                [item["id"] for item in items],
            )
            logger.info(f"intel_digest生成: {len(items)}件 → summary={summary[:50]}")
            return result
    except Exception as e:
        logger.error(f"intel_digest生成失敗: {e}")
        return {"date": str(date.today()), "summary": "生成失敗", "error": str(e)}
