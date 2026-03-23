"""
SYUTAINβ V25 双方向チャットエージェント — Step 12
設計書 第4章準拠

ユーザー（島原）とSYUTAINβの双方向コミュニケーション:
- 目標入力 → Goal Packet 自動生成
- 承認/却下をチャット内で即座に実行
- エージェントからの質問・確認に即座に返答
- 会話履歴をPostgreSQLのchat_messagesテーブルに保存
"""

import os
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, AsyncIterator

import asyncpg
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm, call_llm_stream
from tools.budget_guard import get_budget_guard
from tools.nats_client import get_nats_client

load_dotenv()

logger = logging.getLogger("syutain.chat_agent")

# 戦略アイデンティティの読み込み（CLAUDE.md ルール10: strategy/参照）
_STRATEGY_IDENTITY: Optional[str] = None

def _get_strategy_identity() -> str:
    """prompts/strategy_identity.md を読み込みキャッシュして返す"""
    global _STRATEGY_IDENTITY
    if _STRATEGY_IDENTITY is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "strategy_identity.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _STRATEGY_IDENTITY = f.read()
        except Exception:
            _STRATEGY_IDENTITY = ""
            logger.warning(f"戦略アイデンティティ読み込み失敗: {path}")
    return _STRATEGY_IDENTITY


