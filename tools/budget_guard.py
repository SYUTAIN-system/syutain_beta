"""
SYUTAINβ V25 予算ガード（Budget Guard）
設計書 第8章 Layer 6準拠

日次/月次のAPI支出を追跡し、閾値でアラートを発行する。
予算設定は .env から読み込み、ハードコードしない（CLAUDE.md ルール9）。
"""

import os
import time
import asyncio
import logging
from datetime import datetime, date
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.budget_guard")

# ===== 予算設定（.envから読み込み）=====
DAILY_BUDGET_JPY = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "120")))
MONTHLY_BUDGET_JPY = float(os.getenv("MONTHLY_BUDGET_JPY", os.getenv("MONTHLY_API_BUDGET_JPY", "2000")))
MONTHLY_INFO_BUDGET_JPY = float(os.getenv("MONTHLY_INFO_BUDGET_JPY", "15000"))

# アラート閾値
ALERT_THRESHOLD_WARN = float(os.getenv("BUDGET_ALERT_WARN", "0.8"))    # 80%で警告
ALERT_THRESHOLD_STOP = float(os.getenv("BUDGET_ALERT_STOP", "0.9"))    # 90%で停止（Emergency Kill条件）
SINGLE_CALL_LIMIT_JPY = float(os.getenv("SINGLE_CALL_LIMIT_JPY", "500"))  # 1回の呼び出し上限



