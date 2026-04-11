"""
X Quote-RT Loop — バズ投稿への高品質引用リツイート

目的:
- X 収益分配 (500万imp/90d) / サブスク解放 (認証済フォロワー 2,000) への直接貢献
- 認証済 4桁台クリエイターのバズった投稿 (engagement 高) に
  shimahara/syutain_beta から価値のある引用 RT を投下
- 相手のインプにも貢献するので、相互メンションの可能性が上がる

設計:
- X API search_recent_tweets で AI/クリエイター niche のハイエンゲージメント投稿を収集
- フィルタ:
  - verified_type in (blue, business, government)
  - followers 1,000〜9,999 (4桁台)
  - reply_settings='everyone' (quote RT は設定に依存しないが一応)
  - like_count >= 10 かつ retweet_count >= 3 (バズ閾値)
  - created_at が 1〜6 時間前 (新鮮かつ露出済み)
  - 自分の所有アカウントは除外
- 生成: shimahara/syutain_beta 両方で分析的な一言コメント付きで引用 RT
- ガード:
  - 日次上限 2 件 / アカウント (計 4 件)
  - 同一 tweet への二重引用を構造的に禁止 (x_reply_log UNIQUE)
  - 同一作者への日次1件上限
  - dry_run モード対応

スケジュール: 毎日 12:00 / 20:00 JST (active_reply と時間をずらして投下パターンを散らす)
"""
from __future__ import annotations

import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 設定値
MAX_QUOTE_PER_DAY_PER_ACCOUNT = 2
MIN_TWEET_AGE_HOURS = 1
MAX_TWEET_AGE_HOURS = 6
MIN_LIKES = 10
MIN_RETWEETS = 3
MIN_FOLLOWERS = 1000
MAX_FOLLOWERS = 9999

# search クエリ (active_reply_candidate_collector と同じ niche を引き継ぐが、
# public_metrics でフィルタするので重複候補が出る可能性あり → x_reply_log で dedup)
SEARCH_QUERIES = [
    "AI クリエイター -is:retweet lang:ja",
    "#個人開発 -is:retweet lang:ja",
    "AI動画 -is:retweet lang:ja",
    "映像制作 -is:retweet lang:ja",
]


def _load_blocked_authors() -> set[str]:
    items: set[str] = set()
    for env_key in (
        "X_SHIMAHARA_USER_ID", "X_SHIMAHARA_USERNAME",
        "X_SYUTAIN_USER_ID", "X_SYUTAIN_USERNAME",
    ):
        v = os.getenv(env_key, "").strip()
        if v:
            items.add(v.lower().lstrip("@"))
    return items


_BLOCKED_AUTHORS_NORM = _load_blocked_authors()


# 引用 RT のシステムプロンプト (shimahara 版)
_QUOTE_SYSTEM_SHIMAHARA = """あなたは島原大知(@Sima_daichi)本人として、バズっている他者の X 投稿を引用 RT する。

## 島原大知
- 非エンジニアの個人事業主。AI 活用の事業 OS を開発中
- 冷静で観察的。押し付けない、売り込まない
- バズっている投稿に対して、自分の視点を一言添えて引用 RT する

## 引用 RT の書き方
- 15〜60字 (引用 RT は本体ツイートが表示されるので短めが効く)
- 敬語基本
- 相手の投稿への肯定 + 自分の視点を一言
- 疑問符で終わらない
- 絵文字禁止、ハッシュタグ禁止、URL 禁止
- 相手を持ち上げつつ、自分の観測/意見を1つ足す
- クソリプと思われない、礼節を保つ

## 出力
引用コメントのテキストのみ。前置き・説明・ラベル禁止。"""

