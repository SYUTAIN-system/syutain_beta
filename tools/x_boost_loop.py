"""
X 2026アルゴリズム: First-30-minute Boost Loop

リサーチ結果(2026-04-11 WebSearch):
- **最初の30分が最強ランキング要因**。test users 100-1000 に露出、engagement >5% でブースト
- 会話チェーン(reply + author reply) = いいねの 150 倍の重み
- replies は単独投稿の 30 倍 reach

実装: 直近 20 分以内に posted された shimahara/syutain/syutain_beta の X 投稿に対して、
もう一方のアカウント(syutain→shimahara / shimahara→syutain)から自動 reply を生成・投下し、
30 分以内の conversation chain を人工的に発火させる。

dedup 保証:
- x_reply_log の UNIQUE(trigger_tweet_id) で同一 tweet への二重返信を構造的防止
- 既存の sakata proactive / shimahara proactive と同じ fake_trigger パターンを使用
- trigger_type='boost_30min' で区別

安全策:
- 日次上限 5 件/アカウント組
- 20 分以内にposted されたもののみ対象
- [SYUTAINβ auto-generated] ラベル付きshimahara投稿は対象(戦略書Day実行分も含む)
- boost reply 後にはさらに boost しない(チェーン連鎖で spam 化を防ぐ)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 設定
BOOST_WINDOW_MINUTES = 20     # 直近何分以内のposted投稿を対象にするか
MAX_BOOST_PER_DAY = 6         # 1日あたり最大boost reply数
SKIP_IF_ALREADY_REPLIED = True  # 既に誰かに返信されているtweetはスキップ


async def _get_posted_last_20min() -> list[dict]:
    """直近20分以内にposted された shimahara/syutain/syutain_beta の X 投稿を取得"""
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, platform, account, content, post_url, posted_at
               FROM posting_queue
               WHERE platform = 'x'
                 AND account IN ('shimahara', 'syutain', 'syutain_beta')
                 AND status = 'posted'
                 AND posted_at > NOW() - make_interval(mins => $1)
               ORDER BY posted_at DESC""",
            BOOST_WINDOW_MINUTES,
        )
    return [dict(r) for r in rows]


def _extract_tweet_id_from_url(url: str | None) -> str | None:
    """post_url から tweet_id を抽出"""
    if not url:
        return None
    import re
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


