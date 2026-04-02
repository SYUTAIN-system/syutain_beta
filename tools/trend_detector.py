"""
SYUTAINβ 海外トレンド先取り検出 (trend_detector)

英語圏で話題だが日本語記事がまだ少ないAIトピックを検出する。
既存のintel_itemsデータを最大限活用し、Tavily APIは日本語検証のみに使用（予算節約）。

検出フロー:
1. intel_items（直近48h, 英語ソース）からトピックを抽出
2. 類似トピックをクラスタリング
3. 各クラスタについてTavily日本語検索で日本語記事の有無を確認
4. gap_score（英語記事数 vs 日本語記事数）を算出
5. 高gap_scoreのトピックをintel_itemsに保存 + Discord通知
"""

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("syutain.trend_detector")

# 英語ソースの判定用プレフィックス
ENGLISH_SOURCES = (
    "tavily", "rss:openai", "rss:anthropic", "rss:google",
    "rss:huggingface", "youtube", "jina", "gmail",
)

# トピック抽出時に除外するストップワード
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall",
    "and", "or", "but", "not", "no", "nor",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "over",
    "this", "that", "these", "those", "it", "its",
    "how", "what", "which", "who", "whom", "when", "where", "why",
    "new", "more", "most", "very", "just", "now", "here",
    "all", "each", "every", "both", "few", "many", "much",
    "also", "than", "then", "so", "if", "as", "out",
    "ai", "based", "using", "use", "used", "like", "get",
}

# トレンド検出対象のAI関連キーフレーズ（2語以上の複合語を優先抽出）
KEY_PHRASES = [
    "agent protocol", "a2a protocol", "mcp protocol", "model context protocol",
    "computer use", "tool use", "function calling",
    "reasoning model", "chain of thought", "tree of thought",
    "code generation", "code review", "code assistant",
    "multimodal", "vision language", "text to image", "text to video",
    "text to speech", "speech to text", "voice cloning",
    "fine tuning", "fine-tuning", "lora", "qlora", "gguf",
    "rag", "retrieval augmented", "vector database", "embeddings",
    "prompt engineering", "prompt injection", "jailbreak",
    "ai safety", "ai alignment", "red teaming",
    "open source", "open weight", "local llm",
    "benchmark", "evaluation", "leaderboard",
    "api pricing", "rate limit", "context window",
    "ai agent", "autonomous agent", "multi agent",
    "world model", "reward model", "reinforcement learning",
]


def _extract_topics_from_title(title: str) -> list[str]:
    """タイトルからトピックキーワード/フレーズを抽出する"""
    if not title:
        return []

    title_lower = title.lower()
    topics = []

    # 1. キーフレーズマッチング（複合語優先）
    for phrase in KEY_PHRASES:
        if phrase in title_lower:
            topics.append(phrase)

    # 2. 固有名詞抽出（大文字始まりの単語、バージョン番号付き）
    # 例: "GPT-5", "Claude 4", "Gemini 2.0", "DeepSeek-V4"
    proper_nouns = re.findall(
        r'\b([A-Z][a-zA-Z]*(?:[-\s]\d+(?:\.\d+)?)?(?:[-\s][A-Z][a-zA-Z]*)?)\b',
        title,
    )
    for noun in proper_nouns:
        noun_lower = noun.lower().strip()
        if noun_lower not in STOP_WORDS and len(noun_lower) >= 3:
            topics.append(noun_lower)

    # 3. テクニカルターム抽出（ハイフン付き / 大文字略語）
    tech_terms = re.findall(r'\b([A-Z]{2,}(?:-[A-Z0-9]+)*)\b', title)
    for term in tech_terms:
        term_lower = term.lower()
        if term_lower not in STOP_WORDS and len(term_lower) >= 2:
            topics.append(term_lower)

    return list(set(topics))


