"""
SYUTAINβ V25 学習管理エージェント (Step 21)
コンテンツ→商品変換、提案採用率、モデル品質を追跡し、
週次学習レポートを生成する。

データはPostgreSQLのmodel_quality_log等に保存。
"""

import os
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.learning_manager")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


class LearningManager:
    """学習管理エージェント"""

    def __init__(self):
        self._nats_client = None

    async def initialize(self) -> bool:
        """初期化"""
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.warning(f"NATS接続スキップ: {e}")
        return True

    async def _record_trace(self, action: str = "", reasoning: str = "",
                           confidence: float = None, context: dict = None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5)""",
                    "learning_manager", action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    # ===== コンテンツ→商品変換の追跡 =====

    async def track_content_conversion(
        self,
        content_id: str,
        product_id: str,
        platform: str,
        revenue_jpy: int = 0,
        conversion_stage: str = "initial",
    ):
        """コンテンツが商品に変換された記録を保存"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """
                    INSERT INTO revenue_linkage
                        (source_content_id, product_id, conversion_stage,
                         revenue_jpy, platform)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    content_id, product_id, conversion_stage,
                    revenue_jpy, platform,
                )
                logger.info(
                    f"コンテンツ変換記録: {content_id} → {product_id} "
                    f"({platform}, {revenue_jpy}円)"
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"コンテンツ変換記録失敗: {e}")

    async def get_conversion_stats(self, days: int = 30) -> dict:
        """コンテンツ→商品変換の統計を取得"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                rows = await conn.fetch(
                    """
                    SELECT platform,
                           COUNT(*) as count,
                           SUM(revenue_jpy) as total_revenue,
                           AVG(revenue_jpy) as avg_revenue
                    FROM revenue_linkage
                    WHERE created_at >= NOW() - INTERVAL '$1 days'
                    GROUP BY platform
                    ORDER BY total_revenue DESC
                    """,
                    days,
                )
                return {
                    "period_days": days,
                    "platforms": [dict(r) for r in rows],
                }
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"変換統計取得失敗: {e}")
            return {}

    # ===== 提案採用率の追跡 =====

    async def track_proposal_outcome(
        self,
        proposal_id: str,
        adopted: bool,
        rejection_reason: Optional[str] = None,
        outcome_type: Optional[str] = None,
        revenue_impact_jpy: int = 0,
    ):
        """提案の採用/却下結果を記録"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """
                    UPDATE proposal_history
                    SET adopted = $2,
                        outcome_type = $3,
                        revenue_impact_jpy = $4,
                        updated_at = NOW()
                    WHERE proposal_id = $1
                    """,
                    proposal_id, adopted, outcome_type, revenue_impact_jpy,
                )

                # フィードバック記録
                await conn.execute(
                    """
                    INSERT INTO proposal_feedback
                        (proposal_id, layer_used, adopted, rejection_reason)
                    VALUES ($1, 'learning', $2, $3)
                    """,
                    proposal_id, adopted, rejection_reason,
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"提案結果記録失敗: {e}")

    async def get_proposal_adoption_rate(self, days: int = 30) -> dict:
        """提案採用率の統計"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE adopted = true) as adopted,
                        COUNT(*) FILTER (WHERE adopted = false) as rejected,
                        COALESCE(SUM(revenue_impact_jpy) FILTER (WHERE adopted = true), 0) as total_revenue
                    FROM proposal_history
                    WHERE created_at >= NOW() - INTERVAL '$1 days'
                    """,
                    days,
                )
                total = row["total"] if row else 0
                adopted = row["adopted"] if row else 0
                return {
                    "period_days": days,
                    "total_proposals": total,
                    "adopted": adopted,
                    "rejected": row["rejected"] if row else 0,
                    "adoption_rate": (adopted / total * 100) if total > 0 else 0,
                    "total_revenue_impact_jpy": row["total_revenue"] if row else 0,
                }
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"提案採用率取得失敗: {e}")
            return {}

    # ===== モデル品質の追跡 =====

    async def track_model_quality(
        self,
        task_type: str,
        model_used: str,
        tier: str,
        quality_score: float,
        refinement_needed: bool = False,
        refinement_model: Optional[str] = None,
        total_cost_jpy: float = 0.0,
    ):
        """モデル品質ログを記録"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """
                    INSERT INTO model_quality_log
                        (task_type, model_used, tier, quality_score,
                         refinement_needed, refinement_model, total_cost_jpy)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    task_type, model_used, tier, quality_score,
                    refinement_needed, refinement_model, total_cost_jpy,
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"モデル品質ログ記録失敗: {e}")

    async def get_model_quality_stats(self, days: int = 30) -> list:
        """モデル別品質統計"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        model_used,
                        tier,
                        task_type,
                        COUNT(*) as call_count,
                        AVG(quality_score) as avg_quality,
                        SUM(total_cost_jpy) as total_cost,
                        COUNT(*) FILTER (WHERE refinement_needed = true) as refinement_count
                    FROM model_quality_log
                    WHERE created_at >= NOW() - INTERVAL '$1 days'
                    GROUP BY model_used, tier, task_type
                    ORDER BY avg_quality DESC
                    """,
                    days,
                )
                return [dict(r) for r in rows]
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"モデル品質統計取得失敗: {e}")
            return []

    async def get_best_model_for_task(self, task_type: str) -> Optional[dict]:
        """タスクタイプ別の最適モデルを取得（学習結果に基づく）"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT
                        model_used,
                        tier,
                        AVG(quality_score) as avg_quality,
                        COUNT(*) as sample_count,
                        AVG(total_cost_jpy) as avg_cost
                    FROM model_quality_log
                    WHERE task_type = $1
                      AND created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY model_used, tier
                    HAVING COUNT(*) >= 3
                    ORDER BY avg_quality DESC
                    LIMIT 1
                    """,
                    task_type,
                )
                if row:
                    return dict(row)
                return None
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"最適モデル取得失敗: {e}")
            return None

    # ===== 週次学習レポート =====

    async def generate_weekly_report(self) -> dict:
        """
        週次学習レポートを生成

        Returns:
            包括的な学習レポートデータ
        """
        try:
            report = {
                "generated_at": datetime.utcnow().isoformat(),
                "period": "7 days",
            }

            # コンテンツ変換統計
            report["content_conversion"] = await self.get_conversion_stats(days=7)

            # 提案採用率
            report["proposal_adoption"] = await self.get_proposal_adoption_rate(days=7)

            # モデル品質
            report["model_quality"] = await self.get_model_quality_stats(days=7)

            # タスク完了統計
            report["task_stats"] = await self._get_task_stats(days=7)

            # ブラウザ操作統計
            report["browser_stats"] = await self._get_browser_stats(days=7)

            # レポートを保存
            await self._save_report(report)

            # NATS通知
            if self._nats_client:
                try:
                    await self._nats_client.publish(
                        "agent.learning.weekly_report",
                        {"report_generated": True, "timestamp": report["generated_at"]},
                    )
                except Exception as e:
                    logger.error(f"レポート通知失敗: {e}")

            logger.info("週次学習レポート生成完了")

            # 判断根拠を記録
            task_stats = report.get("task_stats", {})
            model_stats = report.get("model_quality", [])
            adoption = report.get("proposal_adoption", {})
            await self._record_trace(
                action="weekly_report",
                reasoning=f"週次レポート生成。タスク{task_stats.get('total', 0)}件, 採用率{adoption.get('adoption_rate', 0):.0f}%",
                confidence=0.8,
                context={
                    "period": "7 days",
                    "task_total": task_stats.get("total", 0),
                    "task_completed": task_stats.get("completed", 0),
                    "avg_quality": float(task_stats.get("avg_quality") or 0),
                    "proposal_adoption_rate": adoption.get("adoption_rate", 0),
                    "model_count": len(model_stats),
                    "detected_trends": [
                        f"採用率{'低' if adoption.get('adoption_rate', 100) < 30 else '正常'}",
                    ],
                    "recommended_actions": [
                        "提案基準見直し" if adoption.get("adoption_rate", 100) < 30 else "現行維持",
                    ],
                },
            )

            # モデル品質低下エスカレーション
            try:
                for stat in model_stats:
                    if isinstance(stat, dict) and stat.get("avg_quality") is not None:
                        avg_q = float(stat["avg_quality"])
                        if avg_q < 0.5 and stat.get("call_count", 0) >= 5:
                            from brain_alpha.escalation import escalate_to_queue
                            await escalate_to_queue(
                                category="model_quality_decline",
                                description=f"モデル品質低下: {stat.get('model_used', '?')} task={stat.get('task_type', '?')} avg={avg_q:.2f} (calls={stat.get('call_count', 0)})",
                                priority="medium",
                                source_agent="learning_manager",
                            )
            except Exception:
                pass

            return report

        except Exception as e:
            logger.error(f"週次レポート生成失敗: {e}")
            return {"error": str(e)}

    async def _get_task_stats(self, days: int = 7) -> dict:
        """タスク完了統計"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        AVG(quality_score) FILTER (WHERE quality_score IS NOT NULL) as avg_quality,
                        SUM(cost_jpy) as total_cost
                    FROM tasks
                    WHERE created_at >= NOW() - INTERVAL '$1 days'
                    """,
                    days,
                )
                return dict(row) if row else {}
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"タスク統計取得失敗: {e}")
            return {}

    async def _get_browser_stats(self, days: int = 7) -> dict:
        """ブラウザ操作統計"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        layer_used,
                        COUNT(*) as count,
                        COUNT(*) FILTER (WHERE success = true) as success_count,
                        COUNT(*) FILTER (WHERE fallback_from IS NOT NULL) as fallback_count
                    FROM browser_action_log
                    WHERE created_at >= NOW() - INTERVAL '$1 days'
                    GROUP BY layer_used
                    ORDER BY count DESC
                    """,
                    days,
                )
                return {"layers": [dict(r) for r in rows]}
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"ブラウザ統計取得失敗: {e}")
            return {}

    async def _save_report(self, report: dict):
        """レポートをPostgreSQLに保存（intel_itemsテーブルを流用）"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """
                    INSERT INTO intel_items
                        (source, keyword, title, summary, importance_score, category)
                    VALUES ('learning_manager', 'weekly_report', '週次学習レポート',
                            $1, 1.0, 'learning_report')
                    """,
                    json.dumps(report, ensure_ascii=False, default=str),
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"レポート保存失敗: {e}")

    # ===== 学習に基づく推奨 =====

    async def get_recommendations(self) -> dict:
        """学習データに基づく推奨事項を生成"""
        try:
            recs = {
                "generated_at": datetime.utcnow().isoformat(),
                "recommendations": [],
            }

            # 採用率が低い提案タイプの特定
            adoption = await self.get_proposal_adoption_rate(days=30)
            if adoption.get("adoption_rate", 100) < 30:
                recs["recommendations"].append({
                    "type": "proposal_quality",
                    "message": "提案の採用率が30%を下回っています。提案基準の見直しを推奨します。",
                    "priority": "high",
                })

            # コスト効率の悪いモデルの特定
            model_stats = await self.get_model_quality_stats(days=30)
            for stat in model_stats:
                if stat.get("avg_quality", 0) < 0.5 and stat.get("total_cost", 0) > 1000:
                    recs["recommendations"].append({
                        "type": "model_efficiency",
                        "message": (
                            f"モデル '{stat['model_used']}' のタスク '{stat['task_type']}' での"
                            f"品質スコアが低い割にコストが高いです。代替モデルの検討を推奨します。"
                        ),
                        "priority": "medium",
                    })

            return recs

        except Exception as e:
            logger.error(f"推奨事項生成失敗: {e}")
            return {"error": str(e)}
