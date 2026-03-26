"""
SYUTAINβ V25 OS_Kernel 司令塔 — Step 7-8
設計書 第5-6章準拠

OS_Kernelは全体のオーケストレーターとして機能する。
- Goal Packet の生成（生テキスト → 構造化）
- Capability Audit の実行
- Task Graph の生成と管理
- 5段階自律ループ（認識→思考→行動→検証→停止判断）の駆動
"""

import os
import json
import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from agents.capability_audit import get_capability_audit
from agents.perceiver import Perceiver
from agents.planner import Planner
from agents.executor import Executor
from agents.verifier import Verifier
from agents.stop_decider import StopDecider, DECISION_COMPLETE, DECISION_CONTINUE, \
    DECISION_RETRY_MODIFIED, DECISION_SWITCH_PLAN, DECISION_ESCALATE, \
    DECISION_EMERGENCY_STOP, DECISION_SEMANTIC_STOP, DECISION_INTERFERENCE_STOP
from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client
from tools.loop_guard import get_loop_guard
from tools.cross_goal_detector import get_cross_goal_detector
from tools.event_logger import log_event

load_dotenv()

logger = logging.getLogger("syutain.os_kernel")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# ゴール設定（設計書 6.3準拠）
DEFAULT_MAX_STEPS = 50
DEFAULT_MAX_RETRIES_PER_STEP = 2
DEFAULT_MAX_REPLANS = 3


class GoalPacket:
    """Goal Packet（設計書 第6章 6.3準拠）"""

    def __init__(
        self,
        goal_id: str,
        raw_goal: str,
        parsed_objective: str = "",
        success_definition: Optional[list] = None,
        hard_constraints: Optional[dict] = None,
        soft_constraints: Optional[list] = None,
        approval_boundary: Optional[dict] = None,
        deadline: Optional[str] = None,
        priority: str = "medium",
        fallback_goals: Optional[list] = None,
        max_total_steps: int = DEFAULT_MAX_STEPS,
        max_retries_per_step: int = DEFAULT_MAX_RETRIES_PER_STEP,
        max_replans: int = DEFAULT_MAX_REPLANS,
    ):
        self.goal_id = goal_id
        self.raw_goal = raw_goal
        self.parsed_objective = parsed_objective
        self.success_definition = success_definition or []
        self.hard_constraints = hard_constraints or {}
        self.soft_constraints = soft_constraints or []
        self.approval_boundary = approval_boundary or {
            "human_required": ["公開投稿", "課金発生", "外部アカウント変更", "価格設定", "暗号通貨取引"],
            "auto_allowed": ["下書き生成", "分析", "ログ整理", "候補案生成", "情報収集", "ブラウザ情報収集"],
        }
        self.deadline = deadline
        self.priority = priority
        self.fallback_goals = fallback_goals or []
        self.max_total_steps = max_total_steps
        self.max_retries_per_step = max_retries_per_step
        self.max_replans = max_replans
        self.status = "active"
        self.progress = 0.0
        self.total_steps = 0
        self.total_cost_jpy = 0.0
        self.created_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "raw_goal": self.raw_goal,
            "parsed_objective": self.parsed_objective,
            "success_definition": self.success_definition,
            "hard_constraints": self.hard_constraints,
            "soft_constraints": self.soft_constraints,
            "approval_boundary": self.approval_boundary,
            "deadline": self.deadline,
            "priority": self.priority,
            "fallback_goals": self.fallback_goals,
            "max_total_steps": self.max_total_steps,
            "max_retries_per_step": self.max_retries_per_step,
            "max_replans": self.max_replans,
            "status": self.status,
            "progress": self.progress,
            "total_steps": self.total_steps,
            "total_cost_jpy": self.total_cost_jpy,
        }


