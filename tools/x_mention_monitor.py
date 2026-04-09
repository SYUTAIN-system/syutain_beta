"""X メンション + 引用RT 監視

島原大知（@Sima_daichi）がSYUTAIN X（@syutain_beta）に対して
リプライ・引用RTした時に検知し、自動返信を生成・投稿する。

監視間隔: 20分、稼働時間: 09:00-23:00 JST
対象: @Sima_daichi のみ（ALLOWED_USERS で制御、将来拡張可能）
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger("syutain.x_mention_monitor")

JST = timezone(timedelta(hours=9))

# Phase 1: 島原限定。Phase 2以降でここを広げる。None=全ユーザー許可
ALLOWED_USERS = {os.getenv("X_SHIMAHARA_USER_ID", "257796165")}

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_SYUTAIN_USER_ID = os.getenv("X_SYUTAIN_USER_ID", "")


async def _get_since_id() -> str | None:
    """DBからsince_idを復元"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'x_reply_since_id'"
            )
            if row and row["value"]:
                data = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                return data.get("id")
    except Exception as e:
        logger.debug(f"since_id復元失敗: {e}")
    return None


async def _save_since_id(since_id: str):
    """since_idをDBに永続化"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO settings (key, value) VALUES ('x_reply_since_id', $1)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                json.dumps({"id": since_id}),
            )
    except Exception as e:
        logger.warning(f"since_id保存失敗: {e}")


async def _fetch_mentions(since_id: str = None) -> list[dict]:
    """@syutain_betaへのメンション（リプライ）を取得"""
    if not X_BEARER_TOKEN or not X_SYUTAIN_USER_ID:
        logger.warning("X_BEARER_TOKEN or X_SYUTAIN_USER_ID 未設定")
        return []

    params = {
        "max_results": 20,
        "tweet.fields": "conversation_id,in_reply_to_user_id,referenced_tweets,author_id,created_at",
        "expansions": "author_id,referenced_tweets.id",
        "user.fields": "username",
    }
    if since_id:
        params["since_id"] = since_id

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.x.com/2/users/{X_SYUTAIN_USER_ID}/mentions",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                params=params,
            )
            if resp.status_code != 200:
                logger.warning(f"メンション取得失敗: {resp.status_code} {resp.text[:200]}")
                return []

            data = resp.json()
            tweets = data.get("data", [])

            # ユーザー名マッピング
            users = {}
            for u in data.get("includes", {}).get("users", []):
                users[u["id"]] = u.get("username", "")

            # 元ツイートマッピング
            ref_tweets = {}
            for t in data.get("includes", {}).get("tweets", []):
                ref_tweets[t["id"]] = t.get("text", "")

            results = []
            for tw in tweets:
                tw["_author_username"] = users.get(tw["author_id"], "")
                tw["_ref_tweets"] = ref_tweets
                tw["_trigger_type"] = "reply"
                results.append(tw)

            return results
    except Exception as e:
        logger.error(f"メンション取得エラー: {e}")
        return []


async def _fetch_quote_tweets() -> list[dict]:
    """@syutain_betaの直近投稿への引用RTを取得"""
    if not X_BEARER_TOKEN or not X_SYUTAIN_USER_ID:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # まず直近5投稿を取得
            resp = await client.get(
                f"https://api.x.com/2/users/{X_SYUTAIN_USER_ID}/tweets",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                params={"max_results": 5, "tweet.fields": "created_at,text,public_metrics"},
            )
            if resp.status_code != 200:
                return []

            my_tweets = resp.json().get("data", [])
            results = []

            for my_tw in my_tweets:
                # quote_countが0なら引用RTは存在しない→スキップ
                if my_tw.get("public_metrics", {}).get("quote_count", 0) == 0:
                    continue

                resp2 = await client.get(
                    f"https://api.x.com/2/tweets/{my_tw['id']}/quote_tweets",
                    headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                    params={
                        "max_results": 10,
                        "tweet.fields": "author_id,created_at,text,conversation_id",
                        "expansions": "author_id",
                        "user.fields": "username",
                    },
                )
                if resp2.status_code != 200:
                    continue

                d2 = resp2.json()
                users = {u["id"]: u.get("username", "") for u in d2.get("includes", {}).get("users", [])}

                for qt in d2.get("data", []):
                    qt["_author_username"] = users.get(qt["author_id"], "")
                    qt["_original_tweet_id"] = my_tw["id"]
                    qt["_original_content"] = my_tw.get("text", "")
                    qt["_trigger_type"] = "quote"
                    results.append(qt)

            return results
    except Exception as e:
        logger.error(f"引用RT取得エラー: {e}")
        return []


async def _is_already_replied(trigger_tweet_id: str) -> bool:
    """既に返信済みかDBで確認（重複防止Layer 2）"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM x_reply_log WHERE trigger_tweet_id = $1",
                trigger_tweet_id,
            )
            return row is not None
    except Exception:
        return False


