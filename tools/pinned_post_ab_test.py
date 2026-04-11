"""
固定ポスト A/B テスト自動化

A案/B案 の内容は tools/strategy_book_loader から runtime で取得する。
verbatim テキストはこのファイルには含まれない(security refactor 2026-04-11)。

注意: X API v2 Free tier では tweet の直接 pin API が利用できないため、
本実装は「週次で variant を posting_queue に投下し、engagement を比較する」アプローチ。
Strategy book が存在しない環境では run_weekly_ab_rotation は no-op を返す。

フロー:
1. 毎週月曜 09:10 JST に現行 variant を posting_queue に投下
2. posting_queue_engagement から 2週間分の variant A/B のエンゲージメントを集計
3. 勝ち案を settings に記録し Discord 通知
4. variant を toggle(A↔B) して次週へ
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from tools.strategy_book_loader import (
    get_pinned_post_variants,
    is_available as strategy_book_available,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


async def _get_current_variant() -> dict:
    """settings テーブルから現在の A/B 状態を取得"""
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'pinned_post_ab_state'"
        )
        if row and row["value"]:
            data = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            return data
    # 初期状態
    return {
        "current_variant": "A",
        "week_num": 0,
        "last_rotated_at": None,
        "a_posting_queue_ids": [],
        "b_posting_queue_ids": [],
        "winner": None,
    }


async def _save_state(state: dict) -> None:
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        await conn.execute(
            """INSERT INTO settings (key, value) VALUES ('pinned_post_ab_state', $1)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            json.dumps(state, ensure_ascii=False),
        )


async def _substitute_dynamic_values(content: str) -> str:
    """variant content 内のプレースホルダを実測値で置換する。

    strategy_book_loader が verbatim 数値を {python_lines}/{api_total}/{revenue} 等の
    プレースホルダに既に変換済みなので、ここでは .format_map で置換するだけ。
    """
    try:
        from tools.strategy_plan_executor import _resolve_dynamic_values
        vals = await _resolve_dynamic_values()

        class _SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        return content.format_map(_SafeDict(vals))
    except Exception as e:
        logger.warning(f"pinned_post dynamic 置換失敗: {e}")
    return content


async def _enqueue_variant_post(variant: str, content: str) -> int | None:
    """posting_queue に variant ポストを投下"""
    from tools.db_pool import get_connection
    now_jst = datetime.now(JST)
    scheduled = now_jst.replace(hour=9, minute=30, second=0, microsecond=0)
    if scheduled <= now_jst:
        scheduled = now_jst + timedelta(minutes=5)

    # ラベルとメタは theme_category に埋め込む
    theme_cat = f"pinned_post_{variant.lower()}"

    async with get_connection() as conn:
        pid = await conn.fetchval(
            """INSERT INTO posting_queue
               (platform, account, content, scheduled_at, status, theme_category)
               VALUES ('x', 'shimahara', $1, $2, 'pending', $3)
               RETURNING id""",
            content, scheduled, theme_cat,
        )
    return pid


async def _measure_variant_engagement(queue_ids: list[int]) -> dict:
    """指定の posting_queue_id 群のエンゲージメントを集計"""
    if not queue_ids:
        return {"posts": 0, "likes": 0, "reposts": 0, "replies": 0, "impressions": 0, "score": 0.0}
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """SELECT
                 count(DISTINCT pq.id) AS posts,
                 COALESCE(sum(pqe.likes), 0) AS likes,
                 COALESCE(sum(pqe.reposts), 0) AS reposts,
                 COALESCE(sum(pqe.replies), 0) AS replies,
                 COALESCE(sum(pqe.impressions), 0) AS impressions
               FROM posting_queue pq
               LEFT JOIN posting_queue_engagement pqe ON pqe.posting_queue_id = pq.id
               WHERE pq.id = ANY($1::int[])""",
            queue_ids,
        )
    stats = dict(row) if row else {}
    stats["score"] = (
        int(stats.get("likes", 0)) * 3
        + int(stats.get("reposts", 0)) * 2
        + int(stats.get("replies", 0)) * 5
        + int(stats.get("impressions", 0)) * 0.01
    )
    return stats


async def run_weekly_ab_rotation() -> dict:
    """毎週月曜の A/B ローテーション + 勝敗判定"""
    if not strategy_book_available():
        logger.info("pinned_post AB: strategy book not available. Skipping rotation.")
        return {"skipped": True, "reason": "strategy_book_unavailable"}

    variants = get_pinned_post_variants()
    if not variants or "A" not in variants or "B" not in variants:
        logger.warning(
            f"pinned_post AB: failed to load A/B variants from strategy book "
            f"(got: {list(variants.keys())}). Skipping."
        )
        return {"skipped": True, "reason": "variants_not_parsed"}

    state = await _get_current_variant()
    variant = state.get("current_variant", "A")
    week_num = int(state.get("week_num", 0)) + 1

    # 1. 今週の variant を posting_queue に投下(内容は strategy_book_loader 経由)
    content = variants[variant]
    content = await _substitute_dynamic_values(content)
    queue_id = await _enqueue_variant_post(variant, content)

    key = "a_posting_queue_ids" if variant == "A" else "b_posting_queue_ids"
    state.setdefault(key, [])
    if queue_id:
        state[key].append(queue_id)

    logger.info(
        f"pinned_post AB: week{week_num} variant={variant} "
        f"posting_queue_id={queue_id}"
    )

    # 2. 2週目以降: 勝敗集計
    winner_notice = ""
    if week_num >= 2:
        a_stats = await _measure_variant_engagement(state.get("a_posting_queue_ids", []))
        b_stats = await _measure_variant_engagement(state.get("b_posting_queue_ids", []))
        if a_stats["score"] > b_stats["score"] * 1.2:
            state["winner"] = "A"
        elif b_stats["score"] > a_stats["score"] * 1.2:
            state["winner"] = "B"
        else:
            state["winner"] = "tie"
        winner_notice = (
            f"\n## A/B テスト中間結果\n"
            f"A案 score={a_stats['score']:.1f} "
            f"(likes={a_stats['likes']}, imp={a_stats['impressions']})\n"
            f"B案 score={b_stats['score']:.1f} "
            f"(likes={b_stats['likes']}, imp={b_stats['impressions']})\n"
            f"現時点の勝者: {state['winner']}"
        )

    # 3. Toggle
    state["current_variant"] = "B" if variant == "A" else "A"
    state["week_num"] = week_num
    state["last_rotated_at"] = datetime.now(JST).isoformat()
    await _save_state(state)

    # 4. Discord notification
    try:
        from tools.discord_notify import notify_discord
        await notify_discord(
            f"📌 固定ポストAB: Week {week_num} → 今週{variant}案を投稿\n"
            f"次週は{state['current_variant']}案に切替{winner_notice}"
        )
    except Exception:
        pass

    return {
        "week_num": week_num,
        "posted_variant": variant,
        "next_variant": state["current_variant"],
        "queue_id": queue_id,
        "winner": state.get("winner"),
    }
