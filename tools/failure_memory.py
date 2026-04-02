"""
SYUTAINβ V27 失敗記憶（Failure Memory）
Harness Engineering: 同じ失敗を二度と繰り返さないためのシステム。

エージェントが失敗した際にLLMで根本原因と防止策を抽出し、
次回同種のタスク実行前にセマンティック類似検索で防止策を注入する。
"""

import json
import logging
from typing import Optional

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.embedding_tools import get_embedding

logger = logging.getLogger("syutain.failure_memory")


async def record_failure(
    failure_type: str,
    error_message: str,
    context: Optional[dict] = None,
    task_type: Optional[str] = None,
) -> Optional[int]:
    """
    失敗を記録し、LLMで根本原因と防止策を抽出する。

    Args:
        failure_type: 失敗種別 (task_error, loop_guard, budget_exceeded, approval_timeout, emergency_kill)
        error_message: エラーメッセージ
        context: 付加情報 (goal, node, model等)
        task_type: タスク種別

    Returns:
        failure_memory.id or None
    """
    try:
        # LLMで根本原因と防止策を抽出
        root_cause = None
        prevention_rule = None
        try:
            model_sel = choose_best_model_v6(
                task_type="analysis",
                quality="low",
                budget_sensitive=True,
                local_available=True,
            )
            analysis_prompt = (
                f"以下の失敗を分析し、JSONで回答してください。\n"
                f"失敗種別: {failure_type}\n"
                f"エラー: {error_message}\n"
                f"タスク種別: {task_type or '不明'}\n"
                f"コンテキスト: {json.dumps(context or {}, ensure_ascii=False, default=str)[:500]}\n\n"
                f'{{"root_cause": "根本原因を1文で", "prevention_rule": "次回の防止策を1文で"}}'
            )
            llm_result = await call_llm(
                prompt=analysis_prompt,
                system_prompt="失敗分析エージェント。JSON形式で簡潔に回答。",
                model_selection=model_sel,
            )
            if llm_result and not llm_result.get("error"):
                text = llm_result.get("text", "")
                # JSONを抽出
                try:
                    # テキストからJSON部分を抽出
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        parsed = json.loads(text[start:end])
                        root_cause = parsed.get("root_cause")
                        prevention_rule = parsed.get("prevention_rule")
                except (json.JSONDecodeError, ValueError):
                    logger.debug("LLM分析結果のJSON解析失敗、テキストをそのまま使用")
                    root_cause = text[:200]
        except Exception as e:
            logger.warning(f"失敗分析LLM呼び出し失敗（記録は継続）: {e}")

        # Embedding生成
        embedding_str = None
        try:
            search_text = f"{failure_type} {task_type or ''} {error_message}"
            embedding = await get_embedding(search_text[:2000])
            if embedding:
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        except Exception as e:
            logger.debug(f"失敗記憶embedding生成失敗（無視）: {e}")

        # DB保存
        context_json = json.dumps(context or {}, ensure_ascii=False, default=str)
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """INSERT INTO failure_memory
                   (failure_type, task_type, error_message, root_cause, prevention_rule,
                    context, embedding)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::vector)
                   RETURNING id""",
                failure_type,
                task_type,
                error_message[:2000],
                root_cause,
                prevention_rule,
                context_json,
                embedding_str,
            )
            failure_id = row["id"] if row else None

        logger.info(
            f"失敗記憶を記録: id={failure_id}, type={failure_type}, "
            f"cause={root_cause or '未抽出'}"
        )
        return failure_id

    except Exception as e:
        logger.error(f"失敗記憶の記録失敗: {e}")
        return None


async def check_similar_failures(
    task_description: str,
    threshold: float = 0.75,
    limit: int = 5,
) -> list[dict]:
    """
    タスク実行前に類似失敗を検索し、防止策を返す。

    Args:
        task_description: タスクの説明文
        threshold: 類似度閾値 (0.0〜1.0)
        limit: 最大取得件数

    Returns:
        [{"id", "failure_type", "prevention_rule", "root_cause", "similarity", "occurrence_count"}, ...]
    """
    try:
        embedding = await get_embedding(task_description[:2000])
        if not embedding:
            return []

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT id, failure_type, task_type, error_message,
                          root_cause, prevention_rule, occurrence_count,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM failure_memory
                   WHERE embedding IS NOT NULL
                     AND resolved = FALSE
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                embedding_str,
                limit,
            )

        results = []
        for row in rows:
            sim = float(row["similarity"]) if row["similarity"] is not None else 0.0
            if sim >= threshold:
                results.append({
                    "id": row["id"],
                    "failure_type": row["failure_type"],
                    "task_type": row["task_type"],
                    "error_message": row["error_message"][:200],
                    "root_cause": row["root_cause"],
                    "prevention_rule": row["prevention_rule"],
                    "occurrence_count": row["occurrence_count"],
                    "similarity": round(sim, 3),
                })

        if results:
            logger.info(
                f"類似失敗を{len(results)}件検出 (閾値={threshold}): "
                f"{[r['failure_type'] for r in results]}"
            )
        return results

    except Exception as e:
        logger.error(f"類似失敗検索失敗: {e}")
        return []


async def update_occurrence(failure_id: int) -> bool:
    """失敗の再発カウントを更新"""
    try:
        async with get_connection() as conn:
            await conn.execute(
                """UPDATE failure_memory
                   SET occurrence_count = occurrence_count + 1,
                       last_seen = NOW()
                   WHERE id = $1""",
                failure_id,
            )
        logger.info(f"失敗記憶 id={failure_id} の再発を記録")
        return True
    except Exception as e:
        logger.error(f"失敗記憶の再発更新失敗 (id={failure_id}): {e}")
        return False


async def mark_resolved(failure_id: int) -> bool:
    """失敗を解決済みにマーク"""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE failure_memory SET resolved = TRUE WHERE id = $1",
                failure_id,
            )
        logger.info(f"失敗記憶 id={failure_id} を解決済みにマーク")
        return True
    except Exception as e:
        logger.error(f"失敗記憶の解決マーク失敗 (id={failure_id}): {e}")
        return False
