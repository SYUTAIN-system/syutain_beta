"""
SYUTAINβ V25 DELTA常駐情報収集エージェント (Step 16)
設計書 第5章 5.3「自律調査」準拠

スケジュール情報収集・RSSフィード監視・YouTube監視を行う。
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.info_collector")

# スケジュール設定
FULL_PIPELINE_INTERVAL_HOURS = 4    # フルパイプラインは4時間間隔
RSS_CHECK_INTERVAL_MINUTES = 30     # RSS確認は30分間隔
YOUTUBE_CHECK_INTERVAL_HOURS = 6    # YouTube確認は6時間間隔

# YouTube監視チャンネル
YOUTUBE_CHANNELS = [
    {"name": "OpenAI", "channel_id": "UCXZCJLdBC09xxGZ6gcdrc6A"},
    {"name": "Google DeepMind", "channel_id": "UCP7jMXSY2xbc3KCAE0MHQ-A"},
    {"name": "Anthropic", "channel_id": "UCkSNT4S3gH7kMv6MhS3HQWQ"},
]

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


class InfoCollector:
    """DELTA常駐情報収集エージェント"""

    def __init__(self):
        self._nats_client = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._last_full_run: Optional[datetime] = None
        self._last_rss_run: Optional[datetime] = None
        self._last_youtube_run: Optional[datetime] = None

    async def start(self) -> None:
        """情報収集エージェントを起動"""
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.error(f"NATS接続失敗: {e}")

        self._running = True

        # スケジュールタスクを起動
        self._tasks.append(asyncio.create_task(self._full_pipeline_loop()))
        self._tasks.append(asyncio.create_task(self._rss_monitor_loop()))
        self._tasks.append(asyncio.create_task(self._youtube_monitor_loop()))

        logger.info("InfoCollector起動完了 (DELTA常駐)")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    # ===== フルパイプライン =====

    async def _full_pipeline_loop(self) -> None:
        """4時間間隔でフルパイプラインを実行"""
        while self._running:
            try:
                from tools.info_pipeline import InfoPipeline
                pipeline = InfoPipeline()
                result = await pipeline.run_full_pipeline()
                self._last_full_run = datetime.now()

                # 重要ニュースをNATSで配信
                await self._publish_important_items(result)

                logger.info(f"フルパイプライン完了: {result.get('total_saved', 0)}件")

                # 判断根拠トレース
                try:
                    await self._record_trace(
                        action="full_pipeline_run",
                        reasoning=f"フルパイプライン完了: {result.get('total_saved', 0)}件保存",
                        confidence=1.0,
                        context={"total_saved": result.get("total_saved", 0), "sources": list(result.keys())},
                    )
                except Exception:
                    pass

                await pipeline.close()
            except Exception as e:
                logger.error(f"フルパイプラインエラー: {e}")

            await asyncio.sleep(FULL_PIPELINE_INTERVAL_HOURS * 3600)

    # ===== RSS監視 =====

    async def _rss_monitor_loop(self) -> None:
        """30分間隔でRSSフィードを確認"""
        while self._running:
            try:
                new_items = await self._check_rss_feeds()
                self._last_rss_run = datetime.now()
                if new_items:
                    logger.info(f"RSS新着: {len(new_items)}件")
                    for item in new_items:
                        await self._notify_new_intel(item)
            except Exception as e:
                logger.error(f"RSS監視エラー: {e}")

            await asyncio.sleep(RSS_CHECK_INTERVAL_MINUTES * 60)

    async def _check_rss_feeds(self) -> list:
        """RSSフィードの新着を確認"""
        items = []
        rss_feeds = [
            ("https://blog.openai.com/rss/", "openai"),
            ("https://www.anthropic.com/feed", "anthropic"),
            ("https://blog.google/technology/ai/rss/", "google_ai"),
            ("https://huggingface.co/blog/feed.xml", "huggingface"),
        ]

        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser未インストール")
            return items

        for feed_url, source in rss_feeds:
            try:
                feed = await asyncio.to_thread(feedparser.parse, feed_url)
                for entry in feed.entries[:3]:
                    # 24時間以内の記事のみ
                    published = entry.get("published_parsed")
                    if published:
                        from time import mktime
                        pub_time = datetime.fromtimestamp(mktime(published))
                        if datetime.now() - pub_time > timedelta(hours=24):
                            continue

                    items.append({
                        "source": f"rss:{source}",
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "summary": entry.get("summary", "")[:500],
                    })
            except Exception as e:
                logger.warning(f"RSSフィード取得失敗 ({source}): {e}")

        return items

    # ===== YouTube監視 =====

    async def _youtube_monitor_loop(self) -> None:
        """6時間間隔でYouTubeチャンネルを確認"""
        while self._running:
            try:
                new_videos = await self._check_youtube_channels()
                self._last_youtube_run = datetime.now()
                if new_videos:
                    logger.info(f"YouTube新着: {len(new_videos)}件")
                    for video in new_videos:
                        await self._notify_new_intel(video)
            except Exception as e:
                logger.error(f"YouTube監視エラー: {e}")

            await asyncio.sleep(YOUTUBE_CHECK_INTERVAL_HOURS * 3600)

    async def _check_youtube_channels(self) -> list:
        """YouTube Data APIで新着動画を確認"""
        if not YOUTUBE_API_KEY:
            logger.warning("YOUTUBE_API_KEY未設定: YouTube監視スキップ")
            return []

        items = []
        for ch in YOUTUBE_CHANNELS:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "key": YOUTUBE_API_KEY,
                            "channelId": ch["channel_id"],
                            "part": "snippet",
                            "order": "date",
                            "maxResults": 3,
                            "type": "video",
                            "publishedAfter": (datetime.utcnow() - timedelta(hours=YOUTUBE_CHECK_INTERVAL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for item in data.get("items", []):
                        snippet = item.get("snippet", {})
                        video_id = item.get("id", {}).get("videoId", "")
                        items.append({
                            "source": f"youtube:{ch['name']}",
                            "title": snippet.get("title", ""),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "summary": snippet.get("description", "")[:500],
                        })
            except Exception as e:
                logger.warning(f"YouTube APIエラー ({ch['name']}): {e}")

        return items

    # ===== 通知 =====

    async def _publish_important_items(self, pipeline_result: dict) -> None:
        """重要度の高いアイテムをNATSで配信"""
        if not self._nats_client:
            return

        for source_key in ["tavily", "jina", "rss"]:
            for item in pipeline_result.get(source_key, []):
                if item.get("importance_score", 0) >= 0.6:
                    try:
                        await self._nats_client.publish(
                            "intel.news",
                            {
                                "source": item.get("source", ""),
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "importance": item.get("importance_score", 0),
                                "category": item.get("category", "other"),
                            },
                        )
                    except Exception as e:
                        logger.error(f"NATS配信失敗: {e}")

    async def _notify_new_intel(self, item: dict) -> None:
        """新着情報をDB永続化+NATSで通知"""
        # DB永続化（intel_itemsテーブルに保存）
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO intel_items
                       (source, title, url, summary, importance_score, review_flag)
                       VALUES ($1, $2, $3, $4, $5, 'pending_review')
                       ON CONFLICT DO NOTHING""",
                    item.get("source", "unknown"),
                    item.get("title", "")[:500],
                    item.get("url", ""),
                    item.get("summary", "")[:1000],
                    item.get("importance_score", 0.5),
                )
        except Exception as e:
            logger.error(f"intel_items DB保存失敗: {e}")

        # NATS通知
        if not self._nats_client:
            return
        try:
            await self._nats_client.publish(
                "intel.news",
                {
                    "source": item.get("source", ""),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                },
            )
        except Exception as e:
            logger.error(f"新着通知失敗: {e}")

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
                    "INFO_COLLECTOR", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    # ===== ステータス =====

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "last_full_run": str(self._last_full_run) if self._last_full_run else None,
            "last_rss_run": str(self._last_rss_run) if self._last_rss_run else None,
            "last_youtube_run": str(self._last_youtube_run) if self._last_youtube_run else None,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        collector = InfoCollector()
        await collector.start()
        logger.info("InfoCollector実行中 (Ctrl+Cで停止)")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await collector.stop()

    asyncio.run(main())
