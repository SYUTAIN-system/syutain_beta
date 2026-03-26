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
    - 前回の能動報告から5分以内に再報告しない
    - 「静かにして」「後で」で次のメッセージまで停止
    """

    def __init__(self):
        self._consecutive_reports = 0  # 連続報告カウント
        self._last_report_at: datetime | None = None
        self._silenced = False  # 「静かにして」で停止
        self._last_daichi_msg_at: datetime | None = None

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

        # 緊急は常に報告可能
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


async def check_proactive_triggers(channel) -> str | None:
    """能動報告すべきかチェックし、報告テキストを返す"""
    if not proactive.can_report():
        return None

    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # 1. CRITICALエラー（緊急）
            critical = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE severity = 'critical'
                   AND created_at > NOW() - INTERVAL '10 minutes'"""
            )
            if critical and critical > 0:
                proactive.record_report()
                return f"大知さん、直近10分でCRITICALエラーが{critical}件出ています。確認しますか？"

            # 2. 承認待ち（タイムリー）
            if proactive.is_daichi_active():
                approvals = await conn.fetchval(
                    "SELECT COUNT(*) FROM approval_queue WHERE status='pending'"
                )
                if approvals and approvals >= 3:
                    proactive.record_report()
                    return f"大知さん、承認待ちが{approvals}件溜まっています。"

            # 3. 高品質成果物完成（タイムリー）
            if proactive.is_daichi_active():
                artifact = await conn.fetchrow(
                    """SELECT id, type, quality_score FROM tasks
                       WHERE status = 'completed' AND quality_score >= 0.80
                       AND created_at > NOW() - INTERVAL '1 hour'
                       ORDER BY created_at DESC LIMIT 1"""
                )
                if artifact:
                    proactive.record_report()
                    return (f"大知さん、{artifact['type']}の成果物ができました。"
                            f"品質{artifact['quality_score']:.2f}です。確認しますか？")

    except Exception as e:
        logger.warning(f"プロアクティブチェック失敗: {e}")

    return None
