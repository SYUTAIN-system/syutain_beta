"""
SYUTAINβ V25 海外トレンド先取り検出
英語で出ているが日本語記事がまだないAI話題を検出し、先行者利益を狙う。
"""

import logging
from typing import Optional

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.overseas_trend")

# 英語のみで検索するキーワード（日本語カバレッジが低い領域）
OVERSEAS_KEYWORDS = [
    "AI agent framework 2026",
    "harness engineering AI",
    "Claude Code tips",
    "OpenAI Codex agent",
    "AI monetization strategy",
    "MCP server tutorial",
    "A2A protocol agent",
    "local LLM deployment",
    "AI automation business",
    "vibe coding",
]


async def detect_overseas_trends() -> list:
    """英語で話題だが日本語記事がまだないトピックを検出"""
    try:
        from tools.tavily_client import search_tavily
    except ImportError:
        logger.warning("tavily_client not available")
        return []

    findings = []
    for kw in OVERSEAS_KEYWORDS:
        try:
            # 英語で検索
            en_results = await search_tavily(kw, search_depth="basic", max_results=5)
            if not en_results:
                continue

            # 同じトピックを日本語で検索
            jp_query = kw  # Tavilyは自動翻訳しないので英語のまま + 日本語サイト限定
            jp_results = await search_tavily(
                jp_query, search_depth="basic", max_results=3,
                include_domains=["note.com", "zenn.dev", "qiita.com", "hateblo.jp"],
            )

            jp_count = len(jp_results) if jp_results else 0

            if jp_count == 0:
                # 日本語記事なし → 先行者チャンス
                for r in en_results[:2]:
                    findings.append({
                        "keyword": kw,
                        "title": r.get("title", "")[:100],
                        "url": r.get("url", ""),
                        "jp_coverage": 0,
                        "opportunity": "high",
                    })
            elif jp_count <= 1:
                findings.append({
                    "keyword": kw,
                    "title": en_results[0].get("title", "")[:100],
                    "url": en_results[0].get("url", ""),
                    "jp_coverage": jp_count,
                    "opportunity": "medium",
                })
        except Exception as e:
            logger.debug(f"trend check failed for '{kw}': {e}")
            continue

    # DBに保存
    if findings:
        try:
            async with get_connection() as conn:
                for f in findings:
                    await conn.execute("""
                        INSERT INTO intel_items (source, keyword, title, url, importance_score, category, processed)
                        VALUES ('overseas_trend', $1, $2, $3, $4, 'overseas_exclusive', false)
                        ON CONFLICT DO NOTHING
                    """, f["keyword"], f["title"], f["url"],
                        0.9 if f["opportunity"] == "high" else 0.7)
        except Exception as e:
            logger.warning(f"overseas trend DB save failed: {e}")

    return findings
