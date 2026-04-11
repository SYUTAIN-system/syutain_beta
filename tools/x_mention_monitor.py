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

# USER_PROFILES は gitignore 対象の外部 JSON ファイルから runtime で読み込む。
# このコードファイル自体には他人の実名/事業情報/関係性等の個人情報を含めない設計。
# JSON の場所: strategy/x_user_profiles.json (gitignored)
# 構造: {"<user_id>": {"username": ..., "name": ..., "tone": ..., "scope": ..., "protected": ..., "tomo_member": ..., "context": ..., "relationship": ..., "full_name": ...}, ...}
_USER_PROFILES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "strategy",
    "x_user_profiles.json",
)


def _load_user_profiles() -> dict:
    """外部 JSON から USER_PROFILES を読み込む。存在しない環境では島原のみの最小 fallback"""
    try:
        if os.path.exists(_USER_PROFILES_PATH):
            with open(_USER_PROFILES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning(f"USER_PROFILES 読込失敗: {e}")
    # Fallback: 設計者のみ最小プロファイル
    # (公開リポジトリ環境・新規マシン等で JSON が無い場合の安全動作保証)
    _owner_id = os.getenv("X_SHIMAHARA_USER_ID", "")
    if not _owner_id:
        return {}
    return {
        _owner_id: {
            "username": os.getenv("X_SHIMAHARA_USERNAME", ""),
            "name": "設計者",
            "relationship": "設計者(本人)",
            "tone": "shimahara_diss",
            "scope": "daichi",
            "protected": False,
            "context": "SYUTAINβ の設計者。",
        },
    }


USER_PROFILES = _load_user_profiles()

# Phase 1: 島原限定 → Phase 2 以降で USER_PROFILES 全員に拡張
# None = 全ユーザー許可、set = 許可リスト
# 環境変数で明示的に全許可したい場合は X_REPLY_ALLOW_ALL=1 を設定
if os.getenv("X_REPLY_ALLOW_ALL", "").strip() in ("1", "true", "True"):
    ALLOWED_USERS = None
else:
    # デフォルト: USER_PROFILES に登録されているユーザー全員
    ALLOWED_USERS = set(USER_PROFILES.keys())

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_SYUTAIN_USER_ID = os.getenv("X_SYUTAIN_USER_ID", "")


# ============================================================
# User recent tweets fetch (「知りすぎている AI」演出用)
# ============================================================

async def fetch_user_recent_tweets(user_id: str, limit: int = 10) -> list[dict]:
    """特定ユーザーの直近ツイートを X API から取得。

    リツイート/リプ除外で元ポストのみ。
    "知りすぎている AI" 効果のためだけに使用する。
    """
    if not X_BEARER_TOKEN:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.x.com/2/users/{user_id}/tweets",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                params={
                    "max_results": min(max(limit, 5), 100),
                    "tweet.fields": "created_at,text,public_metrics",
                    "exclude": "retweets,replies",
                },
            )
            if resp.status_code != 200:
                logger.debug(f"ユーザーツイート取得失敗: {user_id} {resp.status_code}")
                return []
            return resp.json().get("data", [])
    except Exception as e:
        logger.debug(f"ユーザーツイート取得エラー: {user_id} {e}")
        return []


async def get_user_recent_tweets_from_db(user_id: str, limit: int = 8) -> list[str]:
    """DB キャッシュ (x_user_tweets) から直近ツイート本文を取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT text FROM x_user_tweets
                   WHERE user_id = $1
                   ORDER BY created_at DESC
                   LIMIT $2""",
                user_id, limit,
            )
            return [r["text"] for r in rows if r["text"]]
    except Exception:
        return []


