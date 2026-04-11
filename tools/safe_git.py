"""Safe Git 操作ラッパ — 破壊的な全ツリー操作を構造的に拒否する

2026-04-11 05:19 の改修消失事故を構造的に再発不能にするための防御層。
`git checkout -- .`, `git reset --hard`, `git clean -fd` 等の「作業ツリー全体を
触る」コマンドは、意図して Codex の revert ロジックが混入すると過去の未コミット
作業ごと吹き飛ばすため、このラッパ経由のみ許可する。

使い方:
    from tools.safe_git import safe_git_run

    proc = await safe_git_run("git", "diff", "--name-only", cwd=REPO_DIR)
    stdout, stderr = await proc.communicate()

    # 以下は DangerousGitError を raise する:
    await safe_git_run("git", "checkout", "--", ".", cwd=REPO_DIR)
    await safe_git_run("git", "reset", "--hard", "HEAD", cwd=REPO_DIR)
    await safe_git_run("git", "clean", "-fd", cwd=REPO_DIR)

起動時サニティチェック:
    result = audit_codebase_for_dangerous_git("/path/to/repo")
    if result:
        # danger patterns still present in code — abort startup
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("syutain.safe_git")

JST = timezone(timedelta(hours=9))


class DangerousGitError(RuntimeError):
    """危険な git 操作が拒否された"""


# 拒否するコマンドパターン (引数列を subprocess に渡す形で判定)
# 各エントリ: (name, predicate)
# predicate(args: list[str]) -> reason (str) or None
def _is_checkout_wildcard(args: list[str]) -> str | None:
    """git checkout -- . や git checkout -- *.py のような全ツリー操作を検出"""
    if len(args) < 2 or args[0] != "git" or args[1] != "checkout":
        return None
    # git checkout [flags] -- <pathspec>
    try:
        sep = args.index("--")
    except ValueError:
        return None
    paths = args[sep + 1:]
    if not paths:
        return None
    for p in paths:
        if p in (".", "./", "*"):
            return f"git checkout -- '{p}' は作業ツリー全体を破壊する（2026-04-11 事故原因）"
        if p.startswith("*") or p.endswith("*"):
            return f"git checkout -- '{p}' は wildcard で広範囲を破壊する可能性がある"
    return None


def _is_reset_hard(args: list[str]) -> str | None:
    if len(args) < 2 or args[0] != "git" or args[1] != "reset":
        return None
    if "--hard" in args:
        return "git reset --hard は作業ツリーを破壊する"
    return None


def _is_clean_destructive(args: list[str]) -> str | None:
    if len(args) < 2 or args[0] != "git" or args[1] != "clean":
        return None
    # git clean -f, -fd, -fx, -fdx etc — どれも未追跡ファイルを削除
    for a in args[2:]:
        if a.startswith("-") and "f" in a:
            return f"git clean {a} は未追跡ファイルを削除する"
    return None


DANGEROUS_PREDICATES = (
    ("checkout_wildcard", _is_checkout_wildcard),
    ("reset_hard", _is_reset_hard),
    ("clean_destructive", _is_clean_destructive),
)


def is_dangerous_git_args(args: list[str] | tuple[str, ...]) -> tuple[bool, str]:
    """args を検査し、危険なら (True, reason) を返す"""
    args_list = list(args)
    for _name, pred in DANGEROUS_PREDICATES:
        reason = pred(args_list)
        if reason:
            return True, reason
    return False, ""


async def _log_git_event(event_type: str, args: list[str], extra: dict[str, Any] | None = None) -> None:
    """git 操作を event_log に fire-and-forget で記録"""
    try:
        from tools.db_pool import get_connection
        import json as _json
        payload = {
            "cmd": " ".join(args)[:500],
            "at": datetime.now(JST).isoformat(),
        }
        if extra:
            payload.update(extra)
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                   VALUES ($1, 'safe_git', $2, 'alpha', $3::jsonb, NOW())""",
                event_type,
                "error" if event_type.endswith(".blocked") else "info",
                _json.dumps(payload, ensure_ascii=False),
            )
    except Exception:
        # event_log 失敗でも git 処理は止めない
        pass


