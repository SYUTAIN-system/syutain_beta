"""
SYUTAINβ V25 Emergency Kill（最終防衛線）
設計書 第8章 Layer 7準拠 / CLAUDE.md ルール16

Emergency Kill条件:
- total_step_count >= 50
- total_cost_jpy >= daily_budget * 0.9
- same_error_count >= 5
- time_elapsed_minutes >= 120
- セマンティックループ検知
- Cross-Goal干渉検知
"""

import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.emergency_kill")

# Emergency Kill設定
MAX_STEPS = int(os.getenv("EMERGENCY_KILL_MAX_STEPS", "50"))
BUDGET_KILL_RATIO = float(os.getenv("EMERGENCY_KILL_BUDGET_RATIO", "0.9"))
MAX_SAME_ERROR = int(os.getenv("EMERGENCY_KILL_MAX_SAME_ERROR", "5"))
MAX_ELAPSED_MINUTES = int(os.getenv("EMERGENCY_KILL_MAX_MINUTES", "120"))
DAILY_BUDGET_JPY = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))

# ログファイルパス
KILL_LOG_PATH = Path(os.getenv("EMERGENCY_KILL_LOG", "logs/emergency_kill.log"))


def _ensure_log_dir():
    """ログディレクトリを作成"""
    try:
        KILL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"ログディレクトリ作成失敗: {e}")


def _write_kill_log(reason: str, details: dict):
    """Emergency Killログを書き込む"""
    try:
        _ensure_log_dir()
        timestamp = datetime.now().isoformat()
        entry = (
            f"[{timestamp}] EMERGENCY_KILL\n"
            f"  Reason: {reason}\n"
            f"  Details: {details}\n"
            f"{'=' * 60}\n"
        )
        with open(KILL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.error(f"Emergency Killログ書き込み失敗: {e}")


class EmergencyKill:
    """Emergency Kill（最終防衛線）"""

    def __init__(self):
        self._killed_goals: set[str] = set()  # Kill発動済みゴールID
        self._kill_reasons: dict[str, str] = {}  # goal_id -> reason
        # ゴール別のエラーカウント
        self._error_counts: dict[str, dict[str, int]] = {}  # goal_id -> {error_class: count}

    def check_kill_conditions(
        self,
        goal_id: str,
        step_count: int,
        total_cost_jpy: float,
        start_time: float,
        last_error_class: Optional[str] = None,
        semantic_loop_detected: bool = False,
        cross_goal_interference: bool = False,
    ) -> dict:
        """
        Emergency Kill条件をチェックする。

        Returns:
            {
                "kill": bool,
                "reason": str | None,
                "condition": str | None,
            }
        """
        if goal_id in self._killed_goals:
            return {
                "kill": True,
                "reason": self._kill_reasons.get(goal_id, "already_killed"),
                "condition": "already_killed",
            }

        try:
            # 条件1: 総ステップ数 >= 50
            if step_count >= MAX_STEPS:
                return self._trigger_kill(
                    goal_id,
                    f"総ステップ数上限到達: {step_count} >= {MAX_STEPS}",
                    "step_count_exceeded",
                    {"step_count": step_count, "max_steps": MAX_STEPS},
                )

            # 条件2: 日次予算の90%超過
            budget_limit = DAILY_BUDGET_JPY * BUDGET_KILL_RATIO
            if total_cost_jpy >= budget_limit:
                return self._trigger_kill(
                    goal_id,
                    f"日次予算90%超過: {total_cost_jpy:.0f}円 >= {budget_limit:.0f}円",
                    "budget_exceeded",
                    {"cost_jpy": total_cost_jpy, "budget_limit": budget_limit},
                )

            # 条件3: 同一エラー5回
            if last_error_class:
                if goal_id not in self._error_counts:
                    self._error_counts[goal_id] = {}
                ec = self._error_counts[goal_id]
                ec[last_error_class] = ec.get(last_error_class, 0) + 1

                if ec[last_error_class] >= MAX_SAME_ERROR:
                    return self._trigger_kill(
                        goal_id,
                        f"同一エラー{MAX_SAME_ERROR}回到達: {last_error_class} ({ec[last_error_class]}回)",
                        "same_error_repeated",
                        {"error_class": last_error_class, "count": ec[last_error_class]},
                    )

            # 条件4: 2時間超過
            elapsed_minutes = (time.time() - start_time) / 60
            if elapsed_minutes >= MAX_ELAPSED_MINUTES:
                return self._trigger_kill(
                    goal_id,
                    f"実行時間上限超過: {elapsed_minutes:.1f}分 >= {MAX_ELAPSED_MINUTES}分",
                    "time_exceeded",
                    {"elapsed_minutes": elapsed_minutes, "max_minutes": MAX_ELAPSED_MINUTES},
                )

            # 条件5: セマンティックループ検知（step_count >= 3でのみ発動、1-2ステップは誤検知）
            if semantic_loop_detected and step_count >= 3:
                return self._trigger_kill(
                    goal_id,
                    "セマンティックループ検知による停止",
                    "semantic_loop",
                    {"step_count": step_count},
                )

            # 条件6: Cross-Goal干渉検知
            if cross_goal_interference:
                return self._trigger_kill(
                    goal_id,
                    "Cross-Goal干渉検知による停止",
                    "cross_goal_interference",
                    {},
                )

            return {
                "kill": False,
                "reason": None,
                "condition": None,
            }

        except Exception as e:
            logger.error(f"Emergency Kill条件チェックエラー: {e}")
            # エラー時は安全側（Kill発動）にはしない
            return {
                "kill": False,
                "reason": None,
                "condition": None,
            }

    def _trigger_kill(self, goal_id: str, reason: str, condition: str, details: dict) -> dict:
        """Killを発動し、ログに記録（ゴール単位）"""
        self._killed_goals.add(goal_id)
        self._kill_reasons[goal_id] = reason

        full_details = {
            "goal_id": goal_id,
            "condition": condition,
            **details,
        }
        logger.critical(f"EMERGENCY KILL発動: {reason}")
        _write_kill_log(reason, full_details)

        return {
            "kill": True,
            "reason": reason,
            "condition": condition,
        }

    def record_error(self, goal_id: str, error_class: str):
        """エラーを記録（check_kill_conditions外で使う場合）"""
        if goal_id not in self._error_counts:
            self._error_counts[goal_id] = {}
        ec = self._error_counts[goal_id]
        ec[error_class] = ec.get(error_class, 0) + 1

    def get_error_count(self, goal_id: str, error_class: str) -> int:
        """特定ゴール・エラークラスのエラー回数を取得"""
        return self._error_counts.get(goal_id, {}).get(error_class, 0)

    def reset_goal(self, goal_id: str):
        """ゴール完了時にエラーカウントとKillフラグをリセット"""
        self._error_counts.pop(goal_id, None)
        self._killed_goals.discard(goal_id)
        self._kill_reasons.pop(goal_id, None)

    def reset(self):
        """全状態をリセット"""
        self._killed_goals.clear()
        self._kill_reasons.clear()
        self._error_counts.clear()

    @property
    def is_killed(self) -> bool:
        return len(self._killed_goals) > 0

    @property
    def kill_reason(self) -> Optional[str]:
        if self._kill_reasons:
            return next(iter(self._kill_reasons.values()))
        return None

    def is_goal_killed(self, goal_id: str) -> bool:
        """特定ゴールがKill済みか"""
        return goal_id in self._killed_goals


# シングルトン
_instance: Optional[EmergencyKill] = None


def get_emergency_kill() -> EmergencyKill:
    """EmergencyKillのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = EmergencyKill()
    return _instance
