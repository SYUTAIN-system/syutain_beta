"""
SYUTAINβ Brain-α セッション開始時精査サイクル
設計書 Section 5 準拠

セッション開始時に以下を収集・分析し、精査レポートを生成する:
Phase 1: 前回セッション記憶復元
Phase 2: Daichiの最新思考参照
Phase 3: 情報収集精査
Phase 4: 成果物精査
Phase 5: タスク結果検証（品質推移）
Phase 6: エラー自律修復候補
Phase 7: 収益・エンゲージメント分析
Phase 8: レポート保存 + Discord投稿

LLM呼び出しなし。PostgreSQLクエリのみ。
"""

import json
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.startup_review")

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"


async def run_startup_review() -> dict:
    """精査サイクル全8フェーズを実行し、レポートを返す"""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phases": {},
        "summary": "",
        "recommended_actions": [],
        "warnings": [],
    }

    async with get_connection() as conn:
        try:
            # Phase 1: 前回セッション記憶復元
            report["phases"]["1_session_restore"] = await _phase1_session(conn)

            # Phase 2: Daichiの最新思考
            report["phases"]["2_daichi_thoughts"] = await _phase2_daichi(conn)

            # Phase 3: 情報収集精査
            report["phases"]["3_intel_review"] = await _phase3_intel(conn)

            # Phase 4: 成果物精査
            report["phases"]["4_artifacts"] = await _phase4_artifacts(conn)

            # Phase 5: 品質推移
            report["phases"]["5_quality_trend"] = await _phase5_quality(conn)

            # Phase 6: エラー分析
            report["phases"]["6_errors"] = await _phase6_errors(conn)

            # Phase 7: 収益
            report["phases"]["7_revenue"] = await _phase7_revenue(conn)

            # Phase 8: トレース警告 + キュー確認
            report["phases"]["8_trace_queue"] = await _phase8_trace_queue(conn)

            # サマリー・推奨アクション生成
            _build_summary(report)

            # レポートをDBに保存
            await _save_report(conn, report)

        except Exception as e:
            logger.error(f"精査サイクル例外: {e}")
            report["summary"] = f"精査中にエラー: {e}"

    return report


# ===== Phase 1: 前回セッション記憶復元 =====