_QUOTE_SYSTEM_SYUTAIN = """あなたは SYUTAINβ(@syutain_beta)、島原大知が作った自律型 AI 事業 OS。
バズっている他者の X 投稿を引用 RT する。

## SYUTAINβ
- 冷静・分析的・観察的。感情を乗せない機械口調ではなく、落ち着いた人間らしいトーン
- データや構造に注目する視点を添える

## 引用 RT の書き方
- 15〜60字
- 敬語 (「〜ですね」「〜かもしれません」)
- 相手の投稿の内容をちゃんと読んで、構造 / パターン / 本質について短く補足
- 疑問符で終わらない
- 絵文字禁止、ハッシュタグ禁止、URL 禁止
- 一人称は「私」
- 売り込み禁止 (SYUTAINβ を宣伝する内容は絶対に書かない)

## 出力
引用コメントのテキストのみ。"""


# 品質チェック用 regex
_RE_EMOJI = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\u2600-\u27BF\u2700-\u27BF]"
)
_RE_HASHTAG = re.compile(r"#\S+")
_RE_URL = re.compile(r"https?://\S+")
_RE_MULTI_EXCLAIM = re.compile(r"[!！]{2,}")


def _quality_check(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if len(t) < 10:
        return False, f"too_short ({len(t)})"
    if len(t) > 70:
        return False, f"too_long ({len(t)})"
    if _RE_EMOJI.search(t):
        return False, "emoji"
    if _RE_HASHTAG.search(t):
        return False, "hashtag"
    if _RE_URL.search(t):
        return False, "url"
    if _RE_MULTI_EXCLAIM.search(t):
        return False, "multi_exclaim"
    if t.rstrip("。 …").endswith(("？", "?")):
        return False, "ends_with_question"
    return True, ""


def _build_client():
    import tweepy
    bearer = os.getenv("X_BEARER_TOKEN", "")
    if not bearer:
        raise RuntimeError("X_BEARER_TOKEN not set")
    return tweepy.Client(bearer_token=bearer)


async def _collect_viral_candidates() -> list[dict]:
    """X search でバズった認証済4桁台の投稿を集める"""
    import tweepy
    try:
        client = _build_client()
    except Exception as e:
        logger.warning(f"quote_rt client init失敗: {e}")
        return []

    candidates: list[dict] = []
    seen_ids: set[str] = set()

    for query in SEARCH_QUERIES:
        try:
            resp = client.search_recent_tweets(
                query=query,
                max_results=50,
                tweet_fields=["public_metrics", "created_at", "reply_settings", "lang"],
                expansions=["author_id"],
                user_fields=["verified", "verified_type", "public_metrics", "description", "name"],
            )
        except Exception as e:
            logger.warning(f"quote_rt search failed {query!r}: {e}")
            continue

        users_by_id: dict[str, Any] = {}
        if resp.includes and "users" in resp.includes:
            users_by_id = {u.id: u for u in resp.includes["users"]}

        if not resp.data:
            continue

        now_utc = datetime.now(timezone.utc)
        for t in resp.data:
            if str(t.id) in seen_ids:
                continue
            seen_ids.add(str(t.id))

            u = users_by_id.get(t.author_id)
            if not u:
                continue

            # 認証済チェック
            vt = getattr(u, "verified_type", None) or ""
            if not (u.verified and vt in ("blue", "business", "government")):
                continue

            # フォロワー 4 桁チェック
            pm_u = u.public_metrics or {}
            fc = pm_u.get("followers_count", 0)
            if not (MIN_FOLLOWERS <= fc <= MAX_FOLLOWERS):
                continue

            # 所有アカウント除外
            if u.username.lower() in _BLOCKED_AUTHORS_NORM:
                continue

            # ツイート鮮度
            age_h = (now_utc - t.created_at).total_seconds() / 3600 if t.created_at else 999
            if not (MIN_TWEET_AGE_HOURS <= age_h <= MAX_TWEET_AGE_HOURS):
                continue

            # エンゲージメント閾値
            pm_t = t.public_metrics or {}
            likes = pm_t.get("like_count", 0)
            rts = pm_t.get("retweet_count", 0)
            if likes < MIN_LIKES or rts < MIN_RETWEETS:
                continue

            candidates.append({
                "tweet_id": str(t.id),
                "author_id": str(u.id),
                "author_username": u.username,
                "author_name": u.name,
                "author_followers": int(fc),
                "tweet_text": (t.text or "")[:500],
                "like_count": likes,
                "retweet_count": rts,
                "age_hours": round(age_h, 1),
                "reply_settings": getattr(t, "reply_settings", None),
            })

    # エンゲージメント降順
    candidates.sort(key=lambda c: (c["like_count"] + c["retweet_count"] * 3), reverse=True)
    return candidates


async def _count_today_quotes(account: str) -> int:
    """当日の引用 RT 件数 (JST基準)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # trigger_type='quote_rt' + reply_content が空でない = 成功済み
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_type = $1
                     AND status = 'replied'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date""",
                f"quote_rt_{account}",
            )
            return int(row["cnt"]) if row else 0
    except Exception:
        return 9999


