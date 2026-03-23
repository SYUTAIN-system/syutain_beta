"""
SYUTAINβ V25 Discord Webhook通知
"""
import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("syutain.discord")

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


async def notify_discord(content: str, username: str = "SYUTAINβ") -> bool:
    """Discord Webhookに通知を送信"""
    if not WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL未設定")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(WEBHOOK_URL, json={
                "username": username,
                "content": content,
            })
            if resp.status_code in (200, 204):
                return True
            logger.error(f"Discord通知失敗: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        logger.error(f"Discord通知エラー: {e}")
        return False


async def notify_approval_request(task_name: str, approval_id: int = 0):
    await notify_discord(f"\U0001f514 承認待ち: {task_name} — Web UIで確認してください (ID: {approval_id})")


async def notify_task_complete(task_name: str, summary: str = ""):
    await notify_discord(f"\u2705 タスク完了: {task_name} — 結果: {summary[:200]}")


async def notify_task_failed(task_name: str, error: str = ""):
    await notify_discord(f"\u274c タスク失敗: {task_name} — エラー: {error[:200]}")


async def notify_emergency_kill(reason: str):
    await notify_discord(f"\U0001f6a8 緊急停止: {reason}")


async def notify_goal_accepted(goal_text: str):
    await notify_discord(f"\U0001f504 ゴール受付: {goal_text[:300]} — 自律ループを開始します")


async def notify_daily_summary(completed: int, revenue: float, pending_approvals: int):
    await notify_discord(
        f"\U0001f4ca 日次サマリー: 完了タスク {completed}件 / 収益 \u00a5{revenue:,.0f} / 承認待ち {pending_approvals}件"
    )
