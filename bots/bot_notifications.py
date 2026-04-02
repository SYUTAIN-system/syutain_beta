"""能動的通知 — Botが自分から話しかける"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("syutain.bot_notifications")


async def _ensure_db_pool():
    """DB poolが初期化されていなければ初期化する"""
    try:
        from tools.db_pool import get_pool
        await get_pool()
        return True
    except Exception as e:
        logger.warning(f"DB pool未準備: {e}")
        return False


async def generate_morning_report(bot) -> str:
    """朝の報告（07:00に呼ばれる）"""
    try:
        if not await _ensure_db_pool():
            return "おはようございます。DB接続が準備できていないため、レポートを生成できませんでした。"

        from tools.db_pool import get_connection
        async with get_connection() as conn:
            posted = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='posted' AND posted_at::date = CURRENT_DATE - 1"
            )
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='pending' AND scheduled_at::date = CURRENT_DATE"
            )
            errors = await conn.fetchval(
                "SELECT COUNT(*) FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '24 hours'"
            )
            # actionableなニュース
            actionable = await conn.fetch(
                "SELECT title FROM intel_items WHERE review_flag='actionable' ORDER BY importance_score DESC LIMIT 1"
            )
            # 成果物
            artifacts = await conn.fetchval(
                """SELECT COUNT(*) FROM tasks WHERE status='completed' AND quality_score >= 0.75
                AND created_at > NOW() - INTERVAL '24 hours'"""
            )

        msg = f"おはようございます。昨日のSNS投稿は{posted}件完了。今日は{pending}件予定です。"
        if errors > 0:
            msg += f" エラーが{errors}件出ています。"
        else:
            msg += " エラーはなしです。"
        if actionable:
            msg += f"\n今朝のダイジェストで注目: {actionable[0]['title'][:50]}。"
        if artifacts and artifacts > 0:
            msg += f"\n成果物が{artifacts}件できています。確認しますか？"
        return msg
    except Exception as e:
        logger.error(f"朝レポート生成エラー: {e}")
        return f"おはようございます。レポート生成でエラーが出ました: {e}"


async def generate_night_summary(bot) -> str:
    """夜のサマリー（22:00に呼ばれる）"""
    try:
        if not await _ensure_db_pool():
            return "お疲れ様です。DB接続が準備できていないため、サマリーを生成できませんでした。"

        from tools.db_pool import get_connection
        async with get_connection() as conn:
            posted = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='posted' AND posted_at::date=CURRENT_DATE"
            )
            failed = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='failed' AND scheduled_at::date=CURRENT_DATE"
            )
            errors = await conn.fetchval(
                "SELECT COUNT(*) FROM event_log WHERE severity='error' AND created_at::date=CURRENT_DATE"
            )
            cost = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
            )
            local_pct = await conn.fetchval(
                """SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE tier IN ('local','L'))
                   / GREATEST(COUNT(*), 1), 1)
                FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"""
            )

        msg = f"今日のまとめ。投稿: {posted}件"
        if failed and failed > 0:
            msg += f" (失敗{failed}件)"
        msg += f" / エラー: {errors}件 / コスト: ¥{float(cost):.0f} (ローカル{float(local_pct or 0):.0f}%)。"
        msg += " 明日分の投稿はこれから生成します。お疲れ様でした。"
        return msg
    except Exception as e:
        logger.error(f"夜サマリー生成エラー: {e}")
        return "今日のサマリー生成に失敗しました。"
