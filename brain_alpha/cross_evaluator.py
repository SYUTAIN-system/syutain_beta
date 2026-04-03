"""
SYUTAINβ Brain-α 相互評価エンジン
設計書 Section 5 準拠

Brain-αの修正効果をBrain-β側から後追い検証する。
- 修正24h後にエラー再発/品質変化を計測
- スコア修正後の実績と比較
- 結果をbrain_cross_evaluationに記録
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.cross_evaluator")


# ======================================================================
# 1. 修正効果の評価（auto_fix_log）
# ======================================================================

async def evaluate_alpha_fix(auto_fix_log_id: int) -> dict:
    """
    Brain-αの修正を24h後に検証。
    修正前後でエラー再発頻度と品質変化を比較。
    """
    async with get_connection() as conn:
        try:
            # 修正レコード取得
            fix = await conn.fetchrow(
                "SELECT * FROM auto_fix_log WHERE id = $1", auto_fix_log_id
            )
            if not fix:
                return {"status": "not_found", "id": auto_fix_log_id}

            fix_time = fix["created_at"]
            error_type = fix["error_type"]

            # 修正前24hのエラー件数
            window_before = fix_time - timedelta(hours=24)
            window_after = fix_time + timedelta(hours=24)

            before_count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE severity IN ('error', 'critical')
                     AND event_type = $1
                     AND created_at BETWEEN $2 AND $3""",
                error_type, window_before, fix_time,
            )

            # 修正後24hのエラー件数
            after_count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE severity IN ('error', 'critical')
                     AND event_type = $1
                     AND created_at BETWEEN $2 AND $3""",
                error_type, fix_time, window_after,
            )

            # 修正前後の品質スコア平均
            quality_before = await conn.fetchval(
                """SELECT AVG(quality_score) FROM tasks
                   WHERE quality_score > 0
                     AND created_at BETWEEN $1 AND $2""",
                window_before, fix_time,
            )
            quality_after = await conn.fetchval(
                """SELECT AVG(quality_score) FROM tasks
                   WHERE quality_score > 0
                     AND created_at BETWEEN $1 AND $2""",
                fix_time, window_after,
            )

            before_count = before_count or 0
            after_count = after_count or 0
            q_before = float(quality_before or 0)
            q_after = float(quality_after or 0)

            # 効果判定
            error_improvement = before_count - after_count
            quality_improvement = q_after - q_before

            if error_improvement > 0 and quality_improvement >= -0.05:
                verdict = "effective"
                score = min(1.0, 0.5 + error_improvement * 0.1 + quality_improvement)
            elif quality_improvement > 0.3:
                # エラー変化なしでも品質が大幅向上 → effective
                verdict = "effective"
                score = min(1.0, 0.5 + quality_improvement)
            elif error_improvement == 0 and after_count == 0 and quality_improvement >= -0.05:
                verdict = "neutral"
                score = 0.5 + max(0.0, quality_improvement * 0.5)
            elif after_count > before_count:
                verdict = "regression"
                score = max(0.0, 0.3 - (after_count - before_count) * 0.1)
            else:
                verdict = "inconclusive"
                score = 0.5

            evaluation = (
                f"修正効果: エラー{before_count}→{after_count}回 (差={error_improvement}), "
                f"品質{q_before:.2f}→{q_after:.2f} (差={quality_improvement:+.2f})"
            )

            # brain_cross_evaluationに記録
            await conn.execute(
                """INSERT INTO brain_cross_evaluation
                   (evaluator, evaluated_agent, target_id, target_type, score, evaluation, recommendations)
                   VALUES ('brain_beta', 'brain_alpha', $1, 'auto_fix', $2, $3, $4)""",
                str(auto_fix_log_id),
                score,
                evaluation,
                json.dumps({
                    "verdict": verdict,
                    "error_before": before_count,
                    "error_after": after_count,
                    "error_improvement": error_improvement,
                    "quality_before": round(q_before, 3),
                    "quality_after": round(q_after, 3),
                    "quality_improvement": round(quality_improvement, 3),
                    "fix_strategy": fix["fix_strategy"],
                    "fix_result": fix["fix_result"],
                }, ensure_ascii=False),
            )

            logger.info(f"修正評価完了: fix#{auto_fix_log_id} → {verdict} (score={score:.2f})")
            return {
                "status": "ok",
                "fix_id": auto_fix_log_id,
                "verdict": verdict,
                "score": round(score, 2),
                "error_improvement": error_improvement,
                "quality_improvement": round(quality_improvement, 3),
            }

        except Exception as e:
            logger.error(f"修正評価失敗: {e}")
            return {"status": "error", "error": str(e)}


# ======================================================================
# 2. レビュー効果の評価（review_log）
# ======================================================================

async def evaluate_alpha_review(review_log_id: int) -> dict:
    """
    Brain-αのスコア修正を後追い検証。
    修正後のSNS反応/タスク品質と比較し、修正が正しかったか判定。
    """
    async with get_connection() as conn:
        try:
            review = await conn.fetchrow(
                "SELECT * FROM review_log WHERE id = $1", review_log_id
            )
            if not review:
                return {"status": "not_found", "id": review_log_id}

            review_time = review["created_at"]
            target_type = review["target_type"]
            q_before = float(review["quality_before"] or 0)
            q_after = float(review["quality_after"] or 0)
            verdict_original = review["verdict"]

            # 後続の品質推移（レビュー後24h）
            subsequent_quality = await conn.fetchval(
                """SELECT AVG(quality_score) FROM tasks
                   WHERE quality_score > 0
                     AND created_at BETWEEN $1 AND $1 + INTERVAL '24 hours'""",
                review_time,
            )

            # SNS反応（投稿後エンゲージメント）
            sns_engagement = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE event_type = 'sns.posted'
                     AND created_at BETWEEN $1 AND $1 + INTERVAL '48 hours'""",
                review_time,
            )

            subsequent_q = float(subsequent_quality or q_after)

            # 判定: Brain-αの修正が実績と一致するか
            alpha_adjustment = q_after - q_before  # Brain-αの修正量

            if alpha_adjustment < -0.05:
                # 下方修正した場合: 後続品質も低ければ正しかった
                if subsequent_q <= q_after + 0.10:
                    accuracy = "correct_downgrade"
                    score = 0.8
                else:
                    accuracy = "unnecessary_downgrade"
                    score = 0.3
            elif alpha_adjustment > 0.05:
                # 上方修正した場合: 後続品質も高ければ正しかった
                if subsequent_q >= q_after - 0.10:
                    accuracy = "correct_upgrade"
                    score = 0.8
                else:
                    accuracy = "overestimated"
                    score = 0.4
            else:
                accuracy = "minimal_change"
                score = 0.6

            evaluation = (
                f"レビュー検証: {target_type} verdict={verdict_original}, "
                f"品質修正{q_before:.2f}→{q_after:.2f}, "
                f"後続品質{subsequent_q:.2f}, "
                f"判定={accuracy}"
            )

            await conn.execute(
                """INSERT INTO brain_cross_evaluation
                   (evaluator, evaluated_agent, target_id, target_type, score, evaluation, recommendations)
                   VALUES ('brain_beta', 'brain_alpha', $1, 'review', $2, $3, $4)""",
                str(review_log_id),
                score,
                evaluation,
                json.dumps({
                    "accuracy": accuracy,
                    "quality_before": round(q_before, 3),
                    "quality_after_review": round(q_after, 3),
                    "quality_subsequent": round(subsequent_q, 3),
                    "alpha_adjustment": round(alpha_adjustment, 3),
                    "sns_posts_48h": sns_engagement or 0,
                    "original_verdict": verdict_original,
                }, ensure_ascii=False),
            )

            logger.info(f"レビュー評価完了: review#{review_log_id} → {accuracy} (score={score:.2f})")
            return {
                "status": "ok",
                "review_id": review_log_id,
                "accuracy": accuracy,
                "score": round(score, 2),
                "alpha_adjustment": round(alpha_adjustment, 3),
                "subsequent_quality": round(subsequent_q, 3),
            }

        except Exception as e:
            logger.error(f"レビュー評価失敗: {e}")
            return {"status": "error", "error": str(e)}


