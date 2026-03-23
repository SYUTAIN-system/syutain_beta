"""
SYUTAINβ Brain-α 自律修復（Self-Healing）+ 自律回復（Self-Recovery）
設計書 Section 5, 10 準拠

⚠️ CHARLIE Win11対応:
  node_state='charlie_win11' → 修復試行しない
  node_state='healthy' + SSH応答なし → 10分猶予 → charlie_win11自動移行
  SSH復帰検出 → healthy自動復帰
"""

import os
import json
import time
import asyncio
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.self_healer")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

NODE_IPS = {
    "bravo": "100.75.146.9",
    "charlie": "100.70.161.106",
    "delta": "100.82.81.105",
}

NODE_STATES = {
    "healthy": "SSH応答あり、全サービス正常",
    "degraded": "SSH応答あり、一部サービス異常",
    "charlie_win11": "CHARLIE固有: SSH応答なし（島原Win11使用中）",
    "down": "SSH応答なし（障害）",
    "recovering": "復旧処理中",
    "unknown": "状態判定不能",
}

# CHARLIE SSH猶予タイマー（初回検出時刻を記録）
_charlie_ssh_fail_since: Optional[float] = None
CHARLIE_GRACE_PERIOD = 600  # 10分


async def _get_conn() -> Optional[asyncpg.Connection]:
    try:
        return await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"DB接続失敗: {e}")
        return None


def _ssh_check(ip: str, timeout: int = 5) -> bool:
    """SSH疎通確認"""
    try:
        result = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={timeout}", "-o", "StrictHostKeyChecking=no",
             f"shimahara@{ip}", "echo ok"],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def _ssh_exec(ip: str, cmd: str, timeout: int = 15) -> tuple[bool, str]:
    """SSH経由でコマンド実行"""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             f"shimahara@{ip}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


async def _update_node_state(conn, node: str, state: str, reason: str, changed_by: str = "self_healer"):
    """node_stateを更新"""
    await conn.execute(
        """UPDATE node_state SET state = $1, reason = $2, changed_by = $3, changed_at = NOW()
           WHERE node_name = $4""",
        state, reason, changed_by, node,
    )


async def _log_fix(conn, error_type: str, detail: str, strategy: str, result: str, files: list = None):
    """auto_fix_logに修復記録"""
    await conn.execute(
        """INSERT INTO auto_fix_log (error_type, error_detail, fix_strategy, fix_result, files_modified)
           VALUES ($1, $2, $3, $4, $5)""",
        error_type, detail, strategy, result,
        json.dumps(files or [], ensure_ascii=False),
    )


async def _notify(message: str):
    """Discord通知"""
    try:
        from tools.discord_notify import notify_discord
        await notify_discord(message)
    except Exception:
        pass


# ======================================================================
# 自律修復メインループ（5分間隔）
# ======================================================================

async def self_heal_check() -> dict:
    """全ノードサービス確認 + 自動修復"""
    global _charlie_ssh_fail_since

    conn = await _get_conn()
    if not conn:
        return {"status": "db_error"}

    results = {"checked_at": datetime.now(timezone.utc).isoformat(), "nodes": {}, "fixes": []}

    try:
        # 現在のnode_state取得
        states = {}
        rows = await conn.fetch("SELECT node_name, state FROM node_state")
        for r in rows:
            states[r["node_name"]] = r["state"]

        # --- ALPHA（ローカル） ---
        results["nodes"]["alpha"] = await _check_alpha_services(conn, results["fixes"])

        # --- BRAVO / CHARLIE / DELTA ---
        for node, ip in NODE_IPS.items():
            current_state = states.get(node, "unknown")

            # CHARLIE Win11: 修復試行しない
            if node == "charlie" and current_state == "charlie_win11":
                # ただしSSH復帰を検出したらhealthyに戻す
                if _ssh_check(ip, timeout=3):
                    await _update_node_state(conn, "charlie", "healthy", "SSH復帰検出（自動）")
                    await _notify("✅ CHARLIE: Ubuntu復帰を自動検出。推論ノードとして再稼働。")
                    _charlie_ssh_fail_since = None
                    results["nodes"]["charlie"] = "restored_from_win11"
                    try:
                        from tools.event_logger import log_event
                        await log_event("charlie.auto_restore", "node",
                                        {"node": "charlie", "new_state": "healthy"}, source_node="alpha")
                    except Exception:
                        pass
                else:
                    results["nodes"]["charlie"] = "charlie_win11"
                continue

            # SSH疎通チェック
            ssh_ok = _ssh_check(ip)

            if not ssh_ok:
                # CHARLIE固有: Win11自動移行ロジック
                if node == "charlie":
                    if _charlie_ssh_fail_since is None:
                        _charlie_ssh_fail_since = time.time()
                        results["nodes"]["charlie"] = "ssh_fail_grace_period"
                        continue

                    elapsed = time.time() - _charlie_ssh_fail_since
                    if elapsed < CHARLIE_GRACE_PERIOD:
                        results["nodes"]["charlie"] = f"ssh_fail_grace_{int(elapsed)}s"
                        continue

                    # 10分経過: charlie_win11に自動移行
                    await _update_node_state(conn, "charlie", "charlie_win11",
                                            "SSH応答なし10分超過。Win11使用中と判断（自動）")
                    await _notify("⚠️ CHARLIE: 応答なし。Win11使用中の可能性。自動メンテナンスモード。")
                    _charlie_ssh_fail_since = None
                    results["nodes"]["charlie"] = "auto_charlie_win11"
                    try:
                        from tools.event_logger import log_event
                        await log_event("charlie.auto_win11", "node",
                                        {"node": "charlie", "reason": "SSH応答なし10分超過"}, source_node="alpha")
                    except Exception:
                        pass
                else:
                    # BRAVO/DELTA: 障害
                    if current_state != "down":
                        await _update_node_state(conn, node, "down", f"SSH応答なし")
                        await _notify(f"🔴 {node.upper()}: SSH応答なし。ダウンと判定。")
                    results["nodes"][node] = "down"
                continue

            # SSH OK → CHARLIEの猶予タイマーリセット
            if node == "charlie":
                _charlie_ssh_fail_since = None

            # サービスチェック + 修復
            node_result = await _check_remote_services(conn, node, ip, results["fixes"])
            results["nodes"][node] = node_result

            # downからの復帰
            if current_state in ("down", "recovering") and node_result in ("healthy", "degraded"):
                await _update_node_state(conn, node, node_result, "サービス復帰検出（自動）")
                await _notify(f"✅ {node.upper()}: 復帰。状態={node_result}")

    except Exception as e:
        logger.error(f"self_heal_check例外: {e}")
        results["error"] = str(e)
    finally:
        await conn.close()

    return results


