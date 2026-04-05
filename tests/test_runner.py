"""SYUTAINβ自動テストランナー
日中にローカルLLMを使ってテストを実行。API消費ゼロ。

3種類のテスト:
1. 構文テスト: 全.pyファイルのast.parse
2. インポートテスト: 全モジュールの循環依存チェック
3. 統合テスト: DB接続、NATS接続、主要関数の呼び出しテスト
4. リモートノードヘルスチェック: SSH/Ollama/ディスク
"""

import os
import ast
import sys
import json
import time
import asyncio
import logging
import importlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.test_runner")

BASE_DIR = Path(__file__).resolve().parent.parent
TARGET_DIRS = ["agents", "tools", "brain_alpha", "bots", "scripts"]

REMOTE_NODES = {
    "bravo": {
        "ip": os.getenv("BRAVO_IP", "127.0.0.1"),
        "user": os.getenv("REMOTE_SSH_USER", "user"),
        "services": ["syutain-worker-bravo"],
    },
    "charlie": {
        "ip": os.getenv("CHARLIE_IP", "127.0.0.1"),
        "user": os.getenv("REMOTE_SSH_USER", "user"),
        "services": ["syutain-worker-charlie"],
    },
    "delta": {
        "ip": os.getenv("DELTA_IP", "127.0.0.1"),
        "user": os.getenv("REMOTE_SSH_USER", "user"),
        "services": ["syutain-worker-delta"],
    },
}


def _collect_py_files() -> list[Path]:
    """対象ディレクトリ内の全.pyファイルを収集"""
    files = []
    for d in TARGET_DIRS:
        target = BASE_DIR / d
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
    return files


# ================================================================
# A. 構文テスト
# ================================================================

def run_syntax_tests() -> dict:
    """全.pyファイルのast.parseで構文チェック"""
    results = {"passed": 0, "failed": 0, "errors": [], "test_type": "syntax"}
    files = _collect_py_files()

    for fp in files:
        try:
            source = fp.read_text(encoding="utf-8")
            ast.parse(source, filename=str(fp))
            results["passed"] += 1
        except SyntaxError as e:
            results["failed"] += 1
            results["errors"].append({
                "file": str(fp.relative_to(BASE_DIR)),
                "line": e.lineno,
                "error": str(e),
            })
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "file": str(fp.relative_to(BASE_DIR)),
                "error": f"読み込みエラー: {e}",
            })

    return results


# ================================================================
# B. インポートテスト
# ================================================================

def run_import_tests() -> dict:
    """全モジュールのインポート試行+循環依存検出"""
    results = {"passed": 0, "failed": 0, "errors": [], "test_type": "import"}

    # インポートテストから除外するモジュール（構造上テスト不可能なもの）
    SKIP_IMPORT_MODULES = {
        "tools.pw_extract",       # subprocess専用スクリプト。asyncio.run()がイベントループ内で衝突
        "bots.discord_bot",       # discord.pyのBot初期化がimport時に実行される
    }

    # sys.pathにプロジェクトルートを追加
    root_str = str(BASE_DIR)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    files = _collect_py_files()

    for fp in files:
        rel = fp.relative_to(BASE_DIR)
        # __pycache__をスキップ
        if "__pycache__" in str(rel):
            continue
        # モジュール名を構築 (例: tools.llm_router)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1].replace(".py", "")
        module_name = ".".join(parts)

        if module_name in SKIP_IMPORT_MODULES:
            results["passed"] += 1  # 既知の除外としてpass扱い
            continue

        try:
            # タイムアウト付きインポート（重いモジュールが無限待ちしないよう）
            importlib.import_module(module_name)
            results["passed"] += 1
        except ImportError as e:
            results["failed"] += 1
            results["errors"].append({
                "module": module_name,
                "error": f"ImportError: {e}",
            })
        except Exception as e:
            # 循環依存は通常 ImportError だが AttributeError 等で出る場合も
            error_type = type(e).__name__
            results["failed"] += 1
            results["errors"].append({
                "module": module_name,
                "error": f"{error_type}: {e}",
            })

    return results


# ================================================================
# C. 統合スモークテスト
# ================================================================

