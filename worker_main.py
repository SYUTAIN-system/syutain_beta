"""
SYUTAINβ V25 Workerエントリーポイント (Step 23)
BRAVO / CHARLIE / DELTA ワーカープロセス

NATSに接続し、ノード役割に応じたエージェントを起動する。
タスク割り当てをサブスクライブし、適切なエージェントにディスパッチする。

使用法:
    THIS_NODE=bravo python worker_main.py
    THIS_NODE=charlie python worker_main.py
    THIS_NODE=delta python worker_main.py
"""

import os
import sys
import json
import signal
import asyncio
import logging
import subprocess
from datetime import datetime, timezone

import httpx
import psutil

from dotenv import load_dotenv

load_dotenv()

# ログ設定
THIS_NODE = os.getenv("THIS_NODE", "bravo")
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{THIS_NODE.upper()}] %(name)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{LOG_DIR}/{THIS_NODE}.log"),
    ],
)
logger = logging.getLogger("syutain.worker")

# ノード別の役割定義
NODE_ROLES = {
    "bravo": {
        "description": "Browser操作 / Computer Use / 高品質推論ワーカー / コンテンツ生成",
        "agents": ["browser_agent", "computer_use_agent"],
        "subscriptions": [
            "task.assign.bravo",
            # browser.action.bravo と computer.action.bravo は
            # BrowserAgent / ComputerUseAgent が自前でsubscribeするため
            # ここには含めない（二重subscribeでメッセージ競合を防止）
        ],
    },
    "charlie": {
        "description": "推論ワーカー / コンテンツ生成 / Browser操作（段階的有効化）",
        "agents": [],
        "subscriptions": [
            "task.assign.charlie",
        ],
    },
    "delta": {
        "description": "監視 / 情報収集 / 軽量推論 / 突然変異エンジンホスト",
        "agents": ["monitor_agent", "info_collector"],
        "subscriptions": [
            "task.assign.delta",
            "monitor.request.delta",
            "intel.collect.delta",
        ],
    },
}


