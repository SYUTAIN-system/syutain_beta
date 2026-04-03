"""
SYUTAINβ V27 バズアカウント分析
Jina Search APIで競合・トレンドSNS投稿を収集し、バズパターンを抽出。
sns_batch.pyのテーマ選定、content_pipelineのネタ選定に反映する。

スケジュール: 毎週月曜 07:30 JST
API呼び出し: Jina Search 4クエリ × 4サイト = 最大16回 + LLM 2回
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

import os

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm

logger = logging.getLogger("syutain.buzz_analyzer")

JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_SEARCH_URL = "https://s.jina.ai"

# 検索クエリ（AI関連のバズりやすいテーマ）
SEARCH_QUERIES = [
    "AI 活用 話題",
    "AI エージェント 最新",
    "Claude Code 活用",
    "AIツール おすすめ",
]

# サイトフィルタ（site:で絞る）
SITE_FILTERS = [
    "note.com",
    "x.com",
    "qiita.com",
    "zenn.dev",
]

# Jina Search 1回あたりの概算コスト（円）
_JINA_SEARCH_COST_JPY = float(os.getenv("JINA_SEARCH_COST_JPY", "0.5"))


async def _jina_search(query: str, site: Optional[str] = None, max_results: int = 5) -> list[dict]:
    """Jina Search APIで検索。site指定でドメイン絞り込み。

    Returns: [{"title": str, "url": str, "snippet": str}, ...]
    """
    full_query = f"site:{site} {query}" if site else query

    headers = {
        "Accept": "application/json",
        "X-Retain-Images": "none",
    }
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{JINA_SEARCH_URL}/{full_query}",
                headers=headers,
            )

            if resp.status_code == 429:
                logger.warning(f"Jina Search 429 rate limit: {full_query}")
                return []

            resp.raise_for_status()

            # 予算記録
            try:
                from tools.budget_guard import get_budget_guard
                bg = get_budget_guard()
                await bg.record_spend(
                    amount_jpy=_JINA_SEARCH_COST_JPY,
                    model="jina-search",
                    tier="info",
                    is_info_collection=True,
                )
            except Exception:
                pass

            if "application/json" in resp.headers.get("content-type", ""):
                data = resp.json()
                results = data.get("data", [])
                if isinstance(results, list):
                    return [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "snippet": r.get("description", r.get("content", ""))[:500],
                        }
                        for r in results[:max_results]
                    ]
            # テキスト応答のフォールバック
            return []

    except Exception as e:
        logger.debug(f"Jina Search失敗 ({full_query}): {e}")
        return []


async def _collect_posts() -> list[dict]:
    """全クエリ×サイトで検索し、投稿を収集。

    API呼び出しを最小化: 各クエリにつきサイトを1つランダム選択（計4回）。
    + 全サイト横断の汎用検索1回 = 計5回。
    """
    import random
    all_posts = []

    # 各クエリに対しランダムにサイトを割り当て（重複回避）
    sites_shuffled = SITE_FILTERS.copy()
    random.shuffle(sites_shuffled)

    tasks = []
    for i, query in enumerate(SEARCH_QUERIES):
        site = sites_shuffled[i % len(sites_shuffled)]
        tasks.append(_jina_search(query, site=site, max_results=5))

    # サイト指定なしの汎用検索（バズっている投稿をキャッチ）
    tasks.append(_jina_search("AI 最新トレンド 2026", site=None, max_results=5))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls = set()
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug(f"検索タスク {i} 失敗: {result}")
            continue
        for post in result:
            url = post.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_posts.append(post)

    logger.info(f"バズ分析: {len(all_posts)}件の投稿を収集（API {len(tasks)}回）")
    return all_posts


async def _load_own_posting_history() -> list[str]:
    """SYUTAINβの直近7日のSNS投稿テーマを取得"""
    themes = []
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT theme FROM posting_queue
                   WHERE scheduled_at > NOW() - INTERVAL '7 days'
                   AND status IN ('posted', 'queued')
                   ORDER BY scheduled_at DESC
                   LIMIT 100""",
            )
            themes = [r["theme"] for r in rows if r.get("theme")]
    except Exception as e:
        logger.debug(f"投稿履歴取得失敗: {e}")
    return themes