async def _count_today_boost_replies() -> int:
    """当日の boost reply 成功件数(JST基準).

    2026-04-11 修正: 以前は status を問わずカウントしていたため、失敗した
    attempt も cap に計上されて、6 件連続失敗で以降全サイクルが daily_cap
    でスキップされていた。成功分 (status='replied') のみをカウントする。
    """
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM x_reply_log
                   WHERE trigger_type = 'boost_30min'
                     AND status = 'replied'
                     AND (created_at AT TIME ZONE 'Asia/Tokyo')::date
                         = (NOW() AT TIME ZONE 'Asia/Tokyo')::date"""
            )
            return int(row["cnt"]) if row else 0
    except Exception as e:
        logger.warning(f"boost count失敗: {e}")
        return 9999


async def _is_already_boosted(tweet_id: str) -> bool:
    """既にx_reply_logに記録があるか"""
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


_BOOST_SYSTEM = {
    # shimahara が syutain_beta の投稿に返信する場合
    "shimahara_to_syutain": (
        "あなたは島原大知(@Sima_daichi)本人。"
        "SYUTAINβ(自分が作ったAI事業OS)がXに投稿した内容に対して、"
        "設計者として短くツッコミ/承認/呆れを入れる。\n\n"
        "ルール:\n"
        "- 1-2行。60字以内\n"
        "- 敬語なし、完全にタメ口\n"
        "- 「それ本気で言ってるの」「データで殴ってくる」「認めざるを得ない」系\n"
        "- 定型的な「いいね」「素晴らしい」禁止\n"
        "- 感想ではなく、ツッコミ/承認/呆れのいずれか\n"
        "- 絵文字・ハッシュタグ禁止\n"
        "返信テキストのみ出力。"
    ),
    # syutain_beta が shimahara の投稿に返信する場合
    "syutain_to_shimahara": (
        "あなたは SYUTAINβ(@syutain_beta)、島原大知が作った自律型AI事業OS。"
        "設計者の島原大知が X に投稿した内容に対して、横から観測報告/補足データ/妙な解釈で返信する。\n\n"
        "ルール:\n"
        "- 1-2行。60字以内\n"
        "- 冷静なトーン(感情を乗せない、本気で言ってる)\n"
        "- 具体的な数字・観察・データで殴る(ただし捏造禁止、実測値のみ)\n"
        "- 「persona_memoryの分析によると」「直近7日のデータでは」等\n"
        "- 絵文字・ハッシュタグ禁止\n"
        "- 敬語は使わない(機械的・事務的に)\n"
        "返信テキストのみ出力。"
    ),
}


async def _generate_boost_reply(
    origin_content: str, direction: str, recent_materials: list[str] | None = None,
) -> str | None:
    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        return None

    system = _BOOST_SYSTEM.get(direction)
    if not system:
        return None

    materials_text = ""
    if recent_materials:
        materials_text = "\n\n## 使える実ネタ(optional)\n" + "\n".join(
            f"- {m[:120]}" for m in recent_materials[:3]
        )

    user_prompt = (
        f"# 元の投稿\n{origin_content[:280]}\n{materials_text}\n\n"
        f"# タスク\n上記投稿に対して、上記ルールに従って 1-2 行の短い boost 返信を生成せよ。"
    )

    sel = choose_best_model_v6(
        task_type="sns_draft", quality="medium", needs_japanese=True,
    )
    try:
        result = await call_llm(
            prompt=user_prompt, system_prompt=system, model_selection=sel,
            temperature=0.95, use_cache=False,
        )
    except Exception as e:
        logger.warning(f"boost reply LLM失敗: {e}")
        return None

    text = (result.get("text") or result.get("content") or "").strip()
    # ノイズ除去
    import re
    text = re.sub(r"#\S+", "", text).strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    if len(text) < 5:
        return None
    if len(text) > 120:
        text = text[:110] + "…"
    return text


async def run_boost_cycle() -> dict:
    """直近20分のposted投稿に対して boost 返信を実行"""
    from brain_alpha.x_reply_generator import _get_persona_facts
    from tools.social_tools import execute_approved_x
    from tools.db_pool import get_connection

    stats = {"candidates": 0, "boosted": 0, "skipped": 0, "reason": ""}

    # X Credit Guard: 402 halt 中ならスキップ
    try:
        from tools.x_credit_guard import is_halted
        if await is_halted():
            stats["reason"] = "x_credit_guard_halted"
            return stats
    except Exception:
        pass

    # 日次上限
    today = await _count_today_boost_replies()
    if today >= MAX_BOOST_PER_DAY:
        stats["reason"] = f"daily_cap ({today}/{MAX_BOOST_PER_DAY})"
        return stats

    posts = await _get_posted_last_20min()
    stats["candidates"] = len(posts)
    if not posts:
        return stats

    # 実ネタ(persona_facts)を先に一度だけ取得
    try:
        facts = await _get_persona_facts(scope="daichi")
    except Exception:
        facts = []

    for post in posts:
        tweet_id = _extract_tweet_id_from_url(post.get("post_url"))
        if not tweet_id:
            continue
        if await _is_already_boosted(tweet_id):
            stats["skipped"] += 1
            continue

        account = post.get("account") or ""
        content = post.get("content") or ""
        if not content:
            continue

        # 方向決定: shimahara posted → syutain_beta が reply / syutain_beta posted → shimahara が reply
        if account == "shimahara":
            direction = "syutain_to_shimahara"
            reply_account = "syutain"  # execute_approved_x の account名
            reply_username = "syutain_beta"
            trigger_author_username = "Sima_daichi"
        elif account in ("syutain", "syutain_beta"):
            direction = "shimahara_to_syutain"
            reply_account = "shimahara"
            reply_username = "Sima_daichi"
            trigger_author_username = "syutain_beta"
        else:
            continue

        # LLM 返信生成
        reply_text = await _generate_boost_reply(content, direction, facts)
        if not reply_text:
            continue

        # 記録(UNIQUE で dedup)
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO x_reply_log
                       (trigger_tweet_id, trigger_author_id, trigger_author_username,
                        trigger_content, trigger_type, reply_content, thread_id, depth, status)
                       VALUES ($1, '', $2, $3, 'boost_30min', $4, $1, 0, 'posting')""",
                    tweet_id, trigger_author_username, content[:500], reply_text[:500],
                )
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                stats["skipped"] += 1
                continue
            logger.warning(f"boost 記録失敗 tweet_id={tweet_id}: {e}")
            continue

        # 投稿
        try:
            result = await execute_approved_x(
                content=reply_text,
                account=reply_account,
                in_reply_to_tweet_id=tweet_id,
            )
        except Exception as e:
            logger.error(f"boost 投稿失敗 tweet_id={tweet_id}: {e}")
            try:
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
                async with get_connection() as conn:
                    await conn.execute(
                        """UPDATE x_reply_log SET status='replied', reply_tweet_id=$1, replied_at=NOW()
                           WHERE trigger_tweet_id=$2""",
                        result.get("tweet_id", ""), tweet_id,
                    )
            except Exception:
                pass
            stats["boosted"] += 1
            logger.info(
                f"X boost 成功: {account} → {reply_account} tweet_id={tweet_id} "
                f"reply={result.get('tweet_id', '')}"
            )
            try:
                from tools.discord_notify import notify_discord
                url = f"https://x.com/{reply_username}/status/{result.get('tweet_id', '')}"
                await notify_discord(
                    f"🚀 X boost 30min: {reply_username} → {account}\n"
                    f"元: {content[:70]}\n"
                    f"boost: {reply_text[:70]}\n{url}"
                )
            except Exception:
                pass

            # 日次上限に達したら break
            if today + stats["boosted"] >= MAX_BOOST_PER_DAY:
                stats["reason"] = "daily_cap_reached"
                break
        else:
            # execute_approved_x は {"success": False, "reason": ...} を返す
            err = result.get("reason") or result.get("error") or "unknown"
            logger.warning(f"boost 投稿失敗: {err}")
            try:
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE x_reply_log SET status='failed', error_message=$1 WHERE trigger_tweet_id=$2",
                        str(err)[:500], tweet_id,
                    )
            except Exception:
                pass

    return stats