class BudgetGuard:
    """日次/月次API支出の追跡・アラート"""

    def __init__(self):
        # インメモリ集計（DB接続不可時のフォールバック）
        self._daily_spend_jpy: float = 0.0
        self._monthly_spend_jpy: float = 0.0
        self._info_spend_jpy: float = 0.0
        self._chat_spend_jpy: float = 0.0  # チャット経由のAPI支出
        self._current_date: date = date.today()
        self._current_month: int = date.today().month
        self._initialized_from_db: bool = False
        self._warn_logged_today: bool = False

    async def _load_from_db(self):
        """起動時にDB（llm_cost_log）から当日/当月の支出を復元"""
        if self._initialized_from_db:
            return
        self._initialized_from_db = True
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # 当日の支出合計
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_jpy), 0) AS total FROM llm_cost_log WHERE recorded_at::date = CURRENT_DATE"
                )
                if row:
                    self._daily_spend_jpy = float(row["total"])
                # 当月の支出合計
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_jpy), 0) AS total FROM llm_cost_log WHERE date_trunc('month', recorded_at) = date_trunc('month', CURRENT_DATE)"
                )
                if row:
                    self._monthly_spend_jpy = float(row["total"])
                # 情報収集支出（is_info=trueのもの）
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_jpy), 0) AS total FROM llm_cost_log WHERE date_trunc('month', recorded_at) = date_trunc('month', CURRENT_DATE) AND is_info = true"
                )
                if row:
                    self._info_spend_jpy = float(row["total"])
                # チャット支出（goal_id='chat'のもの）
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(amount_jpy), 0) AS total FROM llm_cost_log WHERE recorded_at::date = CURRENT_DATE AND goal_id = 'chat'"
                )
                if row:
                    self._chat_spend_jpy = float(row["total"])
                logger.info(f"DB復元: 日次¥{self._daily_spend_jpy:.1f}, 月次¥{self._monthly_spend_jpy:.1f}, 情報¥{self._info_spend_jpy:.1f}, チャット¥{self._chat_spend_jpy:.1f}")
        except Exception as e:
            logger.warning(f"DB復元失敗（インメモリで継続）: {e}")

    async def _reset_if_new_day(self):
        """日付が変わったら日次集計をリセット"""
        today = date.today()
        if today != self._current_date:
            self._daily_spend_jpy = 0.0
            self._chat_spend_jpy = 0.0
            self._warn_logged_today = False
            self._current_date = today
            logger.info(f"日次予算リセット: {today}")
        if today.month != self._current_month:
            self._monthly_spend_jpy = 0.0
            self._info_spend_jpy = 0.0
            self._current_month = today.month
            logger.info(f"月次予算リセット: {today.month}月")

    async def record_spend(
        self,
        amount_jpy: float,
        model: str,
        tier: str,
        is_info_collection: bool = False,
        goal_id: str = "",
    ) -> dict:
        """
        API支出を記録し、予算状態を返す。

        Returns:
            {
                "allowed": bool,
                "daily_remaining_jpy": float,
                "monthly_remaining_jpy": float,
                "alert_level": "ok" | "warn" | "stop",
                "message": str,
            }
        """
        await self._reset_if_new_day()

        # 1回の呼び出し上限チェック
        if amount_jpy > SINGLE_CALL_LIMIT_JPY:
            logger.warning(f"単一呼び出し上限超過: {amount_jpy}円 > {SINGLE_CALL_LIMIT_JPY}円 ({model})")
            return {
                "allowed": False,
                "daily_remaining_jpy": DAILY_BUDGET_JPY - self._daily_spend_jpy,
                "monthly_remaining_jpy": MONTHLY_BUDGET_JPY - self._monthly_spend_jpy,
                "alert_level": "stop",
                "message": f"単一呼び出し上限超過: {amount_jpy}円 > {SINGLE_CALL_LIMIT_JPY}円",
            }

        # 予算超過チェック（加算前に判定）
        projected_daily = self._daily_spend_jpy + amount_jpy
        projected_monthly = self._monthly_spend_jpy + amount_jpy
        daily_ratio = projected_daily / DAILY_BUDGET_JPY if DAILY_BUDGET_JPY > 0 else 0
        monthly_ratio = projected_monthly / MONTHLY_BUDGET_JPY if MONTHLY_BUDGET_JPY > 0 else 0
        max_ratio = max(daily_ratio, monthly_ratio)

        if max_ratio >= ALERT_THRESHOLD_STOP:
            msg = f"予算90%超過 - 即時停止: 日次{projected_daily:.0f}/{DAILY_BUDGET_JPY:.0f}円, 月次{projected_monthly:.0f}/{MONTHLY_BUDGET_JPY:.0f}円"
            logger.critical(msg)
            return {
                "allowed": False,
                "daily_remaining_jpy": max(0, DAILY_BUDGET_JPY - self._daily_spend_jpy),
                "monthly_remaining_jpy": max(0, MONTHLY_BUDGET_JPY - self._monthly_spend_jpy),
                "alert_level": "stop",
                "message": msg,
            }

        # インメモリ集計更新（予算範囲内の場合のみ加算）
        self._daily_spend_jpy += amount_jpy
        self._monthly_spend_jpy += amount_jpy
        if is_info_collection:
            self._info_spend_jpy += amount_jpy

        # DB記録（失敗しても処理は続行）
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO llm_cost_log (model, tier, amount_jpy, goal_id, is_info, recorded_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    model, tier, amount_jpy, goal_id, is_info_collection,
                )
        except Exception as e:
            # テーブルが存在しない場合もあるため警告のみ
            logger.warning(f"予算記録DB保存失敗（インメモリで継続）: {e}")

        # アラートレベル判定（stop は加算前にチェック済みなのでここでは warn/ok のみ）
        daily_ratio = self._daily_spend_jpy / DAILY_BUDGET_JPY if DAILY_BUDGET_JPY > 0 else 0
        monthly_ratio = self._monthly_spend_jpy / MONTHLY_BUDGET_JPY if MONTHLY_BUDGET_JPY > 0 else 0
        max_ratio = max(daily_ratio, monthly_ratio)

        if max_ratio >= ALERT_THRESHOLD_WARN:
            alert_level = "warn"
            msg = f"予算80%警告: 日次{self._daily_spend_jpy:.0f}/{DAILY_BUDGET_JPY:.0f}円, 月次{self._monthly_spend_jpy:.0f}/{MONTHLY_BUDGET_JPY:.0f}円"
            # 同じ警告を繰り返さない（1日1回のみlogger.warning）
            if not getattr(self, '_warn_logged_today', False):
                logger.warning(msg)
                self._warn_logged_today = True
            else:
                logger.debug(msg)
        else:
            alert_level = "ok"
            msg = f"予算正常: 日次{self._daily_spend_jpy:.0f}/{DAILY_BUDGET_JPY:.0f}円"

        # コスト異常エスカレーション: 24hコスト > 7日平均 * 2
        try:
            if alert_level in ("warn", "stop"):
                from tools.db_pool import get_connection
                async with get_connection() as conn:
                    r = await conn.fetchrow(
                        """SELECT
                             COALESCE(SUM(amount_jpy) FILTER (WHERE recorded_at > NOW() - INTERVAL '24 hours'), 0) as cost_24h,
                             COALESCE(AVG(daily_total), 0) as avg_7d
                           FROM (
                             SELECT DATE(recorded_at) as d, SUM(amount_jpy) as daily_total
                             FROM llm_cost_log
                             WHERE recorded_at > NOW() - INTERVAL '7 days'
                             GROUP BY DATE(recorded_at)
                           ) sub"""
                    )
                    if r and float(r["avg_7d"]) > 0 and float(r["cost_24h"]) > float(r["avg_7d"]) * 2:
                        existing = await conn.fetchval(
                            "SELECT COUNT(*) FROM claude_code_queue WHERE category = 'cost_spike' AND created_at > NOW() - INTERVAL '24 hours'"
                        )
                        if existing == 0:
                            from brain_alpha.escalation import escalate_to_queue
                            await escalate_to_queue(
                                category="cost_spike",
                                description=f"APIコスト異常: 24h=¥{float(r['cost_24h']):.0f}, 7日平均=¥{float(r['avg_7d']):.0f} (2倍超過)",
                                priority="high",
                                source_agent="budget_guard",
                            )
        except Exception:
            pass

        return {
            "allowed": alert_level != "stop",
            "daily_remaining_jpy": max(0, DAILY_BUDGET_JPY - self._daily_spend_jpy),
            "monthly_remaining_jpy": max(0, MONTHLY_BUDGET_JPY - self._monthly_spend_jpy),
            "alert_level": alert_level,
            "message": msg,
        }

    async def record_chat_spend(self, amount_jpy: float, model: str = ""):
        """チャット経由のAPI支出を記録（日次/月次にも加算、予算チェック付き）"""
        # 予算チェック（90%制限）
        daily_pct = (self._daily_spend_jpy + amount_jpy) / self._daily_budget * 100
        if daily_pct >= self._stop_pct:
            logger.warning(f"チャット予算超過: 日次{daily_pct:.1f}%（停止閾値{self._stop_pct}%）")
            return  # 加算しない
        self._chat_spend_jpy += amount_jpy
        self._daily_spend_jpy += amount_jpy
        self._monthly_spend_jpy += amount_jpy
        # DBにもchat固有マーカー付きで記録
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO llm_cost_log (model, tier, amount_jpy, goal_id, is_info, recorded_at)
                    VALUES ($1, 'chat', $2, 'chat', FALSE, NOW())
                    """,
                    model, amount_jpy,
                )
        except Exception as e:
            logger.warning(f"チャット予算DB記録失敗: {e}")

    async def check_before_call(self, estimated_cost_jpy: float) -> dict:
        """
        LLM呼び出し前に予算チェック。
        推定コストを加算した場合に閾値を超えるかを事前判定する。
        """
        try:
            await self._load_from_db()
            await self._reset_if_new_day()

            projected_daily = self._daily_spend_jpy + estimated_cost_jpy
            projected_monthly = self._monthly_spend_jpy + estimated_cost_jpy

            daily_ratio = projected_daily / DAILY_BUDGET_JPY if DAILY_BUDGET_JPY > 0 else 0
            monthly_ratio = projected_monthly / MONTHLY_BUDGET_JPY if MONTHLY_BUDGET_JPY > 0 else 0
            max_ratio = max(daily_ratio, monthly_ratio)

            if max_ratio >= ALERT_THRESHOLD_STOP:
                return {
                    "allowed": False,
                    "reason": f"推定コスト{estimated_cost_jpy}円を加算すると予算90%超過",
                    "suggest_tier_downgrade": True,
                }
            elif max_ratio >= ALERT_THRESHOLD_WARN:
                return {
                    "allowed": True,
                    "reason": f"予算80%警告圏内（推定{estimated_cost_jpy}円加算後）",
                    "suggest_tier_downgrade": True,
                }
            else:
                return {
                    "allowed": True,
                    "reason": "予算範囲内",
                    "suggest_tier_downgrade": False,
                }
        except Exception as e:
            logger.error(f"予算チェックエラー: {e}")
            return {"allowed": True, "reason": f"予算チェックエラー: {e}", "suggest_tier_downgrade": False}

    async def get_budget_status(self) -> dict:
        """現在の予算状態を取得"""
        try:
            await self._load_from_db()
            await self._reset_if_new_day()
        except Exception as e:
            logger.error(f"予算状態取得エラー: {e}")
        return {
            "daily_budget_jpy": DAILY_BUDGET_JPY,
            "daily_spent_jpy": self._daily_spend_jpy,
            "daily_remaining_jpy": max(0, DAILY_BUDGET_JPY - self._daily_spend_jpy),
            "daily_usage_pct": (self._daily_spend_jpy / DAILY_BUDGET_JPY * 100) if DAILY_BUDGET_JPY > 0 else 0,
            "monthly_budget_jpy": MONTHLY_BUDGET_JPY,
            "monthly_spent_jpy": self._monthly_spend_jpy,
            "monthly_remaining_jpy": max(0, MONTHLY_BUDGET_JPY - self._monthly_spend_jpy),
            "monthly_usage_pct": (self._monthly_spend_jpy / MONTHLY_BUDGET_JPY * 100) if MONTHLY_BUDGET_JPY > 0 else 0,
            "info_budget_jpy": MONTHLY_INFO_BUDGET_JPY,
            "info_spent_jpy": self._info_spend_jpy,
            "chat_spent_jpy": self._chat_spend_jpy,
            "budget_mode": self._get_budget_mode(),
        }

    def _get_budget_mode(self) -> str:
        """予算モードを判定"""
        daily_ratio = self._daily_spend_jpy / DAILY_BUDGET_JPY if DAILY_BUDGET_JPY > 0 else 0
        monthly_ratio = self._monthly_spend_jpy / MONTHLY_BUDGET_JPY if MONTHLY_BUDGET_JPY > 0 else 0
        max_ratio = max(daily_ratio, monthly_ratio)

        if max_ratio >= ALERT_THRESHOLD_STOP:
            return "emergency"
        elif max_ratio >= ALERT_THRESHOLD_WARN:
            return "constrained"
        elif max_ratio >= 0.5:
            return "moderate"
        else:
            return "normal"

    def is_emergency_kill_triggered(self) -> bool:
        """Emergency Kill条件: 日次予算の90%超過"""
        return self._daily_spend_jpy >= (DAILY_BUDGET_JPY * ALERT_THRESHOLD_STOP)

    async def close(self):
        """リソース解放（互換性のため保持）"""
        pass


# シングルトン
_instance: Optional[BudgetGuard] = None


def get_budget_guard() -> BudgetGuard:
    """BudgetGuardのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = BudgetGuard()
    return _instance
