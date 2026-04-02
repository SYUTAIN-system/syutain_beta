"""
SYUTAINβ V25 Garbage Collector Agent (Harness Engineering)
AI Slop対策 + 低品質成果物クリーンアップ

週次で成果物・投稿キュー・ドキュメントを走査し、
品質劣化を検出・クリーンアップ提案を生成する。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.garbage_collector")

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"

# 品質閾値
LOW_QUALITY_THRESHOLD = 0.40
STALE_INTEL_DAYS = 14
MAX_PENDING_POSTS_PER_DAY = 60


async def run_garbage_collection() -> dict:
    """
    ゴミ収集メインループ。

    1. 低品質成果物の検出
    2. 古いintel_itemsの処理済みマーク
    3. rejected投稿の過剰蓄積チェック
    4. 品質トレンド劣化検出
    5. 重複コンテンツ検出

    Returns: 収集結果レポート
    """
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "findings": [],
        "actions_taken": [],
        "stats": {},
    }

    try:
        async with get_connection() as conn:
            # 1. 低品質タスク成果物の検出
            await _check_low_quality_tasks(conn, report)

            # 2. 古いintel_items
            await _check_stale_intel(conn, report)

            # 3. rejected投稿の過剰蓄積
            await _check_rejected_posts(conn, report)

            # 4. 品質トレンド劣化検出
            await _check_quality_trend(conn, report)

            # 5. 重複コンテンツ検出
            await _check_duplicate_content(conn, report)

            # 6. 古いファイル成果物
            _check_stale_artifacts(report)

            # レポート保存
            await _save_report(conn, report)

    except Exception as e:
        logger.error(f"ゴミ収集例外: {e}")
        report["error"] = str(e)

    return report


async def _check_low_quality_tasks(conn, report: dict):
    """品質スコア0.4未満のタスク成果物を検出"""
    rows = await conn.fetch(
        """SELECT id, type, quality_score, assigned_node, created_at
           FROM tasks
           WHERE quality_score IS NOT NULL AND quality_score < $1 AND quality_score > 0
             AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY quality_score ASC LIMIT 20""",
        LOW_QUALITY_THRESHOLD,
    )
    if rows:
        report["findings"].append({
            "type": "low_quality_tasks",
            "count": len(rows),
            "items": [
                {"id": r["id"], "type": r["type"], "score": round(r["quality_score"], 3),
                 "node": r["assigned_node"]}
                for r in rows
            ],
        })
    report["stats"]["low_quality_tasks_7d"] = len(rows)


async def _check_stale_intel(conn, report: dict):
    """14日以上未処理のintel_itemsを検出・処理済みマーク"""
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM intel_items
           WHERE processed = false
             AND created_at < NOW() - INTERVAL '$1 days'""".replace("$1", str(STALE_INTEL_DAYS))
    )
    if count and count > 50:
        # 古すぎるものは自動で処理済みマーク
        updated = await conn.execute(
            f"""UPDATE intel_items SET processed = true
               WHERE processed = false
                 AND created_at < NOW() - INTERVAL '{STALE_INTEL_DAYS} days'
                 AND importance_score < 0.5"""
        )
        marked = int(updated.split()[-1]) if updated else 0
        report["actions_taken"].append({
            "action": "stale_intel_marked_processed",
            "count": marked,
            "criteria": f"{STALE_INTEL_DAYS}日超過 + importance < 0.5",
        })
    report["stats"]["stale_intel_count"] = count or 0


async def _check_rejected_posts(conn, report: dict):
    """rejected投稿の蓄積チェック"""
    rejected = await conn.fetch(
        """SELECT platform, COUNT(*) as cnt
           FROM posting_queue
           WHERE status = 'rejected'
             AND scheduled_at > NOW() - INTERVAL '7 days'
           GROUP BY platform"""
    )
    total_rejected = sum(r["cnt"] for r in rejected)
    total_all = await conn.fetchval(
        """SELECT COUNT(*) FROM posting_queue
           WHERE scheduled_at > NOW() - INTERVAL '7 days'"""
    )
    reject_rate = total_rejected / max(total_all or 1, 1)

    if reject_rate > 0.50:
        report["findings"].append({
            "type": "high_reject_rate",
            "reject_rate": round(reject_rate, 2),
            "total_rejected": total_rejected,
            "total_posts": total_all,
            "by_platform": {r["platform"]: r["cnt"] for r in rejected},
            "recommendation": "SNSバッチ生成の品質パラメータ調整が必要",
        })
    report["stats"]["reject_rate_7d"] = round(reject_rate, 3)
    report["stats"]["total_rejected_7d"] = total_rejected


