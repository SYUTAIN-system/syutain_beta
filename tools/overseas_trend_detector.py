"""
SYUTAINβ V25 海外トレンド先取り検出
英語で出ているが日本語記事がまだないAI話題を検出し、先行者利益を狙う。
英語記事の内容を取得・要約してDBに保存し、記事生成パイプラインで活用可能にする。
"""

import json
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
    "autonomous AI system",
    "multi-agent orchestration",
    "LLM cost optimization",
    "AI safety guardrails",
    "non-coder AI development",
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
            jp_query = kw
            jp_results = await search_tavily(
                jp_query, search_depth="basic", max_results=3,
                include_domains=["note.com", "zenn.dev", "qiita.com", "hateblo.jp"],
            )

            jp_count = len(jp_results) if jp_results else 0

            if jp_count == 0:
                for r in en_results[:2]:
                    findings.append({
                        "keyword": kw,
                        "title": r.get("title", "")[:100],
                        "url": r.get("url", ""),
                        "content_snippet": r.get("content", "")[:500],
                        "jp_coverage": 0,
                        "opportunity": "high",
                    })
            elif jp_count <= 1:
                findings.append({
                    "keyword": kw,
                    "title": en_results[0].get("title", "")[:100],
                    "url": en_results[0].get("url", ""),
                    "content_snippet": en_results[0].get("content", "")[:500],
                    "jp_coverage": jp_count,
                    "opportunity": "medium",
                })
        except Exception as e:
            logger.debug(f"trend check failed for '{kw}': {e}")
            continue

    # DBに保存（content_snippetをsummaryに、メタデータも保存）
    if findings:
        try:
            async with get_connection() as conn:
                for f in findings:
                    await conn.execute("""
                        INSERT INTO intel_items
                        (source, keyword, title, url, summary, importance_score,
                         category, metadata, processed)
                        VALUES ('overseas_trend', $1, $2, $3, $4, $5,
                                'overseas_exclusive', $6, false)
                        ON CONFLICT DO NOTHING
                    """, f["keyword"], f["title"], f["url"],
                        f.get("content_snippet", ""),
                        0.9 if f["opportunity"] == "high" else 0.7,
                        json.dumps({
                            "jp_coverage": f["jp_coverage"],
                            "opportunity": f["opportunity"],
                            "language": "en",
                        }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"overseas trend DB save failed: {e}")

    return findings


async def fetch_and_summarize_english_article(url: str, keyword: str = "") -> dict:
    """英語記事の全文を取得し、日本語要約を生成してDBに保存する。
    記事生成パイプラインで「海外ソースからの情報」として活用可能。
    """
    result = {"success": False, "url": url, "summary_ja": "", "key_points": []}

    try:
        # 1. Jina Reader APIで全文取得
        from tools.jina_client import JinaClient
        jina = JinaClient()
        full_text = await jina.extract_markdown(url)
        if not full_text or len(full_text) < 100:
            result["error"] = "記事本文取得失敗"
            return result

        # 2. ローカルLLMで日本語要約+キーポイント抽出
        from tools.llm_router import call_llm, choose_best_model_v6
        model_info = choose_best_model_v6(
            task_type="analysis", quality="medium",
            budget_sensitive=True, needs_japanese=True,
        )

        prompt = f"""以下の英語記事を日本語で要約してください。

## 指示
1. 300字以内の日本語要約
2. キーポイント3-5個（箇条書き、各50字以内）
3. SYUTAINβ（自律型AIシステム）の改善に活かせる知見があれば明記
4. 日本の読者が知らないであろう情報を優先

## 出力形式（JSON）
{{"summary_ja": "要約文", "key_points": ["ポイント1", "ポイント2", ...], "system_insights": "システム改善への示唆（なければ空文字）"}}

## 記事本文（先頭3000字）
{full_text[:3000]}"""

        llm_result = await call_llm(
            prompt=prompt,
            system_prompt="英語技術記事を日本語で要約するエキスパート。",
            model=model_info.get("model"),
            node=model_info.get("node", "auto"),
        )

        response_text = llm_result.get("text", "")

        # JSON解析
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            parsed = json.loads(json_match.group())
            result["summary_ja"] = parsed.get("summary_ja", "")
            result["key_points"] = parsed.get("key_points", [])
            result["system_insights"] = parsed.get("system_insights", "")
            result["success"] = True
        else:
            # JSONパース失敗時はテキスト全体を要約として使用
            result["summary_ja"] = response_text[:300]
            result["success"] = True

        # 3. DBに保存（intel_itemsにenriched情報として）
        try:
            async with get_connection() as conn:
                await conn.execute("""
                    INSERT INTO intel_items
                    (source, keyword, title, url, summary, importance_score,
                     category, metadata, review_flag, processed)
                    VALUES ('english_article', $1, $2, $3, $4, 0.8,
                            'overseas_exclusive', $5, 'actionable', true)
                    ON CONFLICT DO NOTHING
                """,
                    keyword,
                    result["summary_ja"][:100],
                    url,
                    result["summary_ja"],
                    json.dumps({
                        "language": "en",
                        "key_points": result["key_points"],
                        "system_insights": result.get("system_insights", ""),
                        "full_text_length": len(full_text),
                        "summarized": True,
                    }, ensure_ascii=False),
                )
        except Exception as db_err:
            logger.warning(f"英語記事要約DB保存失敗: {db_err}")

    except Exception as e:
        result["error"] = str(e)
        logger.warning(f"英語記事取得・要約失敗 ({url}): {e}")

    return result


async def enrich_overseas_trends() -> int:
    """overseas_trendとしてDBに保存済みの未処理英語記事を取得・要約する。
    スケジューラから定期実行される想定。
    """
    enriched = 0
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, url, keyword FROM intel_items
                WHERE source = 'overseas_trend'
                AND processed = false
                AND url IS NOT NULL AND url != ''
                ORDER BY importance_score DESC
                LIMIT 3
            """)

            for row in rows:
                result = await fetch_and_summarize_english_article(
                    url=row["url"], keyword=row.get("keyword", "")
                )
                if result.get("success"):
                    # 元のレコードをprocessed=trueに更新
                    await conn.execute(
                        "UPDATE intel_items SET processed = true WHERE id = $1",
                        row["id"]
                    )
                    enriched += 1
                    logger.info(f"英語記事enriched: {row['url'][:60]}")

    except Exception as e:
        logger.warning(f"enrich_overseas_trends失敗: {e}")

    return enriched
