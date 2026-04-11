"""
PDL (Parallel Development Loop) 監視ツール

2026-04-11 島原さん方針「PDLはコスト0なので廃止せず監視のみ」に基づき追加。
毎時、PDL worker の稼働状況を軽量チェックし、異常時のみ Discord 通知する。

チェック項目:
1. crontab に PDL エントリが存在するか
2. logs/pdl_worker.log の最終更新時刻（30分以内に更新されていればOK）
3. /tmp/pdl_worker.lock が存在する場合、中身のPIDが生存しているか
4. 直近ログにエラー('ERROR', 'FAILED')が含まれていないか
5. pdl/PAUSE ファイルが存在するか（意図的な停止）
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

PDL_LOG = Path.home() / "syutain_beta" / "logs" / "pdl_worker.log"
PDL_LOCK = Path("/tmp/pdl_worker.lock")
PDL_PAUSE = Path.home() / "syutain_beta" / "pdl" / "PAUSE"
PDL_WORKER_SH = Path.home() / "syutain_beta" / "pdl" / "worker.sh"

# cron は10分間隔で走るので、30分以上ログ更新がなければ異常
MAX_LOG_AGE_MINUTES = 30


def _check_cron_registered() -> bool:
    """crontab に PDL worker エントリが登録されているかチェック"""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        return "pdl/worker.sh" in result.stdout
    except Exception as e:
        logger.warning(f"crontab チェック失敗: {e}")
        return False


def _check_log_freshness() -> tuple[bool, float]:
    """ログの最終更新時刻をチェック。戻り値: (fresh, age_minutes)"""
    if not PDL_LOG.exists():
        return False, -1
    try:
        mtime = PDL_LOG.stat().st_mtime
        age_sec = time.time() - mtime
        age_min = age_sec / 60
        return age_min <= MAX_LOG_AGE_MINUTES, age_min
    except Exception:
        return False, -1


def _check_lock_file() -> tuple[bool, str]:
    """ロックファイルの状態をチェック。戻り値: (healthy, message)"""
    if not PDL_LOCK.exists():
        return True, "ロックなし（正常 or 未稼働）"
    try:
        pid_str = PDL_LOCK.read_text().strip()
        if not pid_str:
            return False, "ロックファイル存在するがPID空"
        pid = int(pid_str)
        # PIDの生存確認（kill -0）
        try:
            os.kill(pid, 0)
            return True, f"ロックあり、PID={pid} 生存中"
        except ProcessLookupError:
            return False, f"ロックファイルあり、PID={pid} 既に死亡（stale lock）"
        except PermissionError:
            # プロセスは存在するが権限不足 — 生存扱い
            return True, f"ロックあり、PID={pid} (権限外だが生存)"
    except Exception as e:
        return False, f"ロック判定失敗: {e}"


def _scan_recent_errors(max_lines: int = 200) -> list[str]:
    """直近ログからエラー行を抽出"""
    if not PDL_LOG.exists():
        return []
    try:
        # 直近200行のみ読む
        result = subprocess.run(
            ["tail", "-n", str(max_lines), str(PDL_LOG)],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.splitlines()
        errors = []
        for line in lines:
            lu = line.upper()
            if ("ERROR" in lu or "FAILED" in lu or "BUDGET EXCEEDED" in lu) and "INFO" not in lu:
                errors.append(line[:200])
        return errors[-5:]  # 最新5件
    except Exception as e:
        logger.warning(f"ログスキャン失敗: {e}")
        return []


async def check_pdl_health() -> dict[str, Any]:
    """PDL の総合ヘルスチェック"""
    status: dict[str, Any] = {
        "timestamp": datetime.now(JST).isoformat(),
        "healthy": True,
        "warnings": [],
        "errors": [],
        "details": {},
    }

    # 0. worker.sh ファイル自体の存在確認
    if not PDL_WORKER_SH.exists():
        status["healthy"] = False
        status["errors"].append(f"worker.sh が存在しない: {PDL_WORKER_SH}")
        return status

    # 1. PAUSE ファイル確認
    if PDL_PAUSE.exists():
        status["details"]["paused"] = True
        status["warnings"].append("PDL は PAUSE ファイルで意図的に停止中")
        return status
    status["details"]["paused"] = False

    # 2. crontab 登録確認
    cron_ok = _check_cron_registered()
    status["details"]["cron_registered"] = cron_ok
    if not cron_ok:
        status["healthy"] = False
        status["errors"].append("crontab に pdl/worker.sh エントリがない")

    # 3. ログ新鮮度
    fresh, age_min = _check_log_freshness()
    status["details"]["log_age_minutes"] = round(age_min, 1) if age_min >= 0 else None
    status["details"]["log_fresh"] = fresh
    if age_min < 0:
        status["warnings"].append(
            f"pdl_worker.log が未作成（cron起動時に環境変数問題等で失敗の可能性）"
        )
    elif not fresh:
        status["healthy"] = False
        status["errors"].append(
            f"ログが {age_min:.0f}分更新されていない（cron=10分間隔、閾値={MAX_LOG_AGE_MINUTES}分）"
        )

    # 4. ロック状態
    lock_ok, lock_msg = _check_lock_file()
    status["details"]["lock_status"] = lock_msg
    if not lock_ok:
        status["healthy"] = False
        status["errors"].append(f"ロック異常: {lock_msg}")

    # 5. 最近のエラー
    recent_errors = _scan_recent_errors()
    status["details"]["recent_errors"] = recent_errors
    if recent_errors:
        # エラーがあっても健全性は個別判定（BUDGET EXCEEDED は正常動作）
        budget_only = all("BUDGET EXCEEDED" in e for e in recent_errors)
        if not budget_only:
            status["warnings"].append(f"直近エラー {len(recent_errors)}件")

    return status


async def pdl_monitor_check_and_alert() -> dict[str, Any]:
    """ヘルスチェック → 異常時 Discord 通知"""
    status = await check_pdl_health()

    if not status["healthy"]:
        try:
            from tools.discord_notify import notify_discord
            err_summary = " / ".join(status["errors"][:3])
            msg = f"⚠️ PDL Worker 異常検出\n{err_summary}"
            if status["details"].get("log_age_minutes") is not None:
                msg += f"\nログ最終更新: {status['details']['log_age_minutes']}分前"
            await notify_discord(msg)
            logger.warning(f"PDL監視: 異常通知送信 — errors={status['errors']}")
        except Exception as e:
            logger.error(f"PDL異常通知失敗: {e}")
    else:
        logger.debug(f"PDL監視: 正常 details={status['details']}")

    return status