async def _analyze_with_llm(posts: list[dict], own_themes: list[str]) -> dict:
    """LLMでバズパターンを分析し、構造化された結果を返す。

    Returns: {
        trending_topics: [str],
        effective_formats: [{"format": str, "example": str, "why_works": str}],
        language_patterns: [str],
        content_gaps: [str],
        recommendations: [str],
    }
    """
    # 投稿データを圧縮してプロンプトに入れる
    posts_text = "\n---\n".join(
        f"[{p.get('url', 'N/A')}]\nタイトル: {p.get('title', 'N/A')}\n抜粋: {p.get('snippet', '')[:300]}"
        for p in posts[:20]  # 最大20件（トークン節約）
    )

    own_themes_text = ", ".join(own_themes[:30]) if own_themes else "（投稿履歴なし）"

    model_sel = choose_best_model_v6(
        task_type="analysis",
        quality="medium",
        budget_sensitive=True,
        needs_japanese=True,
    )

    prompt = f"""以下はAI関連のSNS投稿（note.com、X、Qiita、Zenn等）から収集したバズっている記事です。
パターンを分析し、以下のJSON形式で出力してください。

## 収集した投稿
{posts_text}

## SYUTAINβの直近7日の投稿テーマ
{own_themes_text}

## 出力形式（JSON）
{{
  "trending_topics": ["今バズっているトピック5つ"],
  "effective_formats": [
    {{"format": "形式名", "example": "具体例", "why_works": "なぜバズるか"}}
  ],
  "language_patterns": ["エンゲージメントを高める言い回し・構造パターン5つ"],
  "content_gaps": ["競合が扱っているがSYUTAINβが扱っていないテーマ3つ"],
  "recommendations": ["次週のSNS投稿・記事で取り入れるべきアクション5つ"]
}}

JSONのみ出力。説明不要。"""

    try:
        result = await call_llm(
            prompt=prompt,
            system_prompt=(
                "あなたはSNSマーケティング分析の専門家です。"
                "AI・テック系の日本語SNS投稿のバズパターンを分析します。"
                "必ずJSON形式で出力してください。"
            ),
            model_selection=model_sel,
        )

        text = result.get("text", "")

        # JSONを抽出（```json...```やテキスト混在対応）
        json_str = text
        if "```" in text:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                json_str = match.group(1)

        # JSON先頭の{を見つける
        brace_start = json_str.find("{")
        if brace_start >= 0:
            json_str = json_str[brace_start:]

        parsed = json.loads(json_str)
        return {
            "trending_topics": parsed.get("trending_topics", [])[:10],
            "effective_formats": parsed.get("effective_formats", [])[:5],
            "language_patterns": parsed.get("language_patterns", [])[:10],
            "content_gaps": parsed.get("content_gaps", [])[:5],
            "recommendations": parsed.get("recommendations", [])[:10],
        }

    except json.JSONDecodeError:
        logger.warning("バズ分析LLM出力のJSON解析失敗、フォールバック")
        return {
            "trending_topics": [],
            "effective_formats": [],
            "language_patterns": [],
            "content_gaps": [],
            "recommendations": [],
            "_raw": text[:500] if 'text' in dir() else "",
        }
    except Exception as e:
        logger.error(f"バズ分析LLM呼び出し失敗: {e}")
        return {
            "trending_topics": [],
            "effective_formats": [],
            "language_patterns": [],
            "content_gaps": [],
            "recommendations": [],
        }


async def analyze_buzz_accounts() -> dict:
    """バズアカウント分析のメインエントリポイント。

    1. Jina Searchで競合投稿を収集
    2. SYUTAINβの投稿履歴を取得
    3. LLMでパターン分析
    4. event_logに保存
    5. 結果を返す（sns_batch, content_pipelineが参照）

    Returns: {
        analyzed_at: str,
        posts_collected: int,
        trending_topics: [str],
        effective_formats: [...],
        language_patterns: [str],
        content_gaps: [str],
        recommendations: [str],
    }
    """
    analyzed_at = datetime.now(timezone.utc).isoformat()

    # 1. 投稿収集
    posts = await _collect_posts()
    if not posts:
        logger.warning("バズ分析: 投稿収集結果が0件")
        return {
            "analyzed_at": analyzed_at,
            "posts_collected": 0,
            "trending_topics": [],
            "effective_formats": [],
            "language_patterns": [],
            "content_gaps": [],
            "recommendations": [],
        }

    # 2. 自社投稿履歴取得
    own_themes = await _load_own_posting_history()

    # 3. LLM分析
    analysis = await _analyze_with_llm(posts, own_themes)

    # 結果を構築
    result = {
        "analyzed_at": analyzed_at,
        "posts_collected": len(posts),
        **analysis,
    }

    # 4. event_logに保存
    try:
        from tools.event_logger import log_event
        await log_event("buzz_analysis.completed", "sns", {
            "posts_collected": len(posts),
            "trending_topics": result.get("trending_topics", []),
            "content_gaps": result.get("content_gaps", []),
            "recommendations_count": len(result.get("recommendations", [])),
        })
    except Exception as e:
        logger.debug(f"バズ分析イベント記録失敗: {e}")

    # 5. DBに最新分析結果をキャッシュ（sns_batch/content_pipeline参照用）
    try:
        await _save_analysis_cache(result)
    except Exception as e:
        logger.debug(f"バズ分析キャッシュ保存失敗: {e}")

    logger.info(
        f"バズ分析完了: {len(posts)}件収集, "
        f"トレンド{len(result.get('trending_topics', []))}件, "
        f"ギャップ{len(result.get('content_gaps', []))}件"
    )

    return result


