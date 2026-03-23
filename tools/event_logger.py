"""
SYUTAINβ V25 汎用イベントロガー
Phase 1-4まで テーブル変更なしで対応できる汎用設計。
"""

import os
import json
import logging
from typing import Optional

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.event_logger")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
THIS_NODE = os.getenv("THIS_NODE", "alpha")

_pool: Optional[asyncpg.Pool] = None


async def _get_pool() -> Optional[asyncpg.Pool]:
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        except Exception as e:
            logger.error(f"event_logger DB接続失敗: {e}")
    return _pool


async def log_event(
    event_type: str,
    category: str,
    payload: dict = None,
    severity: str = "info",
    source_node: str = None,
    goal_id: str = None,
    task_id: str = None,
) -> bool:
    """イベントをevent_logテーブルに記録する。

    Args:
        event_type: イベント種別 (例: "llm.call", "task.completed")
        category: カテゴリ (例: "llm", "task", "goal", "sns", "system")
        payload: 任意のJSONデータ
        severity: "info" / "warning" / "error" / "critical"
        source_node: 発生元ノード (alpha/bravo/charlie/delta)
        goal_id: 関連ゴールID
        task_id: 関連タスクID
    """
    try:
        pool = await _get_pool()
        if not pool:
            return False
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO event_log
                (event_type, category, severity, source_node, goal_id, task_id, payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                event_type,
                category,
                severity,
                source_node or THIS_NODE,
                goal_id,
                task_id,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
            )
        # 重要イベントをDiscordに自動通知
        try:
            await _notify_important_event(event_type, category, payload or {}, severity, source_node)
        except Exception:
            pass

        return True
    except Exception as e:
        # イベントログ自体の失敗でアプリを止めない
        logger.debug(f"イベント記録失敗 ({event_type}): {e}")
        return False


# Discord通知すべきイベントと絵文字マッピング
_DISCORD_EVENTS = {
    "goal.created": "🎯",
    "goal.completed": "✅",
    "goal.escalated": "🚨",
    "goal.fallback_activated": "🔄",
    "quality.artifact": "📝",
    "quality.refinement": "✨",
    "sns.posted": "📢",
    "sns.duplicate_rejected": "🚫",
    "content.batch_generated": "🌙",
    "content.note_draft": "📄",
    "system.new_capability_detected": "🔍",
    "system.backup": "💾",
}


async def _notify_important_event(event_type: str, category: str, payload: dict,
                                   severity: str, source_node: str = None):
    """重要イベントをDiscordに自動通知"""
    emoji = _DISCORD_EVENTS.get(event_type)
    if not emoji and severity not in ("error", "critical"):
        return  # 通知不要

    if severity == "critical":
        emoji = "🔴"
    elif severity == "error":
        emoji = "⚠️"

    if not emoji:
        return

    node_tag = f"[{(source_node or 'ALPHA').upper()}] " if source_node else ""

    # イベント固有のメッセージ生成
    if event_type == "goal.created":
        msg = f"{emoji} {node_tag}ゴール作成: {payload.get('raw_goal', '')[:80]}"
    elif event_type == "goal.completed":
        msg = f"{emoji} {node_tag}ゴール達成: {payload.get('total_steps', 0)}ステップ, ¥{payload.get('total_cost_jpy', 0):.1f}"
    elif event_type == "quality.artifact":
        msg = f"{emoji} {node_tag}成果物保存: 品質{payload.get('quality_score', 0):.2f} ({payload.get('length', 0)}文字)"
    elif event_type == "quality.refinement":
        msg = f"{emoji} {node_tag}精錬成功: {payload.get('original_score', 0):.2f}→{payload.get('refined_score', 0):.2f}"
    elif event_type == "sns.posted":
        msg = f"{emoji} {node_tag}{payload.get('platform', 'SNS')}投稿完了"
    elif event_type == "content.batch_generated":
        msg = f"{emoji} {node_tag}バッチ生成: {payload.get('topic', '')[:50]}"
    elif event_type == "content.note_draft":
        msg = f"{emoji} {node_tag}note記事ドラフト: {payload.get('theme', '')} ({payload.get('length', 0)}文字)"
    else:
        detail = payload.get("error", payload.get("reason", payload.get("message", "")))
        msg = f"{emoji} {node_tag}{event_type}: {str(detail)[:80]}"

    try:
        from tools.discord_notify import notify_discord
        await notify_discord(msg)
    except Exception:
        pass
