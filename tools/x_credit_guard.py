"""X API Credit Guard — 402 Payment Required を検出したら X 系ジョブを自動停止

2026-04-11 実装、同日 project 別に拡張。背景:
- X API が PAYG (pay-as-you-go) モデルに変わり、read/write ともに credits を消費
- credits 切れで 402 Payment Required が返る
- SYUTAINβ は shimahara 用 / syutain 用に **別々の X Developer Project** を使って
  おり、projects は独立した credit プールを持つ
- 一方の project だけ credit 切れになっても、他方は稼働可能 → halt は project
  単位で管理する必要がある

設計:
- project key: "shimahara" / "syutain" / "bearer" (bearer token は通常 syutain 側)
- flag は PostgreSQL `system_state` テーブルで key=f"x_credit_guard:{project}"
- 402 検出時に `register_402(project=...)` を呼ぶ → その project のみ halt
- ジョブは実行前に `is_halted(project=...)` をチェックして silent skip
- 解除は (a) 時間経過 (デフォルト 12h) (b) 手動 (reset_halt(project=...))
- Discord 通知は project 単位で 1 度だけ (cooldown 30分)
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


def _normalize_project(project: str) -> str:
    """project キーを正規化する。shimahara / syutain / bearer のいずれか。"""
    p = (project or "").lower().strip()
    if p in ("shimahara", "sima_daichi", "daichi"):
        return "shimahara"
    if p in ("syutain", "syutain_beta", "bearer"):
        return "syutain"
    return p or "syutain"


def _state_key(project: str) -> str:
    return f"x_credit_guard:{_normalize_project(project)}"


async def register_402(endpoint_hint: str = "", project: str = "syutain") -> None:
    """X API が 402 を返した時に呼ぶ。指定 project の halt フラグを立てる.
    project: "shimahara" / "syutain" (bearer = syutain side)
    """
    from tools.db_pool import get_connection
    await _ensure_table()
    project = _normalize_project(project)
    key = _state_key(project)
    now = datetime.now(timezone.utc)
    halt_until = now + timedelta(hours=DEFAULT_HALT_HOURS)
    payload = {
        "halted": True,
        "project": project,
        "since": now.isoformat(),
        "halt_until": halt_until.isoformat(),
        "last_endpoint": endpoint_hint[:200],
        "notify_sent_at": None,
    }

    existing_notify = None
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM system_state WHERE key=$1", key
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
                   VALUES ($1, $2::jsonb, NOW())
                   ON CONFLICT (key) DO UPDATE
                   SET value=$2::jsonb, updated_at=NOW()""",
                key, json.dumps(payload, ensure_ascii=False, default=str),
            )
    except Exception as e:
        logger.warning(f"register_402({project}) failed: {e}")
        return

    logger.critical(
        f"x_credit_guard: 402 検出 ({project}) → {DEFAULT_HALT_HOURS}h halt "
        f"(until {halt_until.astimezone(JST).isoformat()})"
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
                f"🛑 **X API Credit 切れ ({project} project)**\n"
                f"error: 402 Payment Required\n"
                f"endpoint: {endpoint_hint[:150] or '(未指定)'}\n"
                f"halt until: {halt_until.astimezone(JST).strftime('%m/%d %H:%M JST')}\n"
                f"解除: credit 追加後 → tools.x_credit_guard.reset_halt('{project}')"
            )
            payload["notify_sent_at"] = now.isoformat()
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE system_state SET value=$1::jsonb, updated_at=NOW() WHERE key=$2",
                    json.dumps(payload, ensure_ascii=False, default=str), key,
                )
        except Exception as e:
            logger.warning(f"credit_guard Discord notify failed: {e}")


async def is_halted(project: str = "syutain") -> bool:
    """指定 project の halt 状態を返す。タイムアウトなら自動解除."""
    from tools.db_pool import get_connection
    project = _normalize_project(project)
    key = _state_key(project)
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM system_state WHERE key=$1", key
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
                    await reset_halt(project=project, reason="auto_timeout")
                    return False
            except Exception:
                pass

        return True
    except Exception as e:
        logger.warning(f"is_halted({project}) check failed: {e}")
        return False


async def reset_halt(project: str = "syutain", reason: str = "manual") -> None:
    """指定 project の halt フラグを解除。"""
    from tools.db_pool import get_connection
    project = _normalize_project(project)
    key = _state_key(project)
    try:
        async with get_connection() as conn:
            await conn.execute(
                """UPDATE system_state SET value=jsonb_set(
                     COALESCE(value, '{}'::jsonb), '{halted}', 'false'::jsonb
                   ), updated_at=NOW()
                   WHERE key=$1""",
                key,
            )
        logger.info(f"x_credit_guard: halt 解除 project={project} reason={reason}")
        if reason == "manual":
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"✅ X API Credit Guard 解除 ({project})\n"
                    f"reason={reason}\n"
                    f"{project} project の X 系ジョブを再開しました"
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"reset_halt({project}) failed: {e}")


def is_402_error(error_obj: Exception | str) -> bool:
    """エラーから 402 Payment Required を検出する"""
    s = str(error_obj).lower()
    return (
        "402" in s and "payment required" in s
    ) or "does not have any credits" in s


async def guard_check(project: str = "syutain", job_name: str = "") -> bool:
    """X 系ジョブが実行前に呼ぶラッパ。halt 中なら False、実行 OK なら True"""
    if await is_halted(project):
        logger.debug(f"{job_name}: x_credit_guard により skip (project={project})")
        return False
    return True


def account_to_project(account: str) -> str:
    """account 名を project key にマップする."""
    return _normalize_project(account)
