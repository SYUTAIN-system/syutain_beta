"""
SYUTAINβ V25 3層提案エンジン — Step 10
設計書 第9章準拠

Layer 1: 提案生成（Revenue Scoring付き）
Layer 2: 反論生成（リスク・中止条件・失敗条件）
Layer 3: 代替案生成（次善策・低リスク案・スモールスタート案）

週次定例: 「今週やるべき3手」+「今週やめるべき1手」を自律提案
"""

import os
import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client
from tools.db_pool import get_pool as _db_get_pool

load_dotenv()

logger = logging.getLogger("syutain.proposal_engine")

# ===== Revenue Scoring 評価軸（設計書 9.4 準拠）=====
REVENUE_SCORING_CRITERIA = {
    "icp_fit": {"max": 25, "label": "ICP適合性"},
    "channel_fit": {"max": 15, "label": "チャネル適合性"},
    "content_reuse": {"max": 15, "label": "再利用性"},
    "speed_to_cash": {"max": 15, "label": "収益到達速度"},
    "gross_margin": {"max": 10, "label": "粗利"},
    "trust_building": {"max": 10, "label": "信頼構築"},
    "continuity_value": {"max": 10, "label": "継続性"},
}
# 合計100点。70点未満は「参考案」として自動優先提案には上げない

# 自動提案の閾値
AUTO_PROPOSAL_THRESHOLD = 70


def _load_strategy_file(filename: str) -> str:
    """strategy/ ディレクトリから戦略ファイルを読み込む"""
    strategy_dir = Path(__file__).resolve().parent.parent / "strategy"
    filepath = strategy_dir / filename
    try:
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        logger.warning(f"戦略ファイルが見つかりません: {filepath}")
        return ""
    except Exception as e:
        logger.error(f"戦略ファイル読み込みエラー ({filename}): {e}")
        return ""


def _load_all_strategies() -> dict:
    """全戦略ファイルを読み込み"""
    return {
        "icp_definition": _load_strategy_file("ICP_DEFINITION.md"),
        "channel_strategy": _load_strategy_file("CHANNEL_STRATEGY.md"),
        "content_strategy": _load_strategy_file("CONTENT_STRATEGY.md"),
    }


async def _get_pg_pool() -> Optional[asyncpg.Pool]:
    """PostgreSQL接続プールを取得（グローバルdb_poolを再利用）"""
    try:
        return await _db_get_pool()
    except Exception as e:
        logger.error(f"PostgreSQL接続エラー: {e}")
        return None


