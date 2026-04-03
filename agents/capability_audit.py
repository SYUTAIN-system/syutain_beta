"""
SYUTAINβ V25 能力監査（Capability Audit）— Step 7
設計書 第7章準拠

全4ノード（ALPHA/BRAVO/CHARLIE/DELTA）の能力を監査し、
PostgreSQLのcapability_snapshotsテーブルにスナップショットを保存する。

CLAUDE.md ルール22: mutation_engineは監査対象に含めない。
"""

import os
import json
import time
import asyncio
import logging
import shutil
from datetime import datetime
from typing import Optional

from tools.db_pool import get_connection
from dotenv import load_dotenv

from tools.nats_client import get_nats_client

load_dotenv()

logger = logging.getLogger("syutain.capability_audit")


# ノード定義（設計書 第2章準拠）
NODE_DEFINITIONS = {
    "alpha": {
        "role": "司令塔/WebUI/DB/NATS_Server",
        "os": "macOS",
        "local_model": "qwen3.5-9b-mlx",
        "gpu": None,
        "ollama_url": "http://localhost:11434",
        "services": ["postgresql", "nats_server", "web_ui", "fastapi"],
    },
    "bravo": {
        "role": "Browser/ComputerUse/推論ワーカー",
        "os": "Ubuntu 24.04",
        "local_model": "qwen3.5-9b",
        "gpu": "RTX_5070_12GB",
        "ollama_url": os.getenv("BRAVO_OLLAMA_URL", "http://127.0.0.1:11434"),
        "services": ["nats_server", "lightpanda", "stagehand_v3", "playwright", "computer_use"],
    },
    "charlie": {
        "role": "ローカルLLM推論/バッチ処理",
        "os": "Ubuntu 24.04 (Win11 dual-boot)",
        "local_model": "qwen3.5-9b",
        "gpu": "RTX_3080_10GB",
        "ollama_url": os.getenv("CHARLIE_OLLAMA_URL", "http://127.0.0.1:11434"),
        "services": ["nats_server"],
    },
    "delta": {
        "role": "監視/補助/情報収集",
        "os": "Ubuntu 24.04",
        "local_model": "qwen3.5-4b",
        "gpu": "GTX_980Ti_6GB",
        "ollama_url": os.getenv("DELTA_OLLAMA_URL", "http://127.0.0.1:11434"),
        "services": ["nats_server"],
    },
}

# MCP サーバー定義（設計書 7.2準拠）
MCP_SERVERS = [
    "syutain_tools", "github", "gmail", "bluesky", "tavily", "jina",
]

# 外部API定義
EXTERNAL_APIS = {
    "openai": {"env_key": "OPENAI_API_KEY"},
    "anthropic": {"env_key": "ANTHROPIC_API_KEY"},
    "deepseek": {"env_key": "DEEPSEEK_API_KEY"},
    "google": {"env_key": "GEMINI_API_KEY"},
    "openrouter": {"env_key": "OPENROUTER_API_KEY"},
}


