"""
戦略書KPI監査ツール

戦略書の 2ヶ月後目標 + 数字より重要な呼び名を runtime で
tools/strategy_book_loader から取得して達成率を集計する。

verbatim な目標値・呼び名はこのファイルに含まれない(security refactor 2026-04-11)。
Strategy book が存在しない環境では全 KPI が empty になり degrade する。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tools.strategy_book_loader import (
    get_callout_nicknames,
    get_kpi_targets,
    get_week1_start_date,
    is_available as strategy_book_available,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 基準日・終了日は strategy book の Day 1 日付から計算
# (2ヶ月後 ≒ 61日後)
START_DATE = get_week1_start_date()
END_DATE = START_DATE + timedelta(days=61)

# KPI targets は strategy_book_loader 経由で取得 (lazy load)
_KPI_TARGETS_CACHE: dict | None = None
_NICKNAMES_CACHE: list[str] | None = None


def _get_kpi_targets_cached() -> dict:
    global _KPI_TARGETS_CACHE
    if _KPI_TARGETS_CACHE is None:
        _KPI_TARGETS_CACHE = get_kpi_targets() or {"lower": {}, "upper": {}}
    return _KPI_TARGETS_CACHE


def _get_nicknames_cached() -> list[str]:
    global _NICKNAMES_CACHE
    if _NICKNAMES_CACHE is None:
        _NICKNAMES_CACHE = get_callout_nicknames() or []
    return _NICKNAMES_CACHE


async def _get_x_follower_count() -> int | None:
    """settings から最新の X フォロワー数を取得。集計は別ジョブが行う想定"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'x_follower_current'"
            )
            if row and row["value"]:
                data = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                return int(data.get("count", 0))
    except Exception as e:
        logger.debug(f"x_follower_current 取得失敗: {e}")
    return None


