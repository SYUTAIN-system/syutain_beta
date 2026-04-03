"""
SYUTAINβ MCP Server — Expose bot capabilities as MCP tools.

Implements a lightweight MCP-style server as FastAPI endpoints.
Other AI agents can discover and call these tools via REST API.
Authentication is API key based (MCP_API_KEY in .env).
Rate limited to 100 calls/day per API key.

Endpoints:
  POST /mcp/tools/list          — Discover available tools
  POST /mcp/tools/call          — Call a tool by name
  GET  /mcp/health              — Server health check
"""

import os
import json
import time
import logging
from datetime import date, datetime, timezone
from typing import Optional
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.mcp_server")

# ===== 設定 =====
MCP_API_KEY = os.getenv("MCP_API_KEY", "")
MCP_RATE_LIMIT_DAILY = int(os.getenv("MCP_RATE_LIMIT_DAILY", "100"))
TOOLS_CONFIG_PATH = Path(__file__).parent.parent / "config" / "mcp_tools.json"

# ===== レート制限（インメモリ）=====
_rate_counters: dict[str, dict] = defaultdict(lambda: {"date": "", "count": 0})

router = APIRouter(prefix="/mcp", tags=["MCP"])


# ===== Pydantic モデル =====

class MCPToolCallRequest(BaseModel):
    """JSON-RPC風のツール呼び出しリクエスト"""
    name: str = Field(..., description="Tool name to call")
    arguments: dict = Field(default_factory=dict, description="Tool arguments")


class MCPToolCallResponse(BaseModel):
    """ツール呼び出しレスポンス"""
    tool: str
    success: bool
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


# ===== 認証 =====

async def verify_mcp_api_key(request: Request) -> str:
    """MCP API キー検証。Authorizationヘッダから取得。"""
    if not MCP_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="MCP server not configured: MCP_API_KEY is not set in .env",
        )

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    key = auth[7:]
    if key != MCP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid MCP API key")

    return key


def _check_rate_limit(api_key: str) -> None:
    """日次レート制限チェック"""
    today = date.today().isoformat()
    entry = _rate_counters[api_key]
    if entry["date"] != today:
        entry["date"] = today
        entry["count"] = 0
    if entry["count"] >= MCP_RATE_LIMIT_DAILY:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {MCP_RATE_LIMIT_DAILY} calls/day",
        )
    entry["count"] += 1


# ===== ツール実装 =====