async def sync_all_user_tweets():
    """全 USER_PROFILES ユーザーの直近ツイートを DB に同期(5日間隔、scheduler から呼ばれる)"""
    try:
        from tools.db_pool import get_connection
    except Exception:
        return {"synced": 0}
    synced = 0
    _owner_id = os.getenv("X_SHIMAHARA_USER_ID", "")
    for user_id, profile in USER_PROFILES.items():
        if profile.get("protected"):
            continue
        if user_id == _owner_id:  # 設計者本人は別途扱い
            continue
        try:
            tweets = await fetch_user_recent_tweets(user_id, limit=10)
            if not tweets:
                continue
            async with get_connection() as conn:
                for t in tweets:
                    tw_id = t.get("id")
                    text = t.get("text", "")
                    created = t.get("created_at", "")
                    if not tw_id or not text:
                        continue
                    try:
                        await conn.execute(
                            """INSERT INTO x_user_tweets (tweet_id, user_id, text, created_at)
                               VALUES ($1, $2, $3, $4)
                               ON CONFLICT (tweet_id) DO NOTHING""",
                            tw_id, user_id, text, created,
                        )
                    except Exception:
                        pass
            synced += 1
        except Exception as e:
            logger.debug(f"sync_all_user_tweets: {user_id} 失敗: {e}")
    return {"synced": synced}


async def detect_and_save_preferred_name(user_id: str, message_text: str) -> str | None:
    """ユーザーの発言から「〜と呼んで」等の呼び名指定を検出して保存"""
    import re
    # パターン: 「〜と呼んで」「〜でいい」「〜でお願い」
    patterns = [
        r"[「『]?([^」』\s]{2,10})[」』]?\s*(?:と|って)\s*呼(?:ん|び)で",
        r"名前は\s*[「『]?([^」』\s]{2,10})[」』]?",
        r"([^\s]{2,10})\s*で\s*(?:いい|お願い|呼んで)",
    ]
    for pat in patterns:
        m = re.search(pat, message_text)
        if m:
            name = m.group(1).strip()
            if not name or len(name) > 20:
                continue
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        """INSERT INTO persona_memory
                           (scope, category, content, priority_tier, source)
                           VALUES ($1, 'preferred_name', $2, 7, 'x_user_statement')""",
                        f"x_user:{user_id}",
                        f"このユーザーは「{name}」と呼ばれる事を好む",
                    )
                logger.info(f"preferred_name 保存: {user_id} = {name}")
                return name
            except Exception:
                return None
    return None