async def _check_alpha_services(conn, fixes: list) -> str:
    """ALPHAローカルサービスチェック"""
    status = "healthy"

    # FastAPI
    try:
        result = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                 "http://localhost:8000/health"], capture_output=True, text=True, timeout=5)
        if result.stdout.strip() != "200":
            status = "degraded"
            # launchd再起動
            subprocess.run(["launchctl", "kickstart", "-k",
                            f"gui/{os.getuid()}/com.syutain.fastapi"], capture_output=True, timeout=10)
            await _log_fix(conn, "fastapi_down", "HTTP応答なし", "launchctl_restart", "attempted")
            fixes.append("FastAPI再起動")
    except Exception:
        pass

    # Next.js
    try:
        result = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                 "http://localhost:3000/"], capture_output=True, text=True, timeout=5)
        if result.stdout.strip() != "200":
            status = "degraded"
            subprocess.run(["launchctl", "kickstart", "-k",
                            f"gui/{os.getuid()}/com.syutain.nextjs"], capture_output=True, timeout=10)
            await _log_fix(conn, "nextjs_down", "HTTP応答なし", "launchctl_restart", "attempted")
            fixes.append("Next.js再起動")
    except Exception:
        pass

    # NATS
    try:
        result = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                 "http://localhost:8222/varz"], capture_output=True, text=True, timeout=5)
        if result.stdout.strip() != "200":
            status = "degraded"
            subprocess.run(["launchctl", "kickstart", "-k",
                            f"gui/{os.getuid()}/com.syutain.nats"], capture_output=True, timeout=10)
            await _log_fix(conn, "nats_down", "監視ポート応答なし", "launchctl_restart", "attempted")
            fixes.append("NATS再起動")
    except Exception:
        pass

    return status


async def _check_remote_services(conn, node: str, ip: str, fixes: list) -> str:
    """リモートノードのサービスチェック + 修復"""
    status = "healthy"

    # Ollamaチェック
    ok, out = _ssh_exec(ip, "curl -s -o /dev/null -w '%{http_code}' http://localhost:11434/api/tags", timeout=10)
    if not ok or "200" not in out:
        status = "degraded"
        # Ollama再起動
        _ssh_exec(ip, "sudo systemctl restart ollama", timeout=15)
        await _log_fix(conn, f"ollama_down_{node}", "Ollama API応答なし", "systemctl_restart", "attempted")
        fixes.append(f"{node.upper()} Ollama再起動")

    # Workerチェック
    ok, out = _ssh_exec(ip, "systemctl is-active syutain-worker-*", timeout=10)
    if not ok or "active" not in out:
        status = "degraded"
        _ssh_exec(ip, "sudo systemctl restart syutain-worker-alpha.service 2>/dev/null; "
                      "sudo systemctl restart syutain-worker.service 2>/dev/null", timeout=15)
        await _log_fix(conn, f"worker_down_{node}", "ワーカー非稼働", "systemctl_restart", "attempted")
        fixes.append(f"{node.upper()} Worker再起動")

    return status


# ======================================================================
# データ整合性回復（日次04:00）
# ======================================================================