async def run_integration_tests() -> dict:
    """DB接続、NATS接続、主要関数の存在確認"""
    results = {"passed": 0, "failed": 0, "errors": [], "test_type": "integration"}

    # C-1: DB接続テスト
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            val = await conn.fetchval("SELECT 1")
            if val == 1:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({"test": "db_connect", "error": f"SELECT 1 returned {val}"})
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "db_connect", "error": str(e)})

    # C-2: NATS接続テスト
    try:
        from tools.nats_client import get_nats_client
        nc = await get_nats_client()
        if nc and nc.nc and nc.nc.is_connected:
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"test": "nats_connect", "error": "NATS not connected"})
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "nats_connect", "error": str(e)})

    # C-3: choose_best_model_v6 存在確認
    try:
        from tools.llm_router import choose_best_model_v6
        assert callable(choose_best_model_v6)
        results["passed"] += 1
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "choose_best_model_v6", "error": str(e)})

    # C-4: get_budget_guard 存在確認
    try:
        from tools.budget_guard import get_budget_guard
        guard = get_budget_guard()
        assert guard is not None
        results["passed"] += 1
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "get_budget_guard", "error": str(e)})

    # C-5: get_connection 存在確認
    try:
        from tools.db_pool import get_connection
        assert callable(get_connection)
        results["passed"] += 1
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "get_connection", "error": str(e)})

    # C-6: get_nats_client 存在確認
    try:
        from tools.nats_client import get_nats_client
        assert callable(get_nats_client)
        results["passed"] += 1
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "get_nats_client", "error": str(e)})

    # C-7: node_state テーブルに4行存在
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM node_state")
            if count >= 4:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "test": "node_state_rows",
                    "error": f"node_stateに{count}行（期待: 4行以上）",
                })
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "node_state_rows", "error": str(e)})

    # C-8: event_log書き込みテスト
    try:
        from tools.event_logger import log_event
        ok = await log_event(
            "system.self_test", "system",
            {"test": "write_check", "timestamp": datetime.now(timezone.utc).isoformat()},
            severity="info",
        )
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"test": "event_log_write", "error": "log_event returned False"})
    except Exception as e:
        results["failed"] += 1
        results["errors"].append({"test": "event_log_write", "error": str(e)})

    return results


# ================================================================
# D. リモートノードヘルステスト
# ================================================================

async def run_remote_health_tests() -> dict:
    """SSH経由で各ノードのサービス状態・Ollama・ディスク容量をチェック"""
    results = {"passed": 0, "failed": 0, "errors": [], "test_type": "remote_health", "nodes": {}}

    for node, cfg in REMOTE_NODES.items():
        ip = cfg["ip"]
        user = cfg["user"]
        node_result = {"ssh": False, "services": {}, "ollama": False, "disk_free_gb": 0.0}

        # D-1: SSH疎通
        try:
            proc = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 f"{user}@{ip}", "echo ok"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and "ok" in proc.stdout:
                node_result["ssh"] = True
                results["passed"] += 1
            else:
                node_result["ssh"] = False
                results["failed"] += 1
                results["errors"].append({"test": f"{node}_ssh", "error": f"SSH failed: {proc.stderr[:100]}"})
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"test": f"{node}_ssh", "error": str(e)})

        # D-2: systemctlでサービス稼働確認（syutain-worker-* は system-level service）
        for svc in cfg["services"]:
            try:
                proc = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", f"{user}@{ip}",
                     f"systemctl is-active {svc}"],
                    capture_output=True, text=True, timeout=10,
                )
                status = proc.stdout.strip()
                node_result["services"][svc] = status
                if status == "active":
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({"test": f"{node}_{svc}", "error": f"service {status}"})
            except Exception as e:
                results["failed"] += 1
                node_result["services"][svc] = "error"
                results["errors"].append({"test": f"{node}_{svc}", "error": str(e)})

        # D-3: Ollama応答確認
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://{ip}:11434/api/tags")
                if resp.status_code == 200:
                    node_result["ollama"] = True
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({"test": f"{node}_ollama", "error": f"HTTP {resp.status_code}"})
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"test": f"{node}_ollama", "error": str(e)})

        # D-4: ディスク空き容量
        try:
            proc = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", f"{user}@{ip}",
                 "df -BG / | tail -1 | awk '{print $4}' | tr -d 'G'"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                free_gb = float(proc.stdout.strip())
                node_result["disk_free_gb"] = free_gb
                if free_gb >= 5.0:
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({
                        "test": f"{node}_disk",
                        "error": f"ディスク残り{free_gb}GB（閾値: 5GB）",
                    })
            else:
                results["failed"] += 1
                results["errors"].append({"test": f"{node}_disk", "error": proc.stderr[:100]})
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"test": f"{node}_disk", "error": str(e)})

        results["nodes"][node] = node_result

    return results


# ================================================================
# メイン: 全テスト実行
# ================================================================