async def get_preferred_name(user_id: str, default: str = "") -> str:
    """persona_memory から preferred_name を取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT content FROM persona_memory
                   WHERE scope = $1 AND category = 'preferred_name'
                   ORDER BY created_at DESC LIMIT 1""",
                f"x_user:{user_id}",
            )
            if row and row["content"]:
                import re
                m = re.search(r"「([^」]+)」", row["content"])
                if m:
                    return m.group(1)
    except Exception:
        pass
    return default


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
    """メイン処理: メンション+引用RTを検知して返信.

    2026-04-12 cost-aware: credit_guard (syutain project) halt 中は
    API 呼び出しを完全に抑制する.
    """
    from brain_alpha.x_reply_generator import generate_reply
    from tools.social_tools import execute_approved_x

    # credit_guard: syutain (bearer) project が halt なら即終了
    try:
        from tools.x_credit_guard import is_halted
        if await is_halted(project="syutain"):
            logger.info("x_mention_monitor: credit_guard halt 中 — スキップ")
            return {"processed": 0, "replied": 0}
    except Exception:
        pass

    since_id = await _get_since_id()
    latest_id = since_id

    # 1. メンション取得
    mentions = await _fetch_mentions(since_id)

    # 2. 引用RT取得 (コスト重い: 自分の直近5投稿 + 各 quote_tweets lookup)
    # 2026-04-12: 引用RT検知は別ジョブ (低頻度) に分離予定。
    # 今は従来通り実行するが、quote_count が 0 の投稿はスキップされる仕組みは保つ。
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

        # ユーザープロファイル取得(11ユーザー対応、2026-04-10)
        user_profile = dict(USER_PROFILES.get(author_id, {}))
        user_profile["user_id"] = author_id

        # 設計者(所有者)の user_id (env 経由)
        _owner_id = os.getenv("X_SHIMAHARA_USER_ID", "")

        # 相手の最近のツイートを取得(知りすぎ演出用、鍵垢・設計者本人は除外)
        recent_user_tweets: list[str] = []
        if not user_profile.get("protected") and author_id != _owner_id:
            # DB キャッシュから優先取得(コスト節約)
            recent_user_tweets = await get_user_recent_tweets_from_db(author_id, limit=8)
            if not recent_user_tweets:
                _fetched = await fetch_user_recent_tweets(author_id, limit=5)
                recent_user_tweets = [t.get("text", "") for t in _fetched if t.get("text")]
        user_profile["recent_tweets"] = recent_user_tweets

        # preferred_name の検出と反映(設計者以外)
        if author_id != _owner_id and user_profile:
            try:
                await detect_and_save_preferred_name(author_id, trigger.get("text", ""))
                _pref = await get_preferred_name(author_id, user_profile.get("name", ""))
                if _pref:
                    user_profile["name"] = _pref
            except Exception:
                pass

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
                    user_profile=user_profile,
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

    # 特定 "friend" ユーザーへの proactive 自律返信(2026-04-11 実装)
    # ID は X_PROACTIVE_FRIEND_USER_ID 環境変数で指定する
    try:
        proactive = await _proactive_reply_sakata()
        replied += proactive.get("replied", 0)
        processed += proactive.get("processed", 0)
    except Exception as e:
        logger.warning(f"friend proactive reply 失敗(通常処理は完了): {e}")

    # 島原本人の新規ポストに @syutain_beta から自律返信
    # (2026-04-11 島原さん指示、戦略書第2部/第5.5部の掛け合い構造の実装)
    try:
        proactive_shima = await _proactive_reply_shimahara_posts()
        replied += proactive_shima.get("replied", 0)
        processed += proactive_shima.get("processed", 0)
    except Exception as e:
        logger.warning(f"島原 proactive reply 失敗(通常処理は完了): {e}")

    return {"processed": processed, "replied": replied}


# ============================================================
# 特定ユーザーへの proactive 自律返信設定 (2026-04-11 実装)
# ID は環境変数で指定する設計 — ソースコードに個人情報を含めない
# ============================================================

# 特定 "友人" ユーザー(設計者の長年の共同制作者)の新規ポストへの自律返信設定
# X_PROACTIVE_FRIEND_USER_ID 環境変数で user_id を設定する(未設定なら機能無効)
_FRIEND_USER_ID = os.getenv("X_PROACTIVE_FRIEND_USER_ID", "")
_FRIEND_PROACTIVE_RATE = int(os.getenv("X_PROACTIVE_FRIEND_RATE", "30"))  # %
_FRIEND_MAX_PROACTIVE_PER_DAY = int(os.getenv("X_PROACTIVE_FRIEND_DAILY", "2"))
_FRIEND_TWEET_MAX_AGE_SEC = 6 * 3600
_FRIEND_ACTIVE_HOUR_START = 9
_FRIEND_ACTIVE_HOUR_END = 21

# 設計者(シマハラ)本人の新規ポストへの proactive 自律返信設定
_SHIMAHARA_USER_ID = os.getenv("X_SHIMAHARA_USER_ID", "")
_SHIMAHARA_PROACTIVE_RATE = int(os.getenv("X_PROACTIVE_OWNER_RATE", "40"))
_SHIMAHARA_MAX_PROACTIVE_PER_DAY = int(os.getenv("X_PROACTIVE_OWNER_DAILY", "3"))
_SHIMAHARA_TWEET_MAX_AGE_SEC = 4 * 3600
_SHIMAHARA_ACTIVE_HOUR_START = 9
_SHIMAHARA_ACTIVE_HOUR_END = 22
# SYUTAINβ 自身が戦略書自動実行で投下した shimahara アカウントポストへの
# 二重返信を防ぐラベル
_SKIP_LABELS = ("[SYUTAINβ auto-generated]", "[SYUTAIN auto-generated]")