class ProposalEngine:
    """3層提案エンジン（設計書 第9章準拠）"""

    def __init__(self):
        self.strategies = _load_all_strategies()
        self.pg_pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """エンジン初期化"""
        self.pg_pool = await _get_pg_pool()
        if self.pg_pool:
            logger.info("ProposalEngine: PostgreSQL接続完了")
        else:
            logger.warning("ProposalEngine: PostgreSQL未接続（提案はメモリ保持のみ）")

    async def close(self):
        """リソース解放（プールはグローバル共有のため閉じない）"""
        self.pg_pool = None

    async def _record_trace(self, action: str = "", reasoning: str = "",
                           confidence: float = None, context: dict = None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            if not self.pg_pool:
                self.pg_pool = await _get_pg_pool()
            if self.pg_pool:
                async with self.pg_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO agent_reasoning_trace
                           (agent_name, action, reasoning, confidence, context)
                           VALUES ($1, $2, $3, $4, $5)""",
                        "proposal_engine", action, reasoning,
                        confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                    )
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    async def _get_recent_intel(self, limit: int = 10) -> str:
        """直近のintel_items（importance上位）を提案コンテキスト用テキストに変換"""
        try:
            if not self.pg_pool:
                self.pg_pool = await _get_pg_pool()
            if not self.pg_pool:
                return "（情報収集データ取得不可）"
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, source, title, summary, importance_score, category
                    FROM intel_items
                    WHERE created_at > NOW() - INTERVAL '48 hours'
                    AND importance_score >= 0.4
                    ORDER BY importance_score DESC
                    LIMIT $1""", limit
                )
                if not rows:
                    return "（直近48時間の情報収集データなし）"
                lines = []
                used_ids = []
                for r in rows:
                    lines.append(f"- [{r['source']}] {r['title']} (重要度:{r['importance_score']:.1f}, カテゴリ:{r['category']})")
                    if r['summary']:
                        lines.append(f"  要約: {r['summary'][:100]}")
                    used_ids.append(r['id'])
                # 提案に使用したintelをprocessed=trueに更新
                if used_ids:
                    await conn.execute(
                        "UPDATE intel_items SET processed = true WHERE id = ANY($1::int[])",
                        used_ids,
                    )
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"intel_items取得失敗: {e}")
            return "（情報収集データ取得エラー）"

    # ========== Layer 1: 提案生成 ==========

    async def generate_proposal(
        self,
        context: str,
        objective: str = "revenue",
        target_icp: str = "hot_icp",
        primary_channel: str = "note",
    ) -> dict:
        """
        Layer 1: 提案を生成し、Revenue Scoringで評価する

        Args:
            context: 現在の状況・データ（直近の反応、収益状況など）
            objective: 目的（revenue / trust / growth）
            target_icp: 対象ICP
            primary_channel: 主チャネル
        """
        proposal_id = str(uuid.uuid4())

        # LLMモデル選択（設計書ルール5: choose_best_model_v6必須）
        model_selection = choose_best_model_v6(
            task_type="proposal",
            quality="high",
            budget_sensitive=True,
            needs_japanese=True,
        )

        # 戦略コンテキストを構築
        strategy_context = self._build_strategy_context()

        # 直近の情報収集結果を注入（設計書 第11章: intel_items → 提案根拠）
        intel_context = await self._get_recent_intel()

        # 過去の却下パターンを取得して注入
        past_proposals_context = ""
        try:
            if self.pg_pool:
                async with self.pg_pool.acquire() as conn:
                    rejected = await conn.fetch(
                        """SELECT ph.title, pf.rejection_reason
                        FROM proposal_history ph
                        LEFT JOIN proposal_feedback pf ON ph.proposal_id = pf.proposal_id
                        WHERE ph.adopted = false
                        ORDER BY ph.created_at DESC LIMIT 5"""
                    )
                    if rejected:
                        past_proposals_context = "\n## 過去に却下された提案（同じ方向性を避けること）\n"
                        for r in rejected:
                            reason = f" 理由: {r['rejection_reason']}" if r.get('rejection_reason') else ""
                            past_proposals_context += f"- ❌ {r['title']}{reason}\n"
                        past_proposals_context += "\n上記と同じテーマ・構造の提案は却下される。却下理由を踏まえ、全く異なる切り口で提案すること。\n"
        except Exception:
            pass

        # persona_memoryからDAICHIの判断傾向+tabooを取得（接続#17修正+V27 taboo参照）
        persona_context = ""
        try:
            if self.pg_pool:
                async with self.pg_pool.acquire() as conn:
                    persona_rows = await conn.fetch(
                        """SELECT content FROM persona_memory
                        WHERE category = 'approval_pattern'
                        ORDER BY created_at DESC LIMIT 5"""
                    )
                    if persona_rows:
                        persona_context = "\n## DAICHIの判断傾向（過去の承認/却下パターン）\n"
                        for r in persona_rows:
                            persona_context += f"- {r['content'][:120]}\n"
                    # CLAUDE.md ルール26: tabooカテゴリは絶対に違反しない
                    taboo_rows = await conn.fetch(
                        """SELECT content FROM persona_memory
                        WHERE category = 'taboo'
                        ORDER BY created_at DESC LIMIT 15"""
                    )
                    if taboo_rows:
                        persona_context += "\n## 絶対禁止事項（taboo — これに違反する提案は生成禁止）\n"
                        for r in taboo_rows:
                            persona_context += f"- {r['content'][:100]}\n"
        except Exception:
            pass

        prompt = f"""あなたはSYUTAINβの提案エンジンです。以下の戦略と現在の状況に基づいて、収益提案を生成してください。

## 戦略コンテキスト
{strategy_context}

## 直近の情報収集（市場動向・トレンド）
{intel_context}
{persona_context}
## 現在の状況
{context}
{past_proposals_context}
## 提案要件
- 目的: {objective}
- 対象ICP: {target_icp}
- 主チャネル: {primary_channel}

## 絶対に守るルール
1. 「島原が今日取れる具体的な1アクション」を必ず含めること（例: 「noteに2000文字の記事を1本書く」「Boothに¥980の商品を1つ出品する」）
2. 過去に却下された提案と同じテーマ・構造は禁止
3. 所要時間と想定コストを具体的に書くこと
4. 「連載」「シリーズ」より「単発で完結する1本」を優先

以下のJSON形式で提案を出力してください:
{{
  "title": "提案タイトル",
  "first_action": "島原が今日取るべき具体的な1アクション（30分以内で完了できるもの）",
  "why_now": ["理由1（データ付き）", "理由2", "理由3"],
  "expected_outcome": {{
    "revenue_estimate_jpy": 数値,
    "timeline": "期間",
    "confidence": 0.0-1.0
  }},
  "required_human_actions": ["作業1（所要時間付き）"],
  "auto_actions_allowed": ["自動実行可能なアクション"],
  "scoring": {{
    "icp_fit": 0-25,
    "channel_fit": 0-15,
    "content_reuse": 0-15,
    "speed_to_cash": 0-15,
    "gross_margin": 0-10,
    "trust_building": 0-10,
    "continuity_value": 0-10
  }}
}}"""

        # 戦略アイデンティティを読み込み
        strategy_id_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "strategy_identity.md")
        strategy_id = ""
        try:
            with open(strategy_id_path, "r", encoding="utf-8") as f:
                strategy_id = f.read()
        except Exception:
            pass

        # アンチAI文体ガイド
        anti_ai = ""
        try:
            anti_ai_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "anti_ai_writing.md")
            if os.path.exists(anti_ai_path):
                with open(anti_ai_path, "r") as f:
                    anti_ai = f.read()
        except Exception:
            pass

        # エージェントコンテキスト注入（最新インテリジェンス + 島原の指摘）
        agent_intel = ""
        try:
            from tools.agent_context import build_agent_context
            agent_intel = await build_agent_context("proposal_engine")
        except Exception:
            pass

        intel_section = f"{agent_intel}\n\n" if agent_intel else ""
        system_prompt = (
            "SYUTAINβの収益提案エンジン。島原大知の事業を最大化する提案を生成する。\n\n"
            f"{strategy_id}\n\n"
            f"{anti_ai[:1500]}\n\n"
            f"{intel_section}"
            "上記の戦略と文体ガイドに基づき、ICP・チャネル・禁止語句を厳守して提案すること。"
            "必ず有効なJSONのみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            proposal_data = self._parse_llm_json(result.get("text", ""))
        except Exception as e:
            logger.error(f"提案生成LLM呼び出しエラー: {e}")
            proposal_data = self._fallback_proposal(context, objective)

        # Revenue Score を計算
        scoring = proposal_data.get("scoring", {})
        total_score = sum(scoring.values())
        is_auto_recommendable = total_score >= AUTO_PROPOSAL_THRESHOLD

        proposal = {
            "proposal_id": proposal_id,
            "title": proposal_data.get("title", "無題の提案"),
            "first_action": proposal_data.get("first_action", ""),
            "objective": objective,
            "target_icp": target_icp,
            "primary_channel": primary_channel,
            "why_now": proposal_data.get("why_now", []),
            "expected_outcome": proposal_data.get("expected_outcome", {}),
            "required_human_actions": proposal_data.get("required_human_actions", []),
            "auto_actions_allowed": proposal_data.get("auto_actions_allowed", []),
            "scoring": scoring,
            "total_score": total_score,
            "is_auto_recommendable": is_auto_recommendable,
            "intel_items_used": len(intel_context.split("\n")) if intel_context and intel_context != "（直近48時間の情報収集データなし）" else 0,
            "status": "proposed",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # 意思決定トレース: 提案生成の根拠を記録
        try:
            from tools.event_logger import log_event
            await log_event("proposal.reasoning", "proposal", {
                "proposal_id": proposal_id,
                "title": proposal_data.get("title", ""),
                "intel_context_length": len(intel_context),
                "target_icp": target_icp,
                "channel_selected": primary_channel,
                "total_score": total_score,
                "is_auto_recommendable": is_auto_recommendable,
                "model_used": model_selection.get("model", "unknown"),
            })
        except Exception:
            pass

        # agent_reasoning_traceに判断根拠を記録
        await self._record_trace(
            action="proposal_generation",
            reasoning=f"提案「{proposal_data.get('title', '')}」を生成。スコア={total_score}, 自動推奨={'Yes' if is_auto_recommendable else 'No'}",
            confidence=min(total_score / 100.0, 1.0),
            context={
                "proposal_id": proposal_id,
                "target_icp": target_icp,
                "primary_channel": primary_channel,
                "intel_items_used": len(intel_context.split("\n")) if intel_context else 0,
                "persona_memory_used": bool(persona_context),
                "theme_selection_reason": f"目的={objective}, ICP={target_icp}, チャネル={primary_channel}",
                "model_used": model_selection.get("model", "unknown"),
                "total_score": total_score,
            },
        )

        return proposal

    # ========== Layer 2: 反論生成 ==========

    async def generate_counter(self, proposal: dict) -> dict:
        """
        Layer 2: 提案に対する反論を生成

        リスク・やらない方がいい理由・失敗条件を明示する
        """
        model_selection = choose_best_model_v6(
            task_type="analysis",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        prompt = f"""あなたはSYUTAINβの反論エンジンです。以下の提案に対する建設的な反論を生成してください。

## 提案
タイトル: {proposal.get('title')}
理由: {json.dumps(proposal.get('why_now', []), ensure_ascii=False)}
期待成果: {json.dumps(proposal.get('expected_outcome', {}), ensure_ascii=False)}
スコア: {proposal.get('total_score', 0)}点

以下のJSON形式で反論を出力してください:
{{
  "risks": ["リスク1", "リスク2"],
  "dont_do_if": ["やらない方がいい条件1", "条件2"],
  "failure_conditions": ["失敗する条件1", "条件2"],
  "opportunity_cost": "この提案に時間を使うことで失う機会"
}}"""

        system_prompt = (
            "SYUTAINβの反論エンジン。提案のリスクと弱点を正直に指摘する。"
            "必ず有効なJSONのみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            counter_data = self._parse_llm_json(result.get("text", ""))
        except Exception as e:
            logger.error(f"反論生成LLM呼び出しエラー: {e}")
            counter_data = {
                "risks": ["LLM呼び出し失敗のため反論を生成できませんでした"],
                "dont_do_if": [],
                "failure_conditions": [],
                "opportunity_cost": "不明",
            }

        return counter_data

    # ========== Layer 3: 代替案生成 ==========

    async def generate_alternatives(self, proposal: dict, counter: dict) -> list:
        """
        Layer 3: 代替案を生成

        提案が却下された場合の次善策・低リスク案・スモールスタート案
        """
        model_selection = choose_best_model_v6(
            task_type="proposal",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        prompt = f"""あなたはSYUTAINβの代替案エンジンです。提案と反論を踏まえた代替案を3つ生成してください。

## 元提案
タイトル: {proposal.get('title')}
スコア: {proposal.get('total_score', 0)}点

## 反論内容
リスク: {json.dumps(counter.get('risks', []), ensure_ascii=False)}
失敗条件: {json.dumps(counter.get('failure_conditions', []), ensure_ascii=False)}

以下のJSON形式で代替案を出力してください:
[
  {{
    "title": "代替案タイトル",
    "effort": "low|medium|high",
    "revenue_estimate_jpy": 数値,
    "trust_building": "low|medium|high",
    "description": "概要"
  }}
]"""

        system_prompt = (
            "SYUTAINβの代替案エンジン。リスクを避けつつ成果を出す別解を提案する。"
            "必ず有効なJSON配列のみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            alternatives = self._parse_llm_json(result.get("text", ""))
            if not isinstance(alternatives, list):
                alternatives = [alternatives] if alternatives else []
        except Exception as e:
            logger.error(f"代替案生成LLM呼び出しエラー: {e}")
            alternatives = [
                {
                    "title": "既存コンテンツのリライト",
                    "effort": "low",
                    "revenue_estimate_jpy": 0,
                    "trust_building": "medium",
                    "description": "LLMエラーのためフォールバック代替案",
                }
            ]

        return alternatives

    # ========== 3層統合パイプライン ==========

    async def run_three_layer_pipeline(
        self,
        context: str,
        objective: str = "revenue",
        target_icp: str = "hot_icp",
        primary_channel: str = "note",
    ) -> dict:
        """
        3層提案パイプラインを一括実行

        Layer 1 → Layer 2 → Layer 3 の順に実行し、
        結果をPostgreSQLに保存してNATSで通知する
        """
        # Layer 1: 提案生成
        proposal = await self.generate_proposal(
            context=context,
            objective=objective,
            target_icp=target_icp,
            primary_channel=primary_channel,
        )

        # Layer 2: 反論生成
        counter = await self.generate_counter(proposal)

        # Layer 3: 代替案生成
        alternatives = await self.generate_alternatives(proposal, counter)

        # 3層を統合した提案パケット
        proposal_packet = {
            "proposal_id": proposal["proposal_id"],
            "title": proposal["title"],
            "objective": proposal["objective"],
            "target_icp": proposal["target_icp"],
            "primary_channel": proposal["primary_channel"],
            "proposal": proposal,
            "counter": counter,
            "alternatives": alternatives,
            "total_score": proposal["total_score"],
            "is_auto_recommendable": proposal["is_auto_recommendable"],
            "created_at": proposal["created_at"],
        }

        # PostgreSQLに保存
        await self._save_to_db(proposal_packet)

        # NATSで通知
        await self._notify_via_nats(proposal_packet)

        logger.info(
            f"3層提案生成完了: {proposal['title']} "
            f"(score={proposal['total_score']}, "
            f"auto_recommend={proposal['is_auto_recommendable']})"
        )

        return proposal_packet

    # ========== 週次定例提案 ==========

    async def weekly_autonomous_proposal(self, weekly_context: str = "") -> dict:
        """
        週次定例: 「今週やるべき3手」+「今週やめるべき1手」を自律提案

        設計書 9.3 準拠
        """
        model_selection = choose_best_model_v6(
            task_type="strategy",
            quality="high",
            budget_sensitive=True,
            needs_japanese=True,
        )

        strategy_context = self._build_strategy_context()

        prompt = f"""あなたはSYUTAINβの週次定例提案エンジンです。

## 戦略コンテキスト
{strategy_context}

## 今週の状況
{weekly_context if weekly_context else "状況データなし（デフォルト分析を実行）"}

以下のJSON形式で週次提案を出力してください:
{{
  "do_top3": [
    {{
      "title": "今週やるべきこと1",
      "why": "理由",
      "expected_revenue_jpy": 数値,
      "effort_hours": 数値,
      "priority": 1
    }}
  ],
  "stop_top1": [
    {{
      "title": "今週やめるべきこと",
      "why": "やめるべき理由",
      "loss_if_continue_jpy": 数値
    }}
  ],
  "reusable_assets_top5": ["再利用可能な既存資産"],
  "icp_temperature": {{
    "current": "warm|hot|cold",
    "trend": "up|down|stable",
    "note": "温度感の根拠"
  }},
  "midterm_roadmap": "中長期（3-6ヶ月）の収益拡大提案",
  "automation_suggestions": ["ローカルLLMで自動化すべき新規タスク"]
}}"""

        system_prompt = (
            "SYUTAINβの週次戦略アドバイザー。島原大知の事業を俯瞰し、"
            "今週の最適な行動を根拠付きで提案する。"
            "必ず有効なJSONのみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            weekly_data = self._parse_llm_json(result.get("text", ""))
        except Exception as e:
            logger.error(f"週次提案生成エラー: {e}")
            weekly_data = {
                "do_top3": [],
                "stop_top1": [],
                "reusable_assets_top5": [],
                "icp_temperature": {"current": "unknown", "trend": "unknown", "note": "LLMエラー"},
                "midterm_roadmap": "LLM呼び出し失敗",
                "automation_suggestions": [],
            }

        # 「やるべき3手」それぞれに3層提案パイプラインを実行
        detailed_proposals = []
        do_top3 = weekly_data.get("do_top3", [])
        for item in do_top3[:3]:  # 最大3件
            try:
                packet = await self.run_three_layer_pipeline(
                    context=f"週次提案: {item.get('title', '')} - {item.get('why', '')}",
                    objective="revenue",
                )
                detailed_proposals.append(packet)
            except Exception as e:
                logger.error(f"週次提案の3層パイプラインエラー: {e}")

        weekly_report = {
            "report_id": str(uuid.uuid4()),
            "type": "weekly_autonomous",
            "summary": weekly_data,
            "detailed_proposals": detailed_proposals,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # NATSで週次レポートを通知
        try:
            nats_client = await get_nats_client()
            await nats_client.publish("proposal.weekly", weekly_report)
        except Exception as e:
            logger.error(f"週次レポートNATS通知エラー: {e}")

        logger.info(
            f"週次定例提案完了: やるべき{len(do_top3)}手, "
            f"やめるべき{len(weekly_data.get('stop_top1', []))}手"
        )

        return weekly_report

    # ========== 却下時の代替案再提案 ==========

    async def handle_rejection(
        self, proposal_id: str, rejection_reason: str = ""
    ) -> dict:
        """
        提案が却下された場合、却下理由を推測して代替案を即座に提示

        設計書 1.2: 「却下理由を推測して代替案を即座に提示できる」
        """
        # 元の提案をDBから取得
        original = await self._load_proposal_from_db(proposal_id)
        if not original:
            return {"error": "提案が見つかりません", "proposal_id": proposal_id}

        model_selection = choose_best_model_v6(
            task_type="proposal",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        prompt = f"""提案が却下されました。却下理由を推測し、代替案を提示してください。

## 却下された提案
タイトル: {original.get('title', '不明')}
スコア: {original.get('score', 0)}点

## 島原からの却下理由（あれば）
{rejection_reason if rejection_reason else "理由の記載なし（推測してください）"}

以下のJSON形式で出力してください:
{{
  "guessed_rejection_reason": "推測した却下理由",
  "alternative_proposals": [
    {{
      "title": "代替案タイトル",
      "description": "概要",
      "addresses_concern": "どの懸念に対応しているか",
      "effort": "low|medium|high",
      "revenue_estimate_jpy": 数値
    }}
  ]
}}"""

        system_prompt = (
            "SYUTAINβの提案改善エンジン。却下された理由を推測し、より良い代替案を提示する。"
            "必ず有効なJSONのみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            response = self._parse_llm_json(result.get("text", ""))
        except Exception as e:
            logger.error(f"却下対応LLM呼び出しエラー: {e}")
            response = {
                "guessed_rejection_reason": "推測不能（LLMエラー）",
                "alternative_proposals": [],
            }

        # フィードバックをDBに記録
        await self._save_feedback(proposal_id, "proposal", False, rejection_reason)

        return response

    # ========== DB操作 ==========

    async def _save_to_db(self, proposal_packet: dict):
        """提案をPostgreSQLのproposal_historyテーブルに保存"""
        if not self.pg_pool:
            logger.warning("PostgreSQL未接続。提案のDB保存をスキップ")
            return

        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO proposal_history
                        (proposal_id, title, target_icp, primary_channel,
                         score, proposal_data, counter_data, alternative_data)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (proposal_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        score = EXCLUDED.score,
                        proposal_data = EXCLUDED.proposal_data,
                        counter_data = EXCLUDED.counter_data,
                        alternative_data = EXCLUDED.alternative_data
                    """,
                    proposal_packet["proposal_id"],
                    proposal_packet["title"],
                    proposal_packet.get("target_icp", ""),
                    proposal_packet.get("primary_channel", ""),
                    proposal_packet.get("total_score", 0),
                    json.dumps(proposal_packet.get("proposal", {}), ensure_ascii=False),
                    json.dumps(proposal_packet.get("counter", {}), ensure_ascii=False),
                    json.dumps(proposal_packet.get("alternatives", []), ensure_ascii=False),
                )
                logger.info(f"提案をDBに保存: {proposal_packet['proposal_id']}")
        except Exception as e:
            logger.error(f"提案DB保存エラー: {e}")

    async def _load_proposal_from_db(self, proposal_id: str) -> Optional[dict]:
        """提案をDBから取得"""
        if not self.pg_pool:
            return None
        try:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM proposal_history WHERE proposal_id = $1",
                    proposal_id,
                )
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"提案DB取得エラー: {e}")
            return None

    async def _save_feedback(
        self,
        proposal_id: str,
        layer_used: str,
        adopted: bool,
        rejection_reason: str = "",
    ):
        """提案フィードバックをDBに記録"""
        if not self.pg_pool:
            return
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO proposal_feedback
                        (proposal_id, layer_used, adopted, rejection_reason)
                    VALUES ($1, $2, $3, $4)
                    """,
                    proposal_id,
                    layer_used,
                    adopted,
                    rejection_reason or None,
                )
        except Exception as e:
            logger.error(f"フィードバックDB保存エラー: {e}")

    async def get_proposals(
        self, limit: int = 20, offset: int = 0
    ) -> list:
        """提案一覧をDBから取得"""
        if not self.pg_pool:
            return []
        try:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT proposal_id, title, target_icp, primary_channel,
                           score, adopted, outcome_type, revenue_impact_jpy,
                           proposal_data, counter_data, alternative_data, created_at
                    FROM proposal_history
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"提案一覧取得エラー: {e}")
            return []

    async def approve_proposal(self, proposal_id: str) -> bool:
        """提案を採用としてマーク"""
        if not self.pg_pool:
            return False
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE proposal_history SET adopted = TRUE WHERE proposal_id = $1",
                    proposal_id,
                )
            await self._save_feedback(proposal_id, "proposal", True)
            logger.info(f"提案採用: {proposal_id}")
            return True
        except Exception as e:
            logger.error(f"提案採用エラー: {e}")
            return False

    async def reject_proposal(
        self, proposal_id: str, reason: str = ""
    ) -> dict:
        """提案を却下し、代替案を再提案"""
        if not self.pg_pool:
            return {"error": "DB未接続"}
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE proposal_history SET adopted = FALSE WHERE proposal_id = $1",
                    proposal_id,
                )
        except Exception as e:
            logger.error(f"提案却下DB更新エラー: {e}")

        # 却下理由を推測して代替案を提示
        return await self.handle_rejection(proposal_id, reason)

    # ========== NATS通知 ==========

    async def _notify_via_nats(self, proposal_packet: dict):
        """NATSで提案を通知"""
        try:
            nats_client = await get_nats_client()
            await nats_client.publish(
                "proposal.new",
                {
                    "proposal_id": proposal_packet["proposal_id"],
                    "title": proposal_packet["title"],
                    "score": proposal_packet["total_score"],
                    "is_auto_recommendable": proposal_packet["is_auto_recommendable"],
                },
            )
        except Exception as e:
            logger.error(f"NATS提案通知エラー: {e}")

    # ========== ヘルパー ==========

    def _build_strategy_context(self) -> str:
        """戦略ファイルからコンテキストを構築"""
        parts = []
        if self.strategies["icp_definition"]:
            # 長すぎる場合は先頭2000文字に制限
            icp = self.strategies["icp_definition"][:2000]
            parts.append(f"### ICP定義\n{icp}")
        if self.strategies["channel_strategy"]:
            ch = self.strategies["channel_strategy"][:2000]
            parts.append(f"### チャネル戦略\n{ch}")
        if self.strategies["content_strategy"]:
            cs = self.strategies["content_strategy"][:2000]
            parts.append(f"### コンテンツ戦略\n{cs}")
        return "\n\n".join(parts) if parts else "戦略ファイル未読み込み"

    def _parse_llm_json(self, text: str) -> dict | list:
        """LLM出力からJSONを抽出・パース"""
        if not text:
            return {}
        # ```json ... ``` ブロックを除去
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 最初の```行と最後の```行を除去
            start = 1 if lines[0].startswith("```") else 0
            end = -1 if lines[-1].strip() == "```" else len(lines)
            cleaned = "\n".join(lines[start:end])

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # JSONブロックを探す
            import re
            json_match = re.search(r'[\[{].*[\]}]', cleaned, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning(f"LLM出力のJSONパース失敗: {text[:200]}...")
            return {}

    def _fallback_proposal(self, context: str, objective: str) -> dict:
        """LLMエラー時のフォールバック提案"""
        return {
            "title": "既存コンテンツの再利用提案（フォールバック）",
            "why_now": ["LLMエラーのため自動生成されたフォールバック提案"],
            "expected_outcome": {
                "revenue_estimate_jpy": 0,
                "timeline": "要検討",
                "confidence": 0.1,
            },
            "required_human_actions": ["提案内容の手動作成"],
            "auto_actions_allowed": [],
            "scoring": {
                "icp_fit": 5,
                "channel_fit": 5,
                "content_reuse": 10,
                "speed_to_cash": 5,
                "gross_margin": 5,
                "trust_building": 5,
                "continuity_value": 5,
            },
        }


# シングルトンインスタンス
_engine: Optional[ProposalEngine] = None


async def get_proposal_engine() -> ProposalEngine:
    """ProposalEngineのシングルトンを取得"""
    global _engine
    if _engine is None:
        _engine = ProposalEngine()
        await _engine.initialize()
    return _engine
