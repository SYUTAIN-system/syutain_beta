"""
SYUTAINβ エンゲージメント収集ツール

各SNSプラットフォーム（X, Bluesky, Threads）の投稿エンゲージメントデータを
定期的に取得し、posting_queue_engagementテーブルに保存する。

対応プラットフォーム:
  - X (Twitter): API v2 public_metrics (Free tierでは403制限あり)
  - Bluesky: AT Protocol getPostThread
  - Threads: Meta Graph API insights
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta

import httpx

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.engagement_collector")


def _extract_x_tweet_id(post_url: str) -> str | None:
    """X/TwitterのURLからtweet_idを抽出"""
    m = re.search(r'/status/(\d+)', post_url)
    return m.group(1) if m else None


def _extract_threads_media_id(post_url: str) -> str | None:
    """ThreadsのURLまたはDB保存値からmedia_idを抽出

    URLパターン: https://www.threads.net/@user/post/18099025459789952
    """
    m = re.search(r'/post/(\d+)', post_url)
    return m.group(1) if m else None


async def _fetch_x_engagement(post_url: str) -> dict:
    """X投稿のエンゲージメントを取得"""
    from tools.social_tools import get_x_engagement

    tweet_id = _extract_x_tweet_id(post_url)
    if not tweet_id:
        return {"error": f"tweet_id抽出失敗: {post_url}"}

    # accountをURLから推定
    account = "syutain"
    if "Sima_daichi" in post_url:
        account = "shimahara"

    result = await get_x_engagement(tweet_id, account=account)
    if "error" in result:
        return result

    return {
        "likes": result.get("like_count", 0),
        "reposts": result.get("repost_count", 0),
        "replies": result.get("reply_count", 0),
        "impressions": result.get("impression_count", 0),
    }


async def _fetch_bluesky_engagement(post_uri: str) -> dict:
    """Bluesky投稿のエンゲージメントを取得"""
    from tools.social_tools import get_bluesky_engagement

    result = await get_bluesky_engagement(post_uri)
    if "error" in result:
        return result

    return {
        "likes": result.get("like_count", 0),
        "reposts": result.get("repost_count", 0),
        "replies": result.get("reply_count", 0),
        "impressions": 0,  # Blueskyにはimpression指標なし
    }


async def _fetch_threads_engagement(post_url: str) -> dict:
    """Threads投稿のエンゲージメントを取得"""
    from tools.social_tools import get_threads_engagement

    media_id = _extract_threads_media_id(post_url)
    if not media_id:
        return {"error": f"media_id抽出失敗: {post_url}"}

    result = await get_threads_engagement(media_id)
    if "error" in result:
        return result

    return {
        "likes": result.get("like_count", 0),
        "reposts": result.get("repost_count", 0),
        "replies": result.get("reply_count", 0),
        "impressions": result.get("view_count", 0),
    }


# プラットフォーム別の取得関数マッピング
_PLATFORM_FETCHERS = {
    "x": _fetch_x_engagement,
    "bluesky": _fetch_bluesky_engagement,
    "threads": _fetch_threads_engagement,
}


async def collect_engagement(hours: int = 48) -> dict:
    """
    直近N時間のposted投稿のエンゲージメントを全プラットフォームから取得し、
    posting_queue_engagementテーブルに保存する。

    Args:
        hours: 遡る時間数（デフォルト48時間）

    Returns:
        {"total": int, "success": int, "failed": int, "skipped": int, "details": [...]}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "details": []}

    try:
        async with get_connection() as conn:
            # 直近N時間のposted投稿を取得（post_urlがあるもの）
            rows = await conn.fetch(
                """SELECT id, platform, post_url, posted_at
                FROM posting_queue
                WHERE status = 'posted'
                AND post_url IS NOT NULL
                AND posted_at >= $1
                ORDER BY posted_at DESC""",
                cutoff,
            )

            stats["total"] = len(rows)
            logger.info(f"エンゲージメント収集開始: 対象{len(rows)}件 (直近{hours}時間)")

            for row in rows:
                posting_id = row["id"]
                platform = row["platform"]
                post_url = row["post_url"]

                fetcher = _PLATFORM_FETCHERS.get(platform)
                if not fetcher:
                    logger.warning(f"未対応プラットフォーム: {platform} (id={posting_id})")
                    stats["skipped"] += 1
                    stats["details"].append({
                        "id": posting_id, "platform": platform,
                        "status": "skipped", "reason": "unsupported_platform",
                    })
                    continue

                try:
                    result = await fetcher(post_url)

                    if "error" in result:
                        logger.warning(
                            f"エンゲージメント取得失敗: {platform} id={posting_id} — {result['error']}"
                        )
                        stats["failed"] += 1
                        stats["details"].append({
                            "id": posting_id, "platform": platform,
                            "status": "failed", "error": str(result["error"])[:200],
                        })
                        continue

                    # posting_queue_engagementにUPSERTは不要（毎回INSERTして時系列で追跡）
                    await conn.execute(
                        """INSERT INTO posting_queue_engagement
                        (posting_queue_id, likes, reposts, replies, impressions)
                        VALUES ($1, $2, $3, $4, $5)""",
                        posting_id,
                        result.get("likes", 0),
                        result.get("reposts", 0),
                        result.get("replies", 0),
                        result.get("impressions", 0),
                    )

                    # posting_queue.engagement_dataにも最新データを保存
                    import json
                    await conn.execute(
                        """UPDATE posting_queue
                        SET engagement_data = $1::jsonb
                        WHERE id = $2""",
                        json.dumps({
                            "likes": result.get("likes", 0),
                            "reposts": result.get("reposts", 0),
                            "replies": result.get("replies", 0),
                            "impressions": result.get("impressions", 0),
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        }),
                        posting_id,
                    )

                    stats["success"] += 1
                    stats["details"].append({
                        "id": posting_id, "platform": platform,
                        "status": "success", **result,
                    })

                except Exception as e:
                    logger.error(f"エンゲージメント処理エラー: {platform} id={posting_id} — {e}")
                    stats["failed"] += 1
                    stats["details"].append({
                        "id": posting_id, "platform": platform,
                        "status": "error", "error": str(e)[:200],
                    })

    except Exception as e:
        logger.error(f"エンゲージメント収集全体エラー: {e}")
        stats["details"].append({"status": "fatal_error", "error": str(e)[:200]})

    # ログサマリー
    logger.info(
        f"エンゲージメント収集完了: "
        f"対象={stats['total']} 成功={stats['success']} "
        f"失敗={stats['failed']} スキップ={stats['skipped']}"
    )

    # event_logに記録
    try:
        from tools.event_logger import log_event
        await log_event(
            "engagement.collected", "sns",
            {
                "total": stats["total"],
                "success": stats["success"],
                "failed": stats["failed"],
                "skipped": stats["skipped"],
            },
        )
    except Exception:
        pass

    return stats


async def collect_single(posting_queue_id: int) -> dict:
    """特定のposting_queue IDのエンゲージメントを1件取得（テスト・手動用）"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id, platform, post_url FROM posting_queue WHERE id = $1",
                posting_queue_id,
            )
            if not row:
                return {"error": f"posting_queue_id={posting_queue_id} not found"}

            platform = row["platform"]
            post_url = row["post_url"]

            if not post_url:
                return {"error": "post_url is NULL"}

            fetcher = _PLATFORM_FETCHERS.get(platform)
            if not fetcher:
                return {"error": f"unsupported platform: {platform}"}

            return await fetcher(post_url)
    except Exception as e:
        return {"error": str(e)}
