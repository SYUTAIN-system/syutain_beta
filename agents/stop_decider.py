"""
SYUTAINβ V25 停止判断エンジン（StopDecider）— Step 8
設計書 第6章 6.2「⑤ 停止判断（StopOrContinue）」準拠

続行 / 経路変更 / 人間エスカレーション / 停止を判断する。
LoopGuardと連携して9層の防御壁を通過させる。
"""

import os
import json
import logging
from typing import Optional

from dotenv import load_dotenv

from tools.loop_guard import get_loop_guard
from tools.nats_client import get_nats_client

load_dotenv()

logger = logging.getLogger("syutain.stop_decider")

# 停止判断の結果定数
DECISION_COMPLETE = "COMPLETE"
DECISION_CONTINUE = "CONTINUE"
DECISION_RETRY_MODIFIED = "RETRY_MODIFIED"
DECISION_SWITCH_PLAN = "SWITCH_PLAN"
DECISION_ESCALATE = "ESCALATE"
DECISION_EMERGENCY_STOP = "EMERGENCY_STOP"
DECISION_SEMANTIC_STOP = "SEMANTIC_STOP"
DECISION_INTERFERENCE_STOP = "INTERFERENCE_STOP"


class StopDecision:
    """停止判断結果"""

    def __init__(
        self,
        decision: str,
        reason: str = "",
        remaining_steps: int = 0,
        fallback_available: bool = False,
    ):
        self.decision = decision
        self.reason = reason
        self.remaining_steps = remaining_steps
        self.fallback_available = fallback_available

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "remaining_steps": self.remaining_steps,
            "fallback_available": self.fallback_available,
        }


