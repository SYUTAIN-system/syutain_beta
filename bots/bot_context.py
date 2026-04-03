"""対話コンテキスト管理 — 参照解決・セッション管理・日跨ぎ参照"""
import re, logging, asyncio
from datetime import datetime, timezone, timedelta
from collections import OrderedDict

logger = logging.getLogger("syutain.bot_context")


class ConversationContext:
    """対話セッション内の参照可能オブジェクトを管理"""

    def __init__(self):
        self.referenced_items: list[dict] = []  # 直近で言及されたオブジェクト
        self.last_single_item: dict | None = None  # 「それ」の参照先
        self.session_topic: str = ""  # 現在の対話トピック
        self.last_message_at: datetime = datetime.now(timezone.utc)

    def update_references(self, items: list[dict]):
        """新しいオブジェクトリストを登録"""
        self.referenced_items = items[:10]  # 最大10件
        if items:
            self.last_single_item = items[0]

    def set_single_reference(self, item: dict):
        """単一オブジェクトを参照先に設定"""
        self.last_single_item = item

    def resolve_reference(self, text: str) -> dict | None:
        """テキスト内の参照を解決"""
        text_lower = text.lower()

        # 「それ」「あれ」「これ」→ last_single_item
        if any(w in text_lower for w in ["それ", "あれ", "これ", "さっきの"]):
            return self.last_single_item

        # 「1番目」「最初のやつ」→ referenced_items[0]
        idx = self._extract_ordinal(text_lower)
        if idx is not None and 0 <= idx < len(self.referenced_items):
            return self.referenced_items[idx]

        return None

    def _extract_ordinal(self, text: str) -> int | None:
        """序数を抽出 (0-indexed)"""
        ordinals = {
            "1番": 0, "一番": 0, "最初": 0, "1つ目": 0,
            "2番": 1, "二番": 1, "2つ目": 1,
            "3番": 2, "三番": 2, "3つ目": 2,
            "4番": 3, "5番": 4,
        }
        for pattern, idx in ordinals.items():
            if pattern in text:
                return idx
        # 数字パターン
        match = re.search(r'(\d+)\s*(?:番目|つ目|個目)', text)
        if match:
            return int(match.group(1)) - 1
        return None

    def touch(self):
        """最終アクティブ時刻を更新"""
        self.last_message_at = datetime.now(timezone.utc)

    def is_expired(self, timeout_minutes: int = 5) -> bool:
        """セッションが期限切れかどうか"""
        return datetime.now(timezone.utc) - self.last_message_at > timedelta(minutes=timeout_minutes)


class SessionManager:
    """チャンネル別のセッション管理"""

    def __init__(self):
        self._sessions: OrderedDict[str, ConversationContext] = OrderedDict()
        self._max_sessions = 50

    def get_or_create(self, channel_id: str) -> ConversationContext:
        """セッションを取得。なければ新規作成"""
        if channel_id in self._sessions:
            ctx = self._sessions[channel_id]
            if ctx.is_expired():
                # 期限切れ→新セッション
                asyncio.ensure_future(self._on_session_end(channel_id, ctx))
                ctx = ConversationContext()
                self._sessions[channel_id] = ctx
            else:
                ctx.touch()
            return ctx

        # 新規セッション
        if len(self._sessions) >= self._max_sessions:
            # 最古のセッションを削除
            oldest_key = next(iter(self._sessions))
            del self._sessions[oldest_key]

        ctx = ConversationContext()
        self._sessions[channel_id] = ctx
        return ctx

    async def _on_session_end(self, channel_id: str, ctx: ConversationContext):
        """セッション終了時の処理"""
        try:
            from bots.bot_learning import extract_learnings_from_recent_chat, save_learnings_to_persona_memory
            learnings = await extract_learnings_from_recent_chat(hours=1)
            if learnings:
                await save_learnings_to_persona_memory(learnings)
                logger.info(f"セッション終了: {channel_id} — {len(learnings)}件の学び")
        except Exception as e:
            logger.warning(f"セッション終了処理失敗: {e}")

    def cleanup_expired(self):
        """期限切れセッションを一括クリーンアップ"""
        expired = [k for k, v in self._sessions.items() if v.is_expired()]
        for k in expired:
            ctx = self._sessions.pop(k)
            asyncio.ensure_future(self._on_session_end(k, ctx))


# グローバルインスタンス
session_manager = SessionManager()


async def get_previous_session_context(channel_id: str, lookback_hours: int = 48) -> str:
    """「昨日の話の続きだけど」への対応。
    discord_chat_historyから直近48時間の対話を検索し、
    現在の話題に関連するコンテキストを200文字以内の要約で返す。
    """
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT author, content, created_at FROM discord_chat_history
                   WHERE channel_id = $1
                   AND created_at > NOW() - $2 * INTERVAL '1 hour'
                   AND created_at < NOW() - INTERVAL '5 minutes'
                   ORDER BY created_at DESC LIMIT 30""",
                channel_id, lookback_hours,
            )

        if not rows:
            return ""

        # 直近セッション以外のメッセージをまとめる
        lines = []
        for r in reversed(rows):
            role = "大知さん" if r["author"] == "daichi" else "SYUTAINβ"
            lines.append(f"{role}: {r['content'][:60]}")

        # LLMで要約（コスト最小化）
        from tools.llm_router import choose_best_model_v6, call_llm
        sel = choose_best_model_v6(task_type="classification", quality="low", budget_sensitive=True)
        result = await call_llm(
            prompt=f"以下の過去の対話を100文字以内で要約してください。要約のみ出力。\n\n" + "\n".join(lines[-15:]),
            system_prompt="過去の対話の要約係。100文字以内で要約のみ出力。",
            model_selection=sel,
        )
        summary = result.get("text", "").strip()
        if summary:
            return f"【前回の対話の要約】{summary[:200]}"
    except Exception as e:
        logger.warning(f"前回セッション取得失敗: {e}")

    return ""


def detect_context_request(message: str) -> bool:
    """過去の対話参照が必要なメッセージかどうか"""
    triggers = ["昨日の", "前回の", "さっきの話", "続きだけど", "続きなんだけど",
                "前に言った", "あの時の", "この前の"]
    return any(t in message for t in triggers)