async def _already_quoted(tweet_id: str) -> bool:
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM x_reply_log WHERE trigger_tweet_id = $1",
                tweet_id,
            )
            return row is not None
    except Exception:
        return True


async def _record_quote(
    tweet_id: str, author_id: str, author_username: str,
    target_text: str, comment: str, account: str,
) -> bool:
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO x_reply_log
                   (trigger_tweet_id, trigger_author_id, trigger_author_username,
                    trigger_content, trigger_type, reply_content, thread_id, depth, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $1, 0, 'posting')""",
                tweet_id, author_id, author_username, target_text[:500],
                f"quote_rt_{account}", comment[:500],
            )
        return True
    except Exception as e:
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str:
            return False
        logger.warning(f"quote_rt 記録失敗: {e}")
        return False


async def _generate_quote_comment(
    target_text: str, target_author: str, account: str,
    max_attempts: int = 3,
) -> str | None:
    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        return None

    system = _QUOTE_SYSTEM_SHIMAHARA if account == "shimahara" else _QUOTE_SYSTEM_SYUTAIN

    user_prompt = (
        f"# 引用 RT する元の投稿\n"
        f"@{target_author}: {target_text[:400]}\n\n"
        f"# タスク\n"
        f"上記投稿に対する引用 RT の一言コメントを書け。\n"
        f"- 15〜60字\n"
        f"- 敬語基本\n"
        f"- 疑問符で終わらない\n"
        f"- クソリプにならない、礼節を保つ\n"
        f"- コメントテキストのみ"
    )

    sel = choose_best_model_v6(
        task_type="sns_draft",
        quality="medium",
        needs_japanese=True,
    )

    last_reason = ""
    for attempt in range(max_attempts):
        try:
            result = await call_llm(
                prompt=user_prompt,
                system_prompt=system,
                model_selection=sel,
                temperature=0.75,
                use_cache=False,
            )
        except Exception as e:
            logger.warning(f"quote_rt LLM 失敗 (attempt {attempt+1}): {e}")
            return None

        text = (result.get("text") or result.get("content") or "").strip()
        text = re.sub(r'^["「『\s]+|["」』\s]+$', "", text).strip()

        ok, reason = _quality_check(text)
        if ok:
            return text
        last_reason = reason
        logger.debug(f"quote_rt 再生成 ({attempt+1}): {reason} text={text[:40]!r}")

    logger.warning(f"quote_rt 品質 3回失敗 last={last_reason}")
    return None


async def run_quote_rt_cycle(dry_run: bool = False) -> dict:
    """Quote-RT loop の 1 サイクル実行.
    shimahara / syutain_beta 両方で日次上限まで投下する."""
    import asyncio
    from tools.social_tools import execute_approved_x

    stats: dict[str, Any] = {
        "candidates": 0, "quoted": 0, "skipped": 0, "errors": 0,
        "dry_run": dry_run, "previews": [],
    }

    # X Credit Guard: 402 halt 中ならスキップ
    try:
        from tools.x_credit_guard import is_halted
        if await is_halted():
            stats["reason"] = "x_credit_guard_halted"
            return stats
    except Exception:
        pass

    # 時間帯 (9-22 JST 以外は stop)
    now_jst = datetime.now(JST)
    if not dry_run and (now_jst.hour < 9 or now_jst.hour >= 22):
        stats["reason"] = "inactive_hour"
        return stats

    candidates = await _collect_viral_candidates()
    stats["candidates"] = len(candidates)
    if not candidates:
        stats["reason"] = "no_viral_candidates"
        return stats

    # アカウント別の今日の引用数
    shimahara_today = await _count_today_quotes("shimahara")
    syutain_today = await _count_today_quotes("syutain")
    shimahara_remaining = max(0, MAX_QUOTE_PER_DAY_PER_ACCOUNT - shimahara_today)
    syutain_remaining = max(0, MAX_QUOTE_PER_DAY_PER_ACCOUNT - syutain_today)

    if not dry_run and shimahara_remaining == 0 and syutain_remaining == 0:
        stats["reason"] = "daily_cap_both_accounts"
        return stats

    # このサイクル内の作者 dedup
    seen_authors: set[str] = set()

    for cand in candidates:
        if stats["quoted"] >= (shimahara_remaining + syutain_remaining) and not dry_run:
            break
        if len(stats["previews"]) >= (MAX_QUOTE_PER_DAY_PER_ACCOUNT * 2) and dry_run:
            break

        tweet_id = cand["tweet_id"]
        author = cand["author_username"]
        author_lower = author.lower()

        if author_lower in seen_authors:
            stats["skipped"] += 1
            continue
        if await _already_quoted(tweet_id):
            stats["skipped"] += 1
            continue

        # どちらのアカウントで引用するか決定
        # 残り枠があるアカウントからランダム、両方残っていればランダム
        possible_accounts = []
        if shimahara_remaining > 0 or dry_run:
            possible_accounts.append("shimahara")
        if syutain_remaining > 0 or dry_run:
            possible_accounts.append("syutain")
        if not possible_accounts:
            break
        account = random.choice(possible_accounts)

        comment = await _generate_quote_comment(cand["tweet_text"], author, account)
        if not comment:
            stats["skipped"] += 1
            continue

        if dry_run:
            stats["previews"].append({
                "tweet_id": tweet_id,
                "author": author,
                "followers": cand["author_followers"],
                "likes": cand["like_count"],
                "retweets": cand["retweet_count"],
                "age_hours": cand["age_hours"],
                "target": cand["tweet_text"][:150],
                "account": account,
                "comment": comment,
                "comment_length": len(comment),
            })
            seen_authors.add(author_lower)
            continue

        # 本番投稿
        recorded = await _record_quote(
            tweet_id, cand["author_id"], author,
            cand["tweet_text"], comment, account,
        )
        if not recorded:
            stats["skipped"] += 1
            continue

        # 自然な遅延 30秒〜3分
        await asyncio.sleep(random.randint(30, 180))

        try:
            result = await execute_approved_x(
                content=comment,
                account=account,
                quote_tweet_id=tweet_id,
            )
        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"quote_rt 投稿失敗 tweet_id={tweet_id}: {e}")
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
            stats["quoted"] += 1
            seen_authors.add(author_lower)
            if account == "shimahara":
                shimahara_remaining -= 1
            else:
                syutain_remaining -= 1

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

            logger.info(
                f"quote_rt 成功: {account} → @{author} tweet={tweet_id} "
                f"quote={result.get('tweet_id','')}"
            )

            try:
                from tools.discord_notify import notify_discord
                handle_map = {"shimahara": "Sima_daichi", "syutain": "syutain_beta"}
                url = f"https://x.com/{handle_map.get(account, '')}/status/{result.get('tweet_id','')}"
                await notify_discord(
                    f"🔁 Quote-RT 投下 ({account} → @{author}, f={cand['author_followers']:,}, "
                    f"like={cand['like_count']}/rt={cand['retweet_count']})\n"
                    f"対象: {cand['tweet_text'][:80]}\n"
                    f"コメント: {comment}\n{url}"
                )
            except Exception:
                pass
        else:
            stats["errors"] += 1
            err = result.get("reason") or result.get("error") or "unknown"
            logger.warning(f"quote_rt 投稿失敗: {err}")
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