class CapabilityAudit:
    """能力監査エンジン"""

    def __init__(self):
        self._last_snapshot: Optional[dict] = None

    async def run_full_audit(self) -> dict:
        """
        全4ノードの完全監査を実行する。

        監査タイミング（設計書7.1）:
        - 目標を受けるたびに必ず実施
        - 実行中にエラーが発生したら再監査
        - 30分ごとに定期監査
        """
        logger.info("能力監査開始（全4ノード）")
        start_time = time.time()

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "nodes": {},
            "llms": {},
            "mcp_servers": {},
            "external_apis": {},
            "tools": {},
            "budget": {},
        }

        # 各ノードの監査を並列実行
        node_tasks = [asyncio.create_task(self._audit_node(name)) for name in NODE_DEFINITIONS]
        try:
            node_results = await asyncio.gather(*node_tasks, return_exceptions=True)
        except Exception as e:
            for t in node_tasks:
                if not t.done():
                    t.cancel()
            # キャンセル完了を待つ
            await asyncio.gather(*node_tasks, return_exceptions=True)
            raise

        for name, result in zip(NODE_DEFINITIONS, node_results):
            if isinstance(result, Exception):
                logger.error(f"ノード'{name}'の監査失敗: {result}")
                snapshot["nodes"][name] = {"status": "unreachable", "error": str(result)}
            else:
                snapshot["nodes"][name] = result

        # LLM可用性チェック
        snapshot["llms"] = await self._audit_llms()

        # MCP接続チェック（CLAUDE.md ルール20: 動的に確認）
        snapshot["mcp_servers"] = await self._audit_mcp_servers()

        # 外部APIチェック
        snapshot["external_apis"] = self._audit_external_apis()

        # ツール可用性
        snapshot["tools"] = self._audit_tools(snapshot["nodes"])

        # 予算状態
        snapshot["budget"] = await self._audit_budget()

        # 前回との差分を計算
        diff = self._compute_diff(snapshot)

        # PostgreSQLに保存
        await self._save_snapshot(snapshot, diff)

        # NATSにパブリッシュ
        await self._publish_snapshot(snapshot)

        # 差分があればevent_logに記録 + Discord通知
        if diff:
            try:
                from tools.event_logger import log_event
                _loop = asyncio.get_running_loop()
                _loop.create_task(log_event(
                    "system.capability_diff", "system",
                    {"diff_count": len(diff), "changes": {k: str(v)[:100] for k, v in list(diff.items())[:5]}},
                ))
                # 新規ツール・モデル検出時は通知
                new_items = [k for k in diff if diff[k].get("from") in (None, "unknown", "offline")]
                if new_items:
                    _loop.create_task(log_event(
                        "system.new_capability_detected", "system",
                        {"new_capabilities": new_items},
                    ))
                    try:
                        from tools.discord_notify import notify_discord
                        _loop.create_task(notify_discord(
                            f"🔍 新規能力検知: {', '.join(new_items[:3])}"
                        ))
                    except Exception:
                        pass
            except Exception:
                pass

        elapsed = time.time() - start_time
        logger.info(f"能力監査完了 ({elapsed:.1f}秒)")

        # 判断根拠トレース
        try:
            node_statuses = {n: snapshot["nodes"].get(n, {}).get("status", "unknown") for n in NODE_DEFINITIONS}
            await self._record_trace(
                action="run_full_audit",
                reasoning=f"全4ノード監査完了 ({elapsed:.1f}秒): {node_statuses}",
                confidence=1.0,
                context={"node_statuses": node_statuses, "diff_count": len(diff) if diff else 0, "elapsed_sec": round(elapsed, 1)},
            )
        except Exception:
            pass

        self._last_snapshot = snapshot
        return snapshot

    async def _audit_node(self, node_name: str) -> dict:
        """1ノードの監査"""
        definition = NODE_DEFINITIONS[node_name]
        result = {
            "status": "unknown",
            "role": definition["role"],
            "os": definition["os"],
            "gpu": definition.get("gpu"),
            "local_model": definition["local_model"],
            "local_model_status": "unknown",
            "nats_connected": False,
        }

        # NATS接続チェック
        try:
            nats_client = await get_nats_client()
            if nats_client.nc and not nats_client.nc.is_closed:
                # ハートビート確認をリクエスト
                heartbeat_resp = await nats_client.request(
                    f"agent.heartbeat.{node_name}",
                    {"ping": True},
                    timeout=5.0,
                )
                if heartbeat_resp:
                    result["nats_connected"] = True
                    result["status"] = "healthy"
                    # ハートビート応答にメトリクスが含まれていれば取得
                    if "cpu_load" in heartbeat_resp:
                        result["cpu_load"] = heartbeat_resp["cpu_load"]
                    if "memory_used_gb" in heartbeat_resp:
                        result["memory_used_gb"] = heartbeat_resp["memory_used_gb"]
                    if "vram_free_gb" in heartbeat_resp:
                        result["vram_free_gb"] = heartbeat_resp["vram_free_gb"]
                    if "inference_speed" in heartbeat_resp:
                        result["inference_speed"] = heartbeat_resp["inference_speed"]
        except Exception as e:
            logger.warning(f"ノード'{node_name}'のNATSハートビート失敗: {e}")

        # ローカルLLM可用性チェック（Ollama API）
        # ALPHAはOllamaアンインストール済み — チェックをスキップ
        if node_name == "alpha":
            result["local_model_status"] = "uninstalled"
            logger.debug("ALPHA: Ollamaアンインストール済み — チェックスキップ")
        else:
            try:
                import httpx
                ollama_url = definition["ollama_url"]
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{ollama_url}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        result["local_model_status"] = "running"
                        result["available_models"] = models
                        result["status"] = "healthy"
                    else:
                        result["local_model_status"] = "unavailable"
            except Exception as e:
                logger.warning(f"ノード'{node_name}'のOllama接続失敗: {e}")
                result["local_model_status"] = "unreachable"

        # ローカルノードのみディスク残量チェック
        if node_name == os.getenv("THIS_NODE", "alpha"):
            try:
                usage = shutil.disk_usage("/")
                result["disk_free_gb"] = round(usage.free / (1024 ** 3), 1)
            except Exception as e:
                logger.warning(f"ディスク容量チェック失敗: {e}")

        # ステータスが設定されていなければ unreachable
        if result["status"] == "unknown":
            result["status"] = "unreachable"

        return result

    async def _audit_llms(self) -> dict:
        """LLMプロバイダの可用性チェック"""
        llms = {}

        # API キーの存在チェック（実際のAPIコールはコスト発生するため省略）
        api_providers = {
            "openai": {
                "env_key": "OPENAI_API_KEY",
                "models": ["gpt-5.4", "gpt-5.4-pro", "gpt-5-mini", "gpt-5-nano"],
            },
            "anthropic": {
                "env_key": "ANTHROPIC_API_KEY",
                "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
            },
            "deepseek": {
                "env_key": "DEEPSEEK_API_KEY",
                "models": ["deepseek-v3.2"],
            },
            "google": {
                "env_key": "GEMINI_API_KEY",
                "models": ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
            },
            "openrouter": {
                "env_key": "OPENROUTER_API_KEY",
                "models": [],
            },
        }

        for provider, info in api_providers.items():
            key = os.getenv(info["env_key"], "")
            llms[provider] = {
                "status": "available" if key else "no_api_key",
                "models": info["models"],
            }

        # ローカルLLM状態はノード監査結果から転記（呼び出し元で統合）
        return llms

    async def _audit_mcp_servers(self) -> dict:
        """MCPサーバー接続状態チェック（CLAUDE.md ルール20: 動的に確認）

        NATS-based MCP ping is disabled — no MCP sidecar processes are running.
        MCP HTTP health endpoint (/mcp/health) is the canonical check method.
        """
        mcp_status = {}
        # HTTP health endpoint でチェック（NATS pingは無効化）
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://localhost:8000/mcp/health")
                if resp.status_code == 200:
                    data = resp.json()
                    for server_name in MCP_SERVERS:
                        mcp_status[server_name] = data.get(server_name, "not_available")
                else:
                    for server_name in MCP_SERVERS:
                        mcp_status[server_name] = "not_available"
        except Exception as e:
            logger.debug(f"MCP HTTP health check失敗: {e}")
            for server_name in MCP_SERVERS:
                mcp_status[server_name] = "not_available"
        return mcp_status

    def _audit_external_apis(self) -> dict:
        """外部APIの可用性チェック（APIキー存在ベース）"""
        result = {}
        for api_name, info in EXTERNAL_APIS.items():
            key = os.getenv(info["env_key"], "")
            result[api_name] = {
                "status": "available" if key else "no_api_key",
            }
        return result

    def _audit_tools(self, nodes: dict) -> dict:
        """ツール可用性チェック"""
        tools = {
            "note_drafting": True,
            "x_posting": "approval_required",
            "bluesky_posting": "approval_required",
            "github_push": "approval_required",
            "crypto_trading": "approval_required",
        }

        # ブラウザツール（BRAVO依存）
        bravo_status = nodes.get("bravo", {}).get("status", "unreachable")
        browser_available = bravo_status == "healthy"
        tools["lightpanda"] = browser_available
        tools["stagehand_v3"] = browser_available
        tools["playwright"] = browser_available
        tools["computer_use_gpt54"] = browser_available and bool(os.getenv("OPENAI_API_KEY"))

        # 注意: mutation_engineは監査対象に含めない（CLAUDE.md ルール22）

        return tools

    async def _audit_budget(self) -> dict:
        """予算状態チェック"""
        try:
            from tools.budget_guard import get_budget_guard
            bg = get_budget_guard()
            return await bg.get_budget_status()
        except Exception as e:
            logger.warning(f"予算状態チェック失敗: {e}")
            return {
                "daily_jpy_remaining": float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80"))),
                "monthly_jpy_remaining": float(os.getenv("MONTHLY_BUDGET_JPY", os.getenv("MONTHLY_API_BUDGET_JPY", "1500"))),
                "budget_mode": "unknown",
            }

    def _compute_diff(self, current: dict) -> Optional[dict]:
        """前回のスナップショットとの差分を計算"""
        if self._last_snapshot is None:
            return None

        diff = {}
        prev = self._last_snapshot

        # ノード状態の差分
        for node in NODE_DEFINITIONS:
            prev_status = prev.get("nodes", {}).get(node, {}).get("status")
            curr_status = current.get("nodes", {}).get(node, {}).get("status")
            if prev_status != curr_status:
                diff[f"node.{node}.status"] = {
                    "from": prev_status,
                    "to": curr_status,
                }

            # LLM状態の差分
            prev_llm = prev.get("nodes", {}).get(node, {}).get("local_model_status")
            curr_llm = current.get("nodes", {}).get(node, {}).get("local_model_status")
            if prev_llm != curr_llm:
                diff[f"node.{node}.local_model_status"] = {
                    "from": prev_llm,
                    "to": curr_llm,
                }

        # MCP差分
        for server in MCP_SERVERS:
            prev_mcp = prev.get("mcp_servers", {}).get(server)
            curr_mcp = current.get("mcp_servers", {}).get(server)
            if prev_mcp != curr_mcp:
                diff[f"mcp.{server}"] = {"from": prev_mcp, "to": curr_mcp}

        if diff:
            logger.info(f"能力監査差分検知: {len(diff)}件の変化")

        return diff if diff else None

    async def _save_snapshot(self, snapshot: dict, diff: Optional[dict]):
        """スナップショットをPostgreSQLに保存"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO capability_snapshots (snapshot_data, diff_from_previous)
                    VALUES ($1, $2)
                    """,
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    json.dumps(diff, ensure_ascii=False, default=str) if diff else None,
                )
            logger.info("能力監査スナップショットをPostgreSQLに保存")
        except Exception as e:
            logger.error(f"スナップショット保存失敗: {e}")

    async def _publish_snapshot(self, snapshot: dict):
        """スナップショットをNATSにパブリッシュ"""
        try:
            nats_client = await get_nats_client()
            node_name = os.getenv("THIS_NODE", "alpha")
            await nats_client.publish(
                f"agent.capability.{node_name}",
                snapshot,
            )
        except Exception as e:
            logger.warning(f"スナップショットNATSパブリッシュ失敗: {e}")

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "CAPABILITY_AUDIT", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def close(self):
        pass


# シングルトン
_instance: Optional[CapabilityAudit] = None


def get_capability_audit() -> CapabilityAudit:
    """CapabilityAuditのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = CapabilityAudit()
    return _instance


async def run_periodic_audit(interval_seconds: int = 1800):
    """定期監査ループ（30分間隔）"""
    audit = get_capability_audit()
    while True:
        try:
            await audit.run_full_audit()
        except Exception as e:
            logger.error(f"定期監査エラー: {e}")
        await asyncio.sleep(interval_seconds)