class StopDecider:
    """
    停止判断エンジン

    設計書 stop_decision_tree:
    - goal_progress == 1.0 → COMPLETE
    - verify.status == "success" and remaining_steps > 0 → CONTINUE
    - verify.status == "partial" and retry_value == "high" → RETRY_MODIFIED
    - verify.status == "failure" and fallback_available → SWITCH_PLAN
    - verify.status == "failure" and no_fallback → ESCALATE
    - loop_guard_triggered → EMERGENCY_STOP
    - semantic_loop_detected → SEMANTIC_STOP
    - cross_goal_interference_detected → INTERFERENCE_STOP

    連続失敗ルール: 同一タスク（task_type+goal_id）が2回連続失敗 → SWITCH_PLAN
    """

    # 連続失敗の閾値
    CONSECUTIVE_FAILURE_THRESHOLD = 2

    def __init__(self):
        # 連続失敗トラッカー: key = (task_type, goal_id), value = consecutive failure count
        self._consecutive_failures: dict[tuple[str, str], int] = {}

    async def decide(
        self,
        goal_id: str,
        verification_result: dict,
        remaining_task_count: int,
        fallback_plans_remaining: int,
        action_key: str = "",
        action_purpose: str = "",
        action_method: str = "",
        action_result_text: str = "",
        value_justification: str = "タスク実行",
        is_approval_waiting: bool = False,
        task_cost_jpy: float = 0.0,
    ) -> StopDecision:
        """
        停止判断を実行する。

        Args:
            goal_id: ゴールID
            verification_result: 検証結果（VerificationResult.to_dict()）
            remaining_task_count: 残りタスク数
            fallback_plans_remaining: 残りフォールバックプラン数
            action_key: LoopGuard Layer 1用のアクションキー
            action_purpose/method/result_text: Layer 8用
            value_justification: Layer 4用の価値根拠
            is_approval_waiting: Layer 5用
            task_cost_jpy: Layer 6用
        """
        status = verification_result.get("status", "failure")
        goal_progress = verification_result.get("goal_progress", 0.0)
        error_class = verification_result.get("error_class")
        retry_value = verification_result.get("retry_value", "none")

        logger.info(
            f"停止判断: goal_id={goal_id}, status={status}, "
            f"progress={goal_progress:.2f}, remaining={remaining_task_count}"
        )

        # 1. LoopGuard 9層チェック（CLAUDE.md ルール15, 16）
        try:
            lg = get_loop_guard()
            guard_result = await lg.check_all_layers(
                goal_id=goal_id,
                action_key=action_key,
                error_class=error_class,
                value_justification=value_justification,
                is_approval_waiting=is_approval_waiting,
                task_cost_jpy=task_cost_jpy,
                action_purpose=action_purpose,
                action_method=action_method,
                action_result=action_result_text,
            )

            if not guard_result["allowed"]:
                layer = guard_result.get("layer_triggered")
                action = guard_result.get("action", "EMERGENCY_STOP")

                # LoopGuardの結果に基づいて停止判断を返す
                if action in ["EMERGENCY_KILL", "EMERGENCY_STOP"]:
                    decision = DECISION_EMERGENCY_STOP
                elif action == "SEMANTIC_STOP":
                    decision = DECISION_SEMANTIC_STOP
                elif action == "INTERFERENCE_STOP":
                    decision = DECISION_INTERFERENCE_STOP
                elif action == "ESCALATE":
                    decision = DECISION_ESCALATE
                elif action in ["SWITCH_METHOD", "CLUSTER_FREEZE", "CLUSTER_FROZEN"]:
                    decision = DECISION_SWITCH_PLAN if fallback_plans_remaining > 0 else DECISION_ESCALATE
                elif action in ["AUTO_STOP", "TIER_DOWNGRADE"]:
                    decision = DECISION_RETRY_MODIFIED
                elif action == "SKIP":
                    decision = DECISION_CONTINUE
                elif action in ["REMIND_AND_MOVE", "MOVE_TO_ALTERNATIVE"]:
                    decision = DECISION_CONTINUE
                else:
                    decision = DECISION_EMERGENCY_STOP

                logger.warning(
                    f"LoopGuard Layer {layer} 発動: {guard_result['details']} → {decision}"
                )

                # 通知（CLAUDE.md ルール12: Discord + Web UI通知）
                await self._notify_stop(goal_id, decision, guard_result["details"])

                return StopDecision(
                    decision=decision,
                    reason=guard_result["details"],
                    remaining_steps=remaining_task_count,
                    fallback_available=fallback_plans_remaining > 0,
                )

        except Exception as e:
            logger.error(f"LoopGuardチェックエラー（安全側に倒してESCALATE）: {e}")
            # LoopGuardが壊れた場合、安全側に倒す（CLAUDE.md Rule 15/16）
            return StopDecision(
                decision="ESCALATE",
                reason=f"LoopGuardチェック自体がエラー: {e}。安全のためエスカレーション。",
                remaining_steps=remaining_task_count,
                fallback_available=fallback_plans_remaining > 0,
            )

        # 判断根拠トレースの準備（最終的な判断をトレース）
        async def _trace_decision(decision_val, reason_val):
            try:
                await self._record_trace(
                    action=f"decide:{decision_val}",
                    reasoning=f"停止判断: {decision_val}。理由: {reason_val}",
                    confidence=goal_progress,
                    context={"status": status, "goal_progress": goal_progress, "remaining_tasks": remaining_task_count,
                             "fallback_remaining": fallback_plans_remaining, "error_class": error_class},
                    goal_id=goal_id,
                    task_id=action_key or None,
                )
            except Exception:
                pass

        # 1.5. 連続失敗トラッカー: 同一タスクが2回連続失敗 → SWITCH_PLAN
        task_type = verification_result.get("task_type", action_key or "unknown")
        failure_key = (task_type, goal_id)
        if status == "failure":
            self._consecutive_failures[failure_key] = self._consecutive_failures.get(failure_key, 0) + 1
            consec_count = self._consecutive_failures[failure_key]
            if consec_count >= self.CONSECUTIVE_FAILURE_THRESHOLD:
                self._consecutive_failures[failure_key] = 0  # リセット
                decision = DECISION_SWITCH_PLAN if fallback_plans_remaining > 0 else DECISION_ESCALATE
                reason = f"同一タスク({task_type})が{consec_count}回連続失敗。プラン切替を強制"
                logger.warning(f"連続失敗閾値到達: {reason} → {decision}")
                await _trace_decision(decision, reason)
                return StopDecision(
                    decision=decision,
                    reason=reason,
                    remaining_steps=remaining_task_count,
                    fallback_available=fallback_plans_remaining > 0,
                )
        else:
            # 成功/部分成功時はカウンタをリセット
            self._consecutive_failures.pop(failure_key, None)

        # 2. 設計書 stop_decision_tree に基づく判断

        # ゴール完了
        if goal_progress >= 1.0:
            # Tier 1（ABSOLUTE）価値観チェック: 完了前にtaboo違反がないか検証
            output_text = action_result_text or verification_result.get("output_text", "")
            if output_text:
                taboo_block = await self._check_tier1_values(output_text)
                if taboo_block:
                    reason = f"ゴール達成だがtier1価値観違反を検出: {taboo_block}"
                    logger.warning(f"COMPLETE→ESCALATE: {reason}")
                    await _trace_decision(DECISION_ESCALATE, reason)
                    await self._notify_stop(goal_id, DECISION_ESCALATE, reason)
                    return StopDecision(
                        decision=DECISION_ESCALATE,
                        reason=reason,
                        remaining_steps=remaining_task_count,
                        fallback_available=fallback_plans_remaining > 0,
                    )

            await _trace_decision(DECISION_COMPLETE, "ゴール達成（progress=1.0）")
            await self._notify_stop(goal_id, DECISION_COMPLETE, "ゴール達成")
            return StopDecision(
                decision=DECISION_COMPLETE,
                reason="ゴール達成（progress=1.0）",
            )

        # 成功 & 残りステップあり → 続行
        if status == "success" and remaining_task_count > 0:
            return StopDecision(
                decision=DECISION_CONTINUE,
                reason=f"成功・残り{remaining_task_count}タスク",
                remaining_steps=remaining_task_count,
            )

        # 部分成功 & 再試行価値高い → 修正して再試行
        if status == "partial" and retry_value == "high":
            return StopDecision(
                decision=DECISION_RETRY_MODIFIED,
                reason=f"部分成功・再試行価値高 (error={error_class})",
                remaining_steps=remaining_task_count,
                fallback_available=fallback_plans_remaining > 0,
            )

        # 失敗 & フォールバックあり → プラン切替
        if status == "failure" and fallback_plans_remaining > 0:
            return StopDecision(
                decision=DECISION_SWITCH_PLAN,
                reason=f"失敗・フォールバック残り{fallback_plans_remaining}",
                remaining_steps=remaining_task_count,
                fallback_available=True,
            )

        # 失敗 & フォールバックなし → エスカレーション
        if status == "failure":
            await _trace_decision(DECISION_ESCALATE, f"全プラン失敗 (error={error_class})")
            await self._notify_stop(goal_id, DECISION_ESCALATE, f"全プラン失敗 (error={error_class})")
            return StopDecision(
                decision=DECISION_ESCALATE,
                reason=f"全プラン失敗・人間エスカレーション (error={error_class})",
                remaining_steps=remaining_task_count,
                fallback_available=False,
            )

        # デフォルト: 残りタスクがあれば続行
        if remaining_task_count > 0:
            return StopDecision(
                decision=DECISION_CONTINUE,
                reason="デフォルト続行",
                remaining_steps=remaining_task_count,
            )

        await _trace_decision(DECISION_COMPLETE, "全タスク完了")
        return StopDecision(
            decision=DECISION_COMPLETE,
            reason="全タスク完了",
        )

    async def _check_tier1_values(self, output_text: str) -> Optional[str]:
        """
        Tier 1（ABSOLUTE）価値観に違反していないかチェック。
        harness_linterのtabooチェックを利用。
        違反があれば違反理由を返す。なければNone。
        """
        try:
            from tools.harness_linter import get_harness_linter
            linter = get_harness_linter()
            result = await linter._check_taboo(output_text)
            if not result.passed:
                details = "; ".join(v.get("detail", "") for v in result.violations)
                return details[:200]
        except Exception as e:
            logger.warning(f"tier1価値観チェックエラー（安全側でパス）: {e}")
        return None

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "STOP_DECIDER", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def _notify_stop(self, goal_id: str, decision: str, reason: str):
        """停止/完了をNATS + Web UIに通知（CLAUDE.md ルール12）"""
        try:
            nats_client = await get_nats_client()
            severity = "info" if decision == DECISION_COMPLETE else "warning"
            if decision in [DECISION_EMERGENCY_STOP, DECISION_SEMANTIC_STOP, DECISION_INTERFERENCE_STOP]:
                severity = "critical"

            await nats_client.publish(
                f"monitor.alert.{severity}",
                {
                    "goal_id": goal_id,
                    "decision": decision,
                    "reason": reason,
                    "source": "stop_decider",
                },
            )
        except Exception as e:
            logger.warning(f"停止通知失敗: {e}")
