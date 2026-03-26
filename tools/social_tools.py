"""
SYUTAINβ V25 SNSツール (Step 18)
設計書準拠

X (Twitter) API v2 投稿、Bluesky AT Protocol投稿、Threads Graph API投稿。
全投稿はApprovalManagerの承認が必須（CLAUDE.mdルール11）。
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime, timezone
import unicodedata

import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.social_tools")

# X (Twitter) API v2 — SYUTAINβ専用アカウント (@syutain_beta)
X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY", "")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET", "")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "")

# X (Twitter) API v2 — 島原大知 個人アカウント (@Sima_daichi)
X_SHIMAHARA_CONSUMER_KEY = os.getenv("X_SHIMAHARA_CONSUMER_KEY", "")
X_SHIMAHARA_CONSUMER_SECRET = os.getenv("X_SHIMAHARA_CONSUMER_SECRET", "")
X_SHIMAHARA_ACCESS_TOKEN = os.getenv("X_SHIMAHARA_ACCESS_TOKEN", "")
X_SHIMAHARA_ACCESS_TOKEN_SECRET = os.getenv("X_SHIMAHARA_ACCESS_TOKEN_SECRET", "")

# Bluesky
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "")

# Threads (Meta Graph API)
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "")
THREADS_USER_ID = os.getenv("THREADS_USER_ID", "")


def _count_x_chars(text: str) -> int:
    """X (Twitter) の文字カウント: CJK=2文字、ASCII=1文字（Twitter API準拠）"""
    count = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            count += 2
        else:
            count += 1
    return count


async def _require_approval(action: str, data: dict) -> dict:
    """ApprovalManager承認を要求（CLAUDE.mdルール11: SNS投稿は承認必須）"""
    try:
        from tools.nats_client import get_nats_client
        nats = await get_nats_client()
        response = await nats.request(
            "approval.request",
            {
                "request_type": "social_post",
                "action": action,
                "data": data,
                "requested_at": datetime.now().isoformat(),
            },
            timeout=300.0,  # 5分待機
        )
        return response or {"approved": False, "reason": "タイムアウト"}
    except Exception as e:
        logger.error(f"承認リクエスト失敗: {e}")
        return {"approved": False, "reason": str(e)}


# ===== X (Twitter) API v2 =====

def _get_x_credentials(account: str = "syutain") -> dict:
    """アカウント別のX APIクレデンシャルを取得

    設計書チャネル戦略:
      - "shimahara" (@Sima_daichi): 感情/挑戦/失敗/数字/判断理由。一人称「僕」
      - "syutain"   (@syutain_beta): 分析/構造/仮説/改善ログ。一人称「私」
    """
    if account == "shimahara":
        return {
            "consumer_key": X_SHIMAHARA_CONSUMER_KEY,
            "consumer_secret": X_SHIMAHARA_CONSUMER_SECRET,
            "access_token": X_SHIMAHARA_ACCESS_TOKEN,
            "access_token_secret": X_SHIMAHARA_ACCESS_TOKEN_SECRET,
            "handle": "@Sima_daichi",
        }
    # デフォルト: SYUTAINβ専用アカウント
    return {
        "consumer_key": X_CONSUMER_KEY,
        "consumer_secret": X_CONSUMER_SECRET,
        "access_token": X_ACCESS_TOKEN,
        "access_token_secret": X_ACCESS_TOKEN_SECRET,
        "handle": "@syutain_beta",
    }


async def post_to_x(content: str, account: str = "syutain", skip_approval: bool = False) -> dict:
    """
    X (Twitter)に投稿

    Args:
        content: 投稿テキスト（280文字以内）
        account: "syutain" (@syutain_beta) or "shimahara" (@Sima_daichi)
        skip_approval: True にしても承認は省略されない（安全装置）

    Returns:
        {"success": bool, "tweet_id": str, ...}
    """
    creds = _get_x_credentials(account)

    # 承認チェック（絶対にスキップしない）
    approval = await _require_approval("x_post", {"content": content, "account": account, "handle": creds["handle"]})
    if not approval.get("approved", False):
        logger.info(f"X投稿({creds['handle']}): 承認されませんでした - {approval.get('reason', 'unknown')}")
        return {"success": False, "reason": "approval_denied", "detail": approval}

    if not creds["consumer_key"] or not creds["access_token"]:
        logger.error(f"X APIキー未設定 (account={account})")
        return {"success": False, "reason": "credentials_missing"}

    # NGワードチェック（post_to_x直接経路）
    try:
        from tools.platform_ng_check import check_platform_ng
        ng_result = check_platform_ng(content, "x")
        if not ng_result["passed"]:
            logger.warning(f"X投稿({creds['handle']}): NGワード検出 — 投稿中止: {ng_result['violations']}")
            return {"success": False, "reason": "ng_word_detected", "violations": ng_result["violations"]}
    except Exception:
        pass

    try:
        # OAuth 1.0a User Context (tweepy使用)
        import tweepy
        client = tweepy.Client(
            consumer_key=creds["consumer_key"],
            consumer_secret=creds["consumer_secret"],
            access_token=creds["access_token"],
            access_token_secret=creds["access_token_secret"],
        )
        response = client.create_tweet(text=content)
        tweet_id = response.data.get("id", "") if response.data else ""

        logger.info(f"X投稿成功({creds['handle']}): {tweet_id}")
        return {"success": True, "tweet_id": tweet_id, "platform": "x", "account": account, "handle": creds["handle"]}
    except ImportError:
        # tweepy未インストール: httpx直接
        return await _post_x_direct(content, creds)
    except Exception as e:
        logger.error(f"X投稿失敗({creds['handle']}): {e}")
        try:
            from tools.event_logger import log_event
            await log_event(
                "sns.post_failed", "sns",
                {"platform": "x", "account": account, "error": str(e)[:200]},
                severity="error",
            )
        except Exception:
            pass
        return {"success": False, "reason": str(e)}


async def execute_approved_x(content: str, account: str = "syutain") -> dict:
    """承認済みX投稿を実行（承認チェックをバイパス — 承認済みキューからのみ呼ぶこと）"""
    creds = _get_x_credentials(account)

    # 280文字制限チェック（CJK=2, ASCII=1でカウント）
    x_len = _count_x_chars(content)
    if x_len > 280:
        logger.warning(f"X投稿: 280文字超過({x_len}加重文字)。切り詰め")
        # 切り詰め: 加重カウントで277以内に収める
        trimmed = []
        cur = 0
        for ch in content:
            w = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
            if cur + w > 277:
                break
            trimmed.append(ch)
            cur += w
        content = "".join(trimmed) + "..."

    # NGワードチェック
    try:
        from tools.platform_ng_check import check_platform_ng
        ng_result = check_platform_ng(content, "x")
        if not ng_result["passed"]:
            logger.warning(f"X投稿: NGワード検出 — 投稿中止: {ng_result['violations']}")
            return {"success": False, "reason": "ng_word_detected", "violations": ng_result["violations"]}
    except Exception:
        pass

    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=creds["consumer_key"],
            consumer_secret=creds["consumer_secret"],
            access_token=creds["access_token"],
            access_token_secret=creds["access_token_secret"],
        )
        response = client.create_tweet(text=content)
        tweet_id = response.data.get("id", "") if response.data else ""
        tweet_url = f"https://x.com/{creds['handle'].lstrip('@')}/status/{tweet_id}"

        logger.info(f"X承認済み投稿成功({creds['handle']}): {tweet_id}")
        try:
            from tools.event_logger import log_event
            await log_event(
                "sns.posted", "sns",
                {"platform": "x", "post_id": tweet_id, "url": tweet_url,
                 "account": account, "handle": creds["handle"],
                 "content_preview": content[:80], "approved": True},
            )
        except Exception:
            pass
        return {"success": True, "tweet_id": tweet_id, "url": tweet_url, "platform": "x", "account": account}
    except ImportError:
        return await _post_x_direct(content, creds)
    except Exception as e:
        logger.error(f"X承認済み投稿失敗({creds['handle']}): {e}")
        try:
            from tools.event_logger import log_event
            await log_event(
                "sns.post_failed", "sns",
                {"platform": "x", "account": account, "error": str(e)[:200]},
                severity="error",
            )
        except Exception:
            pass
        return {"success": False, "reason": str(e)}


async def _post_x_direct(content: str, creds: dict = None) -> dict:
    """X API v2 直接HTTP投稿（tweepy未インストール時のフォールバック）"""
    if creds is None:
        creds = _get_x_credentials("syutain")
    try:
        from requests_oauthlib import OAuth1
        import requests

        oauth = OAuth1(creds["consumer_key"], creds["consumer_secret"], creds["access_token"], creds["access_token_secret"])
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": content},
            auth=oauth,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "tweet_id": data.get("data", {}).get("id", ""), "platform": "x"}
    except Exception as e:
        logger.error(f"X直接API投稿失敗: {e}")
        return {"success": False, "reason": str(e)}


# ===== Bluesky AT Protocol =====

async def post_to_bluesky(content: str, skip_approval: bool = False) -> dict:
    """
    Blueskyに投稿

    Args:
        content: 投稿テキスト（300文字以内）
        skip_approval: True にしても承認は省略されない（安全装置）

    Returns:
        {"success": bool, "uri": str, ...}
    """
    # 承認チェック
    approval = await _require_approval("bluesky_post", {"content": content})
    if not approval.get("approved", False):
        logger.info(f"Bluesky投稿: 承認されませんでした")
        return {"success": False, "reason": "approval_denied", "detail": approval}

    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        logger.error("BLUESKY_HANDLE/BLUESKY_APP_PASSWORD未設定")
        return {"success": False, "reason": "credentials_missing"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # セッション作成
            session_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD},
            )
            session_resp.raise_for_status()
            session = session_resp.json()
            access_jwt = session["accessJwt"]
            did = session["did"]

            # 投稿
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            post_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {access_jwt}"},
                json={
                    "repo": did,
                    "collection": "app.bsky.feed.post",
                    "record": {
                        "$type": "app.bsky.feed.post",
                        "text": content,
                        "createdAt": now,
                    },
                },
            )
            post_resp.raise_for_status()
            data = post_resp.json()

            logger.info(f"Bluesky投稿成功: {data.get('uri', '')}")
            try:
                from tools.event_logger import log_event
                asyncio.ensure_future(log_event(
                    "sns.posted", "sns",
                    {"platform": "bluesky", "uri": data.get("uri", ""),
                     "content_preview": content[:80]},
                ))
            except Exception:
                pass
            return {"success": True, "uri": data.get("uri", ""), "cid": data.get("cid", ""), "platform": "bluesky"}
    except Exception as e:
        logger.error(f"Bluesky投稿失敗: {e}")
        try:
            from tools.event_logger import log_event
            asyncio.ensure_future(log_event(
                "sns.post_failed", "sns",
                {"platform": "bluesky", "error": str(e)[:200]},
                severity="error",
            ))
        except Exception:
            pass
        return {"success": False, "reason": str(e)}


async def execute_approved_bluesky(content: str) -> dict:
    """承認済みBluesky投稿を実行（承認チェックをバイパス — 承認済みキューからのみ呼ぶこと）"""
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        return {"success": False, "reason": "credentials_missing"}

    # NGワードチェック（Bluesky）
    try:
        from tools.platform_ng_check import check_platform_ng
        ng_result = check_platform_ng(content, "bluesky")
        if not ng_result["passed"]:
            logger.warning(f"Bluesky投稿: NGワード検出 — 投稿中止: {ng_result['violations']}")
            return {"success": False, "reason": "ng_word_detected", "violations": ng_result["violations"]}
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            session_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD},
            )
            session_resp.raise_for_status()
            session = session_resp.json()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            post_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {session['accessJwt']}"},
                json={
                    "repo": session["did"],
                    "collection": "app.bsky.feed.post",
                    "record": {"$type": "app.bsky.feed.post", "text": content, "createdAt": now},
                },
            )
            post_resp.raise_for_status()
            data = post_resp.json()
            logger.info(f"Bluesky承認済み投稿成功: {data.get('uri', '')}")
            try:
                from tools.event_logger import log_event
                asyncio.ensure_future(log_event(
                    "sns.posted", "sns",
                    {"platform": "bluesky", "uri": data.get("uri", ""),
                     "content_preview": content[:80], "approved": True},
                ))
            except Exception:
                pass
            return {"success": True, "uri": data.get("uri", ""), "platform": "bluesky"}
    except Exception as e:
        logger.error(f"Bluesky承認済み投稿失敗: {e}")
        try:
            from tools.event_logger import log_event
            asyncio.ensure_future(log_event(
                "sns.post_failed", "sns",
                {"platform": "bluesky", "error": str(e)[:200]},
                severity="error",
            ))
        except Exception:
            pass
        return {"success": False, "reason": str(e)}


async def get_bluesky_engagement(post_uri: str) -> dict:
    """Bluesky投稿のエンゲージメントデータを取得"""
    if not BLUESKY_HANDLE or not BLUESKY_APP_PASSWORD:
        return {"error": "credentials_missing"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            session_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_APP_PASSWORD},
            )
            session_resp.raise_for_status()
            session = session_resp.json()

            thread_resp = await client.get(
                "https://bsky.social/xrpc/app.bsky.feed.getPostThread",
                params={"uri": post_uri, "depth": 0},
                headers={"Authorization": f"Bearer {session['accessJwt']}"},
            )
            thread_resp.raise_for_status()
            thread = thread_resp.json()

            post = thread.get("thread", {}).get("post", {})
            return {
                "uri": post_uri,
                "like_count": post.get("likeCount", 0),
                "reply_count": post.get("replyCount", 0),
                "repost_count": post.get("repostCount", 0),
                "text": post.get("record", {}).get("text", "")[:100],
            }
    except Exception as e:
        logger.error(f"Blueskyエンゲージメント取得失敗: {e}")
        return {"error": str(e), "uri": post_uri}


async def get_x_engagement(post_id: str, account: str = "syutain") -> dict:
    """X投稿のエンゲージメントデータを取得

    注意: X API Free tierではツイート取得不可（Basic tier $200/月が必要）。
    Bearer tokenがない場合はOAuth 1.0aで試行するが、Free tierでは403が返る。
    """
    X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"https://api.x.com/2/tweets/{post_id}"
            params = {"tweet.fields": "public_metrics"}

            if X_BEARER_TOKEN:
                # Bearer token認証（App-only）
                headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
                resp = await client.get(url, params=params, headers=headers)
            else:
                # OAuth 1.0a（User Context）— Free tierでは読み取り不可の可能性大
                import hashlib
                import hmac
                import time
                import urllib.parse
                import base64
                import secrets as _secrets

                creds = _get_x_credentials(account)
                if not creds["consumer_key"] or not creds["access_token"]:
                    logger.warning("Xエンゲージメント取得: APIキー未設定")
                    return {"error": "credentials_missing", "post_id": post_id}

                # OAuth 1.0a署名生成
                oauth_nonce = _secrets.token_hex(16)
                oauth_timestamp = str(int(time.time()))
                oauth_params = {
                    "oauth_consumer_key": creds["consumer_key"],
                    "oauth_nonce": oauth_nonce,
                    "oauth_signature_method": "HMAC-SHA1",
                    "oauth_timestamp": oauth_timestamp,
                    "oauth_token": creds["access_token"],
                    "oauth_version": "1.0",
                }
                all_params = {**oauth_params, **params}
                sorted_params = "&".join(
                    f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
                    for k, v in sorted(all_params.items())
                )
                base_string = f"GET&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(sorted_params, safe='')}"
                signing_key = f"{urllib.parse.quote(creds['consumer_secret'], safe='')}&{urllib.parse.quote(creds['access_token_secret'], safe='')}"
                signature = base64.b64encode(
                    hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
                ).decode()

                oauth_params["oauth_signature"] = signature
                auth_header = "OAuth " + ", ".join(
                    f'{k}="{urllib.parse.quote(v, safe="")}"' for k, v in oauth_params.items()
                )
                resp = await client.get(url, params=params, headers={"Authorization": auth_header})

            if resp.status_code == 403:
                logger.warning(
                    f"Xエンゲージメント取得: 403 Forbidden — Free tierではツイート取得不可。"
                    f" Basic tier ($200/月) が必要です。post_id={post_id}"
                )
                return {"error": "free_tier_limitation", "post_id": post_id,
                        "detail": "X API Free tier does not support tweet lookup. Upgrade to Basic tier."}

            resp.raise_for_status()
            data = resp.json().get("data", {})
            metrics = data.get("public_metrics", {})
            return {
                "post_id": post_id,
                "platform": "x",
                "account": account,
                "like_count": metrics.get("like_count", 0),
                "reply_count": metrics.get("reply_count", 0),
                "repost_count": metrics.get("retweet_count", 0),
                "quote_count": metrics.get("quote_count", 0),
                "impression_count": metrics.get("impression_count", 0),
                "text": data.get("text", "")[:100],
            }
    except httpx.HTTPStatusError as e:
        logger.error(f"Xエンゲージメント取得失敗 (HTTP {e.response.status_code}): {e}")
        return {"error": str(e), "post_id": post_id}
    except Exception as e:
        logger.error(f"Xエンゲージメント取得失敗: {e}")
        return {"error": str(e), "post_id": post_id}


async def get_threads_engagement(post_id: str) -> dict:
    """Threads投稿のエンゲージメントデータを取得

    Media Insights API: GET https://graph.threads.net/{media_id}/insights
    メトリクス: views, likes, replies, reposts, quotes
    """
    if not THREADS_ACCESS_TOKEN:
        logger.warning("Threadsエンゲージメント取得: THREADS_ACCESS_TOKEN未設定")
        return {"error": "credentials_missing", "post_id": post_id}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Media Insights APIでエンゲージメント取得
            resp = await client.get(
                f"https://graph.threads.net/v1.0/{post_id}/insights",
                params={
                    "metric": "views,likes,replies,reposts,quotes",
                    "access_token": THREADS_ACCESS_TOKEN,
                },
            )
            resp.raise_for_status()
            insights_data = resp.json().get("data", [])

            # insights配列からメトリクスを辞書に変換
            metrics = {}
            for item in insights_data:
                name = item.get("name", "")
                # valuesは配列で、各要素に"value"がある
                values = item.get("values", [])
                if values:
                    metrics[name] = values[0].get("value", 0)
                else:
                    metrics[name] = item.get("total_value", {}).get("value", 0)

            return {
                "post_id": post_id,
                "platform": "threads",
                "like_count": metrics.get("likes", 0),
                "reply_count": metrics.get("replies", 0),
                "repost_count": metrics.get("reposts", 0),
                "quote_count": metrics.get("quotes", 0),
                "view_count": metrics.get("views", 0),
            }
    except httpx.HTTPStatusError as e:
        logger.error(f"Threadsエンゲージメント取得失敗 (HTTP {e.response.status_code}): {e}")
        return {"error": str(e), "post_id": post_id}
    except Exception as e:
        logger.error(f"Threadsエンゲージメント取得失敗: {e}")
        return {"error": str(e), "post_id": post_id}


# ===== ユーティリティ =====

async def post_to_all(content: str, platforms: Optional[list] = None, x_account: str = "syutain") -> dict:
    """複数プラットフォームに同時投稿（各プラットフォームで承認が必要）

    Args:
        content: 投稿テキスト
        platforms: ["x", "bluesky"] など
        x_account: "syutain" (@syutain_beta) or "shimahara" (@Sima_daichi)
    """
    platforms = platforms or ["x", "bluesky"]
    results = {}

    if "x" in platforms:
        results["x"] = await post_to_x(content, account=x_account)
    if "bluesky" in platforms:
        results["bluesky"] = await post_to_bluesky(content)

    return results


async def cross_post_bluesky_to_x(limit: int = 3) -> list:
    """
    Blueskyで投稿済みの内容をXに横展開する。
    280文字に調整し、承認キューに投入する。

    Args:
        limit: 横展開対象の最大件数

    Returns: list of dicts with approval queue IDs
    """
    results = []
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # Blueskyで投稿済み＆Xに未横展開の投稿を取得
            rows = await conn.fetch(
                """SELECT payload->>'content_preview' as content,
                          payload->>'uri' as uri,
                          created_at
                FROM event_log
                WHERE event_type = 'sns.posted'
                AND payload->>'platform' = 'bluesky'
                AND NOT EXISTS (
                    SELECT 1 FROM event_log e2
                    WHERE e2.event_type = 'sns.posted'
                    AND e2.payload->>'platform' = 'x'
                    AND e2.payload->>'cross_posted_from' = event_log.payload->>'uri'
                )
                ORDER BY created_at DESC
                LIMIT $1""",
                limit,
            )

            for row in rows:
                content = row["content"] or ""
                if not content or len(content) < 20:
                    continue

                # 280文字に調整（CJK=2, ASCII=1でカウント）
                if _count_x_chars(content) > 280:
                    trimmed = []
                    cur = 0
                    for ch in content:
                        w = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
                        if cur + w > 277:
                            break
                        trimmed.append(ch)
                        cur += w
                    content = "".join(trimmed) + "..."

                # 承認キューに投入
                import json
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('x_post', $1, 'pending')""",
                    json.dumps({
                        "content": content,
                        "platform": "x",
                        "account": "syutain",
                        "auto_generated": True,
                        "cross_posted_from": row["uri"],
                    }, ensure_ascii=False),
                )
                results.append({"content": content[:60], "source_uri": row["uri"]})

            if results:
                logger.info(f"Bluesky→X横展開: {len(results)}件を承認キューに投入")
    except Exception as e:
        logger.error(f"Bluesky→X横展開エラー: {e}")

    return results


