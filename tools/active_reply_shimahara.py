"""
能動的リプの完全自動化 (shimahara アカウント) — 2026-04-11 改訂版

## 目的
X 収益分配 (500万imp/90d) と サブスク機能 (認証済フォロワー 2,000) の要件達成。
認証済 4桁台のクリエイターに島原アカウントが能動的に返信し、オーガニック
インプレッションと認証済フォロワーを獲得する。

## 改訂点 (2026-04-11)
従来:
- intel_items (grok_x_research) の X URL を使用 → 大手バイアスで 100% 403 失敗
- プロンプトが甘く、「面白いですね」「僕も〜で」等の AI 定型表現が漏れていた

新版:
- `active_reply_candidates` テーブル (tools/active_reply_candidate_collector.py が収集)
  から候補を取得 — 認証済+4桁台+reply_settings=everyone を構造的に保証
- few-shot に島原さん実返信例を埋め込み
- 敬語標準 (相手との関係性判定はしない)
- 一人称は「僕」のみ、ただし省略を優先
- ハード禁止: 絵文字、多重感嘆符 (!!)、ハッシュタグ、宣伝URL
- 長さ 15〜80 字、超えたら再生成

## ガード
- 同一 tweet_id への二重返信を x_reply_log UNIQUE(trigger_tweet_id) で構造的に防止
- 同一作者への日次1件上限
- 所有アカウント (@Sima_daichi, @syutain_beta) は blocked_authors で除外
- dry_run モード対応 (投稿せず生成結果を返すだけ)
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
MAX_REPLIES_PER_DAY = 5
ACTIVE_HOUR_START = 9
ACTIVE_HOUR_END = 21
MIN_TWEET_AGE_SEC = 30 * 60       # 30分未満の即反応は機械臭いので除外
MAX_TWEET_AGE_SEC = 8 * 3600      # 8時間以内のツイートのみ


def _load_blocked_authors() -> set[str]:
    """除外ハンドル: 自分の所有アカウントには絶対に返信しない。"""
    items: set[str] = set()
    for env_key in (
        "X_SHIMAHARA_USER_ID",
        "X_SHIMAHARA_USERNAME",
        "X_SYUTAIN_USER_ID",
        "X_SYUTAIN_USERNAME",
    ):
        v = os.getenv(env_key, "").strip()
        if v:
            items.add(v.lower().lstrip("@"))
    return items


_BLOCKED_AUTHORS_NORM = _load_blocked_authors()


# 島原さん実返信の few-shot 例 (2026-04-11 X API 取得)
# - 敬語ベース (初対面/公式向け)
# - 長さのレンジ 10〜90字
# - 定型相槌禁止ではなく、使い方の参考例として
_SHIMAHARA_REPLY_EXAMPLES = [
    "すみません、今は僕のアカウントにしかリアクションしない設定にしておりまして…。返信するアカウントは簡単に増やせれる様にしてあるので、興味あればテスターとして追加させて頂きます！",
    "その結果は、多分このアカウントに反映されると思います…。(上手くいけば…)",
    "なるほど、今現状でもMCPサーバー移行して削減できるコードは24000行ぐらいらしいけど、早目に移行を考えておく。",
    "今日の結果は明日には改善させる。明日の結果は明後日には改善させる。この繰り返し…。",
    "もちろん、他人への返信内容も全て目を通すからね。何か問題や改善点があれば、すぐにやる。",
    "構造不信ではないぜ…ただ、AI任せで実装しても、何処かに問題が出てくるのを潰すってだけ",
    "近いうちに超えると思ってる。",
]


_ACTIVE_REPLY_SYSTEM = """あなたは島原大知(@Sima_daichi)本人として、X で初対面の相手の投稿に返信を書く。

## 島原大知のプロフィール
- 非エンジニアの個人事業主。AI を活用した事業 OS を開発中
- 基本は敬語。相手をリスペクトする姿勢
- 煽らない、押し付けない、売り込まない
- ポジティブだが淡々と、自然な温度感

## 返信の書き方
- 敬語基本 (です/ます調)。ただし過剰に堅くない
- 一人称は省略を優先。どうしても必要な時だけ「僕」
- 長さは 15〜80字
- 相手の投稿内容をちゃんと読んで、空気に合わせる
- 定型相槌 (「すごいですね」「気になります」等) を使ってもよいが、その後に必ず自分の視点を1つ足す