async def safe_git_run(
    *args: str,
    cwd: str | None = None,
    stdin: Any = asyncio.subprocess.DEVNULL,
    stdout: Any = asyncio.subprocess.PIPE,
    stderr: Any = asyncio.subprocess.PIPE,
) -> asyncio.subprocess.Process:
    """git コマンドを安全に実行する。危険パターンは DangerousGitError を raise。

    通常の `asyncio.create_subprocess_exec(*args, ...)` と同じ戻り値 (Process) を返す。
    """
    args_list = list(args)
    if not args_list or args_list[0] != "git":
        raise ValueError(f"safe_git_run は git コマンド専用: {args_list[:2]}")

    is_bad, reason = is_dangerous_git_args(args_list)
    if is_bad:
        logger.error(f"safe_git: 拒否 {' '.join(args_list)} — {reason}")
        await _log_git_event("safe_git.blocked", args_list, {"reason": reason})
        # Discord 通知
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(
                f"🛑 **safe_git: 危険な git 操作を拒否**\n"
                f"cmd: `{' '.join(args_list)[:200]}`\n"
                f"reason: {reason}\n"
                f"cwd: {cwd or os.getcwd()}"
            )
        except Exception:
            pass
        raise DangerousGitError(f"{reason}: {' '.join(args_list)}")

    # 許可: 実行
    await _log_git_event("safe_git.run", args_list)
    return await asyncio.create_subprocess_exec(
        *args_list,
        cwd=cwd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


# 起動時サニティチェック -------------------------------------------------

# コード中で .py ファイルに現れる危険パターン
_SCAN_PATTERNS = (
    # git checkout -- .    (最も危険 — 事故原因)
    (re.compile(r'["\']git["\'].{0,50}["\']checkout["\'].{0,50}["\']--["\'].{0,30}["\']\.[\'"]'),
     "git checkout -- '.' (full-tree checkout)"),
    # git reset --hard
    (re.compile(r'["\']git["\'].{0,50}["\']reset["\'].{0,50}["\']--hard["\']'),
     "git reset --hard"),
    # git clean -fd / -fx / -fdx
    (re.compile(r'["\']git["\'].{0,50}["\']clean["\'].{0,50}["\']-f[dx]*["\']'),
     "git clean -f*"),
)

_AUDIT_EXCLUDE_DIRS = (
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "data", "logs", "tmp", ".context",
)

_AUDIT_ALLOW_FILES = (
    # このファイル自身はパターン検出を保持するため、例外登録
    "tools/safe_git.py",
)


def audit_codebase_for_dangerous_git(root_path: str) -> list[dict]:
    """repo 全体を走査し、危険な git 操作が残っていないかを確認する。
    scheduler 起動時に呼ばれる。

    Returns: list of {file, line, match, pattern_name}
    """
    findings: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in _AUDIT_EXCLUDE_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root_path)
            if rel in _AUDIT_ALLOW_FILES:
                continue
            try:
                with open(full, "r", encoding="utf-8") as f:
                    for lineno, line in enumerate(f, start=1):
                        for pat, pname in _SCAN_PATTERNS:
                            if pat.search(line):
                                findings.append({
                                    "file": rel,
                                    "line": lineno,
                                    "match": line.strip()[:200],
                                    "pattern": pname,
                                })
            except Exception:
                continue
    return findings


async def startup_git_safety_audit(root_path: str) -> dict:
    """scheduler 起動時の git 安全性監査。

    Returns: {"clean": bool, "findings": list, "count": int}
    危険パターンが見つかった場合、CRITICAL level で event_log + Discord 通知。
    """
    findings = audit_codebase_for_dangerous_git(root_path)
    result = {"clean": len(findings) == 0, "findings": findings, "count": len(findings)}

    if findings:
        logger.critical(
            f"startup_git_safety_audit: {len(findings)}件の危険パターンを検出\n"
            + "\n".join(
                f"  {f['file']}:{f['line']} — {f['pattern']}: {f['match'][:100]}"
                for f in findings[:10]
            )
        )
        # event_log
        try:
            from tools.db_pool import get_connection
            import json as _json
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                       VALUES ('safe_git.startup_audit_failed', 'safe_git', 'critical', 'alpha', $1::jsonb, NOW())""",
                    _json.dumps({"count": len(findings), "findings": findings[:20]}, ensure_ascii=False),
                )
        except Exception:
            pass
        # Discord 通知
        try:
            from tools.discord_notify import notify_discord
            sample = "\n".join(
                f"• `{f['file']}:{f['line']}` — {f['pattern']}"
                for f in findings[:5]
            )
            await notify_discord(
                f"🛑 **safe_git startup audit FAILED**\n"
                f"危険な git 操作が {len(findings)} 件残存:\n{sample}\n"
                f"※ 本来 codex_auto_fix 等で revert されるべきだが、構造的防御のため即修正してください。"
            )
        except Exception:
            pass
    else:
        logger.info("safe_git startup audit: ✅ clean (no dangerous git patterns)")

    return result