async def data_integrity_check() -> dict:
    """データ整合性を確認・修復"""
    conn = await _get_conn()
    if not conn:
        return {"status": "db_error"}

    results = {"checked_at": datetime.now(timezone.utc).isoformat(), "fixes": []}

    try:
        # 1. stuck tasks: status='running' かつ30分以上前 → 'failed'
        stuck = await conn.execute(
            """UPDATE tasks SET status = 'failed', updated_at = NOW()
               WHERE status = 'running'
                 AND updated_at < NOW() - INTERVAL '30 minutes'"""
        )
        stuck_count = int(stuck.split()[-1]) if stuck else 0
        if stuck_count:
            results["fixes"].append(f"stuck_tasks: {stuck_count}件→failed")

        # 2. 72h超過承認 → 自動却下
        expired_approvals = await conn.execute(
            """UPDATE approval_queue SET status = 'expired', responded_at = NOW()
               WHERE status = 'pending'
                 AND requested_at < NOW() - INTERVAL '72 hours'"""
        )
        exp_count = int(expired_approvals.split()[-1]) if expired_approvals else 0
        if exp_count:
            results["fixes"].append(f"expired_approvals: {exp_count}件")

        # 3. 7日超過handoff → expired
        expired_handoffs = await conn.execute(
            """UPDATE brain_handoff SET status = 'expired'
               WHERE status = 'pending'
                 AND created_at < NOW() - INTERVAL '7 days'"""
        )
        hoff_count = int(expired_handoffs.split()[-1]) if expired_handoffs else 0
        if hoff_count:
            results["fixes"].append(f"expired_handoffs: {hoff_count}件")

        # 4. 10万件超過debug eventログ削除
        total_events = await conn.fetchval("SELECT COUNT(*) FROM event_log WHERE severity = 'info'")
        if total_events and total_events > 100000:
            delete_count = total_events - 80000  # 8万件まで削減
            await conn.execute(
                """DELETE FROM event_log WHERE id IN (
                     SELECT id FROM event_log WHERE severity = 'info'
                     ORDER BY created_at ASC LIMIT $1
                   )""",
                delete_count,
            )
            results["fixes"].append(f"old_events_pruned: {delete_count}件")

        results["status"] = "ok"
        if results["fixes"]:
            logger.info(f"データ整合性修復: {results['fixes']}")

    except Exception as e:
        logger.error(f"データ整合性チェック失敗: {e}")
        results["status"] = "error"
        results["error"] = str(e)
    finally:
        await conn.close()

    return results


# ======================================================================
# Brain-αセッション監視（10分間隔）
# ======================================================================

async def brain_alpha_health_check() -> dict:
    """Brain-αのtmuxセッション生存確認"""
    result = {"checked_at": datetime.now(timezone.utc).isoformat()}

    try:
        proc = subprocess.run(
            ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5,
        )
        sessions = proc.stdout.strip()
        brain_alive = "brain_alpha" in sessions
        result["brain_alpha_alive"] = brain_alive
        result["tmux_sessions"] = sessions

        if not brain_alive:
            result["action"] = "alert_sent"
            await _notify(
                "🧠 Brain-α tmuxセッション停止検出。\n"
                "`tmux new -s brain_alpha` で手動再起動するか、\n"
                "Brain-β側で自動再起動を実行してください。"
            )
    except Exception as e:
        result["error"] = str(e)

    return result


# ======================================================================
# 統合ステータス + 統計
# ======================================================================

async def get_healing_stats() -> dict:
    """自律修復の統計を返す"""
    conn = await _get_conn()
    if not conn:
        return {"status": "db_error"}

    try:
        # 24h修復件数
        total_24h = await conn.fetchval(
            "SELECT COUNT(*) FROM auto_fix_log WHERE created_at > NOW() - INTERVAL '24 hours'"
        )
        success_24h = await conn.fetchval(
            """SELECT COUNT(*) FROM auto_fix_log
               WHERE created_at > NOW() - INTERVAL '24 hours'
                 AND fix_result IN ('success', 'attempted')"""
        )

        # 7日修復件数
        total_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM auto_fix_log WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        # カテゴリ別
        by_type = await conn.fetch(
            """SELECT error_type, COUNT(*) as cnt, fix_result
               FROM auto_fix_log
               WHERE created_at > NOW() - INTERVAL '7 days'
               GROUP BY error_type, fix_result
               ORDER BY cnt DESC LIMIT 10"""
        )

        # 直近修復ログ
        recent = await conn.fetch(
            """SELECT id, error_type, error_detail, fix_strategy, fix_result, created_at
               FROM auto_fix_log ORDER BY created_at DESC LIMIT 20"""
        )

        return {
            "total_24h": total_24h or 0,
            "success_24h": success_24h or 0,
            "success_rate_24h": round((success_24h or 0) / max(total_24h or 1, 1) * 100, 1),
            "total_7d": total_7d or 0,
            "by_type": [{"error_type": r["error_type"], "count": r["cnt"], "result": r["fix_result"]} for r in by_type],
            "recent": [
                {
                    "id": r["id"],
                    "error_type": r["error_type"],
                    "error_detail": (r["error_detail"] or "")[:100],
                    "fix_strategy": r["fix_strategy"],
                    "fix_result": r["fix_result"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in recent
            ],
        }
    except Exception as e:
        logger.error(f"修復統計取得失敗: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        await conn.close()
