"""
SYUTAINβ V25 ノードルーティング (Step 14)
設計書 第2章・第5章準拠

タスクを能力・負荷に応じて適切なノードにルーティングする。
NATSのQueue Groupsでロードバランシングを実装。
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional, Callable

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.node_router")

# ノード別の対応タスク種別（設計書 第2章・第5章準拠）
NODE_CAPABILITIES = {
    "alpha": {
        "roles": ["orchestrator", "webui", "database"],
        "task_types": ["strategy", "proposal", "approval", "scheduling"],
        "llm_model": None,         # V30: ALPHAにLLMなし（2026-03-06撤去）
        "llm_mode": "off",         # V30: オーケストレーター専任
        "priority": 99,            # 推論タスクのルーティング対象外
    },
    "bravo": {
        "roles": ["executor", "browser", "computer_use", "inference", "high_quality_review"],
        "task_types": ["browser_action", "computer_use", "content", "inference", "coding", "quality_review"],
        "llm_model": "qwen3.5-9b",
        "llm_model_27b": "qwen3.5-27b",  # V30: highest_local用
        "llm_model_nemotron": "nemotron-jp",
        "llm_mode": "always",
        "priority": 1,
    },
    "charlie": {
        "roles": ["inference", "batch"],
        "task_types": ["inference", "content", "batch_process", "translation", "drafting"],
        "llm_model": "qwen3.5-9b",
        "llm_mode": "always",
        "priority": 1,
    },
    "delta": {
        "roles": ["monitor", "info_collector", "light_inference"],
        "task_types": ["monitoring", "info_collection", "tagging", "classification", "health_check"],
        "llm_model": "qwen3.5-4b",
        "llm_mode": "always",
        "priority": 2,
    },
}


class NodeRouter:
    """タスクルーティング・ロードバランシング"""

    def __init__(self):
        self._nats_client = None
        self._node_loads: dict[str, dict] = {
            name: {"busy": False, "queue_size": 0, "last_seen": 0}
            for name in NODE_CAPABILITIES
        }
        self._task_handlers: dict[str, Callable] = {}
        self._running = False
        self._charlie_win11 = False  # node_state参照用

    async def start(self) -> None:
        """ルーターを起動しNATS購読を開始"""
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.error(f"NATS接続失敗: {e}")
            return

        self._running = True

        # タスク割当を購読（Queue Groupでロードバランシング）
        this_node = os.getenv("THIS_NODE", "alpha")
        try:
            if self._nats_client and self._nats_client.nc:
                # 自ノード宛タスクを購読
                await self._nats_client.nc.subscribe(
                    f"task.assign.{this_node}",
                    cb=self._on_task_assigned,
                )
                # Queue Group: 推論リクエストのロードバランシング
                await self._nats_client.nc.subscribe(
                    "agent.request.llm",
                    queue="inference_workers",
                    cb=self._on_llm_request,
                )
                logger.info(f"NodeRouter起動 ({this_node}): タスク受信待機中")
        except Exception as e:
            logger.error(f"タスク購読失敗: {e}")

        # ハートビート受信で負荷情報を更新
        for node in NODE_CAPABILITIES:
            try:
                await self._nats_client.subscribe(
                    f"agent.heartbeat.{node}",
                    self._on_heartbeat,
                )
            except Exception as e:
                logger.error(f"ハートビート購読失敗 ({node}): {e}")

    async def stop(self) -> None:
        self._running = False

    # ===== ルーティング =====

    def route_task(self, task_type: str, prefer_node: Optional[str] = None) -> str:
        """タスク種別に最適なノードを選択"""
        # 指定ノードが使えればそちら
        if prefer_node and self._is_node_available(prefer_node):
            return prefer_node

        # タスク種別に対応できるノードを探す
        candidates = []
        for name, caps in NODE_CAPABILITIES.items():
            if task_type in caps["task_types"] and self._is_node_available(name):
                load = self._node_loads.get(name, {})
                candidates.append((name, caps["priority"], load.get("queue_size", 0)))

        if not candidates:
            # フォールバック: どこかしら生きているノード
            for name in NODE_CAPABILITIES:
                if self._is_node_available(name):
                    logger.warning(f"タスク種別 '{task_type}' に最適なノードなし。{name}にフォールバック")
                    return name
            logger.error(f"利用可能なノードがありません (task_type={task_type})")
            return "alpha"  # 最終手段

        # 優先度 → キュー長 でソート
        candidates.sort(key=lambda x: (x[1], x[2]))
        return candidates[0][0]

    def route_inference(self) -> str:
        """推論タスクの最適ノード（BRAVO/CHARLIE優先、設計書ルール13）"""
        # BRAVO/CHARLIEが主力
        for node in ["bravo", "charlie"]:
            if self._is_node_available(node):
                load = self._node_loads.get(node, {})
                if not load.get("busy", True):
                    return node

        # V30: ALPHAにLLMなし — スキップ

        # DELTA（軽量タスクのみ）
        if self._is_node_available("delta"):
            return "delta"

        return "bravo"  # 最終フォールバック

    async def dispatch_task(self, task_type: str, task_data: dict, prefer_node: Optional[str] = None) -> bool:
        """タスクをNATS経由でディスパッチ"""
        target = self.route_task(task_type, prefer_node)
        task_data["routed_to"] = target
        task_data["task_type"] = task_type
        task_data["routed_at"] = time.time()

        # 判断根拠トレース
        try:
            await self._record_trace(
                action=f"dispatch_task:{task_type}",
                reasoning=f"タスク種別 '{task_type}' をノード '{target}' にルーティング (prefer={prefer_node})",
                confidence=1.0,
                context={"task_type": task_type, "target_node": target, "prefer_node": prefer_node},
                task_id=task_data.get("task_id"),
                goal_id=task_data.get("goal_id"),
            )
        except Exception:
            pass

        try:
            if self._nats_client:
                return await self._nats_client.publish(
                    f"task.assign.{target}",
                    task_data,
                )
        except Exception as e:
            logger.error(f"タスクディスパッチ失敗 ({target}): {e}")
        return False

    async def dispatch_inference(self, prompt: str, system_prompt: str = "", **kwargs) -> Optional[dict]:
        """推論リクエストをQueue Group経由で分散"""
        request_data = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "timestamp": time.time(),
            **kwargs,
        }
        try:
            if self._nats_client:
                return await self._nats_client.request(
                    "agent.request.llm",
                    request_data,
                    timeout=120.0,
                )
        except Exception as e:
            logger.error(f"推論リクエスト失敗: {e}")
        return None

    # ===== コールバック =====

    async def _on_task_assigned(self, msg) -> None:
        """タスク割当受信"""
        try:
            data = json.loads(msg.data.decode())
            task_type = data.get("task_type", "unknown")
            logger.info(f"タスク受信: {task_type} (id={data.get('task_id', 'N/A')})")
            handler = self._task_handlers.get(task_type)
            if handler:
                await handler(data)
            else:
                logger.warning(f"未登録タスク種別: {task_type}")
        except Exception as e:
            logger.error(f"タスク処理エラー: {e}")

    async def _on_llm_request(self, msg) -> None:
        """LLM推論リクエスト受信（Queue Group）"""
        try:
            data = json.loads(msg.data.decode())
            from tools.llm_router import call_llm, choose_best_model_v6
            selection = choose_best_model_v6(task_type="drafting")
            result = await call_llm(
                data.get("prompt", ""),
                data.get("system_prompt", ""),
                model_selection=selection,
            )
            if msg.reply:
                await self._nats_client.nc.publish(
                    msg.reply,
                    json.dumps(result, ensure_ascii=False, default=str).encode(),
                )
        except Exception as e:
            logger.error(f"LLM推論処理エラー: {e}")
            if msg.reply:
                try:
                    await self._nats_client.nc.publish(
                        msg.reply,
                        json.dumps({"error": str(e)}, ensure_ascii=False).encode(),
                    )
                except Exception:
                    pass

    async def _on_heartbeat(self, msg) -> None:
        """ハートビートから負荷情報を更新"""
        try:
            data = json.loads(msg.data.decode())
            node = data.get("node", "")
            if node in self._node_loads:
                self._node_loads[node]["last_seen"] = time.time()
                self._node_loads[node]["busy"] = data.get("busy", False)
                self._node_loads[node]["queue_size"] = data.get("queue_size", 0)
        except Exception as e:
            logger.error(f"ハートビート処理エラー: {e}")

    # ===== 判断根拠トレース =====

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "NODE_ROUTER", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    # ===== ヘルパー =====

    def _is_node_available(self, name: str) -> bool:
        # node_stateがcharlie_win11の場合はCHARLIEにタスクを振らない
        if name == "charlie" and getattr(self, '_charlie_win11', False):
            return False
        load = self._node_loads.get(name, {})
        last_seen = load.get("last_seen", 0)
        # 初期状態（ハートビート未受信）は利用不可とする — 安全側に倒す
        return (time.time() - last_seen) < 90 if last_seen > 0 else False

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """タスクハンドラを登録"""
        self._task_handlers[task_type] = handler

    def get_routing_table(self) -> dict:
        """現在のルーティング状態を返す"""
        return {
            name: {
                "available": self._is_node_available(name),
                "load": self._node_loads.get(name, {}),
                "capabilities": NODE_CAPABILITIES.get(name, {}),
            }
            for name in NODE_CAPABILITIES
        }


# シングルトン
_router: Optional[NodeRouter] = None


async def get_node_router() -> NodeRouter:
    global _router
    if _router is None:
        _router = NodeRouter()
        await _router.start()
    return _router
