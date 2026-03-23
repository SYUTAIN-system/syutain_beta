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
BRAIN_WEBHOOK_URL = os.getenv("DISCORD_BRAIN_WEBHOOK_URL", "")


async def notify_discord(content: str, username: str = "SYUTAINβ") -> bool:
    """Discord Webhookに通知を送信（メイン + Brain-αチャネル）"""
    if not WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL未設定")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(WEBHOOK_URL, json={
                "username": username,
                "content": content,
            })
            ok = resp.status_code in (200, 204)
            if not ok:
                logger.error(f"Discord通知失敗: {resp.status_code} {resp.text[:100]}")

            # Brain-αチャネルにも送信（設定されている場合のみ）
            if BRAIN_WEBHOOK_URL:
                try:
                    await client.post(BRAIN_WEBHOOK_URL, json={
                        "username": f"{username} → Brain-α",
                        "content": content,
                    })
                except Exception:
                    pass  # Brain通知失敗はメイン通知に影響させない

            return ok
    except Exception as e:
        logger.error(f"Discord通知エラー: {e}")
        return False


async def notify_brain_only(content: str, username: str = "Brain-α") -> bool:
    """Brain-αチャネルのみに通知（メインには送らない）"""
    url = BRAIN_WEBHOOK_URL or WEBHOOK_URL
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"username": username, "content": content})
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.error(f"Brain通知エラー: {e}")
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
