#!/usr/bin/env python3
"""
SYUTAINβ Brain-α PreToolUse Hook: 安全装置
禁止ファイルへの書き込み・危険コマンドをブロックする。

Claude Code Hooks仕様:
  - stdinからJSON入力（tool_name, tool_input）
  - exit 0 = 許可
  - exit 2 = ブロック（stderrに理由出力）
  - exit 1 = 警告のみ（ブロックしない）
"""

import sys
import json
import re


# 書き込み禁止ファイルパターン
BLOCKED_FILE_SUFFIXES = [
    ".env",
    "start.sh",
    "settings.json",
    "settings.local.json",
]

# 禁止コマンドパターン（Bash用）
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r"TRUNCATE\s+",
    r">\s*/dev/sd",
    r"mkfs\.",
    r"dd\s+if=",
]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # JSON読み取り失敗時は許可

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Write/Edit: ファイルパスチェック
    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        for suffix in BLOCKED_FILE_SUFFIXES:
            if file_path.endswith(suffix):
                print(
                    f"BLOCKED: {suffix}への書き込みは禁止されています（Brain-α安全装置）",
                    file=sys.stderr,
                )
                sys.exit(2)

    # Bash: 危険コマンドチェック
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                print(
                    f"BLOCKED: 危険なコマンドパターン '{pattern}' が検出されました（Brain-α安全装置）",
                    file=sys.stderr,
                )
                sys.exit(2)

    sys.exit(0)  # 許可


if __name__ == "__main__":
    main()
