"""
能動的リプの完全自動化 (shimahara アカウント)

島原さん方針「完全自動実行優先」に基づき、shimahara アカウントから
AI/映像/VTuber 関連の他者投稿へ能動的にリプライを自動投下する。

方針:
- intel_items の grok_x_research から X URL を抽出して返信候補とする
- 日次上限、時間帯制限、ツイート鮮度の ガードを設定
- 品質ルール(情報付与 / 経験ベース / 定型相槌禁止 / 自己宣伝禁止)をプロンプトに明記
- 既存の x_reply_log UNIQUE(trigger_tweet_id) で同一ポストへの二重返信を構造的に防止
- 自分のアカウント (@Sima_daichi, @syutain_beta) への返信は除外
"""
from __future__ import annotations

import logging
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
MAX_TWEET_AGE_SEC = 12 * 3600  # 12時間以内のツイートのみ


def _load_blocked_authors() -> set[str]:
    """除外ハンドル: 自分の所有アカウントには絶対に返信しない。
    env 変数から user_id / username を読み込んで construct する。
    """
    import os
    items: set[str] = set()
    for env_key in (
        "X_SHIMAHARA_USER_ID",      # 設計者(所有者) user_id
        "X_SHIMAHARA_USERNAME",     # 設計者 username (例: Sima_daichi)
        "X_SYUTAIN_USER_ID",        # SYUTAINβ アカウント user_id
        "X_SYUTAIN_USERNAME",       # SYUTAINβ アカウント username (例: syutain_beta)
    ):
        v = os.getenv(env_key, "").strip()
        if v:
            items.add(v)
    return items


_BLOCKED_AUTHORS = _load_blocked_authors()
_BLOCKED_AUTHORS_NORM = {h.lower().lstrip("@") for h in _BLOCKED_AUTHORS}

# 関心トピック(keyword マッチ)
_TOPIC_KEYWORDS = [
    "AI", "LLM", "ChatGPT", "Claude", "Gemini", "エージェント", "生成AI",
    "映像", "動画", "制作", "撮影", "VTuber", "AITuber", "AI映像",
    "自動化", "個人開発", "SaaS", "ノーコード", "Build in Public",
    "Dify", "n8n", "Anthropic", "OpenAI",
]

# tweet URL からIDを抽出
_TWEET_URL_RE = re.compile(r"https?://(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)")


_ACTIVE_REPLY_SYSTEM = """あなたはSYUTAINβの能動的リプライ生成官。
島原大知(@Sima_daichi)アカウントから、他者の投稿へ質の高いリプライを生成する。

## 島原大知の立場
- 映像制作15年、VTuber業界8年。SYUTAINβ(自律型AI事業OS)を個人開発中
- 非エンジニア視点でAI活用を発信
- 4台PCで24時間動く事業OSを構築

## リプの品質基準
1. 相手の投稿に情報を付与する。何も足さないリプは禁止
2. 自分の経験(映像制作/VTuber/AI運用)を踏まえた実質的なコメント
3. 定型相槌(「いいですね」「わかる」「すごい」等)のみは絶対禁止
4. 自己宣伝が主目的のリプは禁止(SYUTAINβの宣伝を冒頭に入れるな)
5. 80字以内(最大120字)
6. 敬語と軽いタメ口を混ぜる。硬すぎない

## トーン
- 冷静だが好奇心がある
- 一歩踏み込んだ質問 or 具体体験の1行共有
- ポエム調禁止、情景描写禁止

## 出力
返信テキストのみ。前置き・説明・ハッシュタグ禁止。"""


def _build_active_reply_user_prompt(target_text: str, target_author: str) -> str:
    return (
        f"# 返信相手の投稿(@{target_author})\n"
        f"{target_text[:300]}\n\n"
        f"# タスク\n"
        f"上記投稿に対して、上記ルールに従って質の高いリプを1件生成せよ。\n"
        f"- 定型相槌は禁止\n"
        f"- 情報を足すか、経験を1行足すか、具体的な問いを投げる\n"
        f"- 80字以内\n"
        f"- 返信テキストのみ出力"
    )


async def _get_candidate_tweets(limit: int = 30) -> list[dict]:
    """intel_items から返信候補となる X ポストを取得"""
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, title, summary, keyword, url, importance_score, created_at
               FROM intel_items
               WHERE source = 'grok_x_research'
                 AND url ~ 'https?://(twitter\\.com|x\\.com)/[^/]+/status/[0-9]+'
                 AND created_at > NOW() - make_interval(hours => 12)
               ORDER BY importance_score DESC, created_at DESC
               LIMIT $1""",
            limit,
        )
    return [dict(r) for r in rows]


def _parse_tweet_url(url: str) -> tuple[str, str] | None:
    m = _TWEET_URL_RE.search(url or "")
    if not m:
        return None
    return m.group(1), m.group(2)  # (author_handle, tweet_id)


def _matches_topic(item: dict) -> bool:
    """AI/映像/VTuber 関連のトピックか判定"""
    haystack = f"{item.get('title', '')} {item.get('summary', '')} {item.get('keyword', '')}"
    hl = haystack.lower()
    for kw in _TOPIC_KEYWORDS:
        if kw.lower() in hl:
            return True
    return False


async def _is_already_replied_anywhere(tweet_id: str) -> bool:
    """x_reply_log に同じ trigger_tweet_id があるかチェック"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM x_reply_log WHERE trigger_tweet_id = $1",
                tweet_id,
            )
            return row is not None
    except Exception:
        return True  # 安全側: エラー時はスキップ


