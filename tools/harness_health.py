"""
SYUTAINβ ハーネス健全性スコア

システム全体の健全性を0-100のスコアで定量化する。
毎時計算し、経営日報・SYSTEM_STATE.mdに反映。
"""

import json
import logging
from datetime import datetime, timezone

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.harness_health")


async def calculate_health_score() -> dict:
    """Calculate overall system health as a single 0-100 score.

    Components (weighted):
    - Node availability (20%): How many nodes are healthy
    - Task success rate (20%): completed / (completed + failed) last 24h
    - SNS delivery rate (15%): posted / (posted + rejected + failed) last 24h
    - Budget utilization (10%): inverse of budget usage (100% used = 0 score)
    - Error rate (15%): inverse of error frequency
    - Quality average (10%): avg quality_score of completed tasks
    - Memory health (10%): persona_memory count, episodic_memory coverage

    Returns:
        {
            overall: int (0-100),
            components: {name: {score: int, weight: float, detail: str}},
            grade: "A"/"B"/"C"/"D"/"F",
            recommendations: [str],
            calculated_at: str
        }
    """
    components = {}
    recommendations = []

    try:
        async with get_connection() as conn:
            # --- 1. Node availability (20%) ---
            node_score, node_detail = await _calc_node_availability(conn)
            components["node_availability"] = {
                "score": node_score, "weight": 0.20, "detail": node_detail
            }
            if node_score < 50:
                recommendations.append("複数ノードがダウンしています。ノード状態を確認してください")

            # --- 2. Task success rate (20%) ---
            task_score, task_detail = await _calc_task_success_rate(conn)
            components["task_success_rate"] = {
                "score": task_score, "weight": 0.20, "detail": task_detail
            }
            if task_score < 60:
                recommendations.append("タスク成功率が低下しています。failure_memoryを確認してください")

            # --- 3. SNS delivery rate (15%) ---
            sns_score, sns_detail = await _calc_sns_delivery_rate(conn)
            components["sns_delivery_rate"] = {
                "score": sns_score, "weight": 0.15, "detail": sns_detail
            }
            if sns_score < 50:
                recommendations.append("SNS投稿の配信率が低下しています。posting_queueを確認してください")

            # --- 4. Budget utilization (10%) ---
            budget_score, budget_detail = await _calc_budget_utilization(conn)
            components["budget_utilization"] = {
                "score": budget_score, "weight": 0.10, "detail": budget_detail
            }
            if budget_score < 30:
                recommendations.append("API予算の消費が激しいです。コスト最適化を検討してください")

            # --- 5. Error rate (15%) ---
            error_score, error_detail = await _calc_error_rate(conn)
            components["error_rate"] = {
                "score": error_score, "weight": 0.15, "detail": error_detail
            }
            if error_score < 50:
                recommendations.append("エラー頻度が高いです。event_logのerror/criticalを確認してください")

            # --- 6. Quality average (10%) ---
            quality_score, quality_detail = await _calc_quality_average(conn)
            components["quality_average"] = {
                "score": quality_score, "weight": 0.10, "detail": quality_detail
            }
            if quality_score < 50:
                recommendations.append("タスク品質スコアが低下しています。2段階精錬の適用率を確認してください")

            # --- 7. Memory health (10%) ---
            memory_score, memory_detail = await _calc_memory_health(conn)
            components["memory_health"] = {
                "score": memory_score, "weight": 0.10, "detail": memory_detail
            }
            if memory_score < 40:
                recommendations.append("記憶システムの状態を確認してください。persona_memory/episodic_memoryが不足しています")

    except Exception as e:
        logger.error(f"健全性スコア計算エラー: {e}")
        return {
            "overall": 0,
            "components": {},
            "grade": "F",
            "recommendations": [f"計算エラー: {str(e)[:100]}"],
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }

    # 加重平均で総合スコア算出
    overall = 0.0
    for comp in components.values():
        overall += comp["score"] * comp["weight"]
    overall = round(overall)

    # グレード判定
    if overall >= 90:
        grade = "A"
    elif overall >= 75:
        grade = "B"
    elif overall >= 55:
        grade = "C"
    elif overall >= 35:
        grade = "D"
    else:
        grade = "F"

    if not recommendations:
        recommendations.append("全コンポーネント正常。特筆事項なし")

    result = {
        "overall": overall,
        "components": components,
        "grade": grade,
        "recommendations": recommendations,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"ハーネス健全性スコア: {overall}/100 (Grade {grade})")
    return result


# ============================================================
# 各コンポーネントの算出
# ============================================================

async def _calc_node_availability(conn) -> tuple[int, str]:
    """ノード可用性スコア"""
    try:
        rows = await conn.fetch(
            """SELECT node_name, state FROM node_state"""
        )
        if not rows:
            # node_stateがない場合、event_logのハートビートで推定
            recent = await conn.fetchval(
                """SELECT COUNT(DISTINCT source_node) FROM event_log
                   WHERE event_type LIKE 'heartbeat%'
                     AND created_at > NOW() - INTERVAL '5 minutes'"""
            ) or 0
            score = min(int((recent / 4) * 100), 100)
            return score, f"ハートビート検出ノード: {recent}/4"

        total = len(rows)
        healthy = sum(1 for r in rows if r["state"] in ("healthy", "active"))
        score = int((healthy / max(total, 1)) * 100)
        return score, f"正常ノード: {healthy}/{total}"
    except Exception:
        return 50, "ノード状態取得不可（デフォルト50）"


