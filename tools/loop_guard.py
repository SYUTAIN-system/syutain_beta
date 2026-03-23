"""
SYUTAINβ V25 9層ループ防止（LoopGuard）
設計書 第8章準拠 / CLAUDE.md ルール15, 16

9層構成:
  Layer 1: Retry Budget（同一アクション再試行2回まで）
  Layer 2: Same-Failure Cluster（同型失敗2回でクラスタ凍結）
  Layer 3: Planner Reset Limit（再計画3回まで）
  Layer 4: Value Guard（価値のない再試行禁止）
  Layer 5: Approval Deadlock Guard（承認待ちデッドロック防止）
  Layer 6: Cost & Time Guard（コスト80%/時間60分/トークン10万）
  Layer 7: Emergency Kill（50ステップ/予算90%/エラー5回/2時間）
  Layer 8: Semantic Loop Detection（意味的ループ検知）
  Layer 9: Cross-Goal Interference Detection（V25新規）
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from tools.semantic_loop_detector import get_semantic_loop_detector
from tools.cross_goal_detector import get_cross_goal_detector
from tools.emergency_kill import get_emergency_kill
from tools.budget_guard import get_budget_guard

load_dotenv()

logger = logging.getLogger("syutain.loop_guard")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# Layer 1: Retry Budget
MAX_RETRIES_PER_ACTION = 2
# Layer 2: Same-Failure Cluster
MAX_SAME_FAILURE_CLUSTER = 2
CLUSTER_FREEZE_SECONDS = 1800  # 30分
# Layer 3: Planner Reset Limit
MAX_REPLANS = 3
# Layer 5: Approval Deadlock
APPROVAL_DEADLOCK_HOURS = 24
# Layer 6: Cost & Time Guard
COST_WARN_RATIO = 0.8  # 日次予算の80%
TIME_LIMIT_PER_TASK_MINUTES = 60
TOKEN_LIMIT_PER_CALL = 100000


class LoopGuardState:
    """1ゴール分のループガード状態"""

    def __init__(self, goal_id: str):
        self.goal_id = goal_id
        self.start_time = time.time()
        self.step_count = 0
        self.total_cost_jpy = 0.0
        self.replan_count = 0
        # action_key -> retry count
        self.retry_counts: dict[str, int] = {}
        # error_cluster -> { count, frozen_until }
        self.failure_clusters: dict[str, dict] = {}
        # 承認待ち開始時刻
        self.approval_wait_start: Optional[float] = None
        self.approval_reminded = False


class LoopGuard:
    """9層ループ防止壁"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._states: dict[str, LoopGuardState] = {}

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    def get_or_create_state(self, goal_id: str) -> LoopGuardState:
        """ゴール用の状態を取得 or 新規作成"""
        if goal_id not in self._states:
            self._states[goal_id] = LoopGuardState(goal_id)
        return self._states[goal_id]

    async def check_all_layers(
        self,
        goal_id: str,
        action_key: str = "",
        error_class: Optional[str] = None,
        value_justification: str = "",
        is_approval_waiting: bool = False,
        task_cost_jpy: float = 0.0,
        token_count: int = 0,
        action_purpose: str = "",
        action_method: str = "",
        action_result: str = "",
    ) -> dict:
        """
        全9層のチェックを実行する。

        Returns:
            {
                "allowed": bool,
                "layer_triggered": int | None (1-9),
                "layer_name": str | None,
                "action": str,
                "details": str,
            }
        """
        state = self.get_or_create_state(goal_id)
        state.step_count += 1
        state.total_cost_jpy += task_cost_jpy

        # Layer 1: Step Count Guard / Retry Budget
        result = self._check_layer1(state, action_key)
        if not result["allowed"]:
            await self._log_event(goal_id, 1, "retry_budget", result["details"], result["action"], state)
            return result

        # Layer 2: Same-Failure Cluster
        if error_class:
            result = self._check_layer2(state, error_class)
            if not result["allowed"]:
                await self._log_event(goal_id, 2, "same_failure_cluster", result["details"], result["action"], state)
                return result

        # Layer 3: Planner Reset Limit
        # (再計画時のみ呼ばれる想定だが、ここではreplan_countベースで判定)
        result = self._check_layer3(state)
        if not result["allowed"]:
            await self._log_event(goal_id, 3, "planner_reset_limit", result["details"], result["action"], state)
            return result

        # Layer 4: Value Guard
        result = self._check_layer4(value_justification)
        if not result["allowed"]:
            await self._log_event(goal_id, 4, "value_guard", result["details"], result["action"], state)
            return result

        # Layer 5: Approval Deadlock Guard
        result = self._check_layer5(state, is_approval_waiting)
        if not result["allowed"]:
            await self._log_event(goal_id, 5, "approval_deadlock", result["details"], result["action"], state)
            return result

        # Layer 6: Cost & Time Guard
        result = self._check_layer6(state, task_cost_jpy, token_count)
        if not result["allowed"]:
            await self._log_event(goal_id, 6, "cost_time_guard", result["details"], result["action"], state)
            return result

        # Layer 7: Emergency Kill
        result = await self._check_layer7(state, error_class)
        if not result["allowed"]:
            await self._log_event(goal_id, 7, "emergency_kill", result["details"], result["action"], state)
            return result

        # Layer 8: Semantic Loop Detection
        if action_purpose or action_method or action_result:
            result = self._check_layer8(action_purpose, action_method, action_result)
            if not result["allowed"]:
                await self._log_event(goal_id, 8, "semantic_loop", result["details"], result["action"], state)
                return result

        # Layer 9: Cross-Goal Interference Detection
        result = await self._check_layer9(goal_id)
        if not result["allowed"]:
            await self._log_event(goal_id, 9, "cross_goal_interference", result["details"], result["action"], state)
            return result

        return {
            "allowed": True,
            "layer_triggered": None,
            "layer_name": None,
            "action": "CONTINUE",
            "details": f"全9層通過 (step={state.step_count})",
        }

    # ===== 各Layer実装 =====

    def _check_layer1(self, state: LoopGuardState, action_key: str) -> dict:
        """Layer 1: Retry Budget（同一アクション再試行2回まで）/ Step Count"""
        # 総ステップ数チェック（Layer 7の前段チェック）
        if state.step_count > MAX_RETRIES_PER_ACTION * 25:
            # 早期警告用の軽量チェック
            pass

        if action_key:
            count = state.retry_counts.get(action_key, 0) + 1
            state.retry_counts[action_key] = count
            if count > MAX_RETRIES_PER_ACTION:
                return {
                    "allowed": False,
                    "layer_triggered": 1,
                    "layer_name": "retry_budget",
                    "action": "SWITCH_METHOD",
                    "details": f"同一アクション'{action_key}'の再試行{count}回目（上限{MAX_RETRIES_PER_ACTION}回）→別方式へ切替",
                }
        return {"allowed": True}

    def _check_layer2(self, state: LoopGuardState, error_class: str) -> dict:
        """Layer 2: Same-Failure Cluster（同型失敗2回でクラスタ凍結30分）"""
        now = time.time()
        cluster = state.failure_clusters.get(error_class, {"count": 0, "frozen_until": 0})

        # 凍結中チェック
        if cluster.get("frozen_until", 0) > now:
            remaining = int(cluster["frozen_until"] - now)
            return {
                "allowed": False,
                "layer_triggered": 2,
                "layer_name": "same_failure_cluster",
                "action": "CLUSTER_FROZEN",
                "details": f"エラークラスタ'{error_class}'は凍結中（残り{remaining}秒）→別手段を使用",
            }

        cluster["count"] = cluster.get("count", 0) + 1
        if cluster["count"] >= MAX_SAME_FAILURE_CLUSTER:
            cluster["frozen_until"] = now + CLUSTER_FREEZE_SECONDS
            cluster["count"] = 0
            state.failure_clusters[error_class] = cluster
            return {
                "allowed": False,
                "layer_triggered": 2,
                "layer_name": "same_failure_cluster",
                "action": "CLUSTER_FREEZE",
                "details": f"エラークラスタ'{error_class}'で{MAX_SAME_FAILURE_CLUSTER}回失敗→30分間凍結",
            }

        state.failure_clusters[error_class] = cluster
        return {"allowed": True}

    def _check_layer3(self, state: LoopGuardState) -> dict:
        """Layer 3: Planner Reset Limit（再計画3回まで）"""
        if state.replan_count > MAX_REPLANS:
            return {
                "allowed": False,
                "layer_triggered": 3,
                "layer_name": "planner_reset_limit",
                "action": "ESCALATE",
                "details": f"再計画{state.replan_count}回（上限{MAX_REPLANS}回）→人間エスカレーション",
            }
        return {"allowed": True}

    def _check_layer4(self, value_justification: str) -> dict:
        """Layer 4: Value Guard（価値のない再試行禁止）"""
        if not value_justification or value_justification.strip() == "":
            return {
                "allowed": False,
                "layer_triggered": 4,
                "layer_name": "value_guard",
                "action": "SKIP",
                "details": "この行動の価値根拠（value_justification）が未宣言→SKIP",
            }
        return {"allowed": True}

    def _check_layer5(self, state: LoopGuardState, is_approval_waiting: bool) -> dict:
        """Layer 5: Approval Deadlock Guard"""
        now = time.time()
        if is_approval_waiting:
            if state.approval_wait_start is None:
                state.approval_wait_start = now
            wait_hours = (now - state.approval_wait_start) / 3600

            if wait_hours >= APPROVAL_DEADLOCK_HOURS:
                if not state.approval_reminded:
                    state.approval_reminded = True
                    return {
                        "allowed": False,
                        "layer_triggered": 5,
                        "layer_name": "approval_deadlock",
                        "action": "REMIND_AND_MOVE",
                        "details": f"承認待ち{wait_hours:.1f}時間→リマインド通知送信＆代替タスクへ移行",
                    }
                else:
                    return {
                        "allowed": False,
                        "layer_triggered": 5,
                        "layer_name": "approval_deadlock",
                        "action": "MOVE_TO_ALTERNATIVE",
                        "details": f"承認待ち{wait_hours:.1f}時間（リマインド済み）→代替タスクへ移行",
                    }
        else:
            state.approval_wait_start = None
            state.approval_reminded = False
        return {"allowed": True}

    def _check_layer6(self, state: LoopGuardState, task_cost_jpy: float, token_count: int) -> dict:
        """Layer 6: Cost & Time Guard"""
        daily_budget = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))

        # コスト閾値: 日次予算の80%
        cost_limit = daily_budget * COST_WARN_RATIO
        if state.total_cost_jpy >= cost_limit:
            return {
                "allowed": False,
                "layer_triggered": 6,
                "layer_name": "cost_time_guard",
                "action": "AUTO_STOP",
                "details": f"コスト閾値超過: {state.total_cost_jpy:.0f}円 >= {cost_limit:.0f}円（日次予算の80%）",
            }

        # 時間閾値: 1タスクに60分超
        elapsed_min = (time.time() - state.start_time) / 60
        if elapsed_min >= TIME_LIMIT_PER_TASK_MINUTES:
            return {
                "allowed": False,
                "layer_triggered": 6,
                "layer_name": "cost_time_guard",
                "action": "AUTO_STOP",
                "details": f"時間閾値超過: {elapsed_min:.1f}分 >= {TIME_LIMIT_PER_TASK_MINUTES}分",
            }

        # トークン閾値: 1回の推論で10万トークン超 → Tier降格
        if token_count > TOKEN_LIMIT_PER_CALL:
            return {
                "allowed": False,
                "layer_triggered": 6,
                "layer_name": "cost_time_guard",
                "action": "TIER_DOWNGRADE",
                "details": f"トークン閾値超過: {token_count} > {TOKEN_LIMIT_PER_CALL}→Tier降格",
            }

        return {"allowed": True}

    async def _check_layer7(self, state: LoopGuardState, error_class: Optional[str]) -> dict:
        """Layer 7: Emergency Kill"""
        ek = get_emergency_kill()
        semantic_det = get_semantic_loop_detector()
        semantic_check = semantic_det.check_semantic_loop()

        result = ek.check_kill_conditions(
            goal_id=state.goal_id,
            step_count=state.step_count,
            total_cost_jpy=state.total_cost_jpy,
            start_time=state.start_time,
            last_error_class=error_class,
            semantic_loop_detected=semantic_check.get("detected", False),
            cross_goal_interference=False,  # Layer 9で別途チェック
        )
        if result["kill"]:
            return {
                "allowed": False,
                "layer_triggered": 7,
                "layer_name": "emergency_kill",
                "action": "EMERGENCY_KILL",
                "details": result["reason"],
            }
        return {"allowed": True}

    def _check_layer8(self, purpose: str, method: str, result: str) -> dict:
        """Layer 8: Semantic Loop Detection"""
        detector = get_semantic_loop_detector()
        detector.record_action(purpose, method, result)
        check = detector.check_semantic_loop()

        if check["detected"]:
            return {
                "allowed": False,
                "layer_triggered": 8,
                "layer_name": "semantic_loop",
                "action": "SEMANTIC_STOP",
                "details": check["details"],
            }
        return {"allowed": True}

    async def _check_layer9(self, goal_id: str) -> dict:
        """Layer 9: Cross-Goal Interference Detection（V25新規）"""
        detector = get_cross_goal_detector()
        daily_budget = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))
        check = await detector.check_interference(daily_budget_jpy=daily_budget)

        if check["detected"]:
            return {
                "allowed": False,
                "layer_triggered": 9,
                "layer_name": "cross_goal_interference",
                "action": "INTERFERENCE_STOP",
                "details": check["details"],
            }
        return {"allowed": True}

    def increment_replan(self, goal_id: str):
        """再計画カウントをインクリメント"""
        state = self.get_or_create_state(goal_id)
        state.replan_count += 1

    def reset_goal(self, goal_id: str):
        """ゴール完了時に状態をクリア"""
        self._states.pop(goal_id, None)

    async def _log_event(
        self,
        goal_id: str,
        layer: int,
        layer_name: str,
        details: str,
        action: str,
        state: LoopGuardState,
    ):
        """ループガードイベントをPostgreSQLに記録"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO loop_guard_events
                            (goal_id, layer_triggered, layer_name, trigger_reason, action_taken,
                             step_count_at_trigger, cost_at_trigger_jpy)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        goal_id, layer, layer_name, details, action,
                        state.step_count, state.total_cost_jpy,
                    )
        except Exception as e:
            logger.error(f"ループガードイベントDB記録失敗: {e}")

    async def close(self):
        """接続プールを閉じる"""
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")


# シングルトン
_instance: Optional[LoopGuard] = None


def get_loop_guard() -> LoopGuard:
    """LoopGuardのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = LoopGuard()
    return _instance