class OSKernel:
    """
    OS_Kernel 司令塔

    ALPHA上で常駐し、ゴール受信→能力監査→タスク分解→自律実行ループを駆動する。
    """

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._perceiver = Perceiver()
        self._planner = Planner()
        self._executor = Executor()
        self._verifier = Verifier()
        self._stop_decider = StopDecider()
        self._active_goals: dict[str, GoalPacket] = {}

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    # ===== Goal Packet生成 =====

    async def create_goal_packet(self, raw_goal: str, existing_goal_id: str = None) -> GoalPacket:
        """
        生テキストからGoal Packetを生成する。

        LLMでパースし、objective, success_definition,
        hard_constraints, soft_constraints, approval_boundaryに構造化。

        Args:
            existing_goal_id: ChatAgentが既に作成済みのgoal_id（指定時はそのIDを再利用）
        """
        goal_id = existing_goal_id or f"goal-{uuid.uuid4().hex[:12]}"
        logger.info(f"Goal Packet生成開始: {goal_id} — '{raw_goal[:50]}...'")

        # LLMでゴールをパース（CLAUDE.md ルール5: choose_best_model_v6使用）
        model_sel = choose_best_model_v6(
            task_type="strategy",
            quality="medium",
            budget_sensitive=True,
            is_agentic=True,
        )

        parse_prompt = f"""以下の目標をGoal Packetとして構造化してください。JSON形式で出力してください。

## 目標テキスト
{raw_goal}

## 出力形式
{{
  "parsed_objective": "revenue / growth / automation / content / research",
  "success_definition": ["成功条件1", "成功条件2"],
  "hard_constraints": {{
    "budget_limit_jpy": 500,
    "time_limit_hours": 4,
    "available_nodes": ["ALPHA", "BRAVO", "CHARLIE", "DELTA"]
  }},
  "soft_constraints": ["できれば低コスト", "..."],
  "approval_boundary": {{
    "human_required": ["公開投稿", "課金発生", "外部アカウント変更", "価格設定"],
    "auto_allowed": ["下書き生成", "分析", "ログ整理", "候補案生成"]
  }},
  "deadline": "2026-MM-DD or null",
  "priority": "low / medium / high / critical",
  "fallback_goals": ["最低限の部分目標1", "..."]
}}
"""

        parsed_data = {}
        try:
            llm_result = await asyncio.wait_for(
                call_llm(
                    prompt=parse_prompt,
                    system_prompt=(
                        "あなたはSYUTAINβのGoal Packetパーサーです。"
                        "目標を構造化してJSON形式で出力してください。"
                    ),
                    model_selection=model_sel,
                ),
                timeout=90,
            )
            text = llm_result.get("text", "")
            logger.info(f"Goal Packet LLMパース完了: {goal_id} ({len(text)}文字)")

            # JSON抽出
            import re
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                parsed_data = json.loads(json_match.group())
        except asyncio.TimeoutError:
            logger.error(f"Goal Packetパース タイムアウト(90s): {goal_id} — デフォルト値で続行")
        except Exception as e:
            logger.error(f"Goal Packetパース失敗: {e}")

        # GoalPacket構築
        goal_packet = GoalPacket(
            goal_id=goal_id,
            raw_goal=raw_goal,
            parsed_objective=parsed_data.get("parsed_objective", "general"),
            success_definition=parsed_data.get("success_definition", [f"{raw_goal}を達成する"]),
            hard_constraints=parsed_data.get("hard_constraints", {
                "budget_limit_jpy": float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80"))),
                "time_limit_hours": 4,
                "available_nodes": ["ALPHA", "BRAVO", "CHARLIE", "DELTA"],
            }),
            soft_constraints=parsed_data.get("soft_constraints", ["できれば低コスト"]),
            approval_boundary=parsed_data.get("approval_boundary"),
            deadline=parsed_data.get("deadline"),
            priority=parsed_data.get("priority", "medium"),
            fallback_goals=parsed_data.get("fallback_goals", []),
        )

        # PostgreSQLに保存
        await self._save_goal_packet(goal_packet)

        # Cross-Goal Detectorに登録
        cgd = get_cross_goal_detector()
        cgd.register_goal(goal_id)

        self._active_goals[goal_id] = goal_packet
        logger.info(f"Goal Packet生成完了: {goal_id}")

        # イベント記録: goal.created
        asyncio.ensure_future(log_event(
            "goal.created", "goal",
            {"raw_goal": raw_goal[:200], "parsed_objective": goal_packet.parsed_objective,
             "priority": goal_packet.priority},
            goal_id=goal_id,
        ))

        return goal_packet

    async def _save_goal_packet(self, gp: GoalPacket):
        """Goal PacketをPostgreSQLに保存"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO goal_packets
                            (goal_id, raw_goal, parsed_objective, success_definition,
                             hard_constraints, soft_constraints, approval_boundary, status, progress)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (goal_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            progress = EXCLUDED.progress
                        """,
                        gp.goal_id, gp.raw_goal, gp.parsed_objective,
                        json.dumps(gp.success_definition, ensure_ascii=False),
                        json.dumps(gp.hard_constraints, ensure_ascii=False, default=str),
                        json.dumps(gp.soft_constraints, ensure_ascii=False),
                        json.dumps(gp.approval_boundary, ensure_ascii=False),
                        gp.status, gp.progress,
                    )
                logger.info(f"Goal Packet '{gp.goal_id}' をPostgreSQLに保存")
        except Exception as e:
            logger.error(f"Goal Packet保存失敗: {e}")

    # ===== 5段階自律ループ =====

    async def execute_goal(self, raw_goal: str, existing_goal_id: str = None) -> dict:
        """
        ゴールを受け取り、5段階自律ループで実行する。

        設計書 第6章:
        ① 認識（Perceive） → ② 思考（Think） → ③ 行動（Act）
        → ④ 検証（Verify） → ⑤ 停止判断（StopOrContinue）

        Args:
            raw_goal: 生テキストの目標
            existing_goal_id: ChatAgentが既に作成済みのgoal_id（二重登録防止）
        """
        # Goal Packet生成（既存IDがあれば再利用）
        goal_packet = await self.create_goal_packet(raw_goal, existing_goal_id=existing_goal_id)
        gp_dict = goal_packet.to_dict()

        logger.info(f"=== 5段階自律ループ開始: {goal_packet.goal_id} ===")

        # 新ゴール開始時にSemanticLoopDetectorをリセット（前ゴールの履歴が残ると誤検知する）
        try:
            from tools.semantic_loop_detector import get_semantic_loop_detector
            get_semantic_loop_detector().reset()
        except Exception:
            pass

        # 判断根拠トレース
        try:
            await self._record_trace(
                action="execute_goal:start",
                reasoning=f"5段階自律ループ開始。目標: {raw_goal[:100]}。パース結果: {goal_packet.parsed_objective}",
                confidence=1.0,
                context={"parsed_objective": goal_packet.parsed_objective, "priority": goal_packet.priority,
                         "max_steps": goal_packet.max_total_steps},
                goal_id=goal_packet.goal_id,
            )
        except Exception:
            pass

        all_results = []
        fallback_count = len(goal_packet.fallback_goals)
        current_plan_index = 0  # 0=主プラン, 1+=フォールバック

        while True:
            # ① 認識（Perceive）
            logger.info(f"--- ① 認識（Perceive）: {goal_packet.goal_id} ---")
            try:
                perception = await self._perceiver.perceive(goal_packet.goal_id, goal_packet.raw_goal)
            except Exception as e:
                logger.error(f"認識エンジンエラー: {e}")
                perception = {"goal_id": goal_packet.goal_id, "raw_goal": goal_packet.raw_goal}

            # ② 思考（Think）— タスクDAG生成
            logger.info(f"--- ② 思考（Think）: {goal_packet.goal_id} ---")
            try:
                task_graph = await self._planner.plan(gp_dict, perception)
            except Exception as e:
                logger.error(f"計画エンジンエラー: {e}")
                break

            if not task_graph.nodes:
                logger.warning("タスクグラフが空です")
                break

            # ③ 行動（Act）& ④ 検証（Verify）& ⑤ 停止判断
            completed_count = 0
            total_count = len(task_graph.nodes)
            decision = None  # デフォルト値（ready_tasksが空の場合のスコープ漏洩防止）

            while True:
                # 実行可能タスクを取得
                ready_tasks = task_graph.get_ready_tasks()
                if not ready_tasks:
                    if task_graph.all_completed():
                        break
                    else:
                        logger.warning("実行可能タスクなし（依存関係未解決）")
                        break

                for task_node in ready_tasks:
                    task_dict = task_node.to_dict()

                    # 突然変異注入（設計書第24章 — try-exceptで完全隔離）
                    try:
                        from agents.mutation_engine import should_mutate, apply_deviation, mutate_text_style
                        if should_mutate():
                            _action_id = f"dispatch_{task_dict.get('task_id', '')}"
                            # タスク優先度に微小な逸脱を加える
                            if "priority" in task_dict and isinstance(task_dict["priority"], (int, float)):
                                task_dict["priority"] = apply_deviation(
                                    float(task_dict["priority"]), f"{_action_id}_priority"
                                )
                            # 文体パラメータがあれば変異
                            if "style_params" in task_dict and isinstance(task_dict["style_params"], dict):
                                task_dict["style_params"] = mutate_text_style(
                                    task_dict["style_params"], _action_id
                                )
                    except Exception:
                        pass  # 変異エンジンのバグで処理を止めない

                    # ③ 行動（Act）
                    logger.info(f"--- ③ 行動（Act）: {task_node.task_id} ---")
                    # イベント記録: task.dispatched（意思決定トレース付き）
                    asyncio.ensure_future(log_event(
                        "task.dispatched", "task",
                        {
                            "node": task_node.assigned_node,
                            "type": task_node.task_type,
                            "description": task_node.description[:100],
                            "reason": f"assigned_to_{task_node.assigned_node}",
                            "goal_step": goal_packet.total_steps + 1,
                        },
                        goal_id=goal_packet.goal_id, task_id=task_node.task_id,
                    ))
                    try:
                        exec_result = await self._executor.execute_task(task_dict, gp_dict)
                        result_dict = exec_result.to_dict()
                    except Exception as e:
                        logger.error(f"行動エンジンエラー: {e}")
                        result_dict = {
                            "task_id": task_node.task_id,
                            "status": "failure",
                            "error_class": "external",
                            "error_message": str(e),
                        }

                    all_results.append(result_dict)
                    goal_packet.total_steps += 1
                    goal_packet.total_cost_jpy += result_dict.get("cost_jpy", 0)

                    # ④ 検証（Verify）
                    logger.info(f"--- ④ 検証（Verify）: {task_node.task_id} ---")
                    try:
                        verification = await self._verifier.verify(
                            result_dict, gp_dict, completed_count, total_count,
                        )
                        verify_dict = verification.to_dict()
                    except Exception as e:
                        logger.error(f"検証エンジンエラー: {e}")
                        # エラー時でも出力があれば品質0.5をデフォルトとして設定
                        has_output = bool(result_dict.get("output", {}).get("text", ""))
                        verify_dict = {
                            "status": "partial" if has_output else "failure",
                            "goal_progress": completed_count / max(total_count, 1),
                            "retry_value": "none",
                            "quality_score": 0.5 if has_output else 0.0,
                        }

                    # タスクステータス + 品質スコアをDBに反映
                    q_score = verify_dict.get("quality_score", 0.0)
                    if verify_dict["status"] in ["success", "partial"]:
                        task_graph.mark_completed(task_node.task_id)
                        completed_count += 1
                        # イベント記録: task.completed
                        asyncio.ensure_future(log_event(
                            "task.completed", "task",
                            {"quality_score": q_score,
                             "model": result_dict.get("model_used", ""),
                             "cost_jpy": result_dict.get("cost_jpy", 0),
                             "status": verify_dict["status"]},
                            goal_id=goal_packet.goal_id, task_id=task_node.task_id,
                        ))
                    else:
                        task_graph.mark_failed(task_node.task_id)
                        # イベント記録: task.failed
                        asyncio.ensure_future(log_event(
                            "task.failed", "task",
                            {"error_class": verify_dict.get("error_class", "unknown"),
                             "retry_value": verify_dict.get("retry_value", "none"),
                             "error": result_dict.get("error_message", "")[:200]},
                            severity="warning",
                            goal_id=goal_packet.goal_id, task_id=task_node.task_id,
                        ))
                    # 2段階精錬: 品質0.7未満のコンテンツ系タスクをAPI精錬（CLAUDE.md ルール6）
                    refinable_types = {"content", "drafting", "note_article", "product_desc", "booth_description"}
                    output_text = ""
                    if isinstance(result_dict.get("output"), dict):
                        output_text = result_dict["output"].get("text", "")
                    elif isinstance(result_dict.get("output"), str):
                        output_text = result_dict["output"]

                    if (0.3 <= q_score < 0.7
                        and task_node.task_type in refinable_types
                        and output_text and len(output_text) > 50):
                        try:
                            from tools.two_stage_refiner import two_stage_refine
                            logger.info(f"2段階精錬発動: {task_node.task_id} (品質{q_score:.2f})")
                            refined = await two_stage_refine(
                                prompt=f"以下のテキストを改善してください:\n\n{output_text}",
                                system_prompt="品質を向上させてください。論理性、日本語の自然さ、有用性を改善。",
                                task_type=task_node.task_type,
                            )
                            if refined.get("text") and refined.get("quality_score", 0) > q_score:
                                new_q = refined["quality_score"]
                                result_dict["output"] = {"text": refined["text"]}
                                result_dict["refined"] = True
                                result_dict["cost_jpy"] = result_dict.get("cost_jpy", 0) + refined.get("cost_jpy", 0)
                                goal_packet.total_cost_jpy += refined.get("cost_jpy", 0)
                                asyncio.ensure_future(log_event(
                                    "quality.refinement", "task",
                                    {"original_score": q_score, "refined_score": new_q,
                                     "model": refined.get("model_used", ""),
                                     "cost_jpy": refined.get("cost_jpy", 0)},
                                    goal_id=goal_packet.goal_id, task_id=task_node.task_id,
                                ))
                                q_score = new_q
                                logger.info(f"精錬成功: {q_score:.2f} → {new_q:.2f}")
                        except Exception as e:
                            logger.warning(f"2段階精錬失敗（元の結果を維持）: {e}")

                    # イベント記録: quality.scored
                    if q_score > 0:
                        asyncio.ensure_future(log_event(
                            "quality.scored", "task",
                            {"quality_score": q_score, "task_type": task_node.task_type},
                            goal_id=goal_packet.goal_id, task_id=task_node.task_id,
                        ))
                    try:
                        pool = await self._get_pool()
                        if pool:
                            async with pool.acquire() as conn:
                                await conn.execute(
                                    "UPDATE tasks SET quality_score=$1, updated_at=NOW() WHERE id=$2",
                                    q_score, task_node.task_id,
                                )
                    except Exception as e:
                        logger.warning(f"品質スコアDB反映失敗 ({task_node.task_id}): {e}")

                    # ⑤ 停止判断（StopOrContinue）
                    logger.info(f"--- ⑤ 停止判断: {task_node.task_id} ---")
                    remaining = total_count - completed_count
                    remaining_fallbacks = fallback_count - current_plan_index

                    try:
                        stop_decision = await self._stop_decider.decide(
                            goal_id=goal_packet.goal_id,
                            verification_result=verify_dict,
                            remaining_task_count=remaining,
                            fallback_plans_remaining=remaining_fallbacks,
                            action_key=task_node.task_id,
                            action_purpose=task_node.description,
                            action_method=task_node.task_type,
                            action_result_text=result_dict.get("status", ""),
                            value_justification=task_node.description,
                            task_cost_jpy=result_dict.get("cost_jpy", 0),
                        )
                    except Exception as e:
                        logger.error(f"停止判断エラー: {e}")
                        stop_decision = type("SD", (), {
                            "decision": DECISION_CONTINUE,
                            "reason": f"停止判断エラー: {e}",
                            "remaining_steps": remaining,
                            "fallback_available": remaining_fallbacks > 0,
                        })()

                    decision = stop_decision.decision

                    # 停止判断に基づく制御
                    if decision == DECISION_COMPLETE:
                        logger.info(f"ゴール達成: {goal_packet.goal_id}")
                        goal_packet.status = "completed"
                        goal_packet.progress = 1.0
                        await self._update_goal_status(goal_packet)
                        avg_quality = sum(r.get("quality_score", 0) or 0 for r in all_results) / max(len(all_results), 1)
                        asyncio.ensure_future(log_event(
                            "goal.completed", "goal",
                            {"total_steps": goal_packet.total_steps,
                             "total_cost_jpy": goal_packet.total_cost_jpy,
                             "avg_quality": round(avg_quality, 3)},
                            goal_id=goal_packet.goal_id,
                        ))
                        return self._build_final_result(goal_packet, all_results, "completed")

                    elif decision in [DECISION_EMERGENCY_STOP, DECISION_SEMANTIC_STOP, DECISION_INTERFERENCE_STOP]:
                        logger.critical(f"{decision}: {stop_decision.reason}")
                        goal_packet.status = "emergency_stopped"
                        await self._update_goal_status(goal_packet)
                        asyncio.ensure_future(log_event(
                            "loopguard.triggered", "system",
                            {"decision": decision, "reason": stop_decision.reason,
                             "step_count": goal_packet.total_steps,
                             "cost_jpy": goal_packet.total_cost_jpy,
                             "layer_name": decision.lower().replace("_", " ")},
                            severity="warning",
                            goal_id=goal_packet.goal_id,
                        ))
                        # CLAUDE.md ルール12: 重要判断はDiscord + Web UIで通知
                        try:
                            from tools.discord_notify import notify_emergency_kill
                            await notify_emergency_kill(
                                reason=f"{decision}: {stop_decision.reason}",
                                goal_id=goal_packet.goal_id,
                                step_count=goal_packet.total_steps,
                                cost_jpy=goal_packet.total_cost_jpy,
                            )
                        except Exception:
                            pass
                        return self._build_final_result(goal_packet, all_results, decision)

                    elif decision == DECISION_ESCALATE:
                        logger.warning(f"人間エスカレーション: {stop_decision.reason}")
                        goal_packet.status = "escalated"
                        await self._update_goal_status(goal_packet)
                        asyncio.ensure_future(log_event(
                            "goal.escalated", "goal",
                            {"reason": stop_decision.reason},
                            severity="warning",
                            goal_id=goal_packet.goal_id,
                        ))
                        # CLAUDE.md ルール12: 重要判断はDiscord + Web UIで通知
                        try:
                            from tools.discord_notify import notify_discord
                            await notify_discord(
                                f"🚨 エスカレーション: {stop_decision.reason}\n"
                                f"Goal: {goal_packet.goal_id}"
                            )
                        except Exception:
                            pass
                        # 到達不能→部分目標自動再設定（設計書V25 第1.2節）
                        if goal_packet.fallback_goals:
                            fallback = goal_packet.fallback_goals.pop(0)
                            logger.info(f"部分目標に切替: {fallback[:50]}")
                            asyncio.ensure_future(log_event(
                                "goal.fallback_activated", "goal",
                                {"original_goal": goal_packet.raw_goal[:100],
                                 "fallback_goal": fallback[:100],
                                 "reason": stop_decision.reason},
                                goal_id=goal_packet.goal_id,
                            ))
                            try:
                                fallback_result = await self.execute_goal(
                                    fallback, existing_goal_id=f"{goal_packet.goal_id}-fb"
                                )
                                all_results.extend(fallback_result.get("task_results", []))
                            except Exception as fb_err:
                                logger.error(f"部分目標実行失敗: {fb_err}")
                        return self._build_final_result(goal_packet, all_results, "escalated")

                    elif decision == DECISION_SWITCH_PLAN:
                        logger.info(f"プラン切替: {stop_decision.reason}")
                        current_plan_index += 1
                        lg = get_loop_guard()
                        lg.increment_replan(goal_packet.goal_id)
                        break  # 内側ループを抜けて再計画

                    elif decision == DECISION_RETRY_MODIFIED:
                        logger.info(f"修正再試行: {stop_decision.reason}")
                        # 次のready_tasksで自然に再実行される

                    # DECISION_CONTINUE: そのまま続行

                # SWITCH_PLAN時は外側ループで再計画
                if decision == DECISION_SWITCH_PLAN:
                    break

            # 全タスク完了チェック
            if task_graph.all_completed():
                goal_packet.status = "completed"
                goal_packet.progress = 1.0
                await self._update_goal_status(goal_packet)
                return self._build_final_result(goal_packet, all_results, "completed")

            # SWITCH_PLANでない場合は終了
            if decision != DECISION_SWITCH_PLAN:
                break

        # ループ終了（未完了）
        goal_packet.status = "incomplete"
        await self._update_goal_status(goal_packet)
        return self._build_final_result(goal_packet, all_results, "incomplete")

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO agent_reasoning_trace
                           (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        "OS_KERNEL", goal_id, task_id, action, reasoning,
                        confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                    )
        except Exception:
            pass

    async def _update_goal_status(self, gp: GoalPacket):
        """ゴールのステータスをDBに更新"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE goal_packets SET
                            status = $1, progress = $2, total_steps = $3,
                            total_cost_jpy = $4, completed_at = CASE WHEN $1 = 'completed' THEN NOW() ELSE NULL END
                        WHERE goal_id = $5
                        """,
                        gp.status, gp.progress, gp.total_steps,
                        gp.total_cost_jpy, gp.goal_id,
                    )
        except Exception as e:
            logger.error(f"ゴールステータス更新失敗: {e}")

        # Cross-Goal Detector登録解除
        try:
            cgd = get_cross_goal_detector()
            cgd.unregister_goal(gp.goal_id)
        except Exception:
            pass

        # LoopGuard状態クリア
        try:
            lg = get_loop_guard()
            lg.reset_goal(gp.goal_id)
        except Exception:
            pass

        # SemanticLoopDetectorリセット
        try:
            from tools.semantic_loop_detector import get_semantic_loop_detector
            get_semantic_loop_detector().reset()
        except Exception:
            pass

    def _build_final_result(self, gp: GoalPacket, results: list, status: str) -> dict:
        """最終結果を構築 + 成果物Markdown出力 + Blueskyドラフト生成"""
        final = {
            "goal_id": gp.goal_id,
            "raw_goal": gp.raw_goal,
            "status": status,
            "progress": gp.progress,
            "total_steps": gp.total_steps,
            "total_cost_jpy": gp.total_cost_jpy,
            "task_results": results,
            "completed_at": datetime.now().isoformat(),
        }

        # 品質0.5以上のコンテンツをMarkdownファイルとして出力（ゴール状態問わず）
        try:
            self._save_quality_artifacts(gp.goal_id, results)
        except Exception as e:
            logger.warning(f"成果物Markdown出力失敗: {e}")

        return final

    def _save_quality_artifacts(self, goal_id: str, results: list):
        """品質0.7以上の成果物をdata/artifacts/にMarkdown保存"""
        artifacts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)

        for r in results:
            output = r.get("output", {})
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except Exception:
                    output = {"text": output}

            text = output.get("text", "") if isinstance(output, dict) else str(output)
            quality = r.get("quality_score", 0) or 0

            if text and len(text) > 100 and quality >= 0.5:
                task_id = r.get("task_id", "unknown")
                task_type = r.get("task_type", "output")
                # 日付_タスクタイプ_品質_内容要約 のファイル名
                date_str = datetime.now().strftime("%Y%m%d")
                # テキスト冒頭から20文字で内容を示す（ファイル名に使えない文字を除去）
                import re as _re
                summary_raw = text[:40].replace("\n", " ").strip()
                summary_clean = _re.sub(r'[^\w\s\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f]', '', summary_raw)[:20].strip()
                if not summary_clean:
                    summary_clean = task_id[-6:]
                filename = f"{date_str}_{task_type}_{quality:.2f}_{summary_clean}.md"
                filepath = os.path.join(artifacts_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {task_type}: {summary_clean}\n")
                    f.write(f"- ゴール: {goal_id}\n")
                    f.write(f"- タスク: {task_id}\n")
                    f.write(f"- 品質スコア: {quality}\n")
                    f.write(f"- 生成日: {datetime.now().isoformat()}\n\n---\n\n")
                    f.write(text)
                logger.info(f"成果物Markdown保存: {filepath}")
                import asyncio as _aio
                try:
                    loop = _aio.get_event_loop()
                    if loop.is_running():
                        _aio.ensure_future(log_event(
                            "quality.artifact", "task",
                            {"filepath": filepath, "quality_score": quality,
                             "length": len(text)},
                            goal_id=goal_id, task_id=task_id,
                        ))
                except Exception:
                    pass

    async def close(self):
        """全リソースを解放"""
        for component in [self._perceiver, self._planner, self._executor, self._verifier]:
            try:
                await component.close()
            except Exception as e:
                logger.warning(f"コンポーネント終了エラー: {e}")
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")


# シングルトン
_instance: Optional[OSKernel] = None


def get_os_kernel() -> OSKernel:
    """OSKernelのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = OSKernel()
    return _instance