# ======================================================================
# 3. 未評価レコードの自動スケジュール評価
# ======================================================================

async def schedule_evaluations() -> dict:
    """
    24h以上前の未評価auto_fix_log/review_logを自動評価。
    """
    results = {"fixes_evaluated": 0, "reviews_evaluated": 0, "errors": []}

    async with get_connection() as conn:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

            # 未評価のauto_fix_logを検索
            fix_rows = await conn.fetch(
                """SELECT afl.id FROM auto_fix_log afl
                   LEFT JOIN brain_cross_evaluation bce
                     ON bce.target_id = afl.id::text AND bce.target_type = 'auto_fix'
                   WHERE bce.id IS NULL
                     AND afl.created_at < $1
                   LIMIT 10""",
                cutoff,
            )

            for row in fix_rows:
                try:
                    await evaluate_alpha_fix(row["id"])
                    results["fixes_evaluated"] += 1
                except Exception as e:
                    results["errors"].append(f"fix#{row['id']}: {e}")

            # 未評価のreview_logを検索
            review_rows = await conn.fetch(
                """SELECT rl.id FROM review_log rl
                   LEFT JOIN brain_cross_evaluation bce
                     ON bce.target_id = rl.id::text AND bce.target_type = 'review'
                   WHERE bce.id IS NULL
                     AND rl.created_at < $1
                   LIMIT 10""",
                cutoff,
            )

            for row in review_rows:
                try:
                    await evaluate_alpha_review(row["id"])
                    results["reviews_evaluated"] += 1
                except Exception as e:
                    results["errors"].append(f"review#{row['id']}: {e}")

            results["status"] = "ok"
            total = results["fixes_evaluated"] + results["reviews_evaluated"]
            if total > 0:
                logger.info(f"相互評価完了: fix={results['fixes_evaluated']}, review={results['reviews_evaluated']}")

        except Exception as e:
            logger.error(f"スケジュール評価失敗: {e}")
            results["status"] = "error"
            results["errors"].append(str(e))

    return results