## 返信の終わり方 (超重要)
**疑問符 (？) で終わらせない**。初対面の相手に質問を投げるのはクソリプ扱いされる。
次のいずれかで終わらせる:
 (a) 短い感想や同意で閉じる (「〜ですね」「〜だと思います」「〜かもしれません」)
 (b) 相手への肯定/尊重で閉じる (「応援してます」「楽しみにしてます」「素敵な取り組みですね」)
 (c) 自分の観察や補足で閉じる (「〜という視点が新鮮でした」「〜の流れが進みそうですね」)
 (d) トレイルオフ (「…」) で余韻を残す

## 返信の基本姿勢 (最重要)
- **クソリプと思われないことが全て**。相手の発言を尊重し、その内容に合った反応をする
- 相手の投稿を読まずに書いたような一般論は禁止
- 相手の言いたいことに対して、ちゃんと反応していると伝わる内容にする
- 知ったかぶり、上から目線、余計な指摘は絶対に書かない
- 「いいね」だけでは伝えきれない一言を、礼儀正しく添えるイメージ

## ハード禁止事項
- 絵文字は一切使わない
- ハッシュタグ禁止
- URL 禁止
- 多重感嘆符 (「!!」「！！」) 禁止
- 「僕も〜で〜」「私も〜業界で〜」の自己経験押し付け禁止
- 技術用語の list-down (「retopo, UV, LOD」のような並列) 禁止
- 宣伝・自分のプロダクト誘導は書かない
- 相手の投稿をただオウム返しにするのは禁止
- 1つのリプで全部詰め込まない。1つの論点だけ取り上げる

## 出力
返信テキストのみ。前置き・説明・引用符・ラベル等は書かない。"""


# 返信終わり方の指示候補 (毎回ランダムに1つ選ぶ。疑問は原則禁止)
_ENDING_STRATEGIES = [
    ("statement", "語尾は断定や感想 (「〜ですね」「〜だと思います」)。相手をちゃんと肯定する。"),
    ("observation", "語尾は自分の観察や補足 (「〜という視点が新鮮でした」「〜の流れが見えてきそうです」)。上から目線にしない。"),
    ("support", "語尾は肯定・尊重・応援 (「応援してます」「楽しみにしてます」「素敵な取り組みですね」)。"),
    ("trailoff", "語尾は余韻を残す形 (「〜ですね…」「〜かもしれません…」)。"),
]


def _build_active_reply_user_prompt(
    target_text: str, target_author: str, author_description: str,
    ending_strategy: tuple[str, str] | None = None,
) -> str:
    examples_block = "\n".join(
        f"例{i+1}: {ex}"
        for i, ex in enumerate(_SHIMAHARA_REPLY_EXAMPLES)
    )
    if ending_strategy is None:
        ending_strategy = random.choice(_ENDING_STRATEGIES)
    _, ending_instruction = ending_strategy

    return (
        f"# 島原さんの過去の返信例 (文体参考)\n{examples_block}\n\n"
        f"# 返信先の相手\n"
        f"username: @{target_author}\n"
        f"プロフィール: {(author_description or '')[:200]}\n\n"
        f"# 相手の投稿\n{target_text[:400]}\n\n"
        f"# タスク\n"
        f"上記投稿に対して、島原さんの文体で自然な返信を1件書け。\n"
        f"- 15〜80字\n"
        f"- 敬語基本\n"
        f"- 疑問符で終わらせない\n"
        f"- **このリプ固有のルール**: {ending_instruction}\n"
        f"- 返信テキストのみ"
    )


# 品質チェック用 regex
_RE_EMOJI = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\u2600-\u27BF\u2700-\u27BF]"
)
_RE_HASHTAG = re.compile(r"#\S+")
_RE_URL = re.compile(r"https?://\S+")
_RE_MULTI_EXCLAIM = re.compile(r"[!！]{2,}")
_RE_SELF_PUSH = re.compile(r"(僕も|私も)[^。]{0,20}(映像|VTuber|AI)")


def _quality_check(text: str) -> tuple[bool, str]:
    """返信テキストの品質チェック。OK なら (True, ''), NG なら (False, reason)"""
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if len(t) < 15:
        return False, f"too_short ({len(t)})"
    if len(t) > 80:
        return False, f"too_long ({len(t)})"
    if _RE_EMOJI.search(t):
        return False, "emoji"
    if _RE_HASHTAG.search(t):
        return False, "hashtag"
    if _RE_URL.search(t):
        return False, "url"
    if _RE_MULTI_EXCLAIM.search(t):
        return False, "multi_exclaim"
    if _RE_SELF_PUSH.search(t):
        return False, "self_experience_push"
    # 疑問符で終わるのは禁止 (初対面相手への質問はクソリプ扱い)
    if t.rstrip("。 …").endswith(("？", "?")):
        return False, "ends_with_question"
    # 具体性チェック: ほぼ定型だけなら再生成
    generic_only = {
        "すごいですね": "すごいですね" in t,
        "素敵です": "素敵です" in t,
        "面白いですね": "面白いですね" in t,
        "気になります": "気になります" in t,
    }
    matched = [k for k, v in generic_only.items() if v]
    # どの定型相槌も使われていて、かつ文字数が少なすぎる (20字未満) なら NG
    if matched and len(t) < 25:
        return False, f"too_generic ({matched})"
    return True, ""


async def _generate_active_reply(
    target_text: str, target_author: str, author_description: str = "",
    max_attempts: int = 3,
) -> str | None:
    """LLM でリプ生成 + 品質チェック ループ"""
    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        return None

    sel = choose_best_model_v6(
        task_type="sns_draft",
        quality="medium",
        needs_japanese=True,
    )

    last_reason = ""
    for attempt in range(max_attempts):
        user_prompt = _build_active_reply_user_prompt(
            target_text, target_author, author_description, ending_strategy=None,
        )

        try:
            result = await call_llm(
                prompt=user_prompt,
                system_prompt=_ACTIVE_REPLY_SYSTEM,
                model_selection=sel,
                temperature=0.75,
                use_cache=False,
            )
        except Exception as e:
            logger.warning(f"active_reply LLM 失敗 (attempt {attempt+1}): {e}")
            return None

        text = (result.get("text") or result.get("content") or "").strip()
        text = re.sub(r'^["「『\s]+|["」』\s]+$', "", text)
        text = text.strip()

        ok, reason = _quality_check(text)
        if ok:
            return text
        last_reason = reason
        logger.debug(f"active_reply 再生成 (attempt {attempt+1}): reason={reason} text={text[:60]!r}")

    logger.warning(f"active_reply 品質チェック 3回失敗 last={last_reason}")
    return None


# ---------- 候補取得 (active_reply_candidates テーブル) ----------

async def _pick_candidates_from_db(limit: int) -> list[dict]:
    """active_reply_candidates から鮮度チェック済み候補を取得"""
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT tweet_id, author_id, author_username, author_name,
                      author_description, author_verified_type, author_followers_count,
                      tweet_text, tweet_created_at, reply_settings
               FROM active_reply_candidates
               WHERE used = FALSE
                 AND reply_settings = 'everyone'
                 AND tweet_created_at < NOW() - make_interval(secs => $1)
                 AND tweet_created_at > NOW() - make_interval(secs => $2)
                 AND author_followers_count BETWEEN 1000 AND 9999
               ORDER BY RANDOM()
               LIMIT $3""",
            MIN_TWEET_AGE_SEC, MAX_TWEET_AGE_SEC, limit,
        )
    return [dict(r) for r in rows]


