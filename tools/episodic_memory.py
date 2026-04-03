"""
SYUTAINβ MemRL: エピソード記憶 + Q値ベース検索

失敗だけでなく成功・部分成功も記録し、
各エピソードのQ値（有用度）を強化学習的に更新する。

Two-phase retrieval:
1. セマンティック類似度 (pgvector cosine) で候補を絞る
2. Q値でランキングし、最も有用なエピソードを返す
"""

import json
import logging
from typing import Optional

from tools.db_pool import get_connection
from tools.embedding_tools import get_embedding

logger = logging.getLogger("syutain.episodic_memory")


class EpisodicMemory:
    """MemRL-inspired episodic memory with Q-value-based retrieval.

    Stores task execution episodes (success + failure) and learns
    which memories are most useful for future decisions.
    """

    async def record_episode(
        self,
        task_type: str,
        description: str,
        outcome: str,
        context: Optional[dict] = None,
        quality_score: float = 0.5,
        lessons: Optional[str] = None,
    ) -> Optional[int]:
        """Record a task execution episode.

        Args:
            task_type: タスク種別 (drafting, research, browser_action, etc.)
            description: タスクの説明
            outcome: 結果 ('success', 'failure', 'partial')
            context: 付加情報 (goal_id, node, model, error, etc.)
            quality_score: 品質スコア (0.0-1.0)
            lessons: 抽出された教訓（Noneなら自動生成しない）

        Returns:
            episodic_memory.id or None
        """
        if outcome not in ("success", "failure", "partial"):
            outcome = "partial"

        try:
            # Embedding生成
            embedding_str = None
            try:
                search_text = f"{task_type} {outcome} {description}"
                embedding = await get_embedding(search_text[:2000])
                if embedding:
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            except Exception as e:
                logger.debug(f"エピソード記憶embedding生成失敗（無視）: {e}")

            # 初期Q値: 成功は高め、失敗は低め
            initial_q = 0.6 if outcome == "success" else (0.4 if outcome == "partial" else 0.5)

            context_json = json.dumps(context or {}, ensure_ascii=False, default=str)

            async with get_connection() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO episodic_memory
                       (task_type, description, outcome, lessons, context,
                        quality_score, q_value, embedding)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8::vector)
                       RETURNING id""",
                    task_type,
                    description[:2000],
                    outcome,
                    lessons,
                    context_json,
                    quality_score,
                    initial_q,
                    embedding_str,
                )
                episode_id = row["id"] if row else None

            logger.info(
                f"エピソード記憶を記録: id={episode_id}, type={task_type}, "
                f"outcome={outcome}, q={initial_q}"
            )
            return episode_id

        except Exception as e:
            logger.error(f"エピソード記憶の記録失敗: {e}")
            return None

    async def retrieve_relevant(
        self,
        task_description: str,
        task_type: Optional[str] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> list[dict]:
        """Retrieve most useful episodes for the current task.

        Phase 1: semantic similarity > threshold
        Phase 2: rank by q_value (higher = more useful)

        Args:
            task_description: 現在のタスクの説明
            task_type: タスク種別（Noneなら全種別検索）
            top_k: 最大取得件数
            similarity_threshold: 類似度閾値

        Returns:
            [{"id", "task_type", "outcome", "lessons", "description",
              "quality_score", "q_value", "similarity"}, ...]
        """
        try:
            embedding = await get_embedding(task_description[:2000])
            if not embedding:
                return []

            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            # Phase 1 + 2: セマンティック類似度で候補を広めに取得し、Q値でソート
            # 候補プール: top_k * 4 件をコサイン類似度で取得
            pool_size = top_k * 4

            if task_type:
                query = """
                    SELECT id, task_type, description, outcome, lessons,
                           quality_score, q_value, retrieval_count,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM episodic_memory
                    WHERE embedding IS NOT NULL
                      AND task_type = $3
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                """
                async with get_connection() as conn:
                    rows = await conn.fetch(query, embedding_str, pool_size, task_type)
            else:
                query = """
                    SELECT id, task_type, description, outcome, lessons,
                           quality_score, q_value, retrieval_count,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM episodic_memory
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                """
                async with get_connection() as conn:
                    rows = await conn.fetch(query, embedding_str, pool_size)

            # Phase 1: 類似度フィルタ
            candidates = []
            for row in rows:
                sim = float(row["similarity"]) if row["similarity"] is not None else 0.0
                if sim >= similarity_threshold:
                    candidates.append({
                        "id": row["id"],
                        "task_type": row["task_type"],
                        "description": row["description"][:300] if row["description"] else "",
                        "outcome": row["outcome"],
                        "lessons": row["lessons"],
                        "quality_score": float(row["quality_score"]) if row["quality_score"] else 0.0,
                        "q_value": float(row["q_value"]) if row["q_value"] else 0.5,
                        "similarity": round(sim, 3),
                    })

            # Phase 2: Q値でランキング（同Q値なら類似度で）
            candidates.sort(key=lambda x: (x["q_value"], x["similarity"]), reverse=True)
            results = candidates[:top_k]

            # retrieval_countをインクリメント
            if results:
                ids = [r["id"] for r in results]
                try:
                    async with get_connection() as conn:
                        await conn.execute(
                            """UPDATE episodic_memory
                               SET retrieval_count = retrieval_count + 1
                               WHERE id = ANY($1::int[])""",
                            ids,
                        )
                except Exception:
                    pass

            if results:
                logger.info(
                    f"エピソード記憶を{len(results)}件検索 "
                    f"(top q_value={results[0]['q_value']:.2f})"
                )
            return results

        except Exception as e:
            logger.error(f"エピソード記憶検索失敗: {e}")
            return []

    async def update_q_value(self, episode_id: int, was_helpful: bool) -> bool:
        """Update Q-value based on whether the retrieved memory helped.

        helpful:     q_value += 0.1 (max 1.0)
        not helpful: q_value -= 0.05 (min 0.0)
        """
        try:
            if was_helpful:
                delta_sql = "LEAST(q_value + 0.1, 1.0)"
            else:
                delta_sql = "GREATEST(q_value - 0.05, 0.0)"

            async with get_connection() as conn:
                await conn.execute(
                    f"UPDATE episodic_memory SET q_value = {delta_sql} WHERE id = $1",
                    episode_id,
                )
            logger.debug(
                f"エピソード記憶 id={episode_id} Q値更新: helpful={was_helpful}"
            )
            return True
        except Exception as e:
            logger.error(f"Q値更新失敗 (id={episode_id}): {e}")
            return False


# モジュールレベルのシングルトン
_instance: Optional[EpisodicMemory] = None


def get_episodic_memory() -> EpisodicMemory:
    """シングルトンインスタンスを取得"""
    global _instance
    if _instance is None:
        _instance = EpisodicMemory()
    return _instance