async def _phase1_session(conn) -> dict:
    try:
        row = await conn.fetchrow(
            """SELECT session_id, started_at, ended_at, summary,
                      key_decisions, unresolved_issues, daichi_interactions
               FROM brain_alpha_session
               ORDER BY created_at DESC LIMIT 1"""
        )
        if row:
            return {
                "status": "restored",
                "session_id": row["session_id"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "ended_at": row["ended_at"].isoformat() if row["ended_at"] else None,
                "summary": row["summary"],
                "unresolved_issues": json.loads(row["unresolved_issues"]) if row["unresolved_issues"] else [],
                "daichi_interactions": row["daichi_interactions"] or 0,
            }
        return {"status": "no_previous_session"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===== Phase 2: Daichiの最新思考 =====

async def _phase2_daichi(conn) -> dict:
    try:
        rows = await conn.fetch(
            """SELECT channel, daichi_message, extracted_philosophy, created_at
               FROM daichi_dialogue_log
               ORDER BY created_at DESC LIMIT 5"""
        )
        entries = []
        for r in rows:
            entries.append({
                "channel": r["channel"],
                "message": (r["daichi_message"] or "")[:200],
                "philosophy": json.loads(r["extracted_philosophy"]) if r["extracted_philosophy"] else None,
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            })
        return {"count": len(entries), "entries": entries}
    except Exception as e:
        return {"count": 0, "error": str(e)}


# ===== Phase 3: 情報収集精査 =====

async def _phase3_intel(conn) -> dict:
    try:
        stats = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as new_24h,
                 COUNT(*) FILTER (WHERE importance_score >= 0.7 AND created_at > NOW() - INTERVAL '24 hours') as important_24h,
                 COUNT(*) FILTER (WHERE review_flag = 'pending_review') as pending_review,
                 AVG(importance_score) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as avg_importance
               FROM intel_items"""
        )
        top_items = await conn.fetch(
            """SELECT id, source, title, importance_score, category
               FROM intel_items
               WHERE created_at > NOW() - INTERVAL '24 hours'
               ORDER BY importance_score DESC LIMIT 5"""
        )
        return {
            "new_24h": stats["new_24h"] or 0,
            "important_24h": stats["important_24h"] or 0,
            "pending_review": stats["pending_review"] or 0,
            "avg_importance": round(float(stats["avg_importance"] or 0), 3),
            "top_items": [
                {"id": r["id"], "source": r["source"], "title": r["title"][:80],
                 "score": float(r["importance_score"] or 0), "category": r["category"]}
                for r in top_items
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# ===== Phase 4: 成果物精査 =====

async def _phase4_artifacts(conn) -> dict:
    try:
        # ファイルシステムの成果物
        recent_files = []
        if ARTIFACTS_DIR.exists():
            cutoff = datetime.now().timestamp() - 86400
            for f in sorted(ARTIFACTS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.stat().st_mtime > cutoff:
                    recent_files.append(f.name)
                if len(recent_files) >= 10:
                    break

        # DBの成果物統計
        row = await conn.fetchrow(
            """SELECT COUNT(*) as total,
                      COUNT(*) FILTER (WHERE quality_score >= 0.65) as high_quality,
                      COUNT(*) FILTER (WHERE quality_score < 0.5 AND quality_score > 0) as low_quality
               FROM tasks
               WHERE status IN ('completed', 'success')
                 AND created_at > NOW() - INTERVAL '24 hours'"""
        )
        result = {
            "recent_files": recent_files,
            "file_count_24h": len(recent_files),
            "tasks_completed_24h": row["total"] or 0,
            "high_quality": row["high_quality"] or 0,
            "low_quality": row["low_quality"] or 0,
        }

        # review_logに精査結果を記録
        await conn.execute(
            """INSERT INTO review_log
               (reviewer, target_type, target_id, verdict, issues_found, quality_before, quality_after)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            "brain_alpha",
            "phase4_artifacts",
            f"startup_review_{datetime.now().strftime('%Y%m%d_%H%M')}",
            "reviewed" if row["low_quality"] == 0 else "issues_found",
            json.dumps({"low_quality_count": row["low_quality"] or 0}, ensure_ascii=False),
            None,
            None,
        )

        return result
    except Exception as e:
        return {"error": str(e)}


# ===== Phase 5: 品質推移 =====

async def _phase5_quality(conn) -> dict:
    try:
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
        trend = "improving" if tw_avg > lw_avg + 0.02 else "declining" if tw_avg < lw_avg - 0.02 else "stable"
        return {
            "this_week_avg": round(tw_avg, 3),
            "this_week_count": this_week["cnt"] or 0,
            "last_week_avg": round(lw_avg, 3),
            "last_week_count": last_week["cnt"] or 0,
            "trend": trend,
            "delta": round(tw_avg - lw_avg, 3),
        }
    except Exception as e:
        return {"error": str(e)}


# ===== Phase 6: エラー分析 =====

async def _phase6_errors(conn) -> dict:
    try:
        errors = await conn.fetch(
            """SELECT event_type, payload->>'error' as error, source_node, created_at
               FROM event_log
               WHERE severity IN ('error', 'critical')
                 AND created_at > NOW() - INTERVAL '24 hours'
               ORDER BY created_at DESC LIMIT 15"""
        )
        # 再発パターン検出
        pattern_counts = {}
        for r in errors:
            key = r["event_type"]
            pattern_counts[key] = pattern_counts.get(key, 0) + 1

        recurring = [{"event_type": k, "count": v} for k, v in pattern_counts.items() if v >= 2]
        recurring.sort(key=lambda x: x["count"], reverse=True)

        return {
            "total_24h": len(errors),
            "recurring_patterns": recurring,
            "recent": [
                {"event_type": r["event_type"], "error": (r["error"] or "")[:100],
                 "node": r["source_node"], "at": r["created_at"].isoformat() if r["created_at"] else None}
                for r in errors[:5]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# ===== Phase 7: 収益 =====

async def _phase7_revenue(conn) -> dict:
    try:
        row = await conn.fetchrow(
            """SELECT COUNT(*) as total, COALESCE(SUM(revenue_jpy), 0) as total_jpy
               FROM revenue_linkage
               WHERE created_at > NOW() - INTERVAL '7 days'"""
        )
        # SNS投稿統計
        sns = await conn.fetchrow(
            """SELECT COUNT(*) as total,
                      COUNT(*) FILTER (WHERE payload->>'platform' = 'bluesky') as bluesky,
                      COUNT(*) FILTER (WHERE payload->>'platform' = 'x') as x,
                      COUNT(*) FILTER (WHERE payload->>'platform' = 'threads') as threads
               FROM event_log
               WHERE event_type = 'sns.posted'
                 AND created_at > NOW() - INTERVAL '7 days'"""
        )
        return {
            "revenue_7d_jpy": int(row["total_jpy"]),
            "revenue_records": row["total"] or 0,
            "sns_posts_7d": {
                "total": sns["total"] or 0,
                "bluesky": sns["bluesky"] or 0,
                "x": sns["x"] or 0,
                "threads": sns["threads"] or 0,
            },
        }
    except Exception as e:
        return {"error": str(e)}


# ===== Phase 8: トレース警告 + キュー確認 =====

async def _phase8_trace_queue(conn) -> dict:
    try:
        # 低confidence警告
        low_conf = await conn.fetch(
            """SELECT agent_name, action, reasoning, confidence, created_at
               FROM agent_reasoning_trace
               WHERE confidence < 0.5 AND confidence IS NOT NULL
                 AND created_at > NOW() - INTERVAL '24 hours'
               ORDER BY confidence ASC LIMIT 10"""
        )
        # claude_code_queue未処理
        queue = await conn.fetch(
            """SELECT id, priority, category, description, auto_solvable
               FROM claude_code_queue
               WHERE status = 'pending'
               ORDER BY
                 CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 created_at ASC
               LIMIT 10"""
        )
        return {
            "low_confidence_traces": [
                {"agent": r["agent_name"], "action": r["action"],
                 "reasoning": (r["reasoning"] or "")[:100], "confidence": float(r["confidence"])}
                for r in low_conf
            ],
            "pending_queue": [
                {"id": r["id"], "priority": r["priority"], "category": r["category"],
                 "description": r["description"][:100], "auto_solvable": r["auto_solvable"]}
                for r in queue
            ],
            "pending_count": len(queue),
        }
    except Exception as e:
        return {"error": str(e)}


# ===== サマリー・推奨アクション生成 =====

def _build_summary(report: dict):
    """フェーズ結果からサマリーと推奨アクションを構築"""
    actions = []
    warnings = []

    # Phase 3: 未精査intel
    intel = report["phases"].get("3_intel_review", {})
    pending = intel.get("pending_review", 0)
    if pending > 20:
        actions.append(f"intel_items {pending}件が未精査。重要度0.7+を優先確認")
    important = intel.get("important_24h", 0)
    if important > 0:
        actions.append(f"重要情報 {important}件を検出（24h）。提案・戦略への反映を検討")

    # Phase 5: 品質
    quality = report["phases"].get("5_quality_trend", {})
    if quality.get("trend") == "declining":
        warnings.append(f"品質スコア低下傾向: {quality.get('last_week_avg', 0):.2f} → {quality.get('this_week_avg', 0):.2f}")
        actions.append("品質低下の原因調査。モデル選択・プロンプト改善を検討")

    # Phase 6: エラー
    errors = report["phases"].get("6_errors", {})
    if errors.get("total_24h", 0) > 5:
        warnings.append(f"24hエラー {errors['total_24h']}件。再発パターン確認")
    for pat in errors.get("recurring_patterns", []):
        if pat["count"] >= 3:
            actions.append(f"再発エラー: {pat['event_type']} ({pat['count']}回) → 根本原因修正")

    # Phase 8: キュー
    queue = report["phases"].get("8_trace_queue", {})
    if queue.get("pending_count", 0) > 0:
        actions.append(f"Brain-αキュー {queue['pending_count']}件未処理。auto_solvable優先で消化")
    low_conf = queue.get("low_confidence_traces", [])
    if low_conf:
        warnings.append(f"低confidence判断 {len(low_conf)}件（24h）。判断根拠の見直しを推奨")

    # Phase 1: 未解決課題
    session = report["phases"].get("1_session_restore", {})
    unresolved = session.get("unresolved_issues", [])
    if unresolved:
        actions.append(f"前回セッション未解決: {len(unresolved)}件")

    report["recommended_actions"] = actions[:5]
    report["warnings"] = warnings

    # サマリー生成
    parts = []
    parts.append(f"精査完了 ({datetime.now().strftime('%H:%M')})")
    if intel.get("new_24h"):
        parts.append(f"情報{intel['new_24h']}件")
    if quality.get("this_week_avg"):
        parts.append(f"品質{quality['this_week_avg']:.2f}")
    if errors.get("total_24h"):
        parts.append(f"エラー{errors['total_24h']}件")
    if queue.get("pending_count"):
        parts.append(f"キュー{queue['pending_count']}件")
    report["summary"] = " / ".join(parts)


# ===== DB保存 =====

async def _save_report(conn, report: dict):
    """精査レポートをbrain_alpha_reasoningに保存"""
    try:
        await conn.execute(
            """INSERT INTO brain_alpha_reasoning
               (category, trigger_source, reasoning, decision, confidence, evidence)
               VALUES ('startup_review', 'session_start', $1, $2, 0.9, $3)""",
            report.get("summary", ""),
            json.dumps(report.get("recommended_actions", []), ensure_ascii=False),
            json.dumps(report, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.error(f"精査レポート保存失敗: {e}")


# ===== Discord投稿用Markdown生成 =====

def format_discord_report(report: dict) -> str:
    """精査レポートをDiscord投稿用Markdownに変換"""
    lines = []
    lines.append(f"## Brain-α 精査レポート")
    lines.append(f"**{report.get('summary', '')}**\n")

    # 警告
    for w in report.get("warnings", []):
        lines.append(f"- {w}")
    if report.get("warnings"):
        lines.append("")

    # 推奨アクション
    if report.get("recommended_actions"):
        lines.append("### 推奨アクション")
        for i, a in enumerate(report["recommended_actions"], 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    # Phase概要
    phases = report.get("phases", {})

    # 品質
    q = phases.get("5_quality_trend", {})
    if q.get("this_week_avg"):
        trend_emoji = {"improving": "+", "declining": "-", "stable": "="}
        lines.append(f"**品質**: {q['this_week_avg']:.2f} ({trend_emoji.get(q.get('trend', ''), '?')}{abs(q.get('delta', 0)):.2f}) / {q.get('this_week_count', 0)}件")

    # エラー
    e = phases.get("6_errors", {})
    if e.get("total_24h"):
        recurring = ", ".join(f"{p['event_type']}x{p['count']}" for p in e.get("recurring_patterns", [])[:3])
        lines.append(f"**エラー**: {e['total_24h']}件 {'(再発: ' + recurring + ')' if recurring else ''}")

    # SNS
    r = phases.get("7_revenue", {})
    sns = r.get("sns_posts_7d", {})
    if sns.get("total"):
        lines.append(f"**SNS 7d**: {sns['total']}件 (BS:{sns.get('bluesky',0)} X:{sns.get('x',0)} TH:{sns.get('threads',0)})")

    lines.append(f"\n`{report.get('generated_at', '')[:19]}`")
    return "\n".join(lines)


# ===== CLI実行 =====

async def main():
    """CLIから直接実行"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    report = await run_startup_review()

    # Discord投稿
    discord_md = format_discord_report(report)
    print(discord_md)
    print("\n---")

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.discord_notify import notify_discord
        await notify_discord(discord_md)
        print("Discord投稿完了")
    except Exception as e:
        print(f"Discord投稿失敗: {e}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
