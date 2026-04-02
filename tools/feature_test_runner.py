"""
SYUTAINβ V25 Feature Test Runner (Harness Engineering)
フィーチャーリスト管理 + 動作検証

設計上の機能と実際の動作状態の乖離を検出・追跡する。
"""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.feature_test_runner")

FEATURE_FILE = Path(__file__).resolve().parent.parent / "data" / "feature_tests.json"


def _load_features() -> dict:
    """feature_tests.jsonを読み込む"""
    if not FEATURE_FILE.exists():
        return {"version": "v25", "features": []}
    with open(FEATURE_FILE) as f:
        return json.load(f)


def _save_features(data: dict):
    """feature_tests.jsonを保存"""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(FEATURE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def run_feature_tests() -> dict:
    """全フィーチャーテストを実行"""
    data = _load_features()
    results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": 0,
        "passing": 0,
        "failing": 0,
        "unknown": 0,
        "changed": [],
    }

    for feature in data["features"]:
        results["total"] += 1
        old_status = feature["status"]
        new_status = await _test_feature(feature)
        now = datetime.now(timezone.utc).isoformat()

        if new_status != old_status and new_status != "unknown":
            results["changed"].append({
                "id": feature["id"],
                "from": old_status,
                "to": new_status,
            })
            feature["status"] = new_status

        feature["last_verified"] = now

        if feature["status"] == "passing":
            results["passing"] += 1
        elif feature["status"] == "failing":
            results["failing"] += 1
        else:
            results["unknown"] += 1

    _save_features(data)

    # 変更があればイベントログに記録
    if results["changed"]:
        try:
            from tools.event_logger import log_event
            await log_event("feature_test.status_changed", "system", {
                "changed": results["changed"],
                "summary": f"passing={results['passing']}, failing={results['failing']}",
            }, severity="warning" if any(c["to"] == "failing" for c in results["changed"]) else "info")
        except Exception:
            pass

    return results


async def _test_feature(feature: dict) -> str:
    """個別フィーチャーのテスト"""
    fid = feature["id"]

    # URLベース検証
    if "verify_url" in feature:
        return _test_url(feature["verify_url"])

    # DB接続検証
    if feature.get("verify_method") == "db_connect":
        return await _test_db_connection()

    # ノード状態検証
    if fid.startswith("node_") and fid.endswith("_healthy"):
        node = fid.replace("node_", "").replace("_healthy", "")
        return await _test_node_health(node)

    # Phase 2機能（テストスキップ）
    if feature.get("reason", "").startswith("Phase 2"):
        return "failing"  # 意図的にfailing

    # それ以外は現在のステータスを維持
    return feature.get("status", "unknown")


def _test_url(url: str) -> str:
    """HTTP GETで200が返るか"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=10,
        )
        return "passing" if result.stdout.strip() == "200" else "failing"
    except Exception:
        return "failing"


async def _test_db_connection() -> str:
    """PostgreSQL接続テスト"""
    try:
        async with get_connection() as conn:
            val = await conn.fetchval("SELECT 1")
            return "passing" if val == 1 else "failing"
    except Exception:
        return "failing"


async def _test_node_health(node: str) -> str:
    """ノードの健全性チェック"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM node_state WHERE node_name = $1", node
            )
            if row and row["state"] == "healthy":
                return "passing"
            return "failing"
    except Exception:
        return "unknown"


def get_feature_summary() -> dict:
    """フィーチャーテスト結果のサマリー"""
    data = _load_features()
    summary = {"passing": 0, "failing": 0, "unknown": 0, "total": 0}
    by_category = {}

    for f in data["features"]:
        summary["total"] += 1
        summary[f["status"]] = summary.get(f["status"], 0) + 1
        cat = f.get("category", "other")
        if cat not in by_category:
            by_category[cat] = {"passing": 0, "failing": 0, "unknown": 0}
        by_category[cat][f["status"]] = by_category[cat].get(f["status"], 0) + 1

    summary["by_category"] = by_category
    summary["failing_features"] = [
        {"id": f["id"], "reason": f.get("reason", "")}
        for f in data["features"]
        if f["status"] == "failing"
    ]
    return summary
