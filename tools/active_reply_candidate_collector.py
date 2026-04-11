"""
Active Reply 候補収集 — 毎日 09:00 JST

2026-04-11 刷新: 従来 intel_items (grok_x_research) から取っていた候補は大手メディア
バイアスが強く、100% 403 Forbidden で失敗していた。

新方針:
- X API v2 search_recent_tweets を直接叩く (Basic tier で使用可能)
- 複数の niche クエリを走らせて AI/映像/VTuber 関連のツイートを集める
- author 条件: verified=true かつ followers_count が 1000〜9999 (4桁台)
- tweet 条件: reply_settings='everyone' のみ (403 を構造的に排除)
- 候補は active_reply_candidates テーブルに保存 (used フラグで dedup)
- 同一作者は 1 候補まで (同じ人に連投しない)

目的:
- 認証済フォロワー 2,000 獲得 (X 収益分配の要件)
- 4桁台は読んで反応を返してくれる確率が高く、リフォロー期待値も高い
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 収集クエリセット (7 本 * 最大 100 件 = 1 回の cycle で ~700 ツイート評価)
# search_recent_tweets の rate: Basic tier 180req/月 = 1日 6 req 安全圏
SEARCH_QUERIES = [
    "AI クリエイター -is:retweet lang:ja",
    "#個人開発 -is:retweet lang:ja",
    "AI動画 -is:retweet lang:ja",
    "VTuber 開発 -is:retweet lang:ja",
    "映像作家 -is:retweet lang:ja",
    "Build in Public AI -is:retweet",
    "indie hacker AI -is:retweet",
]

# 候補条件
MIN_FOLLOWERS = 1000
MAX_FOLLOWERS = 9999
MAX_TWEETS_PER_QUERY = 50  # search_recent_tweets の max_results


def _build_client():
    """X API 読み取り専用クライアント (bearer token ベース)"""
    import tweepy
    bearer = os.getenv("X_BEARER_TOKEN", "")
    if not bearer:
        raise RuntimeError("X_BEARER_TOKEN not set")
    return tweepy.Client(bearer_token=bearer)


async def _upsert_candidate(conn, cand: dict) -> bool:
    """候補を UPSERT。既存 tweet_id ならスキップ"""
    try:
        await conn.execute(
            """INSERT INTO active_reply_candidates
               (tweet_id, author_id, author_username, author_name, author_description,
                author_verified_type, author_followers_count, tweet_text, tweet_lang,
                tweet_created_at, reply_settings, search_query)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               ON CONFLICT (tweet_id) DO NOTHING""",
            cand["tweet_id"], cand["author_id"], cand["author_username"],
            cand.get("author_name"), cand.get("author_description"),
            cand.get("author_verified_type"), cand.get("author_followers_count"),
            cand["tweet_text"], cand.get("tweet_lang"),
            cand.get("tweet_created_at"), cand.get("reply_settings"),
            cand.get("search_query"),
        )
        return True
    except Exception as e:
        logger.warning(f"候補 upsert 失敗 tweet_id={cand.get('tweet_id')}: {e}")
        return False


async def _count_fresh_candidates(conn) -> int:
    row = await conn.fetchrow(
        """SELECT count(*) as c FROM active_reply_candidates
           WHERE used = FALSE AND collected_at > NOW() - INTERVAL '48 hours'"""
    )
    return int(row["c"]) if row else 0


async def collect_active_reply_candidates() -> dict:
    """候補を X API から取得して DB に保存する。毎日 09:00 JST 実行。

    Returns: {"queries_run": int, "tweets_seen": int, "candidates_saved": int, ...}
    """
    import tweepy
    from tools.db_pool import get_connection

    stats = {
        "queries_run": 0,
        "tweets_seen": 0,
        "candidates_saved": 0,
        "filtered_out": 0,
        "errors": 0,
        "reason": "",
    }

    # X Credit Guard: 402 halt 中ならスキップ
    try:
        from tools.x_credit_guard import is_halted
        if await is_halted():
            stats["reason"] = "x_credit_guard_halted"
            logger.info("active_reply_collector: credit_guard halt 中、スキップ")
            return stats
    except Exception:
        pass

    try:
        client = _build_client()
    except Exception as e:
        stats["reason"] = f"client_init_failed: {e}"
        logger.error(f"X client 初期化失敗: {e}")
        return stats

    # 同一作者 dedup (このサイクル内)
    seen_authors: set[str] = set()
    candidates_buffer: list[dict] = []

    for query in SEARCH_QUERIES:
        try:
            resp = client.search_recent_tweets(
                query=query,
                max_results=MAX_TWEETS_PER_QUERY,
                tweet_fields=["reply_settings", "created_at", "public_metrics", "lang"],
                expansions=["author_id"],
                user_fields=["verified", "verified_type", "public_metrics", "description", "name"],
            )
            stats["queries_run"] += 1
        except tweepy.TooManyRequests as e:
            logger.warning(f"search rate limited on {query!r}: {e}")
            stats["errors"] += 1
            break
        except Exception as e:
            logger.warning(f"search failed {query!r}: {e}")
            stats["errors"] += 1
            # 402 検出で credit_guard 発動し以降は skip
            try:
                from tools.x_credit_guard import is_402_error, register_402
                if is_402_error(e):
                    await register_402(endpoint_hint="search_recent_tweets")
                    stats["reason"] = "credit_402_halt"
                    return stats
            except Exception:
                pass
            continue

        users_by_id: dict[str, Any] = {}
        if resp.includes and "users" in resp.includes:
            users_by_id = {u.id: u for u in resp.includes["users"]}

        if not resp.data:
            continue

        for t in resp.data:
            stats["tweets_seen"] += 1
            u = users_by_id.get(t.author_id)
            if not u:
                stats["filtered_out"] += 1
                continue

            # フィルタ 1: verified (verified_type=blue/business/government)
            vt = getattr(u, "verified_type", None) or ""
            is_verified = bool(u.verified) and vt in ("blue", "business", "government")
            if not is_verified:
                stats["filtered_out"] += 1
                continue

            # フィルタ 2: followers 1000〜9999
            pm = u.public_metrics or {}
            fc = pm.get("followers_count", 0)
            if not (MIN_FOLLOWERS <= fc <= MAX_FOLLOWERS):
                stats["filtered_out"] += 1
                continue

            # フィルタ 3: reply_settings='everyone'
            rs = getattr(t, "reply_settings", None)
            if rs != "everyone":
                stats["filtered_out"] += 1
                continue

            # フィルタ 4: 同一作者は 1 候補まで (このサイクル内)
            if u.username.lower() in seen_authors:
                stats["filtered_out"] += 1
                continue
            seen_authors.add(u.username.lower())

            candidates_buffer.append({
                "tweet_id": str(t.id),
                "author_id": str(u.id),
                "author_username": u.username,
                "author_name": u.name,
                "author_description": (u.description or "")[:500],
                "author_verified_type": vt,
                "author_followers_count": int(fc),
                "tweet_text": (t.text or "")[:500],
                "tweet_lang": getattr(t, "lang", None),
                "tweet_created_at": t.created_at,
                "reply_settings": rs,
                "search_query": query[:200],
            })

    # DB 書き込み (同一 tweet_id は既存チェックで自動スキップ)
    async with get_connection() as conn:
        for cand in candidates_buffer:
            ok = await _upsert_candidate(conn, cand)
            if ok:
                stats["candidates_saved"] += 1

        fresh = await _count_fresh_candidates(conn)
        stats["fresh_candidates_in_db"] = fresh

    logger.info(
        f"active_reply 候補収集: queries={stats['queries_run']} seen={stats['tweets_seen']} "
        f"saved={stats['candidates_saved']} filtered={stats['filtered_out']} "
        f"fresh_in_db={fresh}"
    )
    return stats