async def _tool_research_topic(query: str, depth: str = "basic") -> str:
    """info_pipeline / tavily を使ってトピックをリサーチ"""
    try:
        from tools.tavily_client import TavilyClient
        client = TavilyClient()
        search_depth = "advanced" if depth == "deep" else "basic"
        result = await client.search(
            query=query,
            max_results=5,
            search_depth=search_depth,
            include_answer=True,
        )
        if result.get("error"):
            return json.dumps({"error": result["error"]}, ensure_ascii=False)

        output = {
            "query": query,
            "answer": result.get("answer", ""),
            "sources": [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:200]}
                for r in result.get("results", [])[:5]
            ],
        }
        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        logger.error(f"research_topic failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _tool_analyze_trend(topic: str, language: str = "ja") -> str:
    """trend_detector を使ってトレンド分析"""
    try:
        from tools.trend_detector import detect_untapped_trends
        trends = await detect_untapped_trends(hours=48, max_topics=10)
        # トピックに関連するものをフィルタ
        topic_lower = topic.lower()
        relevant = [
            t for t in trends
            if topic_lower in t.get("topic", "").lower()
            or any(topic_lower in v.lower() for v in t.get("variants", []))
        ]
        if not relevant:
            # 関連トレンドが見つからなかったので、Tavilyで直接調査
            from tools.tavily_client import TavilyClient
            client = TavilyClient()
            lang_query = f"{topic} トレンド 最新" if language == "ja" else f"{topic} trend latest"
            result = await client.search(query=lang_query, max_results=3, include_answer=True)
            return json.dumps({
                "topic": topic,
                "trending": False,
                "analysis": result.get("answer", "No trend data found"),
                "sources": len(result.get("results", [])),
            }, ensure_ascii=False)

        output = {
            "topic": topic,
            "trending": True,
            "trends": [
                {
                    "topic": t["topic"],
                    "gap_score": t.get("gap_score", 0),
                    "english_sources": t.get("english_sources", 0),
                    "japanese_sources": t.get("japanese_sources", 0),
                    "recommended_angle": t.get("recommended_angle", ""),
                }
                for t in relevant[:5]
            ],
        }
        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        logger.error(f"analyze_trend failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _tool_generate_content(topic: str, format: str = "article", length: int = 3000) -> str:
    """content_tools を使ってコンテンツ生成"""
    try:
        from tools.content_tools import generate_content
        prompt = f"トピック: {topic}\nフォーマット: {format}\n目標文字数: {length}文字"
        result = await generate_content(
            content_type=format,
            prompt=prompt,
            quality="medium",
        )
        if result.get("error"):
            return json.dumps({"error": result["error"]}, ensure_ascii=False)
        return json.dumps({
            "topic": topic,
            "format": format,
            "text": result.get("text", ""),
            "char_count": len(result.get("text", "")),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"generate_content failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _tool_check_facts(text: str) -> str:
    """Tavily/Jina を使ってファクトチェック"""
    try:
        from tools.tavily_client import TavilyClient
        client = TavilyClient()
        # テキストから主要な主張を抽出して検証
        # 最初の200文字をクエリとして使用
        query = text[:200] if len(text) > 200 else text
        result = await client.search(
            query=f"fact check: {query}",
            max_results=5,
            search_depth="advanced",
            include_answer=True,
        )
        output = {
            "original_text_preview": text[:300],
            "verification": result.get("answer", "Unable to verify"),
            "sources": [
                {"title": r.get("title", ""), "url": r.get("url", "")}
                for r in result.get("results", [])[:5]
            ],
        }
        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        logger.error(f"check_facts failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _tool_monitor_system(target: str = "all") -> str:
    """システムヘルスステータスを返す"""
    try:
        import psutil
        nodes = ["alpha", "bravo", "charlie", "delta"]
        if target != "all" and target in nodes:
            nodes = [target]

        # ローカル（ALPHA）のメトリクスは直接取得
        local_metrics = {
            "node": "alpha",
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
        }

        # リモートノードのステータスはNATSハートビートキャッシュから取得
        remote_status = {}
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (payload->>'node')
                        payload->>'node' AS node,
                        payload,
                        created_at
                    FROM event_log
                    WHERE event_type = 'heartbeat'
                      AND created_at > NOW() - INTERVAL '15 minutes'
                    ORDER BY payload->>'node', created_at DESC
                """)
                for row in rows:
                    node = row["node"]
                    if node != "alpha":
                        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                        remote_status[node] = {
                            "status": "alive",
                            "cpu_percent": payload.get("cpu_percent", 0),
                            "memory_percent": payload.get("memory_percent", 0),
                            "last_seen": row["created_at"].isoformat(),
                        }
        except Exception as db_err:
            logger.warning(f"DB query for remote nodes failed: {db_err}")

        # ステータスが取得できなかったノードは unknown
        for node in ["bravo", "charlie", "delta"]:
            if node not in remote_status:
                remote_status[node] = {"status": "unknown", "last_seen": None}

        output = {"alpha": local_metrics}
        output.update(remote_status)

        return json.dumps(output, ensure_ascii=False)
    except Exception as e:
        logger.error(f"monitor_system failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ===== ツールレジストリ =====

TOOL_REGISTRY = {
    "research_topic": _tool_research_topic,
    "analyze_trend": _tool_analyze_trend,
    "generate_content": _tool_generate_content,
    "check_facts": _tool_check_facts,
    "monitor_system": _tool_monitor_system,
}


# ===== エンドポイント =====

@router.get("/health")
async def mcp_health():
    """MCP サーバーヘルスチェック（認証不要）"""
    return {
        "status": "ok",
        "server": "syutain-beta-mcp",
        "version": "1.0.0",
        "tools_available": len(TOOL_REGISTRY),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/tools/list")
async def mcp_tools_list(api_key: str = Depends(verify_mcp_api_key)):
    """利用可能なツール一覧を返す（MCP tools/list 相当）"""
    try:
        if TOOLS_CONFIG_PATH.exists():
            tools_config = json.loads(TOOLS_CONFIG_PATH.read_text(encoding="utf-8"))
            return {"tools": tools_config.get("tools", [])}
        else:
            # config がなくてもレジストリから最低限の情報を返す
            return {
                "tools": [
                    {"name": name, "description": f"SYUTAINβ tool: {name}"}
                    for name in TOOL_REGISTRY
                ]
            }
    except Exception as e:
        logger.error(f"tools/list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/call")
async def mcp_tools_call(
    req: MCPToolCallRequest,
    api_key: str = Depends(verify_mcp_api_key),
):
    """ツールを呼び出す（MCP tools/call 相当）"""
    _check_rate_limit(api_key)

    if req.name not in TOOL_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool: {req.name}. Available: {list(TOOL_REGISTRY.keys())}",
        )

    # イベントログに記録
    try:
        from tools.event_logger import log_event
        await log_event(
            event_type="mcp.tool_call",
            category="mcp",
            payload={"tool": req.name, "arguments": req.arguments},
            severity="info",
        )
    except Exception:
        pass  # ログ失敗でもツール実行は続行

    start = time.monotonic()
    try:
        tool_fn = TOOL_REGISTRY[req.name]
        result = await tool_fn(**req.arguments)
        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(f"MCP tool call: {req.name} ({duration_ms}ms)")

        return MCPToolCallResponse(
            tool=req.name,
            success=True,
            result=result,
            duration_ms=duration_ms,
        )
    except TypeError as e:
        # 引数エラー
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(f"MCP tool argument error: {req.name} — {e}")
        return MCPToolCallResponse(
            tool=req.name,
            success=False,
            error=f"Invalid arguments: {e}",
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error(f"MCP tool error: {req.name} — {e}")
        return MCPToolCallResponse(
            tool=req.name,
            success=False,
            error=str(e),
            duration_ms=duration_ms,
        )
