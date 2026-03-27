"""
SYUTAINβ 経営日報 — 毎朝07:05 JSTにHaiku 1回で生成→Discord送信

コストガード: 日1回のみ、max_tokens=800、月¥60上限
"""

import json
import logging
from datetime import date, datetime, timezone

from tools.db_pool import get_connection
from tools.discord_notify import notify_discord
from tools.llm_router import choose_best_model_v6, call_llm

logger = logging.getLogger("syutain.executive_briefing")

# 月次コスト上限
MONTHLY_COST_LIMIT_JPY = 60.0


async def generate_executive_briefing() -> dict:
    """経営日報を生成してDiscordに送信"""

    # コストガード: 今日既に生成済みか確認
    try:
        async with get_connection() as conn:
            already = await conn.fetchval("""
                SELECT COUNT(*) FROM event_log
                WHERE event_type = 'briefing.generated'
                AND created_at > CURRENT_DATE
            """)
            if already and already > 0:
                logger.info("本日の経営日報は既に生成済み")
                return {"status": "already_generated"}

            # 月次コスト確認
            monthly_cost = await conn.fetchval("""
                SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log
                WHERE model LIKE '%haiku%'
                AND recorded_at > date_trunc('month', CURRENT_DATE)
                AND goal_id = 'executive_briefing'
            """) or 0.0
            if float(monthly_cost) >= MONTHLY_COST_LIMIT_JPY:
                logger.warning(f"経営日報月次コスト上限到達: ¥{monthly_cost:.1f} >= ¥{MONTHLY_COST_LIMIT_JPY}")
                return {"status": "cost_limit_reached", "monthly_cost": float(monthly_cost)}

            # 昨日のデータ収集
            data = {}

            # ゴール
            goals = await conn.fetch("""
                SELECT goal_id, raw_goal, status
                FROM goal_packets
                WHERE created_at > CURRENT_DATE - INTERVAL '1 day'
                AND created_at <= CURRENT_DATE
                ORDER BY created_at DESC LIMIT 5
            """)
            data["goals"] = [{"id": r["goal_id"], "goal": (r["raw_goal"] or "")[:100], "status": r["status"]} for r in goals]

            # タスク
            task_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'running') as running,
                    COUNT(*) FILTER (WHERE status = 'pending') as pending
                FROM tasks
                WHERE updated_at > CURRENT_DATE - INTERVAL '1 day'
            """)
            data["tasks"] = dict(task_stats) if task_stats else {}

            # SNS投稿
            sns = await conn.fetchrow("""
                SELECT COUNT(*) as posted FROM event_log
                WHERE event_type = 'sns.posted'
                AND created_at > CURRENT_DATE - INTERVAL '1 day'
                AND created_at <= CURRENT_DATE
            """)
            data["sns_posted"] = sns["posted"] if sns else 0

            # LLMコスト
            cost = await conn.fetchrow("""
                SELECT COUNT(*) as calls, COALESCE(SUM(amount_jpy), 0) as total_jpy
                FROM llm_cost_log
                WHERE recorded_at > CURRENT_DATE - INTERVAL '1 day'
                AND recorded_at <= CURRENT_DATE
            """)
            data["llm_cost"] = {"calls": cost["calls"], "total_jpy": float(cost["total_jpy"] or 0)} if cost else {}

            # エラー
            errors = await conn.fetch("""
                SELECT event_type, COUNT(*) as cnt
                FROM event_log
                WHERE severity IN ('error', 'critical')
                AND created_at > CURRENT_DATE - INTERVAL '1 day'
                AND created_at <= CURRENT_DATE
                GROUP BY event_type ORDER BY cnt DESC LIMIT 5
            """)
            data["errors"] = [{"type": r["event_type"], "count": r["cnt"]} for r in errors]

            # 承認待ち
            pending_approvals = await conn.fetchval(
                "SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'"
            ) or 0
            data["pending_approvals"] = pending_approvals

            # 商品パッケージ待ち
            try:
                pending_packages = await conn.fetchval(
                    "SELECT COUNT(*) FROM product_packages WHERE status = 'ready'"
                ) or 0
            except Exception:
                pending_packages = 0
            data["pending_packages"] = pending_packages

            # 収益
            try:
                revenue = await conn.fetchval(
                    "SELECT COALESCE(SUM(revenue_jpy), 0) FROM commerce_transactions WHERE created_at > CURRENT_DATE - INTERVAL '30 days'"
                ) or 0
            except Exception:
                revenue = 0
            data["monthly_revenue"] = float(revenue)

    except Exception as e:
        logger.error(f"経営日報データ収集失敗: {e}")
        return {"status": "error", "error": str(e)}

    # Haiku 1回でブリーフィング生成
    model_sel = choose_best_model_v6(
        task_type="strategy",
        quality="medium",
        budget_sensitive=True,
    )

    prompt = f"""以下のデータから島原大知への経営日報を作成してください。

## 昨日のシステムデータ
{json.dumps(data, ensure_ascii=False, indent=2)}

## 出力フォーマット
📋 **SYUTAINβ 経営日報 {date.today().strftime('%Y-%m-%d')}**

**昨日の成果:**
- （タスク完了数、SNS投稿数、特筆事項）

**コスト:** ¥X（LLM Y回）

**注意事項:**
- （エラー、承認待ち、問題点）

**💡 今日やるべき1つのこと:**
（最も収益インパクトの高い具体的なアクション1つ）

---
300文字以内で簡潔に。"""

    try:
        result = await call_llm(
            prompt=prompt,
            system_prompt="SYUTAINβの経営日報生成。島原大知に対して、対等なパートナーとして簡潔に報告する。",
            model_selection=model_sel,
            goal_id="executive_briefing",
            max_tokens=800,
        )
        briefing_text = result.get("text", "日報生成失敗")
        cost_jpy = result.get("cost_jpy", 0.0)
    except Exception as e:
        logger.error(f"経営日報LLM生成失敗: {e}")
        return {"status": "error", "error": str(e)}

    # Discord送信
    try:
        await notify_discord(briefing_text, username="SYUTAINβ 経営日報")
    except Exception as e:
        logger.error(f"経営日報Discord送信失敗: {e}")

    # イベント記録
    try:
        from tools.event_logger import log_event
        await log_event("briefing.generated", "system", {
            "date": str(date.today()),
            "cost_jpy": cost_jpy,
            "data_summary": {k: str(v)[:50] for k, v in data.items()},
        })
    except Exception:
        pass

    logger.info(f"経営日報生成完了: ¥{cost_jpy:.2f}")
    return {"status": "success", "cost_jpy": cost_jpy, "text_length": len(briefing_text)}
