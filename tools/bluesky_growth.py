"""
SYUTAINβ Bluesky Growth Tool

フォロワー拡大のための自動フォロー + フォローバック追跡システム。
AT Protocol APIを使用。

戦略:
  1. 自分の投稿にいいね/リポストしたユーザー（最高フォローバック率）
  2. 関連ハッシュタグで投稿しているユーザー
  3. フォロワー数100-10000の中規模アカウント
  4. 直近7日以内に投稿があるアクティブユーザーのみ
  5. 1日30人上限、30秒間隔（スパム回避）

フォローバック追跡:
  - 3日後にフォローバック確認
  - 7日後にフォローバックなければアンフォロー
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.bluesky_growth")

BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

# セッションキャッシュ
_session_cache = {"access_jwt": "", "did": "", "expires_at": 0.0}

DAILY_FOLLOW_LIMIT = 30
FOLLOW_INTERVAL_SEC = 30
FOLLOWBACK_CHECK_DAYS = 3
UNFOLLOW_AFTER_DAYS = 7

# 関連ハッシュタグ（検索キーワード）
SEARCH_KEYWORDS = [
    "#AI", "#個人開発", "#BuildInPublic", "#VTuber", "#映像制作",
    "AI開発", "個人開発者", "AIエージェント",
]

# フォロワー数フィルタ
MIN_FOLLOWERS = 100
MAX_FOLLOWERS = 10000


async def _get_session() -> tuple[str, str]:
    """Blueskyセッションをキャッシュ付きで取得"""
    import time as _time
    if _session_cache["access_jwt"] and _time.time() < _session_cache["expires_at"]:
        return _session_cache["access_jwt"], _session_cache["did"]

    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        raise ValueError("BLUESKY_HANDLE/BLUESKY_APP_PASSWORD未設定")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
        _session_cache["access_jwt"] = data["accessJwt"]
        _session_cache["did"] = data["did"]
        _session_cache["expires_at"] = _time.time() + 7000
        return data["accessJwt"], data["did"]


async def _api_get(client: httpx.AsyncClient, endpoint: str, params: dict = None) -> dict:
    """認証付きGETリクエスト"""
    jwt, _ = await _get_session()
    resp = await client.get(
        f"https://bsky.social/xrpc/{endpoint}",
        params=params or {},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    resp.raise_for_status()
    return resp.json()


async def _api_post(client: httpx.AsyncClient, endpoint: str, json_data: dict) -> dict:
    """認証付きPOSTリクエスト"""
    jwt, _ = await _get_session()
    resp = await client.post(
        f"https://bsky.social/xrpc/{endpoint}",
        json=json_data,
        headers={"Authorization": f"Bearer {jwt}"},
    )
    resp.raise_for_status()
    return resp.json()


async def _get_my_did() -> str:
    """自分のDIDを取得"""
    _, did = await _get_session()
    return did


async def _get_already_followed_dids() -> set[str]:
    """DB上で既にフォロー済み（アンフォローしていない）のDIDセットを返す"""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                "SELECT did FROM bluesky_follow_tracking WHERE unfollowed_at IS NULL"
            )
            return {row["did"] for row in rows}
    except Exception as e:
        logger.error(f"フォロー済みDID取得エラー: {e}")
        return set()


async def _get_current_following_dids(client: httpx.AsyncClient) -> set[str]:
    """API経由で現在フォロー中のDIDセットを取得"""
    my_did = await _get_my_did()
    following = set()
    cursor = None
    for _ in range(20):  # 最大2000人分
        params = {"actor": my_did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _api_get(client, "app.bsky.graph.getFollows", params)
            for f in data.get("follows", []):
                following.add(f.get("did", ""))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            logger.error(f"フォロー一覧取得エラー: {e}")
            break
    return following


async def _get_current_followers_dids(client: httpx.AsyncClient) -> set[str]:
    """API経由で現在のフォロワーのDIDセットを取得"""
    my_did = await _get_my_did()
    followers = set()
    cursor = None
    for _ in range(20):
        params = {"actor": my_did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _api_get(client, "app.bsky.graph.getFollowers", params)
            for f in data.get("followers", []):
                followers.add(f.get("did", ""))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            logger.error(f"フォロワー一覧取得エラー: {e}")
            break
    return followers


async def _get_profile(client: httpx.AsyncClient, did_or_handle: str) -> Optional[dict]:
    """ユーザープロフィールを取得"""
    try:
        data = await _api_get(client, "app.bsky.actor.getProfile", {"actor": did_or_handle})
        return data
    except Exception:
        return None


async def _is_active_user(client: httpx.AsyncClient, did: str) -> bool:
    """直近7日以内に投稿があるかチェック"""
    try:
        data = await _api_get(client, "app.bsky.feed.getAuthorFeed", {
            "actor": did, "limit": 1,
        })
        feed = data.get("feed", [])
        if not feed:
            return False
        post = feed[0].get("post", {}).get("record", {})
        created_at = post.get("createdAt", "")
        if not created_at:
            return False
        post_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - post_time) < timedelta(days=7)
    except Exception:
        return False


async def _discover_from_my_engagement(client: httpx.AsyncClient, max_targets: int) -> list[dict]:
    """自分の投稿にいいね/リポストしたユーザーを発見"""
    targets = []
    my_did = await _get_my_did()

    try:
        # 自分の最近の投稿を取得
        feed_data = await _api_get(client, "app.bsky.feed.getAuthorFeed", {
            "actor": my_did, "limit": 20,
        })
        for item in feed_data.get("feed", []):
            if len(targets) >= max_targets:
                break
            post = item.get("post", {})
            uri = post.get("uri", "")
            like_count = post.get("likeCount", 0)
            repost_count = post.get("repostCount", 0)

            if like_count == 0 and repost_count == 0:
                continue

            # いいねしたユーザーを取得
            try:
                likes_data = await _api_get(client, "app.bsky.feed.getLikes", {
                    "uri": uri, "limit": 50,
                })
                for like in likes_data.get("likes", []):
                    if len(targets) >= max_targets:
                        break
                    actor = like.get("actor", {})
                    did = actor.get("did", "")
                    if did and did != my_did:
                        targets.append({
                            "did": did,
                            "handle": actor.get("handle", ""),
                            "display_name": actor.get("displayName", ""),
                            "source": "liked_my_post",
                        })
            except Exception as e:
                logger.debug(f"いいねユーザー取得エラー: {e}")

            # リポストしたユーザーを取得
            try:
                reposts_data = await _api_get(client, "app.bsky.feed.getRepostedBy", {
                    "uri": uri, "limit": 50,
                })
                for actor in reposts_data.get("repostedBy", []):
                    if len(targets) >= max_targets:
                        break
                    did = actor.get("did", "")
                    if did and did != my_did:
                        targets.append({
                            "did": did,
                            "handle": actor.get("handle", ""),
                            "display_name": actor.get("displayName", ""),
                            "source": "reposted_my_post",
                        })
            except Exception as e:
                logger.debug(f"リポストユーザー取得エラー: {e}")

    except Exception as e:
        logger.error(f"自分のエンゲージメントからのターゲット発見エラー: {e}")

    return targets


async def _discover_from_hashtags(client: httpx.AsyncClient, max_targets: int) -> list[dict]:
    """関連ハッシュタグで投稿しているユーザーを発見"""
    targets = []
    seen_dids = set()
    my_did = await _get_my_did()

    for keyword in SEARCH_KEYWORDS:
        if len(targets) >= max_targets:
            break
        try:
            data = await _api_get(client, "app.bsky.feed.searchPosts", {
                "q": keyword, "limit": 25,
            })
            for item in data.get("posts", []):
                if len(targets) >= max_targets:
                    break
                author = item.get("author", {})
                did = author.get("did", "")
                if did and did != my_did and did not in seen_dids:
                    seen_dids.add(did)
                    source_tag = keyword.lstrip("#").lower().replace(" ", "_")
                    targets.append({
                        "did": did,
                        "handle": author.get("handle", ""),
                        "display_name": author.get("displayName", ""),
                        "source": f"hashtag_{source_tag}",
                    })
        except Exception as e:
            logger.debug(f"ハッシュタグ検索エラー ({keyword}): {e}")

    return targets


async def discover_targets(max_targets: int = 30) -> list[dict]:
    """
    フォロー対象ユーザーを発見する。

    優先順位:
      1. 自分の投稿にいいね/リポストしたユーザー
      2. 関連ハッシュタグで投稿しているユーザー

    フィルタ:
      - 自分自身を除外
      - 既にフォロー済みを除外
      - フォロワー数100-10000の中規模アカウント
      - 直近7日以内に投稿があるアクティブユーザー

    Returns:
        list[dict]: [{did, handle, display_name, source, followers_count}, ...]
    """
    my_did = await _get_my_did()
    already_followed = await _get_already_followed_dids()

    async with httpx.AsyncClient(timeout=20) as client:
        current_following = await _get_current_following_dids(client)
        exclude_dids = already_followed | current_following | {my_did}

        # Phase 1: エンゲージメントからの発見
        raw_targets = await _discover_from_my_engagement(client, max_targets * 2)

        # Phase 2: ハッシュタグからの発見
        remaining = max(0, max_targets * 2 - len(raw_targets))
        if remaining > 0:
            hashtag_targets = await _discover_from_hashtags(client, remaining)
            raw_targets.extend(hashtag_targets)

        # 重複排除
        seen = set()
        unique_targets = []
        for t in raw_targets:
            if t["did"] not in seen and t["did"] not in exclude_dids:
                seen.add(t["did"])
                unique_targets.append(t)

        # フィルタリング: フォロワー数 + アクティブチェック
        filtered = []
        for t in unique_targets:
            if len(filtered) >= max_targets:
                break
            try:
                profile = await _get_profile(client, t["did"])
                if not profile:
                    continue
                followers_count = profile.get("followersCount", 0)
                if followers_count < MIN_FOLLOWERS or followers_count > MAX_FOLLOWERS:
                    logger.debug(f"スキップ(フォロワー数): {t['handle']} ({followers_count})")
                    continue

                # アクティブチェック
                if not await _is_active_user(client, t["did"]):
                    logger.debug(f"スキップ(非アクティブ): {t['handle']}")
                    continue

                t["followers_count"] = followers_count
                t["following_count"] = profile.get("followsCount", 0)
                filtered.append(t)
            except Exception as e:
                logger.debug(f"プロフィールフィルタエラー ({t['handle']}): {e}")

        logger.info(f"ターゲット発見: {len(filtered)}人 (候補{len(unique_targets)}人からフィルタ)")
        return filtered


async def follow_targets(targets: list[dict]) -> dict:
    """
    ターゲットユーザーをフォローする。

    Args:
        targets: discover_targets()の戻り値

    Returns:
        {"followed": N, "skipped": N, "errors": N}
    """
    my_did = await _get_my_did()
    followed = 0
    skipped = 0
    errors = 0

    async with httpx.AsyncClient(timeout=20) as client:
        current_following = await _get_current_following_dids(client)

        for i, target in enumerate(targets):
            if followed >= DAILY_FOLLOW_LIMIT:
                logger.info(f"日次フォロー上限({DAILY_FOLLOW_LIMIT})に達しました")
                skipped += len(targets) - i
                break

            did = target["did"]
            handle = target.get("handle", "unknown")

            if did == my_did:
                skipped += 1
                continue

            if did in current_following:
                logger.debug(f"スキップ(既フォロー): {handle}")
                skipped += 1
                continue

            try:
                # フォロー実行
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                await _api_post(client, "com.atproto.repo.createRecord", {
                    "repo": my_did,
                    "collection": "app.bsky.graph.follow",
                    "record": {
                        "$type": "app.bsky.graph.follow",
                        "subject": did,
                        "createdAt": now,
                    },
                })

                # DB記録
                try:
                    async with get_connection() as conn:
                        await conn.execute(
                            """INSERT INTO bluesky_follow_tracking (did, handle, source)
                            VALUES ($1, $2, $3)
                            ON CONFLICT DO NOTHING""",
                            did, handle, target.get("source", "unknown"),
                        )
                except Exception as db_err:
                    logger.error(f"DB記録エラー: {db_err}")

                followed += 1
                current_following.add(did)
                logger.info(f"フォロー成功 ({followed}/{DAILY_FOLLOW_LIMIT}): {handle} (source={target.get('source', '')})")

                # レート制限対策: 30秒間隔
                if i < len(targets) - 1 and followed < DAILY_FOLLOW_LIMIT:
                    await asyncio.sleep(FOLLOW_INTERVAL_SEC)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("レート制限到達。フォロー中断")
                    skipped += len(targets) - i - 1
                    break
                logger.error(f"フォローHTTPエラー ({handle}): {e.response.status_code}")
                errors += 1
            except Exception as e:
                logger.error(f"フォローエラー ({handle}): {e}")
                errors += 1

    result = {"followed": followed, "skipped": skipped, "errors": errors}
    logger.info(f"フォロー結果: {result}")
    return result


async def check_followbacks() -> dict:
    """
    フォローバック状況を確認する。
    フォローから3日以上経過したユーザーのフォローバック状況をチェック。

    Returns:
        {"checked": N, "followback": N, "rate": float}
    """
    checked = 0
    followback_count = 0

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            followers = await _get_current_followers_dids(client)

            async with get_connection() as conn:
                # フォローから3日以上経過 & まだ確認していない or 前回確認から1日以上
                rows = await conn.fetch(
                    """SELECT id, did, handle FROM bluesky_follow_tracking
                    WHERE unfollowed_at IS NULL
                    AND followed_at < NOW() - INTERVAL '3 days'
                    AND (followback_checked_at IS NULL
                         OR followback_checked_at < NOW() - INTERVAL '1 day')
                    ORDER BY followed_at ASC
                    LIMIT 200"""
                )

                for row in rows:
                    did = row["did"]
                    is_fb = did in followers
                    await conn.execute(
                        """UPDATE bluesky_follow_tracking
                        SET followback_checked_at = NOW(), is_followback = $1
                        WHERE id = $2""",
                        is_fb, row["id"],
                    )
                    checked += 1
                    if is_fb:
                        followback_count += 1
                        logger.debug(f"フォローバック確認: {row['handle']}")

    except Exception as e:
        logger.error(f"フォローバックチェックエラー: {e}")

    rate = (followback_count / checked * 100) if checked > 0 else 0.0
    result = {"checked": checked, "followback": followback_count, "rate": round(rate, 1)}
    logger.info(f"フォローバック確認結果: {result}")
    return result


async def unfollow_non_reciprocal(days: int = 7) -> dict:
    """
    フォローから指定日数経過してもフォローバックされていないユーザーをアンフォロー。
    フォロー/フォロワー比率を健全に維持する。

    Args:
        days: アンフォローまでの猶予日数（デフォルト7日）

    Returns:
        {"unfollowed": N, "errors": N, "kept": N}
    """
    my_did = await _get_my_did()
    unfollowed = 0
    errors = 0
    kept = 0

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # 最新のフォロワーを取得
            followers = await _get_current_followers_dids(client)

            async with get_connection() as conn:
                # フォローからN日以上 & フォローバックなし & まだアンフォローしていない
                rows = await conn.fetch(
                    """SELECT id, did, handle FROM bluesky_follow_tracking
                    WHERE unfollowed_at IS NULL
                    AND followed_at < NOW() - INTERVAL '1 day' * $1
                    AND is_followback = FALSE
                    ORDER BY followed_at ASC""",
                    days,
                )

                for row in rows:
                    did = row["did"]
                    handle = row.get("handle", "unknown")

                    # 最終確認: フォロワーに含まれていたらスキップ
                    if did in followers:
                        await conn.execute(
                            """UPDATE bluesky_follow_tracking
                            SET is_followback = TRUE, followback_checked_at = NOW()
                            WHERE id = $1""",
                            row["id"],
                        )
                        kept += 1
                        continue

                    try:
                        # フォローレコードのrkeyを取得するためにlistRecordsを使う
                        resp = await _api_get(client, "com.atproto.repo.listRecords", {
                            "repo": my_did,
                            "collection": "app.bsky.graph.follow",
                            "limit": 100,
                        })
                        rkey = None
                        for record in resp.get("records", []):
                            if record.get("value", {}).get("subject") == did:
                                # URIからrkeyを抽出
                                uri = record.get("uri", "")
                                rkey = uri.split("/")[-1] if "/" in uri else None
                                break

                        if rkey:
                            await _api_post(client, "com.atproto.repo.deleteRecord", {
                                "repo": my_did,
                                "collection": "app.bsky.graph.follow",
                                "rkey": rkey,
                            })
                            await conn.execute(
                                """UPDATE bluesky_follow_tracking
                                SET unfollowed_at = NOW()
                                WHERE id = $1""",
                                row["id"],
                            )
                            unfollowed += 1
                            logger.info(f"アンフォロー: {handle}")
                            await asyncio.sleep(5)  # アンフォローも間隔を空ける
                        else:
                            logger.warning(f"フォローレコード未発見(既にアンフォロー済み?): {handle}")
                            await conn.execute(
                                "UPDATE bluesky_follow_tracking SET unfollowed_at = NOW() WHERE id = $1",
                                row["id"],
                            )

                    except Exception as e:
                        logger.error(f"アンフォローエラー ({handle}): {e}")
                        errors += 1

    except Exception as e:
        logger.error(f"アンフォロー処理エラー: {e}")

    result = {"unfollowed": unfollowed, "errors": errors, "kept": kept}
    logger.info(f"アンフォロー結果: {result}")
    return result


async def get_growth_stats() -> dict:
    """
    Blueskyアカウントのグロース統計を取得。

    Returns:
        {
            "followers_count": int,
            "following_count": int,
            "posts_count": int,
            "db_total_followed": int,
            "db_followback_count": int,
            "db_followback_rate": float,
            "db_unfollowed_count": int,
            "db_pending_check": int,
        }
    """
    stats = {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            my_did = await _get_my_did()
            profile = await _get_profile(client, my_did)
            if profile:
                stats["followers_count"] = profile.get("followersCount", 0)
                stats["following_count"] = profile.get("followsCount", 0)
                stats["posts_count"] = profile.get("postsCount", 0)
                stats["handle"] = profile.get("handle", "")
    except Exception as e:
        logger.error(f"プロフィール取得エラー: {e}")

    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE is_followback = TRUE) as followback,
                    COUNT(*) FILTER (WHERE unfollowed_at IS NOT NULL) as unfollowed,
                    COUNT(*) FILTER (WHERE unfollowed_at IS NULL AND followback_checked_at IS NULL) as pending
                FROM bluesky_follow_tracking"""
            )
            if row:
                stats["db_total_followed"] = row["total"]
                stats["db_followback_count"] = row["followback"]
                stats["db_unfollowed_count"] = row["unfollowed"]
                stats["db_pending_check"] = row["pending"]
                stats["db_followback_rate"] = round(
                    (row["followback"] / row["total"] * 100) if row["total"] > 0 else 0.0, 1
                )
    except Exception as e:
        logger.error(f"DB統計取得エラー: {e}")

    logger.info(f"グロース統計: {stats}")
    return stats


