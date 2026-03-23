"""
SYUTAINβ V25 NATS接続クライアント
NATS v2.12.5 + JetStreamでノード間メッセージング
"""

import os
import json
import asyncio
import logging
from typing import Optional, Callable, Any

import nats
from nats.js.api import StreamConfig, RetentionPolicy, StorageType
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.nats")


class SyutainNATSClient:
    """SYUTAINβ V25 NATSクライアント"""

    def __init__(self):
        self.nc: Optional[nats.NATS] = None
        self.js = None  # JetStream コンテキスト
        self.node_name = os.getenv("THIS_NODE", "alpha")
        self.nats_url = os.getenv("NATS_URL", "nats://localhost:4222")

    async def connect(self) -> bool:
        """NATSサーバーに接続"""
        try:
            self.nc = await nats.connect(
                self.nats_url,
                name=f"syutain-{self.node_name}",
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,  # 無限再接続
                error_cb=self._error_handler,
                disconnected_cb=self._disconnected_handler,
                reconnected_cb=self._reconnected_handler,
            )
            self.js = self.nc.jetstream()
            logger.info(f"NATS接続成功: {self.nats_url} (node={self.node_name})")
            return True
        except Exception as e:
            logger.error(f"NATS接続失敗: {e}")
            return False

    async def init_streams(self) -> bool:
        """JetStreamストリームを初期化（設計書2.3準拠）"""
        if not self.js:
            logger.error("JetStream未初期化。先にconnect()を呼んでください")
            return False

        streams = [
            # タスク管理ストリーム
            StreamConfig(
                name="TASKS",
                subjects=["task.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=100000,
                max_age=7 * 24 * 3600,  # 7日（秒）
                num_replicas=1,  # 4ノードクラスタでは最大3
            ),
            # エージェント間通信ストリーム
            StreamConfig(
                name="AGENTS",
                subjects=["agent.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=50000,
                max_age=24 * 3600,  # 1日（秒）
                num_replicas=1,
            ),
            # 提案・承認ストリーム
            StreamConfig(
                name="PROPOSALS",
                subjects=["proposal.>", "approval.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=10000,
                max_age=30 * 24 * 3600,  # 30日（秒）
                num_replicas=1,
            ),
            # 監視・ログストリーム
            StreamConfig(
                name="MONITOR",
                subjects=["monitor.>", "log.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=200000,
                max_age=3 * 24 * 3600,  # 3日（秒）
                num_replicas=1,
            ),
            # ブラウザ操作ストリーム（V25新規）
            StreamConfig(
                name="BROWSER",
                subjects=["browser.>", "computer.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=50000,
                max_age=7 * 24 * 3600,  # 7日（秒）
                num_replicas=1,
            ),
            # 情報収集ストリーム
            StreamConfig(
                name="INTEL",
                subjects=["intel.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_msgs=100000,
                max_age=30 * 24 * 3600,  # 30日（秒）
                num_replicas=1,
            ),
        ]

        ok = True
        for cfg in streams:
            try:
                await self.js.add_stream(cfg)
                logger.info(f"JetStreamストリーム '{cfg.name}' を作成/更新しました")
            except Exception as e:
                # 既に存在する場合は更新を試みる
                try:
                    await self.js.update_stream(cfg)
                    logger.info(f"JetStreamストリーム '{cfg.name}' を更新しました")
                except Exception as e2:
                    logger.error(f"ストリーム '{cfg.name}' の初期化失敗: {e2}")
                    ok = False

        return ok

    async def publish(self, subject: str, data: dict) -> bool:
        """メッセージをパブリッシュ（JetStream永続化）"""
        if not self.js:
            logger.error("JetStream未初期化")
            return False
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str).encode()
            ack = await self.js.publish(subject, payload)
            logger.debug(f"NATS publish: {subject} (seq={ack.seq})")
            return True
        except Exception as e:
            logger.error(f"NATS publish失敗 ({subject}): {e}")
            return False

    async def publish_simple(self, subject: str, data: dict) -> bool:
        """メッセージをパブリッシュ（JetStream非永続・Core NATS）"""
        if not self.nc:
            logger.error("NATS未接続")
            return False
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str).encode()
            await self.nc.publish(subject, payload)
            return True
        except Exception as e:
            logger.error(f"NATS publish_simple失敗 ({subject}): {e}")
            return False

    async def subscribe(self, subject: str, callback: Callable) -> Any:
        """Core NATSサブスクリプション"""
        if not self.nc:
            return None
        try:
            sub = await self.nc.subscribe(subject, cb=callback)
            logger.info(f"NATS subscribe: {subject}")
            return sub
        except Exception as e:
            logger.error(f"NATS subscribe失敗 ({subject}): {e}")
            return None

    async def request(self, subject: str, data: dict, timeout: float = 10.0) -> Optional[dict]:
        """Request-Replyパターン"""
        if not self.nc:
            return None
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str).encode()
            response = await self.nc.request(subject, payload, timeout=timeout)
            return json.loads(response.data.decode())
        except Exception as e:
            logger.error(f"NATS request失敗 ({subject}): {e}")
            return None

    async def heartbeat(self):
        """ハートビートを送信（30秒間隔で呼ばれる想定）"""
        await self.publish_simple(
            f"agent.heartbeat.{self.node_name}",
            {"node": self.node_name, "status": "alive"},
        )

    async def close(self):
        """接続を閉じる"""
        if self.nc:
            await self.nc.drain()
            logger.info("NATS接続を閉じました")

    # ===== コールバック =====
    async def _error_handler(self, e):
        logger.error(f"NATSエラー: {e}")

    async def _disconnected_handler(self):
        logger.warning("NATS切断")

    async def _reconnected_handler(self):
        logger.info("NATS再接続成功")


# シングルトンインスタンス
_client: Optional[SyutainNATSClient] = None


async def get_nats_client() -> SyutainNATSClient:
    """NATSクライアントのシングルトンを取得"""
    global _client
    if _client is None or _client.nc is None or _client.nc.is_closed:
        _client = SyutainNATSClient()
        await _client.connect()
    return _client


async def init_nats_and_streams() -> bool:
    """NATS接続とJetStreamストリームを初期化"""
    client = await get_nats_client()
    if not client.nc or client.nc.is_closed:
        return False
    return await client.init_streams()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        ok = await init_nats_and_streams()
        if ok:
            client = await get_nats_client()
            # テスト送信
            await client.publish("task.create", {
                "test": True,
                "message": "NATS JetStreamストリーム初期化テスト"
            })
            logger.info("NATS + JetStream初期化完了")
            await client.close()
        else:
            logger.error("NATS初期化失敗")

    asyncio.run(main())