async def _check_quality_trend(conn, report: dict):
    """品質トレンドの劣化検出"""
    this_week = await conn.fetchrow(
        """SELECT AVG(quality_score) as avg, COUNT(*) as cnt
           FROM tasks
           WHERE quality_score IS NOT NULL AND quality_score > 0
             AND created_at > NOW() - INTERVAL '7 days'"""
    )
    last_week = await conn.fetchrow(
        """SELECT AVG(quality_score) as avg, COUNT(*) as cnt
           FROM tasks
           WHERE quality_score IS NOT NULL AND quality_score > 0
             AND created_at > NOW() - INTERVAL '14 days'
             AND created_at <= NOW() - INTERVAL '7 days'"""
    )

    tw_avg = float(this_week["avg"] or 0)
    lw_avg = float(last_week["avg"] or 0)

    if lw_avg > 0 and tw_avg < lw_avg - 0.05:
        report["findings"].append({
            "type": "quality_declining",
            "this_week": round(tw_avg, 3),
            "last_week": round(lw_avg, 3),
            "delta": round(tw_avg - lw_avg, 3),
            "recommendation": "モデル選択・プロンプト・2段階精錬パイプラインの見直し推奨",
        })
    report["stats"]["quality_this_week"] = round(tw_avg, 3)
    report["stats"]["quality_last_week"] = round(lw_avg, 3)


async def _check_duplicate_content(conn, report: dict):
    """投稿キュー内の重複コンテンツ検出"""
    dupes = await conn.fetch(
        """SELECT content, COUNT(*) as cnt, array_agg(id) as ids
           FROM posting_queue
           WHERE scheduled_at > NOW() - INTERVAL '7 days'
             AND content IS NOT NULL AND LENGTH(content) > 20
           GROUP BY content
           HAVING COUNT(*) > 1
           ORDER BY cnt DESC LIMIT 10"""
    )
    if dupes:
        report["findings"].append({
            "type": "duplicate_content",
            "count": len(dupes),
            "items": [
                {"content_preview": r["content"][:80], "duplicates": r["cnt"], "ids": r["ids"][:5]}
                for r in dupes
            ],
        })
    report["stats"]["duplicate_posts_7d"] = len(dupes)


def _check_stale_artifacts(report: dict):
    """30日以上前のファイル成果物を検出"""
    if not ARTIFACTS_DIR.exists():
        return

    stale_count = 0
    cutoff = datetime.now().timestamp() - (30 * 86400)
    for f in ARTIFACTS_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            stale_count += 1

    if stale_count > 50:
        report["findings"].append({
            "type": "stale_artifacts",
            "count": stale_count,
            "directory": str(ARTIFACTS_DIR),
            "recommendation": "30日超過の成果物ファイルのアーカイブまたは削除を検討",
        })
    report["stats"]["stale_artifact_files"] = stale_count


async def _save_report(conn, report: dict):
    """ゴミ収集レポートをevent_logに保存"""
    try:
        from tools.event_logger import log_event
        await log_event(
            "garbage_collection.completed", "system",
            {
                "findings_count": len(report.get("findings", [])),
                "actions_count": len(report.get("actions_taken", [])),
                "stats": report.get("stats", {}),
            },
            severity="info",
        )
    except Exception as e:
        logger.error(f"ゴミ収集レポート保存失敗: {e}")


def format_gc_report(report: dict) -> str:
    """Discord投稿用Markdown"""
    lines = ["## Garbage Collection Report"]
    lines.append(f"実行: {report.get('run_at', '')[:19]}")

    stats = report.get("stats", {})
    if stats:
        lines.append(f"\n**統計**: 低品質タスク={stats.get('low_quality_tasks_7d', 0)} / "
                      f"reject率={stats.get('reject_rate_7d', 0):.1%} / "
                      f"品質={stats.get('quality_this_week', 0):.2f}")

    findings = report.get("findings", [])
    if findings:
        lines.append(f"\n### 検出事項 ({len(findings)}件)")
        for f in findings:
            lines.append(f"- **{f['type']}**: {f.get('recommendation', json.dumps(f, ensure_ascii=False)[:100])}")

    actions = report.get("actions_taken", [])
    if actions:
        lines.append(f"\n### 自動アクション ({len(actions)}件)")
        for a in actions:
            lines.append(f"- {a['action']}: {a.get('count', '')}件")

    if not findings and not actions:
        lines.append("\n問題なし。")

    return "\n".join(lines)