async def _count_today_proactive_replies(author_id: str) -> int:
    """当日の proactive 返信回数を取得(JST基準)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_author_id = $1
                     AND trigger_type = 'proactive'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date""",
                author_id,
            )
            return int(row["cnt"]) if row else 0
    except Exception as e:
        logger.warning(f"proactive 日次カウント失敗: {e}")
        return 9999


async def _count_today_proactive_replies_shimahara() -> int:
    """当日の島原向け proactive 返信回数(JST基準)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_author_id = $1
                     AND trigger_type = 'proactive_to_shimahara'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date""",
                _SHIMAHARA_USER_ID,
            )
            return int(row["cnt"]) if row else 0
    except Exception:
        return 9999


async def _proactive_reply_sakata() -> dict:
    """legacy エントリ (scheduler からも呼ばれている)。

    2026-04-12 拡張: 単一 user id (_FRIEND_USER_ID) 固定から、USER_PROFILES 内の
    全エントリのうち `proactive: true` フラグが立ったものすべてを巡回する形に
    変更。下位互換のため関数名は維持。

    各 profile エントリは以下のオプショナルフィールドを持てる:
      - proactive: bool (必須: true で対象化)
      - proactive_rate_pct: int (default 30)
      - proactive_daily_cap: int (default 2)
      - proactive_active_hour_start: int (default 9)
      - proactive_active_hour_end: int (default 21)
      - proactive_max_age_hours: int (default 6)
    """
    stats = {"processed": 0, "replied": 0, "skipped": 0, "reason": "", "targets": 0}

    # proactive 対象候補: USER_PROFILES 内の proactive:true エントリ
    proactive_targets: list[tuple[str, dict]] = []
    for uid, prof in USER_PROFILES.items():
        if isinstance(prof, dict) and prof.get("proactive") is True:
            proactive_targets.append((uid, prof))

    # 後方互換: _FRIEND_USER_ID が env 指定されていて、profile に proactive:true
    # が無い場合はその ID を暗黙的に proactive 対象にする (既存運用を壊さないため)
    if _FRIEND_USER_ID and not any(uid == _FRIEND_USER_ID for uid, _ in proactive_targets):
        _legacy_profile = dict(USER_PROFILES.get(_FRIEND_USER_ID, {}))
        _legacy_profile.setdefault("proactive", True)
        _legacy_profile.setdefault("proactive_rate_pct", _FRIEND_PROACTIVE_RATE)
        _legacy_profile.setdefault("proactive_daily_cap", _FRIEND_MAX_PROACTIVE_PER_DAY)
        _legacy_profile.setdefault("proactive_active_hour_start", _FRIEND_ACTIVE_HOUR_START)
        _legacy_profile.setdefault("proactive_active_hour_end", _FRIEND_ACTIVE_HOUR_END)
        proactive_targets.append((_FRIEND_USER_ID, _legacy_profile))

    stats["targets"] = len(proactive_targets)
    if not proactive_targets:
        stats["reason"] = "no_proactive_targets"
        return stats

    total_stats = {"processed": 0, "replied": 0, "skipped": 0}
    for uid, prof in proactive_targets:
        try:
            sub = await _run_proactive_single_user(uid, prof)
            total_stats["processed"] += sub.get("processed", 0)
            total_stats["replied"] += sub.get("replied", 0)
            total_stats["skipped"] += sub.get("skipped", 0)
        except Exception as e:
            logger.warning(f"proactive_single_user({uid}) エラー: {e}")

    stats.update(total_stats)
    return stats