async def _get_x_follower_baseline() -> int:
    """戦略書開始時点のフォロワー数を取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = 'x_follower_baseline_20260408'"
            )
            if row and row["value"]:
                data = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                return int(data.get("count", 0))
    except Exception:
        pass
    return 0


async def _get_third_party_mentions() -> int:
    """第三者言及の推定(intel_items に SYUTAINβ 関連の mention がどれだけあるか)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT count(*) as cnt FROM intel_items
                   WHERE (title ILIKE '%SYUTAINβ%' OR summary ILIKE '%SYUTAINβ%'
                          OR title ILIKE '%syutain%' OR summary ILIKE '%syutain%')
                     AND source IN ('grok_x_research', 'trend_detector', 'overseas_trend')
                     AND created_at > $1""",
                START_DATE,
            )
            return int(row["cnt"]) if row else 0
    except Exception:
        return 0


async def _get_nickname_mentions() -> dict[str, int]:
    """「数字より重要な状態」: 呼び名候補が intel で何件言及されたか"""
    result: dict[str, int] = {}
    nicknames = _get_nicknames_cached()
    if not nicknames:
        return result
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            for nick in nicknames:
                row = await conn.fetchrow(
                    """SELECT count(*) as cnt FROM intel_items
                       WHERE (title ILIKE $1 OR summary ILIKE $1)
                         AND created_at > $2""",
                    f"%{nick}%", START_DATE,
                )
                result[nick] = int(row["cnt"]) if row else 0
    except Exception as e:
        logger.warning(f"nickname mentions 取得失敗: {e}")
    return result


async def _get_note_stats() -> dict:
    """note記事の統計(公開数・品質通過率)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT
                     count(*) FILTER (WHERE status = 'published') as published,
                     count(*) as total,
                     count(*) FILTER (WHERE status IN ('rejected_factual', 'rejected_stage1', 'rejected_stage2', 'rejected_mechanical')) as rejected
                   FROM product_packages
                   WHERE platform = 'note' AND created_at >= $1""",
                START_DATE,
            )
            return dict(row) if row else {}
    except Exception:
        return {}


async def _get_posting_stats() -> dict:
    """SNS投稿の総数・成功率"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT
                     count(*) FILTER (WHERE status = 'posted') as posted,
                     count(*) FILTER (WHERE status = 'rejected') as rejected,
                     count(*) FILTER (WHERE status = 'falsity_blocked') as falsity_blocked,
                     count(*) as total
                   FROM posting_queue
                   WHERE created_at >= $1""",
                START_DATE,
            )
            return dict(row) if row else {}
    except Exception:
        return {}


def _progress_ratio(current: int, target: tuple[int, int] | int) -> float:
    """達成率を返す(0.0-1.0+)"""
    if isinstance(target, tuple):
        lower = target[0]
    else:
        lower = target
    if lower <= 0:
        return 0.0
    return min(2.0, current / lower)


async def run_kpi_audit() -> dict:
    """KPI監査を実行して結果を返す"""
    now = datetime.now(JST).date()
    days_elapsed = (now - START_DATE).days
    days_remaining = (END_DATE - now).days
    progress_ratio_time = max(0.0, min(1.0, days_elapsed / 61))  # 61日=2ヶ月強

    targets = _get_kpi_targets_cached()
    lower_targets = targets.get("lower", {})
    upper_targets = targets.get("upper", {})

    # X フォロワー
    x_current = await _get_x_follower_count()
    x_baseline = await _get_x_follower_baseline()
    x_delta = (x_current - x_baseline) if (x_current is not None and x_baseline) else None

    # 第三者言及
    third_party = await _get_third_party_mentions()

    # 呼び名言及
    nicknames = await _get_nickname_mentions()

    # note 統計
    note_stats = await _get_note_stats()

    # posting 統計
    post_stats = await _get_posting_stats()

    # KPI target が読めない場合は progress=0 を返す
    def _progress(current: int, tgt_key: str, tier: dict) -> float:
        target_val = tier.get(tgt_key)
        if target_val is None:
            return 0.0
        return _progress_ratio(current, target_val)

    result = {
        "audit_date": now.isoformat(),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "time_progress": round(progress_ratio_time, 2),
        "strategy_book_available": strategy_book_available(),
        "x_follower_current": x_current,
        "x_follower_baseline": x_baseline,
        "x_follower_delta": x_delta,
        "x_follower_lower_progress": _progress(x_delta or 0, "x_follower_delta", lower_targets),
        "x_follower_upper_progress": _progress(x_delta or 0, "x_follower_delta", upper_targets),
        "third_party_mentions": third_party,
        "third_party_progress": _progress(third_party, "third_party_mentions", lower_targets),
        "nickname_mentions": nicknames,
        "top_nickname": max(nicknames.items(), key=lambda x: x[1])[0] if nicknames else None,
        "note_published": note_stats.get("published", 0),
        "note_total": note_stats.get("total", 0),
        "note_rejected": note_stats.get("rejected", 0),
        "posting_posted": post_stats.get("posted", 0),
        "posting_rejected": post_stats.get("rejected", 0),
    }

    # Discord 通知
    try:
        from tools.discord_notify import notify_discord
        lines = [
            f"📊 戦略書KPI監査 ({now})",
            f"経過: {days_elapsed}日 / 残り: {days_remaining}日 (時間進捗 {result['time_progress']*100:.0f}%)",
            "",
            "## 戦略書2ヶ月後目標との比較",
        ]
        if x_delta is not None:
            lines.append(
                f"Xフォロワー純増: {x_delta:+d} "
                f"(下限目標 600-1000: {result['x_follower_lower_progress']*100:.0f}%, "
                f"上振れ目標 3000-5000: {result['x_follower_upper_progress']*100:.0f}%)"
            )
        else:
            lines.append("Xフォロワー純増: 未計測(`settings.x_follower_baseline_20260408` 要設定)")
        lines.append(
            f"第三者言及(intel検出): {third_party}件 "
            f"(目標5件 → {result['third_party_progress']*100:.0f}%)"
        )
        if nicknames and result["top_nickname"]:
            top = result["top_nickname"]
            lines.append(f"注目呼び名: 『{top}』 ({nicknames[top]}件)")
        lines.append("")
        lines.append("## 実行量")
        lines.append(
            f"note記事: 公開{result['note_published']}本 / 総{result['note_total']}本 "
            f"(rejected {result['note_rejected']})"
        )
        lines.append(
            f"SNS投稿: posted {result['posting_posted']} / rejected {result['posting_rejected']}"
        )
        await notify_discord("\n".join(lines))
    except Exception as e:
        logger.warning(f"KPI監査 Discord通知失敗: {e}")

    return result