# ===== Threads (Meta Graph API) =====

async def post_to_threads(content: str, skip_approval: bool = False) -> dict:
    """
    Threads公式API (Meta Graph API) でテキスト投稿する。

    2ステップ: メディアコンテナ作成 → 公開
    500文字制限。

    Returns: {"success": bool, "post_id": str, "url": str}
    """
    # 承認チェック
    approval = await _require_approval("threads_post", {"content": content})
    if not approval.get("approved", False):
        logger.info("Threads投稿: 承認されませんでした")
        return {"success": False, "reason": "approval_denied", "detail": approval}

    return await execute_approved_threads(content)


async def execute_approved_threads(content: str) -> dict:
    """承認済みThreads投稿を実行（承認チェックをバイパス）"""
    if not THREADS_USER_ID or not THREADS_ACCESS_TOKEN:
        logger.error("THREADS_USER_ID/THREADS_ACCESS_TOKEN未設定")
        return {"success": False, "reason": "credentials_missing"}

    # 500文字チェック
    if len(content) > 500:
        content = content[:497] + "..."

    # NGワードチェック
    try:
        from tools.platform_ng_check import check_platform_ng
        ng_result = check_platform_ng(content, "threads")
        if not ng_result["passed"]:
            logger.warning(f"Threads投稿: NGワード検出 — 投稿中止: {ng_result['violations']}")
            return {"success": False, "reason": "ng_word_detected", "violations": ng_result["violations"]}
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # ステップ1: メディアコンテナ作成
            create_resp = await client.post(
                f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads",
                params={
                    "media_type": "TEXT",
                    "text": content,
                    "access_token": THREADS_ACCESS_TOKEN,
                },
            )
            create_data = create_resp.json()
            if "id" not in create_data:
                error_msg = create_data.get("error", {}).get("message", str(create_data))
                logger.error(f"Threadsコンテナ作成失敗: {error_msg}")
                try:
                    from tools.event_logger import log_event
                    await log_event("sns.post_failed", "sns",
                                    {"platform": "threads", "error": error_msg[:200]},
                                    severity="error")
                except Exception:
                    pass
                return {"success": False, "reason": error_msg}

            creation_id = create_data["id"]

            # ステップ2: 公開
            publish_resp = await client.post(
                f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
                params={
                    "creation_id": creation_id,
                    "access_token": THREADS_ACCESS_TOKEN,
                },
            )
            pub_data = publish_resp.json()
            if "id" not in pub_data:
                error_msg = pub_data.get("error", {}).get("message", str(pub_data))
                logger.error(f"Threads公開失敗: {error_msg}")
                try:
                    from tools.event_logger import log_event
                    await log_event("sns.post_failed", "sns",
                                    {"platform": "threads", "error": error_msg[:200]},
                                    severity="error")
                except Exception:
                    pass
                return {"success": False, "reason": error_msg}

            post_id = pub_data["id"]
            post_url = f"https://www.threads.net/@syutain_beta/post/{post_id}"

            logger.info(f"Threads投稿成功: {post_id}")
            try:
                from tools.event_logger import log_event
                await log_event("sns.posted", "sns", {
                    "platform": "threads",
                    "post_id": post_id,
                    "url": post_url,
                    "content_preview": content[:80],
                    "approved": True,
                })
            except Exception:
                pass

            return {"success": True, "post_id": post_id, "url": post_url, "platform": "threads"}

    except Exception as e:
        logger.error(f"Threads投稿エラー: {e}")
        try:
            from tools.event_logger import log_event
            await log_event("sns.post_failed", "sns",
                            {"platform": "threads", "error": str(e)[:200]},
                            severity="error")
        except Exception:
            pass
        return {"success": False, "reason": str(e)}