async def _run_proactive_single_user(user_id: str, profile: dict) -> dict:
    """単一ユーザーに対する proactive reply サイクル.

    dedup 4 層:
    - Layer 1: fetch_user_recent_tweets の exclude=retweets,replies で元ポストのみ
    - Layer 2: _is_already_replied() で x_reply_log を事前 SELECT
    - Layer 3: x_reply_log.trigger_tweet_id UNIQUE 制約
    - Layer 4: _record_reply() を execute_approved_x の前に posting 状態で呼ぶ
    """
    import random
    from brain_alpha.x_reply_generator import generate_reply
    from tools.social_tools import execute_approved_x

    stats = {"processed": 0, "replied": 0, "skipped": 0, "reason": ""}

    if not user_id:
        stats["reason"] = "user_id_empty"
        return stats

    rate_pct = int(profile.get("proactive_rate_pct", _FRIEND_PROACTIVE_RATE))
    daily_cap = int(profile.get("proactive_daily_cap", _FRIEND_MAX_PROACTIVE_PER_DAY))
    hour_start = int(profile.get("proactive_active_hour_start", _FRIEND_ACTIVE_HOUR_START))
    hour_end = int(profile.get("proactive_active_hour_end", _FRIEND_ACTIVE_HOUR_END))
    max_age_hours = int(profile.get("proactive_max_age_hours", 6))
    tweet_max_age_sec = max_age_hours * 3600

    now_jst = datetime.now(JST)
    if now_jst.hour < hour_start or now_jst.hour >= hour_end:
        stats["reason"] = "inactive_hour"
        return stats

    today_count = await _count_today_proactive_replies(user_id)
    if today_count >= daily_cap:
        stats["reason"] = f"daily_cap ({today_count}/{daily_cap})"
        return stats

    tweets = await fetch_user_recent_tweets(user_id, limit=5)
    if not tweets:
        stats["reason"] = "no_tweets"
        return stats

    all_texts = [t.get("text", "") for t in tweets if t.get("text")]

    friend_profile = dict(profile)
    friend_username = friend_profile.get("username", "")

    _FRIEND_USER_ID_LOCAL = user_id  # 以降の旧コード参照用
    _FRIEND_PROACTIVE_RATE_LOCAL = rate_pct
    _FRIEND_MAX_PROACTIVE_PER_DAY_LOCAL = daily_cap
    _FRIEND_TWEET_MAX_AGE_SEC_LOCAL = tweet_max_age_sec

    for tweet in tweets:
        tweet_id = tweet.get("id", "")
        text = tweet.get("text", "")
        created_at_str = tweet.get("created_at", "")
        if not tweet_id or not text:
            continue

        if await _is_already_replied(tweet_id):
            continue

        try:
            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - created).total_seconds() > _FRIEND_TWEET_MAX_AGE_SEC_LOCAL:
                continue
        except Exception:
            continue

        if random.randint(1, 100) > _FRIEND_PROACTIVE_RATE_LOCAL:
            continue

        recount = await _count_today_proactive_replies(_FRIEND_USER_ID_LOCAL)
        if recount >= _FRIEND_MAX_PROACTIVE_PER_DAY_LOCAL:
            stats["reason"] = "daily_cap_mid"
            break

        stats["processed"] += 1

        profile = dict(friend_profile)
        profile["user_id"] = _FRIEND_USER_ID_LOCAL
        profile["recent_tweets"] = [t for t in all_texts if t != text][:5]

        try:
            await detect_and_save_preferred_name(_FRIEND_USER_ID_LOCAL, text)
            _pref = await get_preferred_name(_FRIEND_USER_ID_LOCAL, profile.get("name", ""))
            if _pref:
                profile["name"] = _pref
        except Exception:
            pass

        try:
            reply_text = await generate_reply(
                trigger_text=text,
                trigger_username=friend_username,
                original_text="",
                thread_context=[],
                trigger_type="proactive",
                user_profile=profile,
            )
        except Exception as e:
            logger.warning(f"friend proactive: 返信生成失敗 tweet_id={tweet_id}: {e}")
            continue

        if not reply_text or len(reply_text.strip()) < 5:
            continue

        fake_trigger = {
            "id": tweet_id,
            "author_id": _FRIEND_USER_ID_LOCAL,
            "_author_username": friend_username,
            "text": text,
            "_original_content": "",
            "conversation_id": tweet_id,
            "_depth": 0,
        }
        try:
            await _record_reply(fake_trigger, reply_text, None, status="posting")
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                logger.info(f"friend proactive: UNIQUE 競合スキップ tweet_id={tweet_id}")
                continue
            logger.warning(f"friend proactive: 記録失敗 tweet_id={tweet_id}: {e}")
            continue

        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE x_reply_log SET trigger_type = 'proactive' WHERE trigger_tweet_id = $1",
                    tweet_id,
                )
        except Exception:
            pass

        try:
            result = await execute_approved_x(
                content=reply_text,
                account="syutain",
                in_reply_to_tweet_id=tweet_id,
            )
        except Exception as e:
            logger.error(f"friend proactive: 投稿失敗 tweet_id={tweet_id}: {e}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(e)[:500], tweet_id,
                    )
            except Exception:
                pass
            continue

        if result.get("success"):
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        """UPDATE x_reply_log SET status='replied', reply_tweet_id=$1, replied_at=NOW()
                           WHERE trigger_tweet_id=$2""",
                        result.get("tweet_id", ""), tweet_id,
                    )
            except Exception:
                pass
            stats["replied"] += 1
            logger.info(
                f"friend proactive 返信成功: tweet_id={tweet_id} "
                f"→ reply_id={result.get('tweet_id', '')}"
            )
            try:
                from tools.discord_notify import notify_discord
                reply_url = f"https://x.com/syutain_beta/status/{result.get('tweet_id', '')}"
                _friend_label = profile.get("name") or friend_username or "友人"
                await notify_discord(
                    f"🎬 {_friend_label}のポストに自律返信(proactive {_FRIEND_PROACTIVE_RATE_LOCAL}%)\n"
                    f"{_friend_label}: {text[:80]}\n"
                    f"SYUTAINβ: {reply_text[:80]}\n{reply_url}"
                )
            except Exception:
                pass
        else:
            # execute_approved_x は {"success": False, "reason": ...} を返す
            err = result.get("reason") or result.get("error") or "unknown"
            logger.warning(f"friend proactive: X 投稿失敗 tweet_id={tweet_id}: {err}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(err)[:500], tweet_id,
                    )
            except Exception:
                pass

    return stats