# ===== スケジューラー用エントリポイント =====

async def scheduled_follow():
    """毎日14:00 JSTに実行: ターゲット発見→フォロー"""
    logger.info("=== スケジュール実行: フォロー開始 ===")
    try:
        targets = await discover_targets(max_targets=DAILY_FOLLOW_LIMIT)
        if targets:
            result = await follow_targets(targets)
            logger.info(f"スケジュールフォロー完了: {result}")
        else:
            logger.info("フォロー対象なし")
    except Exception as e:
        logger.error(f"スケジュールフォローエラー: {e}")


async def scheduled_check_followbacks():
    """毎日10:00 JSTに実行: フォローバック確認"""
    logger.info("=== スケジュール実行: フォローバック確認 ===")
    try:
        result = await check_followbacks()
        logger.info(f"スケジュールフォローバック確認完了: {result}")
    except Exception as e:
        logger.error(f"スケジュールフォローバック確認エラー: {e}")


async def scheduled_unfollow():
    """毎週日曜15:00 JSTに実行: 非相互フォローのアンフォロー"""
    logger.info("=== スケジュール実行: アンフォロー ===")
    try:
        result = await unfollow_non_reciprocal(days=UNFOLLOW_AFTER_DAYS)
        logger.info(f"スケジュールアンフォロー完了: {result}")
    except Exception as e:
        logger.error(f"スケジュールアンフォローエラー: {e}")
