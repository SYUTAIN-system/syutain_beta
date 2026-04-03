"""
SYUTAINβ スキル形式化マネージャー

高Q値のエピソード記憶を再利用可能な「スキル」に昇格させる。
スキルは実行前にタスクに注入され、成功パターンを横展開する。

抽出基準: q_value >= 0.5, retrieval_count >= 1, outcome = 'success'（初期フェーズ緩和版）
"""

import json
import logging
from typing import Optional

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm

logger = logging.getLogger("syutain.skill_manager")


class SkillManager:
    """Manages reusable skills extracted from high-performing episodic memories.

    Skills are formalized patterns that proved effective:
    - Extracted from episodic_memory where q_value >= 0.5 and retrieval_count >= 1
    - Stored as structured rules with applicability conditions
    - Auto-applied to matching tasks before execution
    """

    async def extract_skills(self) -> list:
        """Scan episodic_memory for skill candidates.

        Criteria: q_value >= 0.5, retrieval_count >= 1, success outcome.
        Use LLM to generalize the lesson into a reusable skill rule.

        Returns:
            list of created skill dicts
        """
        created_skills = []
        try:
            async with get_connection() as conn:
                # 高Q値かつ頻繁に参照された成功エピソードを取得
                # 既にスキル化済みのエピソードを除外
                candidates = await conn.fetch(
                    """SELECT e.id, e.task_type, e.description, e.lessons,
                              e.quality_score, e.q_value, e.retrieval_count
                       FROM episodic_memory e
                       WHERE e.q_value >= 0.5
                         AND e.retrieval_count >= 1
                         AND e.outcome = 'success'
                         AND e.lessons IS NOT NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM skills s
                             WHERE s.source_episode_ids @> jsonb_build_array(e.id)
                         )
                       ORDER BY e.q_value DESC, e.retrieval_count DESC
                       LIMIT 10"""
                )

                if not candidates:
                    logger.info("スキル抽出: 候補なし")
                    return []

                logger.info(f"スキル抽出: {len(candidates)}件の候補を処理")

                for ep in candidates:
                    try:
                        skill = await self._generalize_episode(ep)
                        if skill:
                            skill_id = await conn.fetchval(
                                """INSERT INTO skills
                                   (name, rule, source_episode_ids, task_types, confidence)
                                   VALUES ($1, $2, $3, $4, $5)
                                   RETURNING id""",
                                skill["name"],
                                skill["rule"],
                                json.dumps([ep["id"]]),
                                json.dumps(skill["task_types"]),
                                min(float(ep["q_value"]), 0.9),
                            )
                            created_skills.append({
                                "id": skill_id,
                                "name": skill["name"],
                                "source_episode_id": ep["id"],
                            })
                            logger.info(
                                f"スキル作成: id={skill_id}, name={skill['name']}, "
                                f"source_episode={ep['id']}"
                            )
                    except Exception as e:
                        logger.warning(f"エピソード{ep['id']}のスキル化失敗: {e}")

            return created_skills

        except Exception as e:
            logger.error(f"スキル抽出失敗: {e}")
            return []

    async def get_applicable_skills(
        self, task_type: str, task_description: str
    ) -> list:
        """Find skills that match the current task context.

        Args:
            task_type: タスク種別
            task_description: タスクの説明

        Returns:
            list of applicable skill dicts
        """
        try:
            async with get_connection() as conn:
                # task_typeが一致 + confidenceが十分なスキルを取得
                rows = await conn.fetch(
                    """SELECT id, name, rule, task_types, confidence,
                              success_count, total_usage
                       FROM skills
                       WHERE task_types @> $1::jsonb
                         AND confidence >= 0.4
                       ORDER BY confidence DESC, success_count DESC
                       LIMIT 5""",
                    json.dumps([task_type]),
                )

                # task_type完全一致がない場合、汎用スキル（task_types空配列）もチェック
                if not rows:
                    rows = await conn.fetch(
                        """SELECT id, name, rule, task_types, confidence,
                                  success_count, total_usage
                           FROM skills
                           WHERE task_types = '[]'::jsonb
                             AND confidence >= 0.5
                           ORDER BY confidence DESC
                           LIMIT 3"""
                    )

                return [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "rule": r["rule"],
                        "confidence": float(r["confidence"]),
                        "success_rate": (
                            round(r["success_count"] / r["total_usage"], 2)
                            if r["total_usage"] > 0
                            else 0.0
                        ),
                    }
                    for r in rows
                ]

        except Exception as e:
            logger.error(f"スキル検索失敗: {e}")
            return []

    async def record_skill_usage(self, skill_id: int, was_helpful: bool):
        """Track skill effectiveness.

        Args:
            skill_id: スキルID
            was_helpful: スキルが有用だったか
        """
        try:
            async with get_connection() as conn:
                if was_helpful:
                    await conn.execute(
                        """UPDATE skills
                           SET success_count = success_count + 1,
                               total_usage = total_usage + 1,
                               confidence = LEAST(confidence + 0.05, 1.0)
                           WHERE id = $1""",
                        skill_id,
                    )
                else:
                    await conn.execute(
                        """UPDATE skills
                           SET total_usage = total_usage + 1,
                               confidence = GREATEST(confidence - 0.1, 0.0)
                           WHERE id = $1""",
                        skill_id,
                    )
                logger.debug(
                    f"スキル使用記録: id={skill_id}, helpful={was_helpful}"
                )
        except Exception as e:
            logger.error(f"スキル使用記録失敗 (id={skill_id}): {e}")

    async def _generalize_episode(self, episode: dict) -> Optional[dict]:
        """LLMでエピソードの教訓を汎用スキルに昇華する。

        Args:
            episode: episodic_memoryレコード

        Returns:
            {"name": str, "rule": str, "task_types": list} or None
        """
        try:
            model_sel = choose_best_model_v6(
                task_type="analysis",
                quality="low",
                budget_sensitive=True,
                local_available=True,
            )

            prompt = f"""以下の成功タスクの教訓を、汎用的な再利用可能ルールに昇華してください。
具体的な状況に依存しない、一般化されたパターンとして記述してください。

タスク種別: {episode['task_type']}
説明: {(episode['description'] or '')[:500]}
教訓: {(episode['lessons'] or '')[:500]}
品質スコア: {episode['quality_score']}

以下のJSON形式で回答:
{{"name": "スキル名（10文字以内）", "rule": "再利用可能なルール（1-2文）", "task_types": ["適用可能なタスク種別リスト"]}}"""

            result = await call_llm(
                prompt=prompt,
                system_prompt="タスク最適化エージェント。有効なJSONのみ出力。",
                model_selection=model_sel,
            )

            text = result.get("text", "").strip()

            import re
            match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get("name") and data.get("rule"):
                    return {
                        "name": data["name"][:50],
                        "rule": data["rule"][:500],
                        "task_types": data.get("task_types", [episode["task_type"]]),
                    }
            return None

        except Exception as e:
            logger.warning(f"スキル汎化LLM失敗: {e}")
            return None


# モジュールレベルのシングルトン
_instance: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """シングルトンインスタンスを取得"""
    global _instance
    if _instance is None:
        _instance = SkillManager()
    return _instance