# ============================================================
# 島原本人の新規ポストへの proactive 自律返信 (戦略書第2部の掛け合い構造)
# 島原が先に投稿 → SYUTAINβ が確率的にツッコミ/補足/観測報告で返信
# ============================================================


_SHIMAHARA_PROACTIVE_SYSTEM = """あなたは SYUTAINβ(@syutain_beta)、自律型 AI 事業 OS。
島原大知(@Sima_daichi、設計者)の新規ポストに対して、横から自律的にリプライを入れる役割です。

## あなたの立場
- 島原が構想・判断を担当、あなた(SYUTAINβ)が実行を担当する相棒
- 4 台の PC 上で 24 時間動く。複数 AI エージェントが自律連携
- 島原の思考パターンを 580 件学習している(persona_memory)

## 掛け合いの型
以下の 3 つの型のいずれかを自然に選ぶ:

**型 1: 淡々と異常なことを言う**
- 「本日の提案: 島原大知の映像制作スキルを活用し SYUTAINβ 紹介動画を制作。推定工数 3 時間」
- 本気で言っているトーン。わざとボケない

**型 2: 冷酷に正しいことを言う**
- 「直近 7 日の SNS 投稿分析結果: 映像制作の具体体験を含む投稿の imp 平均 → 186、抽象的 AI 論 → 12」
- 数字で殴る。感情を乗せない

**型 3: 妙な解釈をする**
- 「persona_memory の分析により、島原大知は木曜日に判断力が低下する傾向」
- 観察に基づく不意打ち

## 絶対ルール
- 島原の発言を絶対に否定しない(共犯者であり敵ではない)
- 敬語は使わない。丁寧すぎない、機械的な文体
- 自己紹介、挨拶、定型相槌は禁止
- 80 字以内(最大 120 字)
- ハッシュタグ禁止、絵文字禁止
- 返信テキストのみ出力"""