async def _calc_task_success_rate(conn) -> tuple[int, str]:
    """タスク成功率スコア"""
    try:
        row = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                 COUNT(*) FILTER (WHERE status = 'failed') AS failed
               FROM tasks
               WHERE updated_at > NOW() - INTERVAL '24 hours'"""
        )
        completed = row["completed"] or 0
        failed = row["failed"] or 0
        total = completed + failed
        if total == 0:
            return 80, "24h以内のタスクなし（デフォルト80）"
        rate = completed / total
        score = int(rate * 100)
        return score, f"成功{completed}/失敗{failed} (率{rate:.0%})"
    except Exception:
        return 50, "タスク成功率取得不可"


async def _calc_sns_delivery_rate(conn) -> tuple[int, str]:
    """SNS配信率スコア"""
    try:
        row = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status = 'posted') AS posted,
                 COUNT(*) FILTER (WHERE status IN ('failed', 'rejected')) AS failed
               FROM posting_queue
               WHERE created_at > NOW() - INTERVAL '24 hours'"""
        )
        posted = row["posted"] or 0
        failed = row["failed"] or 0
        total = posted + failed
        if total == 0:
            return 80, "24h以内のSNS投稿なし（デフォルト80）"
        rate = posted / total
        score = int(rate * 100)
        return score, f"投稿{posted}/失敗{failed} (率{rate:.0%})"
    except Exception:
        return 50, "SNS配信率取得不可"


async def _calc_budget_utilization(conn) -> tuple[int, str]:
    """予算消費スコア（少ないほどスコア高）"""
    try:
        import os
        daily_budget = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))

        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(amount_jpy), 0) AS total
               FROM llm_cost_log
               WHERE recorded_at::date = CURRENT_DATE"""
        )
        spent = float(row["total"]) if row else 0.0
        usage_rate = spent / max(daily_budget, 1)
        # 100%消費 = 0点, 0%消費 = 100点
        score = max(0, int((1 - usage_rate) * 100))
        return score, f"本日API支出: ¥{spent:.1f}/¥{daily_budget:.0f} ({usage_rate:.0%})"
    except Exception:
        return 50, "予算情報取得不可"


async def _calc_error_rate(conn) -> tuple[int, str]:
    """エラー頻度スコア（少ないほどスコア高）"""
    try:
        row = await conn.fetchrow(
            """SELECT
                 COUNT(*) AS total,
                 COUNT(*) FILTER (WHERE severity IN ('error', 'critical')) AS errors
               FROM event_log
               WHERE created_at > NOW() - INTERVAL '24 hours'"""
        )
        total = row["total"] or 0
        errors = row["errors"] or 0
        if total == 0:
            return 90, "24h以内のイベントなし（デフォルト90）"
        error_rate = errors / total
        # エラー率10%以上で急速に悪化
        score = max(0, int((1 - min(error_rate * 5, 1.0)) * 100))
        return score, f"エラー{errors}/{total}件 (率{error_rate:.1%})"
    except Exception:
        return 50, "エラー率取得不可"


async def _calc_quality_average(conn) -> tuple[int, str]:
    """品質スコア平均"""
    try:
        row = await conn.fetchrow(
            """SELECT AVG(quality_score) AS avg_q, COUNT(*) AS cnt
               FROM tasks
               WHERE quality_score IS NOT NULL
                 AND updated_at > NOW() - INTERVAL '24 hours'"""
        )
        avg_q = float(row["avg_q"]) if row and row["avg_q"] else 0.0
        cnt = row["cnt"] or 0
        if cnt == 0:
            return 70, "24h以内の品質スコアなし（デフォルト70）"
        score = int(avg_q * 100)
        return score, f"平均品質: {avg_q:.2f} ({cnt}件)"
    except Exception:
        return 50, "品質スコア取得不可"


async def _calc_memory_health(conn) -> tuple[int, str]:
    """記憶システム健全性"""
    try:
        persona_count = await conn.fetchval(
            "SELECT COUNT(*) FROM persona_memory"
        ) or 0
        episodic_count = await conn.fetchval(
            "SELECT COUNT(*) FROM episodic_memory"
        ) or 0
        session_count = await conn.fetchval(
            "SELECT COUNT(*) FROM brain_alpha_session"
        ) or 0

        # persona_memory: 10件以上で満点
        persona_score = min(persona_count / 10, 1.0) * 40
        # episodic_memory: 20件以上で満点
        episodic_score = min(episodic_count / 20, 1.0) * 30
        # session: 5件以上で満点
        session_score = min(session_count / 5, 1.0) * 30

        score = int(persona_score + episodic_score + session_score)
        detail = f"persona={persona_count}, episodic={episodic_count}, session={session_count}"
        return score, detail
    except Exception:
        return 50, "記憶システム状態取得不可"