# ======================================================================
# 4. フィードバックループ: 評価結果をself_healer/llm_routerに反映
# ======================================================================

async def apply_cross_evaluation_feedback() -> dict:
    """
    brain_cross_evaluationの最新結果を集計し:
    1. 修復成功率が低い(< 0.5)修復戦略をevent_logに警告記録
    2. 修復後品質が安定して悪いモデルをmodel_quality_logにフィードバック
    """
    feedback = {"strategies_flagged": 0, "model_adjustments": 0}

    try:
        async with get_connection() as conn:
            # 修復戦略の成功率を集計（直近30日）
            strategy_stats = await conn.fetch(
                """SELECT
                    recommendations->>'fix_strategy' as strategy,
                    COUNT(*) as total,
                    AVG(score) as avg_score,
                    SUM(CASE WHEN recommendations->>'accuracy' IN ('effective', 'improved', 'accurate') THEN 1 ELSE 0 END) as success_count
                FROM brain_cross_evaluation
                WHERE target_type = 'auto_fix'
                AND created_at > NOW() - INTERVAL '30 days'
                AND recommendations->>'fix_strategy' IS NOT NULL
                GROUP BY recommendations->>'fix_strategy'
                HAVING COUNT(*) >= 3"""
            )

            for row in strategy_stats:
                success_rate = int(row["success_count"]) / int(row["total"]) if int(row["total"]) > 0 else 0
                if success_rate < 0.5:
                    from tools.event_logger import log_event
                    await log_event(
                        "cross_eval.strategy_low_success", "brain_alpha",
                        {
                            "strategy": row["strategy"],
                            "success_rate": round(success_rate, 2),
                            "total_evaluated": int(row["total"]),
                            "avg_score": round(float(row["avg_score"]), 2),
                        },
                        severity="warning",
                    )
                    feedback["strategies_flagged"] += 1

            # レビュー精度が低い場合のモデル品質フィードバック
            low_accuracy_reviews = await conn.fetch(
                """SELECT
                    recommendations->>'accuracy' as accuracy,
                    score,
                    recommendations
                FROM brain_cross_evaluation
                WHERE target_type = 'review'
                AND created_at > NOW() - INTERVAL '7 days'
                AND score < 0.4
                LIMIT 10"""
            )

            if len(low_accuracy_reviews) >= 3:
                from tools.event_logger import log_event
                await log_event(
                    "cross_eval.review_quality_alert", "brain_alpha",
                    {
                        "low_reviews_count": len(low_accuracy_reviews),
                        "avg_score": round(
                            sum(float(r["score"]) for r in low_accuracy_reviews) / len(low_accuracy_reviews), 2
                        ),
                    },
                    severity="warning",
                )
                feedback["model_adjustments"] += 1

        if feedback["strategies_flagged"] > 0 or feedback["model_adjustments"] > 0:
            logger.info(
                f"相互評価フィードバック適用: 戦略警告{feedback['strategies_flagged']}件, "
                f"モデル調整{feedback['model_adjustments']}件"
            )
    except Exception as e:
        logger.error(f"相互評価フィードバック適用失敗: {e}")

    return feedback
