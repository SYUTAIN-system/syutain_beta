"""
SYUTAINβ V25 スケジューラー (Step 23)
APScheduler ベースのタスクスケジューリング

- ハートビート: 30秒間隔
- Capability Audit: 1時間間隔
- 情報収集パイプライン: 12時間間隔
- 週次提案生成: 毎週月曜 09:00 JST
- 週次学習レポート: 毎週日曜 21:00 JST
"""

import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

# ログ設定（RotatingFileHandler: 10MB x 5世代）
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_formatter = logging.Formatter("%(asctime)s [SCHEDULER] %(name)s %(levelname)s: %(message)s")
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_log_formatter)
_file_handler = RotatingFileHandler(
    f"{LOG_DIR}/scheduler.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_stream_handler, _file_handler],
)
logger = logging.getLogger("syutain.scheduler")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
REMOTE_SSH_USER = os.getenv("REMOTE_SSH_USER", "user")


# リモートノードIPマッピング（一元管理）
REMOTE_NODES = {
    "bravo": os.getenv("BRAVO_IP", "127.0.0.1"),
    "charlie": os.getenv("CHARLIE_IP", "127.0.0.1"),
    "delta": os.getenv("DELTA_IP", "127.0.0.1"),
}

# 時間帯別パワーモード
_current_power_mode = "day"  # "day" or "night"

