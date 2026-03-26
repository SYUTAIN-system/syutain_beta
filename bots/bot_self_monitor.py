"""応答品質の自己モニタリング（内部利用のみ、島原には表示しない）"""
import logging
from datetime import datetime, timezone, timedelta
from collections import deque

logger = logging.getLogger("syutain.bot_self_monitor")


class ResponseQualityMonitor:
    """Botの応答が島原に受け入れられたかを追跡。

    シグナル:
    - 肯定: 話題継続、「ありがとう」、thumbs_up
    - 否定: 「違う」「嘘」「ユーモアか？」、thumbs_down、同じ質問再送
    - 無視: 応答に反応せず別の話題に移動

    重要: 「大知さんの満足度が低下しています」のような報告は絶対にしない。
    内部改善にのみ使う。
    """

    def __init__(self):
        self._recent_signals: deque = deque(maxlen=100)
        self._negative_patterns: list[str] = []

    def record_signal(self, signal_type: str, context: str = ""):
        """シグナルを記録"""
        self._recent_signals.append({
            "type": signal_type,  # positive / negative / ignored
            "context": context[:100],
            "at": datetime.now(timezone.utc).isoformat(),
        })

    def detect_negative_signal(self, message: str) -> str | None:
        """否定シグナルを検出"""
        negative_triggers = {
            "correction": ["違う", "嘘", "間違い", "間違って", "そうじゃない", "ユーモアか"],
            "repeat_question": ["もう一回", "だから", "聞いてる？", "答えになってない"],
            "frustration": ["使えない", "ダメだな", "全然", "話にならない"],
        }
        msg_lower = message.lower()
        for category, triggers in negative_triggers.items():
            for t in triggers:
                if t in msg_lower:
                    return category
        return None

    def detect_positive_signal(self, message: str) -> str | None:
        """肯定シグナルを検出"""
        positive_triggers = ["ありがとう", "おk", "ok", "了解", "いいね", "完璧", "さすが"]
        msg_lower = message.lower()
        for t in positive_triggers:
            if t in msg_lower:
                return "positive"
        return None

    def on_reaction(self, emoji: str) -> str:
        """リアクションからシグナルを判定"""
        if emoji in ("👍", "✅", "🙌"):
            return "positive"
        elif emoji in ("👎", "❌", "😤"):
            return "negative"
        return "neutral"

    async def save_negative_pattern(self, category: str, context: str):
        """否定パターンをpersona_memoryに蓄積"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # 重複チェック
                exists = await conn.fetchval(
                    "SELECT COUNT(*) FROM persona_memory WHERE content = $1",
                    context,
                )
                if exists == 0:
                    await conn.execute(
                        "INSERT INTO persona_memory (category, content, reasoning) VALUES ($1, $2, $3)",
                        "taboo", context, f"自己モニタリング: {category}",
                    )
                    logger.info(f"否定パターン蓄積: [{category}] {context[:50]}")
        except Exception as e:
            logger.warning(f"否定パターン保存失敗: {e}")

    def get_quality_summary(self) -> dict:
        """直近の品質サマリー（内部利用のみ）"""
        if not self._recent_signals:
            return {"total": 0, "positive": 0, "negative": 0, "rate": 0.0}

        total = len(self._recent_signals)
        positive = sum(1 for s in self._recent_signals if s["type"] == "positive")
        negative = sum(1 for s in self._recent_signals if s["type"] == "negative")
        rate = positive / max(total, 1)

        return {"total": total, "positive": positive, "negative": negative, "rate": round(rate, 2)}


# グローバルインスタンス
quality_monitor = ResponseQualityMonitor()