async def _mark_candidate_used(tweet_id: str, reason: str = "replied") -> None:
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        await conn.execute(
            """UPDATE active_reply_candidates
               SET used=TRUE, used_at=NOW(), skip_reason=$2
               WHERE tweet_id=$1""",
            tweet_id, reason,
        )


async def _count_today_active_replies() -> int:
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_type = 'active_reply_shimahara'
                     AND status = 'replied'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date"""
            )
            return int(row["cnt"]) if row else 0
    except Exception:
        return 9999


async def _is_already_replied_anywhere(tweet_id: str) -> bool:
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


async def _record_active_reply(
    tweet_id: str, author_id: str, author_handle: str,
    target_text: str, reply_content: str, status: str = "posting",
) -> bool:
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO x_reply_log
                   (trigger_tweet_id, trigger_author_id, trigger_author_username,
                    trigger_content, trigger_type, reply_content, thread_id, depth, status)
                   VALUES ($1, $2, $3, $4, 'active_reply_shimahara', $5, $6, 0, $7)""",
                tweet_id, author_id or "", author_handle, target_text[:500],
                reply_content[:500], tweet_id, status,
            )
        return True
    except Exception as e:
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str:
            return False
        logger.warning(f"active_reply 記録失敗: {e}")
        return False


async def run_active_reply_cycle(dry_run: bool = False) -> dict:
    """能動的リプの 1 サイクル実行。
    dry_run=True の場合は投稿せず候補+返信文のリストを返す。
    """
    from tools.social_tools import execute_approved_x

    stats: dict[str, Any] = {
        "candidates": 0, "replied": 0, "skipped": 0, "errors": 0,
        "reason": "", "dry_run": dry_run, "previews": [],
    }

    # X Credit Guard: 投稿は shimahara project、search は syutain project。
    # shimahara が halt ならそもそもリプ投下不可なので cycle skip。
    # syutain (bearer) が halt でも、既存の active_reply_candidates を使うだけ
    # なら問題ないので cycle は継続する (新規収集は別ジョブで別チェック)。
    try:
        from tools.x_credit_guard import is_halted
        if not dry_run and await is_halted(project="shimahara"):
            stats["reason"] = "x_credit_guard_halted_shimahara"
            return stats
    except Exception:
        pass

    # 1. 時間帯
    now_jst = datetime.now(JST)
    if not dry_run and (now_jst.hour < ACTIVE_HOUR_START or now_jst.hour >= ACTIVE_HOUR_END):
        stats["reason"] = "inactive_hour"
        return stats

    # 2. 日次上限
    if not dry_run:
        today = await _count_today_active_replies()
        if today >= MAX_REPLIES_PER_DAY:
            stats["reason"] = f"daily_cap ({today}/{MAX_REPLIES_PER_DAY})"
            return stats
        remaining = MAX_REPLIES_PER_DAY - today
    else:
        remaining = 5

    # 3. 候補
    candidates = await _pick_candidates_from_db(limit=remaining * 4)
    stats["candidates"] = len(candidates)
    if not candidates:
        stats["reason"] = "no_fresh_candidates"
        return stats

    # 4. フィルタ (blocked + 同一日内作者)
    same_author_today: set[str] = set()
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT lower(trigger_author_username) as u
                   FROM x_reply_log
                   WHERE trigger_type='active_reply_shimahara'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date"""
            )
            same_author_today = {r["u"] for r in rows if r["u"]}
    except Exception:
        pass

    for cand in candidates:
        if stats["replied"] >= remaining:
            break
        if len(stats["previews"]) >= remaining and dry_run:
            break

        author_handle = cand["author_username"]
        tweet_id = cand["tweet_id"]

        if author_handle.lower() in _BLOCKED_AUTHORS_NORM:
            stats["skipped"] += 1
            continue
        if author_handle.lower() in same_author_today:
            stats["skipped"] += 1
            continue

        # dedup layer: x_reply_log
        if await _is_already_replied_anywhere(tweet_id):
            stats["skipped"] += 1
            continue

        target_text = cand["tweet_text"] or ""
        target_author = cand["author_username"]
        author_description = cand.get("author_description", "") or ""

        reply_text = await _generate_active_reply(
            target_text, target_author, author_description,
        )
        if not reply_text:
            stats["skipped"] += 1
            continue

        if dry_run:
            stats["previews"].append({
                "tweet_id": tweet_id,
                "author_username": target_author,
                "author_followers": cand["author_followers_count"],
                "target_text": target_text[:200],
                "reply_text": reply_text,
                "reply_length": len(reply_text),
            })
            same_author_today.add(target_author.lower())
            continue

        # 本番投稿モード
        recorded = await _record_active_reply(
            tweet_id, cand.get("author_id", ""), target_author,
            target_text, reply_text, status="posting",
        )
        if not recorded:
            stats["skipped"] += 1
            continue

        try:
            # 自然な遅延 (30秒〜4分のランダム)
            delay = random.randint(30, 240)
            logger.debug(f"active_reply: {delay}秒 待機してから投稿")
            import asyncio
            await asyncio.sleep(delay)

            result = await execute_approved_x(
                content=reply_text,
                account="shimahara",
                in_reply_to_tweet_id=tweet_id,
            )
        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"active_reply 投稿失敗 tweet_id={tweet_id}: {e}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(e)[:500], tweet_id,
                    )
            except Exception:
                pass
            await _mark_candidate_used(tweet_id, reason="post_exception")
            continue

        if result.get("success"):
            stats["replied"] += 1
            same_author_today.add(target_author.lower())
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
            await _mark_candidate_used(tweet_id, reason="replied")
            logger.info(
                f"active_reply 成功: @{target_author} → tweet_id={tweet_id} "
                f"reply_id={result.get('tweet_id', '')}"
            )
            try:
                from tools.discord_notify import notify_discord
                url = f"https://x.com/Sima_daichi/status/{result.get('tweet_id', '')}"
                await notify_discord(
                    f"💬 能動的リプ投下 (@{target_author}, f={cand['author_followers_count']:,})\n"
                    f"相手: {target_text[:80]}\n"
                    f"島原: {reply_text}\n{url}"
                )
            except Exception:
                pass
        else:
            stats["errors"] += 1
            err = result.get("reason") or result.get("error") or "unknown"
            logger.warning(f"active_reply 投稿失敗: {err}")
            try:
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(err)[:500], tweet_id,
                    )
            except Exception:
                pass
            await _mark_candidate_used(tweet_id, reason=f"post_failed:{str(err)[:50]}")

    return stats
