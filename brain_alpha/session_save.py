#!/usr/bin/env python3
"""
SYUTAINβ Brain-α Stop Hook: セッション自動保存
Claudeの応答完了時に発火。過剰保存を防ぐため5分間隔制限。

Claude Code Hooks仕様:
  - Stopイベントは毎応答完了時に発火
  - stdinからJSON入力
  - exit 0で正常終了
"""

import sys
import json
import asyncio
import os
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LAST_SAVE_FILE = "/tmp/syutain_last_session_save"
MIN_INTERVAL_SEC = 300  # 5分


def should_save() -> bool:
    """前回保存から5分以上経過しているか"""
    try:
        if Path(LAST_SAVE_FILE).exists():
            last_ts = float(Path(LAST_SAVE_FILE).read_text().strip())
            if time.time() - last_ts < MIN_INTERVAL_SEC:
                return False
    except Exception:
        pass
    return True


def mark_saved():
    """保存時刻を記録"""
    try:
        Path(LAST_SAVE_FILE).write_text(str(time.time()))
    except Exception:
        pass


async def _gather_session_context() -> dict:
    """直近のシステム活動からセッションコンテキストを収集"""
    from tools.db_pool import get_connection
    ctx = {"open_issues": [], "summary_parts": [], "daichi_interactions": 0, "files_modified": []}
    try:
        async with get_connection() as conn:
            # 直近の未処理エラー（open_issues候補）
            errors = await conn.fetch(
                """SELECT event_type, payload FROM event_log
                WHERE severity IN ('error', 'critical')
                AND created_at > NOW() - INTERVAL '30 minutes'
                ORDER BY created_at DESC LIMIT 5"""
            )
            for e in errors:
                detail = e["event_type"]
                if e["payload"] and isinstance(e["payload"], dict):
                    detail += f": {str(e['payload'].get('error', ''))[:80]}"
                ctx["open_issues"].append(detail)

            # 直近の承認待ちキュー数
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'"
            ) or 0
            if pending > 0:
                ctx["summary_parts"].append(f"承認待ち{pending}件")

            # 直近のタスク完了数
            completed = await conn.fetchval(
                """SELECT COUNT(*) FROM tasks
                WHERE status = 'completed'
                AND updated_at > NOW() - INTERVAL '30 minutes'"""
            ) or 0
            if completed > 0:
                ctx["summary_parts"].append(f"タスク{completed}件完了")

            # 直近のchat_messages数（daichi_interactions代替）
            chats = await conn.fetchval(
                """SELECT COUNT(*) FROM chat_messages
                WHERE role = 'user'
                AND created_at > NOW() - INTERVAL '30 minutes'"""
            ) or 0
            ctx["daichi_interactions"] = chats

            # 直近の自動修復
            fixes = await conn.fetchval(
                """SELECT COUNT(*) FROM auto_fix_log
                WHERE created_at > NOW() - INTERVAL '30 minutes'"""
            ) or 0
            if fixes > 0:
                ctx["summary_parts"].append(f"自動修復{fixes}件実行")

    except Exception:
        pass
    return ctx


async def save_session():
    """セッション状態を保存"""
    if not should_save():
        return

    try:
        from tools.db_pool import init_pool, close_pool
        await init_pool(min_size=1, max_size=3)

        ctx = await _gather_session_context()

        from brain_alpha.memory_manager import save_session_memory
        from datetime import datetime, timezone
        session_id = f"auto-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        summary = "セッション自動保存（Stopフック）"
        if ctx["summary_parts"]:
            summary += " — " + ", ".join(ctx["summary_parts"])

        await save_session_memory(
            session_id=session_id,
            summary=summary,
            open_issues=ctx["open_issues"],
            daichi_interactions=ctx["daichi_interactions"],
        )
        mark_saved()
        await close_pool()
    except Exception:
        pass


def main():
    try:
        json.load(sys.stdin)  # 入力を消費（使わないが読む必要がある）
    except Exception:
        pass

    try:
        asyncio.run(save_session())
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