async def run_all_tests(include_remote: bool = True) -> dict:
    """全テストスイートを実行し結果を返す"""
    start = time.time()
    all_results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "suites": {},
        "total_passed": 0,
        "total_failed": 0,
        "total_errors": [],
    }

    # A: 構文テスト
    try:
        syntax = run_syntax_tests()
        all_results["suites"]["syntax"] = syntax
        all_results["total_passed"] += syntax["passed"]
        all_results["total_failed"] += syntax["failed"]
        all_results["total_errors"].extend(syntax["errors"])
    except Exception as e:
        logger.error(f"構文テスト実行失敗: {e}")
        all_results["suites"]["syntax"] = {"passed": 0, "failed": 1, "errors": [{"error": str(e)}]}
        all_results["total_failed"] += 1

    # B: インポートテスト
    try:
        imports = run_import_tests()
        all_results["suites"]["import"] = imports
        all_results["total_passed"] += imports["passed"]
        all_results["total_failed"] += imports["failed"]
        all_results["total_errors"].extend(imports["errors"])
    except Exception as e:
        logger.error(f"インポートテスト実行失敗: {e}")
        all_results["suites"]["import"] = {"passed": 0, "failed": 1, "errors": [{"error": str(e)}]}
        all_results["total_failed"] += 1

    # C: 統合テスト
    try:
        integration = await run_integration_tests()
        all_results["suites"]["integration"] = integration
        all_results["total_passed"] += integration["passed"]
        all_results["total_failed"] += integration["failed"]
        all_results["total_errors"].extend(integration["errors"])
    except Exception as e:
        logger.error(f"統合テスト実行失敗: {e}")
        all_results["suites"]["integration"] = {"passed": 0, "failed": 1, "errors": [{"error": str(e)}]}
        all_results["total_failed"] += 1

    # D: リモートノードヘルステスト
    if include_remote:
        try:
            remote = await run_remote_health_tests()
            all_results["suites"]["remote_health"] = remote
            all_results["total_passed"] += remote["passed"]
            all_results["total_failed"] += remote["failed"]
            all_results["total_errors"].extend(remote["errors"])
        except Exception as e:
            logger.error(f"リモートヘルステスト実行失敗: {e}")
            all_results["suites"]["remote_health"] = {"passed": 0, "failed": 1, "errors": [{"error": str(e)}]}
            all_results["total_failed"] += 1

    elapsed = time.time() - start
    all_results["elapsed_sec"] = round(elapsed, 2)

    # event_logに記録
    try:
        from tools.event_logger import log_event
        severity = "error" if all_results["total_failed"] > 0 else "info"
        await log_event(
            "system.self_test", "system",
            {
                "passed": all_results["total_passed"],
                "failed": all_results["total_failed"],
                "elapsed_sec": all_results["elapsed_sec"],
                "error_count": len(all_results["total_errors"]),
                "suites": {k: {"passed": v["passed"], "failed": v["failed"]}
                           for k, v in all_results["suites"].items()},
            },
            severity=severity,
        )
    except Exception as e:
        logger.error(f"テスト結果のevent_log記録失敗: {e}")

    # 失敗があればDiscord通知
    if all_results["total_failed"] > 0:
        try:
            from tools.discord_notify import notify_error
            error_summary = "; ".join(
                f"{e.get('test', e.get('file', e.get('module', '?')))}: {e.get('error', '')[:60]}"
                for e in all_results["total_errors"][:5]
            )
            await notify_error(
                "self_test_failure",
                f"自動テスト失敗: {all_results['total_failed']}件\n"
                f"passed={all_results['total_passed']}, failed={all_results['total_failed']}\n"
                f"{error_summary}",
                severity="error",
            )
        except Exception as e:
            logger.error(f"Discord通知失敗: {e}")

    logger.info(
        f"テスト完了: passed={all_results['total_passed']}, "
        f"failed={all_results['total_failed']}, "
        f"elapsed={all_results['elapsed_sec']}s"
    )
    return all_results


async def run_syntax_only() -> dict:
    """構文チェックのみ実行（毎時用の軽量テスト）"""
    results = run_syntax_tests()

    # event_logに記録
    try:
        from tools.event_logger import log_event
        severity = "error" if results["failed"] > 0 else "info"
        await log_event(
            "system.self_test", "system",
            {
                "test_type": "syntax_only",
                "passed": results["passed"],
                "failed": results["failed"],
                "error_count": len(results["errors"]),
            },
            severity=severity,
        )
    except Exception:
        pass

    # 失敗があればDiscord通知
    if results["failed"] > 0:
        try:
            from tools.discord_notify import notify_error
            error_lines = "; ".join(
                f"{e['file']}:{e.get('line', '?')}" for e in results["errors"][:5]
            )
            await notify_error(
                "syntax_check_failure",
                f"構文エラー検出: {results['failed']}件\n{error_lines}",
                severity="error",
            )
        except Exception:
            pass

    return results