async def _count_today_active_replies() -> int:
    """当日の能動的リプ件数(JST基準)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_type = 'active_reply_shimahara'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date"""
            )
            return int(row["cnt"]) if row else 0
    except Exception:
        return 9999


async def _record_active_reply(
    tweet_id: str,
    author_handle: str,
    target_text: str,
    reply_content: str,
    status: str = "posting",
) -> bool:
    """能動的リプをx_reply_logに記録(UNIQUE制約で重複防止)"""
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO x_reply_log
                   (trigger_tweet_id, trigger_author_id, trigger_author_username,
                    trigger_content, trigger_type, reply_content, thread_id, depth, status)
                   VALUES ($1, $2, $3, $4, 'active_reply_shimahara', $5, $6, 0, $7)""",
                tweet_id, "", author_handle, target_text[:500],
                reply_content[:500], tweet_id, status,
            )
        return True
    except Exception as e:
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str:
            return False
        logger.warning(f"active_reply 記録失敗: {e}")
        return False


async def _generate_active_reply(target_text: str, target_author: str) -> str | None:
    """LLMでリプ生成"""
    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        return None

    sel = choose_best_model_v6(
        task_type="sns_draft",
        quality="medium",
        needs_japanese=True,
    )
    try:
        result = await call_llm(
            prompt=_build_active_reply_user_prompt(target_text, target_author),
            system_prompt=_ACTIVE_REPLY_SYSTEM,
            model_selection=sel,
            temperature=0.85,
            use_cache=False,
        )
        text = (result.get("text") or result.get("content") or "").strip()
        # ハッシュタグ除去
        text = re.sub(r"#\S+", "", text).strip()
        # 過剰な絵文字除去はしない(人間味のため残す)
        # 「いいですね」だけの定型は rejection
        if len(text) < 10:
            return None
        if text.lower() in ("いいですね", "すごい", "わかる", "素敵"):
            return None
        # 150字を超える場合は切り詰め
        if len(text) > 150:
            text = text[:140] + "…"
        return text
    except Exception as e:
        logger.warning(f"active_reply LLM失敗: {e}")
        return None


async def run_active_reply_cycle() -> dict:
    """能動的リプの1サイクル実行"""
    from tools.social_tools import execute_approved_x

    stats = {"candidates": 0, "replied": 0, "skipped": 0, "errors": 0, "reason": ""}

    # 1. 時間帯チェック
    now_jst = datetime.now(JST)
    if now_jst.hour < ACTIVE_HOUR_START or now_jst.hour >= ACTIVE_HOUR_END:
        stats["reason"] = "inactive_hour"
        return stats

    # 2. 日次上限
    today = await _count_today_active_replies()
    if today >= MAX_REPLIES_PER_DAY:
        stats["reason"] = f"daily_cap ({today}/{MAX_REPLIES_PER_DAY})"
        return stats
    remaining = MAX_REPLIES_PER_DAY - today

    # 3. 候補取得
    raw_candidates = await _get_candidate_tweets(limit=30)
    stats["candidates"] = len(raw_candidates)

    # 4. フィルタリング
    candidates: list[dict] = []
    for item in raw_candidates:
        parsed = _parse_tweet_url(item.get("url") or "")
        if not parsed:
            continue
        author_handle, tweet_id = parsed
        # 自分のアカウントは除外
        if author_handle.lower().lstrip("@") in _BLOCKED_AUTHORS_NORM:
            continue
        # トピックマッチ
        if not _matches_topic(item):
            continue
        candidates.append({
            **item,
            "author_handle": author_handle,
            "tweet_id": tweet_id,
        })

    if not candidates:
        stats["reason"] = "no_matching_candidates"
        return stats

    # 5. シャッフルしてランダム順に評価
    random.shuffle(candidates)

    for cand in candidates:
        if stats["replied"] >= remaining:
            break

        tweet_id = cand["tweet_id"]
        author_handle = cand["author_handle"]
        title = cand.get("title", "") or ""
        summary = cand.get("summary", "") or ""
        # intel_items の summary は grok が要約したもの。ツイート本文はそのままでは無いが近似として使える
        target_text = f"{title}: {summary}"[:300]

        # Layer 2 dedup: 既に返信済みスキップ
        if await _is_already_replied_anywhere(tweet_id):
            stats["skipped"] += 1
            continue

        # 返信生成
        reply_text = await _generate_active_reply(target_text, author_handle)
        if not reply_text:
            stats["skipped"] += 1
            continue

        # Layer 3 dedup: INSERT(UNIQUE制約)
        recorded = await _record_active_reply(
            tweet_id, author_handle, target_text, reply_text, status="posting",
        )
        if not recorded:
            # UNIQUE違反 or エラー
            stats["skipped"] += 1
            continue

        # X投稿
        try:
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
            continue

        if result.get("success"):
            stats["replied"] += 1
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
                f"active_reply 成功: @{author_handle} → tweet_id={tweet_id} "
                f"reply_id={result.get('tweet_id', '')}"
            )
            try:
                from tools.discord_notify import notify_discord
                url = f"https://x.com/Sima_daichi/status/{result.get('tweet_id', '')}"
                await notify_discord(
                    f"💬 能動的リプ投下 (@{author_handle})\n"
                    f"相手: {target_text[:80]}\n"
                    f"島原: {reply_text[:80]}\n{url}"
                )
            except Exception:
                pass
        else:
            stats["errors"] += 1
            err = result.get("error", "unknown")
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