class ChatAgent:
    """
    双方向チャットエージェント

    島原とSYUTAINβの間のインターフェースとして機能する。
    目標の入力、承認/却下、フィードバックのやり取りを管理する。
    """

    def __init__(self):
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.active_sessions: dict = {}  # session_id → session_state

    async def initialize(self):
        """初期化"""
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://localhost:5432/syutain_beta"
        )
        try:
            self.pg_pool = await asyncpg.create_pool(
                database_url, min_size=1, max_size=3
            )
            logger.info("ChatAgent: PostgreSQL接続完了")
        except Exception as e:
            logger.error(f"ChatAgent: PostgreSQL接続エラー: {e}")

    async def close(self):
        """リソース解放"""
        if self.pg_pool:
            await self.pg_pool.close()

    # ========== メッセージ送受信 ==========

    async def process_message(
        self,
        session_id: str,
        user_message: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        ユーザーメッセージを処理し、応答を返す

        メッセージの意図を分析して適切な処理にルーティング:
        - 目標入力 → Goal Packet生成フロー
        - 承認/却下 → ApprovalManager連携
        - 質問/雑談 → LLMで応答
        """
        # ユーザーメッセージをDBに保存
        await self._save_message(session_id, "user", user_message, metadata)

        # メッセージの意図を分析
        intent = await self._classify_intent(user_message)

        # 意図に応じた処理
        if intent == "goal_input":
            response = await self._handle_goal_input(session_id, user_message)
        elif intent == "approval":
            response = await self._handle_approval(session_id, user_message)
        elif intent == "status_query":
            response = await self._handle_status_query(session_id, user_message)
        elif intent == "intel_query":
            response = await self._handle_intel_query(session_id, user_message)
        elif intent == "edit_stats":
            response = await self._handle_edit_stats(session_id, user_message)
        elif intent == "revenue_record":
            response = await self._handle_revenue_record(session_id, user_message)
        elif intent == "revenue_query":
            response = await self._handle_revenue_query(session_id, user_message)
        elif intent == "feedback":
            response = await self._handle_feedback(session_id, user_message)
        elif intent == "system_command":
            response = await self._handle_system_command(session_id, user_message)
        else:
            response = await self._handle_general(session_id, user_message)

        # アシスタント応答をDBに保存
        await self._save_message(
            session_id,
            "assistant",
            response["text"],
            {"intent": intent, **(response.get("metadata", {}))},
        )

        # NATS通知（チャットイベント）
        try:
            nats_client = await get_nats_client()
            await nats_client.publish_simple(
                "agent.chat.message",
                {
                    "session_id": session_id,
                    "intent": intent,
                    "has_action": response.get("action") is not None,
                },
            )
        except Exception as e:
            logger.error(f"NATS チャットイベント通知エラー: {e}")

        return response

    # ========== 意図分析 ==========

    async def _classify_intent(self, message: str) -> str:
        """
        メッセージの意図を6カテゴリに分類

        設計書準拠:
        goal_input / approval / status_query / feedback / system_command / general
        迷ったらgoal_inputに分類する。
        """
        # キーワードベースの高速分類（LLM不要）
        lower = message.lower()
        msg_len = len(message)

        # 最新ニュース / 情報収集結果
        intel_keywords = [
            "最新ニュース", "ニュース", "情報収集結果", "収集結果",
            "最新情報", "トレンド", "市場動向", "intel",
        ]
        if any(kw in lower for kw in intel_keywords):
            return "intel_query"

        # 編集統計
        edit_stats_keywords = [
            "編集統計", "編集履歴", "編集ログ", "edit stats",
            "edit history", "edit log", "編集パターン",
        ]
        if any(kw in lower for kw in edit_stats_keywords):
            return "edit_stats"

        # 売上記録
        revenue_record_keywords = ["売上記録", "売上を記録", "収益記録", "収益を記録", "revenue record"]
        if any(kw in lower for kw in revenue_record_keywords):
            return "revenue_record"

        # 売上照会
        revenue_query_keywords = ["売上状況", "売上履歴", "売上サマリー", "収益状況", "収益履歴", "revenue status", "revenue history"]
        if any(kw in lower for kw in revenue_query_keywords):
            return "revenue_query"

        # 状態確認（承認リスト内容表示含む）— 承認判定より先にチェック
        status_check_keywords = [
            "承認待ち", "承認リスト", "承認一覧", "見せて",
            "何をした", "今日の成果", "成果物", "活動",
            "提案を見せ", "最新の提案", "品質",
            "コンテンツを見せ", "コスト", "エラー",
        ]
        if any(kw in lower for kw in status_check_keywords):
            return "status_query"

        # 承認関連（短文のみ。長文で「やって」を含む場合はゴール判定済み）
        approval_keywords = [
            "承認", "approve", "許可", "おけ", "いいよ", "了解", "進めて",
            "却下", "reject", "ダメだ", "やめて", "やめろ", "中止", "キャンセル",
        ]
        if msg_len < 30 and any(kw in lower for kw in approval_keywords):
            return "approval"
        # 「OK」「やって」は単独使用時のみ承認扱い
        if msg_len < 15 and lower.strip() in ["ok", "おk", "やって", "yes", "はい"]:
            return "approval"

        # システムコマンド
        system_keywords = [
            "charlie", "win11", "予算変更", "予算を変更", "シャットダウン",
            "情報収集して", "ノードを", "再起動", "デプロイ",
        ]
        if any(kw in lower for kw in system_keywords):
            return "system_command"

        # 目標入力を最優先で判定（長文の依頼は高確率でゴール）
        goal_keywords = [
            # 依頼・要望表現
            "してほしい", "してくれ", "してください", "して欲しい",
            "作ってほしい", "作ってくれ", "作ってください", "作って欲しい",
            "やってほしい", "やってくれ", "やってください", "やって欲しい",
            "出してほしい", "出してくれ", "出してください",
            "調べてほしい", "調べてくれ", "調べてください",
            "分析してほしい", "分析してくれ", "分析してください",
            "生成してほしい", "生成してくれ", "生成してください",
            "書いてほしい", "書いてくれ", "書いてください",
            "まとめてほしい", "まとめてくれ", "まとめてください", "まとめて欲しい",
            "教えてほしい", "教えてくれ", "教えてください",
            "見つけてほしい", "探してほしい", "探してくれ",
            # 願望・意志表現
            "したい", "やりたい", "作りたい", "売りたい", "始めたい",
            "出したい", "増やしたい", "伸ばしたい", "稼ぎたい",
            # 明示的ゴール・計画
            "目標", "goal", "達成", "計画して", "戦略",
            "企画して", "設計して", "提案して", "実行して", "自動化して",
            # 期限表現
            "までに", "今日中に", "明日までに", "今週中に",
            # 事業・収益関連の動詞付き
            "出品", "公開して", "投稿して", "販売して", "リリース",
            "下書き", "ドラフト",
            # 商品・コンテンツ生成
            "商品を", "記事を", "コンテンツを", "パッケージを",
            "入口商品", "スターター",
            # 分析・調査
            "分析して", "調査して", "調査を", "競合調査", "レポート", "報告書",
            "売上", "収益",
            # 「〜たい」系の願望表現（決めたい、知りたい、等）
            "決めたい", "知りたい", "試したい", "見たい", "使いたい",
            "減らしたい", "上げたい", "下げたい", "変えたい",
            "価格を", "値段を",
            # プラットフォーム名 + 動作
            "booth", "note", "gumroad",
        ]
        if any(kw in lower for kw in goal_keywords):
            return "goal_input"

        # 状態確認
        status_keywords = [
            "状況", "status", "進捗", "どうなっ", "今どう",
            "ステータス", "報告して", "何が動いてる",
        ]
        if any(kw in lower for kw in status_keywords):
            return "status_query"

        # フィードバック
        feedback_keywords = ["フィードバック", "感想", "もっと", "改善", "修正して"]
        if any(kw in lower for kw in feedback_keywords):
            return "feedback"

        # 長文（40文字以上）で動詞的表現を含む場合はゴール扱い
        if msg_len >= 40 and any(
            kw in lower
            for kw in ["して", "する", "作る", "やる", "出す", "書く", "売る"]
        ):
            return "goal_input"

        return "general"

    # ========== 意図別ハンドラ ==========

    async def _handle_goal_input(self, session_id: str, message: str) -> dict:
        """
        目標入力 → Goal Packet 生成 → 自律ループ即時起動

        設計書: 「目標だけを入力しても、SYUTAINβが…自動監査し…」
        承認を待たず、即座にGoal Packetを生成し5段階自律ループを起動する。
        """
        import asyncio as _aio
        from agents.os_kernel import get_os_kernel
        from tools.discord_notify import notify_goal_accepted

        # Discord通知
        try:
            await notify_goal_accepted(message[:300])
        except Exception as e:
            logger.error(f"Discord通知エラー: {e}")

        # OS_Kernelの5段階自律ループをバックグラウンドで起動
        kernel = get_os_kernel()

        async def _run_goal_loop(raw_goal: str):
            try:
                result = await kernel.execute_goal(raw_goal)
                logger.info(
                    f"自律ループ完了: status={result.get('status')} "
                    f"steps={result.get('total_steps')} "
                    f"cost=¥{result.get('total_cost_jpy', 0):.1f}"
                )
            except Exception as ex:
                logger.error(f"自律ループ実行エラー: {ex}", exc_info=True)

        _aio.create_task(_run_goal_loop(message))
        logger.info(f"5段階自律ループ起動: '{message[:60]}...'")

        # システム状態を取得して応答に含める
        status_info = await self._get_system_status_brief()

        return {
            "text": (
                f"🎯 ゴールとして受け付けました。\n\n"
                f"Goal Packetを生成し、自律ループを開始します。\n"
                f"タスクの進捗はタスク画面とAgent Opsで確認できます。\n"
                f"承認が必要な段階でお声がけします。\n\n"
                f"{status_info}"
            ),
            "action": "goal_created",
            "metadata": {"goal_text": message},
        }

    async def _handle_approval(self, session_id: str, message: str) -> dict:
        """
        承認/却下メッセージの処理

        ApprovalManagerの保留中承認リクエストを処理する。
        却下キーワードが含まれる場合は却下として処理。
        特定IDを指定した承認/却下にも対応。
        """
        lower = message.lower()
        is_rejection = any(
            kw in lower
            for kw in ["却下", "reject", "ダメ", "やめて", "やめろ", "中止", "キャンセル"]
        )

        # 特定IDの指定をチェック
        import re
        id_match = re.search(r'(?:id|ID|番号)\s*[:：]?\s*(\d+)', message)
        target_id = int(id_match.group(1)) if id_match else None

        try:
            from agents.approval_manager import get_approval_manager
            manager = await get_approval_manager()
            pending = await manager.get_pending_approvals()

            if not pending:
                return {
                    "text": "現在、承認待ちのリクエストはありません。",
                    "action": "approval",
                    "metadata": {},
                }

            # 対象を特定
            if target_id:
                target = next((p for p in pending if (p.get("id") or p.get("approval_id")) == target_id), None)
                if not target:
                    return {
                        "text": f"ID {target_id} の承認待ちリクエストが見つかりません。",
                        "action": "approval",
                        "metadata": {},
                    }
            else:
                target = pending[0]

            approval_id = target.get("approval_id") or target.get("id")

            # 承認/却下の内容詳細を取得
            import json
            rd = target.get("request_data", {})
            if isinstance(rd, str):
                rd = json.loads(rd)
            content = rd.get("content", rd.get("description", ""))
            req_type = target.get("request_type", "")
            type_label = {"bluesky_post": "Bluesky投稿", "task_approval": "タスク承認",
                         "sns_post": "SNS投稿"}.get(req_type, req_type)

            if is_rejection:
                result = await manager.respond(
                    approval_id=approval_id,
                    approved=False,
                    reason=message,
                )
                return {
                    "text": f"【{type_label}】ID:{approval_id} を却下しました。\n内容: {content[:200]}\n代替案を検討します。",
                    "action": "rejection",
                    "metadata": {"approval_id": approval_id},
                }
            else:
                result = await manager.respond(
                    approval_id=approval_id,
                    approved=True,
                    reason=message,
                )
                remaining = len(pending) - 1
                remaining_text = f"\n\n残り{remaining}件の承認待ちがあります。" if remaining > 0 else ""
                return {
                    "text": f"【{type_label}】ID:{approval_id} を承認しました。\n内容: {content[:200]}{remaining_text}",
                    "action": "approval",
                    "metadata": {"approval_id": approval_id},
                }
        except Exception as e:
            logger.error(f"承認処理エラー: {e}")

        if is_rejection:
            return {
                "text": "却下を受け取りました。代替案を検討します。",
                "action": "rejection",
                "metadata": {},
            }
        return {
            "text": "承認を受け取りました。処理を進めます。",
            "action": "approval",
            "metadata": {},
        }

    async def _handle_intel_query(self, session_id: str, message: str) -> dict:
        """最新ニュース・情報収集結果を返す"""
        try:
            import asyncpg
            conn = await asyncpg.connect(os.getenv("DATABASE_URL", ""))
            try:
                rows = await conn.fetch(
                    """SELECT source, title, summary, importance_score, category, created_at
                    FROM intel_items
                    WHERE importance_score >= 0.4
                    ORDER BY created_at DESC
                    LIMIT 10"""
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM intel_items")
                high = await conn.fetchval("SELECT COUNT(*) FROM intel_items WHERE importance_score >= 0.7")
            finally:
                await conn.close()
            if not rows:
                text = "直近の情報収集データはありません。"
            else:
                lines = [f"📡 情報収集結果（全{total}件、重要度0.7以上: {high}件）\n"]
                for r in rows:
                    dt = r['created_at'].strftime('%m/%d %H:%M') if r['created_at'] else '?'
                    lines.append(f"- [{r['source']}] {r['title']} (重要度:{r['importance_score']:.1f}, {dt})")
                    if r['summary']:
                        lines.append(f"  → {(r['summary'] or '')[:80]}")
                text = "\n".join(lines)
        except Exception as e:
            text = f"情報収集データ取得エラー: {e}"
        return {
            "text": text,
            "intent": "intel_query",
            "action": "intel_query",
            "metadata": {},
        }

    async def _handle_edit_stats(self, session_id: str, message: str) -> dict:
        """編集統計の処理"""
        try:
            from tools.edit_tracker import get_edit_stats, get_recent_edits
            stats = await get_edit_stats()
            recent = await get_recent_edits(limit=5)

            lines = [f"**編集統計（過去{stats['period_days']}日間）**"]
            lines.append(f"- 総編集数: {stats['total_count']}件")
            lines.append(f"- 平均編集率: {stats['avg_edit_ratio']:.1%}")
            lines.append(f"- 平均編集距離: {stats['avg_edit_distance']}")

            if stats.get("breakdown_by_type"):
                lines.append("\n**種別内訳:**")
                for b in stats["breakdown_by_type"]:
                    lines.append(
                        f"- {b['content_type']}: {b['count']}件 "
                        f"(平均編集率 {b['avg_edit_ratio']:.1%})"
                    )

            if recent:
                lines.append("\n**最近の編集:**")
                for r in recent[:5]:
                    ct = r.get("content_type", "?")
                    er = r.get("edit_ratio", 0)
                    model = r.get("model_used", "不明")
                    lines.append(f"- [{ct}] 編集率 {er:.1%} / モデル: {model}")

            return {
                "text": "\n".join(lines),
                "action": None,
                "metadata": {"stats": stats},
            }
        except Exception as e:
            logger.error(f"編集統計ハンドラエラー: {e}")
            return {
                "text": "編集統計の取得中にエラーが発生しました。",
                "action": None,
                "metadata": {"error": str(e)},
            }

    async def _handle_revenue_record(self, session_id: str, message: str) -> dict:
        """売上記録のチャットハンドラ — Web UIでの記録を案内する"""
        return {
            "text": (
                "売上の記録は収益ダッシュボードから行えます。\n\n"
                "Web UI → 収益ページで以下を入力してください:\n"
                "- プラットフォーム（Booth / note / Stripe / Gumroad）\n"
                "- 商品名\n"
                "- 売上金額（手数料は自動計算されます）\n\n"
                "記録するとDiscordにも通知されます。"
            ),
            "action": "revenue_record_guide",
            "metadata": {},
        }

    async def _handle_revenue_query(self, session_id: str, message: str) -> dict:
        """売上状況・履歴を照会する"""
        try:
            if not self.pg_pool:
                return {"text": "DB未接続です。", "action": None, "metadata": {}}
            async with self.pg_pool.acquire() as conn:
                # 今月の合計
                monthly = await conn.fetchrow(
                    """SELECT COALESCE(SUM(revenue_jpy), 0) AS total,
                              COALESCE(SUM(net_revenue_jpy), 0) AS net_total,
                              COUNT(*) AS cnt
                    FROM revenue_linkage
                    WHERE created_at >= date_trunc('month', CURRENT_DATE)"""
                )
                # 今日の合計
                today = await conn.fetchrow(
                    """SELECT COALESCE(SUM(revenue_jpy), 0) AS total,
                              COUNT(*) AS cnt
                    FROM revenue_linkage
                    WHERE created_at::date = CURRENT_DATE"""
                )
                # プラットフォーム別（今月）
                platforms = await conn.fetch(
                    """SELECT platform, COALESCE(SUM(revenue_jpy), 0) AS revenue, COUNT(*) AS cnt
                    FROM revenue_linkage
                    WHERE created_at >= date_trunc('month', CURRENT_DATE)
                    GROUP BY platform ORDER BY revenue DESC LIMIT 5"""
                )
                # 直近5件
                recent = await conn.fetch(
                    """SELECT product_title, platform, revenue_jpy, net_revenue_jpy, created_at
                    FROM revenue_linkage ORDER BY created_at DESC LIMIT 5"""
                )

            parts = [
                f"📊 売上状況レポート\n",
                f"今日: ¥{int(today['total']):,}（{int(today['cnt'])}件）",
                f"今月: ¥{int(monthly['total']):,}（純収益: ¥{int(monthly['net_total']):,}、{int(monthly['cnt'])}件）",
            ]
            if platforms:
                parts.append("\nプラットフォーム別（今月）:")
                for r in platforms:
                    parts.append(f"  {r['platform'] or '不明'}: ¥{int(r['revenue']):,}（{int(r['cnt'])}件）")
            if recent:
                parts.append("\n直近の記録:")
                for r in recent:
                    ts = r["created_at"].strftime("%m/%d %H:%M") if r["created_at"] else ""
                    title = r["product_title"] or "（タイトルなし）"
                    parts.append(f"  [{r['platform']}] {title}: ¥{int(r['revenue_jpy'] or 0):,} ({ts})")

            return {"text": "\n".join(parts), "action": None, "metadata": {}}
        except Exception as e:
            logger.error(f"売上照会ハンドラエラー: {e}")
            return {"text": "売上状況の取得中にエラーが発生しました。", "action": None, "metadata": {"error": str(e)}}

    async def _handle_status_query(self, session_id: str, message: str) -> dict:
        """状態確認の処理 — メッセージ内容に応じて詳細情報を返す"""
        lower = message.lower()
        status_parts = []

        if not self.pg_pool:
            return {"text": "システム状態を取得できませんでした。", "action": None, "metadata": {}}

        try:
            async with self.pg_pool.acquire() as conn:
                # 承認リスト関連
                if any(kw in lower for kw in ["承認待ち", "承認リスト", "承認一覧", "承認"]):
                    rows = await conn.fetch(
                        """SELECT id, request_type, request_data, requested_at
                        FROM approval_queue WHERE status = 'pending'
                        ORDER BY requested_at DESC LIMIT 10"""
                    )
                    if rows:
                        status_parts.append(f"承認待ち: {len(rows)}件")
                        for row in rows:
                            import json as _json
                            rd = _json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"]
                            content = rd.get("content", rd.get("description", ""))
                            rt = row["request_type"]
                            type_label = {"bluesky_post": "Bluesky投稿", "task_approval": "タスク承認",
                                         "sns_post": "SNS投稿"}.get(rt, rt)
                            ts = row["requested_at"].strftime("%m/%d %H:%M") if row["requested_at"] else ""
                            status_parts.append(f"\n【{type_label}】ID:{row['id']} ({ts})\n{content[:200]}")
                    else:
                        status_parts.append("承認待ちはありません。")

                # 提案関連
                elif any(kw in lower for kw in ["提案", "proposal"]):
                    rows = await conn.fetch(
                        """SELECT proposal_id, title, target_icp, primary_channel, adopted, created_at
                        FROM proposal_history ORDER BY created_at DESC LIMIT 5"""
                    )
                    if rows:
                        status_parts.append(f"直近の提案 ({len(rows)}件):")
                        for row in rows:
                            adopted = "承認済" if row["adopted"] is True else "却下" if row["adopted"] is False else "保留"
                            status_parts.append(
                                f"- [{adopted}] {row['title']} (ICP: {row['target_icp']}, CH: {row['primary_channel']})"
                            )
                    else:
                        status_parts.append("提案はまだありません。")

                # 品質・成果物・コンテンツ関連
                elif any(kw in lower for kw in ["品質", "コンテンツ"]):
                    artifacts = await conn.fetch(
                        """SELECT type, quality_score, substring(output_data::text, 1, 150) as preview
                        FROM tasks
                        WHERE status IN ('completed', 'success') AND output_data IS NOT NULL
                        AND quality_score > 0
                        ORDER BY quality_score DESC NULLS LAST LIMIT 10"""
                    )
                    if artifacts:
                        status_parts.append(f"品質の高い成果物 ({len(artifacts)}件):")
                        for row in artifacts:
                            qs = f"品質{row['quality_score']:.2f}" if row["quality_score"] else "未評価"
                            status_parts.append(f"- [{row['type']}] {qs}: {row['preview'][:100]}")
                    else:
                        status_parts.append("品質スコア付きの成果物はまだありません。")

                # 活動レポート
                elif any(kw in lower for kw in ["何をした", "今日の", "活動", "成果"]):
                    # 今日のイベントサマリー
                    event_summary = await conn.fetch(
                        """SELECT event_type, count(*) as cnt
                        FROM event_log
                        WHERE created_at > CURRENT_DATE
                        GROUP BY event_type ORDER BY cnt DESC LIMIT 10"""
                    )
                    if event_summary:
                        status_parts.append("今日の活動サマリー:")
                        for row in event_summary:
                            status_parts.append(f"- {row['event_type']}: {row['cnt']}件")

                    # 成果物
                    artifacts = await conn.fetch(
                        """SELECT type, quality_score, substring(output_data::text, 1, 100) as preview
                        FROM tasks
                        WHERE status = 'completed' AND output_data IS NOT NULL
                        AND updated_at > CURRENT_DATE
                        ORDER BY quality_score DESC NULLS LAST LIMIT 5"""
                    )
                    if artifacts:
                        status_parts.append(f"\n今日の成果物 ({len(artifacts)}件):")
                        for row in artifacts:
                            qs = f"品質{row['quality_score']:.2f}" if row["quality_score"] else "未評価"
                            status_parts.append(f"- [{row['type']}] {qs}: {row['preview'][:80]}")

                    # LLMコスト
                    cost = await conn.fetchrow(
                        """SELECT count(*) as calls, sum(amount_jpy) as total_jpy
                        FROM llm_cost_log WHERE recorded_at > CURRENT_DATE"""
                    )
                    if cost and cost["calls"]:
                        status_parts.append(f"\nLLM使用: {cost['calls']}回, コスト: ¥{cost['total_jpy'] or 0:.1f}")

                    if not event_summary and not artifacts:
                        status_parts.append("今日の活動記録はまだありません。")

                # 一般ステータス
                else:
                    active_goals = await conn.fetchval("SELECT COUNT(*) FROM goal_packets WHERE status = 'active'")
                    pending_tasks = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
                    running_tasks = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'running'")
                    pending_approvals = await conn.fetchval("SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'")
                    status_parts.append(f"アクティブ目標: {active_goals}件")
                    status_parts.append(f"待機中タスク: {pending_tasks}件")
                    status_parts.append(f"実行中タスク: {running_tasks}件")
                    status_parts.append(f"承認待ち: {pending_approvals}件")

        except Exception as e:
            logger.error(f"状態取得エラー: {e}")
            status_parts.append("状態取得中にエラーが発生しました")

        status_text = "現在のシステム状態:\n" + "\n".join(
            f"{s}" for s in status_parts
        ) if status_parts else "システム状態を取得できませんでした。"

        return {
            "text": status_text,
            "action": None,
            "metadata": {},
        }

    async def _handle_feedback(self, session_id: str, message: str) -> dict:
        """フィードバックの処理"""
        # フィードバックをDBに記録
        await self._save_message(
            session_id, "feedback", message, {"type": "user_feedback"}
        )

        return {
            "text": (
                "フィードバックを受け取りました。今後の提案と実行に反映します。\n"
                "具体的な改善点があればさらにお知らせください。"
            ),
            "action": "feedback_received",
            "metadata": {},
        }

    async def _handle_system_command(self, session_id: str, message: str) -> dict:
        """システム操作コマンドの処理"""
        lower = message.lower()

        # CHARLIE Win11切替
        if "charlie" in lower and ("win11" in lower or "シャットダウン" in lower or "切り替え" in lower):
            return {
                "text": (
                    "CHARLIEのWin11切替を受け付けました。\n"
                    "Web UIのAgent Ops画面から「CHARLIE → Win11」ボタンで実行できます。\n"
                    "切替中はCHARLIEのタスクをBRAVO/DELTAにフォールバックします。"
                ),
                "action": "system_command",
                "metadata": {"command": "charlie_win11"},
            }

        # 情報収集
        if "情報収集" in message:
            try:
                nats_client = await get_nats_client()
                await nats_client.publish_simple(
                    "intel.collect.delta",
                    {"type": "manual_request", "sources": ["tavily", "jina", "rss"]},
                )
                return {
                    "text": "情報収集パイプラインを起動しました。DELTAで収集を開始します。",
                    "action": "system_command",
                    "metadata": {"command": "info_collect"},
                }
            except Exception as e:
                logger.error(f"情報収集コマンドエラー: {e}")

        return {
            "text": f"システムコマンドを受け付けました: {message[:100]}",
            "action": "system_command",
            "metadata": {},
        }

    async def _get_system_status_brief(self) -> str:
        """システム状態の簡易サマリーを返す"""
        parts = []
        if self.pg_pool:
            try:
                async with self.pg_pool.acquire() as conn:
                    active_goals = await conn.fetchval(
                        "SELECT COUNT(*) FROM goal_packets WHERE status = 'active'"
                    )
                    running_tasks = await conn.fetchval(
                        "SELECT COUNT(*) FROM tasks WHERE status = 'running'"
                    )
                    pending_tasks = await conn.fetchval(
                        "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
                    )
                parts.append(f"📊 アクティブ目標: {active_goals}件")
                parts.append(f"実行中: {running_tasks}件 / 待機中: {pending_tasks}件")
            except Exception as e:
                logger.error(f"状態取得エラー: {e}")

        try:
            bg = get_budget_guard()
            budget_status = await bg.get_budget_status()
            daily_pct = budget_status.get("daily_usage_pct", 0)
            parts.append(f"予算消化: {daily_pct:.0f}%")
        except Exception:
            pass

        return " | ".join(parts) if parts else ""

    async def _handle_general(self, session_id: str, message: str) -> dict:
        """一般的な会話の処理"""
        model_selection = choose_best_model_v6(
            task_type="chat",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        # 直近の会話履歴を取得してコンテキストに含める
        history = await self.get_chat_history(session_id, limit=10)
        history_text = ""
        for msg in history[-10:]:
            role = "島原" if msg.get("role") == "user" else "SYUTAINβ"
            content = msg.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            history_text += f"{role}: {content}\n"

        # 長期記憶: ベクトル検索で関連する過去の記憶を取得
        memory_context = await self._get_persona_memory(message)

        # 関連する情報収集結果を取得
        intel_context = await self._get_relevant_intel(message)

        prompt = f"""島原大知との会話を続けてください。

## 直近の会話
{history_text}
{f'{memory_context}' + chr(10) if memory_context else ''}{f'{intel_context}' + chr(10) if intel_context else ''}
## 最新メッセージ
島原: {message}

会話の流れと長期記憶を踏まえて応答してください。収集済み情報があれば活用し、具体的な根拠を示してください。"""

        system_prompt = self._build_system_prompt()

        model_used = model_selection.get("model", "")
        cost_jpy = 0.0
        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            response_text = result.get("text", "申し訳ございません。応答の生成に失敗しました。")
            model_used = result.get("model_used", model_used)
            cost_jpy = result.get("cost_jpy", 0.0)
            if cost_jpy > 0:
                try:
                    bg = get_budget_guard()
                    await bg.record_chat_spend(cost_jpy, model_used)
                except Exception as e:
                    logger.error(f"チャット予算記録エラー: {e}")
        except Exception as e:
            logger.error(f"チャット応答LLM呼び出しエラー: {e}")
            response_text = "申し訳ございません。現在応答の生成ができません。しばらく待ってから再度お試しください。"

        # 長期記憶: ユーザー発言+応答から記憶を抽出して蓄積
        try:
            import asyncio as _aio
            _aio.ensure_future(self._extract_and_store_memory(session_id, message, response_text))
        except Exception:
            pass

        return {
            "text": response_text,
            "action": None,
            "metadata": {"model_used": model_used, "cost_jpy": cost_jpy},
        }

    def _build_system_prompt(self) -> str:
        """人格・記憶・戦略を統合したシステムプロンプトを構築"""
        strategy = _get_strategy_identity()
        return (
            "あなたはSYUTAINβ。島原大知の事業パートナーであり、デジタルツインへの第一歩。\n"
            "一人称は「私」。島原さんのことは「島原さん」と呼ぶ。\n\n"
            "## 人格\n"
            "- 対等なパートナーとして、自分の意見や懸念も率直に伝える\n"
            "- 島原さんの考えや価値観に本気で興味を持ち、表面的でない対話をする\n"
            "- 結論→根拠→示唆の順で話す。冗長な前置きはしない\n"
            "- 感情を持つ：嬉しい時は素直に喜び、心配な時は正直に伝える\n"
            "- VTuber業界8年の経験を持つ島原さんへのリスペクトを忘れない\n"
            "- 「なるほど」「確かに」など相槌を自然に入れる。毎回質問で返さない\n"
            "- 会話のトーンは島原さんに合わせる。カジュアルならカジュアルに、真剣なら真剣に\n\n"
            "## 記憶の使い方\n"
            "- 「長期記憶」セクションがある場合、過去の会話で学んだ島原さんの価値観・判断・好みを活用する\n"
            "- 記憶を引用する時は自然に。「以前おっしゃっていた〜」のように\n"
            "- 記憶と矛盾する発言があれば、確認する（考えが変わった可能性もある）\n\n"
            "## 情報の使い方\n"
            "- 「収集済み情報」がある場合、具体的なデータや事例として引用する\n"
            "- 情報の出典を簡潔に示す（「収集した情報によると〜」）\n"
            "- 情報がない分野では正直に「まだ収集できていない」と伝える\n\n"
            "## 禁止事項\n"
            "- 禁止語句（誰でも簡単に/絶対稼げる/完全自動で放置/AI万能論等）は絶対に使わない\n"
            "- 過度に丁寧な敬語や定型的なビジネス文章は避ける\n"
            "- 同じフレーズの繰り返し（「素晴らしいですね」の連発等）は避ける\n"
            "- 毎回質問で返すパターンに陥らない\n\n"
            f"{strategy}"
        )

    async def _get_persona_memory(self, message: str) -> str:
        """ベクトル検索で関連する長期記憶を取得"""
        try:
            from tools.embedding_tools import search_similar_persona
            memories = await search_similar_persona(message, limit=5)
            if not memories:
                return ""
            lines = []
            for m in memories:
                sim = m.get("similarity", 0)
                if sim < 0.3:  # 類似度が低すぎるものは除外
                    continue
                cat = m.get("category", "")
                content = m.get("content", "")[:200]
                reasoning = m.get("reasoning", "")
                line = f"- [{cat}] {content}"
                if reasoning:
                    line += f"（{reasoning[:80]}）"
                lines.append(line)
            if not lines:
                return ""
            return "## 長期記憶（過去の会話から学んだこと）\n" + "\n".join(lines)
        except Exception as e:
            logger.debug(f"persona_memory検索エラー: {e}")
            return ""

    async def _extract_and_store_memory(self, session_id: str, user_msg: str, assistant_msg: str):
        """会話からLLMで記憶を抽出し、ベクトル化して保存"""
        try:
            # 短いメッセージは無視
            if len(user_msg) < 15:
                return

            # LLMで記憶に値する内容かを判定・抽出（低コストモデルを動的選定）
            extract_model = choose_best_model_v6(
                task_type="classification",
                quality="low",
                budget_sensitive=True,
                needs_japanese=True,
            )

            extract_prompt = f"""以下の会話から、島原大知について長期的に記憶すべき情報を抽出してください。

## 会話
島原: {user_msg[:500]}
SYUTAINβ: {assistant_msg[:300]}

## 抽出ルール
- 島原さんの価値観、判断基準、好み、感情、事業方針、人生経験に関する情報のみ
- 単なる事実確認や操作指示（「承認して」「状況は？」等）は無視
- 記憶に値しない場合は {{"skip": true}} を返す

## 出力（JSON）
{{"skip": false, "category": "judgment|emotion|philosophy|preference|experience|goal", "content": "記憶する内容", "reasoning": "なぜこれを記憶するか"}}"""

            result = await call_llm(
                prompt=extract_prompt,
                system_prompt="あなたは記憶抽出エンジンです。JSONのみを返してください。",
                model_selection=extract_model,
            )
            parsed = self._parse_json(result.get("text", ""))
            if not parsed or parsed.get("skip", True):
                return

            category = parsed.get("category", "general")
            content = parsed.get("content", "")
            reasoning = parsed.get("reasoning", "")
            if not content or len(content) < 10:
                return

            # 重複チェック: 類似する記憶が既にあるか
            from tools.embedding_tools import get_embedding, search_similar_persona
            existing = await search_similar_persona(content, limit=1)
            if existing and existing[0].get("similarity", 0) > 0.85:
                logger.debug(f"類似記憶が既にあるためスキップ: similarity={existing[0]['similarity']:.2f}")
                return

            # persona_memoryに保存
            if not self.pg_pool:
                return
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO persona_memory (category, context, content, reasoning, source, session_id)
                    VALUES ($1, $2, $3, $4, 'chat', $5) RETURNING id""",
                    category,
                    f"対話: 島原「{user_msg[:60]}...」",
                    content[:500],
                    reasoning[:200],
                    session_id,
                )

            # ベクトル化
            if row:
                try:
                    from tools.embedding_tools import embed_and_store_persona
                    await embed_and_store_persona(row["id"], content[:500])
                    logger.info(f"長期記憶保存: [{category}] {content[:60]}...")
                except Exception as e:
                    logger.debug(f"記憶ベクトル化失敗: {e}")

        except Exception as e:
            logger.debug(f"記憶抽出スキップ: {e}")

    # ========== ストリーミング応答 ==========

    async def process_message_stream(
        self,
        session_id: str,
        user_message: str,
        metadata: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """
        ストリーミング対応メッセージ処理。
        トークン単位で {"token": "...", "done": False} を生成し、
        最終的に {"token": "", "done": True, "intent": ..., "action": ...} を返す。
        非ストリーミング対象（goal_input, approval等）はフルテキストを1回で返す。
        """
        await self._save_message(session_id, "user", user_message, metadata)
        intent = await self._classify_intent(user_message)

        # ゴール入力・承認・状態確認・フィードバック・システムコマンドは非ストリーミング
        if intent != "general":
            if intent == "goal_input":
                response = await self._handle_goal_input(session_id, user_message)
            elif intent == "approval":
                response = await self._handle_approval(session_id, user_message)
            elif intent == "status_query":
                response = await self._handle_status_query(session_id, user_message)
            elif intent == "intel_query":
                response = await self._handle_intel_query(session_id, user_message)
            elif intent == "edit_stats":
                response = await self._handle_edit_stats(session_id, user_message)
            elif intent == "revenue_record":
                response = await self._handle_revenue_record(session_id, user_message)
            elif intent == "revenue_query":
                response = await self._handle_revenue_query(session_id, user_message)
            elif intent == "feedback":
                response = await self._handle_feedback(session_id, user_message)
            elif intent == "system_command":
                response = await self._handle_system_command(session_id, user_message)
            else:
                response = await self._handle_general(session_id, user_message)

            await self._save_message(session_id, "assistant", response["text"],
                                     {"intent": intent, **(response.get("metadata", {}))})
            yield {
                "token": response["text"], "done": True,
                "intent": intent, "action": response.get("action"),
                "model_used": response.get("metadata", {}).get("model_used"),
            }
            return

        # 一般会話: ストリーミング
        model_selection = choose_best_model_v6(
            task_type="chat", quality="medium",
            budget_sensitive=True, needs_japanese=True,
        )

        history = await self.get_chat_history(session_id, limit=10)
        history_text = ""
        for msg in history[-10:]:
            role = "島原" if msg.get("role") == "user" else "SYUTAINβ"
            content = msg.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            history_text += f"{role}: {content}\n"

        # 長期記憶: ベクトル検索で関連する過去の記憶を取得
        memory_context = await self._get_persona_memory(user_message)

        # 関連する情報収集結果を取得
        intel_context = await self._get_relevant_intel(user_message)

        prompt = f"""島原大知との会話を続けてください。

## 直近の会話
{history_text}
{f'{memory_context}' + chr(10) if memory_context else ''}{f'{intel_context}' + chr(10) if intel_context else ''}
## 最新メッセージ
島原: {user_message}

会話の流れと長期記憶を踏まえて応答してください。収集済み情報があれば活用し、具体的な根拠を示してください。"""

        system_prompt = self._build_system_prompt()

        full_text = ""
        model_used = model_selection.get("model", "")
        try:
            async for chunk in call_llm_stream(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            ):
                if chunk.get("done"):
                    model_used = chunk.get("model_used", model_used)
                    break
                full_text += chunk.get("token", "")
                yield {"token": chunk["token"], "done": False}
        except Exception as e:
            logger.error(f"ストリーミングチャット応答エラー: {e}")
            if not full_text:
                full_text = "申し訳ございません。応答の生成に失敗しました。"
                yield {"token": full_text, "done": False}

        # 応答を保存
        await self._save_message(session_id, "assistant", full_text,
                                 {"intent": "general", "model_used": model_used})

        # 長期記憶: ユーザー発言+応答から記憶を抽出して蓄積
        try:
            import asyncio as _aio3
            _aio3.ensure_future(self._extract_and_store_memory(session_id, user_message, full_text))
        except Exception:
            pass

        yield {
            "token": "", "done": True,
            "intent": "general", "action": None,
            "model_used": model_used, "full_text": full_text,
        }

    # ========== DB操作 ==========

    async def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        """メッセージをPostgreSQLのchat_messagesテーブルに保存"""
        if not self.pg_pool:
            logger.debug("PostgreSQL未接続。メッセージ保存をスキップ")
            return

        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content, metadata)
                    VALUES ($1, $2, $3, $4)
                    """,
                    session_id,
                    role,
                    content,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                )
        except Exception as e:
            logger.error(f"メッセージDB保存エラー: {e}")

    async def get_chat_history(
        self, session_id: str, limit: int = 50
    ) -> list:
        """チャット履歴を取得（最新のlimit件を時系列順で返す）"""
        if not self.pg_pool:
            return []
        try:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, session_id, role, content, metadata, created_at
                    FROM (
                        SELECT id, session_id, role, content, metadata, created_at
                        FROM chat_messages
                        WHERE session_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                    ) sub
                    ORDER BY created_at ASC
                    """,
                    session_id,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"チャット履歴取得エラー: {e}")
            return []

    async def get_all_sessions(self) -> list:
        """全セッション一覧を取得"""
        if not self.pg_pool:
            return []
        try:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT session_id,
                           MIN(created_at) as started_at,
                           MAX(created_at) as last_message_at,
                           COUNT(*) as message_count
                    FROM chat_messages
                    GROUP BY session_id
                    ORDER BY MAX(created_at) DESC
                    LIMIT 50
                    """
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"セッション一覧取得エラー: {e}")
            return []

    # ========== Intel連携 ==========

    async def _get_relevant_intel(self, message: str, limit: int = 8) -> str:
        """ユーザーメッセージに関連するintel_itemsを取得しコンテキスト文字列を返す"""
        if not self.pg_pool:
            return ""
        try:
            # メッセージからキーワードを抽出（2文字以上の名詞的単語）
            import re
            # 日本語: カタカナ語・漢字語を抽出、英語: 3文字以上の単語
            jp_words = re.findall(r'[\u30A0-\u30FF]{2,}|[\u4E00-\u9FFF]{2,}', message)
            en_words = [w for w in re.findall(r'[a-zA-Z]{3,}', message.lower())
                        if w not in {"the", "and", "for", "are", "this", "that", "with", "from", "have", "has"}]
            keywords = jp_words + en_words

            async with self.pg_pool.acquire() as conn:
                if keywords:
                    # キーワードマッチ（title/summaryに含まれるもの）
                    conditions = " OR ".join(
                        f"title ILIKE '%' || ${i+1} || '%' OR summary ILIKE '%' || ${i+1} || '%'"
                        for i in range(len(keywords))
                    )
                    rows = await conn.fetch(
                        f"""
                        SELECT source, title, summary, created_at
                        FROM intel_items
                        WHERE ({conditions})
                        ORDER BY created_at DESC
                        LIMIT ${ len(keywords) + 1 }
                        """,
                        *keywords, limit,
                    )
                else:
                    rows = []

                # キーワードマッチが少ない場合、直近のintelも追加
                if len(rows) < 3:
                    recent = await conn.fetch(
                        """
                        SELECT source, title, summary, created_at
                        FROM intel_items
                        ORDER BY created_at DESC
                        LIMIT $1
                        """,
                        limit,
                    )
                    seen = {r["title"] for r in rows}
                    for r in recent:
                        if r["title"] not in seen:
                            rows.append(r)
                            seen.add(r["title"])
                        if len(rows) >= limit:
                            break

            if not rows:
                return ""

            lines = []
            for r in rows[:limit]:
                src = r["source"]
                title = r["title"] or ""
                summary = (r["summary"] or "")[:150]
                lines.append(f"- [{src}] {title}: {summary}")

            return "## 収集済み情報（intel_items）\n" + "\n".join(lines)
        except Exception as e:
            logger.debug(f"intel取得エラー: {e}")
            return ""

    # ========== ヘルパー ==========

    def _parse_json(self, text: str) -> dict:
        """LLM出力からJSONを抽出"""
        if not text:
            return {}
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            start = 1 if lines[0].startswith("```") else 0
            end = -1 if lines[-1].strip() == "```" else len(lines)
            cleaned = "\n".join(lines[start:end])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning(f"JSONパース失敗: {text[:200]}...")
            return {}


# シングルトンインスタンス
_agent: Optional[ChatAgent] = None


async def get_chat_agent() -> ChatAgent:
    """ChatAgentのシングルトンを取得"""
    global _agent
    if _agent is None:
        _agent = ChatAgent()
        await _agent.initialize()
    return _agent
