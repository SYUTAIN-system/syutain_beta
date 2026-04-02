"""
SYUTAINβ V25 A2A Protocol (Agent-to-Agent) Support (Feature 9)
Google主導のエージェント間通信標準プロトコル。

MCP = エージェント↔ツール接続
A2A = エージェント↔エージェント接続

SYUTAINβのケイパビリティを外部エージェントに広告し、
タスク委任を受け付ける。

feature_flags.yaml: a2a_protocol: false（デフォルト無効）
"""

import os
import json
import logging
from datetime import datetime, timezone

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.a2a")

# SYUTAINβのA2Aエージェントカード
AGENT_CARD = {
    "name": "SYUTAINβ",
    "description": "自律型AI事業OS。コンテンツ生成、市場リサーチ、SNS管理、競合分析を提供。",
    "url": os.getenv("A2A_AGENT_URL", "https://syutain.local"),
    "version": "v25",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "content_generation",
            "name": "コンテンツ生成",
            "description": "note記事、SNS投稿、商品説明を自動生成。2段階精錬パイプライン。",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "market_research",
            "name": "市場リサーチ",
            "description": "AI/テック市場のトレンド分析、競合調査、海外動向検出。",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "sns_management",
            "name": "SNS運用",
            "description": "Bluesky/X/Threadsへの自動投稿、エンゲージメント分析。",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "competitive_analysis",
            "name": "競合分析",
            "description": "バズアカウント分析、トレンドパターン抽出。",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
    ],
}


async def get_agent_card() -> dict:
    """A2Aエージェントカードを返す"""
    return AGENT_CARD


async def handle_a2a_task(task: dict) -> dict:
    """外部エージェントからのA2Aタスクを処理"""
    task_id = task.get("id", "")
    skill_id = task.get("skill_id", "")
    input_text = task.get("input", {}).get("text", "")

    # タスクをDBに記録
    try:
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS a2a_tasks (
                    id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    input_text TEXT,
                    output_text TEXT,
                    status TEXT DEFAULT 'pending',
                    source_agent TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
            await conn.execute(
                "INSERT INTO a2a_tasks (id, skill_id, input_text, source_agent, status) VALUES ($1, $2, $3, $4, 'processing')",
                task_id, skill_id, input_text, task.get("source_agent", "unknown"),
            )
    except Exception as e:
        logger.warning(f"a2a task recording failed: {e}")

    # スキル別処理
    try:
        if skill_id == "market_research":
            from tools.overseas_trend_detector import detect_overseas_trends
            findings = await detect_overseas_trends()
            output = json.dumps(findings, ensure_ascii=False)
        elif skill_id == "competitive_analysis":
            from tools.buzz_account_analyzer import analyze_buzz_patterns
            result = await analyze_buzz_patterns()
            output = json.dumps(result, ensure_ascii=False)
        else:
            output = json.dumps({"error": f"Unknown skill: {skill_id}"})

        # 完了記録
        try:
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE a2a_tasks SET status = 'completed', output_text = $1, completed_at = NOW() WHERE id = $2",
                    output[:10000], task_id,
                )
        except Exception:
            pass

        return {"id": task_id, "status": "completed", "output": {"text": output}}

    except Exception as e:
        logger.error(f"a2a task failed: {e}")
        return {"id": task_id, "status": "failed", "error": str(e)}


async def get_a2a_task_status(task_id: str) -> dict:
    """A2Aタスクのステータスを返す"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM a2a_tasks WHERE id = $1", task_id)
            if row:
                return {
                    "id": row["id"],
                    "status": row["status"],
                    "output": {"text": row["output_text"]} if row["output_text"] else None,
                }
            return {"id": task_id, "status": "not_found"}
    except Exception as e:
        return {"id": task_id, "status": "error", "error": str(e)}