def _cluster_topics(topic_counts: Counter, min_count: int = 2) -> list[dict]:
    """類似トピックをクラスタリングし、出現頻度でソートする。

    Returns: [{"topic": str, "count": int, "variants": [str]}]
    """
    clusters = []
    processed = set()

    # 頻度順にソート
    sorted_topics = topic_counts.most_common()

    for topic, count in sorted_topics:
        if topic in processed:
            continue
        if count < min_count:
            continue

        # 類似トピックを集約（部分文字列マッチ）
        cluster = {"topic": topic, "count": count, "variants": [topic]}
        processed.add(topic)

        for other_topic, other_count in sorted_topics:
            if other_topic in processed:
                continue
            # 一方が他方を含む場合は同クラスタ
            if (topic in other_topic or other_topic in topic) and topic != other_topic:
                cluster["count"] += other_count
                cluster["variants"].append(other_topic)
                processed.add(other_topic)

        clusters.append(cluster)

    # クラスタをカウント降順でソート
    clusters.sort(key=lambda c: c["count"], reverse=True)
    return clusters


async def _get_recent_english_items(hours: int = 48) -> list[dict]:
    """直近N時間の英語ソースintel_itemsを取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT id, source, title, summary, url, importance_score, category
                FROM intel_items
                WHERE created_at > NOW() - make_interval(hours => $1)
                ORDER BY importance_score DESC, created_at DESC
                LIMIT 200""",
                hours,
            )
            items = []
            for r in rows:
                source = r["source"] or ""
                # 英語ソースのみフィルタ
                if any(source.startswith(prefix) for prefix in ENGLISH_SOURCES):
                    items.append(dict(r))
            return items
    except Exception as e:
        logger.error(f"英語intel_items取得失敗: {e}")
        return []


async def _search_japanese_articles(topic: str, max_results: int = 5) -> list[dict]:
    """Tavilyで日本語記事を検索（予算節約: basicモード、少数結果）"""
    try:
        from tools.tavily_client import TavilyClient
        client = TavilyClient()

        # 日本語ドメインで検索
        result = await client.search(
            query=f"{topic} AI",
            max_results=max_results,
            search_depth="basic",
            include_answer=False,
            include_domains=[
                "note.com", "qiita.com", "zenn.dev", "gigazine.net",
                "itmedia.co.jp", "impress.co.jp", "ascii.jp",
                "atmarkit.itmedia.co.jp", "ainow.ai",
            ],
        )
        return result.get("results", [])
    except Exception as e:
        logger.warning(f"日本語記事検索失敗 ({topic}): {e}")
        return []


def _calculate_gap_score(english_count: int, japanese_count: int) -> float:
    """英語/日本語ギャップスコアを計算 (0.0-1.0)

    - 英語記事が多く日本語記事が0 → 高スコア
    - 英語記事が多く日本語記事も多い → 低スコア
    - 英語記事が少ない → 低スコア（まだトレンドではない）
    """
    if english_count == 0:
        return 0.0

    # 英語のカバレッジ（多いほど高い、最大1.0）
    en_factor = min(1.0, english_count / 5.0)

    # 日本語のギャップ（少ないほど高い）
    if japanese_count == 0:
        jp_gap = 1.0
    elif japanese_count <= 1:
        jp_gap = 0.7
    elif japanese_count <= 3:
        jp_gap = 0.3
    else:
        jp_gap = 0.0

    score = en_factor * jp_gap
    return round(min(1.0, max(0.0, score)), 3)


def _suggest_angle(topic: str, sample_titles: list[str]) -> str:
    """トピックからnote記事の推奨アングルを提案"""
    topic_lower = topic.lower()

    # カテゴリ別のアングル提案
    if any(kw in topic_lower for kw in ["agent", "mcp", "a2a", "protocol"]):
        return "【AIエージェント最前線】海外で注目の新技術を非エンジニア向けに解説"
    elif any(kw in topic_lower for kw in ["safety", "alignment", "red team"]):
        return "【AI安全性】海外の最新議論を日本のクリエイター視点で読み解く"
    elif any(kw in topic_lower for kw in ["fine-tun", "lora", "qlora", "gguf", "local"]):
        return "【AIカスタマイズ】自分専用AIを作る海外の最新手法を紹介"
    elif any(kw in topic_lower for kw in ["multimodal", "vision", "image", "video"]):
        return "【マルチモーダルAI】画像・動画生成の海外最新動向とクリエイター活用法"
    elif any(kw in topic_lower for kw in ["pricing", "api", "cost", "free"]):
        return "【AIコスト戦略】海外で話題のコスト削減テクニックを紹介"
    elif any(kw in topic_lower for kw in ["benchmark", "evaluation", "leaderboard"]):
        return "【AIモデル比較】海外の最新ベンチマーク結果を分かりやすく解説"
    else:
        return f"【海外AI速報】{topic}の最新動向と日本での活用可能性"


