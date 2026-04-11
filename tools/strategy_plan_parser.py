"""
戦略書パーサ — runtime で strategy_book_loader 経由で Day 1-7 を parse し、
strategy_plan_items テーブルに登録する。

Security refactor (2026-04-11 案B):
- 戦略書の verbatim テキストはこのファイルに含まれない
- 実際の Day 1-7 content は tools/strategy_book_loader.py が runtime で parse
- strategy_book_loader は strategy/diffusion_execution_plan.md (gitignore) を読む
- book が存在しない環境では sync_strategy_plan は no-op を返し、degrade する
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tools.db_pool import get_connection
from tools.strategy_book_loader import (
    get_day_items,
    get_week1_start_date,
    is_available as strategy_book_available,
)

logger = logging.getLogger(__name__)


def _day_date(day_number: int) -> date:
    """Day 番号から実行日を算出(Day 1 = 戦略書冒頭の日付)"""
    start = get_week1_start_date()
    return start + timedelta(days=day_number - 1)


async def sync_strategy_plan() -> dict[str, int]:
    """戦略書の Day 1-7 を strategy_plan_items に同期する(冪等)"""
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "total": 0}

    if not strategy_book_available():
        logger.info(
            "strategy_plan_parser: strategy book not available (gitignored, missing on this machine). "
            "sync_strategy_plan is no-op."
        )
        return stats

    items = get_day_items()
    stats["total"] = len(items)
    if not items:
        logger.warning("strategy_plan_parser: strategy_book_loader returned 0 items. Parse failed?")
        return stats

    plan_source = "diffusion_execution_plan"

    async with get_connection() as conn:
        for it in items:
            it.setdefault("plan_source", plan_source)
            day_date = _day_date(it["day_number"])
            meta_json = json.dumps(it["metadata"], ensure_ascii=False)
            meta_json_norm = json.dumps(it["metadata"], ensure_ascii=False, sort_keys=True)

            existing = await conn.fetchrow(
                """SELECT id, content, metadata, status, day_date, day_label, title
                   FROM strategy_plan_items
                   WHERE plan_source = $1 AND day_number = $2 AND item_type = $3
                     AND COALESCE(platform, '') = COALESCE($4, '')
                     AND COALESCE(account, '') = COALESCE($5, '')""",
                plan_source, it["day_number"], it["item_type"],
                it.get("platform"), it.get("account"),
            )

            if existing is None:
                await conn.execute(
                    """INSERT INTO strategy_plan_items
                       (plan_source, day_number, day_date, day_label, item_type,
                        platform, account, title, content, metadata, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, 'pending')""",
                    plan_source, it["day_number"], day_date,
                    it["day_label"], it["item_type"],
                    it.get("platform"), it.get("account"),
                    it.get("title"), it["content"], meta_json,
                )
                stats["inserted"] += 1
                logger.info(
                    f"strategy_plan_items insert: Day{it['day_number']} "
                    f"{it['item_type']} ({it.get('platform', '-')}/{it.get('account', '-')})"
                )
            else:
                existing_meta = existing.get("metadata")
                if isinstance(existing_meta, str):
                    try:
                        existing_meta_parsed = json.loads(existing_meta)
                    except Exception:
                        existing_meta_parsed = {}
                else:
                    existing_meta_parsed = existing_meta or {}
                existing_meta_norm = json.dumps(existing_meta_parsed, ensure_ascii=False, sort_keys=True)
                needs_update = (
                    existing["status"] == "pending" and (
                        existing["content"] != it["content"]
                        or existing_meta_norm != meta_json_norm
                        or existing["day_date"] != day_date
                        or existing["day_label"] != it["day_label"]
                        or (existing["title"] or None) != (it.get("title") or None)
                    )
                )
                if needs_update:
                    await conn.execute(
                        """UPDATE strategy_plan_items
                           SET content = $1, metadata = $2::jsonb,
                               day_date = $3, day_label = $4, title = $5,
                               updated_at = NOW()
                           WHERE id = $6""",
                        it["content"], meta_json,
                        day_date, it["day_label"], it.get("title"),
                        existing["id"],
                    )
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

    return stats


async def get_today_items(target_date: date | None = None) -> list[dict]:
    """今日実行すべき strategy_plan_items を取得(status='pending'のみ)"""
    if target_date is None:
        jst = timezone(timedelta(hours=9))
        target_date = datetime.now(jst).date()

    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, day_number, day_label, item_type, platform, account,
                      title, content, metadata, status
               FROM strategy_plan_items
               WHERE day_date = $1 AND status = 'pending'
               ORDER BY day_number, id""",
            target_date,
        )
        return [dict(r) for r in rows]


async def mark_item_executed(
    item_id: int, execution_ref: str, status: str = "executed",
) -> None:
    """実行後のステータス更新"""
    async with get_connection() as conn:
        await conn.execute(
            """UPDATE strategy_plan_items
               SET status = $1, execution_ref = $2, executed_at = NOW(), updated_at = NOW()
               WHERE id = $3""",
            status, execution_ref, item_id,
        )


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(sync_strategy_plan())
    print(f"sync result: {result}")
