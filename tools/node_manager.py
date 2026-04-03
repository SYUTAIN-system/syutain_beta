"""
SYUTAINβ V25 ノード管理 (Step 14)
設計書 第2章・第7章準拠

4台のノード (ALPHA/BRAVO/CHARLIE/DELTA) を追跡し、
NATSハートビート・ヘルスチェック・フォールバックを管理する。
"""

import os
import time
import asyncio
import logging
from typing import Optional
from pathlib import Path

import yaml
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.node_manager")

# ノード定義（設計書 第2章準拠）
NODE_NAMES = ["alpha", "bravo", "charlie", "delta"]

# ハートビート間隔（秒）
HEARTBEAT_INTERVAL = 30
# ノードダウン判定（ハートビートの3倍）
NODE_DOWN_THRESHOLD = HEARTBEAT_INTERVAL * 3


class NodeState:
    """単一ノードの状態"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.role: str = config.get("role", "unknown")
        self.tailscale_ip: str = config.get("tailscale_ip", "")
        self.ollama_url: str = self._build_ollama_url(config)
        self.status: str = "unknown"  # healthy / degraded / down / unknown
        self.last_heartbeat: float = 0.0
        self.cpu_pct: float = 0.0
        self.ram_pct: float = 0.0
        self.gpu_pct: float = 0.0
        self.disk_free_gb: float = 0.0
        self.ollama_ok: bool = False
        self.agents_running: list = config.get("agents", [])

    def _build_ollama_url(self, config: dict) -> str:
        llm_cfg = config.get("local_llm", {})
        if llm_cfg.get("ollama_url"):
            return llm_cfg["ollama_url"]
        ip = config.get("tailscale_ip", "localhost")
        return f"http://{ip}:11434"

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < NODE_DOWN_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "is_alive": self.is_alive,
            "last_heartbeat": self.last_heartbeat,
            "cpu_pct": self.cpu_pct,
            "ram_pct": self.ram_pct,
            "gpu_pct": self.gpu_pct,
            "disk_free_gb": self.disk_free_gb,
            "ollama_ok": self.ollama_ok,
            "agents": self.agents_running,
        }


class NodeManager:
    """全ノードを統合管理"""

    def __init__(self):
        self.nodes: dict[str, NodeState] = {}
        self._nats_client = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ===== 初期化 =====

    def load_configs(self, config_dir: str = "config") -> None:
        """config/node_*.yaml からノード設定を読み込む"""
        base = Path(config_dir)
        for name in NODE_NAMES:
            cfg_path = base / f"node_{name}.yaml"
            try:
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                else:
                    # 設定ファイルがなくても最低限登録
                    cfg = {"node_name": name, "role": name}
                    logger.warning(f"設定ファイルなし: {cfg_path}")
                self.nodes[name] = NodeState(name, cfg)
                logger.info(f"ノード設定ロード: {name} (role={cfg.get('role', 'unknown')})")
            except Exception as e:
                logger.error(f"ノード設定読み込み失敗 ({name}): {e}")

    async def start(self) -> None:
        """NATS接続とハートビートループを開始"""
        self.load_configs()
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()

            # ハートビート受信を購読
            for name in NODE_NAMES:
                await self._nats_client.subscribe(
                    f"agent.heartbeat.{name}",
                    self._on_heartbeat,
                )

            # 自ノードのハートビート送信開始
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("NodeManager開始: ハートビート監視中")
        except Exception as e:
            logger.error(f"NodeManager開始失敗: {e}")

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    # ===== ハートビート =====

    async def _heartbeat_loop(self) -> None:
        """30秒間隔でハートビートを送信"""
        this_node = os.getenv("THIS_NODE", "alpha")
        while True:
            try:
                if self._nats_client:
                    await self._nats_client.publish_simple(
                        f"agent.heartbeat.{this_node}",
                        {
                            "node": this_node,
                            "status": "alive",
                            "timestamp": time.time(),
                        },
                    )
            except Exception as e:
                logger.error(f"ハートビート送信失敗: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _on_heartbeat(self, msg) -> None:
        """ハートビートメッセージ受信"""
        try:
            import json
            data = json.loads(msg.data.decode())
            name = data.get("node", "")
            if name in self.nodes:
                node = self.nodes[name]
                node.last_heartbeat = data.get("timestamp", time.time())
                node.status = "healthy"
                # メトリクスが含まれていれば更新
                node.cpu_pct = data.get("cpu_pct", node.cpu_pct)
                node.ram_pct = data.get("ram_pct", node.ram_pct)
                node.gpu_pct = data.get("gpu_pct", node.gpu_pct)
                node.disk_free_gb = data.get("disk_free_gb", node.disk_free_gb)
        except Exception as e:
            logger.error(f"ハートビート処理エラー: {e}")

    # ===== ヘルスチェック =====

    async def health_check(self, node_name: str) -> dict:
        """指定ノードのヘルスチェック（Ollama ping + ディスク + GPU）"""
        if node_name not in self.nodes:
            return {"node": node_name, "status": "unknown", "error": "ノード未登録"}

        node = self.nodes[node_name]
        result = {"node": node_name, "ollama_ok": False, "disk_ok": False}

        # Ollama ping
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{node.ollama_url}/api/tags")
                node.ollama_ok = resp.status_code == 200
                result["ollama_ok"] = node.ollama_ok
                if node.ollama_ok:
                    result["models"] = [
                        m["name"] for m in resp.json().get("models", [])
                    ]
        except Exception as e:
            logger.warning(f"Ollamaヘルスチェック失敗 ({node_name}): {e}")
            node.ollama_ok = False

        # ディスク容量チェック（ローカルノードの場合のみ）
        this_node = os.getenv("THIS_NODE", "alpha")
        if node_name == this_node:
            try:
                import shutil
                usage = shutil.disk_usage("/")
                node.disk_free_gb = usage.free / (1024 ** 3)
                result["disk_free_gb"] = node.disk_free_gb
                result["disk_ok"] = node.disk_free_gb > 5.0  # 5GB以上で正常
            except Exception as e:
                logger.warning(f"ディスクチェック失敗: {e}")

        # 総合ステータス判定
        if node.is_alive and node.ollama_ok:
            node.status = "healthy"
        elif node.is_alive:
            node.status = "degraded"
        else:
            node.status = "down"

        result["status"] = node.status
        return result

    async def health_check_all(self) -> dict:
        """全ノードのヘルスチェック"""
        results = {}
        for name in self.nodes:
            try:
                results[name] = await self.health_check(name)
            except Exception as e:
                logger.error(f"ヘルスチェック失敗 ({name}): {e}")
                results[name] = {"node": name, "status": "error", "error": str(e)}
        return results

    # ===== フォールバック =====

    def get_available_nodes(self, role: Optional[str] = None) -> list[str]:
        """利用可能なノードのリストを返す"""
        available = []
        for name, node in self.nodes.items():
            if node.status in ("healthy", "degraded") and node.is_alive:
                if role is None or node.role == role:
                    available.append(name)
        return available

    def get_inference_nodes(self) -> list[str]:
        """推論可能なノードを優先順で返す（BRAVO/CHARLIE優先、ALPHAはオンデマンド）"""
        primary = []
        fallback = []
        for name in ["bravo", "charlie"]:
            if name in self.nodes and self.nodes[name].is_alive and self.nodes[name].ollama_ok:
                primary.append(name)
        # ALPHA はBRAVO/CHARLIE両方ダウン時のみ
        if not primary:
            if "alpha" in self.nodes and self.nodes["alpha"].is_alive:
                fallback.append("alpha")
        # DELTA は軽量タスク用の最終フォールバック
        if "delta" in self.nodes and self.nodes["delta"].is_alive and self.nodes["delta"].ollama_ok:
            fallback.append("delta")
        return primary + fallback

    def get_fallback_node(self, failed_node: str) -> Optional[str]:
        """指定ノードがダウンした場合のフォールバック先"""
        fallback_map = {
            "bravo": ["charlie", "alpha"],
            "charlie": ["bravo", "alpha"],
            "alpha": ["bravo", "charlie"],
            "delta": ["charlie", "bravo"],
        }
        candidates = fallback_map.get(failed_node, [])
        for candidate in candidates:
            if candidate in self.nodes and self.nodes[candidate].is_alive:
                return candidate
        return None

    # ===== スナップショット =====

    def get_snapshot(self) -> dict:
        """Capability Snapshot（設計書 第7章準拠）"""
        return {
            "timestamp": time.time(),
            "nodes": {
                name: node.to_dict() for name, node in self.nodes.items()
            },
            "inference_nodes": self.get_inference_nodes(),
            "available_nodes": self.get_available_nodes(),
        }


# シングルトン
_manager: Optional[NodeManager] = None


async def get_node_manager() -> NodeManager:
    global _manager
    if _manager is None:
        _manager = NodeManager()
        await _manager.start()
    return _manager


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        mgr = NodeManager()
        mgr.load_configs()
        snapshot = mgr.get_snapshot()
        for name, info in snapshot["nodes"].items():
            print(f"  {name}: role={info['role']}, status={info['status']}")

    asyncio.run(main())
