"""
SYUTAINβ V25 スケジューラー (Step 23)
APScheduler ベースのタスクスケジューリング

- ハートビート: 30秒間隔
- Capability Audit: 1時間間隔
- 情報収集パイプライン: 6時間間隔
- 週次提案生成: 毎週月曜 09:00 JST
- 週次学習レポート: 毎週日曜 21:00 JST
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# ログ設定
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCHEDULER] %(name)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{LOG_DIR}/scheduler.log"),
    ],
)
logger = logging.getLogger("syutain.scheduler")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


# 時間帯別パワーモード
_current_power_mode = "day"  # "day" or "night"

POWER_MODES = {
    "night": {  # 23:00-07:00 JST
        "batch_content_generation": True,
        "parallel_inference": True,
        "local_llm_priority": 100,
        "max_concurrent_tasks": 6,
        "gpu_temp_limit": 85,
    },
    "day": {  # 07:00-23:00 JST
        "batch_content_generation": False,
        "parallel_inference": False,
        "local_llm_priority": 80,
        "max_concurrent_tasks": 3,
        "gpu_temp_limit": 80,
    },
}


def get_power_mode() -> str:
    """現在のパワーモードを返す"""
    return _current_power_mode


def get_power_config() -> dict:
    """現在のパワーモード設定を返す"""
    return POWER_MODES.get(_current_power_mode, POWER_MODES["day"])


class SyutainScheduler:
    """SYUTAINβ スケジューラー"""

    def __init__(self):
        self._scheduler = None
        self._nats_client = None

    async def start(self):
        """スケジューラーを起動"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from apscheduler.triggers.cron import CronTrigger

            self._scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")

            # NATS接続
            try:
                from tools.nats_client import get_nats_client
                self._nats_client = await get_nats_client()
            except Exception as e:
                logger.warning(f"NATS接続失敗（スケジューラー単体で継続）: {e}")

            # ジョブ登録
            self._scheduler.add_job(
                self.heartbeat,
                IntervalTrigger(seconds=30),
                id="heartbeat",
                name="ハートビート（30秒）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.capability_audit,
                IntervalTrigger(hours=1),
                id="capability_audit",
                name="Capability Audit（1時間）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.info_pipeline,
                IntervalTrigger(hours=12),
                id="info_pipeline",
                name="情報収集パイプライン（6時間）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.daily_proposal,
                CronTrigger(hour=7, minute=0),
                id="daily_proposal",
                name="日次提案生成（毎日 07:00）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.weekly_proposal,
                CronTrigger(day_of_week="mon", hour=9, minute=0),
                id="weekly_proposal",
                name="週次提案生成（月曜 09:00）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.reactive_proposal,
                IntervalTrigger(hours=6),
                id="reactive_proposal",
                name="リアクティブ提案（6時間）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.weekly_learning_report,
                CronTrigger(day_of_week="sun", hour=21, minute=0),
                id="weekly_learning_report",
                name="週次学習レポート（日曜 21:00）",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self.redispatch_orphan_tasks,
                IntervalTrigger(minutes=5),
                id="redispatch_orphan",
                name="孤立タスク再ディスパッチ（5分）",
                replace_existing=True,
            )

            # SNS投稿49件/日 分割生成（4バッチ）
            self._scheduler.add_job(
                self.night_batch_sns_1,
                CronTrigger(hour=22, minute=0, timezone=JST),
                id="night_batch_sns_1",
                name="SNS生成1: X島原+SYUTAIN 10件（22:00）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_2,
                CronTrigger(hour=22, minute=30, timezone=JST),
                id="night_batch_sns_2",
                name="SNS生成2: Bluesky前半13件（22:30）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_3,
                CronTrigger(hour=23, minute=0, timezone=JST),
                id="night_batch_sns_3",
                name="SNS生成3: Bluesky後半13件（23:00）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_4,
                CronTrigger(hour=23, minute=30, timezone=JST),
                id="night_batch_sns_4",
                name="SNS生成4: Threads13件（23:30）",
                replace_existing=True,
            )

            # SYSTEM_STATE.md定期更新（1時間）
            self._scheduler.add_job(
                self.update_system_state,
                IntervalTrigger(hours=1),
                id="system_state_update",
                name="SYSTEM_STATE.md更新（1時間）",
                replace_existing=True,
            )

            # OPERATION_LOG生成（毎日 00:00 JST）
            self._scheduler.add_job(
                self.generate_operation_log,
                CronTrigger(hour=0, minute=0),
                id="operation_log",
                name="運用ログ生成（00:00）",
                replace_existing=True,
            )

            # PostgreSQLバックアップ（毎日 03:00 JST）
            self._scheduler.add_job(
                self.backup_postgresql,
                CronTrigger(hour=3, minute=0),
                id="pg_backup",
                name="PostgreSQLバックアップ（03:00）",
                replace_existing=True,
            )

            # BTC価格取得（30分間隔）
            self._scheduler.add_job(
                self.crypto_price_snapshot,
                IntervalTrigger(minutes=30),
                id="crypto_price",
                name="暗号通貨価格取得（30分）",
                replace_existing=True,
            )

            # コスト予測チェック（6時間間隔）
            self._scheduler.add_job(
                self.cost_forecast,
                IntervalTrigger(hours=6),
                id="cost_forecast",
                name="コスト予測（6時間）",
                replace_existing=True,
            )

            # Blueskyエンゲージメント取得（12時間間隔）
            self._scheduler.add_job(
                self.bluesky_engagement_check,
                IntervalTrigger(hours=12),
                id="bluesky_engagement",
                name="Blueskyエンゲージメント取得（12時間）",
                replace_existing=True,
            )

            # Xエンゲージメント取得（12時間間隔）
            self._scheduler.add_job(
                self.x_engagement_check,
                IntervalTrigger(hours=12),
                id="x_engagement",
                name="Xエンゲージメント取得（12時間）",
                replace_existing=True,
            )

            # Threadsエンゲージメント取得（12時間間隔）
            self._scheduler.add_job(
                self.threads_engagement_check,
                IntervalTrigger(hours=12),
                id="threads_engagement",
                name="Threadsエンゲージメント取得（12時間）",
                replace_existing=True,
            )

            # モデル品質キャッシュ更新（1時間間隔）
            self._scheduler.add_job(
                self.refresh_model_quality,
                IntervalTrigger(hours=1),
                id="model_quality_refresh",
                name="モデル品質キャッシュ更新（1時間）",
                replace_existing=True,
            )

            # SQLiteバックアップ rsync集約（毎日 03:30 JST）
            self._scheduler.add_job(
                self.sqlite_backup_rsync,
                CronTrigger(hour=3, minute=30),
                id="sqlite_backup",
                name="SQLiteバックアップ（03:30）",
                replace_existing=True,
            )

            # デジタルツイン問いかけ（水曜・土曜 20:00 JST）
            self._scheduler.add_job(
                self.persona_question,
                CronTrigger(day_of_week="wed,sat", hour=20, minute=0),
                id="persona_question",
                name="デジタルツイン問いかけ（水土20:00）",
                replace_existing=True,
            )

            # 夜間モード切替（23:00 JST）
            self._scheduler.add_job(
                self.switch_to_night_mode,
                CronTrigger(hour=23, minute=0),
                id="night_mode",
                name="夜間モード切替（23:00）",
                replace_existing=True,
            )

            # 日中モード切替（07:00 JST）
            self._scheduler.add_job(
                self.switch_to_day_mode,
                CronTrigger(hour=7, minute=0),
                id="day_mode",
                name="日中モード切替（07:00）",
                replace_existing=True,
            )

            # 夜間バッチコンテンツ生成（23:30 JST）
            self._scheduler.add_job(
                self.night_batch_content,
                CronTrigger(hour=23, minute=30),
                id="night_batch",
                name="夜間バッチ生成（23:30）",
                replace_existing=True,
            )

            # 週次商品化ジョブ（毎週金曜 23:15 JST）
            self._scheduler.add_job(
                self.weekly_product_candidate,
                CronTrigger(day_of_week="fri", hour=23, minute=15),
                id="weekly_product",
                name="週次商品化候補生成（金曜23:15）",
                replace_existing=True,
            )

            # note記事ドラフト自動生成（23:45 JST）
            self._scheduler.add_job(
                self.note_draft_generation,
                CronTrigger(hour=23, minute=45),
                id="note_draft",
                name="note記事ドラフト生成（23:45）",
                replace_existing=True,
            )

            # 競合分析（日曜 03:00 JST）
            self._scheduler.add_job(
                self.competitive_analysis,
                CronTrigger(day_of_week="sun", hour=3, minute=0),
                id="competitive_analysis",
                name="競合分析（日曜03:00）",
                replace_existing=True,
            )

            # 承認タイムアウトチェック（1時間間隔）
            self._scheduler.add_job(
                self.approval_timeout_check,
                IntervalTrigger(hours=1),
                id="approval_timeout",
                name="承認タイムアウトチェック（1時間）",
                replace_existing=True,
            )

            # brain_handoff期限切れ処理（日次）
            self._scheduler.add_job(
                self.expire_old_handoffs,
                IntervalTrigger(hours=24),
                id="expire_handoffs",
                name="brain_handoff期限切れ処理（日次）",
                replace_existing=True,
            )

            # posting_queue自動投稿（毎分）
            self._scheduler.add_job(
                self.posting_queue_process,
                IntervalTrigger(minutes=1),
                id="posting_queue_process",
                name="posting_queue自動投稿（毎分）",
                replace_existing=True,
            )

            # Brain-α相互評価（毎日06:00）
            self._scheduler.add_job(
                self.brain_cross_evaluate,
                CronTrigger(hour=6, minute=0, timezone=JST),
                id="brain_cross_evaluate",
                name="Brain-α相互評価（毎日06:00）",
                replace_existing=True,
            )

            # 自律修復チェック（5分間隔）
            self._scheduler.add_job(
                self.self_heal_check,
                IntervalTrigger(minutes=5),
                id="self_heal_check",
                name="自律修復チェック（5分）",
                replace_existing=True,
            )

            # データ整合性チェック（毎日04:00）
            self._scheduler.add_job(
                self.data_integrity_check,
                CronTrigger(hour=4, minute=0, timezone=JST),
                id="data_integrity_check",
                name="データ整合性チェック（毎日04:00）",
                replace_existing=True,
            )

            # Brain-αセッション監視（10分間隔）
            self._scheduler.add_job(
                self.brain_alpha_health,
                IntervalTrigger(minutes=10),
                id="brain_alpha_health",
                name="Brain-αセッション監視（10分）",
                replace_existing=True,
            )

            # ノードヘルスチェック（5分間隔）
            self._scheduler.add_job(
                self.node_health_check,
                IntervalTrigger(minutes=5),
                id="node_health_check",
                name="ノードヘルスチェック（5分）",
                replace_existing=True,
            )

            # 異常検知→Discord通知（5分間隔）
            self._scheduler.add_job(
                self.anomaly_detection,
                IntervalTrigger(minutes=5),
                id="anomaly_detection",
                name="異常検知（5分）",
                replace_existing=True,
            )

            self._scheduler.start()
            logger.info("スケジューラー起動完了")

            # ジョブ一覧表示
            for job in self._scheduler.get_jobs():
                logger.info(f"  登録ジョブ: {job.name} (next: {job.next_run_time})")

        except Exception as e:
            logger.error(f"スケジューラー起動失敗: {e}")
            raise

    async def heartbeat(self):
        """ハートビート: ALPHAの状態をNATSで通知"""
        try:
            import psutil
            if self._nats_client:
                await self._nats_client.publish_simple(
                    "agent.heartbeat.alpha",
                    {
                        "node": "alpha",
                        "status": "alive",
                        "role": "orchestrator",
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "memory_percent": psutil.virtual_memory().percent,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
        except Exception as e:
            logger.error(f"ハートビート失敗: {e}")

    async def capability_audit(self):
        """Capability Audit: 全4台の能力スナップショットを取得"""
        logger.info("Capability Audit開始")
        try:
            snapshot = {
                "timestamp": datetime.utcnow().isoformat(),
                "nodes": {},
            }

            # 各ノードのハートビートからステータスを確認
            if self._nats_client:
                for node in ["alpha", "bravo", "charlie", "delta"]:
                    try:
                        resp = await self._nats_client.request(
                            f"agent.status.{node}",
                            {"request": "capability_snapshot"},
                            timeout=5.0,
                        )
                        snapshot["nodes"][node] = resp or {"status": "unreachable"}
                    except Exception:
                        snapshot["nodes"][node] = {"status": "unreachable"}

            # PostgreSQLに保存
            try:
                import asyncpg
                import json
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    await conn.execute(
                        """
                        INSERT INTO capability_snapshots (snapshot_data)
                        VALUES ($1)
                        """,
                        json.dumps(snapshot, ensure_ascii=False, default=str),
                    )
                finally:
                    await conn.close()
            except Exception as e:
                logger.error(f"Capability Audit保存失敗: {e}")

            logger.info(f"Capability Audit完了: {len(snapshot['nodes'])}ノード")

        except Exception as e:
            logger.error(f"Capability Audit失敗: {e}")

    async def info_pipeline(self):
        """情報収集パイプライン: DELTAに指示、またはALPHAで直接実行"""
        logger.info("情報収集パイプライン開始")
        nats_sent = False

        # 1. NATSでDELTAに指示を試みる
        try:
            if self._nats_client:
                await self._nats_client.publish_simple(
                    "intel.collect.delta",
                    {
                        "type": "scheduled_collection",
                        "timestamp": datetime.utcnow().isoformat(),
                        "sources": ["tavily", "jina", "rss", "youtube"],
                    },
                )
                logger.info("情報収集リクエストをDELTAに送信しました")
                nats_sent = True
        except Exception as e:
            logger.warning(f"NATS送信失敗（ALPHAで直接実行にフォールバック）: {e}")

        # 2. NATSが失敗した場合、ALPHAで直接実行
        if not nats_sent:
            try:
                from tools.info_pipeline import InfoPipeline
                pipeline = InfoPipeline()
                result = await pipeline.run_full_pipeline()
                logger.info(f"情報収集パイプライン（ALPHA直接実行）完了: {result.get('total_items', 0)}件")
            except Exception as e:
                logger.error(f"情報収集パイプライン（ALPHA直接実行）失敗: {e}")

    async def daily_proposal(self):
        """日次提案生成: 毎日7:00 JSTに提案を生成"""
        logger.info("日次提案生成開始")
        try:
            from agents.proposal_engine import get_proposal_engine
            engine = await get_proposal_engine()
            result = await engine.run_three_layer_pipeline(
                context="日次定期提案: 直近24時間の事業データに基づく",
                objective="revenue",
            )
            logger.info(
                f"日次提案完了: {result.get('title', '?')} "
                f"(score={result.get('total_score', 0)})"
            )
            # Discord通知
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"📋 日次提案: {result.get('title', '無題')} "
                    f"(スコア: {result.get('total_score', 0)}点)"
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"日次提案生成失敗: {e}")

    async def weekly_proposal(self):
        """週次提案生成: 「今週やるべき3手 + やめるべき1手」"""
        logger.info("週次提案生成開始")
        try:
            from agents.proposal_engine import get_proposal_engine
            engine = await get_proposal_engine()
            report = await engine.weekly_autonomous_proposal()
            logger.info(
                f"週次提案完了: "
                f"やるべき{len(report.get('summary', {}).get('do_top3', []))}手, "
                f"やめるべき{len(report.get('summary', {}).get('stop_top1', []))}手"
            )
            # Discord通知
            try:
                from tools.discord_notify import notify_discord
                summary = report.get("summary", {})
                do_items = summary.get("do_top3", [])
                msg = "📋 週次定例: 今週やるべき手\n"
                for i, item in enumerate(do_items[:3], 1):
                    msg += f"  {i}. {item.get('title', '?')}\n"
                stop_items = summary.get("stop_top1", [])
                if stop_items:
                    msg += f"  🛑 やめるべき: {stop_items[0].get('title', '?')}"
                await notify_discord(msg)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"週次提案生成失敗: {e}")

    async def reactive_proposal(self):
        """6時間ごとにリアクティブ提案を生成"""
        logger.info("リアクティブ提案生成開始")
        try:
            from agents.proposal_engine import get_proposal_engine
            engine = await get_proposal_engine()
            result = await engine.run_three_layer_pipeline(
                context="リアクティブ提案: 情報収集結果に基づく機会検出",
                objective="revenue",
            )
            # 70点以上の場合のみDiscord通知
            if result.get("total_score", 0) >= 70:
                try:
                    from tools.discord_notify import notify_discord
                    await notify_discord(
                        f"💡 自動提案: {result.get('title', '無題')} "
                        f"(スコア: {result.get('total_score', 0)}点) — 採用を検討してください"
                    )
                except Exception:
                    pass
            logger.info(
                f"リアクティブ提案完了: {result.get('title', '?')} "
                f"(score={result.get('total_score', 0)})"
            )
        except Exception as e:
            logger.error(f"リアクティブ提案生成失敗: {e}")

    async def redispatch_orphan_tasks(self):
        """5分おきに孤立pendingタスクを検出し、NATSでディスパッチを再試行"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # 30分以上前に作成されてpendingのままのタスクを取得
                rows = await conn.fetch(
                    """
                    SELECT id, type, assigned_node, input_data::text as input_text
                    FROM tasks
                    WHERE status = 'pending'
                      AND created_at < NOW() - INTERVAL '30 minutes'
                    ORDER BY created_at ASC
                    LIMIT 10
                    """
                )
                if not rows:
                    return

                logger.info(f"孤立pendingタスク: {len(rows)}件")

                for row in rows:
                    task_id = str(row["id"])
                    task_type = row["type"]
                    node = row["assigned_node"] or "alpha"

                    # approval_requestはapproval_queueに挿入（既にpending行がある場合はスキップ）
                    if task_type == "approval_request":
                        try:
                            # 同一task_idのpending承認リクエストが既にあるか確認
                            existing = await conn.fetchval(
                                """
                                SELECT COUNT(*) FROM approval_queue
                                WHERE status = 'pending'
                                  AND request_data->>'task_id' = $1
                                """,
                                task_id,
                            )
                            if existing > 0:
                                # 既にpending行があるのでスキップ、ステータスだけ更新
                                await conn.execute(
                                    "UPDATE tasks SET status = 'waiting_approval' WHERE id = $1 AND status = 'pending'",
                                    row["id"],
                                )
                                logger.debug(f"approval_request {task_id}: 既にpending承認あり、スキップ")
                                continue
                            input_data = json.loads(row["input_text"]) if row["input_text"] else {}
                            await conn.execute(
                                """
                                INSERT INTO approval_queue (request_type, request_data, status, requested_at)
                                VALUES ($1, $2, 'pending', NOW())
                                """,
                                "task_approval",
                                json.dumps({"task_id": task_id, **input_data}, ensure_ascii=False),
                            )
                            await conn.execute(
                                "UPDATE tasks SET status = 'waiting_approval' WHERE id = $1 AND status = 'pending'",
                                row["id"],
                            )
                            logger.info(f"approval_request {task_id} → approval_queue挿入 + waiting_approval")
                        except Exception as e:
                            logger.error(f"approval_request再ディスパッチ失敗: {e}")
                        continue

                    # その他のタスクはNATSでディスパッチ
                    if self._nats_client:
                        try:
                            await self._nats_client.publish_simple(
                                f"task.assign.{node}",
                                {
                                    "task_id": task_id,
                                    "type": task_type,
                                    "action": "redispatch",
                                },
                            )
                            logger.info(f"タスク {task_id} ({task_type}) → {node} に再ディスパッチ")
                        except Exception as e:
                            logger.error(f"タスク再ディスパッチ失敗: {e}")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"孤立タスク再ディスパッチ処理失敗: {e}")

    async def weekly_learning_report(self):
        """週次学習レポート生成"""
        logger.info("週次学習レポート生成開始")
        try:
            from agents.learning_manager import LearningManager
            lm = LearningManager()
            await lm.initialize()
            report = await lm.generate_weekly_report()
            if report and "error" not in report:
                logger.info("週次学習レポート生成完了")
            else:
                logger.warning(f"週次学習レポート生成に問題: {report.get('error', 'unknown')}")
        except Exception as e:
            logger.error(f"週次学習レポート生成失敗: {e}")

    async def backup_postgresql(self):
        """毎日03:00 JSTにPostgreSQLをバックアップ"""
        try:
            import subprocess
            backup_dir = os.path.join(os.path.dirname(__file__), "data", "backup")
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d")
            backup_file = os.path.join(backup_dir, f"syutain_beta_{timestamp}.sql.gz")

            result = subprocess.run(
                f"pg_dump syutain_beta | gzip > {backup_file}",
                shell=True, capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                size = os.path.getsize(backup_file)
                logger.info(f"PostgreSQLバックアップ完了: {backup_file} ({size}bytes)")
                from tools.event_logger import log_event
                await log_event("system.backup", "system", {
                    "file": backup_file, "size_bytes": size, "status": "success",
                })
                # 7日以上前のバックアップを削除
                import glob
                old_files = sorted(glob.glob(os.path.join(backup_dir, "syutain_beta_*.sql.gz")))[:-7]
                for f in old_files:
                    os.remove(f)
                    logger.info(f"古いバックアップ削除: {f}")
            else:
                logger.error(f"PostgreSQLバックアップ失敗: {result.stderr[:200]}")
        except Exception as e:
            logger.error(f"PostgreSQLバックアップエラー: {e}")

    async def crypto_price_snapshot(self):
        """30分間隔でBTC/JPY価格を取得しevent_logに記録"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.coin.z.com/public/v1/ticker?symbol=BTC_JPY")
                if resp.status_code == 200:
                    data = resp.json()
                    ticker = data.get("data", [{}])[0]
                    price = int(ticker.get("last", 0))
                    from tools.event_logger import log_event
                    await log_event("trade.price_snapshot", "system", {
                        "pair": "BTC_JPY", "price": price,
                        "high": int(ticker.get("high", 0)),
                        "low": int(ticker.get("low", 0)),
                        "volume": ticker.get("volume", "0"),
                    })
        except Exception as e:
            logger.warning(f"暗号通貨価格取得失敗: {e}")

    async def cost_forecast(self):
        """6時間間隔でAPI月末コスト予測"""
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # 直近7日の平均日次コスト
                avg_daily = await conn.fetchval("""
                    SELECT COALESCE(AVG(daily_total), 0) FROM (
                        SELECT date_trunc('day', recorded_at) as d, SUM(amount_jpy) as daily_total
                        FROM llm_cost_log
                        WHERE recorded_at > NOW() - INTERVAL '7 days'
                        GROUP BY d
                    ) sub
                """)
                # 月末までの残日数
                from calendar import monthrange
                now = datetime.now()
                days_in_month = monthrange(now.year, now.month)[1]
                remaining_days = days_in_month - now.day
                # 当月の累計
                monthly_total = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log WHERE date_trunc('month', recorded_at) = date_trunc('month', CURRENT_DATE)"
                )
                forecast = float(monthly_total or 0) + float(avg_daily or 0) * remaining_days
                monthly_budget = float(os.getenv("MONTHLY_BUDGET_JPY", os.getenv("MONTHLY_API_BUDGET_JPY", "1500")))

                from tools.event_logger import log_event
                await log_event("budget.forecast", "system", {
                    "monthly_total": round(float(monthly_total or 0), 2),
                    "avg_daily": round(float(avg_daily or 0), 2),
                    "remaining_days": remaining_days,
                    "forecast": round(forecast, 2),
                    "budget": monthly_budget,
                    "forecast_pct": round(forecast / monthly_budget * 100, 1) if monthly_budget > 0 else 0,
                })

                if forecast > monthly_budget * 0.8:
                    try:
                        from tools.discord_notify import notify_discord
                        await notify_discord(
                            f"⚠️ コスト予測警告: 月末推定¥{forecast:.0f} / 予算¥{monthly_budget:.0f} "
                            f"({forecast/monthly_budget*100:.0f}%)"
                        )
                    except Exception:
                        pass
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"コスト予測失敗: {e}")

    async def bluesky_engagement_check(self):
        """12時間間隔でBluesky投稿のエンゲージメント取得"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # sns.postedイベントからURIを取得（直近72時間）
                rows = await conn.fetch("""
                    SELECT payload->>'uri' as uri
                    FROM event_log
                    WHERE event_type = 'sns.posted'
                    AND payload->>'platform' = 'bluesky'
                    AND created_at > NOW() - INTERVAL '72 hours'
                    LIMIT 10
                """)
                if not rows:
                    return

                from tools.social_tools import get_bluesky_engagement
                from tools.event_logger import log_event

                for row in rows:
                    uri = row["uri"]
                    if not uri:
                        continue
                    engagement = await get_bluesky_engagement(uri)
                    if not engagement.get("error"):
                        await log_event("sns.engagement", "sns", engagement)
                        logger.info(f"Blueskyエンゲージメント: likes={engagement.get('like_count',0)}")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Blueskyエンゲージメント取得失敗: {e}")

    async def x_engagement_check(self):
        """12時間間隔でX投稿のエンゲージメント取得

        注意: X API Free tierではツイート取得不可。403が返る場合はログのみ。
        """
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # sns.postedイベントからpost_idを取得（直近7日）
                rows = await conn.fetch("""
                    SELECT payload->>'post_id' as post_id,
                           COALESCE(payload->>'account', 'syutain') as account
                    FROM event_log
                    WHERE event_type = 'sns.posted'
                    AND payload->>'platform' = 'x'
                    AND payload->>'post_id' IS NOT NULL
                    AND created_at > NOW() - INTERVAL '7 days'
                    LIMIT 20
                """)
                if not rows:
                    return

                from tools.social_tools import get_x_engagement
                from tools.event_logger import log_event

                for row in rows:
                    post_id = row["post_id"]
                    account = row["account"] or "syutain"
                    if not post_id:
                        continue
                    engagement = await get_x_engagement(post_id, account=account)
                    if engagement.get("error") == "free_tier_limitation":
                        logger.info("Xエンゲージメント: Free tierのため取得不可。スキップ。")
                        return  # Free tierなら全件スキップ
                    if not engagement.get("error"):
                        engagement["platform"] = "x"
                        await log_event("sns.engagement", "sns", engagement)
                        logger.info(f"Xエンゲージメント: likes={engagement.get('like_count',0)} post_id={post_id}")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Xエンゲージメント取得失敗: {e}")

    async def threads_engagement_check(self):
        """12時間間隔でThreads投稿のエンゲージメント取得"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # sns.postedイベントからpost_idを取得（直近7日）
                rows = await conn.fetch("""
                    SELECT payload->>'post_id' as post_id
                    FROM event_log
                    WHERE event_type = 'sns.posted'
                    AND payload->>'platform' = 'threads'
                    AND payload->>'post_id' IS NOT NULL
                    AND created_at > NOW() - INTERVAL '7 days'
                    LIMIT 20
                """)
                if not rows:
                    return

                from tools.social_tools import get_threads_engagement
                from tools.event_logger import log_event

                for row in rows:
                    post_id = row["post_id"]
                    if not post_id:
                        continue
                    engagement = await get_threads_engagement(post_id)
                    if not engagement.get("error"):
                        engagement["platform"] = "threads"
                        await log_event("sns.engagement", "sns", engagement)
                        logger.info(f"Threadsエンゲージメント: likes={engagement.get('like_count',0)} views={engagement.get('view_count',0)} post_id={post_id}")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Threadsエンゲージメント取得失敗: {e}")

    async def refresh_model_quality(self):
        """1時間間隔でモデル品質キャッシュを更新"""
        try:
            from tools.llm_router import refresh_model_quality_cache
            await refresh_model_quality_cache()
        except Exception as e:
            logger.error(f"モデル品質キャッシュ更新失敗: {e}")

    async def update_system_state(self):
        """1時間ごとにSYSTEM_STATE.mdを自動更新"""
        try:
            import subprocess
            result = subprocess.run(
                ["bash", "scripts/generate_system_state.sh"],
                cwd=os.path.dirname(__file__),
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info(f"SYSTEM_STATE.md更新完了: {result.stdout.strip()}")
            else:
                logger.warning(f"SYSTEM_STATE.md更新失敗: {result.stderr[:200]}")
        except Exception as e:
            logger.error(f"SYSTEM_STATE.md更新エラー: {e}")

    async def generate_operation_log(self):
        """毎日00:00に前日の運用ログを生成"""
        try:
            import subprocess
            result = subprocess.run(
                ["bash", "scripts/generate_operation_log.sh"],
                cwd=os.path.dirname(__file__),
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"OPERATION_LOG生成完了: {result.stdout.strip()}")
            else:
                logger.warning(f"OPERATION_LOG生成失敗: {result.stderr[:200]}")
        except Exception as e:
            logger.error(f"OPERATION_LOG生成エラー: {e}")

    async def sqlite_backup_rsync(self):
        """毎日03:30 JSTに各ノードのSQLite DBをALPHAに集約"""
        try:
            import subprocess
            backup_dir = os.path.join(os.path.dirname(__file__), "data", "backup", "nodes")
            os.makedirs(backup_dir, exist_ok=True)

            nodes = {
                "bravo": "100.75.146.9",
                "charlie": "100.70.161.106",
                "delta": "100.82.81.105",
            }
            results = []
            for node, ip in nodes.items():
                try:
                    r = subprocess.run(
                        ["rsync", "-az", f"shimahara@{ip}:~/syutain_beta/data/*.db", backup_dir],
                        capture_output=True, text=True, timeout=60,
                    )
                    results.append(f"{node}: {'OK' if r.returncode == 0 else 'FAILED'}")
                except Exception as e:
                    results.append(f"{node}: ERROR {e}")

            from tools.event_logger import log_event
            await log_event("system.sqlite_backup", "system", {
                "results": results, "backup_dir": backup_dir,
            })
            logger.info(f"SQLiteバックアップ: {', '.join(results)}")
        except Exception as e:
            logger.error(f"SQLiteバックアップ失敗: {e}")

    async def persona_question(self):
        """水・土 20:00 JSTにDiscord経由で島原に問いかけ"""
        try:
            from tools.llm_router import call_llm, choose_best_model_v6
            from tools.event_logger import log_event

            # 最近のシステム活動からコンテキストを生成
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                recent_proposals = await conn.fetch(
                    "SELECT title, score FROM proposal_history ORDER BY created_at DESC LIMIT 3"
                )
                recent_tasks = await conn.fetchval(
                    "SELECT count(*) FROM tasks WHERE updated_at > NOW() - INTERVAL '3 days'"
                )
            finally:
                await conn.close()

            context = f"直近3日: タスク{recent_tasks}件処理。"
            if recent_proposals:
                context += f" 最新提案: {', '.join(r['title'][:30] for r in recent_proposals)}"

            model_sel = choose_best_model_v6(
                task_type="drafting", quality="low",
                budget_sensitive=True, local_available=True,
            )
            result = await call_llm(
                prompt=f"""以下の状況を踏まえて、島原大知さんへの問いかけを1つだけ生成してください。
目的: 島原さんの判断パターン・思想・感情を引き出し、デジタルツインの資料にする。
状況: {context}

問いかけの種類（ランダムに1つ選択）:
- 今週の活動で最も直感に合っていた判断は？
- 最近のSYUTAINβに対して違和感を感じた部分は？
- VTuber/映像制作時代の経験で今に活かせそうなことは？
- 今のICP定義に修正したい部分は？
- 最近やめた方がいいと感じたことは？

問いかけテキストのみを出力（50文字以内）。""",
                system_prompt="SYUTAINβのデジタルツイン問いかけ生成。",
                model_selection=model_sel,
            )
            question = result.get("text", "").strip()
            if question and len(question) > 5:
                from tools.discord_notify import notify_discord
                await notify_discord(f"💭 島原さんへの問いかけ:\n{question}\n\n（Web UIチャットで回答してください）")
                await log_event("persona.question_sent", "system", {
                    "question": question, "context": context[:100],
                })
                logger.info(f"デジタルツイン問いかけ送信: {question[:50]}")
        except Exception as e:
            logger.error(f"デジタルツイン問いかけ失敗: {e}")

    async def switch_to_night_mode(self):
        """23:00 JST: 夜間モードに切替"""
        global _current_power_mode
        _current_power_mode = "night"
        logger.info("=== 夜間モード（Night Mode）に切替 === フルパワー運転開始")
        try:
            from tools.event_logger import log_event
            await log_event("system.power_mode", "system", {
                "mode": "night", "max_concurrent": 6, "local_priority": 100,
            })
            from tools.discord_notify import notify_discord
            await notify_discord("🌙 夜間モード開始。フルパワー運転（バッチ生成・並列推論・深い情報収集）")
        except Exception:
            pass

    async def switch_to_day_mode(self):
        """07:00 JST: 日中モードに切替"""
        global _current_power_mode
        _current_power_mode = "day"
        logger.info("=== 日中モード（Day Mode）に切替 === 省エネ運転開始")
        try:
            from tools.event_logger import log_event
            await log_event("system.power_mode", "system", {
                "mode": "day", "max_concurrent": 3, "local_priority": 80,
            })
        except Exception:
            pass

    async def night_batch_content(self):
        """23:30 JST: 夜間バッチコンテンツ生成（BRAVO+CHARLIE並列）"""
        if _current_power_mode != "night":
            return
        logger.info("夜間バッチコンテンツ生成開始（Best-of-N並列）")
        try:
            from tools.llm_router import call_llm_parallel

            # intel_itemsからトピックを動的生成（Q7修正）
            topics = []
            try:
                import asyncpg as _apg_nb
                _conn_nb = await _apg_nb.connect(DATABASE_URL)
                try:
                    intel_rows = await _conn_nb.fetch(
                        """SELECT title, summary, category FROM intel_items
                        WHERE importance_score >= 0.5
                        AND created_at > NOW() - INTERVAL '48 hours'
                        ORDER BY importance_score DESC LIMIT 5"""
                    )
                    if intel_rows:
                        for r in intel_rows[:3]:
                            title = r['title'] or ''
                            summary = (r['summary'] or '')[:100]
                            topics.append(f"{title}に関する実践的な解説と島原大知の見解（参考: {summary}）")
                        logger.info(f"夜間バッチ: intel_itemsから{len(topics)}トピック生成")
                finally:
                    await _conn_nb.close()
            except Exception as e:
                logger.warning(f"夜間バッチ intel_items取得失敗: {e}")

            # intelからトピックが取れなかった場合のフォールバック
            if not topics:
                topics = [
                    "AIエージェントの自律分散システムを構築する際の5つの教訓",
                    "ローカルLLM運用で学んだコスト最適化の実践テクニック",
                    "4台のPCで動くAI事業OSの設計思想",
                ]

            for i, topic in enumerate(topics):
                try:
                    result = await call_llm_parallel(
                        prompt=f"以下のテーマで500-800文字のnote記事ドラフトを書いてください。\nテーマ: {topic}\n\n"
                               f"注意: 読者はAIに興味があるが技術者ではない人。専門用語は避け、実体験に基づく具体例を入れる。",
                        system_prompt="SYUTAINβのコンテンツ生成エンジン。島原大知の実名ドキュメンタリースタイルで書く。",
                        nodes=["bravo", "charlie"],
                    )
                    if result.get("text"):
                        # 成果物保存
                        import os as _os
                        artifacts_dir = _os.path.join(_os.path.dirname(__file__), "data", "artifacts")
                        _os.makedirs(artifacts_dir, exist_ok=True)
                        filename = f"night_batch_{datetime.now().strftime('%Y%m%d')}_{i+1}.md"
                        filepath = _os.path.join(artifacts_dir, filename)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(f"# {topic}\n\n")
                            f.write(f"- 生成ノード: {result.get('source_node', '?')}\n")
                            f.write(f"- 並列数: {result.get('parallel_count', 1)}\n")
                            f.write(f"- 生成日: {datetime.now().isoformat()}\n\n---\n\n")
                            f.write(result["text"])
                        logger.info(f"夜間バッチ #{i+1}: {filepath}")
                        from tools.event_logger import log_event
                        await log_event("content.batch_generated", "task", {
                            "topic": topic[:50], "node": result.get("source_node"),
                            "length": len(result["text"]), "filepath": filepath,
                        })
                except Exception as e:
                    logger.error(f"夜間バッチ #{i+1} 失敗: {e}")

            # 品質0.7以上の成果物に対してcontent_multiplier実行
            try:
                import asyncpg as _apg
                conn = await _apg.connect(DATABASE_URL)
                try:
                    high_quality = await conn.fetch(
                        """SELECT id, type, output_data
                        FROM tasks
                        WHERE quality_score >= 0.7 AND output_data IS NOT NULL
                        AND status = 'completed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                        ORDER BY quality_score DESC LIMIT 1"""
                    )
                    if high_quality:
                        row = high_quality[0]
                        from tools.content_multiplier import multiply_content
                        result = await multiply_content(
                            source_text=str(row["output_data"])[:3000],
                            source_title=f"task_{row['id']}_{row['type']}",
                            source_type="artifact",
                        )
                        logger.info(f"夜間バッチ: content_multiplier {result['total_count']}件生成")
                finally:
                    await conn.close()
            except Exception as e:
                logger.error(f"夜間バッチ content_multiplier失敗: {e}")

            logger.info("夜間バッチコンテンツ生成完了")
        except Exception as e:
            logger.error(f"夜間バッチコンテンツ生成失敗: {e}")

    async def weekly_product_candidate(self):
        """毎週金曜23:15 JST: 直近1週間の高品質成果物から商品化候補を生成"""
        logger.info("週次商品化候補生成開始")
        try:
            import asyncpg as _apg
            conn = await _apg.connect(DATABASE_URL)
            try:
                # 直近1週間で品質0.7以上の成果物
                rows = await conn.fetch(
                    """SELECT id, type, quality_score, output_data
                    FROM tasks
                    WHERE quality_score >= 0.7 AND output_data IS NOT NULL
                    AND status = 'completed'
                    AND updated_at > NOW() - INTERVAL '7 days'
                    ORDER BY quality_score DESC LIMIT 3"""
                )
                if not rows:
                    logger.info("週次商品化: 品質0.7以上の成果物なし")
                    return

                best = rows[0]
                from tools.content_multiplier import multiply_content
                result = await multiply_content(
                    source_text=str(best["output_data"])[:3000],
                    source_title=f"weekly_product_{best['id']}",
                    source_type="product_candidate",
                )

                if result.get("booth_desc"):
                    import json
                    await conn.execute(
                        """INSERT INTO approval_queue (request_type, request_data, status)
                        VALUES ('product_publish', $1, 'pending')""",
                        json.dumps({
                            "content": result["booth_desc"],
                            "source_task_id": best["id"],
                            "quality_score": float(best["quality_score"]),
                        }, ensure_ascii=False),
                    )
                    logger.info(f"週次商品化: 候補生成→承認キュー投入 (task_id={best['id']})")

                    from tools.event_logger import log_event
                    await log_event("product.candidate_generated", "product", {
                        "source_task_id": best["id"],
                        "quality_score": float(best["quality_score"]),
                    })
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"週次商品化候補生成失敗: {e}")

    async def note_draft_generation(self):
        """23:45 JST: note記事ドラフト自動生成（曜日別テーマ）"""
        if _current_power_mode != "night":
            return
        logger.info("note記事ドラフト生成開始")
        try:
            from tools.llm_router import call_llm, choose_best_model_v6
            import os as _os

            weekday = datetime.now().weekday()  # 0=月曜
            theme_map = {
                0: ("週次収益報告", "今週のSYUTAINβの活動と収益状況をまとめる"),
                1: ("AI活用Tips", "非エンジニアでも使えるAI活用のコツを共有する"),
                2: ("AI開発失敗談", "SYUTAINβ開発で経験した失敗と学びを共有する"),
                3: ("AI開発失敗談", "SYUTAINβ開発で経験した失敗と学びを共有する"),
                4: ("AI活用Tips", "非エンジニアでも使えるAI活用のコツを共有する"),
                5: ("週末まとめ", "今週の振り返りと来週の展望"),
                6: ("自由テーマ", "AIと個人事業の未来について自由に書く"),
            }
            theme_name, theme_desc = theme_map.get(weekday, ("自由テーマ", "AIについて自由に書く"))

            # intel_itemsから直近トレンドを取得してプロンプトに注入（Q7修正）
            intel_hint = ""
            try:
                import asyncpg as _apg_nd
                _conn_nd = await _apg_nd.connect(DATABASE_URL)
                try:
                    intel_rows = await _conn_nd.fetch(
                        """SELECT title, summary, source FROM intel_items
                        WHERE importance_score >= 0.4
                        AND created_at > NOW() - INTERVAL '48 hours'
                        ORDER BY importance_score DESC LIMIT 5"""
                    )
                    if intel_rows:
                        intel_hint = "\n\n## 直近の市場動向（記事に活用できる素材）\n"
                        for r in intel_rows:
                            intel_hint += f"- [{r['source']}] {r['title']}: {(r['summary'] or '')[:80]}\n"
                finally:
                    await _conn_nd.close()
            except Exception as e:
                logger.warning(f"note_draft intel取得失敗: {e}")

            model_sel = choose_best_model_v6(
                task_type="content", quality="medium",
                budget_sensitive=True, local_available=True, needs_japanese=True,
            )
            result = await call_llm(
                prompt=f"note記事のドラフトを書いてください。\n\n"
                       f"テーマ: {theme_name}\n"
                       f"方針: {theme_desc}\n\n"
                       f"{intel_hint}\n"
                       f"注意事項:\n"
                       f"- 1000-2000文字\n"
                       f"- 見出し（##）を3-4個\n"
                       f"- 島原大知の一人称「僕」で書く\n"
                       f"- 読者は技術者ではない。平易な言葉で\n"
                       f"- 具体的な数字やエピソードを入れる\n"
                       f"- 上記の市場動向がテーマに関連すれば、具体例として言及する\n",
                system_prompt=f"SYUTAINβのnote記事ドラフト生成。島原大知のドキュメンタリースタイル。\n\n{self._load_anti_ai_guide()}",
                model_selection=model_sel,
            )

            draft = result.get("text", "").strip()
            if draft and len(draft) > 100:
                drafts_dir = _os.path.join(_os.path.dirname(__file__), "data", "artifacts", "note_drafts")
                _os.makedirs(drafts_dir, exist_ok=True)
                filename = f"note_{datetime.now().strftime('%Y%m%d')}_{theme_name}.md"
                filepath = _os.path.join(drafts_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(draft)
                logger.info(f"note記事ドラフト保存: {filepath} ({len(draft)}文字)")

                from tools.event_logger import log_event
                await log_event("content.note_draft", "task", {
                    "theme": theme_name, "length": len(draft),
                    "filepath": filepath, "model": result.get("model_used"),
                })

                # 品質が高ければDiscord通知
                if len(draft) > 500:
                    try:
                        from tools.discord_notify import notify_discord
                        await notify_discord(
                            f"📝 note記事ドラフト完成: {theme_name}\n"
                            f"文字数: {len(draft)}文字\n"
                            f"保存先: {filepath}\n"
                            f"プレビュー: {draft[:100]}..."
                        )
                    except Exception:
                        pass
            else:
                logger.warning(f"note記事ドラフト生成: テキストが短すぎ ({len(draft) if draft else 0}文字)")
        except Exception as e:
            logger.error(f"note記事ドラフト生成失敗: {e}")

    async def competitive_analysis(self):
        """週次競合分析（日曜03:00 JST）"""
        try:
            from tools.competitive_analyzer import run_competitive_analysis
            result = await run_competitive_analysis()
            logger.info(f"競合分析: {result['total']}件取得, {result['saved']}件保存")
        except Exception as e:
            logger.error(f"競合分析失敗: {e}")

    async def approval_timeout_check(self):
        """承認タイムアウトチェック（1時間間隔）"""
        try:
            from agents.approval_manager import get_approval_manager
            manager = await get_approval_manager()
            timed_out = await manager.check_timeouts()
            if timed_out:
                logger.info(f"承認タイムアウト: {len(timed_out)}件を自動却下")
        except Exception as e:
            logger.error(f"承認タイムアウトチェック失敗: {e}")

    async def node_health_check(self):
        """5分間隔でノードのヘルスチェックを実行しevent_logに記録"""
        try:
            import asyncpg
            import json
            import httpx

            from tools.event_logger import log_event

            NODE_IPS = {
                "bravo": "100.75.146.9",
                "charlie": "100.70.161.106",
                "delta": "100.82.81.105",
            }

            for node, ip in NODE_IPS.items():
                health = {"node": node, "ip": ip, "status": "unknown"}

                # Ollama応答確認
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(f"http://{ip}:11434/api/tags")
                        if resp.status_code == 200:
                            models = resp.json().get("models", [])
                            health["ollama"] = "ok"
                            health["ollama_models"] = [m.get("name", "") for m in models[:3]]
                        else:
                            health["ollama"] = f"error_{resp.status_code}"
                except Exception as e:
                    health["ollama"] = f"unreachable: {str(e)[:50]}"

                # GPU温度チェック（SSH経由）
                try:
                    import subprocess
                    gpu_temp_out = subprocess.check_output(
                        ["ssh", "-o", "ConnectTimeout=3", f"shimahara@{ip}",
                         "nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null"],
                        timeout=8, stderr=subprocess.DEVNULL,
                    ).decode().strip()
                    parts = [p.strip() for p in gpu_temp_out.split(",")]
                    if len(parts) >= 4:
                        health["gpu_temp_c"] = int(parts[0])
                        health["gpu_util_pct"] = int(parts[1])
                        health["gpu_mem_used_mb"] = int(parts[2])
                        health["gpu_mem_total_mb"] = int(parts[3])
                        health["status"] = "alive"
                        # GPU温度閾値チェック
                        config = get_power_config()
                        if health["gpu_temp_c"] > config.get("gpu_temp_limit", 80):
                            health["gpu_throttled"] = True
                            logger.warning(f"{node.upper()} GPU温度{health['gpu_temp_c']}℃ > 閾値{config['gpu_temp_limit']}℃")
                except Exception:
                    pass

                # CPU/MEM（SSH経由）
                try:
                    import subprocess
                    cpu_out = subprocess.check_output(
                        ["ssh", "-o", "ConnectTimeout=3", f"shimahara@{ip}",
                         "python3 -c \"import psutil;print(f'{psutil.cpu_percent()}:{psutil.virtual_memory().percent}')\" 2>/dev/null || "
                         "echo \"$(top -bn1 | grep 'Cpu(s)' | awk '{print $2}'):$(free | awk '/Mem:/{printf(\\\"%.1f\\\", $3/$2*100)}')\""],
                        timeout=8, stderr=subprocess.DEVNULL,
                    ).decode().strip()
                    if ":" in cpu_out:
                        cpu_val, mem_val = cpu_out.split(":")
                        health["cpu_percent"] = float(cpu_val)
                        health["memory_percent"] = float(mem_val)
                        health["status"] = "alive"
                except Exception:
                    pass

                severity = "info"
                if health.get("ollama", "").startswith("unreachable"):
                    severity = "error"
                elif health.get("ollama", "").startswith("error"):
                    severity = "warning"
                elif health.get("gpu_throttled"):
                    severity = "warning"

                await log_event(
                    "node.health", "node",
                    health,
                    severity=severity,
                    source_node=node,
                )

            # ALPHAのヘルスチェック
            import psutil
            alpha_health = {
                "node": "alpha", "status": "alive",
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
            }
            await log_event("node.health", "node", alpha_health, source_node="alpha")

        except Exception as e:
            logger.error(f"ノードヘルスチェック失敗: {e}")

    async def anomaly_detection(self):
        """5分間隔で異常検知 → Discord通知"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # 直近5分のerrorイベント数
                error_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM event_log
                    WHERE severity = 'error'
                    AND created_at > NOW() - INTERVAL '5 minutes'"""
                ) or 0

                # 直近5分のcriticalイベント
                critical_rows = await conn.fetch(
                    """SELECT event_type, payload, source_node FROM event_log
                    WHERE severity = 'critical'
                    AND created_at > NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at DESC LIMIT 5"""
                )

                # Ollamaダウン検知（直近のnode.healthイベント）
                ollama_down_nodes = await conn.fetch(
                    """SELECT DISTINCT payload->>'node' as node
                    FROM event_log
                    WHERE event_type = 'node.health'
                    AND payload->>'ollama' LIKE 'unreachable%'
                    AND created_at > NOW() - INTERVAL '10 minutes'"""
                )

                notifications = []

                # severity=errorが5分間に3件以上
                if error_count >= 3:
                    notifications.append(
                        f"⚠️ 異常検知: 直近5分でエラー{error_count}件発生"
                    )

                # severity=criticalは即座に通知
                for row in critical_rows:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                    notifications.append(
                        f"🚨 CRITICAL: {row['event_type']} on {row['source_node']} — "
                        f"{payload.get('reason', payload.get('error', ''))[:100]}"
                    )

                # Ollamaダウン
                for row in ollama_down_nodes:
                    notifications.append(
                        f"🔴 {row['node'].upper()}: Ollamaダウン検知"
                    )

                # Discord通知
                if notifications:
                    try:
                        from tools.discord_notify import notify_discord
                        msg = "\n".join(notifications[:5])
                        await notify_discord(msg)
                    except Exception as e:
                        logger.error(f"異常検知Discord通知失敗: {e}")

            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"異常検知処理失敗: {e}")

    async def _check_bluesky_duplicate(self, draft: str) -> bool:
        """Bluesky投稿の重複チェック。N-gram類似度0.5以上なら棄却。"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # 直近10件のBlueskyドラフトを取得（テーマ重複を広く検出）
                rows = await conn.fetch(
                    """SELECT request_data FROM approval_queue
                    WHERE request_type = 'bluesky_post'
                    ORDER BY requested_at DESC LIMIT 10"""
                )
                if not rows:
                    return False

                past_contents = []
                for row in rows:
                    rd = json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                    past_contents.append(rd.get("content", ""))

                # N-gram類似度チェック（3-gram: 日本語でも有効）
                def ngrams(text, n=3):
                    return set(text[i:i+n] for i in range(len(text) - n + 1))

                draft_ng = ngrams(draft)
                if not draft_ng:
                    return False

                for past in past_contents:
                    if not past:
                        continue
                    past_ng = ngrams(past)
                    if not past_ng:
                        continue
                    overlap = len(draft_ng & past_ng) / max(len(draft_ng | past_ng), 1)
                    if overlap > 0.5:
                        logger.info(f"Bluesky重複検知: N-gram類似度{overlap:.2f} — ドラフト棄却")
                        from tools.event_logger import log_event
                        await log_event(
                            "sns.duplicate_rejected", "sns",
                            {"similarity": round(overlap, 3), "draft_preview": draft[:80]},
                            severity="info",
                        )
                        return True
                return False
            finally:
                await conn.close()
        except Exception as e:
            logger.warning(f"Bluesky重複チェック失敗: {e}")
            return False

    async def bluesky_auto_draft(self):
        """Bluesky投稿ドラフト自動生成 → 品質チェック → 重複チェック → 承認キュー投入"""
        logger.info("Bluesky投稿ドラフト生成開始")
        try:
            from tools.llm_router import call_llm, choose_best_model_v6

            # 戦略アイデンティティ読み込み
            strategy = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "strategy_identity.md"), "r") as f:
                    strategy = f.read()
            except Exception:
                pass

            # Bluesky世界観読み込み
            worldview = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "bluesky_worldview.md"), "r") as f:
                    worldview = f.read()
            except Exception:
                pass

            # アンチAI文体ガイド読み込み
            anti_ai = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "anti_ai_writing.md"), "r") as f:
                    anti_ai = f.read()
            except Exception:
                pass

            # 直近10投稿の内容を取得して重複回避+テーマローテーション強制
            recent_contents = []
            try:
                import asyncpg
                import json as _json
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type = 'bluesky_post'
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_contents.append(rd.get("content", ""))
                finally:
                    await conn.close()
            except Exception:
                pass

            # 投稿パターンローテーション
            patterns = [
                "失敗談（今週壊したもの、想定外だったこと、諦めたこと）",
                "数字を出す途中経過（コスト、品質スコア、収益、処理時間）",
                "VTuber8年の経験からAI事業に翻訳した学び",
                "非エンジニアがAI事業OSを作る中での技術的挑戦の実況",
                "設計思想の仮説・問いかけ（まだ答えが出ていないこと）",
            ]
            # 直近の投稿数からローテーション位置を決定
            pattern_idx = len(recent_contents) % len(patterns)
            current_pattern = patterns[pattern_idx]

            model_sel = choose_best_model_v6(
                task_type="content", quality="medium", budget_sensitive=True, needs_japanese=True
            )

            avoid_instruction = ""
            if recent_contents:
                recent_summary = "\n".join(f"- {c[:80]}" for c in recent_contents[:5] if c)
                avoid_instruction = f"\n\n直近の投稿（以下と同じテーマ・構造は絶対に避けてください）:\n{recent_summary}"

            result = await call_llm(
                prompt=(
                    f"Blueskyに投稿するドラフトを1つ作ってください。\n"
                    f"- 300文字以内\n"
                    f"- 今回のパターン: 【{current_pattern}】\n"
                    f"- 結論を固めすぎない。対話の余地を残す\n"
                    f"- Xのコピペ禁止。深い会話・コア層育成が目的\n"
                    f"- 禁止語句を使わない\n"
                    f"- 島原大知の人格が見える内容にすること\n"
                    f"- 他の誰でも書ける汎用AI解説は禁止\n"
                    f"{avoid_instruction}\n"
                    f"投稿テキストのみを出力してください。"
                ),
                system_prompt=(
                    f"SYUTAINβのBluesky投稿ドラフト生成。\n\n"
                    f"{worldview}\n\n"
                    f"{anti_ai}\n\n"
                    f"{strategy}"
                ),
                model_selection=model_sel,
            )

            draft = result.get("text", "").strip()
            if not draft or len(draft) < 10:
                logger.warning("Blueskyドラフト生成: テキストが空または短すぎ")
                return

            # 品質スコアリング（0.6未満は棄却して再生成）
            quality_score = await self._score_bluesky_draft(draft)
            if quality_score < 0.6:
                logger.info(f"Blueskyドラフト: 品質{quality_score:.2f} < 0.6 — 棄却して再生成")
                from tools.event_logger import log_event
                await log_event(
                    "sns.quality_rejected", "sns",
                    {"quality_score": quality_score, "draft_preview": draft[:80]},
                    severity="info",
                )
                # 再生成1回だけ試行
                result2 = await call_llm(
                    prompt=(
                        f"前回の投稿ドラフトが品質不足でした。より具体的で、島原大知の人格が見える投稿を作ってください。\n"
                        f"- 300文字以内\n"
                        f"- パターン: 【{current_pattern}】\n"
                        f"- 具体的な数字、実体験、感情を含めること\n"
                        f"投稿テキストのみを出力してください。"
                    ),
                    system_prompt=f"{worldview}\n\n{anti_ai}\n\n{strategy}",
                    model_selection=model_sel,
                )
                draft = result2.get("text", "").strip()
                if not draft or len(draft) < 10:
                    return

            # NGワードチェック
            try:
                from tools.platform_ng_check import check_and_log
                ng_result = await check_and_log(draft, "bluesky")
                if not ng_result["passed"]:
                    logger.info(f"Blueskyドラフト: NGワード検出 — 棄却: {ng_result['violations']}")
                    return
            except Exception as e:
                logger.warning(f"NGワードチェック失敗（続行）: {e}")

            # 重複チェック
            if await self._check_bluesky_duplicate(draft):
                logger.info("Blueskyドラフト: 重複のため棄却。次回サイクルで再生成")
                return

            # 承認キューに投入
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('bluesky_post', $1, 'pending')""",
                    json.dumps({
                        "content": draft[:300],
                        "platform": "bluesky",
                        "auto_generated": True,
                        "pattern": current_pattern,
                        "quality_score": quality_score if 'quality_score' in dir() else None,
                    }, ensure_ascii=False),
                )
            finally:
                await conn.close()

            # イベント記録
            try:
                from tools.event_logger import log_event
                await log_event(
                    "sns.draft_created", "sns",
                    {"platform": "bluesky", "content_preview": draft[:80],
                     "pattern": current_pattern, "auto_generated": True},
                )
            except Exception:
                pass

            logger.info(f"Blueskyドラフト生成→承認キュー投入: {draft[:50]}...")
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(f"📝 Bluesky投稿ドラフト生成（承認待ち）: {draft[:100]}...")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Blueskyドラフト生成失敗: {e}")

    async def _score_bluesky_draft(self, draft: str) -> float:
        """Bluesky投稿ドラフトの品質スコアリング（0.0-1.0）"""
        score = 0.5  # ベース

        # 長さチェック: 50-300文字が適切
        if 50 <= len(draft) <= 300:
            score += 0.1
        elif len(draft) < 30:
            score -= 0.2

        # 具体性チェック: 数字を含むか
        import re
        if re.search(r'\d+', draft):
            score += 0.1

        # 人格チェック: 一人称を含むか
        if any(w in draft for w in ["私", "僕", "島原"]):
            score += 0.1

        # 問いかけチェック: 対話を誘発する問いかけを含むか
        if any(w in draft for w in ["？", "?", "でしょうか", "ですか", "みなさん", "皆さん"]):
            score += 0.1

        # 禁止語句チェック
        ng_words = ["誰でも簡単に", "絶対稼げる", "完全自動で放置", "AIに任せればOK", "最短で月"]
        if any(ng in draft for ng in ng_words):
            score -= 0.5

        # 汎用AI解説チェック（よくある定型表現）
        generic_phrases = ["AIとは", "人工知能とは", "機械学習とは", "ChatGPTとは"]
        if any(gp in draft for gp in generic_phrases):
            score -= 0.3

        return max(0.0, min(1.0, score))

    async def x_auto_draft_syutain(self):
        """X投稿ドラフト自動生成（SYUTAINβアカウント @syutain_beta）"""
        logger.info("X投稿ドラフト生成開始（SYUTAINβ）")
        try:
            from tools.llm_router import call_llm, choose_best_model_v6

            strategy = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "strategy_identity.md"), "r") as f:
                    strategy = f.read()
            except Exception:
                pass

            anti_ai = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "anti_ai_writing.md"), "r") as f:
                    anti_ai = f.read()
            except Exception:
                pass

            # 直近のX投稿とBluesky投稿を取得（重複回避）
            recent_posts = ""
            try:
                import asyncpg
                import json as _json
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('x_post', 'bluesky_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
                finally:
                    await conn.close()
            except Exception:
                pass

            model_sel = choose_best_model_v6(
                task_type="content", quality="medium", budget_sensitive=True, needs_japanese=True
            )

            patterns = [
                "データ・分析結果から見える構造的示唆",
                "AI事業OSの設計思想と改善ログ",
                "非エンジニアでも再現できる仕組み化の知見",
            ]
            import random
            current_pattern = random.choice(patterns)

            avoid_instruction = ""
            if recent_posts:
                avoid_instruction = f"\n\n直近の投稿（重複禁止）:\n{recent_posts}"

            result = await call_llm(
                prompt=(
                    f"Xに投稿するドラフトを1つ作ってください。\n"
                    f"- 280文字以内（厳守）\n"
                    f"- 一人称は「私」\n"
                    f"- パターン: 【{current_pattern}】\n"
                    f"- 結論→根拠→示唆の構造\n"
                    f"- 島原の人格が見えない汎用AI解説は禁止\n"
                    f"- 禁止語句を使わない\n"
                    f"{avoid_instruction}\n"
                    f"投稿テキストのみを出力してください。"
                ),
                system_prompt=(
                    f"SYUTAINβ公式Xアカウント（@syutain_beta）の投稿ドラフト生成。\n"
                    f"論理・設計・分析。結論→根拠→示唆。一人称「私」。\n\n{anti_ai}\n\n{strategy[:1500]}"
                ),
                model_selection=model_sel,
            )

            draft = result.get("text", "").strip()
            if not draft or len(draft) < 10:
                logger.warning("Xドラフト生成: テキストが空または短すぎ")
                return

            # 280文字超過時は切り詰め
            if len(draft) > 280:
                draft = draft[:277] + "..."

            # NGワードチェック
            try:
                from tools.platform_ng_check import check_and_log
                ng_result = await check_and_log(draft, "x")
                if not ng_result["passed"]:
                    logger.info(f"Xドラフト: NGワード検出 — 棄却")
                    return
            except Exception:
                pass

            # 重複チェック（N-gram）
            if await self._check_bluesky_duplicate(draft):
                logger.info("Xドラフト: 重複のため棄却")
                return

            # 承認キューに投入
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('x_post', $1, 'pending')""",
                    json.dumps({
                        "content": draft[:280],
                        "platform": "x",
                        "account": "syutain",
                        "auto_generated": True,
                        "pattern": current_pattern,
                    }, ensure_ascii=False),
                )
            finally:
                await conn.close()

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "x", "account": "syutain",
                    "content_preview": draft[:80], "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"Xドラフト生成→承認キュー投入: {draft[:50]}...")
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(f"📝 X投稿ドラフト生成（SYUTAINβ、承認待ち）: {draft[:100]}...")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Xドラフト生成失敗: {e}")

    async def x_auto_draft_shimahara(self):
        """X投稿ドラフト自動生成（島原アカウント @Sima_daichi）"""
        logger.info("X投稿ドラフト生成開始（島原）")
        try:
            from tools.llm_router import call_llm, choose_best_model_v6

            strategy = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "strategy_identity.md"), "r") as f:
                    strategy = f.read()
            except Exception:
                pass

            anti_ai = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "anti_ai_writing.md"), "r") as f:
                    anti_ai = f.read()
            except Exception:
                pass

            # 直近投稿取得（重複回避）
            recent_posts = ""
            try:
                import asyncpg
                import json as _json
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('x_post', 'bluesky_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
                finally:
                    await conn.close()
            except Exception:
                pass

            model_sel = choose_best_model_v6(
                task_type="content", quality="medium", budget_sensitive=True, needs_japanese=True
            )

            patterns = [
                "失敗談（今週壊したもの、想定外だったこと）と学び",
                "具体的な数字（コスト、品質スコア、収益）を含む途中経過報告",
                "VTuber8年の経験からAI事業に翻訳した学び",
                "非エンジニアとしての技術的挑戦と感情",
            ]
            import random
            current_pattern = random.choice(patterns)

            avoid_instruction = ""
            if recent_posts:
                avoid_instruction = f"\n\n直近の投稿（重複禁止）:\n{recent_posts}"

            result = await call_llm(
                prompt=(
                    f"Xに投稿するドラフトを1つ作ってください。\n"
                    f"- 280文字以内（厳守）\n"
                    f"- 一人称は「僕」\n"
                    f"- パターン: 【{current_pattern}】\n"
                    f"- 感情・失敗・数字のフックを入れる\n"
                    f"- 共感を誘う内容にする\n"
                    f"- 島原の人格が見えない汎用AI解説は禁止\n"
                    f"{avoid_instruction}\n"
                    f"投稿テキストのみを出力してください。"
                ),
                system_prompt=(
                    f"島原大知（@Sima_daichi）のX投稿ドラフト生成。\n"
                    f"共感・人格・物語。一人称「僕」。数字/失敗/感情/学びのどれかを含める。\n\n{anti_ai}\n\n{strategy[:1500]}"
                ),
                model_selection=model_sel,
            )

            draft = result.get("text", "").strip()
            if not draft or len(draft) < 10:
                logger.warning("島原Xドラフト生成: テキストが空または短すぎ")
                return

            if len(draft) > 280:
                draft = draft[:277] + "..."

            try:
                from tools.platform_ng_check import check_and_log
                ng_result = await check_and_log(draft, "x")
                if not ng_result["passed"]:
                    logger.info(f"島原Xドラフト: NGワード検出 — 棄却")
                    return
            except Exception:
                pass

            if await self._check_bluesky_duplicate(draft):
                logger.info("島原Xドラフト: 重複のため棄却")
                return

            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('x_post', $1, 'pending')""",
                    json.dumps({
                        "content": draft[:280],
                        "platform": "x",
                        "account": "shimahara",
                        "auto_generated": True,
                        "pattern": current_pattern,
                    }, ensure_ascii=False),
                )
            finally:
                await conn.close()

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "x", "account": "shimahara",
                    "content_preview": draft[:80], "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"島原Xドラフト生成→承認キュー投入: {draft[:50]}...")
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(f"📝 X投稿ドラフト生成（島原、承認待ち）: {draft[:100]}...")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"島原Xドラフト生成失敗: {e}")

    async def threads_auto_draft(self):
        """Threads投稿ドラフト自動生成（@syutain_beta）"""
        logger.info("Threads投稿ドラフト生成開始")
        try:
            from tools.llm_router import call_llm, choose_best_model_v6

            strategy = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "strategy_identity.md"), "r") as f:
                    strategy = f.read()
            except Exception:
                pass

            anti_ai = self._load_anti_ai_guide()

            worldview = ""
            try:
                with open(os.path.join(os.path.dirname(__file__), "prompts", "bluesky_worldview.md"), "r") as f:
                    worldview = f.read()
            except Exception:
                pass

            # 直近投稿取得（全プラットフォーム重複回避）
            recent_posts = ""
            try:
                import asyncpg
                import json as _json
                conn = await asyncpg.connect(DATABASE_URL)
                try:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('threads_post', 'bluesky_post', 'x_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
                finally:
                    await conn.close()
            except Exception:
                pass

            model_sel = choose_best_model_v6(
                task_type="content", quality="medium", budget_sensitive=True, needs_japanese=True
            )

            patterns = [
                "AI事業OSの開発途中経過（数字と感情を含める）",
                "VTuber8年の経験からAI事業に翻訳した学び",
                "非エンジニアが直面した技術的チャレンジと解決策",
                "失敗と修正の記録（具体的なエピソード）",
                "設計思想の仮説と問いかけ",
            ]
            import random
            current_pattern = random.choice(patterns)

            avoid_instruction = ""
            if recent_posts:
                avoid_instruction = f"\n\n直近の投稿（重複禁止）:\n{recent_posts}"

            result = await call_llm(
                prompt=(
                    f"Threadsに投稿するドラフトを1つ作ってください。\n"
                    f"- 500文字以内\n"
                    f"- パターン: 【{current_pattern}】\n"
                    f"- X(280文字)より詳しく書ける。体験談ベースで深掘りする\n"
                    f"- 問いかけを含めて対話を誘発する\n"
                    f"- 島原大知の人格が見える内容にすること\n"
                    f"- 汎用AI解説は禁止\n"
                    f"{avoid_instruction}\n"
                    f"投稿テキストのみを出力してください。"
                ),
                system_prompt=(
                    f"SYUTAINβのThreads投稿ドラフト生成。\n"
                    f"Blueskyより長め(500文字)、体験談ベース、問いかけ多め。\n\n"
                    f"{worldview}\n\n{anti_ai}\n\n{strategy[:1500]}"
                ),
                model_selection=model_sel,
            )

            draft = result.get("text", "").strip()
            if not draft or len(draft) < 10:
                logger.warning("Threadsドラフト生成: テキストが空または短すぎ")
                return

            if len(draft) > 500:
                draft = draft[:497] + "..."

            # NGワードチェック
            try:
                from tools.platform_ng_check import check_and_log
                ng_result = await check_and_log(draft, "threads")
                if not ng_result["passed"]:
                    logger.info("Threadsドラフト: NGワード検出 — 棄却")
                    return
            except Exception:
                pass

            # 重複チェック
            if await self._check_bluesky_duplicate(draft):
                logger.info("Threadsドラフト: 重複のため棄却")
                return

            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('threads_post', $1, 'pending')""",
                    json.dumps({
                        "content": draft[:500],
                        "platform": "threads",
                        "auto_generated": True,
                        "pattern": current_pattern,
                    }, ensure_ascii=False),
                )
            finally:
                await conn.close()

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "threads",
                    "content_preview": draft[:80],
                    "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"Threadsドラフト生成→承認キュー投入: {draft[:50]}...")
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(f"📝 Threads投稿ドラフト生成（承認待ち）: {draft[:100]}...")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Threadsドラフト生成失敗: {e}")

    def _load_anti_ai_guide(self) -> str:
        """アンチAI文体ガイドを読み込む"""
        try:
            with open(os.path.join(os.path.dirname(__file__), "prompts", "anti_ai_writing.md"), "r") as f:
                return f.read()
        except Exception:
            return ""

    async def _run_sns_batch(self, batch_num: int):
        """SNS分割バッチ共通実行"""
        from brain_alpha.sns_batch import generate_batch, BATCH_1_SCHEDULE, BATCH_2_SCHEDULE, BATCH_3_SCHEDULE, BATCH_4_SCHEDULE
        batches = {
            1: ("X島原+SYUTAIN", BATCH_1_SCHEDULE),
            2: ("Bluesky前半", BATCH_2_SCHEDULE),
            3: ("Bluesky後半", BATCH_3_SCHEDULE),
            4: ("Threads", BATCH_4_SCHEDULE),
        }
        name, schedule = batches[batch_num]
        try:
            result = await generate_batch(f"batch{batch_num}", schedule)
            logger.info(f"SNS生成{batch_num} [{name}]: {result.get('inserted', 0)}/{result.get('total', 0)}件")
            if batch_num == 4:  # 最終バッチ後にDiscord通知
                try:
                    from tools.discord_notify import notify_discord
                    await notify_discord(f"📝 SNS生成バッチ{batch_num} [{name}] 完了: {result.get('inserted', 0)}件")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"SNS生成{batch_num} [{name}] 失敗: {e}")

    async def night_batch_sns_1(self):
        await self._run_sns_batch(1)

    async def night_batch_sns_2(self):
        await self._run_sns_batch(2)

    async def night_batch_sns_3(self):
        await self._run_sns_batch(3)

    async def night_batch_sns_4(self):
        await self._run_sns_batch(4)

    async def posting_queue_process(self):
        """毎分: posting_queueからscheduled_at<=NOWの投稿を実行"""
        try:
            import asyncpg
            import json
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                rows = await conn.fetch(
                    """SELECT id, platform, account, content
                       FROM posting_queue
                       WHERE status = 'pending' AND scheduled_at <= NOW()
                       ORDER BY scheduled_at ASC LIMIT 3"""
                )
                for row in rows:
                    platform = row["platform"]
                    account = row["account"]
                    content = row["content"]
                    post_id = row["id"]

                    try:
                        result = {}
                        if platform == "bluesky":
                            from tools.social_tools import execute_approved_bluesky
                            result = await execute_approved_bluesky(content)
                        elif platform == "x":
                            from tools.social_tools import execute_approved_x
                            result = await execute_approved_x(content, account=account)
                        elif platform == "threads":
                            from tools.social_tools import execute_approved_threads
                            result = await execute_approved_threads(content)

                        if result.get("success"):
                            await conn.execute(
                                """UPDATE posting_queue SET status='posted', post_url=$1, posted_at=NOW()
                                   WHERE id=$2""",
                                result.get("url") or result.get("uri") or "", post_id,
                            )
                            logger.info(f"posting_queue#{post_id} → {platform} 投稿成功")
                        else:
                            # リトライ: 3回まで
                            retry_count = await conn.fetchval(
                                "SELECT COUNT(*) FROM event_log WHERE payload->>'posting_queue_id' = $1 AND event_type = 'sns.post_retry'",
                                str(post_id),
                            )
                            if retry_count and retry_count >= 3:
                                await conn.execute("UPDATE posting_queue SET status='failed' WHERE id=$1", post_id)
                                from tools.discord_notify import notify_discord
                                await notify_discord(f"❌ 投稿失敗(3回リトライ後): {platform}/{account} — {content[:60]}")
                            else:
                                from tools.event_logger import log_event
                                await log_event("sns.post_retry", "sns", {
                                    "posting_queue_id": str(post_id), "platform": platform,
                                    "retry": (retry_count or 0) + 1, "error": result.get("reason", "")[:100],
                                }, severity="warning")
                    except Exception as e:
                        logger.error(f"posting_queue#{post_id} 投稿エラー: {e}")
                        await conn.execute("UPDATE posting_queue SET status='failed' WHERE id=$1", post_id)
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"posting_queue処理エラー: {e}")

    async def self_heal_check(self):
        """5分間隔で全ノードサービス確認 + 自動修復"""
        try:
            from brain_alpha.self_healer import self_heal_check
            result = await self_heal_check()
            fixes = result.get("fixes", [])
            if fixes:
                logger.info(f"自律修復: {fixes}")
        except Exception as e:
            logger.error(f"自律修復チェック失敗: {e}")

    async def data_integrity_check(self):
        """毎日04:00 データ整合性チェック"""
        try:
            from brain_alpha.self_healer import data_integrity_check
            result = await data_integrity_check()
            if result.get("fixes"):
                logger.info(f"データ整合性修復: {result['fixes']}")
        except Exception as e:
            logger.error(f"データ整合性チェック失敗: {e}")

    async def brain_alpha_health(self):
        """10分間隔 Brain-αセッション監視"""
        try:
            from brain_alpha.self_healer import brain_alpha_health_check
            await brain_alpha_health_check()
        except Exception as e:
            logger.error(f"Brain-αヘルスチェック失敗: {e}")

    async def brain_cross_evaluate(self):
        """Brain-αの修正/レビュー効果を後追い検証"""
        try:
            from brain_alpha.cross_evaluator import schedule_evaluations
            result = await schedule_evaluations()
            total = result.get("fixes_evaluated", 0) + result.get("reviews_evaluated", 0)
            if total > 0:
                logger.info(f"Brain-α相互評価: {total}件評価完了")
        except Exception as e:
            logger.error(f"Brain-α相互評価失敗: {e}")

    async def expire_old_handoffs(self):
        """7日超過のpending brain_handoffをexpiredに更新"""
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                result = await conn.execute(
                    """UPDATE brain_handoff
                       SET status = 'expired'
                       WHERE status = 'pending'
                         AND created_at < NOW() - INTERVAL '7 days'"""
                )
                count = int(result.split()[-1]) if result else 0
                if count > 0:
                    logger.info(f"brain_handoff expired: {count}件")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"handoff期限切れ処理失敗: {e}")

    def stop(self):
        """スケジューラーを停止"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("スケジューラー停止")


async def main():
    scheduler = SyutainScheduler()
    await scheduler.start()

    # メインループ（スケジューラーはバックグラウンドで動作）
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