async def detect_untapped_trends(
    hours: int = 48,
    max_topics: int = 10,
    min_english_count: int = 2,
    min_gap_score: float = 0.3,
) -> list[dict]:
    """英語圏で話題だが日本語記事が少ないAIトピックを検出する。

    Args:
        hours: 直近何時間のintel_itemsを対象とするか
        max_topics: 最大検出トピック数
        min_english_count: 英語記事の最低出現数
        min_gap_score: 最低ギャップスコア

    Returns: [{
        topic: str,
        english_sources: int,
        japanese_sources: int,
        gap_score: float,
        sample_title: str,
        recommended_angle: str,
        variants: [str],
    }]
    """
    logger.info(f"海外トレンド先取り検出開始 (直近{hours}時間)")

    # 1. 英語ソースのintel_itemsを取得
    english_items = await _get_recent_english_items(hours)
    if not english_items:
        logger.info("英語ソースのintel_itemsが0件 — 検出スキップ")
        return []

    logger.info(f"英語ソースintel_items: {len(english_items)}件")

    # 2. トピック抽出 + 出現頻度カウント
    topic_counter: Counter = Counter()
    topic_sample_titles: dict[str, list[str]] = {}

    for item in english_items:
        title = item.get("title", "") or ""
        topics = _extract_topics_from_title(title)
        for t in topics:
            topic_counter[t] += 1
            if t not in topic_sample_titles:
                topic_sample_titles[t] = []
            if len(topic_sample_titles[t]) < 3:
                topic_sample_titles[t].append(title)

    # 3. クラスタリング
    clusters = _cluster_topics(topic_counter, min_count=min_english_count)
    logger.info(f"トピッククラスタ: {len(clusters)}件 (min_count={min_english_count})")

    if not clusters:
        logger.info("有効なトピッククラスタが0件 — 検出スキップ")
        return []

    # 4. 上位クラスタについて日本語記事を検索
    results = []
    search_count = 0
    max_searches = min(len(clusters), max_topics + 5)  # 予算節約: 最大15検索

    for cluster in clusters[:max_searches]:
        topic = cluster["topic"]

        # Tavily API呼び出し（レート配慮）
        if search_count > 0:
            await asyncio.sleep(1.0)

        jp_articles = await _search_japanese_articles(topic)
        search_count += 1

        japanese_count = len(jp_articles)
        english_count = cluster["count"]
        gap_score = _calculate_gap_score(english_count, japanese_count)

        if gap_score >= min_gap_score:
            sample_titles = topic_sample_titles.get(topic, [])
            results.append({
                "topic": topic,
                "english_sources": english_count,
                "japanese_sources": japanese_count,
                "gap_score": gap_score,
                "sample_title": sample_titles[0] if sample_titles else "",
                "recommended_angle": _suggest_angle(topic, sample_titles),
                "variants": cluster["variants"],
            })

        # 十分な結果が集まったら終了
        if len(results) >= max_topics:
            break

    # gap_score降順でソート
    results.sort(key=lambda r: r["gap_score"], reverse=True)

    logger.info(f"海外トレンド先取り検出完了: {len(results)}件 (Tavily検索{search_count}回)")
    return results


