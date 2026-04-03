"""
SYUTAINβ V25 認識エンジン（Perceiver）— Step 8
設計書 第6章 6.2「① 認識（Perceive）」準拠

外部/内部の状態情報を収集し、Planner向けに構造化する。
5段階自律ループの第1段階。
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from agents.capability_audit import get_capability_audit
from tools.nats_client import get_nats_client
from tools.budget_guard import get_budget_guard
from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm

load_dotenv()

logger = logging.getLogger("syutain.perceiver")

# コンテキスト圧縮の閾値（文字数）
CONTEXT_MAX_CHARS = 8000

# 圧縮対象外（絶対に圧縮してはいけないキー）
NEVER_COMPRESS_KEYS = {
    "budget", "approval_boundaries", "persona_context", "goal_id",
    "raw_goal", "timestamp", "checklist",
}

# 圧縮優先度（低い数値ほど先に圧縮される）
COMPRESS_PRIORITY = {
    "agents_map": 1,          # 大きいが変化少ない → 最優先で圧縮
    "market_context": 2,      # 古い情報 → 圧縮可
    "previous_attempts": 3,   # 過去の試行 → 要約可
    "strategy": 4,            # 戦略ファイル → 要約可
    "session_memory": 5,      # 古いセッション記憶 → 要約可
    "capability_snapshot": 6, # ノード情報 → 要約可
    "intel_context": 7,       # インテリジェンス → 要約可
    "mcp_tools_available": 8,
    "api_availability": 9,
    "browser_capability": 10,
    "bravo_status": 11,
}


class Perceiver:
    """認識エンジン — 環境状態の収集と構造化"""

    def __init__(self):
        pass

    async def perceive(self, goal_id: str, raw_goal: str) -> dict:
        """
        目標を受けて環境を認識し、認識データを構造化して返す。

        設計書 perceive_checklist:
        - goal_received / goal_packet_generated
        - capability_audit_done
        - nodes_status_checked (全4台)
        - bravo_status_checked (V25)
        - mcp_tools_discovered
        - budget_remaining_checked
        - approval_boundaries_loaded
        - strategy_files_loaded
        - previous_attempts_loaded
        - market_context_loaded
        - api_availability_checked
        - browser_capability_checked (V25: 4層)
        """
        logger.info(f"認識開始: goal_id={goal_id}")

        perception = {
            "goal_id": goal_id,
            "raw_goal": raw_goal,
            "timestamp": datetime.now().isoformat(),
            "checklist": {},
        }

        # 1. Capability Audit（全4台監査）
        capability_snapshot = None
        try:
            audit = get_capability_audit()
            capability_snapshot = await audit.run_full_audit()
            perception["capability_snapshot"] = capability_snapshot
            perception["checklist"]["capability_audit_done"] = True
            perception["checklist"]["nodes_status_checked"] = True
        except Exception as e:
            logger.error(f"Capability Audit失敗: {e}")
            perception["checklist"]["capability_audit_done"] = False
            perception["checklist"]["nodes_status_checked"] = False

        # 2. BRAVO状態確認（V25: Phase 1完全稼働確認）
        try:
            bravo_status = capability_snapshot.get("nodes", {}).get("bravo", {}) if capability_snapshot else {}
            perception["bravo_status"] = bravo_status
            perception["checklist"]["bravo_status_checked"] = True
        except Exception as e:
            logger.warning(f"BRAVO状態確認失敗: {e}")
            perception["checklist"]["bravo_status_checked"] = False

        # 3. MCP ツール発見（CLAUDE.md ルール20: 動的確認）
        try:
            mcp_servers = capability_snapshot.get("mcp_servers", {}) if capability_snapshot else {}
            perception["mcp_tools_available"] = mcp_servers
            perception["checklist"]["mcp_tools_discovered"] = True
        except Exception as e:
            logger.warning(f"MCPツール発見失敗: {e}")
            perception["checklist"]["mcp_tools_discovered"] = False

        # 4. 予算残高チェック
        try:
            bg = get_budget_guard()
            budget_status = await bg.get_budget_status()
            perception["budget"] = budget_status
            perception["checklist"]["budget_remaining_checked"] = True
        except Exception as e:
            logger.warning(f"予算チェック失敗: {e}")
            perception["checklist"]["budget_remaining_checked"] = False

        # 5. 承認境界の読み込み
        try:
            perception["approval_boundaries"] = {
                "human_required": [
                    "公開投稿", "課金発生", "外部アカウント変更",
                    "価格設定", "暗号通貨取引",
                ],
                "auto_allowed": [
                    "下書き生成", "分析", "ログ整理",
                    "候補案生成", "情報収集", "ブラウザ情報収集",
                ],
            }
            perception["checklist"]["approval_boundaries_loaded"] = True
        except Exception as e:
            logger.warning(f"承認境界読み込み失敗: {e}")
            perception["checklist"]["approval_boundaries_loaded"] = False

        # 6. 戦略ファイルの読み込み（CLAUDE.md ルール10: strategy/参照）
        try:
            strategy_data = await self._load_strategy_files()
            perception["strategy"] = strategy_data
            perception["checklist"]["strategy_files_loaded"] = bool(strategy_data)
        except Exception as e:
            logger.warning(f"戦略ファイル読み込み失敗: {e}")
            perception["checklist"]["strategy_files_loaded"] = False

        # 7. 過去の試行を読み込み
        try:
            previous = await self._load_previous_attempts(goal_id)
            perception["previous_attempts"] = previous
            perception["checklist"]["previous_attempts_loaded"] = True
        except Exception as e:
            logger.warning(f"過去の試行読み込み失敗: {e}")
            perception["checklist"]["previous_attempts_loaded"] = False

        # 8. 市場コンテキスト（直近の情報収集結果）
        try:
            market = await self._load_market_context()
            perception["market_context"] = market
            perception["checklist"]["market_context_loaded"] = bool(market)
        except Exception as e:
            logger.warning(f"市場コンテキスト読み込み失敗: {e}")
            perception["checklist"]["market_context_loaded"] = False

        # 9. API可用性チェック
        try:
            api_status = capability_snapshot.get("external_apis", {}) if capability_snapshot else {}
            perception["api_availability"] = api_status
            perception["checklist"]["api_availability_checked"] = True
        except Exception as e:
            logger.warning(f"API可用性チェック失敗: {e}")
            perception["checklist"]["api_availability_checked"] = False

        # 10. ブラウザ能力チェック（V25: 4層構成）
        try:
            tools = capability_snapshot.get("tools", {}) if capability_snapshot else {}
            perception["browser_capability"] = {
                "lightpanda": tools.get("lightpanda", False),
                "stagehand_v3": tools.get("stagehand_v3", False),
                "playwright": tools.get("playwright", False),
                "computer_use_gpt54": tools.get("computer_use_gpt54", False),
            }
            perception["checklist"]["browser_capability_checked"] = True
        except Exception as e:
            logger.warning(f"ブラウザ能力チェック失敗: {e}")
            perception["checklist"]["browser_capability_checked"] = False

        perception["checklist"]["goal_received"] = True

        # 11. ペルソナ記憶 — 目標に関連するDaichiの価値観・判断基準（CLAUDE.md ルール23）
        try:
            from brain_alpha.memory_manager import recall_relevant_memory
            persona_memories = await recall_relevant_memory(raw_goal, limit=5)
            perception["persona_context"] = persona_memories
            perception["checklist"]["persona_memory_loaded"] = bool(persona_memories)
        except Exception as e:
            logger.warning(f"ペルソナ記憶読み込み失敗: {e}")
            perception["persona_context"] = []
            perception["checklist"]["persona_memory_loaded"] = False

        # 12. セッション記憶 — 直近セッションの経験・未解決課題
        try:
            from brain_alpha.memory_manager import load_session_memory
            session_memories = await load_session_memory(limit=2)
            perception["session_memory"] = session_memories
            perception["checklist"]["session_memory_loaded"] = bool(session_memories)
        except Exception as e:
            logger.warning(f"セッション記憶読み込み失敗: {e}")
            perception["session_memory"] = []
            perception["checklist"]["session_memory_loaded"] = False

        # 13. AGENTS.md — システム能力マップ（ノード/ツール/制約/障害パターン）
        try:
            agents_md_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "AGENTS.md"
            )
            if os.path.isfile(agents_md_path):
                with open(agents_md_path, "r", encoding="utf-8") as f:
                    perception["agents_map"] = f.read()
                perception["checklist"]["agents_map_loaded"] = True
            else:
                perception["checklist"]["agents_map_loaded"] = False
        except Exception as e:
            logger.warning(f"AGENTS.md読み込み失敗: {e}")
            perception["checklist"]["agents_map_loaded"] = False

        # 14. 直近の重要インテリジェンス（importance_score上位）
        try:
            from tools.agent_context import build_agent_context
            intel_context = await build_agent_context("perceiver")
            if intel_context:
                perception["intel_context"] = intel_context
            perception["checklist"]["intel_context_loaded"] = bool(intel_context)
        except Exception as e:
            logger.warning(f"インテリジェンスコンテキスト読み込み失敗: {e}")
            perception["checklist"]["intel_context_loaded"] = False

        ok_count = sum(1 for v in perception['checklist'].values() if v)
        total_count = len(perception['checklist'])
        logger.info(f"認識完了: {ok_count}/{total_count} チェック項目OK")

        # コンテキスト圧縮（8000文字超過時にLLMで要約）
        try:
            perception = await self._compress_context(perception)
        except Exception as e:
            logger.warning(f"コンテキスト圧縮失敗（無視）: {e}")

        # 判断根拠トレース
        try:
            await self._record_trace(
                action="perceive",
                reasoning=f"認識完了: {ok_count}/{total_count} チェック項目OK。ゴール: {raw_goal[:80]}",
                confidence=ok_count / max(total_count, 1),
                context={"checklist": perception["checklist"], "goal_id": goal_id},
                goal_id=goal_id,
            )
        except Exception:
            pass

        return perception

    async def _compress_context(self, perception: dict) -> dict:
        """コンテキスト圧縮: 総サイズが8000文字を超過した場合、
        優先度の低いセクションをLLMで要約して圧縮する。

        budget, approval_boundaries, persona_context は絶対に圧縮しない。
        """
        total = sum(len(str(v)) for v in perception.values())
        if total <= CONTEXT_MAX_CHARS:
            return perception

        logger.info(f"コンテキスト圧縮開始: {total}文字 → 目標{CONTEXT_MAX_CHARS}文字")

        # 圧縮対象を優先度順にソート
        compressible = []
        for key, value in perception.items():
            if key in NEVER_COMPRESS_KEYS:
                continue
            size = len(str(value))
            if size < 100:  # 小さいフィールドは圧縮不要
                continue
            priority = COMPRESS_PRIORITY.get(key, 50)
            compressible.append((priority, key, size))
        compressible.sort(key=lambda x: x[0])

        # 圧縮用モデル選択（低品質・ローカル優先）
        model_sel = choose_best_model_v6(
            task_type="compression",
            quality="low",
            local_available=True,
        )

        current_total = total
        for priority, key, original_size in compressible:
            if current_total <= CONTEXT_MAX_CHARS:
                break

            # LLMで要約
            try:
                content_str = str(perception[key])
                if len(content_str) > 4000:
                    content_str = content_str[:4000]

                result = await call_llm(
                    prompt=(
                        f"以下の「{key}」コンテキストを重要な情報を保持しつつ"
                        f"200文字以内に要約してください。\n\n{content_str}"
                    ),
                    system_prompt="簡潔にJSON互換の要約を生成。重要な数値・ステータス・キー情報を保持。",
                    model_selection=model_sel,
                )
                summary_text = result.get("text", "")
                if summary_text and len(summary_text) < original_size:
                    perception[key] = f"[compressed] {summary_text}"
                    new_size = len(perception[key])
                    current_total -= (original_size - new_size)
                    logger.info(
                        f"圧縮: {key} {original_size}→{new_size}文字 "
                        f"(残り{current_total}文字)"
                    )
            except Exception as e:
                logger.debug(f"コンテキスト圧縮失敗（{key}）: {e}")
                continue

        logger.info(f"コンテキスト圧縮完了: {total}→{current_total}文字")
        return perception

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "PERCEIVER", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def _load_strategy_files(self) -> dict:
        """戦略ファイル（strategy/）を読み込む"""
        strategy = {}
        strategy_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategy")

        try:
            if os.path.isdir(strategy_dir):
                for filename in os.listdir(strategy_dir):
                    filepath = os.path.join(strategy_dir, filename)
                    if os.path.isfile(filepath):
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                if filename.endswith(".json"):
                                    strategy[filename] = json.load(f)
                                elif filename.endswith((".yaml", ".yml")):
                                    strategy[filename] = f.read()
                                elif filename.endswith(".md"):
                                    strategy[filename] = f.read()
                        except Exception as e:
                            logger.warning(f"戦略ファイル'{filename}'読み込み失敗: {e}")
        except Exception as e:
            logger.warning(f"strategy/ディレクトリ走査失敗: {e}")

        return strategy

    async def _load_previous_attempts(self, goal_id: str) -> list[dict]:
        """過去の同一ゴールへの試行を読み込む"""
        try:
            async with get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, type, status, output_data, cost_jpy, quality_score, created_at
                    FROM tasks
                    WHERE goal_id = $1
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    goal_id,
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"過去の試行DB読み込み失敗: {e}")
            return []

    async def _load_market_context(self) -> list[dict]:
        """直近の情報収集結果を読み込む"""
        try:
            async with get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT source, title, summary, importance_score, category, created_at
                    FROM intel_items
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    ORDER BY importance_score DESC
                    LIMIT 10
                    """,
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"市場コンテキストDB読み込み失敗: {e}")
            return []

    async def close(self):
        pass
