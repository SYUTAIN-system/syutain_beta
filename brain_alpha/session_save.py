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


async def save_session():
    """セッション状態を保存"""
    if not should_save():
        return

    try:
        from tools.db_pool import init_pool, close_pool
        await init_pool(min_size=1, max_size=3)

        from brain_alpha.memory_manager import save_session_memory
        from datetime import datetime, timezone
        session_id = f"auto-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        await save_session_memory(
            session_id=session_id,
            summary="セッション自動保存（Stopフック）",
            open_issues=[],
            daichi_interactions=0,
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