POWER_MODES = {
    "night": {  # 23:00-09:00 JST
        "batch_content_generation": True,
        "parallel_inference": True,
        "local_llm_priority": 100,
        "max_concurrent_tasks": 6,
        "gpu_temp_limit": 85,
    },
    "day": {  # 09:00-23:00 JST
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
                self.auto_review_intel,
                IntervalTrigger(hours=6),
                id="auto_review_intel",
                name="intel_items自動レビュー（6時間）",
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
                misfire_grace_time=30,
            )

            # SNS投稿49件/日 分割生成（4バッチ）
            self._scheduler.add_job(
                self.night_batch_sns_1,
                CronTrigger(hour=22, minute=0, timezone="Asia/Tokyo"),
                id="night_batch_sns_1",
                name="SNS生成1: X島原+SYUTAIN 10件（22:00）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_2,
                CronTrigger(hour=22, minute=30, timezone="Asia/Tokyo"),
                id="night_batch_sns_2",
                name="SNS生成2: Bluesky前半13件（22:30）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_3,
                CronTrigger(hour=23, minute=0, timezone="Asia/Tokyo"),
                id="night_batch_sns_3",
                name="SNS生成3: Bluesky後半13件（23:00）",
                replace_existing=True,
            )
            self._scheduler.add_job(
                self.night_batch_sns_4,
                CronTrigger(hour=23, minute=30, timezone="Asia/Tokyo"),
                id="night_batch_sns_4",
                name="SNS生成4: Threads13件（23:30）",
                replace_existing=True,
            )

            # 日次コンテンツ生成 #1（07:30 JST — 海外トレンド先取り）
            self._scheduler.add_job(
                self.generate_daily_content_morning,
                CronTrigger(hour=7, minute=30, timezone="Asia/Tokyo"),
                id="daily_content_morning",
                name="日次コンテンツ#1 海外トレンド先取り（07:30）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 日次コンテンツ生成 #2（12:00 JST — SYUTAINβ実データベース）
            self._scheduler.add_job(
                self.generate_daily_content_midday,
                CronTrigger(hour=12, minute=0, timezone="Asia/Tokyo"),
                id="daily_content_midday",
                name="日次コンテンツ#2 実データベース（12:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 日次コンテンツ生成 #3（18:00 JST — 自由テーマ）
            self._scheduler.add_job(
                self.generate_daily_content_evening,
                CronTrigger(hour=18, minute=0, timezone="Asia/Tokyo"),
                id="daily_content_evening",
                name="日次コンテンツ#3 自由テーマ（18:00）",
                replace_existing=True,
                misfire_grace_time=60,
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
                misfire_grace_time=30,
            )

            # コスト予測チェック（6時間間隔）
            self._scheduler.add_job(
                self.cost_forecast,
                IntervalTrigger(hours=6),
                id="cost_forecast",
                name="コスト予測（6時間）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # エンゲージメント取得（12時間間隔、起動5分後に初回実行）
            _eng_first_run = datetime.now() + timedelta(minutes=5)
            self._scheduler.add_job(
                self.bluesky_engagement_check,
                IntervalTrigger(hours=12),
                id="bluesky_engagement",
                name="Blueskyエンゲージメント取得（12時間）",
                replace_existing=True,
                next_run_time=_eng_first_run,
            )

            self._scheduler.add_job(
                self.x_engagement_check,
                IntervalTrigger(hours=12),
                id="x_engagement",
                name="Xエンゲージメント取得（12時間）",
                replace_existing=True,
                next_run_time=_eng_first_run + timedelta(minutes=1),
            )

            self._scheduler.add_job(
                self.threads_engagement_check,
                IntervalTrigger(hours=12),
                id="threads_engagement",
                name="Threadsエンゲージメント取得（12時間）",
                replace_existing=True,
                next_run_time=_eng_first_run + timedelta(minutes=2),
            )

            # エンゲージメント分析（毎日06:30）
            self._scheduler.add_job(
                self.daily_engagement_analysis,
                CronTrigger(hour=6, minute=30),
                id="daily_engagement_analysis",
                name="エンゲージメント分析（毎日06:30）",
                replace_existing=True,
            )

            # モデル品質キャッシュ更新（1時間間隔、起動1分後に初回実行）
            self._scheduler.add_job(
                self.refresh_model_quality,
                IntervalTrigger(hours=1),
                id="model_quality_refresh",
                name="モデル品質キャッシュ更新（1時間）",
                replace_existing=True,
                next_run_time=datetime.now() + timedelta(minutes=1),
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

            # 日中モード切替（09:00 JST）
            self._scheduler.add_job(
                self.switch_to_day_mode,
                CronTrigger(hour=9, minute=0),
                id="day_mode",
                name="日中モード切替（09:00）",
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

            # note記事ドラフト自動生成（23:45 JST — 翌日向け）
            self._scheduler.add_job(
                self.note_draft_generation,
                CronTrigger(hour=23, minute=45, timezone="Asia/Tokyo"),
                id="note_draft",
                name="note記事ドラフト生成 翌日向け（23:45）",
                replace_existing=True,
                misfire_grace_time=60,
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
                misfire_grace_time=30,
            )

            # 提案自動承認→ゴール変換（30分間隔）
            self._scheduler.add_job(
                self.process_approved_proposals,
                IntervalTrigger(minutes=30),
                id="process_proposals",
                name="提案自動承認→ゴール変換（30分）",
                replace_existing=True,
                misfire_grace_time=30,
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
                misfire_grace_time=30,
            )

            # Brain-α相互評価（毎日06:00）
            self._scheduler.add_job(
                self.brain_cross_evaluate,
                CronTrigger(hour=6, minute=0, timezone="Asia/Tokyo"),
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
                misfire_grace_time=30,
            )

            # データ整合性チェック（毎日04:00）
            self._scheduler.add_job(
                self.data_integrity_check,
                CronTrigger(hour=4, minute=0, timezone="Asia/Tokyo"),
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
                misfire_grace_time=30,
            )

            # ノードヘルスチェック（5分間隔）
            self._scheduler.add_job(
                self.node_health_check,
                IntervalTrigger(minutes=5),
                id="node_health_check",
                name="ノードヘルスチェック（5分）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # 異常検知→Discord通知（5分間隔）
            self._scheduler.add_job(
                self.anomaly_detection,
                IntervalTrigger(minutes=5),
                id="anomaly_detection",
                name="異常検知（5分）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # 動的キーワード更新（毎日06:00 JST）
            self._scheduler.add_job(
                self.dynamic_keyword_update,
                CronTrigger(hour=6, minute=0, timezone="Asia/Tokyo"),
                id="dynamic_keyword_update",
                name="動的キーワード更新（毎日06:00）",
                replace_existing=True,
            )

            # intel_digest生成（毎日07:00 JST）
            self._scheduler.add_job(
                self.generate_intel_digest,
                CronTrigger(hour=7, minute=0, timezone="Asia/Tokyo"),
                id="generate_intel_digest",
                name="intel_digest生成（毎日07:00）",
                replace_existing=True,
            )

            # 深掘り記事取得バッチ（毎日12:00 JST）
            self._scheduler.add_job(
                self.deep_article_scrape_batch,
                CronTrigger(hour=12, minute=0, timezone="Asia/Tokyo"),
                id="deep_article_scrape",
                name="深掘り記事取得バッチ（毎日12:00）",
                replace_existing=True,
            )

            # 対話学習（1時間間隔）
            self._scheduler.add_job(
                self.chat_learning_job,
                IntervalTrigger(hours=1),
                id="chat_learning",
                name="対話学習（1時間）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # note記事品質チェック（30分間隔、コストガード付き）
            self._scheduler.add_job(
                self.note_quality_check,
                IntervalTrigger(minutes=30),
                id="note_quality_check",
                name="note記事品質チェック（30分）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # 日次サマリーDiscord通知（毎日 20:30 JST）
            self._scheduler.add_job(
                self.daily_summary_notify,
                CronTrigger(hour=20, minute=30, timezone="Asia/Tokyo"),
                id="daily_summary_notify",
                name="日次サマリーDiscord通知（20:30）",
                replace_existing=True,
            )

            # 商品パッケージング（1時間間隔）
            self._scheduler.add_job(
                self.product_packaging,
                IntervalTrigger(hours=1),
                id="product_packaging",
                name="商品パッケージング（1時間）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 経営日報（毎日 07:05 JST）
            self._scheduler.add_job(
                self.executive_briefing,
                CronTrigger(hour=7, minute=5, timezone="Asia/Tokyo"),
                id="executive_briefing",
                name="経営日報（毎日07:05）",
                replace_existing=True,
            )

            # === 収益・コンテンツ強化ジョブ ===

            # エンゲージメント分析（毎日06:30 JST）
            self._scheduler.add_job(
                self.engagement_analysis,
                CronTrigger(hour=6, minute=30, timezone="Asia/Tokyo"),
                id="engagement_analysis",
                name="エンゲージメント分析（毎日06:30）",
                replace_existing=True,
            )

            # 海外トレンド検出（毎日08:00 JST）
            self._scheduler.add_job(
                self.overseas_trend_detection,
                CronTrigger(hour=8, minute=0, timezone="Asia/Tokyo"),
                id="overseas_trend_detection",
                name="海外トレンド検出（毎日08:00）",
                replace_existing=True,
            )

            # SYUTAINβ日報（毎日12:00 JST — note無料連載用）
            self._scheduler.add_job(
                self.daily_syutain_report,
                CronTrigger(hour=12, minute=0, timezone="Asia/Tokyo"),
                id="daily_syutain_report",
                name="SYUTAINβ日報（毎日12:00）",
                replace_existing=True,
            )

            # Xスレッド（月木10:00 JST）
            self._scheduler.add_job(
                self.weekly_x_thread,
                CronTrigger(day_of_week="mon,thu", hour=10, minute=0, timezone="Asia/Tokyo"),
                id="weekly_x_thread",
                name="Xスレッド生成（月木10:00）",
                replace_existing=True,
            )

            # intel速報 X投稿（毎日11:30 JST）
            self._scheduler.add_job(
                self.intel_bulletin_x,
                CronTrigger(hour=11, minute=30, timezone="Asia/Tokyo"),
                id="intel_bulletin_x",
                name="intel速報X投稿（毎日11:30）",
                replace_existing=True,
            )

            # 週次インテルダイジェスト（毎週日曜20:00 JST）
            self._scheduler.add_job(
                self.weekly_intel_digest,
                CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="Asia/Tokyo"),
                id="weekly_intel_digest",
                name="週次インテルダイジェスト（日曜20:00）",
                replace_existing=True,
            )

            # ドキュメンタリー記事生成 #1（毎週水曜10:00 JST）
            self._scheduler.add_job(
                self.documentary_generation,
                CronTrigger(day_of_week="wed", hour=10, minute=0, timezone="Asia/Tokyo"),
                id="documentary_generation_wed",
                name="ドキュメンタリー記事生成#1（毎週水曜10:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # ドキュメンタリー記事生成 #2（毎週土曜10:00 JST）
            self._scheduler.add_job(
                self.documentary_generation,
                CronTrigger(day_of_week="sat", hour=10, minute=0, timezone="Asia/Tokyo"),
                id="documentary_generation_sat",
                name="ドキュメンタリー記事生成#2（毎週土曜10:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # バズアカウント分析（毎週月曜07:30 JST）
            self._scheduler.add_job(
                self.buzz_account_analysis,
                CronTrigger(day_of_week="mon", hour=7, minute=30, timezone="Asia/Tokyo"),
                id="buzz_account_analysis",
                name="バズ分析（毎週月曜07:30）",
                replace_existing=True,
            )

            # 収益機会リサーチ（毎月1日04:00 JST）
            self._scheduler.add_job(
                self.revenue_research,
                CronTrigger(day=1, hour=4, minute=0, timezone="Asia/Tokyo"),
                id="revenue_research",
                name="収益機会リサーチ（毎月1日04:00）",
                replace_existing=True,
            )

            # セマンティックキャッシュクリーンアップ（毎日04:15 JST）
            self._scheduler.add_job(
                self.semantic_cache_cleanup,
                CronTrigger(hour=4, minute=15, timezone="Asia/Tokyo"),
                id="semantic_cache_cleanup",
                name="セマンティックキャッシュ清掃（毎日04:15）",
                replace_existing=True,
            )

            # Karpathy Loop（毎日05:00 JST）
            self._scheduler.add_job(
                self.karpathy_loop_cycle,
                CronTrigger(hour=5, minute=0, timezone="Asia/Tokyo"),
                id="karpathy_loop",
                name="Karpathy自律改善（毎日05:00）",
                replace_existing=True,
            )

            # 収益パイプラインヘルスチェック（毎日07:30 JST）
            self._scheduler.add_job(
                self.revenue_health_check,
                CronTrigger(hour=7, minute=30, timezone="Asia/Tokyo"),
                id="revenue_health_check",
                name="収益パイプラインチェック（毎日07:30）",
                replace_existing=True,
            )

            # === Harness Engineering ジョブ ===

            # ゴミ収集（毎週月曜 05:00 JST）
            self._scheduler.add_job(
                self.garbage_collection,
                CronTrigger(day_of_week="mon", hour=5, minute=0, timezone="Asia/Tokyo"),
                id="garbage_collection",
                name="ゴミ収集（毎週月曜05:00）",
                replace_existing=True,
            )

            # フィーチャーテスト（毎日 05:30 JST）
            self._scheduler.add_job(
                self.feature_test_run,
                CronTrigger(hour=5, minute=30, timezone="Asia/Tokyo"),
                id="feature_test_run",
                name="フィーチャーテスト（毎日05:30）",
                replace_existing=True,
            )

            # ドキュメントガーデニング（毎週日曜 04:00 JST）
            self._scheduler.add_job(
                self.doc_gardening,
                CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="Asia/Tokyo"),
                id="doc_gardening",
                name="ドキュメントガーデニング（日曜04:00）",
                replace_existing=True,
            )

            # note.com自動公開チェック（30分間隔）
            self._scheduler.add_job(
                self.note_auto_publish,
                IntervalTrigger(minutes=30),
                id="note_auto_publish",
                name="note.com自動公開チェック（30分）",
                replace_existing=True,
                misfire_grace_time=30,
            )

            # ログクリーンアップ（毎日04:30 JST）— 7日超のログファイルを削除
            self._scheduler.add_job(
                self.log_cleanup,
                CronTrigger(hour=4, minute=30, timezone="Asia/Tokyo"),
                id="log_cleanup",
                name="ログクリーンアップ（毎日04:30）",
                replace_existing=True,
            )

            # 承認キュー自動クリーンアップ（毎日05:00 JST）
            self._scheduler.add_job(
                self.approval_queue_cleanup,
                CronTrigger(hour=5, minute=0, timezone="Asia/Tokyo"),
                id="approval_queue_cleanup",
                name="承認キュー自動クリーンアップ（毎日05:00）",
                replace_existing=True,
            )

            # 夜間メモリ統合（毎日03:45 JST）
            self._scheduler.add_job(
                self.memory_consolidation,
                CronTrigger(hour=3, minute=45, timezone="Asia/Tokyo"),
                id="memory_consolidation",
                name="メモリ統合（毎日03:45）",
                replace_existing=True,
            )

            # 海外トレンド先取り検出（毎日08:00 JST）
            self._scheduler.add_job(
                self.detect_overseas_trends,
                CronTrigger(hour=8, minute=0, timezone="Asia/Tokyo"),
                id="overseas_trend_detection",
                name="海外トレンド検出（毎日08:00）",
                replace_existing=True,
            )

            # === スキル形式化 & ハーネス健全性 ===

            # スキル抽出（毎日04:00 JST）
            self._scheduler.add_job(
                self.skill_extraction,
                CronTrigger(hour=4, minute=0, timezone="Asia/Tokyo"),
                id="skill_extraction",
                name="スキル抽出（毎日04:00）",
                replace_existing=True,
            )

            # ハーネス健全性スコア（毎時）
            self._scheduler.add_job(
                self.harness_health_check,
                IntervalTrigger(hours=1),
                id="harness_health",
                name="ハーネス健全性スコア（毎時）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # === 自動テスト & 依存関係マッピング ===

            # 自動テスト（毎日06:00 JST）— フルスイート
            self._scheduler.add_job(
                self.self_test_full,
                CronTrigger(hour=6, minute=0, timezone="Asia/Tokyo"),
                id="self_test_full",
                name="自動テスト（毎日06:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 構文チェック（毎時）— 軽量
            self._scheduler.add_job(
                self.self_test_syntax,
                IntervalTrigger(hours=1),
                id="self_test_syntax",
                name="構文チェック（毎時）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 依存関係マッピング（毎週月曜06:30 JST）
            self._scheduler.add_job(
                self.dependency_mapping,
                CronTrigger(day_of_week="mon", hour=6, minute=30, timezone="Asia/Tokyo"),
                id="dependency_mapping",
                name="依存関係マッピング（毎週月曜06:30）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # === gstack自律実行ジョブ ===

            # gstackコードレビュー（毎日09:00 JST）
            self._scheduler.add_job(
                self.gstack_code_review,
                CronTrigger(hour=9, minute=0, timezone="Asia/Tokyo"),
                id="gstack_code_review",
                name="gstackコードレビュー（毎日09:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # gstackセキュリティ監査（毎週日曜02:00 JST）
            self._scheduler.add_job(
                self.gstack_security_audit,
                CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="Asia/Tokyo"),
                id="gstack_security_audit",
                name="gstackセキュリティ監査（毎週日曜02:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # gstack週次振り返り（毎週月曜08:00 JST）
            self._scheduler.add_job(
                self.gstack_retro,
                CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="Asia/Tokyo"),
                id="gstack_retro",
                name="gstack週次振り返り（毎週月曜08:00）",
                replace_existing=True,
                misfire_grace_time=60,
            )

            # === intel活用ジョブ ===

            # X @syutain_beta「今日のAI速報」（毎日11:30 JST）
            self._scheduler.add_job(
                self.intel_bulletin_x,
                CronTrigger(hour=11, minute=30, timezone="Asia/Tokyo"),
                id="intel_bulletin_x",
                name="X AI速報投稿（毎日11:30）",
                replace_existing=True,
            )

            # 週次インテルダイジェスト（毎週日曜20:00 JST）
            self._scheduler.add_job(
                self.weekly_intel_digest,
                CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="Asia/Tokyo"),
                id="weekly_intel_digest",
                name="週次インテルダイジェスト（日曜20:00）",
                replace_existing=True,
            )

            self._scheduler.start()
            logger.info("スケジューラー起動完了")

            # 起動時の時刻に応じてパワーモードを自動判定（23:00-09:00 JST = night）
            global _current_power_mode
            from zoneinfo import ZoneInfo
            jst_now = datetime.now(ZoneInfo("Asia/Tokyo"))
            current_hour = jst_now.hour
            if current_hour >= 23 or current_hour < 9:
                _current_power_mode = "night"
                logger.info(f"起動時刻 {jst_now.strftime('%H:%M')} JST → 夜間モードで開始")
            else:
                _current_power_mode = "day"
                logger.info(f"起動時刻 {jst_now.strftime('%H:%M')} JST → 日中モードで開始")

            # Karpathy Loop: 再起動時に実行中実験のパラメータを復元
            try:
                from agents.karpathy_loop import restore_running_experiments
                await restore_running_experiments()
            except Exception as e:
                logger.warning(f"Karpathy実験復元スキップ: {e}")

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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception as e:
            logger.error(f"ハートビート失敗: {e}")

    async def capability_audit(self):
        """Capability Audit: 全4台の能力スナップショットを取得"""
        logger.info("Capability Audit開始")
        try:
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                import json
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO capability_snapshots (snapshot_data)
                        VALUES ($1)
                        """,
                        json.dumps(snapshot, ensure_ascii=False, default=str),
                    )
            except Exception as e:
                logger.error(f"Capability Audit保存失敗: {e}")

            logger.info(f"Capability Audit完了: {len(snapshot['nodes'])}ノード")

        except Exception as e:
            logger.error(f"Capability Audit失敗: {e}")

    async def auto_review_intel(self):
        """intel_items自動レビュー（重要度スコアで振り分け）"""
        try:
            from tools.intel_reviewer import auto_review_intel
            result = await auto_review_intel()
            if result.get("actionable", 0) > 0:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"\U0001f4ca 情報レビュー: actionable {result['actionable']}件"
                    f" / reviewed {result['reviewed']}件"
                    f" / archived {result['archived']}件"
                )
        except Exception as e:
            logger.error(f"auto_review_intelエラー: {e}")

    async def dynamic_keyword_update(self):
        """動的キーワード更新: persona_memory + intel_itemsから検索キーワードを生成"""
        try:
            from tools.keyword_generator import generate_search_keywords
            from tools.event_logger import log_event
            keywords = await generate_search_keywords()
            logger.info(f"動的キーワード更新完了: {len(keywords)}件")
            await log_event("keyword.updated", "system", {
                "count": len(keywords), "keywords": keywords[:5],
            })
        except Exception as e:
            logger.error(f"動的キーワード更新失敗: {e}")

    async def daily_summary_notify(self):
        """日次サマリー: 完了タスク数・収益・承認待ち件数をDiscord通知"""
        try:
            from tools.db_pool import get_connection
            from tools.discord_notify import notify_daily_summary
            async with get_connection() as conn:
                completed = await conn.fetchval(
                    "SELECT COUNT(*) FROM tasks WHERE status = 'completed' AND updated_at > CURRENT_DATE"
                ) or 0
                revenue = await conn.fetchval(
                    "SELECT COALESCE(SUM(revenue_jpy), 0) FROM commerce_transactions WHERE created_at > CURRENT_DATE"
                ) or 0.0
                pending = await conn.fetchval(
                    "SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'"
                ) or 0
            await notify_daily_summary(int(completed), float(revenue), int(pending))
            logger.info(f"日次サマリー通知: 完了={completed}, 収益=¥{revenue}, 承認待ち={pending}")
        except Exception as e:
            logger.error(f"日次サマリー通知失敗: {e}")

    async def product_packaging(self):
        """publish_ready記事を商品パッケージに変換"""
        try:
            from brain_alpha.product_packager import package_publish_ready_articles
            result = await package_publish_ready_articles()
            if result.get("packaged", 0) > 0:
                logger.info(f"商品パッケージング: {result['packaged']}件パッケージ化")
            else:
                logger.debug("商品パッケージング: 対象なし")
        except Exception as e:
            logger.error(f"商品パッケージングエラー: {e}")

    async def executive_briefing(self):
        """経営日報を生成してDiscord送信"""
        try:
            from brain_alpha.executive_briefing import generate_executive_briefing
            result = await generate_executive_briefing()
            logger.info(f"経営日報: {result.get('status', 'unknown')}")
        except Exception as e:
            logger.error(f"経営日報エラー: {e}")

    async def generate_intel_digest(self):
        """intel_digest生成: 直近24時間の情報をエージェント向けに要約"""
        try:
            from tools.intel_digest import generate_intel_digest
            from tools.event_logger import log_event
            result = await generate_intel_digest()
            logger.info(f"intel_digest生成完了: {result.get('items_count', 0)}件")
            await log_event("intel.digest_generated", "system", {
                "items_count": result.get("items_count", 0),
            })
        except Exception as e:
            logger.error(f"intel_digest生成失敗: {e}")

    async def deep_article_scrape_batch(self):
        """未処理のactionableアイテムの全文をJina/ブラウザで取得"""
        try:
            from tools.browser_ops import scrape_page
            from tools.db_pool import get_connection
            import json
            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, url FROM intel_items
                    WHERE review_flag = 'actionable' AND url IS NOT NULL
                    AND (metadata IS NULL OR metadata::text NOT LIKE '%full_text%')
                    LIMIT 5
                """)
                for row in rows:
                    if not row["url"]:
                        continue
                    result = await scrape_page(row["url"])
                    if result.get("text"):
                        # metadata が存在しない可能性あるのでsummaryを更新
                        await conn.execute(
                            "UPDATE intel_items SET summary = LEFT($1, 500) WHERE id = $2",
                            result["text"], row["id"],
                        )
                        logger.info(f"深掘り取得: id={row['id']} {len(result['text'])}文字")
        except Exception as e:
            logger.error(f"深掘りバッチ失敗: {e}")

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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
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

    async def detect_overseas_trends(self):
        """海外トレンド先取り検出: 毎日08:00 JSTに実行"""
        logger.info("海外トレンド先取り検出開始")
        try:
            from tools.trend_detector import run_trend_detection_and_save
            result = await run_trend_detection_and_save()
            logger.info(
                f"海外トレンド検出完了: 検出{result.get('detected', 0)}件, "
                f"保存{result.get('saved', 0)}件, 通知{result.get('notified', 0)}件"
            )
        except Exception as e:
            logger.error(f"海外トレンド検出失敗: {e}")

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
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # 48時間以上前のpendingタスクは stale に移行（永久放置防止）
                stale_count = await conn.execute(
                    """UPDATE tasks SET status = 'stale'
                       WHERE status = 'pending'
                       AND created_at < NOW() - INTERVAL '48 hours'"""
                )
                if stale_count and stale_count != "UPDATE 0":
                    logger.info(f"古い孤立タスクを stale に移行: {stale_count}")

                # 終了済みゴールの子タスクも stale に移行（孤児タスク防止）
                orphan_count = await conn.execute(
                    """UPDATE tasks SET status = 'stale'
                       WHERE status IN ('pending', 'dispatched')
                       AND SPLIT_PART(id, '-t', 1) IN (
                         SELECT goal_id FROM goal_packets
                         WHERE status IN ('emergency_stopped', 'escalated', 'completed')
                       )"""
                )
                if orphan_count and orphan_count != "UPDATE 0":
                    logger.info(f"終了済みゴールの孤児タスクを stale に移行: {orphan_count}")

                # 30分-48時間前のpendingタスクを取得
                rows = await conn.fetch(
                    """
                    SELECT id, type, assigned_node, input_data::text as input_text
                    FROM tasks
                    WHERE status = 'pending'
                      AND created_at < NOW() - INTERVAL '30 minutes'
                      AND created_at > NOW() - INTERVAL '48 hours'
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
                            # titleがなければdescriptionをtitleに設定（Web UI表示用）
                            if "title" not in input_data and "description" in input_data:
                                input_data["title"] = input_data["description"][:80]
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
                            # ステータスを dispatched に更新（再取得防止）
                            await conn.execute(
                                "UPDATE tasks SET status = 'dispatched' WHERE id = $1 AND status = 'pending'",
                                row["id"],
                            )
                            logger.info(f"タスク {task_id} ({task_type}) → {node} に再ディスパッチ")
                        except Exception as e:
                            logger.error(f"タスク再ディスパッチ失敗: {e}")
        except Exception as e:
            logger.error(f"孤立タスク再ディスパッチ処理失敗: {e}")

    async def weekly_learning_report(self):
        """週次学習レポート生成"""
        logger.info("週次学習レポート生成開始")
        try:
            from agents.learning_manager import LearningManager
            from tools.event_logger import log_event
            lm = LearningManager()
            await lm.initialize()
            report = await lm.generate_weekly_report()
            if report and "error" not in report:
                logger.info("週次学習レポート生成完了")
                await log_event("learning.weekly_report", "system", {
                    "status": "completed",
                    "summary": str(report.get("summary", ""))[:200],
                })
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

    # 価格収集対象（GMOコインAPIで取得可能なJPYペア + 主要USD建て通貨）
    CRYPTO_WATCH_SYMBOLS = [
        # メジャー
        "BTC_JPY", "ETH_JPY", "XRP_JPY", "SOL_JPY", "DOGE_JPY",
        "LTC_JPY", "BCH_JPY", "DOT_JPY", "LINK_JPY", "ATOM_JPY",
        "ADA_JPY", "SUI_JPY",
        # GMOコイン固有（JPYペアなし→USD建て相当）
        "XLM", "XTZ", "ASTR", "DAI", "FCR", "NAC", "WILD",
    ]
    # 変動検知閾値（30分間の変動率%）
    CRYPTO_ALERT_THRESHOLD_PCT = 3.0  # 3%以上で異常変動アラート
    _prev_prices: dict = {}  # {symbol: last_price}

    async def crypto_price_snapshot(self):
        """30分間隔で20通貨の価格を一括取得、event_logに記録、異常変動時はリサーチ実行"""
        try:
            import httpx
            from tools.event_logger import log_event

            async with httpx.AsyncClient(timeout=15.0) as client:
                # GMOコインAPI: 全通貨を一括取得（1リクエスト）
                resp = await client.get("https://api.coin.z.com/public/v1/ticker")
                if resp.status_code != 200:
                    logger.warning(f"暗号通貨API応答エラー: {resp.status_code}")
                    return

                data = resp.json()
                tickers = {t["symbol"]: t for t in data.get("data", [])}

                alerts = []  # 異常変動リスト

                for symbol in self.CRYPTO_WATCH_SYMBOLS:
                    ticker = tickers.get(symbol)
                    if not ticker:
                        continue

                    price = float(ticker.get("last", 0))
                    high = float(ticker.get("high", 0))
                    low = float(ticker.get("low", 0))
                    volume = ticker.get("volume", "0")

                    if price <= 0:
                        continue

                    # event_logに記録
                    await log_event("trade.price_snapshot", "system", {
                        "pair": symbol,
                        "price": price,
                        "high": high,
                        "low": low,
                        "volume": volume,
                    })

                    # 変動検知（前回比）
                    prev = self._prev_prices.get(symbol)
                    if prev and prev > 0:
                        change_pct = abs(price - prev) / prev * 100
                        if change_pct >= self.CRYPTO_ALERT_THRESHOLD_PCT:
                            direction = "急騰" if price > prev else "急落"
                            alerts.append({
                                "symbol": symbol,
                                "prev": prev,
                                "current": price,
                                "change_pct": round(change_pct, 2),
                                "direction": direction,
                            })

                    self._prev_prices[symbol] = price

                logger.info(f"暗号通貨価格取得: {len([s for s in self.CRYPTO_WATCH_SYMBOLS if s in tickers])}通貨")

                # 異常変動時: リサーチ実行 + intel_items紐付け + Discord通知
                if alerts:
                    await self._research_crypto_movement(alerts)

        except Exception as e:
            logger.warning(f"暗号通貨価格取得失敗: {e}")

    async def _research_crypto_movement(self, alerts: list):
        """暗号通貨の異常変動の原因をリサーチし、intel_itemsと紐付けて記録"""
        try:
            from tools.discord_notify import notify_discord
            from tools.event_logger import log_event

            for alert in alerts[:3]:  # 最大3通貨まで同時リサーチ
                symbol = alert["symbol"]
                direction = alert["direction"]
                change_pct = alert["change_pct"]
                coin_name = symbol.replace("_JPY", "").replace("_", "")

                # Discord通知
                await notify_discord(
                    f"📈 暗号通貨{direction}: **{symbol}** {change_pct}%変動\n"
                    f"  ¥{alert['prev']:,.0f} → ¥{alert['current']:,.0f}"
                )

                # Tavily検索で原因をリサーチ
                search_query = f"{coin_name} price {direction.replace('急騰','surge').replace('急落','crash')} reason today"
                try:
                    from tools.tavily_client import search_tavily
                    results = await search_tavily(search_query, max_results=3, search_depth="basic")
                    if results:
                        # intel_itemsに保存（情報収集パイプラインと紐付け）
                        from tools.db_pool import get_connection
                        async with get_connection() as conn:
                            for r in results[:2]:
                                await conn.execute("""
                                    INSERT INTO intel_items
                                    (source, keyword, title, url, summary, importance_score,
                                     category, metadata, review_flag, processed)
                                    VALUES ('crypto_research', $1, $2, $3, $4, 0.7,
                                            'market_movement', $5, 'actionable', true)
                                    ON CONFLICT DO NOTHING
                                """,
                                    coin_name,
                                    r.get("title", "")[:200],
                                    r.get("url", ""),
                                    r.get("content", "")[:300],
                                    json.dumps({
                                        "symbol": symbol,
                                        "direction": direction,
                                        "change_pct": change_pct,
                                        "research_query": search_query,
                                    }, ensure_ascii=False),
                                )

                        # リサーチ結果をevent_logにも記録
                        await log_event("trade.movement_research", "system", {
                            "symbol": symbol,
                            "direction": direction,
                            "change_pct": change_pct,
                            "research_results": len(results),
                            "top_result": results[0].get("title", "")[:100] if results else "",
                        })

                        # Discord通知（原因）
                        top_title = results[0].get("title", "原因不明")[:80] if results else "原因不明"
                        await notify_discord(
                            f"🔍 {symbol} {direction}原因リサーチ: {top_title}"
                        )
                except Exception as search_err:
                    logger.warning(f"暗号通貨変動リサーチ失敗 ({symbol}): {search_err}")

        except Exception as e:
            logger.error(f"暗号通貨変動リサーチ全体失敗: {e}")

    async def cost_forecast(self):
        """6時間間隔でAPI月末コスト予測"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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
                monthly_budget = float(os.getenv("MONTHLY_BUDGET_JPY", os.getenv("MONTHLY_API_BUDGET_JPY", "2000")))

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
                        from tools.discord_notify import notify_error
                        await notify_error(
                            "budget_forecast_warn",
                            f"コスト予測警告: 月末推定¥{forecast:.0f} / 予算¥{monthly_budget:.0f} "
                            f"({forecast/monthly_budget*100:.0f}%)",
                            severity="error",
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"コスト予測失敗: {e}")

    async def bluesky_engagement_check(self):
        """12時間間隔でBluesky投稿のエンゲージメント取得"""
        try:
            import json
            from tools.db_pool import get_connection
            from tools.social_tools import get_bluesky_engagement
            from tools.event_logger import log_event

            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, post_url FROM posting_queue
                    WHERE platform = 'bluesky' AND status = 'posted' AND post_url IS NOT NULL
                    AND posted_at > NOW() - INTERVAL '72 hours'
                    LIMIT 10
                """)
                for row in rows:
                    uri = row["post_url"]
                    if not uri:
                        continue
                    engagement = await get_bluesky_engagement(uri)
                    if not engagement.get("error"):
                        await conn.execute(
                            "UPDATE posting_queue SET engagement_data = $1 WHERE id = $2",
                            json.dumps(engagement, ensure_ascii=False), row["id"],
                        )
                        await log_event("sns.engagement", "sns", {**engagement, "platform": "bluesky"})
                        logger.info(f"Blueskyエンゲージメント: likes={engagement.get('like_count',0)}")
        except Exception as e:
            logger.error(f"Blueskyエンゲージメント取得失敗: {e}")

    async def x_engagement_check(self):
        """12時間間隔でX投稿のエンゲージメント取得（Free tierでは取得不可の場合あり）"""
        try:
            import json
            from tools.db_pool import get_connection
            from tools.social_tools import get_x_engagement
            from tools.event_logger import log_event

            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, account, post_url FROM posting_queue
                    WHERE platform = 'x' AND status = 'posted' AND post_url IS NOT NULL
                    AND posted_at > NOW() - INTERVAL '7 days'
                    LIMIT 20
                """)
                for row in rows:
                    post_url = row["post_url"] or ""
                    post_id = post_url.split("/")[-1] if "/" in post_url else ""
                    if not post_id:
                        continue
                    engagement = await get_x_engagement(post_id, account=row["account"] or "syutain")
                    if engagement.get("error") == "free_tier_limitation":
                        logger.info("Xエンゲージメント: Free tierのため取得不可。スキップ。")
                        return
                    if not engagement.get("error"):
                        await conn.execute(
                            "UPDATE posting_queue SET engagement_data = $1 WHERE id = $2",
                            json.dumps(engagement, ensure_ascii=False), row["id"],
                        )
                        await log_event("sns.engagement", "sns", {**engagement, "platform": "x"})
        except Exception as e:
            logger.error(f"Xエンゲージメント取得失敗: {e}")

    async def threads_engagement_check(self):
        """12時間間隔でThreads投稿のエンゲージメント取得"""
        try:
            import json
            from tools.db_pool import get_connection
            from tools.social_tools import get_threads_engagement
            from tools.event_logger import log_event

            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, post_url FROM posting_queue
                    WHERE platform = 'threads' AND status = 'posted' AND post_url IS NOT NULL
                    AND posted_at > NOW() - INTERVAL '7 days'
                    LIMIT 20
                """)
                for row in rows:
                    post_url = row["post_url"] or ""
                    post_id = post_url.split("/")[-1] if "/" in post_url else ""
                    if not post_id:
                        continue
                    engagement = await get_threads_engagement(post_id)
                    if not engagement.get("error"):
                        await conn.execute(
                            "UPDATE posting_queue SET engagement_data = $1 WHERE id = $2",
                            json.dumps(engagement, ensure_ascii=False), row["id"],
                        )
                        await log_event("sns.engagement", "sns", {**engagement, "platform": "threads"})
        except Exception as e:
            logger.error(f"Threadsエンゲージメント取得失敗: {e}")

    async def daily_engagement_analysis(self):
        """毎日06:30にエンゲージメント分析を実行し、結果をevent_logに保存"""
        try:
            from tools.engagement_analyzer import run_daily_analysis
            result = await run_daily_analysis()
            if result.get("error"):
                logger.warning(f"エンゲージメント分析エラー: {result['error']}")
            else:
                logger.info(
                    f"エンゲージメント分析完了: {result.get('total_posts_analyzed', 0)}件, "
                    f"推奨テーマ={result.get('best_themes', [])[:3]}"
                )
        except Exception as e:
            logger.error(f"日次エンゲージメント分析失敗: {e}")

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

                # ハーネス健全性スコアをSYSTEM_STATE.mdに追記
                try:
                    from tools.harness_health import calculate_health_score
                    health = await calculate_health_score()
                    state_path = os.path.join(os.path.dirname(__file__), "SYSTEM_STATE.md")
                    with open(state_path, "a", encoding="utf-8") as f:
                        f.write(f"\n## Harness Health Score: {health['overall']}/100 (Grade {health['grade']})\n")
                        for name, comp in health.get("components", {}).items():
                            f.write(f"- {name}: {comp['score']}/100 — {comp['detail']}\n")
                        if health.get("recommendations"):
                            f.write("\n**Recommendations:**\n")
                            for rec in health["recommendations"]:
                                f.write(f"- {rec}\n")
                except Exception as he:
                    logger.debug(f"健全性スコア追記失敗: {he}")
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

            nodes = REMOTE_NODES
            results = []
            for node, ip in nodes.items():
                try:
                    r = subprocess.run(
                        ["rsync", "-az", f"{REMOTE_SSH_USER}@{ip}:~/syutain_beta/data/*.db", backup_dir],
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
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                recent_proposals = await conn.fetch(
                    "SELECT title, score FROM proposal_history ORDER BY created_at DESC LIMIT 3"
                )
                recent_tasks = await conn.fetchval(
                    "SELECT count(*) FROM tasks WHERE updated_at > NOW() - INTERVAL '3 days'"
                )

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
        """09:00 JST: 日中モードに切替"""
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
                from tools.db_pool import get_connection
                async with get_connection() as _conn_nb:
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
                from tools.db_pool import get_connection
                async with get_connection() as conn:
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
            except Exception as e:
                logger.error(f"夜間バッチ content_multiplier失敗: {e}")

            logger.info("夜間バッチコンテンツ生成完了")
        except Exception as e:
            logger.error(f"夜間バッチコンテンツ生成失敗: {e}")

    async def weekly_product_candidate(self):
        """毎週金曜23:15 JST: 直近1週間の高品質成果物から商品化候補を生成"""
        logger.info("週次商品化候補生成開始")
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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
        except Exception as e:
            logger.error(f"週次商品化候補生成失敗: {e}")

    async def note_draft_generation(self):
        """23:45 JST: note記事ドラフト自動生成（content_pipeline経由、Build in Public準拠）"""
        if _current_power_mode != "night":
            return
        logger.info("note記事ドラフト生成開始（content_pipeline経由）")
        try:
            # content_pipeline.generate_publishable_content() を使用
            # これにより Build in Public 方針、外部検索検証、SEOタイトル生成、
            # 実データ注入、品質スコアリングが全て自動適用される
            from brain_alpha.content_pipeline import generate_publishable_content
            import os as _os

            result = await generate_publishable_content(
                theme=None,  # content_pipelineが実データからテーマを自動選定
                content_type="note_article",
                target_length=10000,
            )

            if result.get("content") and len(result["content"]) > 100:
                drafts_dir = _os.path.join(_os.path.dirname(__file__), "data", "artifacts", "note_drafts")
                _os.makedirs(drafts_dir, exist_ok=True)

                title_short = (result.get("title", "untitled"))[:30].replace("/", "_").replace(" ", "_")
                filename = f"note_{datetime.now().strftime('%Y%m%d_%H%M')}_{title_short}.md"
                filepath = _os.path.join(drafts_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(result["content"])

                quality = result.get("quality_score", 0)
                logger.info(
                    f"note記事ドラフト保存: {filepath} "
                    f"({len(result['content'])}文字, 品質={quality:.3f})"
                )

                from tools.event_logger import log_event
                await log_event("content.note_draft", "task", {
                    "theme": result.get("title", ""),
                    "length": len(result["content"]),
                    "quality_score": quality,
                    "filepath": filepath,
                    "stages": len(result.get("stages", [])),
                })

                if len(result["content"]) > 500:
                    try:
                        from tools.discord_notify import notify_discord
                        await notify_discord(
                            f"📝 note記事ドラフト完成（content_pipeline）\n"
                            f"タイトル: {result.get('title', 'N/A')}\n"
                            f"文字数: {len(result['content'])}文字 / 品質: {quality:.3f}\n"
                            f"保存先: {filepath}\n"
                            f"プレビュー: {result['content'][:100]}..."
                        )
                    except Exception:
                        pass
            else:
                logger.warning(
                    f"note記事ドラフト生成: content_pipelineの出力が不足 "
                    f"(status={result.get('status')}, stages={result.get('stages', [])})"
                )
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

    async def process_approved_proposals(self):
        """提案自動承認→ゴール変換（30分間隔）
        品質スコア≧65の未レビュー提案を自動承認し、ゴールに変換する。
        直近1時間にemergency_stoppedが3件以上あればクールダウン（暴走防止）。
        """
        try:
            from tools.db_pool import get_connection
            from agents.os_kernel import get_os_kernel
            import asyncio

            async with get_connection() as conn:
                # クールダウン: 直近1時間のemergency_stopped件数を確認
                stopped_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM goal_packets
                       WHERE status = 'emergency_stopped'
                       AND created_at > NOW() - INTERVAL '1 hour'"""
                )
                if stopped_count and stopped_count >= 3:
                    logger.warning(
                        f"提案自動承認クールダウン: 直近1時間にemergency_stopped {stopped_count}件 → スキップ"
                    )
                    return

                # 現在実行中（active）のゴールが多すぎる場合もスキップ
                active_goals = await conn.fetchval(
                    """SELECT COUNT(*) FROM goal_packets
                       WHERE status IN ('active', 'running')
                       AND created_at > NOW() - INTERVAL '2 hours'"""
                )
                if active_goals and active_goals >= 3:
                    logger.info(f"提案自動承認: 実行中ゴール{active_goals}件 → 待機")
                    return

                # 品質スコア≧65のpending_review提案を取得（暴走防止: 1件ずつ）
                proposals = await conn.fetch(
                    """SELECT id, proposal_id, title, score, proposal_data
                       FROM proposal_history
                       WHERE review_flag = 'pending_review'
                       AND score >= 65
                       ORDER BY score DESC LIMIT 1"""
                )

                if not proposals:
                    return

                for p in proposals:
                    try:
                        title = p["title"] or "自動承認提案"

                        # === V30: Build in Public方針チェック ===
                        # note記事系の提案が外部AIニュース解説になっていないか検証
                        _bip_violations = []
                        _title_lower = title.lower()
                        # 提案本文も検査対象に含める
                        _pdata = p.get("proposal_data") or {}
                        if isinstance(_pdata, str):
                            try:
                                _pdata = json.loads(_pdata)
                            except Exception:
                                _pdata = {}
                        _proposal_text = (
                            title + " " +
                            " ".join(_pdata.get("why_now", [])) + " " +
                            _pdata.get("first_action", "") + " " +
                            str(_pdata.get("expected_outcome", ""))
                        ).lower()

                        # 新モデル名言及チェック: 外部検索で公式リリースを確認
                        import re as _re
                        _model_mentions = _re.findall(
                            r'(?:deepseek[- ]?v\d|gpt[- ]?\d+(?:\.\d+)?|claude[- ]?\d+(?:\.\d+)?|gemini[- ]?\d+(?:\.\d+)?|llama[- ]?\d+)',
                            _proposal_text
                        )
                        if _model_mentions:
                            # 既知のリリース済みモデル（確認不要）
                            _known_released = {
                                "gpt-5.4", "gpt-5", "gpt-4", "gpt-4o",
                                "claude-4", "claude 4", "claude-3", "claude 3",
                                "gemini-2", "gemini 2", "gemini-3", "gemini 3",
                                "deepseek-v3", "deepseek v3",
                                "llama-4", "llama 4", "llama-3", "llama 3",
                            }
                            for mm in _model_mentions:
                                mm_normalized = mm.replace("-", " ").replace("  ", " ").strip()
                                if mm_normalized not in _known_released:
                                    # 未確認モデル → 外部検索で公式リリースを確認
                                    try:
                                        from tools.tavily_client import search_tavily
                                        search_results = await search_tavily(
                                            f"{mm} official release announcement",
                                            max_results=3, search_depth="basic",
                                        )
                                        # 公式リリース記事が見つかるか確認
                                        _has_official = False
                                        if search_results:
                                            for sr in search_results:
                                                sr_title = (sr.get("title", "") + " " + sr.get("content", "")).lower()
                                                if any(kw in sr_title for kw in ["release", "launch", "announce", "available", "公開", "リリース"]):
                                                    _has_official = True
                                                    break
                                        if not _has_official:
                                            _bip_violations.append(
                                                f"モデル「{mm}」の公式リリースを外部検索で確認できず（推測記事の可能性）"
                                            )
                                    except Exception as _search_err:
                                        logger.warning(f"モデルリリース確認検索失敗（安全側reject）: {_search_err}")
                                        _bip_violations.append(f"モデル「{mm}」のリリース確認検索失敗（安全側reject）")

                        # 外部AIニュース解説記事の検出
                        _external_news_patterns = [
                            "完全ガイド", "活用法", "使い方", "導入ガイド", "選定基準",
                            "最新動向", "速報", "まとめ", "徹底比較", "入門",
                        ]
                        _has_external_pattern = any(ep in title or ep in _proposal_text for ep in _external_news_patterns)
                        _has_syutain_ref = "SYUTAINβ" in title or "syutain" in _proposal_text
                        if _has_external_pattern and not _has_syutain_ref:
                            _bip_violations.append(f"外部AIニュース解説記事の疑い: {title[:50]}")

                        if _bip_violations:
                            await conn.execute(
                                "UPDATE proposal_history SET review_flag = 'rejected', adopted = FALSE, outcome_type = $1 WHERE id = $2",
                                f"auto_rejected_bip_violation: {'; '.join(_bip_violations)}", p["id"],
                            )
                            logger.warning(f"提案自動承認拒否（BIP違反）: {title} — {_bip_violations}")
                            try:
                                from tools.discord_notify import notify_discord
                                await notify_discord(
                                    f"⚠️ 提案自動拒否（方針違反）: {title}\n理由: {'; '.join(_bip_violations)}"
                                )
                            except Exception:
                                pass
                            continue

                        # 提案をapprovedに更新
                        await conn.execute(
                            "UPDATE proposal_history SET review_flag = 'approved', adopted = TRUE WHERE id = $1",
                            p["id"],
                        )
                        # proposal_dataからobjective/why_nowを抽出してゴールのコンテキストにする
                        pdata = p["proposal_data"] or {}
                        if isinstance(pdata, str):
                            import json as _json
                            pdata = _json.loads(pdata)
                        objective = pdata.get("objective", "")
                        why_now = pdata.get("why_now", [])
                        context = f" ({objective})" if objective else ""
                        if why_now and isinstance(why_now, list):
                            context += f" 理由: {why_now[0][:200]}"
                        raw_goal = f"{title}{context}"

                        kernel = get_os_kernel()
                        asyncio.create_task(kernel.execute_goal(raw_goal))

                        logger.info(f"提案自動承認→ゴール起動: {title} (score={p['score']})")

                        # Discord通知
                        try:
                            from tools.discord_notify import notify_discord
                            first_action = pdata.get("first_action", "")
                            why_first = why_now[0][:100] if why_now and isinstance(why_now, list) else ""
                            await notify_discord(
                                f"✅ 提案自動承認: {title} (スコア: {p['score']})\n"
                                + (f"理由: {why_first}\n" if why_first else "")
                                + (f"次のアクション: {first_action[:100]}" if first_action else "")
                            )
                        except Exception:
                            pass

                    except Exception as e:
                        logger.error(f"提案→ゴール変換失敗: {e}")

        except Exception as e:
            logger.error(f"提案自動承認処理失敗: {e}")

    # ノード別サービス名マッピング
    _NODE_SERVICES = {
        "bravo": ["syutain-worker-bravo"],
        "charlie": ["syutain-worker-charlie"],
        "delta": ["syutain-worker-delta"],
    }

    async def node_health_check(self):
        """5分間隔でノードのヘルスチェックを実行しevent_logに記録。
        障害検出時はサービス自動再起動を試行し、失敗ならnode_stateを'down'に更新。
        """
        try:
            import json
            import httpx
            import subprocess

            from tools.event_logger import log_event

            for node, ip in REMOTE_NODES.items():
                health = {"node": node, "ip": ip, "status": "unknown"}
                node_has_failure = False

                # 1. SSH疎通確認（タイムアウト5秒）
                ssh_ok = False
                try:
                    proc = subprocess.run(
                        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                         f"{REMOTE_SSH_USER}@{ip}", "echo ok"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if proc.returncode == 0 and "ok" in proc.stdout:
                        ssh_ok = True
                        health["ssh"] = "ok"
                    else:
                        health["ssh"] = f"failed: {proc.stderr[:80]}"
                        node_has_failure = True
                except Exception as e:
                    health["ssh"] = f"unreachable: {str(e)[:50]}"
                    node_has_failure = True

                # 2. systemctl is-active チェック（各ワーカー）
                services = self._NODE_SERVICES.get(node, [])
                health["services"] = {}
                for svc in services:
                    if not ssh_ok:
                        health["services"][svc] = "ssh_unavailable"
                        node_has_failure = True
                        continue
                    try:
                        proc = subprocess.run(
                            ["ssh", "-o", "ConnectTimeout=5", f"{REMOTE_SSH_USER}@{ip}",
                             f"export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus; "
                             f"sudo systemctl is-active {svc}"],
                            capture_output=True, text=True, timeout=10,
                        )
                        status = proc.stdout.strip()
                        health["services"][svc] = status
                        if status != "active":
                            node_has_failure = True
                    except Exception as e:
                        health["services"][svc] = f"check_failed: {str(e)[:50]}"
                        node_has_failure = True

                # 3. Ollama応答確認
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(f"http://{ip}:11434/api/tags")
                        if resp.status_code == 200:
                            models = resp.json().get("models", [])
                            health["ollama"] = "ok"
                            health["ollama_models"] = [m.get("name", "") for m in models[:3]]
                        else:
                            health["ollama"] = f"error_{resp.status_code}"
                            node_has_failure = True
                except Exception as e:
                    health["ollama"] = f"unreachable: {str(e)[:50]}"
                    node_has_failure = True

                # 4. GPU温度チェック（SSH経由）
                if ssh_ok:
                    try:
                        gpu_temp_out = subprocess.check_output(
                            ["ssh", "-o", "ConnectTimeout=3", f"{REMOTE_SSH_USER}@{ip}",
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
                            config = get_power_config()
                            if health["gpu_temp_c"] > config.get("gpu_temp_limit", 80):
                                health["gpu_throttled"] = True
                                logger.warning(f"{node.upper()} GPU温度{health['gpu_temp_c']}℃ > 閾値{config['gpu_temp_limit']}℃")
                    except Exception:
                        pass

                # 5. CPU/MEM（SSH経由）
                if ssh_ok:
                    try:
                        cpu_out = subprocess.check_output(
                            ["ssh", "-o", "ConnectTimeout=3", f"{REMOTE_SSH_USER}@{ip}",
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

                # 6. 障害検出時の自動復旧試行
                if node_has_failure and ssh_ok:
                    health["auto_recovery"] = {}
                    # 停止しているサービスの再起動を試行
                    for svc, svc_status in health.get("services", {}).items():
                        if svc_status not in ("active", "ssh_unavailable"):
                            try:
                                restart_proc = subprocess.run(
                                    ["ssh", "-o", "ConnectTimeout=5", f"{REMOTE_SSH_USER}@{ip}",
                                     f"sudo systemctl restart {svc}"],
                                    capture_output=True, text=True, timeout=15,
                                )
                                if restart_proc.returncode == 0:
                                    health["auto_recovery"][svc] = "restarted"
                                    logger.info(f"{node.upper()} {svc} 自動再起動成功")
                                else:
                                    health["auto_recovery"][svc] = f"restart_failed: {restart_proc.stderr[:80]}"
                                    logger.error(f"{node.upper()} {svc} 自動再起動失敗: {restart_proc.stderr[:80]}")
                            except Exception as e:
                                health["auto_recovery"][svc] = f"restart_error: {str(e)[:50]}"

                    # 再起動後に状態を再確認
                    if health["auto_recovery"]:
                        await asyncio.sleep(3)
                        for svc in health["auto_recovery"]:
                            if health["auto_recovery"][svc] == "restarted":
                                try:
                                    verify_proc = subprocess.run(
                                        ["ssh", "-o", "ConnectTimeout=5", f"{REMOTE_SSH_USER}@{ip}",
                                         f"export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus; "
                                         f"sudo systemctl is-active {svc}"],
                                        capture_output=True, text=True, timeout=10,
                                    )
                                    new_status = verify_proc.stdout.strip()
                                    health["auto_recovery"][svc] = f"verified_{new_status}"
                                    if new_status != "active":
                                        node_has_failure = True  # まだ障害
                                    else:
                                        health["services"][svc] = "active"
                                except Exception:
                                    pass

                # 7. node_state DB更新（障害 & 復旧失敗時）
                if node_has_failure:
                    try:
                        from tools.db_pool import get_connection
                        async with get_connection() as conn:
                            current = await conn.fetchval(
                                "SELECT status FROM node_state WHERE node_name = $1", node
                            )
                            if current == "healthy":
                                # healthy→downに更新
                                await conn.execute(
                                    "UPDATE node_state SET state = 'down', reason = 'ヘルスチェック失敗', changed_by = 'node_health_check', changed_at = NOW() WHERE node_name = $1",
                                    node,
                                )
                                health["node_state_changed"] = "healthy -> down"
                                logger.warning(f"{node.upper()} node_state: healthy -> down")
                    except Exception as e:
                        logger.error(f"{node.upper()} node_state更新失敗: {e}")
                else:
                    # 正常時: downならhealthyに復帰
                    try:
                        from tools.db_pool import get_connection
                        async with get_connection() as conn:
                            current = await conn.fetchval(
                                "SELECT status FROM node_state WHERE node_name = $1", node
                            )
                            if current == "down":
                                await conn.execute(
                                    "UPDATE node_state SET state = 'healthy', reason = 'ヘルスチェック復帰', changed_by = 'node_health_check', changed_at = NOW() WHERE node_name = $1",
                                    node,
                                )
                                health["node_state_changed"] = "down -> healthy"
                                logger.info(f"{node.upper()} node_state: down -> healthy (復帰)")
                    except Exception:
                        pass

                severity = "info"
                if not ssh_ok:
                    severity = "error"
                    health["status"] = "unreachable"
                elif health.get("ollama", "").startswith("unreachable"):
                    severity = "error"
                elif health.get("ollama", "").startswith("error"):
                    severity = "warning"
                elif health.get("gpu_throttled"):
                    severity = "warning"
                elif node_has_failure:
                    severity = "warning"

                await log_event(
                    "node.health", "node",
                    health,
                    severity=severity,
                    source_node=node,
                )

                # 障害時Discord通知
                if node_has_failure:
                    try:
                        from tools.discord_notify import notify_error
                        failed_items = []
                        if not ssh_ok:
                            failed_items.append("SSH不通")
                        for svc, st in health.get("services", {}).items():
                            if st != "active":
                                recovery = health.get("auto_recovery", {}).get(svc, "")
                                failed_items.append(f"{svc}={st}" + (f" (再起動: {recovery})" if recovery else ""))
                        if health.get("ollama", "").startswith(("unreachable", "error")):
                            failed_items.append(f"Ollama={health['ollama'][:40]}")
                        await notify_error(
                            f"node_health_{node}",
                            f"{node.upper()} 障害検出: {', '.join(failed_items[:5])}",
                            severity="error",
                        )
                    except Exception:
                        pass

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

    async def chat_learning_job(self):
        """対話学習: 1時間おきに直近対話を分析しpersona_memoryに蓄積"""
        try:
            from bots.bot_learning import run_chat_learning
            result = await run_chat_learning(hours=1)
            if result.get("saved", 0) > 0:
                logger.info(f"対話学習: {result['saved']}件保存")
        except Exception as e:
            logger.error(f"対話学習ジョブ失敗: {e}")

    async def anomaly_detection(self):
        """5分間隔で異常検知 → Discord通知"""
        try:
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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

                # 既知のダウン状態を除外（charlie_win11等）
                known_down = set()
                node_states = await conn.fetch("SELECT node_name, state FROM node_state")
                for ns in node_states:
                    if ns["state"] in ("charlie_win11", "win11", "down", "recovering", "maintenance", "offline"):
                        known_down.add(ns["node_name"])

                notifications = []

                # severity=errorが5分間に3件以上（既知ダウンノードのエラーは除外）
                if error_count >= 3:
                    # 既知ダウンノード由来のエラーを除いた実エラー数をチェック
                    real_errors = await conn.fetchval(
                        """SELECT COUNT(*) FROM event_log
                        WHERE severity = 'error'
                        AND created_at > NOW() - INTERVAL '5 minutes'
                        AND (source_node IS NULL OR source_node NOT IN (
                            SELECT node_name FROM node_state WHERE state NOT IN ('healthy', 'degraded')
                        ))"""
                    ) or 0
                    if real_errors >= 3:
                        notifications.append(
                            f"⚠️ 異常検知: 直近5分でエラー{real_errors}件発生"
                        )

                # severity=criticalは即座に通知（既知ダウンノードは除外）
                for row in critical_rows:
                    if row["source_node"] in known_down:
                        continue
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                    notifications.append(
                        f"🚨 CRITICAL: {row['event_type']} on {row['source_node']} — "
                        f"{payload.get('reason', payload.get('error', ''))[:100]}"
                    )

                # Ollamaダウン（既知ダウンノードは除外）
                for row in ollama_down_nodes:
                    if row["node"] in known_down:
                        continue
                    notifications.append(
                        f"🔴 {row['node'].upper()}: Ollamaダウン検知"
                    )

                # 復帰検知（charlie.auto_restore等）
                recoveries = await conn.fetch(
                    """SELECT event_type, payload FROM event_log
                    WHERE event_type IN ('charlie.auto_restore', 'self_heal.executed')
                    AND created_at > NOW() - INTERVAL '5 minutes'"""
                )
                for row in recoveries:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                    node = payload.get("node", "unknown")
                    notifications.append(
                        f"✅ {node.upper()}: 復帰確認"
                    )

                # Discord通知（dedup付き — 同じ種類は1時間に1回のみ）
                if notifications:
                    try:
                        from tools.discord_notify import notify_error
                        for note in notifications[:3]:
                            # 安定したdedupキー（日本語含むハッシュで一意性を担保）
                            import hashlib
                            dedup_key = "anomaly_" + hashlib.md5(note[:60].encode('utf-8')).hexdigest()[:12]
                            await notify_error(dedup_key, note, severity="error")
                    except Exception as e:
                        logger.error(f"異常検知Discord通知失敗: {e}")

        except Exception as e:
            logger.error(f"異常検知処理失敗: {e}")

    async def _check_post_duplicate(self, draft: str) -> bool:
        """Bluesky投稿の重複チェック。N-gram類似度0.5以上なら棄却。"""
        try:
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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
                import json as _json
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type = 'bluesky_post'
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_contents.append(rd.get("content", ""))
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
            if await self._check_post_duplicate(draft):
                logger.info("Blueskyドラフト: 重複のため棄却。次回サイクルで再生成")
                return

            # 承認キューに投入
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ('bluesky_post', $1, 'pending')""",
                    json.dumps({
                        "content": draft[:300],
                        "platform": "bluesky",
                        "auto_generated": True,
                        "pattern": current_pattern,
                        "quality_score": quality_score if 'quality_score' in locals() else None,
                    }, ensure_ascii=False),
                )

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

            logger.info(f"Blueskyドラフト生成→承認キュー投入")
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
                import json as _json
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('x_post', 'bluesky_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
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
                    f"- 日本語150文字以内（厳守。途中で切れないよう150字以内で文を完結させる）\n"
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

            # 150文字超過時は文末で切り詰め（文が途中で切れないよう）
            if len(draft) > 150:
                candidates = [i + 1 for i, ch in enumerate(draft[:150]) if ch in "。！？…\n"]
                if candidates and candidates[-1] >= 75:
                    draft = draft[:candidates[-1]].rstrip()
                else:
                    draft = draft[:149].rstrip() + "…"

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
            if await self._check_post_duplicate(draft):
                logger.info("Xドラフト: 重複のため棄却")
                return

            # 承認キューに投入
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "x", "account": "syutain",
                    "content_preview": draft[:80], "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"Xドラフト生成→承認キュー投入 (SYUTAINβ)")
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
                import json as _json
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('x_post', 'bluesky_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
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
                    f"- 日本語150文字以内（厳守。途中で切れないよう150字以内で文を完結させる）\n"
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

            if await self._check_post_duplicate(draft):
                logger.info("島原Xドラフト: 重複のため棄却")
                return

            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "x", "account": "shimahara",
                    "content_preview": draft[:80], "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"島原Xドラフト生成→承認キュー投入")
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
                import json as _json
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    rows = await conn.fetch(
                        """SELECT request_data FROM approval_queue
                        WHERE request_type IN ('threads_post', 'bluesky_post', 'x_post')
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    for row in rows:
                        rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                        recent_posts += f"- {rd.get('content', '')[:60]}\n"
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
            if await self._check_post_duplicate(draft):
                logger.info("Threadsドラフト: 重複のため棄却")
                return

            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
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

            try:
                from tools.event_logger import log_event
                await log_event("sns.draft_created", "sns", {
                    "platform": "threads",
                    "content_preview": draft[:80],
                    "auto_generated": True,
                })
            except Exception:
                pass

            logger.info(f"Threadsドラフト生成→承認キュー投入")
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

    async def _generate_daily_content_impl(self, slot_name: str, theme_hint: str, extra_kwargs: dict = None):
        """日次コンテンツ生成共通実装: 5段パイプラインでnote記事候補を1本生成"""
        try:
            from brain_alpha.content_pipeline import generate_publishable_content
            kwargs = {"content_type": "note_article", "target_length": 6000, "theme": theme_hint}
            if extra_kwargs:
                kwargs.update(extra_kwargs)
            result = await generate_publishable_content(**kwargs)
            content = result.get("content", "")
            title = result.get("title", "無題")
            quality = result.get("quality_score", 0)

            # note_draftsに保存して品質チェッカー→商品パッケージングチェーンに乗せる
            if content and len(content) > 500 and quality >= 0.50:
                try:
                    import os as _os
                    drafts_dir = _os.path.join(
                        _os.path.dirname(__file__), "data", "artifacts", "note_drafts"
                    )
                    _os.makedirs(drafts_dir, exist_ok=True)
                    safe_title = "".join(
                        c for c in title[:30] if c.isalnum() or c in "ぁ-んァ-ヶ亜-熙_- "
                    ).strip() or "pipeline"
                    filename = f"note_{datetime.now().strftime('%Y%m%d_%H%M')}_{slot_name}_{safe_title}.md"
                    filepath = _os.path.join(drafts_dir, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n{content}")
                    logger.info(f"content_pipeline記事をnote_draftsに保存: {filepath} (slot={slot_name})")
                except Exception as e:
                    logger.warning(f"note_drafts保存失敗（タスクDBには記録済み）: {e}")

            if quality >= 0.70:
                try:
                    from tools.discord_notify import notify_discord
                    await notify_discord(
                        f"コンテンツ生成完了 [{slot_name}]: {title} (品質: {quality:.2f})"
                    )
                except Exception as e:
                    logger.warning(f"Discord通知失敗: {e}")
            logger.info(
                f"日次コンテンツ生成完了 [{slot_name}]: {title} "
                f"(品質: {quality:.2f})"
            )
        except Exception as e:
            logger.error(f"日次コンテンツ生成失敗 [{slot_name}]: {e}")

    async def generate_daily_content_morning(self):
        """07:30 JST: 海外トレンド先取り — trend_detector結果をベースに記事生成"""
        await self._generate_daily_content_impl(
            slot_name="morning",
            theme_hint="海外トレンド先取り: trend_detectorが検出した日本語記事が少ない海外トレンドを元に、"
                       "日本の読者向けに先取り解説する記事を書く。具体的なツール名・サービス名・数字を含めること。",
        )

    async def generate_daily_content_midday(self):
        """12:00 JST: SYUTAINβ実データベース — システム運用データから記事生成"""
        await self._generate_daily_content_impl(
            slot_name="midday",
            theme_hint="SYUTAINβ実データベース: SYUTAINβの実際の運用データ（コスト・収益・エラー率・"
                       "LLM使用量・SNSエンゲージメント等）を元に、AIシステム運用のリアルを語る記事を書く。"
                       "数値の裏付けがある内容を優先すること。",
        )

    async def generate_daily_content_evening(self):
        """18:00 JST: 自由テーマ — intel_items + persona driven"""
        await self._generate_daily_content_impl(
            slot_name="evening",
            theme_hint="自由テーマ: intel_itemsで収集した最新情報とpersona_memoryの価値観を組み合わせて、"
                       "島原大知の独自視点で書く自由テーマの記事。他のメディアにない切り口を重視すること。",
        )

    async def generate_daily_content(self):
        """後方互換: 旧generate_daily_contentはmorningスロットにフォールバック"""
        await self.generate_daily_content_morning()

    async def posting_queue_process(self):
        """毎分: posting_queueからscheduled_at<=NOWの投稿を実行"""
        try:
            import json
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                rows = await conn.fetch(
                    """UPDATE posting_queue SET status = 'processing'
                       WHERE id IN (
                           SELECT id FROM posting_queue
                           WHERE status = 'pending' AND scheduled_at <= NOW()
                             AND (quality_score >= 0.55 OR quality_score IS NULL)
                           ORDER BY scheduled_at ASC LIMIT 3
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, platform, account, content, quality_score"""
                )
                for row in rows:
                    platform = row["platform"]
                    account = row["account"]
                    content = row["content"]
                    post_id = row["id"]

                    # === 投稿前 最終品質ゲート ===
                    try:
                        from tools.platform_ng_check import check_platform_ng
                        ng_check = check_platform_ng(content, platform)
                        if not ng_check["passed"]:
                            logger.warning(f"posting_queue#{post_id} 最終NGチェック不合格: {ng_check['violations']}")
                            await conn.execute("UPDATE posting_queue SET status='failed' WHERE id=$1", post_id)
                            continue
                    except Exception as e:
                        logger.warning(f"posting_queue#{post_id} NGチェック失敗（投稿続行）: {e}")

                    # 重複チェック: 同じ日に同じ先頭30文字の投稿が既にpostedなら拒否
                    try:
                        dup = await conn.fetchval(
                            """SELECT COUNT(*) FROM posting_queue
                               WHERE status='posted' AND platform=$1
                               AND LEFT(content, 30) = LEFT($2, 30)
                               AND posted_at::date = CURRENT_DATE""",
                            platform, content,
                        )
                        if dup and dup > 0:
                            logger.warning(f"posting_queue#{post_id} 重複投稿検知→スキップ")
                            await conn.execute("UPDATE posting_queue SET status='failed' WHERE id=$1", post_id)
                            continue
                    except Exception as e:
                        logger.warning(f"posting_queue#{post_id} 重複チェック失敗（投稿続行）: {e}")

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
                        elif platform == "reminder":
                            # リマインダー: Discord通知のみ
                            try:
                                from tools.discord_notify import notify_discord
                                await notify_discord(content)
                            except Exception as e:
                                logger.warning(f"リマインダー通知失敗: {e}")
                            result = {"success": True, "post_url": "reminder"}

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
                                from tools.discord_notify import notify_error
                                await notify_error(
                                    f"sns_fail_{platform}_{post_id}",
                                    f"投稿失敗(3回リトライ後): {platform}/{account} (ID: {post_id})",
                                    severity="error",
                                )
                            else:
                                # pendingに戻してスケジュールを10分後にずらす（次のリトライ）
                                await conn.execute(
                                    "UPDATE posting_queue SET status='pending', scheduled_at = NOW() + INTERVAL '10 minutes' WHERE id=$1",
                                    post_id,
                                )
                                from tools.event_logger import log_event
                                await log_event("sns.post_retry", "sns", {
                                    "posting_queue_id": str(post_id), "platform": platform,
                                    "retry": (retry_count or 0) + 1, "error": result.get("reason", "")[:100],
                                }, severity="warning")
                    except Exception as e:
                        logger.error(f"posting_queue#{post_id} 投稿エラー: {e}")
                        await conn.execute("UPDATE posting_queue SET status='failed' WHERE id=$1", post_id)
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
            from brain_alpha.cross_evaluator import schedule_evaluations, apply_cross_evaluation_feedback
            result = await schedule_evaluations()
            total = result.get("fixes_evaluated", 0) + result.get("reviews_evaluated", 0)
            if total > 0:
                logger.info(f"Brain-α相互評価: {total}件評価完了")
            # 評価結果をself_healer/llm_routerにフィードバック
            try:
                fb = await apply_cross_evaluation_feedback()
                if fb.get("strategies_flagged", 0) > 0 or fb.get("model_adjustments", 0) > 0:
                    logger.info(f"相互評価フィードバック: {fb}")
            except Exception as fb_err:
                logger.warning(f"相互評価フィードバック失敗: {fb_err}")
        except Exception as e:
            logger.error(f"Brain-α相互評価失敗: {e}")

    async def expire_old_handoffs(self):
        """7日超過のpending brain_handoffをexpiredに更新"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                result = await conn.execute(
                    """UPDATE brain_handoff
                       SET status = 'expired'
                       WHERE status = 'pending'
                         AND created_at < NOW() - INTERVAL '7 days'"""
                )
                count = int(result.split()[-1]) if result else 0
                if count > 0:
                    logger.info(f"brain_handoff expired: {count}件")
        except Exception as e:
            logger.error(f"handoff期限切れ処理失敗: {e}")

    async def note_quality_check(self):
        """note記事品質チェック（30分おき、コストガード付き）"""
        try:
            from brain_alpha.note_quality_checker import NoteQualityChecker
            from tools.discord_notify import notify_discord

            checker = NoteQualityChecker()
            await checker.initialize()
            results = await checker.check_all_pending()

            for r in results:
                gpt5 = r.get("gpt5")
                if gpt5 and gpt5.get("publish_verdict") == "publish_ready":
                    await notify_discord(
                        f"✅ 記事『{r.get('title', '不明')}』が品質チェック通過。"
                        f"推奨価格: ¥{gpt5.get('pricing_recommendation', '-')}。"
                        f"チェックコスト: ¥{r.get('cost_jpy', 0):.1f}"
                    )
                elif gpt5 and gpt5.get("publish_verdict") == "needs_edit":
                    instructions = gpt5.get("edit_instructions", [])[:3]
                    await notify_discord(
                        f"⚠️ 記事『{r.get('title', '不明')}』に修正が必要。"
                        f"修正点: {', '.join(instructions)}"
                    )
                elif r.get("status") == "blocked":
                    await notify_discord(f"🛑 品質チェック停止: {r.get('reason', '不明')}")

            if results:
                total_cost = sum(r.get("cost_jpy", 0) for r in results)
                logger.info(f"note品質チェック完了: {len(results)}件, コスト: ¥{total_cost:.1f}")
                try:
                    from tools.event_logger import log_event
                    await log_event(
                        "note_quality.run_complete", "note_quality",
                        {"count": len(results), "cost_jpy": round(total_cost, 2)},
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"note品質チェックエラー: {e}")

    async def engagement_analysis(self):
        """エンゲージメント分析→投稿改善ループ"""
        try:
            from tools.engagement_analyzer import analyze_engagement_patterns
            result = await analyze_engagement_patterns()
            logger.info(f"エンゲージメント分析: {len(result.get('patterns', []))}パターン, top={result.get('top_themes', [])[:3]}")
        except Exception as e:
            logger.error(f"エンゲージメント分析失敗: {e}")

    async def overseas_trend_detection(self):
        """海外トレンド先取り検出 + 英語記事の取得・要約"""
        try:
            from tools.overseas_trend_detector import detect_overseas_trends, enrich_overseas_trends
            findings = await detect_overseas_trends()
            if findings:
                from tools.discord_notify import notify_discord
                high = [f for f in findings if f.get("opportunity") == "high"]
                if high:
                    await notify_discord(f"🌍 海外トレンド検出: {len(high)}件の先行者チャンス\n" +
                        "\n".join(f"  - {f['keyword']}: {f['title'][:60]}" for f in high[:3]))

            # 検出済みの英語記事を取得・要約してDB保存
            enriched = await enrich_overseas_trends()
            logger.info(f"海外トレンド: {len(findings)}件検出, {enriched}件の英語記事を要約済み")
        except Exception as e:
            logger.error(f"海外トレンド検出失敗: {e}")

    async def documentary_generation(self):
        """週次ドキュメンタリー記事生成: SYUTAINβ自身の運用データからnote記事を生成"""
        try:
            from tools.documentary_generator import generate_documentary_article
            result = await generate_documentary_article()
            content = result.get("content", "")
            title = result.get("title", "無題")
            quality = result.get("quality_score", 0)
            article_type = result.get("article_type", "unknown")

            # note_draftsに保存（通常のコンテンツパイプラインと同じパスに乗せる）
            if content and len(content) > 500 and quality >= 0.50:
                try:
                    import os as _os
                    drafts_dir = _os.path.join(
                        _os.path.dirname(__file__), "data", "artifacts", "note_drafts"
                    )
                    _os.makedirs(drafts_dir, exist_ok=True)
                    safe_title = "".join(
                        c for c in title[:30] if c.isalnum() or c in "ぁ-んァ-ヶ亜-熙_- "
                    ).strip() or "documentary"
                    filename = f"doc_{datetime.now().strftime('%Y%m%d_%H%M')}_{safe_title}.md"
                    filepath = _os.path.join(drafts_dir, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n{content}")
                    logger.info(f"ドキュメンタリー記事をnote_draftsに保存: {filepath}")
                except Exception as e:
                    logger.warning(f"ドキュメンタリー記事note_drafts保存失敗: {e}")

            if quality >= 0.50:
                try:
                    from tools.discord_notify import notify_discord
                    await notify_discord(
                        f"[Documentary] {title} (type={article_type}, score={quality:.2f})"
                    )
                except Exception as e:
                    logger.warning(f"Discord通知失敗: {e}")
            logger.info(
                f"ドキュメンタリー記事生成完了: {title} "
                f"(type={article_type}, score={quality:.2f})"
            )
        except Exception as e:
            logger.error(f"ドキュメンタリー記事生成失敗: {e}")

    async def buzz_account_analysis(self):
        """バズアカウント分析（Jina Search + LLMパターン分析）"""
        try:
            from tools.buzz_account_analyzer import analyze_buzz_accounts
            result = await analyze_buzz_accounts()
            logger.info(
                f"バズ分析完了: {result.get('posts_collected', 0)}件収集, "
                f"トレンド{len(result.get('trending_topics', []))}件, "
                f"ギャップ{len(result.get('content_gaps', []))}件"
            )
        except Exception as e:
            logger.error(f"バズ分析失敗: {e}")

    async def revenue_research(self):
        """月次収益機会リサーチ"""
        try:
            from tools.revenue_researcher import research_revenue_opportunities
            from tools.discord_notify import notify_discord
            report = await research_revenue_opportunities()
            ready = [o["model"] for o in report.get("opportunities", []) if o.get("syutain_readiness") == "ready"]
            if ready:
                await notify_discord(f"💰 収益リサーチ完了: 即開始可能={', '.join(ready)}")
            logger.info(f"収益リサーチ: {len(report.get('opportunities', []))}件")
        except Exception as e:
            logger.error(f"収益リサーチ失敗: {e}")

    async def semantic_cache_cleanup(self):
        """セマンティックキャッシュの期限切れエントリ削除"""
        try:
            from tools.semantic_cache import cleanup_expired
            deleted = await cleanup_expired()
            logger.info(f"セマンティックキャッシュ清掃: {deleted}件削除")
        except Exception as e:
            logger.error(f"キャッシュ清掃失敗: {e}")

    async def memory_consolidation(self):
        """夜間メモリ統合: 低Q値削除・類似統合・ペルソナ重複除去・キャッシュ清掃"""
        try:
            from tools.memory_consolidator import consolidate_memory
            stats = await consolidate_memory()
            total = (
                stats.get("low_q_deleted", 0)
                + stats.get("similar_merged", 0)
                + stats.get("persona_deduped", 0)
                + stats.get("cache_cleaned", 0)
            )
            logger.info(f"メモリ統合完了: 合計{total}件処理")
        except Exception as e:
            logger.error(f"メモリ統合失敗: {e}")

    async def karpathy_loop_cycle(self):
        """Karpathy自律改善サイクル（1日1パラメータ最適化）"""
        try:
            from agents.karpathy_loop import run_karpathy_cycle
            result = await run_karpathy_cycle()
            actions = result.get("actions", [])
            if actions:
                lines = []
                for a in actions:
                    if a["type"] == "experiment_started":
                        lines.append(
                            f"  実験開始: {a.get('param_key', '')} "
                            f"{a.get('old_value', ''):.4f}→{a.get('new_value', ''):.4f}"
                        )
                    elif a["type"] == "evaluated":
                        lines.append(
                            f"  評価完了: {a.get('param_key', '')} → {a.get('outcome', '')}"
                        )
                    elif a["type"] == "skipped":
                        lines.append(f"  {a.get('reason', 'スキップ')}")
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"🔄 Karpathy Loop: {len(actions)}アクション\n" + "\n".join(lines[:5])
                )
            logger.info(f"Karpathy: {len(actions)}アクション")
        except Exception as e:
            logger.error(f"Karpathyサイクル失敗: {e}")

    async def revenue_health_check(self):
        """収益パイプラインヘルスチェック"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # 各段階の状態確認
                content = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'success' AND created_at > NOW() - INTERVAL '24 hours'") or 0
                posted = await conn.fetchval("SELECT COUNT(*) FROM posting_queue WHERE status = 'posted' AND posted_at > NOW() - INTERVAL '24 hours'") or 0
                revenue = await conn.fetchval("SELECT COALESCE(SUM(revenue_jpy), 0) FROM revenue_linkage WHERE created_at > NOW() - INTERVAL '7 days'") or 0
                logger.info(f"収益パイプライン: tasks={content}, posted={posted}, revenue_7d=¥{revenue}")
        except Exception as e:
            logger.error(f"収益ヘルスチェック失敗: {e}")

    async def garbage_collection(self):
        """週次ゴミ収集（Harness Engineering）"""
        try:
            from agents.garbage_collector import run_garbage_collection, format_gc_report
            from tools.discord_notify import notify_discord
            report = await run_garbage_collection()
            logger.info(f"ゴミ収集完了: findings={len(report.get('findings', []))}")
            if report.get("findings"):
                md = format_gc_report(report)
                await notify_discord(md)
        except Exception as e:
            logger.error(f"ゴミ収集エラー: {e}")

    async def feature_test_run(self):
        """日次フィーチャーテスト（Harness Engineering）"""
        try:
            from tools.feature_test_runner import run_feature_tests
            results = await run_feature_tests()
            logger.info(f"フィーチャーテスト: passing={results['passing']}, failing={results['failing']}")
            if results.get("changed"):
                from tools.discord_notify import notify_discord
                changes = ", ".join(f"{c['id']}: {c['from']}→{c['to']}" for c in results["changed"][:5])
                await notify_discord(f"⚡ フィーチャーテスト変更検出: {changes}")
        except Exception as e:
            logger.error(f"フィーチャーテストエラー: {e}")

    async def doc_gardening(self):
        """週次ドキュメントガーデニング（Harness Engineering）"""
        try:
            from tools.doc_gardener import run_and_queue
            result = await run_and_queue()
            logger.info(f"ドキュメントガーデニング完了: {result['total']}件検出, {result['queued']}件キュー登録")
        except Exception as e:
            logger.error(f"ドキュメントガーデニングエラー: {e}")

    async def note_auto_publish(self):
        """承認済みnoteパッケージを自動公開（30分間隔）"""
        try:
            from tools.note_publisher import note_auto_publish_check
            result = await note_auto_publish_check()
            if result.get("skipped") == -1:
                logger.debug("note自動公開: feature flag無効")
            elif result.get("published", 0) > 0:
                logger.info(
                    f"note自動公開: 成功{result['published']}件, "
                    f"失敗{result['failed']}件"
                )
            else:
                logger.debug("note自動公開: 対象なし")
        except Exception as e:
            logger.error(f"note自動公開エラー: {e}")

    async def log_cleanup(self):
        """7日超の古いログファイルを削除（毎日04:30 JST）"""
        import glob
        import time as _time

        log_dir = os.getenv("LOG_DIR", "logs")
        max_age_days = 7
        cutoff = _time.time() - (max_age_days * 86400)
        deleted = 0

        try:
            for filepath in glob.glob(os.path.join(log_dir, "*.log*")):
                # .gitkeepは除外
                if os.path.basename(filepath) == ".gitkeep":
                    continue
                # RotatingFileHandlerのバックアップ(.log.1, .log.2等)も対象
                try:
                    mtime = os.path.getmtime(filepath)
                    if mtime < cutoff:
                        os.remove(filepath)
                        deleted += 1
                        logger.debug(f"古いログ削除: {filepath}")
                except OSError as e:
                    logger.warning(f"ログ削除失敗 ({filepath}): {e}")

            if deleted > 0:
                logger.info(f"ログクリーンアップ完了: {deleted}ファイル削除（{max_age_days}日超）")
            else:
                logger.debug("ログクリーンアップ: 削除対象なし")
        except Exception as e:
            logger.error(f"ログクリーンアップエラー: {e}")

    async def approval_queue_cleanup(self):
        """承認キュー自動クリーンアップ（毎日05:00 JST）

        - 72時間超過のpending承認をexpiredに変更
        - 7日超過のexpired承認を削除
        - クリーンアップ結果をDiscord通知
        """
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # 72時間超過のpending → expired
                expired_result = await conn.execute(
                    """UPDATE approval_queue
                       SET status = 'expired', responded_at = NOW()
                       WHERE status = 'pending'
                       AND requested_at < NOW() - INTERVAL '72 hours'"""
                )
                expired_count = int(expired_result.split()[-1]) if expired_result else 0

                # 7日超過のexpired → 削除
                deleted_result = await conn.execute(
                    """DELETE FROM approval_queue
                       WHERE status = 'expired'
                       AND responded_at < NOW() - INTERVAL '7 days'"""
                )
                deleted_count = int(deleted_result.split()[-1]) if deleted_result else 0

                if expired_count > 0 or deleted_count > 0:
                    logger.info(
                        f"承認キュークリーンアップ: {expired_count}件期限切れ, {deleted_count}件削除"
                    )

                    # イベントログ記録
                    try:
                        from tools.event_logger import log_event
                        await log_event(
                            "approval.cleanup",
                            "system",
                            {"expired": expired_count, "deleted": deleted_count},
                            severity="info",
                        )
                    except Exception:
                        pass

                    # Discord通知（実際にクリーンアップが発生した場合のみ）
                    if expired_count > 0 or deleted_count > 0:
                        try:
                            from tools.discord_notify import notify_discord
                            await notify_discord(
                                f"承認キュークリーンアップ: 期限切れ{expired_count}件 / 削除{deleted_count}件"
                            )
                        except Exception as e:
                            logger.debug(f"クリーンアップ通知失敗: {e}")
                else:
                    logger.debug("承認キュークリーンアップ: 対象なし")

        except Exception as e:
            logger.error(f"承認キュークリーンアップエラー: {e}")

    async def skill_extraction(self):
        """毎日04:00: 高Q値エピソードからスキルを抽出"""
        try:
            from tools.skill_manager import get_skill_manager
            sm = get_skill_manager()
            created = await sm.extract_skills()
            if created:
                from tools.event_logger import log_event
                await log_event(
                    "system.skill_extraction", "system",
                    {"created_count": len(created), "skills": [s["name"] for s in created]},
                )
                logger.info(f"スキル抽出完了: {len(created)}件作成")
            else:
                logger.info("スキル抽出: 新規スキルなし")
        except Exception as e:
            logger.error(f"スキル抽出エラー: {e}")

    async def harness_health_check(self):
        """毎時: ハーネス健全性スコアを算出しevent_logに記録"""
        try:
            from tools.harness_health import calculate_health_score
            result = await calculate_health_score()

            from tools.event_logger import log_event
            await log_event(
                "system.harness_health", "system",
                {
                    "overall": result["overall"],
                    "grade": result["grade"],
                    "components": {
                        k: {"score": v["score"], "detail": v["detail"]}
                        for k, v in result.get("components", {}).items()
                    },
                    "recommendations": result.get("recommendations", []),
                },
                severity="warning" if result["overall"] < 50 else "info",
            )
            logger.info(
                f"ハーネス健全性: {result['overall']}/100 "
                f"(Grade {result['grade']})"
            )
        except Exception as e:
            logger.error(f"ハーネス健全性チェックエラー: {e}")

    async def self_test_full(self):
        """日次フルテストスイート（毎日06:00）— API消費ゼロ"""
        try:
            from tests.test_runner import run_all_tests
            results = await run_all_tests(include_remote=True)
            passed = results.get('total_passed', 0)
            failed = results.get('total_failed', 0)
            elapsed = results.get('elapsed_sec', 0)
            logger.info(f"自動テスト完了: passed={passed}, failed={failed}, elapsed={elapsed}s")

            try:
                from tools.event_logger import log_event
                await log_event("system.self_test", "system", {
                    "passed": passed, "failed": failed, "elapsed_sec": elapsed,
                    "errors": results.get("errors", [])[:5],
                })
            except Exception:
                pass

            if failed > 0:
                # 失敗時: 具体的なエラー内容をDiscord通知
                error_details = results.get("errors", [])
                error_summary = "; ".join(
                    f"{e.get('module', e.get('file', '?'))}: {e.get('error', '?')[:80]}"
                    for e in error_details[:5]
                )
                try:
                    from tools.discord_notify import notify_error
                    await notify_error(
                        "self_test_failure",
                        f"自動テスト失敗: {failed}件\n"
                        f"passed={passed}, failed={failed}\n"
                        f"{error_summary}",
                        severity="error",
                    )
                except Exception:
                    pass
            else:
                # 全パス時: 成功を記録（通知は不要）
                logger.info(f"自動テスト全パス: {passed}件 ({elapsed:.1f}s)")
        except Exception as e:
            logger.error(f"自動テストエラー: {e}")

    async def self_test_syntax(self):
        """毎時構文チェック（軽量）"""
        try:
            from tests.test_runner import run_syntax_only
            results = await run_syntax_only()
            if results["failed"] > 0:
                error_details = results.get("errors", [])
                error_summary = "; ".join(
                    f"{e.get('file', '?')}:{e.get('line', '?')}"
                    for e in error_details[:3]
                )
                logger.warning(f"構文エラー検出: {results['failed']}件 — {error_summary}")
                try:
                    from tools.discord_notify import notify_error
                    await notify_error(
                        "syntax_check_failure",
                        f"構文エラー検出: {results['failed']}件\n{error_summary}",
                        severity="warning",
                    )
                except Exception:
                    pass
            else:
                logger.debug(f"構文チェックOK: {results['passed']}ファイル")
        except Exception as e:
            logger.error(f"構文チェックエラー: {e}")

    async def dependency_mapping(self):
        """週次依存関係マッピング（毎週月曜06:30）"""
        try:
            from tools.dependency_mapper import generate_code_map
            content = await generate_code_map()
            lines_count = len(content.splitlines())
            logger.info(f"依存関係マッピング完了: CODE_MAP.md ({lines_count}行)")
        except Exception as e:
            logger.error(f"依存関係マッピングエラー: {e}")

    async def gstack_code_review(self):
        """日次gstackコードレビュー（毎日09:00）"""
        try:
            from tools.gstack_executor import run_code_review
            from tools.event_logger import log_event
            result = await run_code_review()
            await log_event("gstack.review", "gstack", {
                "success": result["success"],
                "duration_ms": result["duration_ms"],
                "output_preview": result["output"][:300],
            })
            logger.info(f"gstackコードレビュー: {'OK' if result['success'] else 'FAIL'} ({result['duration_ms']}ms)")

            # issues検出時はDiscord通知
            output_lower = result["output"].lower()
            no_findings = (
                "pre-landing review: no issues found." in output_lower
                or "pre-landing review: 0 issues" in output_lower
                or "no issues found" in output_lower
            )
            if result["success"] and (not no_findings) and any(
                kw in output_lower for kw in ["issue", "warning", "error", "bug", "問題", "脆弱"]
            ):
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"[gstack] コードレビュー指摘あり\n{result['output'][:500]}"
                )
        except Exception as e:
            logger.error(f"gstackコードレビューエラー: {e}")

    async def gstack_security_audit(self):
        """週次gstackセキュリティ監査（毎週日曜02:00）"""
        try:
            from tools.gstack_executor import run_security_audit
            from tools.event_logger import log_event
            result = await run_security_audit()
            await log_event("gstack.cso", "gstack", {
                "success": result["success"],
                "duration_ms": result["duration_ms"],
                "output_preview": result["output"][:300],
            })
            logger.info(f"gstackセキュリティ監査: {'OK' if result['success'] else 'FAIL'} ({result['duration_ms']}ms)")

            # セキュリティ問題検出時はDiscord通知 + critical時はPDLキュー登録
            output_lower = result["output"].lower()
            no_findings = ("no issues found" in output_lower) or ("問題なし" in result["output"])
            if result["success"] and (not no_findings) and any(
                kw in output_lower for kw in ["critical", "vulnerability", "脆弱性", "危険", "high risk"]
            ):
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"[gstack] セキュリティ監査: 重大な問題検出\n{result['output'][:500]}"
                )
                # PDL Session Bにタスク登録
                try:
                    from tools.db_pool import get_connection
                    async with get_connection() as conn:
                        await conn.execute(
                            """INSERT INTO claude_code_queue (category, description, priority, session_type, status)
                               VALUES ($1, $2, $3, $4, $5)""",
                            "security_fix",
                            f"[gstack-cso] セキュリティ監査で検出された問題の修正:\n{result['output'][:1000]}",
                            "critical",
                            "autonomous",
                            "pending",
                        )
                    logger.info("gstackセキュリティ監査: PDLキューにcriticalタスク登録")
                except Exception as qe:
                    logger.error(f"gstackセキュリティ監査: PDLキュー登録失敗: {qe}")
            elif result["success"] and (not no_findings) and any(
                kw in output_lower for kw in ["issue", "warning", "問題", "注意"]
            ):
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"[gstack] セキュリティ監査: 指摘あり\n{result['output'][:500]}"
                )
        except Exception as e:
            logger.error(f"gstackセキュリティ監査エラー: {e}")

    async def gstack_retro(self):
        """週次gstack振り返り（毎週月曜08:00）"""
        try:
            from tools.gstack_executor import run_retro
            from tools.event_logger import log_event
            result = await run_retro()
            await log_event("gstack.retro", "gstack", {
                "success": result["success"],
                "duration_ms": result["duration_ms"],
                "output_preview": result["output"][:300],
            })
            logger.info(f"gstack週次振り返り: {'OK' if result['success'] else 'FAIL'} ({result['duration_ms']}ms)")

            # 振り返り結果をDiscord通知
            if result["success"] and result["output"].strip():
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"[gstack] 週次振り返り完了\n{result['output'][:500]}"
                )
        except Exception as e:
            logger.error(f"gstack週次振り返りエラー: {e}")

    async def intel_bulletin_x(self):
        """X @syutain_beta「今日のAI速報」: intel_itemsから重要アイテムを選定してX投稿キューに追加"""
        try:
            from tools.db_pool import get_connection
            from tools.llm_router import choose_best_model_v6, call_llm
            from tools.event_logger import log_event

            async with get_connection() as conn:
                # 直近24時間の重要intel_itemsを取得（importance_score >= 0.5）
                rows = await conn.fetch("""
                    SELECT id, title, source, importance_score, summary
                    FROM intel_items
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    AND importance_score >= 0.5
                    AND source IN ('overseas_trend', 'english_article', 'trend_detector', 'tavily')
                    ORDER BY importance_score DESC
                    LIMIT 3
                """)
                if not rows:
                    logger.info("intel_bulletin_x: 重要アイテムなし（スキップ）")
                    return

                # 今日既に生成済みか確認
                already = await conn.fetchval("""
                    SELECT COUNT(*) FROM posting_queue
                    WHERE platform = 'x' AND account = 'syutain'
                    AND theme_category = 'intel_bulletin'
                    AND scheduled_at > CURRENT_DATE
                """)
                if already and already > 0:
                    logger.info("intel_bulletin_x: 本日既に生成済み")
                    return

                # トップ1アイテムでX投稿文を生成
                top = rows[0]
                model_sel = choose_best_model_v6(
                    task_type="sns",
                    quality="medium",
                    budget_sensitive=True,
                    needs_japanese=True,
                )
                prompt = (
                    f"以下の情報から、X（Twitter）投稿文を1つ生成してください。\n"
                    f"タイトル: {top['title']}\n"
                    f"要約: {(top['summary'] or '')[:200]}\n"
                    f"ソース: {top['source']}\n\n"
                    f"フォーマット（150文字以内厳守）:\n"
                    f"🌐 SYUTAINβ情報検出: [タイトル要約]. [SYUTAINβの視点からの1行コメント]\n\n"
                    f"ルール:\n"
                    f"- 150文字以内（絶対厳守）\n"
                    f"- 冒頭は「🌐 SYUTAINβ情報検出:」で始める\n"
                    f"- SYUTAINβがAIシステムとして検出したという視点\n"
                    f"- ハッシュタグ不要\n"
                    f"投稿文のみ出力:"
                )
                result = await call_llm(
                    prompt=prompt,
                    system_prompt="SYUTAINβのSNS投稿生成。150文字以内で簡潔に。",
                    model_selection=model_sel,
                    goal_id="intel_bulletin_x",
                    max_tokens=200,
                )
                draft = (result.get("text") or "").strip()
                if not draft or len(draft) > 150:
                    # 150文字超の場合は切り詰め
                    draft = draft[:147] + "..." if draft else None

                if draft:
                    from datetime import datetime as dt
                    from zoneinfo import ZoneInfo
                    jst_now = dt.now(ZoneInfo("Asia/Tokyo"))
                    await conn.execute(
                        """INSERT INTO posting_queue
                           (platform, account, content, scheduled_at, status, quality_score, theme_category)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        "x", "syutain", draft,
                        jst_now.replace(hour=12, minute=0, second=0, microsecond=0),
                        "pending", 0.7, "intel_bulletin",
                    )
                    await log_event("intel.bulletin_x_queued", "system", {
                        "intel_id": top["id"],
                        "title": top["title"][:80],
                        "draft_length": len(draft),
                    })
                    logger.info(f"intel_bulletin_x: 投稿キュー追加 ({len(draft)}文字)")
        except Exception as e:
            logger.error(f"intel_bulletin_xエラー: {e}")

    async def weekly_intel_digest(self):
        """週次インテルダイジェスト: 過去7日間のintel_itemsをまとめてBluesky+note_draftsに保存"""
        try:
            from tools.db_pool import get_connection
            from tools.llm_router import choose_best_model_v6, call_llm
            from tools.event_logger import log_event

            async with get_connection() as conn:
                # 過去7日間のimportance_score >= 0.3のアイテムを取得
                rows = await conn.fetch("""
                    SELECT id, title, source, importance_score, summary, category
                    FROM intel_items
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    AND importance_score >= 0.3
                    ORDER BY importance_score DESC
                    LIMIT 10
                """)
                if len(rows) < 5:
                    logger.info(f"weekly_intel_digest: アイテム不足 ({len(rows)}/5件) スキップ")
                    return

                # ソース別グループ化してコンテキスト作成
                context_lines = []
                for r in rows:
                    context_lines.append(
                        f"- [{r['source']}] {r['title']} "
                        f"(重要度:{r['importance_score']:.1f}, カテゴリ:{r['category']})"
                    )
                    if r['summary']:
                        context_lines.append(f"  要約: {(r['summary'] or '')[:100]}")

                model_sel = choose_best_model_v6(
                    task_type="content",
                    quality="medium",
                    budget_sensitive=True,
                    needs_japanese=True,
                )
                prompt = (
                    f"以下の今週SYUTAINβが収集した情報（{len(rows)}件）から、\n"
                    f"「今週SYUTAINβが検出した注目情報」というタイトルの週次ダイジェストを生成してください。\n\n"
                    f"## 収集情報\n"
                    + "\n".join(context_lines) + "\n\n"
                    f"## ルール\n"
                    f"- 500文字以内\n"
                    f"- 冒頭: 「📊 今週SYUTAINβが検出した注目情報（週次ダイジェスト）」\n"
                    f"- トップ3-5件を簡潔に紹介\n"
                    f"- SYUTAINβがAIシステムとして自動収集・選定した情報であることを明記\n"
                    f"- Build in Public方針と矛盾しない（「システムが検出した情報」として出す）\n"
                    f"ダイジェスト本文のみ出力:"
                )
                result = await call_llm(
                    prompt=prompt,
                    system_prompt="SYUTAINβの週次情報ダイジェスト生成。500文字以内で簡潔に。",
                    model_selection=model_sel,
                    goal_id="weekly_intel_digest",
                    max_tokens=600,
                )
                digest_text = (result.get("text") or "").strip()
                if not digest_text:
                    logger.warning("weekly_intel_digest: LLM生成失敗")
                    return

                from datetime import datetime as dt
                from zoneinfo import ZoneInfo
                jst_now = dt.now(ZoneInfo("Asia/Tokyo"))

                # Bluesky posting_queueに追加
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "bluesky", "syutain", digest_text[:300],
                    jst_now.replace(hour=20, minute=30, second=0, microsecond=0),
                    "pending", 0.8, "intel_digest_weekly",
                )

                # note_draftsにも保存
                try:
                    week_label = jst_now.strftime("%Y-W%W")
                    await conn.execute(
                        """INSERT INTO note_drafts
                           (title, body, status, category, created_at)
                           VALUES ($1, $2, $3, $4, NOW())""",
                        f"今週SYUTAINβが検出した注目情報（{week_label}）",
                        digest_text,
                        "draft",
                        "intel_digest",
                    )
                except Exception as e:
                    logger.warning(f"weekly_intel_digest: note_drafts保存失敗（続行）: {e}")

                await log_event("intel.weekly_digest_generated", "system", {
                    "items_count": len(rows),
                    "digest_length": len(digest_text),
                })
                logger.info(f"weekly_intel_digest: 生成完了 ({len(digest_text)}文字, {len(rows)}件)")
        except Exception as e:
            logger.error(f"weekly_intel_digestエラー: {e}")

    async def daily_syutain_report(self):
        """毎日12:00 JST: SYUTAINβ日報（note無料連載用）をローカルLLMで自動生成"""
        try:
            from tools.db_pool import get_connection
            from tools.llm_router import choose_best_model_v6, call_llm
            from tools.event_logger import log_event
            import os as _os

            async with get_connection() as conn:
                # 直近24時間のシステム実データを収集
                data = {}

                # LLMコスト
                cost = await conn.fetchrow(
                    "SELECT count(*) as calls, COALESCE(SUM(amount_jpy),0) as total FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours'"
                )
                data["llm"] = {"calls": cost["calls"], "cost_jpy": round(float(cost["total"]), 2)} if cost else {}

                # SNS投稿
                sns = await conn.fetch(
                    "SELECT platform, count(*) as cnt FROM posting_queue WHERE status='posted' AND posted_at > NOW() - INTERVAL '24 hours' GROUP BY platform"
                )
                data["sns"] = {r["platform"]: r["cnt"] for r in sns}

                # エラー
                errors = await conn.fetchval(
                    "SELECT count(*) FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '24 hours'"
                )
                data["errors_24h"] = errors or 0

                # LoopGuard
                lg = await conn.fetchval(
                    "SELECT count(*) FROM loop_guard_events WHERE created_at > NOW() - INTERVAL '24 hours'"
                )
                data["loopguard_24h"] = lg or 0

                # ゴール
                goals = await conn.fetch(
                    "SELECT status, count(*) as cnt FROM goal_packets WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY status"
                )
                data["goals"] = {r["status"]: r["cnt"] for r in goals}

                # イベント総数
                events = await conn.fetchval(
                    "SELECT count(*) FROM event_log WHERE created_at > NOW() - INTERVAL '24 hours'"
                )
                data["events_24h"] = events or 0

                # 暗号通貨（最新BTC価格）
                btc = await conn.fetchval(
                    "SELECT payload->>'price' FROM event_log WHERE event_type='trade.price_snapshot' AND payload->>'pair'='BTC_JPY' ORDER BY created_at DESC LIMIT 1"
                )
                data["btc_jpy"] = btc or "N/A"

                # ローカルLLMで日報生成
                model_sel = choose_best_model_v6(
                    task_type="content", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )
                result = await call_llm(
                    prompt=(
                        f"以下のSYUTAINβ実データから、今日のシステム日報を書いてください。\n\n"
                        f"## データ\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
                        f"## 出力ルール\n"
                        f"- 500-800字で簡潔に\n"
                        f"- 島原大知の一人称「僕」で、Build in Publicのドキュメンタリーとして書く\n"
                        f"- 数字は全て実データをそのまま使う。捏造禁止\n"
                        f"- 「壊れたこと」「動いていること」「気づいたこと」の3構成\n"
                        f"- タイトルを1行目に（例: 「SYUTAINβ日報 #N — 今日は○○が壊れた」）\n"
                        f"- 外部AIニュース解説は禁止。SYUTAINβ内部の出来事のみ\n"
                    ),
                    system_prompt="SYUTAINβの日報ライター。島原大知の文体で、実データに基づく日報を書く。",
                    model_selection=model_sel,
                )

                report_text = result.get("text", "").strip()
                if report_text and len(report_text) > 100:
                    # ファイル保存
                    from datetime import datetime as _dt
                    drafts_dir = _os.path.join(_os.path.dirname(__file__), "data", "artifacts", "note_drafts")
                    _os.makedirs(drafts_dir, exist_ok=True)
                    filename = f"daily_report_{_dt.now().strftime('%Y%m%d')}.md"
                    filepath = _os.path.join(drafts_dir, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(report_text)

                    await log_event("content.daily_report", "task", {
                        "length": len(report_text), "filepath": filepath,
                        "model": result.get("model_used"),
                    })

                    # Discord通知
                    try:
                        from tools.discord_notify import notify_discord
                        await notify_discord(
                            f"📓 SYUTAINβ日報生成完了 ({len(report_text)}字)\n"
                            f"保存先: {filepath}"
                        )
                    except Exception:
                        pass

                    logger.info(f"daily_syutain_report: {len(report_text)}字 saved to {filepath}")
        except Exception as e:
            logger.error(f"daily_syutain_reportエラー: {e}")

    async def weekly_x_thread(self):
        """月木 10:00 JST: Xスレッド用コンテンツ（4-6ツイート）をローカルLLMで生成"""
        try:
            from tools.db_pool import get_connection
            from tools.llm_router import choose_best_model_v6, call_llm
            from tools.event_logger import log_event

            weekday = datetime.now().weekday()
            if weekday == 0:  # 月曜: 先週の数値スレッド
                thread_theme = "weekly_metrics"
                thread_title = "先週のSYUTAINβ運用数値"
            elif weekday == 3:  # 木曜: 壊れた話スレッド
                thread_theme = "weekly_failures"
                thread_title = "今週壊れたもの・直したもの"
            else:
                return  # 月木以外はスキップ

            async with get_connection() as conn:
                data = {}

                if thread_theme == "weekly_metrics":
                    # 先週の数値データ
                    llm = await conn.fetchrow(
                        "SELECT count(*) as calls, COALESCE(SUM(amount_jpy),0) as cost FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '7 days'"
                    )
                    data["llm_calls_7d"] = llm["calls"] if llm else 0
                    data["llm_cost_7d"] = round(float(llm["cost"]), 2) if llm else 0

                    sns = await conn.fetchrow(
                        "SELECT count(*) as total FROM posting_queue WHERE status='posted' AND posted_at > NOW() - INTERVAL '7 days'"
                    )
                    data["sns_posted_7d"] = sns["total"] if sns else 0

                    events = await conn.fetchval(
                        "SELECT count(*) FROM event_log WHERE created_at > NOW() - INTERVAL '7 days'"
                    )
                    data["events_7d"] = events or 0

                    lg = await conn.fetchval(
                        "SELECT count(*) FROM loop_guard_events WHERE created_at > NOW() - INTERVAL '7 days'"
                    )
                    data["loopguard_7d"] = lg or 0

                elif thread_theme == "weekly_failures":
                    # 今週のエラーデータ
                    errors = await conn.fetch(
                        "SELECT event_type, count(*) as cnt FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '7 days' GROUP BY event_type ORDER BY cnt DESC LIMIT 5"
                    )
                    data["errors"] = [{"type": r["event_type"], "count": r["cnt"]} for r in errors]

                    lg = await conn.fetch(
                        "SELECT layer_name, count(*) as cnt FROM loop_guard_events WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY layer_name ORDER BY cnt DESC"
                    )
                    data["loopguard"] = [{"layer": r["layer_name"], "count": r["cnt"]} for r in lg]

                model_sel = choose_best_model_v6(
                    task_type="content", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )
                result = await call_llm(
                    prompt=(
                        f"以下のSYUTAINβ実データから、Xスレッド（4-6ツイート）を生成してください。\n\n"
                        f"## テーマ: {thread_title}\n"
                        f"## データ\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
                        f"## 出力ルール\n"
                        f"- 各ツイートは日本語140字以内（厳守）\n"
                        f"- 1ツイート目: フックとなる数字や事実\n"
                        f"- 2-4ツイート目: 詳細（実データ引用必須）\n"
                        f"- 最終ツイート: 学びor次週の課題\n"
                        f"- 各ツイートを「---」で区切って出力\n"
                        f"- 一人称「僕」。島原大知として書く\n"
                        f"- 数字は実データをそのまま使う。捏造禁止\n"
                        f"- Build in Public: SYUTAINβの実体験のみ。外部AIニュース解説禁止\n"
                    ),
                    system_prompt="SYUTAINβのXスレッドライター。Build in Public方針で実データに基づくスレッドを書く。",
                    model_selection=model_sel,
                )

                thread_text = result.get("text", "").strip()
                if thread_text and len(thread_text) > 50:
                    # スレッドを分割してposting_queueに投入
                    tweets = [t.strip() for t in thread_text.split("---") if t.strip()]
                    scheduled_time = datetime.now().replace(hour=12, minute=0, second=0)

                    for i, tweet in enumerate(tweets[:6]):
                        if len(tweet) > 150:
                            tweet = tweet[:147] + "..."
                        thread_ctx = json.dumps({"thread_id": f"thread_{datetime.now().strftime('%Y%m%d')}_{thread_theme}", "position": i + 1, "total": len(tweets)})
                        await conn.execute(
                            """INSERT INTO posting_queue
                               (platform, account, content, scheduled_at, status, quality_score, theme_category, thread_context)
                               VALUES ('x', 'syutain', $1, $2, 'pending', 0.80, $3, $4)""",
                            tweet,
                            scheduled_time + timedelta(minutes=i * 3),
                            f"thread_{thread_theme}",
                            thread_ctx,
                        )

                    await log_event("content.x_thread_generated", "task", {
                        "theme": thread_theme, "tweets": len(tweets),
                        "model": result.get("model_used"),
                    })

                    try:
                        from tools.discord_notify import notify_discord
                        await notify_discord(
                            f"🧵 Xスレッド生成: {thread_title} ({len(tweets)}ツイート)\n"
                            f"12:00から3分間隔で投稿予定"
                        )
                    except Exception:
                        pass

                    logger.info(f"weekly_x_thread: {thread_theme} {len(tweets)}tweets queued")
        except Exception as e:
            logger.error(f"weekly_x_threadエラー: {e}")

    def stop(self):
        """スケジューラーを停止"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("スケジューラー停止")


async def _restore_session():
    """起動時: 最新のbrain_alpha_sessionを復元しログに出力"""
    try:
        from brain_alpha.memory_manager import load_session_memory
        sessions = await load_session_memory(limit=1)
        if sessions:
            s = sessions[0]
            logger.info(
                f"セッション復元: {s.get('session_id', 'unknown')} "
                f"(未解決: {len(s.get('unresolved_issues', []))}件)"
            )
            issues = s.get("unresolved_issues", [])
            if issues:
                for issue in issues[:5]:
                    logger.info(f"  未解決: {issue}")
        else:
            logger.info("セッション復元: 前回セッションなし（初回起動）")
    except Exception as e:
        logger.warning(f"セッション復元失敗（続行）: {e}")


async def _save_session_on_shutdown():
    """シャットダウン時: 現在の状態をセッション保存"""
    try:
        from brain_alpha.session_save import save_session
        await save_session()
        logger.info("シャットダウン時セッション保存完了")
    except Exception as e:
        logger.warning(f"シャットダウン時セッション保存失敗: {e}")


async def main():
    scheduler = SyutainScheduler()
    await scheduler.start()

    # 起動時セッション復元
    await _restore_session()

    # SIGTERM/SIGINTハンドラ登録（グレースフルシャットダウン）
    import signal

    _shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        logger.info(f"シグナル受信: {signal.Signals(sig).name}")
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # メインループ（スケジューラーはバックグラウンドで動作）
    try:
        await _shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("グレースフルシャットダウン開始")
        await _save_session_on_shutdown()
        scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
