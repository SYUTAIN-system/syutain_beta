"""
SYUTAINβ V25 Discord Webhook通知
severity-based dedup対応
"""
import os
import time
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("syutain.discord")

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
BRAIN_WEBHOOK_URL = os.getenv("DISCORD_BRAIN_WEBHOOK_URL", "")

# ===== 重複排除 =====
DEDUP_INTERVAL = 300  # 5分（デフォルト）
DEDUP_INTERVAL_LONG = 3600  # 1時間（予算警告等の繰り返し抑制）
_recent_notifications: dict[str, float] = {}  # error_type -> last_sent_timestamp

# 長い間隔（1時間）で抑制するエラータイプのプレフィックス/キーワード
_LONG_DEDUP_PREFIXES = ("budget_", "cost_", "予算", "Ollama", "proactive", "node", "BRAVO", "CHARLIE", "DELTA", "health")


def _should_send(error_type: str, severity: str) -> bool:
    """severity-based dedup判定。CRITICALは常に送信、ERRORは5分/1時間dedup"""
    if severity == "critical":
        return True
    now = time.time()
    last = _recent_notifications.get(error_type, 0.0)
    # 予算系は1時間dedup、それ以外は5分dedup
    interval = DEDUP_INTERVAL_LONG if any(error_type.startswith(p) for p in _LONG_DEDUP_PREFIXES) else DEDUP_INTERVAL
    if now - last < interval:
        return False
    _recent_notifications[error_type] = now
    # メモリリーク防止: 200件超で古いエントリを削除、500件でハード上限（半分削除）
    n = len(_recent_notifications)
    if n > 500:
        sorted_keys = sorted(_recent_notifications, key=_recent_notifications.get)
        for k in sorted_keys[: n // 2]:
            del _recent_notifications[k]
    elif n > 200:
        cutoff = now - DEDUP_INTERVAL * 2
        stale = [k for k, v in _recent_notifications.items() if v < cutoff]
        for k in stale:
            del _recent_notifications[k]
    return True


async def notify_error(error_type: str, message: str, severity: str = "error") -> bool:
    """severity-based dedup付きエラー通知。

    Args:
        error_type: エラー種別キー（dedup用）
        message: 通知本文
        severity: "error" or "critical"
    """
    if not _should_send(error_type, severity):
        logger.debug(f"dedup skip: {error_type}")
        return False
    prefix = "\U0001f534" if severity == "critical" else "\u26a0\ufe0f"
    return await notify_discord(f"{prefix} [{severity.upper()}] {message}")


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
                except Exception as e:
                    logger.warning(f"Brain-α通知失敗（メイン送信は成功）: {e}")

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


async def notify_emergency_kill(reason: str, goal_id: str = "", step_count: int = 0, cost_jpy: float = 0.0):
    detail = f"\U0001f6a8 緊急停止: {reason}"
    if goal_id:
        detail += f"\n  goal={goal_id} steps={step_count} cost=¥{cost_jpy:.1f}"
    await notify_discord(detail)


async def notify_goal_accepted(goal_text: str):
    await notify_discord(f"\U0001f504 ゴール受付: {goal_text[:300]} — 自律ループを開始します")


async def notify_daily_summary(completed: int, revenue: float, pending_approvals: int):
    await notify_discord(
        f"\U0001f4ca 日次サマリー: 完了タスク {completed}件 / 収益 \u00a5{revenue:,.0f} / 承認待ち {pending_approvals}件"
    )
