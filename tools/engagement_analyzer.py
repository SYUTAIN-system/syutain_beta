"""
SYUTAINβ V25 エンゲージメント分析 → SNS投稿改善ループ
posting_queueのエンゲージメントデータを分析し、次の投稿生成に活かす。

- analyze_engagement_patterns(): 7日間のパターン分析（テーマ/時間帯/プラットフォーム）
- get_engagement_context_for_generation(): プロンプト注入用コンテキスト
- get_engagement_theme_weights(): テーマ選択の重み調整データ
- get_best_posting_times(): プラットフォーム別最適投稿時間
"""

import json
import logging
from datetime import datetime, timezone
from collections import defaultdict

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.engagement_analyzer")


def _engagement_score(likes: float, reposts: float, replies: float) -> float:
    """エンゲージメントスコア算出（repost×3, reply×5の重み付き）"""
    return likes + reposts * 3 + replies * 5


def _engagement_rate(likes: float, reposts: float, replies: float, impressions: float) -> float:
    """エンゲージメント率算出（impressionsがあれば使用、なければスコアのみ）"""
    if impressions and impressions > 0:
        return (likes + reposts + replies) / impressions
    return 0.0


async def analyze_engagement_patterns(days: int = 7) -> dict:
    """直近N日のエンゲージメントデータを分析してパターンを抽出する。

    Returns: {
        analyzed_at, period_days,
        high_performing: [{theme, platform, time_slot, avg_engagement, post_count}],
        low_performing: [{theme, platform, time_slot, avg_engagement, post_count}],
        best_posting_times: {platform: [times]},
        best_themes: [theme_categories],
        recommendations: [str],
        patterns: [{theme, platform, ...}]  (後方互換)
    }
    """
    try:
        async with get_connection() as conn:
            # --- 全投稿の生データ取得 ---
            rows = await conn.fetch(f"""
                SELECT id, platform, account, theme_category,
                       EXTRACT(HOUR FROM scheduled_at) as hour,
                       engagement_data, quality_score,
                       posted_at
                FROM posting_queue
                WHERE status = 'posted'
                  AND engagement_data IS NOT NULL
                  AND engagement_data::text != 'null'
                  AND posted_at > NOW() - INTERVAL '{days} days'
            """)

            if not rows:
                return {
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "period_days": days,
                    "high_performing": [],
                    "low_performing": [],
                    "best_posting_times": {},
                    "best_themes": [],
                    "recommendations": ["エンゲージメントデータが不足しています。データ蓄積を待ってください。"],
                    "patterns": [],
                }

            # --- 各投稿のスコアを計算 ---
            post_scores = []
            for r in rows:
                try:
                    ed = r["engagement_data"]
                    if isinstance(ed, str):
                        ed = json.loads(ed)
                    likes = int(ed.get("like_count", 0) or 0)
                    reposts = int(ed.get("repost_count", 0) or 0)
                    replies = int(ed.get("reply_count", 0) or 0)
                    impressions = int(ed.get("impression_count", 0) or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

                score = _engagement_score(likes, reposts, replies)
                rate = _engagement_rate(likes, reposts, replies, impressions)
                hour = int(r["hour"]) if r["hour"] is not None else 12

                post_scores.append({
                    "id": r["id"],
                    "platform": r["platform"],
                    "account": r["account"],
                    "theme": r["theme_category"] or "不明",
                    "hour": hour,
                    "time_slot": f"{hour:02d}:00",
                    "likes": likes,
                    "reposts": reposts,
                    "replies": replies,
                    "impressions": impressions,
                    "score": score,
                    "rate": rate,
                })

            if not post_scores:
                return {
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "period_days": days,
                    "high_performing": [], "low_performing": [],
                    "best_posting_times": {}, "best_themes": [],
                    "recommendations": ["エンゲージメントデータの解析に失敗しました。"],
                    "patterns": [],
                }

            # --- スコア順にソート、上位10%/下位10%を抽出 ---
            sorted_posts = sorted(post_scores, key=lambda x: x["score"], reverse=True)
            n = len(sorted_posts)
            top_n = max(1, n // 10)
            bottom_n = max(1, n // 10)

            high_performing = sorted_posts[:top_n]
            low_performing = sorted_posts[-bottom_n:]

            # --- テーマ × プラットフォーム別集計（後方互換 patterns） ---
            theme_platform_agg = defaultdict(lambda: {"likes": [], "reposts": [], "replies": [], "scores": []})
            for p in post_scores:
                key = (p["theme"], p["platform"])
                theme_platform_agg[key]["likes"].append(p["likes"])
                theme_platform_agg[key]["reposts"].append(p["reposts"])
                theme_platform_agg[key]["replies"].append(p["replies"])
                theme_platform_agg[key]["scores"].append(p["score"])

            patterns = []
            for (theme, platform), agg in theme_platform_agg.items():
                count = len(agg["scores"])
                if count < 2:
                    continue
                avg_likes = sum(agg["likes"]) / count
                avg_reposts = sum(agg["reposts"]) / count
                avg_replies = sum(agg["replies"]) / count
                avg_score = sum(agg["scores"]) / count
                patterns.append({
                    "theme": theme,
                    "platform": platform,
                    "post_count": count,
                    "avg_likes": round(avg_likes, 1),
                    "avg_reposts": round(avg_reposts, 1),
                    "avg_replies": round(avg_replies, 1),
                    "engagement_score": round(avg_score, 1),
                })
            patterns.sort(key=lambda x: x["engagement_score"], reverse=True)

            # --- プラットフォーム × 時間帯別集計 → best_posting_times ---
            time_agg = defaultdict(lambda: defaultdict(list))
            for p in post_scores:
                time_agg[p["platform"]][p["hour"]].append(p["score"])

            best_posting_times = {}
            for platform, hours in time_agg.items():
                hour_avg = []
                for hour, scores in hours.items():
                    if len(scores) >= 2:
                        hour_avg.append((hour, sum(scores) / len(scores)))
                hour_avg.sort(key=lambda x: x[1], reverse=True)
                # 上位5時間帯を返す
                best_posting_times[platform] = [f"{h:02d}:00" for h, _ in hour_avg[:5]]

            # --- best_themes（全プラットフォーム横断の高スコアテーマ）---
            theme_total = defaultdict(list)
            for p in post_scores:
                theme_total[p["theme"]].append(p["score"])
            theme_avg = [(t, sum(s) / len(s)) for t, s in theme_total.items() if len(s) >= 2]
            theme_avg.sort(key=lambda x: x[1], reverse=True)
            best_themes = [t for t, _ in theme_avg[:5]]

            # --- recommendations ---
            recommendations = []
            if best_themes:
                recommendations.append(f"高エンゲージメントテーマ: {', '.join(best_themes[:3])}")
            low_themes = [t for t, avg in theme_avg[-3:] if avg < 1.0] if theme_avg else []
            if low_themes:
                recommendations.append(f"低パフォーマンステーマ（頻度を下げる）: {', '.join(low_themes)}")
            for platform, times in best_posting_times.items():
                if times:
                    recommendations.append(f"{platform}の好反応時間帯: {', '.join(times[:3])}")
            if high_performing:
                top = high_performing[0]
                recommendations.append(
                    f"最高スコア投稿: {top['theme']}/{top['platform']} "
                    f"(いいね{top['likes']} RT{top['reposts']} リプ{top['replies']})"
                )

            return {
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "period_days": days,
                "total_posts_analyzed": n,
                "high_performing": [
                    {"theme": p["theme"], "platform": p["platform"],
                     "time_slot": p["time_slot"], "score": round(p["score"], 1),
                     "likes": p["likes"], "reposts": p["reposts"], "replies": p["replies"]}
                    for p in high_performing
                ],
                "low_performing": [
                    {"theme": p["theme"], "platform": p["platform"],
                     "time_slot": p["time_slot"], "score": round(p["score"], 1)}
                    for p in low_performing
                ],
                "best_posting_times": best_posting_times,
                "best_themes": best_themes,
                "recommendations": recommendations,
                "patterns": patterns,
                "top_themes": [p["theme"] for p in patterns[:5] if p["theme"]],
                "low_themes": low_themes,
            }
    except Exception as e:
        logger.error(f"エンゲージメント分析失敗: {e}")
        return {"error": str(e)}


async def get_top_performing_patterns(limit: int = 10) -> list:
    """トップパフォーマンスのパターンを返す"""
    result = await analyze_engagement_patterns()
    return result.get("patterns", [])[:limit]


async def get_engagement_theme_weights() -> dict:
    """テーマ選択用のエンゲージメント重みを返す。

    Returns: {theme: weight_multiplier} (1.0=平均、2.0=高パフォ、0.5=低パフォ)
    """
    try:
        result = await analyze_engagement_patterns()
        patterns = result.get("patterns", [])
        if not patterns:
            return {}

        # 全テーマの平均スコアを計算
        scores = [p["engagement_score"] for p in patterns]
        if not scores:
            return {}
        avg_score = sum(scores) / len(scores)
        if avg_score == 0:
            return {}

        weights = {}
        for p in patterns:
            theme = p["theme"]
            ratio = p["engagement_score"] / avg_score
            # 上限2.0、下限0.5にクリップ
            weights[theme] = round(max(0.5, min(2.0, ratio)), 2)

        return weights
    except Exception as e:
        logger.warning(f"エンゲージメント重み計算失敗: {e}")
        return {}


async def get_best_posting_times() -> dict:
    """プラットフォーム別の最適投稿時間を返す。

    Returns: {platform: [time_strings]}
    """
    try:
        result = await analyze_engagement_patterns()
        return result.get("best_posting_times", {})
    except Exception as e:
        logger.warning(f"最適投稿時間取得失敗: {e}")
        return {}


async def get_engagement_context_for_generation() -> str:
    """SNS投稿生成プロンプトに注入するエンゲージメントコンテキスト"""
    try:
        result = await analyze_engagement_patterns()
        patterns = result.get("patterns", [])
        if not patterns:
            return ""

        lines = ["【直近7日のエンゲージメント傾向】"]
        for p in patterns[:5]:
            lines.append(
                f"- {p['theme']}({p['platform']}): "
                f"いいね{p['avg_likes']} RT{p['avg_reposts']} リプ{p['avg_replies']} "
                f"(スコア{p['engagement_score']})"
            )

        recommendations = result.get("recommendations", [])
        if recommendations:
            lines.append("\n【改善ヒント】")
            for r in recommendations[:3]:
                lines.append(f"- {r}")

        low = result.get("low_themes", [])
        if low:
            lines.append(f"\n避けるべきテーマ: {', '.join(low)}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"エンゲージメントコンテキスト生成失敗: {e}")
        return ""


async def run_daily_analysis() -> dict:
    """日次エンゲージメント分析（スケジューラから呼ばれる）。結果をevent_logに保存。"""
    try:
        from tools.event_logger import log_event

        result = await analyze_engagement_patterns(days=7)

        if not result.get("error"):
            await log_event(
                "engagement.daily_analysis",
                "analytics",
                {
                    "period_days": result.get("period_days", 7),
                    "total_posts": result.get("total_posts_analyzed", 0),
                    "best_themes": result.get("best_themes", []),
                    "low_themes": result.get("low_themes", []),
                    "best_posting_times": result.get("best_posting_times", {}),
                    "recommendations": result.get("recommendations", []),
                    "high_performing_count": len(result.get("high_performing", [])),
                    "low_performing_count": len(result.get("low_performing", [])),
                },
                severity="info",
            )
            logger.info(
                f"日次エンゲージメント分析完了: {result.get('total_posts_analyzed', 0)}件分析, "
                f"推奨テーマ={result.get('best_themes', [])[:3]}"
            )

        return result
    except Exception as e:
        logger.error(f"日次エンゲージメント分析失敗: {e}")
        return {"error": str(e)}
