"""
SYUTAINβ V25 Cross-Goal干渉検知（Layer 9）
設計書 第8章 8.9準拠

複数のGoal Packetが同時進行している場合に、
あるゴールの行動が別のゴールを妨害していないかを検知する。
V25新規機能。
"""

import os
import time
import logging
from datetime import datetime
from typing import Optional

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.cross_goal_detector")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# 干渉検知ルール閾値
API_CONCURRENT_REQUEST_LIMIT = 10       # 同一APIへの同時リクエスト上限
NODE_RESOURCE_THRESHOLD_PCT = 90        # ノードCPU/GPU使用率閾値
BUDGET_DOMINANCE_THRESHOLD_PCT = 60     # 1ゴールの日次予算占有率閾値


class CrossGoalDetector:
    """V25 Cross-Goal干渉検知エンジン"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        # アクティブゴールのリソース使用状況をインメモリ追跡
        self._goal_resources: dict[str, dict] = {}
        # goal_id -> { api_calls: {api: count}, nodes_used: {node: cpu_pct}, budget_used_jpy: float, actions: [str] }
        # api_callsカウンターの時間ベースリセット（1時間ごと）
        self._last_reset_time: float = time.monotonic()
        self._RESET_INTERVAL_SEC: float = 3600.0  # 1時間

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        """PostgreSQL接続プールを取得"""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    def register_goal(self, goal_id: str):
        """アクティブゴールを登録"""
        if goal_id not in self._goal_resources:
            self._goal_resources[goal_id] = {
                "api_calls": {},
                "nodes_used": {},
                "budget_used_jpy": 0.0,
                "actions": [],
                "priority": 0,
                "revenue_contribution": 0.0,
                "deadline": None,
                "created_at": datetime.now(),
            }

    def unregister_goal(self, goal_id: str):
        """ゴール完了時に登録解除"""
        self._goal_resources.pop(goal_id, None)

    def _maybe_reset_counters(self):
        """1時間以上経過していたらapi_callsカウンターをリセット"""
        now = time.monotonic()
        if now - self._last_reset_time >= self._RESET_INTERVAL_SEC:
            for res in self._goal_resources.values():
                res["api_calls"] = {}
            self._last_reset_time = now
            logger.debug("api_callsカウンターを時間ベースでリセット")

    def record_api_call(self, goal_id: str, api_name: str):
        """APIコールを記録"""
        self._maybe_reset_counters()
        if goal_id not in self._goal_resources:
            self.register_goal(goal_id)
        calls = self._goal_resources[goal_id]["api_calls"]
        calls[api_name] = calls.get(api_name, 0) + 1

    def record_node_usage(self, goal_id: str, node: str, cpu_pct: float):
        """ノード使用率を記録"""
        if goal_id not in self._goal_resources:
            self.register_goal(goal_id)
        self._goal_resources[goal_id]["nodes_used"][node] = cpu_pct

    def record_budget_spend(self, goal_id: str, amount_jpy: float):
        """予算消費を記録"""
        if goal_id not in self._goal_resources:
            self.register_goal(goal_id)
        self._goal_resources[goal_id]["budget_used_jpy"] += amount_jpy

    def record_action(self, goal_id: str, action_desc: str):
        """アクションを記録（矛盾検知用）"""
        if goal_id not in self._goal_resources:
            self.register_goal(goal_id)
        actions = self._goal_resources[goal_id]["actions"]
        actions.append(action_desc)
        # 直近50件のみ保持
        if len(actions) > 50:
            self._goal_resources[goal_id]["actions"] = actions[-50:]

    def set_goal_priority(self, goal_id: str, revenue_contribution: float = 0.0,
                          deadline: Optional[datetime] = None, priority: int = 0):
        """ゴールの優先度情報を設定"""
        if goal_id not in self._goal_resources:
            self.register_goal(goal_id)
        res = self._goal_resources[goal_id]
        res["revenue_contribution"] = revenue_contribution
        res["deadline"] = deadline
        res["priority"] = priority

    async def check_interference(self, daily_budget_jpy: float = 1000.0) -> dict:
        """
        Cross-Goal干渉を検知する。

        設計書の検知ルール:
        1. 同一APIへの同時大量リクエスト（rate limit競合）
        2. 同一ノードの計算リソース占有（GPU/CPU 90%超）
        3. 矛盾するアクション
        4. 予算の奪い合い（1ゴールが日次予算の60%以上を消費）

        Returns:
            {
                "detected": bool,
                "interference_type": str | None,
                "conflicting_goals": list[str],
                "details": str,
                "action": str,
                "goal_to_pause": str | None,
            }
        """
        try:
            active_goals = list(self._goal_resources.keys())

            # 2つ以上のGoal Packetが同時進行していない場合はチェック不要
            if len(active_goals) < 2:
                return {
                    "detected": False,
                    "interference_type": None,
                    "conflicting_goals": [],
                    "details": "同時進行ゴールが2未満",
                    "action": "none",
                    "goal_to_pause": None,
                }

            # ルール1: API rate limit競合
            api_conflict = self._check_api_rate_limit_conflict()
            if api_conflict["detected"]:
                return api_conflict

            # ルール2: ノードリソース占有
            node_conflict = self._check_node_resource_conflict()
            if node_conflict["detected"]:
                return node_conflict

            # ルール4: 予算奪い合い（ルール3より先にチェック: 定量的に判定しやすい）
            budget_conflict = self._check_budget_dominance(daily_budget_jpy)
            if budget_conflict["detected"]:
                return budget_conflict

            # ルール3: 矛盾するアクション
            action_conflict = self._check_contradictory_actions()
            if action_conflict["detected"]:
                return action_conflict

            return {
                "detected": False,
                "interference_type": None,
                "conflicting_goals": [],
                "details": "干渉未検知",
                "action": "none",
                "goal_to_pause": None,
            }

        except Exception as e:
            logger.error(f"Cross-Goal干渉検知エラー: {e}")
            return {
                "detected": False,
                "interference_type": None,
                "conflicting_goals": [],
                "details": f"検知エラー: {e}",
                "action": "none",
                "goal_to_pause": None,
            }

    def _check_api_rate_limit_conflict(self) -> dict:
        """同一APIへの同時大量リクエスト検知"""
        # API別の合計リクエスト数を集計
        api_totals: dict[str, list[tuple[str, int]]] = {}
        for goal_id, res in self._goal_resources.items():
            for api, count in res["api_calls"].items():
                if api not in api_totals:
                    api_totals[api] = []
                api_totals[api].append((goal_id, count))

        for api, goals_counts in api_totals.items():
            total = sum(c for _, c in goals_counts)
            if total >= API_CONCURRENT_REQUEST_LIMIT and len(goals_counts) >= 2:
                conflicting = [g for g, _ in goals_counts]
                goal_to_pause = self._resolve_priority(conflicting)
                return {
                    "detected": True,
                    "interference_type": "api_rate_limit_conflict",
                    "conflicting_goals": conflicting,
                    "details": f"API '{api}'への合計リクエスト{total}回（上限{API_CONCURRENT_REQUEST_LIMIT}）",
                    "action": "INTERFERENCE_STOP",
                    "goal_to_pause": goal_to_pause,
                }
        return {"detected": False}

    def _check_node_resource_conflict(self) -> dict:
        """同一ノードの計算リソース占有検知"""
        # ノード別にゴールの使用率を合算
        node_usage: dict[str, list[tuple[str, float]]] = {}
        for goal_id, res in self._goal_resources.items():
            for node, cpu_pct in res["nodes_used"].items():
                if node not in node_usage:
                    node_usage[node] = []
                node_usage[node].append((goal_id, cpu_pct))

        for node, goals_usage in node_usage.items():
            total_pct = sum(u for _, u in goals_usage)
            if total_pct >= NODE_RESOURCE_THRESHOLD_PCT and len(goals_usage) >= 2:
                conflicting = [g for g, _ in goals_usage]
                goal_to_pause = self._resolve_priority(conflicting)
                return {
                    "detected": True,
                    "interference_type": "node_resource_conflict",
                    "conflicting_goals": conflicting,
                    "details": f"ノード'{node}'のリソース使用率合計{total_pct:.1f}%（閾値{NODE_RESOURCE_THRESHOLD_PCT}%）",
                    "action": "INTERFERENCE_STOP",
                    "goal_to_pause": goal_to_pause,
                }
        return {"detected": False}

    def _check_budget_dominance(self, daily_budget_jpy: float) -> dict:
        """1ゴールが日次予算の60%以上を消費していないか"""
        if daily_budget_jpy <= 0:
            return {"detected": False}

        for goal_id, res in self._goal_resources.items():
            ratio = res["budget_used_jpy"] / daily_budget_jpy * 100
            if ratio >= BUDGET_DOMINANCE_THRESHOLD_PCT:
                other_goals = [g for g in self._goal_resources if g != goal_id]
                if other_goals:
                    return {
                        "detected": True,
                        "interference_type": "budget_dominance",
                        "conflicting_goals": [goal_id] + other_goals,
                        "details": f"ゴール'{goal_id}'が日次予算の{ratio:.1f}%を消費（閾値{BUDGET_DOMINANCE_THRESHOLD_PCT}%）",
                        "action": "INTERFERENCE_STOP",
                        "goal_to_pause": goal_id,
                    }
        return {"detected": False}

    def _check_contradictory_actions(self) -> dict:
        """矛盾するアクションの検知（簡易版: 同一アカウント・同一リソースへの矛盾操作）"""
        # 各ゴールの直近アクションからキーワードを抽出して矛盾を検出
        contradictions = {
            # (action_keyword_a, action_keyword_b) → 矛盾ペア
            ("投稿", "削除"): "同一対象への投稿と削除",
            ("値上げ", "値下げ"): "同一商品の価格変更が矛盾",
            ("有効化", "無効化"): "同一設定の有効化と無効化",
            ("publish", "unpublish"): "同一コンテンツの公開と非公開",
        }

        goal_ids = list(self._goal_resources.keys())
        for i in range(len(goal_ids)):
            for j in range(i + 1, len(goal_ids)):
                actions_a = " ".join(self._goal_resources[goal_ids[i]]["actions"][-10:])
                actions_b = " ".join(self._goal_resources[goal_ids[j]]["actions"][-10:])

                for (kw_a, kw_b), desc in contradictions.items():
                    if (kw_a in actions_a and kw_b in actions_b) or \
                       (kw_b in actions_a and kw_a in actions_b):
                        conflicting = [goal_ids[i], goal_ids[j]]
                        goal_to_pause = self._resolve_priority(conflicting)
                        return {
                            "detected": True,
                            "interference_type": "contradictory_actions",
                            "conflicting_goals": conflicting,
                            "details": f"矛盾アクション検知: {desc}",
                            "action": "INTERFERENCE_STOP",
                            "goal_to_pause": goal_to_pause,
                        }
        return {"detected": False}

    def _resolve_priority(self, goal_ids: list[str]) -> Optional[str]:
        """
        優先度解決: 設計書の priority_resolution に準拠
        revenue_contribution > deadline_proximity > creation_order
        優先度が低いゴールを一時停止対象として返す。
        """
        if not goal_ids:
            return None

        def sort_key(gid: str):
            res = self._goal_resources.get(gid, {})
            rev = res.get("revenue_contribution", 0.0)
            dl = res.get("deadline")
            # deadline が近いほど優先度が高い（Noneは最低優先）
            if dl:
                dl_seconds = (dl - datetime.now()).total_seconds()
            else:
                dl_seconds = float("inf")
            created = res.get("created_at", datetime.now())
            return (-rev, dl_seconds, created)

        # ソート: 優先度が高い順
        sorted_goals = sorted(goal_ids, key=sort_key)
        # 最後のゴール（最低優先度）を停止対象とする
        return sorted_goals[-1] if len(sorted_goals) > 1 else None

    async def close(self):
        """接続プールを閉じる"""
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")


# シングルトン
_instance: Optional[CrossGoalDetector] = None


def get_cross_goal_detector() -> CrossGoalDetector:
    """CrossGoalDetectorのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = CrossGoalDetector()
    return _instance