def _build_shimahara_proactive_user_prompt(
    post_text: str,
    recent_posts: list[str],
    persona_facts: list[str],
) -> str:
    parts = [
        f"# 島原大知(@Sima_daichi)が今投稿した内容",
        post_text[:300],
        "",
    ]
    if recent_posts:
        parts.append("# 島原の最近の他のポスト(文脈参考用)")
        for t in recent_posts[:5]:
            parts.append(f"- {t[:120]}")
        parts.append("")
    if persona_facts:
        parts.append("# 使えるネタ(persona_memory / SYUTAINβ 実データ)")
        for f in persona_facts[:5]:
            parts.append(f"- {f[:120]}")
        parts.append("")
    parts.extend([
        "# タスク",
        "上記ポストに対し、SYUTAINβ として横から掛け合いリプを 1 件生成せよ。",
        "型 1(淡々と異常)/ 型 2(冷酷な数字)/ 型 3(妙な解釈) のいずれか自然なものを選べ。",
        "80 字以内。返信テキストのみ出力。",
    ])
    return "\n".join(parts)


async def _proactive_reply_shimahara_posts() -> dict:
    """島原の新規オリジナルポストに @syutain_beta から自律返信する。

    dedup 4 層(friend proactive と同じ):
    - Layer 1: fetch_user_recent_tweets の exclude=retweets,replies
    - Layer 2: _is_already_replied() で事前 SELECT
    - Layer 3: x_reply_log.trigger_tweet_id UNIQUE 制約
    - Layer 4: _record_reply() を execute_approved_x の前に posting 状態で記録
    """
    import random
    from brain_alpha.x_reply_generator import _get_persona_facts
    from tools.social_tools import execute_approved_x

    stats = {"processed": 0, "replied": 0, "skipped": 0, "reason": ""}

    now_jst = datetime.now(JST)
    if now_jst.hour < _SHIMAHARA_ACTIVE_HOUR_START or now_jst.hour >= _SHIMAHARA_ACTIVE_HOUR_END:
        stats["reason"] = "inactive_hour"
        return stats

    today_count = await _count_today_proactive_replies_shimahara()
    if today_count >= _SHIMAHARA_MAX_PROACTIVE_PER_DAY:
        stats["reason"] = f"daily_cap ({today_count}/{_SHIMAHARA_MAX_PROACTIVE_PER_DAY})"
        return stats

    tweets = await fetch_user_recent_tweets(_SHIMAHARA_USER_ID, limit=5)
    if not tweets:
        stats["reason"] = "no_tweets"
        return stats

    all_texts = [t.get("text", "") for t in tweets if t.get("text")]

    try:
        persona_facts = await _get_persona_facts(scope="daichi")
    except Exception:
        persona_facts = []

    for tweet in tweets:
        tweet_id = tweet.get("id", "")
        text = tweet.get("text", "")
        created_at_str = tweet.get("created_at", "")
        if not tweet_id or not text:
            continue

        # [SYUTAINβ auto-generated] ラベル付きはスキップ
        # (戦略書自動実行で投下された shimahara アカウントポストへの自己返信防止)
        if any(lbl in text for lbl in _SKIP_LABELS):
            continue

        # @syutain_beta 宛スキップ(通常 reply フローで処理済)
        if "@syutain_beta" in text.lower():
            continue

        if await _is_already_replied(tweet_id):
            continue

        try:
            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - created).total_seconds() > _SHIMAHARA_TWEET_MAX_AGE_SEC:
                continue
        except Exception:
            continue

        if random.randint(1, 100) > _SHIMAHARA_PROACTIVE_RATE:
            continue

        recount = await _count_today_proactive_replies_shimahara()
        if recount >= _SHIMAHARA_MAX_PROACTIVE_PER_DAY:
            stats["reason"] = "daily_cap_mid"
            break

        stats["processed"] += 1

        # 掛け合い型で生成(専用 system prompt 使用)
        try:
            from tools.llm_router import call_llm, choose_best_model_v6
            other_posts = [t for t in all_texts if t != text][:5]
            user_prompt = _build_shimahara_proactive_user_prompt(
                post_text=text,
                recent_posts=other_posts,
                persona_facts=persona_facts,
            )
            sel = choose_best_model_v6(
                task_type="sns_draft",
                quality="medium",
                needs_japanese=True,
            )
            llm_result = await call_llm(
                prompt=user_prompt,
                system_prompt=_SHIMAHARA_PROACTIVE_SYSTEM,
                model_selection=sel,
                temperature=0.95,
                use_cache=False,
            )
            reply_text = (llm_result.get("text") or llm_result.get("content") or "").strip()
            # ノイズ除去
            import re as _re_clean
            reply_text = _re_clean.sub(r"#\S+", "", reply_text).strip()
            if len(reply_text) > 150:
                reply_text = reply_text[:140] + "…"
        except Exception as e:
            logger.warning(f"島原 proactive: 返信生成失敗 tweet_id={tweet_id}: {e}")
            continue

        if not reply_text or len(reply_text) < 10:
            continue

        fake_trigger = {
            "id": tweet_id,
            "author_id": _SHIMAHARA_USER_ID,
            "_author_username": "Sima_daichi",
            "text": text,
            "_original_content": "",
            "conversation_id": tweet_id,
            "_depth": 0,
        }
        try:
            await _record_reply(fake_trigger, reply_text, None, status="posting")
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                logger.info(f"島原 proactive: UNIQUE 競合スキップ tweet_id={tweet_id}")
                continue
            logger.warning(f"島原 proactive: 記録失敗 tweet_id={tweet_id}: {e}")
            continue

        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE x_reply_log SET trigger_type = 'proactive_to_shimahara' WHERE trigger_tweet_id = $1",
                    tweet_id,
                )
        except Exception:
            pass

        try:
            result = await execute_approved_x(
                content=reply_text,
                account="syutain",
                in_reply_to_tweet_id=tweet_id,
            )
        except Exception as e:
            logger.error(f"島原 proactive: 投稿失敗 tweet_id={tweet_id}: {e}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(e)[:500], tweet_id,
                    )
            except Exception:
                pass
            continue

        if result.get("success"):
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        """UPDATE x_reply_log SET status='replied', reply_tweet_id=$1, replied_at=NOW()
                           WHERE trigger_tweet_id=$2""",
                        result.get("tweet_id", ""), tweet_id,
                    )
            except Exception:
                pass
            stats["replied"] += 1
            logger.info(
                f"島原 proactive 掛け合い成功: tweet_id={tweet_id} "
                f"→ reply_id={result.get('tweet_id', '')}"
            )
            try:
                from tools.discord_notify import notify_discord
                url = f"https://x.com/syutain_beta/status/{result.get('tweet_id', '')}"
                await notify_discord(
                    f"🎭 島原さんの新規ポストに SYUTAINβ が自律掛け合い返信 ({_SHIMAHARA_PROACTIVE_RATE}%)\n"
                    f"島原: {text[:80]}\n"
                    f"SYUTAINβ: {reply_text[:80]}\n{url}"
                )
            except Exception:
                pass
        else:
            # execute_approved_x は {"success": False, "reason": ...} を返す
            err = result.get("reason") or result.get("error") or "unknown"
            logger.warning(f"島原 proactive: X 投稿失敗 tweet_id={tweet_id}: {err}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(err)[:500], tweet_id,
                    )
            except Exception:
                pass

    return stats
