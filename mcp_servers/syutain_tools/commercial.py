"""
SYUTAINβ V25 MCP商用ツール (Feature 8)
SYUTAINβの能力を外部MCPクライアントに販売可能な形で公開する。

内部利用のserver.pyとは分離し、認証・レート制限・使用量追跡を持つ。
feature_flags.yaml: mcp_external_commercial: false（デフォルト無効）
"""

import os
import json
import time
import logging
from typing import Optional

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.mcp_commercial")

# レート制限（クライアントID → {count, reset_at}）
_rate_limits: dict[str, dict] = {}
RATE_LIMIT_PER_HOUR = 60


COMMERCIAL_TOOLS = [
    {
        "name": "analyze_competitor",
        "description": "AI/テック系の競合分析レポートを生成。Bluesky/X/note.comのトレンドを分析。",
        "price_jpy_per_call": 10,
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "分析テーマ（例: 'AI agent framework'）"},
                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["bluesky", "note"]},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "generate_sns_content",
        "description": "SNS投稿文を生成。ターゲット層とプラットフォームに最適化。",
        "price_jpy_per_call": 5,
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "投稿テーマ"},
                "platform": {"type": "string", "enum": ["x", "bluesky", "threads"]},
                "tone": {"type": "string", "default": "professional"},
                "count": {"type": "integer", "default": 3, "maximum": 10},
            },
            "required": ["topic", "platform"],
        },
    },
    {
        "name": "research_topic",
        "description": "特定トピックについてWeb検索+要約レポートを生成。",
        "price_jpy_per_call": 15,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "リサーチクエリ"},
                "depth": {"type": "string", "enum": ["basic", "deep"], "default": "basic"},
                "language": {"type": "string", "default": "ja"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_content_quality",
        "description": "テキストコンテンツの品質スコアを算出。AI臭チェック含む。",
        "price_jpy_per_call": 3,
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "評価対象テキスト"},
                "platform": {"type": "string", "default": "note"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "detect_overseas_trend",
        "description": "英語圏で話題だが日本語記事がまだないAIトピックを検出。",
        "price_jpy_per_call": 20,
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "default": "AI", "description": "カテゴリ"},
            },
        },
    },
]


def check_api_key(api_key: str) -> Optional[str]:
    """APIキーを検証し、クライアントIDを返す。無効ならNone。"""
    # TODO: DBベースのAPIキー管理に移行
    valid_keys = json.loads(os.getenv("MCP_COMMERCIAL_API_KEYS", "{}"))
    return valid_keys.get(api_key)


def check_rate_limit(client_id: str) -> bool:
    """レート制限チェック。超過していたらFalse。"""
    now = time.time()
    if client_id not in _rate_limits:
        _rate_limits[client_id] = {"count": 0, "reset_at": now + 3600}

    rl = _rate_limits[client_id]
    if now > rl["reset_at"]:
        rl["count"] = 0
        rl["reset_at"] = now + 3600

    if rl["count"] >= RATE_LIMIT_PER_HOUR:
        return False

    rl["count"] += 1
    return True


async def record_usage(client_id: str, tool_name: str, cost_jpy: float):
    """使用量をDBに記録"""
    try:
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mcp_external_usage (
                    id SERIAL PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    cost_jpy REAL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute(
                "INSERT INTO mcp_external_usage (client_id, tool_name, cost_jpy) VALUES ($1, $2, $3)",
                client_id, tool_name, cost_jpy,
            )
    except Exception as e:
        logger.warning(f"usage recording failed: {e}")


async def get_usage_summary(client_id: str) -> dict:
    """クライアントの使用量サマリー"""
    try:
        async with get_connection() as conn:
            total = await conn.fetchrow("""
                SELECT COUNT(*) as calls, COALESCE(SUM(cost_jpy), 0) as total_cost
                FROM mcp_external_usage WHERE client_id = $1
            """, client_id)
            monthly = await conn.fetchrow("""
                SELECT COUNT(*) as calls, COALESCE(SUM(cost_jpy), 0) as total_cost
                FROM mcp_external_usage
                WHERE client_id = $1 AND created_at > date_trunc('month', CURRENT_DATE)
            """, client_id)
            return {
                "total_calls": total["calls"] if total else 0,
                "total_cost_jpy": float(total["total_cost"]) if total else 0,
                "monthly_calls": monthly["calls"] if monthly else 0,
                "monthly_cost_jpy": float(monthly["total_cost"]) if monthly else 0,
            }
    except Exception as e:
        return {"error": str(e)}
