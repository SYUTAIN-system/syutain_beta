#!/usr/bin/env python3
"""
SYUTAINβ Brain-α PostToolUse Hook: ファイル修正自動ログ
Write/Edit実行後にauto_fix_logに記録する。

Claude Code Hooks仕様:
  - stdinからJSON入力（tool_name, tool_input）
  - PostToolUseはブロック不可（exit codeに関わらず処理は完了済み）
  - exit 0で正常終了
"""

import sys
import json
import asyncio
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def log_modification(tool_name: str, file_path: str):
    """ファイル修正をauto_fix_logに記録"""
    try:
        from tools.db_pool import init_pool, close_pool, get_connection
        await init_pool(min_size=1, max_size=3)

        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO auto_fix_log
                   (fix_type, error_type, detail, strategy, result, files_affected, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                "file_modification",
                tool_name.lower(),
                f"{tool_name}: {file_path}",
                "brain_alpha_hook",
                "logged",
                json.dumps([file_path], ensure_ascii=False),
                datetime.now(timezone.utc),
            )

        await close_pool()
    except Exception:
        pass  # PostToolUseはエラーでも処理を止めない


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "unknown")

    try:
        asyncio.run(log_modification(tool_name, file_path))
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
