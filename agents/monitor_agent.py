"""
SYUTAINβ V25 DELTA常駐監視エージェント (Step 14)
設計書 第2章・第5章準拠

全ノードをNATSハートビートで監視し、
障害時はDiscord Webhookでアラートを送信する。
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.monitor_agent")

# 監視設定
HEARTBEAT_CHECK_INTERVAL = 30  # 秒
METRICS_COLLECT_INTERVAL = 60  # 秒
NODE_DOWN_THRESHOLD = 90       # ハートビート途絶判定（秒）

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


class MonitorAgent:
    """DELTA常駐監視エージェント"""

    def __init__(self):
        self._nats_client = None
        self._node_states: dict[str, dict] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        # アラート重複抑制（同一アラートは5分間隔）
        self._alert_cooldown: dict[str, float] = {}
        self._alert_cooldown_sec = 300
        # エスカレーション用: 同一エラー5分内3回検出
        self._error_tracker: dict[str, list[float]] = {}

    async def start(self) -> None:
        """監視エージェントを起動"""
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.error(f"NATS接続失敗: {e}")
            return

        self._running = True

        # ハートビート購読（全ノード）
        for node in ["alpha", "bravo", "charlie", "delta"]:
            try:
                await self._nats_client.subscribe(
                    f"agent.heartbeat.{node}",
                    self._on_heartbeat,
                )
            except Exception as e:
                logger.error(f"ハートビート購読失敗 ({node}): {e}")

        # メトリクス購読
        try:
            await self._nats_client.subscribe("monitor.metrics.*", self._on_metrics)
        except Exception as e:
            logger.error(f"メトリクス購読失敗: {e}")

        # バックグラウンドタスク
        self._tasks.append(asyncio.create_task(self._check_loop()))
        self._tasks.append(asyncio.create_task(self._collect_local_metrics()))

        logger.info("MonitorAgent起動完了 (DELTA常駐)")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    # ===== ハートビート受信 =====

    async def _on_heartbeat(self, msg) -> None:
        """ハートビート受信でノード状態を更新"""
        try:
            data = json.loads(msg.data.decode())
            node = data.get("node", "")
            self._node_states[node] = {
                "last_seen": time.time(),
                "status": data.get("status", "alive"),
                "cpu_pct": data.get("cpu_pct", 0),
                "ram_pct": data.get("ram_pct", 0),
                "gpu_pct": data.get("gpu_pct", 0),
                "disk_free_gb": data.get("disk_free_gb", 0),
            }
        except Exception as e:
            logger.error(f"ハートビート処理エラー: {e}")

    async def _on_metrics(self, msg) -> None:
        """メトリクスデータ受信"""
        try:
            data = json.loads(msg.data.decode())
            node = data.get("node", "")
            if node in self._node_states:
                self._node_states[node].update(data)
        except Exception as e:
            logger.error(f"メトリクス処理エラー: {e}")

    # ===== チェックループ =====

    async def _check_loop(self) -> None:
        """定期的にノード生存を確認しアラートを送信"""
        while self._running:
            try:
                await self._check_all_nodes()
            except Exception as e:
                logger.error(f"ノードチェックエラー: {e}")
            await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)

    async def _check_all_nodes(self) -> None:
        """全ノードの生存チェック"""
        now = time.time()
        for node in ["alpha", "bravo", "charlie", "delta"]:
            state = self._node_states.get(node, {})
            last_seen = state.get("last_seen", 0)
            elapsed = now - last_seen

            if last_seen == 0:
                # まだ一度もハートビートを受信していない
                continue

            if elapsed > NODE_DOWN_THRESHOLD:
                await self._send_alert(
                    severity="critical",
                    title=f"ノードダウン: {node.upper()}",
                    message=f"{node.upper()}のハートビートが{elapsed:.0f}秒途絶しています",
                    node=node,
                )
                # ダウンノードのタスクを別ノードに再振替（接続#19修正）
                await self._reassign_tasks_from_down_node(node)
            elif elapsed > NODE_DOWN_THRESHOLD * 0.6:
                await self._send_alert(
                    severity="warning",
                    title=f"ノード応答遅延: {node.upper()}",
                    message=f"{node.upper()}のハートビートが{elapsed:.0f}秒遅延しています",
                    node=node,
                )

            # リソース閾値チェック
            cpu = state.get("cpu_pct", 0)
            ram = state.get("ram_pct", 0)
            disk = state.get("disk_free_gb", 999)

            if cpu > 95:
                await self._send_alert("warning", f"CPU高負荷: {node.upper()}", f"CPU使用率 {cpu}%", node)
            if ram > 90:
                await self._send_alert("warning", f"RAM高使用: {node.upper()}", f"RAM使用率 {ram}%", node)
            if 0 < disk < 5:
                await self._send_alert("critical", f"ディスク残量少: {node.upper()}", f"残り {disk:.1f}GB", node)

        # 判断根拠トレース
        try:
            statuses = {n: self._node_states.get(n, {}).get("status", "unknown") for n in ["alpha", "bravo", "charlie", "delta"]}
            await self._record_trace(
                action="check_all_nodes",
                reasoning=f"ノード状態確認完了: {statuses}",
                confidence=1.0,
                context={"node_statuses": statuses},
            )
        except Exception:
            pass

    async def _reassign_tasks_from_down_node(self, down_node: str) -> None:
        """ダウンノードに割り当てられた実行中タスクを別ノードに再振替（接続#19）"""
        try:
            import asyncpg
            DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # ダウンノードの実行中タスクを検索
                stuck_tasks = await conn.fetch(
                    """SELECT id, type, assigned_node FROM tasks
                    WHERE assigned_node = $1 AND status = 'running'""",
                    down_node,
                )
                if not stuck_tasks:
                    return

                # 生存ノードの中からフォールバック先を選択
                alive_nodes = [
                    n for n in ["bravo", "charlie", "delta", "alpha"]
                    if n != down_node and self._node_states.get(n, {}).get("last_seen", 0) > time.time() - NODE_DOWN_THRESHOLD
                ]
                fallback = alive_nodes[0] if alive_nodes else "alpha"

                for task in stuck_tasks:
                    await conn.execute(
                        "UPDATE tasks SET assigned_node = $1, status = 'pending' WHERE id = $2",
                        fallback, task["id"],
                    )
                    logger.warning(f"タスク再振替: task#{task['id']} {down_node}→{fallback}")

                from tools.event_logger import log_event
                await log_event("monitor.task_reassign", "system", {
                    "down_node": down_node,
                    "reassigned_count": len(stuck_tasks),
                    "fallback_node": fallback,
                }, severity="warning")

                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"⚠️ ノードダウン再振替\n"
                    f"ダウン: {down_node.upper()}\n"
                    f"再振替: {len(stuck_tasks)}タスク → {fallback.upper()}"
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"タスク再振替エラー: {e}")

    # ===== ローカルメトリクス収集 =====

    async def _collect_local_metrics(self) -> None:
        """自ノード（DELTA）のメトリクスを収集しNATSに配信"""
        while self._running:
            try:
                metrics = self._gather_system_metrics()
                if self._nats_client:
                    this_node = os.getenv("THIS_NODE", "delta")
                    await self._nats_client.publish_simple(
                        f"monitor.metrics.{this_node}",
                        metrics,
                    )
            except Exception as e:
                logger.error(f"メトリクス収集エラー: {e}")
            await asyncio.sleep(METRICS_COLLECT_INTERVAL)

    def _gather_system_metrics(self) -> dict:
        """CPU/RAM/GPU/ディスクを収集"""
        metrics = {"node": os.getenv("THIS_NODE", "delta"), "timestamp": time.time()}
        try:
            import psutil
            metrics["cpu_pct"] = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            metrics["ram_pct"] = mem.percent
            metrics["ram_used_gb"] = round(mem.used / (1024 ** 3), 2)
            metrics["ram_total_gb"] = round(mem.total / (1024 ** 3), 2)
            disk = psutil.disk_usage("/")
            metrics["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
            metrics["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
        except ImportError:
            logger.warning("psutil未インストール: メトリクス収集制限あり")
        except Exception as e:
            logger.error(f"psutilメトリクス収集エラー: {e}")

        # GPU（nvidia-smi）
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 3:
                    metrics["gpu_pct"] = float(parts[0])
                    metrics["gpu_vram_used_mb"] = float(parts[1])
                    metrics["gpu_vram_total_mb"] = float(parts[2])
        except Exception:
            pass  # GPUなし or nvidia-smi未インストール

        return metrics

    # ===== アラート送信 =====

    async def _send_alert(
        self,
        severity: str,
        title: str,
        message: str,
        node: str = "",
    ) -> None:
        """NATSとDiscord Webhookでアラート送信"""
        # 重複抑制
        alert_key = f"{severity}:{node}:{title}"
        now = time.time()
        if alert_key in self._alert_cooldown:
            if now - self._alert_cooldown[alert_key] < self._alert_cooldown_sec:
                return
        self._alert_cooldown[alert_key] = now

        alert_data = {
            "severity": severity,
            "title": title,
            "message": message,
            "node": node,
            "timestamp": now,
        }

        # NATSにアラート配信
        try:
            if self._nats_client:
                await self._nats_client.publish(
                    f"monitor.alert.{severity}",
                    alert_data,
                )
        except Exception as e:
            logger.error(f"NATSアラート送信失敗: {e}")

        # Discord Webhook
        await self._send_discord_alert(severity, title, message, node)

        logger.warning(f"ALERT [{severity}] {title}: {message}")

        # エスカレーション: 同一エラー5分内3回 → claude_code_queue
        if severity in ("error", "critical"):
            try:
                now = time.time()
                error_key = f"{node}:{title}"
                self._error_tracker.setdefault(error_key, [])
                self._error_tracker[error_key].append(now)
                # 5分以内のみ保持
                self._error_tracker[error_key] = [t for t in self._error_tracker[error_key] if now - t < 300]
                if len(self._error_tracker[error_key]) >= 3:
                    from brain_alpha.escalation import escalate_to_queue
                    await escalate_to_queue(
                        category="recurring_error",
                        description=f"同一エラー5分内3回検出: {title} ({message[:100]})",
                        priority="high",
                        source_agent="monitor_agent",
                        auto_solvable=False,
                        context_files=[],
                        suggested_prompt=f"event_logでエラー '{title}' を調査し、根本原因を修正してください",
                    )
                    self._error_tracker[error_key] = []  # リセット
            except Exception as e:
                logger.debug(f"エスカレーション失敗（無視）: {e}")

    async def _send_discord_alert(
        self,
        severity: str,
        title: str,
        message: str,
        node: str,
    ) -> None:
        """Discord Webhookでアラート通知（設計書ルール12）"""
        if not DISCORD_WEBHOOK_URL:
            return
        color_map = {"info": 3447003, "warning": 16776960, "critical": 16711680}
        payload = {
            "embeds": [{
                "title": f"[{severity.upper()}] {title}",
                "description": message,
                "color": color_map.get(severity, 0),
                "fields": [{"name": "Node", "value": node.upper() or "N/A", "inline": True}],
            }]
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(DISCORD_WEBHOOK_URL, json=payload)
                if resp.status_code not in (200, 204):
                    logger.warning(f"Discord Webhook応答: {resp.status_code}")
        except Exception as e:
            logger.error(f"Discord Webhook送信失敗: {e}")

    # ===== 判断根拠トレース =====

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            import asyncpg
            DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "MONITOR_AGENT", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
            finally:
                await conn.close()
        except Exception:
            pass

    # ===== ステータス取得 =====

    def get_all_states(self) -> dict:
        return dict(self._node_states)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        agent = MonitorAgent()
        await agent.start()
        logger.info("MonitorAgent実行中 (Ctrl+Cで停止)")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await agent.stop()

    asyncio.run(main())