# 後方互換: 旧関数名を維持
async def analyze_buzz_patterns() -> dict:
    """後方互換エイリアス"""
    return await analyze_buzz_accounts()


async def _save_analysis_cache(result: dict) -> None:
    """分析結果をevent_logにキャッシュとして保存（最新1件をクエリで取得可能）"""
    try:
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO event_log
                   (event_type, category, severity, source_node, payload)
                   VALUES ($1, $2, $3, $4, $5)""",
                "buzz_analysis.cache",
                "sns",
                "info",
                os.getenv("THIS_NODE", "alpha"),
                json.dumps(result, ensure_ascii=False, default=str),
            )
    except Exception as e:
        logger.debug(f"キャッシュ保存失敗: {e}")


async def get_latest_buzz_analysis() -> Optional[dict]:
    """最新のバズ分析結果を取得（sns_batch, content_pipelineから呼ばれる）。

    Returns: analyze_buzz_accounts()の戻り値と同じ構造、またはNone
    """
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT payload FROM event_log
                   WHERE event_type = 'buzz_analysis.cache'
                   AND created_at > NOW() - INTERVAL '14 days'
                   ORDER BY created_at DESC LIMIT 1""",
            )
            if row:
                return json.loads(row["payload"])
    except Exception as e:
        logger.debug(f"バズ分析キャッシュ取得失敗: {e}")
    return None


async def get_buzz_theme_boost() -> dict[str, float]:
    """バズ分析結果からテーマブースト重みを生成。

    sns_batch.py の _pick_theme() の engagement_weights に渡す用。
    trending_topicsに含まれるキーワードに一致するTHEME_POOLテーマの重みを上げる。

    Returns: {"AI技術": 1.5, "ビジネス": 1.3, ...}
    """
    analysis = await get_latest_buzz_analysis()
    if not analysis:
        return {}

    # THEME_POOL のキーワードとtrending_topicsのマッチング
    from brain_alpha.sns_batch import THEME_POOL

    # トレンドトピックのキーワードを展開
    trending = " ".join(analysis.get("trending_topics", []))
    gaps = " ".join(analysis.get("content_gaps", []))
    combined_signal = trending + " " + gaps

    # テーマ→バズ関連度のキーワードマッピング
    theme_keywords = {
        "AI技術": ["AI", "LLM", "GPT", "Claude", "Gemini", "モデル", "推論", "生成AI"],
        "VTuber業界": ["VTuber", "バーチャル", "配信", "ストリーマー"],
        "哲学/思考": ["哲学", "思考", "倫理", "人間", "意識", "存在"],
        "開発進捗": ["開発", "プログラミング", "コード", "エンジニア", "実装"],
        "ビジネス": ["ビジネス", "起業", "収益", "マーケ", "戦略", "副業"],
        "日常": ["日常", "生活", "働き方"],
        "映画/映像": ["映画", "映像", "動画", "クリエイター"],
        "音楽/趣味": ["音楽", "趣味"],
        "カメラ/写真": ["カメラ", "写真"],
        "雑談": ["雑談"],
        "業界批評": ["業界", "批評", "炎上", "問題"],
        "自己内省": ["内省", "自己", "振り返り"],
    }

    boosts = {}
    for theme in THEME_POOL:
        keywords = theme_keywords.get(theme, [theme])
        match_count = sum(1 for kw in keywords if kw in combined_signal)
        if match_count > 0:
            # マッチ数に応じてブースト（1.2〜2.0）
            boosts[theme] = min(2.0, 1.0 + match_count * 0.2)

    return boosts


async def get_buzz_content_suggestions() -> list[str]:
    """バズ分析結果からcontent_pipelineのテーマ候補を生成。

    content_pipeline.py の Stage 1 ネタ選定で参照。

    Returns: テーマ文字列のリスト（最大5件）
    """
    analysis = await get_latest_buzz_analysis()
    if not analysis:
        return []

    suggestions = []

    # content_gapsを最優先（競合がやってて自分がやってないテーマ）
    for gap in analysis.get("content_gaps", []):
        if gap and len(gap) > 2:
            suggestions.append(gap)

    # trending_topicsから補完
    for topic in analysis.get("trending_topics", []):
        if topic and len(topic) > 2 and topic not in suggestions:
            suggestions.append(topic)

    return suggestions[:5]
