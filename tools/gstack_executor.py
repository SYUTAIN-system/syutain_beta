"""SYUTAINβ gstack自律実行ラッパー
Codex exec経由でgstackコマンドを自動実行する。

使用例:
    result = await run_gstack("review")
    result = await run_gstack("cso")
    result = await run_gstack("retro")
"""

import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger("syutain.gstack")

PROJECT_DIR = os.path.expanduser("~/syutain_beta")
CODEX_PATH = "/opt/homebrew/bin/codex"

# gstackコマンドの実行時間上限（秒）
TIMEOUT_MAP = {
    "review": 420,        # コードレビュー: 7分（180sだと2日連続でTIMEOUT発生のため延長）
    "cso": 600,           # セキュリティ監査: 10分
    "retro": 420,         # 振り返り: 7分（180sで08:03 TIMEOUTしたため延長 2026-04-06）
    "qa": 300,            # QAテスト: 5分（ブラウザ操作あり）
    "investigate": 300,   # エラー調査: 5分
    "health": 60,         # ヘルスチェック: 1分
    "design-review": 180, # デザインレビュー: 3分
}
DEFAULT_TIMEOUT = 120


async def run_gstack(command: str, extra_prompt: str = "", cwd: str = None) -> dict:
    """gstackコマンドをCodex exec経由で実行

    Args:
        command: gstackコマンド名（例: "review", "cso", "retro"）
        extra_prompt: 追加指示
        cwd: 作業ディレクトリ（デフォルト: PROJECT_DIR）

    Returns:
        {"success": bool, "output": str, "duration_ms": int, "command": str}
    """
    work_dir = cwd or PROJECT_DIR
    timeout = TIMEOUT_MAP.get(command, DEFAULT_TIMEOUT)

    prompt = f"/gstack-{command}"
    if extra_prompt:
        prompt += f" {extra_prompt}"

    output_file = f"/tmp/gstack_{command}_{datetime.now().strftime('%H%M%S')}.txt"

    start = datetime.now()
    try:
        # Load .env for API keys
        env = os.environ.copy()
        env_file = os.path.join(PROJECT_DIR, ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        env[key.strip()] = val.strip()

        proc = await asyncio.create_subprocess_exec(
            CODEX_PATH, "exec", prompt,
            "--output-last-message", output_file,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        duration = int((datetime.now() - start).total_seconds() * 1000)

        # Read output file
        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            os.unlink(output_file)

        if not output:
            output = stdout.decode("utf-8", errors="replace")

        success = proc.returncode == 0

        # Log to event_log
        try:
            from tools.event_logger import log_event
            await log_event(
                f"gstack.{command}", "gstack",
                {"command": command, "success": success, "duration_ms": duration, "output_preview": output[:200]},
                severity="info" if success else "warning",
            )
        except Exception:
            pass

        logger.info(f"gstack {command}: {'OK' if success else 'FAIL'} ({duration}ms)")

        return {"success": success, "output": output, "duration_ms": duration, "command": command}

    except asyncio.TimeoutError:
        duration = int((datetime.now() - start).total_seconds() * 1000)
        logger.error(f"gstack {command}: TIMEOUT ({timeout}s)")
        return {"success": False, "output": f"Timeout after {timeout}s", "duration_ms": duration, "command": command}

    except Exception as e:
        logger.error(f"gstack {command}: ERROR {e}")
        return {"success": False, "output": str(e), "duration_ms": 0, "command": command}


async def run_code_review() -> dict:
    """コードレビューを実行（最新のgit変更に対して）"""
    return await run_gstack("review", "--uncommitted")


async def run_security_audit() -> dict:
    """セキュリティ監査を実行"""
    return await run_gstack("cso")


async def run_retro() -> dict:
    """週次振り返りを実行"""
    return await run_gstack("retro")


async def run_investigate(error_description: str) -> dict:
    """エラー調査を実行"""
    return await run_gstack("investigate", error_description)


async def run_health_check() -> dict:
    """システムヘルスチェック"""
    return await run_gstack("health")
