"""
Codex ChatGPT Plus 認証期限監視ツール

2026-04-11 島原さん方針「期限5日前にアラート送信」に基づき追加。
~/.codex/auth.json の JWT(id_token) をパースして chatgpt_subscription_active_until を取得、
残り5日以下になったら Discord に通知する。
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
ALERT_THRESHOLD_DAYS = 5


def _parse_jwt_payload(jwt: str) -> dict | None:
    """JWT id_token のペイロードをデコードする（署名検証はしない、情報表示用のみ）"""
    try:
        parts = jwt.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        logger.warning(f"JWT デコード失敗: {e}")
        return None


def get_codex_subscription_status() -> dict[str, Any]:
    """Codex ChatGPT Plus のサブスク状態を取得"""
    status: dict[str, Any] = {
        "available": False,
        "plan_type": None,
        "active_until": None,
        "days_remaining": None,
        "last_refresh": None,
        "error": None,
    }

    if not CODEX_AUTH_PATH.exists():
        status["error"] = f"auth.json 未発見: {CODEX_AUTH_PATH}"
        return status

    try:
        with open(CODEX_AUTH_PATH) as f:
            data = json.load(f)
    except Exception as e:
        status["error"] = f"auth.json 読み込み失敗: {e}"
        return status

    status["last_refresh"] = data.get("last_refresh")

    tokens = data.get("tokens") or {}
    id_token = tokens.get("id_token") or ""
    if not id_token:
        status["error"] = "id_token が auth.json に無い"
        return status

    payload = _parse_jwt_payload(id_token)
    if not payload:
        status["error"] = "JWT デコード失敗"
        return status

    auth_meta = payload.get("https://api.openai.com/auth") or {}
    plan_type = auth_meta.get("chatgpt_plan_type")
    active_until_str = auth_meta.get("chatgpt_subscription_active_until")

    status["plan_type"] = plan_type
    status["active_until"] = active_until_str

    if not active_until_str:
        status["error"] = "chatgpt_subscription_active_until が payload に無い"
        return status

    try:
        active_until = datetime.fromisoformat(active_until_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = active_until - now
        status["days_remaining"] = delta.total_seconds() / 86400
        status["available"] = delta.total_seconds() > 0
    except Exception as e:
        status["error"] = f"日付パース失敗: {e}"

    return status


async def check_and_alert() -> dict[str, Any]:
    """Codex 認証期限チェック → 5日以下なら Discord 通知"""
    status = get_codex_subscription_status()

    if status.get("error"):
        logger.warning(f"Codex 認証チェック: {status['error']}")
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(
                f"⚠️ Codex 認証チェック失敗\n{status['error']}"
            )
        except Exception as e:
            logger.error(f"Codex 警告通知失敗: {e}")
        return status

    days = status.get("days_remaining") or 0
    plan = status.get("plan_type") or "unknown"
    until = status.get("active_until") or "不明"

    logger.info(
        f"Codex 認証: plan={plan}, active_until={until}, "
        f"days_remaining={days:.1f}"
    )

    if days <= 0:
        # 既に期限切れ
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(
                f"🔴 Codex ChatGPT Plus 認証 **期限切れ**\n"
                f"active_until: {until}\n"
                f"`codex auth` で再ログインが必要。gstack 系ジョブが停止する可能性。"
            )
        except Exception as e:
            logger.error(f"Codex 期限切れ通知失敗: {e}")
    elif days <= ALERT_THRESHOLD_DAYS:
        # 期限5日以内: アラート
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(
                f"⏰ Codex ChatGPT Plus 認証 残り **{days:.1f}日**\n"
                f"active_until: {until}\n"
                f"`codex auth` で再ログインの準備を。"
            )
        except Exception as e:
            logger.error(f"Codex アラート通知失敗: {e}")

    return status
