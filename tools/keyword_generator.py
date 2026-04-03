"""SYUTAINβ 動的キーワード生成"""
import logging
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.keyword_generator")

# 固定キーワード（島原のテーマ軸）
FIXED_KEYWORDS = [
    "AIエージェント 最新", "VTuber 収益化", "非エンジニア AI開発",
    "AI事業 個人開発", "生成AI クリエイター", "自律AI システム",
]

async def generate_search_keywords(max_keywords: int = 20) -> list[str]:
    """persona_memory + engagement + actionable intel から動的キーワード生成"""
    keywords = list(FIXED_KEYWORDS)
    try:
        async with get_connection() as conn:
            # 1. persona_memory philosophy/identity からキーワード
            rows = await conn.fetch(
                "SELECT content FROM persona_memory WHERE category IN ('philosophy','identity') ORDER BY created_at DESC LIMIT 5"
            )
            for r in rows:
                # Extract key terms (simple: first 2 meaningful words)
                words = [w for w in (r["content"] or "").split() if len(w) > 2][:2]
                if len(words) >= 2:
                    keywords.append(" ".join(words))

            # 2. actionable intel_items の関連キーワード展開
            rows = await conn.fetch(
                "SELECT title, keyword FROM intel_items WHERE review_flag='actionable' ORDER BY importance_score DESC LIMIT 5"
            )
            for r in rows:
                if r["title"]:
                    keywords.append(f"{r['title'][:30]} 最新")
                if r["keyword"]:
                    keywords.append(r["keyword"])
    except Exception as e:
        logger.warning(f"動的キーワード生成失敗: {e}")

    # 重複除去 + 上限
    seen = set()
    unique = []
    for kw in keywords:
        kw_clean = kw.strip()
        if kw_clean and kw_clean not in seen:
            seen.add(kw_clean)
            unique.append(kw_clean)
    return unique[:max_keywords]