async def _record_reply(trigger: dict, reply_content: str, reply_tweet_id: str, status: str = "replied", error: str = None):
    """返信記録をDBに保存 + daichi_dialogue_log + persona_memory連携"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # x_reply_log（UNIQUE制約=重複防止Layer 3）
            await conn.execute(
                """INSERT INTO x_reply_log
                (trigger_tweet_id, trigger_author_id, trigger_author_username,
                 trigger_content, trigger_type, original_tweet_id, original_content,
                 reply_tweet_id, reply_content, thread_id, depth, status, error_message, replied_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)""",
                trigger.get("id", ""),
                trigger.get("author_id", ""),
                trigger.get("_author_username", ""),
                trigger.get("text", ""),
                trigger.get("_trigger_type", "reply"),
                trigger.get("_original_tweet_id", trigger.get("conversation_id", "")),
                trigger.get("_original_content", ""),
                reply_tweet_id or "",
                reply_content or "",
                trigger.get("conversation_id", trigger.get("_original_tweet_id", "")),
                trigger.get("_depth", 0),
                status,
                error,
                datetime.now(JST) if status == "replied" else None,
            )

            # daichi_dialogue_log に島原の発言を記録（source="x_reply"で区別）
            if trigger.get("author_id") in ALLOWED_USERS and trigger.get("text"):
                try:
                    await conn.execute(
                        """INSERT INTO daichi_dialogue_log
                        (daichi_message, bot_response, extracted_philosophy, source)
                        VALUES ($1, $2, $3, $4)""",
                        trigger.get("text", ""),
                        reply_content or "",
                        json.dumps({"source": "x_reply", "tweet_id": trigger.get("id", "")}),
                        "x_reply",
                    )
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"返信記録保存失敗: {e}")


async def _get_thread_context(thread_id: str, limit: int = 10) -> list[dict]:
    """同一スレッドの過去の掛け合いを取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT trigger_author_username, trigger_content, reply_content, created_at
                FROM x_reply_log
                WHERE thread_id = $1 AND status = 'replied'
                ORDER BY created_at DESC LIMIT $2""",
                thread_id, limit,
            )
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


async def check_and_reply():
    """メイン処理: メンション+引用RTを検知して返信"""
    from brain_alpha.x_reply_generator import generate_reply
    from tools.social_tools import execute_approved_x

    since_id = await _get_since_id()
    latest_id = since_id

    # 1. メンション取得
    mentions = await _fetch_mentions(since_id)

    # 2. 引用RT取得
    quotes = await _fetch_quote_tweets()

    # 全トリガーを統合
    all_triggers = mentions + quotes

    if not all_triggers:
        return {"processed": 0, "replied": 0}

    processed = 0
    replied = 0

    for trigger in all_triggers:
        tweet_id = trigger.get("id", "")
        author_id = trigger.get("author_id", "")

        # フィルター: ALLOWED_USERSのみ
        if ALLOWED_USERS is not None and author_id not in ALLOWED_USERS:
            continue

        # 重複防止 Layer 2: DB照合
        if await _is_already_replied(tweet_id):
            continue

        # 古すぎるツイートはスキップ（60分以上前）
        try:
            created = datetime.fromisoformat(trigger["created_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - created).total_seconds() > 3600:
                # ただし初回起動時は古いものもスキップするだけで記録はしない
                continue
        except Exception:
            pass

        processed += 1

        # 元ツイートの内容を取得
        original_content = trigger.get("_original_content", "")
        if not original_content:
            # リプライの場合、referenced_tweetsから元ツイートを取得
            ref_tweets = trigger.get("_ref_tweets", {})
            for ref in trigger.get("referenced_tweets", []):
                if ref.get("type") in ("replied_to", "quoted"):
                    original_content = ref_tweets.get(ref["id"], "")
                    trigger["_original_tweet_id"] = ref["id"]
                    break

        trigger["_original_content"] = original_content

        # スレッド文脈取得
        thread_id = trigger.get("conversation_id", trigger.get("_original_tweet_id", ""))
        thread_context = await _get_thread_context(thread_id)
        trigger["_depth"] = len(thread_context)

        # 返信生成
        try:
            reply_text = await asyncio.wait_for(
                generate_reply(
                    trigger_text=trigger.get("text", ""),
                    trigger_username=trigger.get("_author_username", ""),
                    original_text=original_content,
                    thread_context=thread_context,
                    trigger_type=trigger.get("_trigger_type", "reply"),
                ),
                timeout=480,
            )
        except asyncio.TimeoutError:
            logger.warning(f"返信生成タイムアウト: {tweet_id}")
            await _record_reply(trigger, None, None, status="timeout", error="LLM generation timeout")
            continue
        except Exception as e:
            logger.error(f"返信生成失敗: {tweet_id} {e}")
            await _record_reply(trigger, None, None, status="failed", error=str(e)[:200])
            continue

        if not reply_text:
            await _record_reply(trigger, None, None, status="failed", error="empty reply")
            continue

        # DB記録（UNIQUE制約=重複防止Layer 3、投稿前に記録）
        await _record_reply(trigger, reply_text, None, status="posting")

        # X API投稿
        try:
            # リプライの場合はin_reply_to、引用RTの場合もリプライとして返す
            reply_to_id = tweet_id  # 島原のツイートに対して返信
            result = await execute_approved_x(
                content=reply_text,
                account="syutain",
                in_reply_to_tweet_id=reply_to_id,
            )

            if result.get("success"):
                # 投稿成功: ステータス更新
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        """UPDATE x_reply_log SET status = 'replied', reply_tweet_id = $1, replied_at = NOW()
                        WHERE trigger_tweet_id = $2""",
                        result.get("tweet_id", ""), tweet_id,
                    )
                replied += 1
                logger.info(f"X自動返信成功: @{trigger.get('_author_username', '')} → {result.get('tweet_id', '')}")

                # Discord通知
                try:
                    from tools.discord_notify import notify
                    reply_url = f"https://x.com/syutain_beta/status/{result.get('tweet_id', '')}"
                    await notify(
                        f"🔁 島原さんのXに返信しました\n"
                        f"島原: {trigger.get('text', '')[:80]}\n"
                        f"返信: {reply_text[:80]}\n{reply_url}",
                    )
                except Exception:
                    pass
            else:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status = 'post_failed', error_message = $1 WHERE trigger_tweet_id = $2",
                        str(result.get("reason", ""))[:200], tweet_id,
                    )
                logger.warning(f"X自動返信投稿失敗: {result}")

        except Exception as e:
            logger.error(f"X自動返信投稿エラー: {e}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status = 'post_failed', error_message = $1 WHERE trigger_tweet_id = $2",
                        str(e)[:200], tweet_id,
                    )
            except Exception:
                pass

        # since_id更新（処理したツイートの最大ID）
        if not latest_id or tweet_id > latest_id:
            latest_id = tweet_id

    # since_id永続化
    if latest_id and latest_id != since_id:
        await _save_since_id(latest_id)

    return {"processed": processed, "replied": replied}
