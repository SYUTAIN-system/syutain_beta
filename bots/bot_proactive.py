"""プロアクティブ知性 — 適切なタイミングで能動的に報告・提案・警告"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.bot_proactive")


class ProactiveIntelligence:
    """能動報告のタイミング制御

    報告カテゴリ別のタイミング:
    1. 緊急（即座）: CRITICALエラー、ノードダウン、Emergency Kill
    2. タイムリー（島原アクティブ時）: 承認待ち3件以上、高品質成果物完成、週次提案
    3. 定期: 朝の報告（07:00）、夜のサマリー（22:00）
    4. コンテキスト: 対話の流れに関連する情報を補足

    ルール:
    - 島原のメッセージなしで連続2回以上能動報告しない
    - 前回の能動報告から5分以内に再報告しない（緊急は除く）
    - 「静かにして」「後で」で次のメッセージまで停止
    """

    def __init__(self):
        self._consecutive_reports = 0  # 連続報告カウント
        self._last_report_at: datetime | None = None
        self._silenced = False  # 「静かにして」で停止
        self._last_daichi_msg_at: datetime | None = None
        self._last_emergency_alerts: dict[str, datetime] = {}  # throttle per alert key

    def on_daichi_message(self):
        """島原からメッセージを受信した時"""
        self._consecutive_reports = 0
        self._silenced = False
        self._last_daichi_msg_at = datetime.now(timezone.utc)

    def on_silence_request(self):
        """「静かにして」「後で」を検出"""
        self._silenced = True

    def can_report(self, priority: str = "normal") -> bool:
        """報告して良いかどうか"""
        now = datetime.now(timezone.utc)

        # 緊急は常に報告可能（サイレンスモードも突破）
        if priority == "urgent":
            return True

        # サイレンスモード
        if self._silenced:
            return False

        # 連続2回以上は不可
        if self._consecutive_reports >= 2:
            return False

        # 5分以内の再報告は不可
        if self._last_report_at and (now - self._last_report_at) < timedelta(minutes=5):
            return False

        return True

    _ALERT_CACHE_FILE = "/tmp/syutain_alert_cooldowns.json"

    def _load_alert_cache(self) -> dict:
        """ファイルからクールダウン記録を復元（bot再起動に対応）"""
        import json as _json
        try:
            with open(self._ALERT_CACHE_FILE, "r") as f:
                data = _json.load(f)
                # ISO形式文字列 → datetime に変換
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_alert_cache(self):
        """クールダウン記録をファイルに永続化"""
        import json as _json
        try:
            data = {k: v.isoformat() for k, v in self._last_emergency_alerts.items()}
            with open(self._ALERT_CACHE_FILE, "w") as f:
                _json.dump(data, f)
        except Exception:
            pass

    def can_emergency_alert(self, alert_key: str, cooldown_minutes: int = 5) -> bool:
        """同一緊急アラートのスロットル。ファイル永続化でbot再起動にも対応。"""
        now = datetime.now(timezone.utc)
        # メモリキャッシュが空ならファイルから復元
        if not self._last_emergency_alerts:
            self._last_emergency_alerts = self._load_alert_cache()
        last = self._last_emergency_alerts.get(alert_key)
        if last and (now - last) < timedelta(minutes=cooldown_minutes):
            return False
        return True

    def record_emergency_alert(self, alert_key: str):
        """緊急アラート送信を記録（メモリ + ファイル永続化）"""
        self._last_emergency_alerts[alert_key] = datetime.now(timezone.utc)
        self._save_alert_cache()

    def record_report(self):
        """報告を記録"""
        self._consecutive_reports += 1
        self._last_report_at = datetime.now(timezone.utc)

    def is_daichi_active(self, minutes: int = 30) -> bool:
        """島原が直近N分以内にアクティブか"""
        if not self._last_daichi_msg_at:
            return False
        return datetime.now(timezone.utc) - self._last_daichi_msg_at < timedelta(minutes=minutes)


# グローバルインスタンス
proactive = ProactiveIntelligence()


def detect_silence_request(message: str) -> bool:
    """「静かにして」系のリクエストを検出"""
    triggers = ["静かにして", "黙って", "後で", "あとで", "今忙しい", "うるさい"]
    return any(t in message for t in triggers)


async def _ensure_db_pool():
    """DB poolが初期化されていなければ初期化する"""
    try:
        from tools.db_pool import get_pool
        await get_pool()
        return True
    except Exception as e:
        logger.warning(f"DB pool未準備: {e}")
        return False


async def check_proactive_triggers(channel) -> str | None:
    """能動報告すべきかチェックし、報告テキストを返す"""
    if not proactive.can_report():
        return None

    try:
        if not await _ensure_db_pool():
            return None

        from tools.db_pool import get_connection
        parts = []

        async with get_connection() as conn:
            # 1. CRITICALエラー（直近10分）
            try:
                critical = await conn.fetchval(
                    """SELECT COUNT(*) FROM event_log
                       WHERE severity = 'critical'
                       AND created_at > NOW() - INTERVAL '10 minutes'"""
                )
                if critical and critical > 0:
                    parts.append(f"\U0001f534 **CRITICAL** 直近10分でCRITICALエラーが{critical}件発生中")
            except Exception as e:
                logger.debug(f"CRITICALチェック失敗: {e}")

            # 2. 承認バックログ（3件以上）
            try:
                approvals = await conn.fetchval(
                    "SELECT COUNT(*) FROM approval_queue WHERE status='pending'"
                )
                if approvals and approvals >= 3:
                    parts.append(f"\U0001f7e1 **承認待ち** {approvals}件溜まっています")
            except Exception as e:
                logger.debug(f"承認チェック失敗: {e}")

            # 3. ノード障害チェック
            try:
                down_nodes = await conn.fetch(
                    """SELECT node_name, state, changed_at FROM node_state
                       WHERE state IN ('down', 'error', 'unreachable')"""
                )
                if down_nodes:
                    names = ", ".join(r['node_name'] for r in down_nodes)
                    parts.append(f"\U0001f534 **ノード障害** {names} がダウン中")
            except Exception as e:
                logger.debug(f"ノード状態チェック失敗: {e}")

            # 4. 予算チェック（80%/90%）— 各レベル1日1回のみ
            try:
                import os
                daily_budget = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))
                daily_spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log WHERE recorded_at::date = CURRENT_DATE"
                )
                if daily_budget > 0 and daily_spent:
                    ratio = float(daily_spent) / daily_budget
                    if ratio >= 0.9:
                        key = "budget_proactive_90"
                        if proactive.can_emergency_alert(key, cooldown_minutes=1440):
                            parts.append(f"\U0001f534 **予算超過** 日次予算の{ratio*100:.0f}%消費 (\\{float(daily_spent):.0f}/\\{daily_budget:.0f})")
                            proactive.record_emergency_alert(key)
                    elif ratio >= 0.8:
                        key = "budget_proactive_80"
                        if proactive.can_emergency_alert(key, cooldown_minutes=1440):
                            parts.append(f"\U0001f7e1 **予算警告** 日次予算の{ratio*100:.0f}%消費 (\\{float(daily_spent):.0f}/\\{daily_budget:.0f})")
                            proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"予算チェック失敗: {e}")

            # 5. 承認待ちタスクの通知（2時間以上放置されているもの）
            try:
                pending_approvals = await conn.fetch(
                    """SELECT id, request_type, request_data, requested_at
                    FROM approval_queue WHERE status='pending'
                    AND requested_at < NOW() - INTERVAL '2 hours'
                    ORDER BY requested_at LIMIT 3"""
                )
                if pending_approvals:
                    key = "pending_approvals_reminder"
                    if proactive.can_emergency_alert(key, cooldown_minutes=360):  # 6時間に1回
                        import json as _json
                        approval_lines = []
                        for pa in pending_approvals:
                            data = pa["request_data"]
                            if isinstance(data, str):
                                try:
                                    data = _json.loads(data)
                                except Exception:
                                    pass
                            if pa["request_type"] == "product_publish":
                                title = data.get("title", "不明")[:50] if isinstance(data, dict) else "不明"
                                approval_lines.append(f"  #{pa['id']} 📝 note記事「{title}」")
                            else:
                                approval_lines.append(f"  #{pa['id']} {pa['request_type']}")
                        parts.append(
                            f"📋 **承認待ち {len(pending_approvals)}件**（2時間以上）\n"
                            + "\n".join(approval_lines)
                            + f"\n  → `!承認一覧` で詳細確認"
                        )
                        proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"承認待ちチェック失敗: {e}")

            # 6. タスクが1時間以上stuck
            try:
                stuck = await conn.fetchval(
                    """SELECT COUNT(*) FROM tasks
                       WHERE status = 'in_progress'
                       AND updated_at < NOW() - INTERVAL '1 hour'"""
                )
                if stuck and stuck > 0:
                    parts.append(f"\U0001f7e1 **タスク停滞** {stuck}件のタスクが1時間以上進捗なし")
            except Exception as e:
                logger.debug(f"タスク停滞チェック失敗: {e}")

            # 6. APIクオータ警告（80%以上消費）— 1日1回のみ通知
            try:
                key = "api_quota_80"
                if proactive.can_emergency_alert(key, cooldown_minutes=1440):  # 24時間
                    from tools.api_quota_monitor import get_quota_warnings
                    quota_warnings = await get_quota_warnings()
                    if quota_warnings:
                        parts.append("\U0001f7e1 **APIクオータ警告**\n  " + "\n  ".join(quota_warnings))
                        proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"APIクオータチェック失敗: {e}")

            # 7. 承認タイムアウト接近（72h期限に対して60h経過）
            try:
                timeout_approaching = await conn.fetchval(
                    """SELECT COUNT(*) FROM approval_queue
                       WHERE status = 'pending'
                       AND created_at < NOW() - INTERVAL '60 hours'"""
                )
                if timeout_approaching and timeout_approaching > 0:
                    parts.append(f"\U0001f7e1 **承認期限** {timeout_approaching}件が72時間タイムアウトに接近中")
            except Exception as e:
                logger.debug(f"承認タイムアウトチェック失敗: {e}")

            # 8. 高品質成果物完成（タイムリー、島原アクティブ時のみ）
            if proactive.is_daichi_active():
                try:
                    artifact = await conn.fetchrow(
                        """SELECT id, type, quality_score FROM tasks
                           WHERE status = 'completed' AND quality_score >= 0.80
                           AND created_at > NOW() - INTERVAL '1 hour'
                           ORDER BY created_at DESC LIMIT 1"""
                    )
                    if artifact:
                        parts.append(f"\U0001f535 **成果物** {artifact['type']}の成果物完成 (品質{artifact['quality_score']:.2f})")
                except Exception as e:
                    logger.debug(f"成果物チェック失敗: {e}")

        if not parts:
            return None

        proactive.record_report()
        header = "大知さん、状況報告です。"
        report = header + "\n" + "\n".join(parts)

        # alertチャンネルにもWebhook送信（CRITICALまたはノード障害を含む場合）
        if any("\U0001f534" in p for p in parts):
            try:
                from tools.discord_notify import notify_error
                await notify_error("proactive_alert", "\n".join(p for p in parts if "\U0001f534" in p), "error")
            except Exception as e:
                logger.debug(f"Webhook送信スキップ: {e}")

        return report

    except Exception as e:
        logger.warning(f"プロアクティブチェック失敗: {e}")
        return None


async def check_emergency_alerts() -> str | None:
    """緊急アラートチェック（2分間隔watchdog用）

    島原のアクティブ状態やサイレンスモードに関係なく発火する。
    同一アラートは5分間スロットルされる。
    """
    try:
        if not await _ensure_db_pool():
            return None

        from tools.db_pool import get_connection
        alerts = []

        async with get_connection() as conn:
            # 1. CRITICALエラー（直近5分）
            try:
                critical = await conn.fetchval(
                    """SELECT COUNT(*) FROM event_log
                       WHERE severity = 'critical'
                       AND created_at > NOW() - INTERVAL '5 minutes'"""
                )
                if critical and critical > 0:
                    key = "critical_errors"
                    if proactive.can_emergency_alert(key):
                        # 最新のCRITICALエラー詳細を取得
                        latest = await conn.fetchrow(
                            """SELECT event_type, category, source_node, payload
                               FROM event_log WHERE severity = 'critical'
                               ORDER BY created_at DESC LIMIT 1"""
                        )
                        detail = ""
                        if latest:
                            detail = f"\n  ノード: {latest['source_node'] or '不明'} / 種別: {latest['event_type']}"
                        alerts.append(f"\U0001f6a8 **緊急: CRITICALエラー** {critical}件検出{detail}")
                        proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"CRITICAL緊急チェック失敗: {e}")

            # 2. Emergency Kill発動チェック
            try:
                ek_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM event_log
                       WHERE event_type = 'emergency_kill'
                       AND created_at > NOW() - INTERVAL '5 minutes'"""
                )
                if ek_count and ek_count > 0:
                    key = "emergency_kill"
                    if proactive.can_emergency_alert(key):
                        alerts.append(f"\U0001f6a8 **緊急: Emergency Kill発動** 自動停止が{ek_count}件トリガーされました")
                        proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"Emergency Killチェック失敗: {e}")

            # 3. ノード完全無応答（node_stateがdown/error）
            try:
                down_nodes = await conn.fetch(
                    """SELECT node_name, state, changed_at FROM node_state
                       WHERE state IN ('down', 'error', 'unreachable')
                       AND changed_at > NOW() - INTERVAL '10 minutes'"""
                )
                if down_nodes:
                    for node in down_nodes:
                        key = f"node_down_{node['node_name']}"
                        if proactive.can_emergency_alert(key, cooldown_minutes=10):
                            alerts.append(
                                f"\U0001f6a8 **緊急: ノード障害** {node['node_name']} が {node['state']} 状態"
                            )
                            proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"ノード無応答チェック失敗: {e}")

            # 4. ノードメモリ/CPU高負荷（ハートビートデータ参照）
            try:
                heartbeats = await conn.fetch(
                    """SELECT DISTINCT ON (source_node) source_node, payload, created_at
                       FROM event_log
                       WHERE event_type LIKE 'agent.heartbeat.%%'
                       AND created_at > NOW() - INTERVAL '15 minutes'
                       ORDER BY source_node, created_at DESC"""
                )
                for hb in heartbeats:
                    import json as _json
                    try:
                        data = _json.loads(hb["payload"]) if isinstance(hb["payload"], str) else hb["payload"]
                    except Exception:
                        continue
                    node_name = hb["source_node"] or data.get("node", "unknown")
                    ram_pct = float(data.get("memory_percent", data.get("ram_pct", 0)))
                    cpu_pct = float(data.get("cpu_percent", data.get("cpu_pct", 0)))

                    if ram_pct > 85:
                        key = f"ram_high_{node_name}"
                        if proactive.can_emergency_alert(key, cooldown_minutes=15):
                            alerts.append(
                                f"\U0001f6a8 **メモリ高負荷: {node_name.upper()}** RAM使用率 {ram_pct:.0f}%"
                            )
                            proactive.record_emergency_alert(key)

                    if cpu_pct > 95:
                        key = f"cpu_high_{node_name}"
                        if proactive.can_emergency_alert(key, cooldown_minutes=15):
                            alerts.append(
                                f"\U0001f6a8 **CPU高負荷: {node_name.upper()}** CPU使用率 {cpu_pct:.0f}%"
                            )
                            proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"リソース監視チェック失敗: {e}")

            # 5. 予算90%超過（1日1回 + 閾値変化時のみ再通知）
            try:
                import os
                daily_budget = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "120")))
                daily_spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log WHERE recorded_at::date = CURRENT_DATE"
                )
                if daily_budget > 0 and daily_spent:
                    ratio = float(daily_spent) / daily_budget
                    if ratio >= 0.9:
                        # 閾値段階: 90%, 100%, 120% でそれぞれ1回だけ通知
                        if ratio >= 1.2:
                            key = "budget_120pct"
                        elif ratio >= 1.0:
                            key = "budget_100pct"
                        else:
                            key = "budget_90pct"
                        # 各閾値につき1日1回（1440分=24時間）
                        if proactive.can_emergency_alert(key, cooldown_minutes=1440):
                            severity = "緊急" if ratio >= 1.0 else "警告"
                            alerts.append(
                                f"\U0001f6a8 **{severity}: 予算{'超過' if ratio >= 1.0 else '警告'}** "
                                f"日次予算{ratio*100:.0f}%消費 (\\{float(daily_spent):.0f}/\\{daily_budget:.0f}円)"
                            )
                            proactive.record_emergency_alert(key)
            except Exception as e:
                logger.debug(f"予算緊急チェック失敗: {e}")

        if not alerts:
            return None

        alert_text = "\n".join(alerts)

        # alertチャンネルにもWebhook送信（全緊急アラートを送る）
        try:
            from tools.discord_notify import notify_error
            await notify_error("watchdog_emergency", alert_text, "critical")
        except Exception as e:
            logger.debug(f"Webhook緊急送信スキップ: {e}")

        return alert_text

    except Exception as e:
        logger.warning(f"緊急アラートチェック失敗: {e}")
        return None