async def run_trend_detection_and_save() -> dict:
    """トレンド検出を実行し、結果をintel_itemsに保存 + Discord通知する。

    スケジューラーから呼び出される統合関数。

    Returns: {"detected": int, "saved": int, "notified": int}
    """
    logger.info("=== 海外トレンド先取り検出パイプライン開始 ===")

    try:
        trends = await detect_untapped_trends()
    except Exception as e:
        logger.error(f"トレンド検出失敗: {e}")
        return {"detected": 0, "saved": 0, "notified": 0, "error": str(e)}

    if not trends:
        logger.info("検出トレンド0件 — 保存スキップ")
        return {"detected": 0, "saved": 0, "notified": 0}

    saved = 0
    notified = 0

    for trend in trends:
        # intel_itemsに保存
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO intel_items
                    (source, keyword, title, summary, url, importance_score, category, review_flag, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT DO NOTHING""",
                    "trend_detector",
                    trend["topic"],
                    f"[海外トレンド] {trend['topic']}",
                    (
                        f"英語記事{trend['english_sources']}件 / 日本語記事{trend['japanese_sources']}件 / "
                        f"ギャップスコア{trend['gap_score']:.2f}\n"
                        f"推奨アングル: {trend['recommended_angle']}\n"
                        f"参考タイトル: {trend['sample_title']}"
                    ),
                    "",  # url
                    min(1.0, 0.5 + trend["gap_score"] * 0.5),  # importance_score: 0.5-1.0
                    "ai_model",  # category
                    "actionable",  # review_flag: actionableで優先度を示す
                    json.dumps({
                        "trend_type": "untapped_overseas",
                        "gap_score": trend["gap_score"],
                        "english_sources": trend["english_sources"],
                        "japanese_sources": trend["japanese_sources"],
                        "variants": trend["variants"],
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False),
                )
                saved += 1
        except Exception as e:
            logger.warning(f"トレンド保存失敗 ({trend['topic']}): {e}")

        # 高gap_scoreはDiscord通知
        if trend["gap_score"] >= 0.5:
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"🔍 海外トレンド先取り検出\n"
                    f"トピック: **{trend['topic']}**\n"
                    f"英語記事: {trend['english_sources']}件 / 日本語記事: {trend['japanese_sources']}件\n"
                    f"ギャップスコア: {trend['gap_score']:.2f}\n"
                    f"推奨アングル: {trend['recommended_angle']}\n"
                    f"参考: {trend['sample_title'][:100]}"
                )
                notified += 1
            except Exception as e:
                logger.warning(f"トレンド通知失敗: {e}")

    # Brain-αハンドオフ（高スコアトレンドがある場合）
    high_score_trends = [t for t in trends if t["gap_score"] >= 0.5]
    if high_score_trends:
        try:
            from brain_alpha.escalation import handoff_to_alpha
            topics_summary = ", ".join(t["topic"] for t in high_score_trends[:3])
            await handoff_to_alpha(
                category="content",
                title=f"海外トレンド先取り: {topics_summary}",
                detail=(
                    f"日本語記事が少ない海外トレンド{len(high_score_trends)}件を検出。\n"
                    f"note記事化の優先候補として検討してください。"
                ),
                source_agent="trend_detector",
                context={"trends": high_score_trends[:5]},
            )
        except Exception as e:
            logger.warning(f"Brain-αハンドオフ失敗: {e}")

    # 判断根拠トレース
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO agent_reasoning_trace
                (agent_name, action, reasoning, confidence, context)
                VALUES ($1, $2, $3, $4, $5)""",
                "trend_detector",
                "detect_untapped_trends",
                f"海外トレンド先取り検出完了: {len(trends)}件検出, {saved}件保存, {notified}件通知",
                0.7,
                json.dumps({
                    "detected": len(trends),
                    "saved": saved,
                    "notified": notified,
                    "top_trends": [
                        {"topic": t["topic"], "gap_score": t["gap_score"]}
                        for t in trends[:5]
                    ],
                }, ensure_ascii=False),
            )
    except Exception:
        pass

    logger.info(f"=== 海外トレンド先取り検出パイプライン完了: 検出{len(trends)}件, 保存{saved}件, 通知{notified}件 ===")

    return {"detected": len(trends), "saved": saved, "notified": notified}