class Worker:
    """ワーカーメインプロセス"""

    def __init__(self):
        self.node = THIS_NODE
        self.role = NODE_ROLES.get(self.node, NODE_ROLES["charlie"])
        self._nats_client = None
        self._agents = {}
        self._running = False

    async def start(self):
        """ワーカーを起動"""
        logger.info(f"ワーカー起動: {self.node} — {self.role['description']}")

        # NATS接続（指数バックオフリトライ: 1s, 2s, 4s, 8s, 16s）
        from tools.nats_client import get_nats_client
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self._nats_client = await get_nats_client()
                if self._nats_client and self._nats_client.nc:
                    logger.info(f"NATS接続成功 (attempt {attempt + 1})")
                    break
            except Exception as e:
                logger.error(f"NATS接続失敗 (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                backoff = 2 ** attempt  # 1, 2, 4, 8, 16
                logger.info(f"NATS再接続を{backoff}秒後にリトライ...")
                await asyncio.sleep(backoff)
        else:
            logger.error("NATS接続: 全リトライ失敗。ワーカー起動を中止")
            return

        # SQLiteローカルDB初期化
        try:
            from tools.db_init import init_sqlite_local
            init_sqlite_local(self.node)
        except Exception as e:
            logger.error(f"SQLite初期化失敗: {e}")

        # エージェント初期化
        await self._init_agents()

        # NATSサブスクリプション
        await self._setup_subscriptions()

        # ハートビートループ開始
        self._running = True
        asyncio.create_task(self._heartbeat_loop())

        logger.info(f"ワーカー '{self.node}' 起動完了。タスク待機中...")

        # メインループ
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _init_agents(self):
        """ノード役割に応じたエージェントを初期化"""
        agent_names = self.role.get("agents", [])

        if "browser_agent" in agent_names:
            try:
                from agents.browser_agent import BrowserAgent
                agent = BrowserAgent()
                if await agent.initialize():
                    self._agents["browser_agent"] = agent
                    logger.info("BrowserAgent初期化完了")
                else:
                    logger.warning("BrowserAgent初期化失敗（一部レイヤーが利用不可）")
            except Exception as e:
                logger.error(f"BrowserAgent初期化例外: {e}")

        if "computer_use_agent" in agent_names:
            try:
                from agents.computer_use_agent import ComputerUseAgent
                agent = ComputerUseAgent()
                if await agent.initialize():
                    self._agents["computer_use_agent"] = agent
                    logger.info("ComputerUseAgent初期化完了")
                else:
                    logger.warning("ComputerUseAgent初期化失敗")
            except Exception as e:
                logger.error(f"ComputerUseAgent初期化例外: {e}")

        # MonitorAgent（DELTA）
        if "monitor_agent" in agent_names:
            try:
                from agents.monitor_agent import MonitorAgent
                agent = MonitorAgent()
                self._agents["monitor_agent"] = agent
                logger.info("MonitorAgent初期化完了")
            except Exception as e:
                logger.error(f"MonitorAgent初期化例外: {e}")

        # InfoCollector（DELTA）
        if "info_collector" in agent_names:
            try:
                from agents.info_collector import InfoCollector
                agent = InfoCollector()
                self._agents["info_collector"] = agent
                logger.info("InfoCollector初期化完了")
            except Exception as e:
                logger.error(f"InfoCollector初期化例外: {e}")

    async def _setup_subscriptions(self):
        """NATSサブスクリプションを設定"""
        if not self._nats_client:
            return

        for subject in self.role.get("subscriptions", []):
            try:
                await self._nats_client.subscribe(subject, self._handle_message)
                logger.info(f"NATSサブスクリプション: {subject}")
            except Exception as e:
                logger.error(f"NATSサブスクリプション失敗 ({subject}): {e}")

        # ブラウザエージェントのNATSリスニング
        if "browser_agent" in self._agents:
            try:
                await self._agents["browser_agent"].start_listening()
            except Exception as e:
                logger.error(f"BrowserAgent NATSリスニング開始失敗: {e}")

        # Computer Useエージェント
        if "computer_use_agent" in self._agents:
            try:
                await self._agents["computer_use_agent"].start_listening()
            except Exception as e:
                logger.error(f"ComputerUseAgent NATSリスニング開始失敗: {e}")

    async def _handle_message(self, msg):
        """NATSメッセージハンドラ"""
        try:
            data = json.loads(msg.data.decode())
            subject = msg.subject
            logger.info(f"タスク受信: {subject}")

            # タスクタイプに基づいてディスパッチ
            task_type = data.get("type", "unknown")

            # intel.collect.delta: 情報収集パイプライン実行
            if subject == "intel.collect.delta" or data.get("type") == "scheduled_collection":
                if "info_collector" in self._agents:
                    try:
                        ic = self._agents["info_collector"]
                        from tools.info_pipeline import InfoPipeline
                        pipeline = InfoPipeline()
                        result = await pipeline.run_full_pipeline()
                        logger.info(f"情報収集パイプライン完了: {result.get('total_items', 0)}件")
                    except Exception as e:
                        logger.error(f"情報収集パイプライン実行失敗: {e}")
                        result = {"status": "error", "error": str(e)}
                else:
                    result = {"status": "info_collector_not_available"}
                    logger.warning("InfoCollector未初期化。情報収集をスキップ")

            elif task_type in ("browser", "browser_action", "extract", "navigate") and "browser_agent" in self._agents:
                target_url = data.get("url", "")
                if not target_url:
                    result = {"status": "skipped", "error": "URLが指定されていないためスキップ"}
                    logger.warning(f"browser_action: URLなしのためスキップ (task: {data.get('task_id', '?')})")
                else:
                    result = await self._agents["browser_agent"].execute(
                        action_type=data.get("action_type", "extract"),
                        url=target_url,
                        params=data.get("params", {}),
                    )
            elif task_type in ("computer_use", "login", "captcha") and "computer_use_agent" in self._agents:
                result = await self._agents["computer_use_agent"].execute_multi_step(
                    goal=data.get("goal", ""),
                    start_url=data.get("url", ""),
                )
            elif task_type in ("inference", "content", "drafting", "tagging", "classification",
                               "coding", "analysis", "research", "strategy", "proposal",
                               "compression", "log_formatting", "variation_gen",
                               "translation_draft", "monitoring", "health_check",
                               "note_article", "booth_description", "batch"):
                # ローカルLLM推論タスク
                try:
                    from tools.llm_router import call_llm, choose_best_model_v6
                    # ランタイムでOllamaの利用可否を確認
                    _local_ok = False
                    try:
                        async with httpx.AsyncClient(timeout=3.0) as _hc:
                            _resp = await _hc.get("http://localhost:11434/api/tags")
                            _local_ok = _resp.status_code == 200
                    except Exception:
                        _local_ok = False
                    model = choose_best_model_v6(
                        task_type=task_type, quality="medium",
                        local_available=_local_ok, budget_sensitive=True,
                    )
                    llm_result = await call_llm(
                        prompt=data.get("prompt", ""),
                        system_prompt=data.get("system_prompt"),
                        model_selection=model,
                    )
                    result = {"status": "success", "output": llm_result, "model": model.get("model")}
                except Exception as e:
                    result = {"status": "error", "error": str(e)}
                    logger.error(f"LLM推論タスク失敗: {e}")
            else:
                result = {"status": "unhandled", "task_type": task_type}
                logger.warning(f"未対応タスクタイプ: {task_type}")

            # リプライ
            if msg.reply:
                await self._nats_client.nc.publish(
                    msg.reply,
                    json.dumps(result, default=str).encode(),
                )

        except Exception as e:
            logger.error(f"メッセージ処理例外: {e}")

    @staticmethod
    def _get_gpu_info() -> dict | None:
        """nvidia-smiからGPU情報を取得（利用不可ならNone）"""
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 3:
                return {
                    "gpu_util_percent": float(parts[0]),
                    "gpu_mem_used_mb": float(parts[1]),
                    "gpu_mem_total_mb": float(parts[2]),
                }
        except Exception:
            pass
        return None

    async def _heartbeat_loop(self):
        """30秒間隔でハートビートを送信"""
        while self._running:
            try:
                if self._nats_client:
                    payload = {
                        "node": self.node,
                        "status": "alive",
                        "agents": list(self._agents.keys()),
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "memory_percent": psutil.virtual_memory().percent,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    gpu = self._get_gpu_info()
                    if gpu:
                        payload["gpu"] = gpu
                    await self._nats_client.publish_simple(
                        f"agent.heartbeat.{self.node}",
                        payload,
                    )
            except Exception as e:
                logger.error(f"ハートビート送信失敗: {e}")
            await asyncio.sleep(30)

    async def stop(self):
        """ワーカーを停止"""
        logger.info(f"ワーカー '{self.node}' 停止中...")
        self._running = False

        # エージェント終了
        for name, agent in self._agents.items():
            try:
                if hasattr(agent, "close"):
                    await agent.close()
            except Exception as e:
                logger.error(f"エージェント '{name}' 終了エラー: {e}")

        # NATS切断
        try:
            if self._nats_client:
                await self._nats_client.close()
        except Exception as e:
            logger.error(f"NATS切断エラー: {e}")

        logger.info(f"ワーカー '{self.node}' 停止完了")


def main():
    """メインエントリーポイント"""
    worker = Worker()

    # シグナルハンドラ
    loop = asyncio.new_event_loop()

    def signal_handler():
        loop.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows ではadd_signal_handlerが使えない
            pass

    try:
        loop.run_until_complete(worker.start())
    except KeyboardInterrupt:
        loop.run_until_complete(worker.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
