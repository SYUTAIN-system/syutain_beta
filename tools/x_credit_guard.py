"""X API Credit Guard — 402 Payment Required を検出したら X 系ジョブを自動停止

2026-04-11 実装。背景:
- X API が PAYG (pay-as-you-go) モデルに変わり、read/write ともに credits を
  消費。credits 切れで 402 Payment Required が返る
- credits 切れで X ジョブが延々と 402 を叩き続けると無駄 (さらに status_code
  402 自体を追加消費する可能性もあり)
- 本ガードで一元的に halt させ、Discord に1回だけ警告 → 管理者判断後に解除

設計:
- flag は PostgreSQL `system_state` テーブルで永続化 (scheduler 再起動後も残る)
- 402 検出時に `register_402()` を呼ぶ → flag 立つ
- X 系ジョブ (active_reply / boost / quote_rt / collector) は実行前に
  `is_halted()` をチェックし、True なら silent skip
- 解除は (a) 時間経過 (デフォルト 12h) (b) 手動 (reset_halt())
- Discord 通知は 1 度だけ (cooldown 30分)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# デフォルト halt 期間 (時間)
DEFAULT_HALT_HOURS = 12

# Discord 通知のクールダウン (秒) — 複数のジョブから同時 register されても 1 回だけ
_NOTIFY_COOLDOWN_SEC = 1800


async def _ensure_table() -> None:
    """system_state テーブルがなければ作る (idempotent)"""
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
    except Exception as e:
        logger.warning(f"system_state テーブル作成失敗: {e}")


async def register_402(endpoint_hint: str = "") -> None:
    """X API が 402 を返した時に呼ぶ。halt フラグを立てる"""
    from tools.db_pool import get_connection
    await _ensure_table()
    now = datetime.now(timezone.utc)
    halt_until = now + timedelta(hours=DEFAULT_HALT_HOURS)
    payload = {
        "halted": True,
        "since": now.isoformat(),
        "halt_until": halt_until.isoformat(),
        "last_endpoint": endpoint_hint[:200],
        "notify_sent_at": None,
    }

    # 既存レコードがあれば notify_sent_at を保持
    existing_notify = None
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM system_state WHERE key='x_credit_guard'"
            )
            if row and row["value"]:
                try:
                    old = row["value"] if isinstance(row["value"], dict) else json.loads(row["value"])
                    existing_notify = old.get("notify_sent_at")
                except Exception:
                    pass
            if existing_notify:
                payload["notify_sent_at"] = existing_notify

            await conn.execute(
                """INSERT INTO system_state (key, value, updated_at)
                   VALUES ('x_credit_guard', $1::jsonb, NOW())
                   ON CONFLICT (key) DO UPDATE
                   SET value=$1::jsonb, updated_at=NOW()""",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
    except Exception as e:
        logger.warning(f"register_402 failed: {e}")
        return

    logger.critical(
        f"x_credit_guard: 402 Payment Required 検出 → X 系ジョブを "
        f"{DEFAULT_HALT_HOURS}h halt (until {halt_until.astimezone(JST).isoformat()})"
    )

    # Discord 通知 (クールダウン内なら skip)
    need_notify = True
    if existing_notify:
        try:
            prev = datetime.fromisoformat(existing_notify)
            if (now - prev).total_seconds() < _NOTIFY_COOLDOWN_SEC:
                need_notify = False
        except Exception:
            pass

    if need_notify:
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(
                f"🛑 **X API Credit 切れ — 全 X 系ジョブを halt**\n"
                f"error: 402 Payment Required\n"
                f"endpoint: {endpoint_hint[:150] or '(未指定)'}\n"
                f"halt until: {halt_until.astimezone(JST).strftime('%m/%d %H:%M JST')}\n"
                f"解除: credit 追加後、tools/x_credit_guard.reset_halt() を実行"
            )
            # notify_sent_at を更新
            payload["notify_sent_at"] = now.isoformat()
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE system_state SET value=$1::jsonb, updated_at=NOW() WHERE key='x_credit_guard'",
                    json.dumps(payload, ensure_ascii=False, default=str),
                )
        except Exception as e:
            logger.warning(f"credit_guard Discord notify failed: {e}")


async def is_halted() -> bool:
    """X 系ジョブが実行前に呼ぶ。halt 中なら True、経過時間超えたら自動解除。"""
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM system_state WHERE key='x_credit_guard'"
            )
        if not row or not row["value"]:
            return False

        val = row["value"] if isinstance(row["value"], dict) else json.loads(row["value"])
        if not val.get("halted"):
            return False

        halt_until = val.get("halt_until")
        if halt_until:
            try:
                until_dt = datetime.fromisoformat(halt_until)
                if datetime.now(timezone.utc) >= until_dt:
                    # タイムアウトで自動解除
                    await reset_halt(reason="auto_timeout")
                    return False
            except Exception:
                pass

        return True
    except Exception as e:
        logger.warning(f"is_halted check failed: {e}")
        return False  # DB 不通時は fail-open (ジョブを通す)


async def reset_halt(reason: str = "manual") -> None:
    """halt フラグを解除。credit がリチャージされた後に手動で呼ぶか、
    タイムアウトで自動呼び出し。"""
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            await conn.execute(
                """UPDATE system_state SET value=jsonb_set(
                     COALESCE(value, '{}'::jsonb), '{halted}', 'false'::jsonb
                   ), updated_at=NOW()
                   WHERE key='x_credit_guard'"""
            )
        logger.info(f"x_credit_guard: halt 解除 (reason={reason})")
        if reason == "manual":
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"✅ X API Credit Guard 解除 (reason={reason})\n"
                    f"X 系ジョブを再開しました"
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"reset_halt failed: {e}")


def is_402_error(error_obj: Exception | str) -> bool:
    """エラーから 402 Payment Required を検出する"""
    s = str(error_obj).lower()
    return (
        "402" in s and "payment required" in s
    ) or "does not have any credits" in s


async def guard_check(job_name: str = "") -> bool:
    """X 系ジョブが実行前に呼ぶラッパ。halt 中なら False、実行 OK なら True"""
    if await is_halted():
        logger.debug(f"{job_name}: x_credit_guard により skip")
        return False
    return True
