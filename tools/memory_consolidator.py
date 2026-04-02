"""
SYUTAINβ 夜間メモリ統合（Memory Consolidation）

毎日03:45 JSTに実行し、メモリの品質を維持する:
- 低Q値の古いエピソード記憶を削除
- 高類似度のエピソード記憶を統合（高Q値側を残す）
- 重複するペルソナ記憶を除去
- セマンティックキャッシュの期限切れエントリを清掃
- 統合結果をevent_logに記録
"""

import logging
from typing import Optional

from tools.db_pool import get_connection
from tools.event_logger import log_event

logger = logging.getLogger("syutain.memory_consolidator")

# 統合パラメータ
LOW_Q_THRESHOLD = 0.1
OLD_ENTRY_DAYS = 14
SIMILARITY_MERGE_THRESHOLD = 0.95
PERSONA_SIMILARITY_THRESHOLD = 0.95


async def consolidate_memory() -> dict:
    """夜間メモリ統合のメイン関数。

    Returns:
        統合結果のサマリーdict
    """
    stats = {
        "low_q_deleted": 0,
        "similar_merged": 0,
        "persona_deduped": 0,
        "cache_cleaned": 0,
        "errors": [],
    }

    # 1. 低Q値 + 古いエピソード記憶の削除
    try:
        stats["low_q_deleted"] = await _prune_low_q_episodes()
    except Exception as e:
        logger.error(f"低Q値エピソード削除失敗: {e}")
        stats["errors"].append(f"prune_low_q: {e}")

    # 2. 高類似度エピソード記憶の統合
    try:
        stats["similar_merged"] = await _merge_similar_episodes()
    except Exception as e:
        logger.error(f"類似エピソード統合失敗: {e}")
        stats["errors"].append(f"merge_similar: {e}")

    # 3. ペルソナ記憶の重複除去
    try:
        stats["persona_deduped"] = await _deduplicate_persona_memory()
    except Exception as e:
        logger.error(f"ペルソナ記憶重複除去失敗: {e}")
        stats["errors"].append(f"dedupe_persona: {e}")

    # 4. セマンティックキャッシュの清掃
    try:
        stats["cache_cleaned"] = await _cleanup_semantic_cache()
    except Exception as e:
        logger.error(f"セマンティックキャッシュ清掃失敗: {e}")
        stats["errors"].append(f"cache_cleanup: {e}")

    # 結果をevent_logに記録
    total_actions = (
        stats["low_q_deleted"]
        + stats["similar_merged"]
        + stats["persona_deduped"]
        + stats["cache_cleaned"]
    )
    try:
        await log_event(
            "memory.consolidation",
            "system",
            {
                "low_q_deleted": stats["low_q_deleted"],
                "similar_merged": stats["similar_merged"],
                "persona_deduped": stats["persona_deduped"],
                "cache_cleaned": stats["cache_cleaned"],
                "total_actions": total_actions,
                "errors": stats["errors"][:5],
            },
            severity="info" if not stats["errors"] else "warning",
        )
    except Exception as e:
        logger.warning(f"統合結果event_log記録失敗: {e}")

    logger.info(
        f"メモリ統合完了: 低Q削除={stats['low_q_deleted']}, "
        f"類似統合={stats['similar_merged']}, "
        f"ペルソナ重複除去={stats['persona_deduped']}, "
        f"キャッシュ清掃={stats['cache_cleaned']}"
    )
    return stats


async def _prune_low_q_episodes() -> int:
    """q_value < 0.1 かつ 14日以上前のエピソード記憶を削除"""
    async with get_connection() as conn:
        result = await conn.execute(
            """
            DELETE FROM episodic_memory
            WHERE q_value < $1
              AND created_at < NOW() - INTERVAL '%s days'
            """ % OLD_ENTRY_DAYS,
            LOW_Q_THRESHOLD,
        )
        # result is "DELETE N"
        deleted = int(result.split()[-1]) if result else 0
        if deleted > 0:
            logger.info(f"低Q値エピソード {deleted}件 削除（q<{LOW_Q_THRESHOLD}, >{OLD_ENTRY_DAYS}日）")
        return deleted


async def _merge_similar_episodes() -> int:
    """cosine similarity > 0.95 のエピソード記憶を統合（高Q値側を残す）

    同一task_typeのエピソード同士でのみ比較し、
    類似ペアのうち低Q値側を削除する。
    """
    merged_count = 0

    async with get_connection() as conn:
        # embeddingが存在するエピソードをtask_typeごとにグループ化して処理
        task_types = await conn.fetch(
            "SELECT DISTINCT task_type FROM episodic_memory WHERE embedding IS NOT NULL"
        )

        for row in task_types:
            task_type = row["task_type"]

            # 同一task_type内で高類似度ペアを検出
            # 自己結合でcosine similarity > threshold のペアを取得
            pairs = await conn.fetch(
                """
                SELECT a.id AS id_a, b.id AS id_b,
                       a.q_value AS q_a, b.q_value AS q_b,
                       1 - (a.embedding <=> b.embedding) AS similarity
                FROM episodic_memory a
                JOIN episodic_memory b ON a.id < b.id
                    AND a.task_type = b.task_type
                WHERE a.task_type = $1
                    AND a.embedding IS NOT NULL
                    AND b.embedding IS NOT NULL
                    AND 1 - (a.embedding <=> b.embedding) > $2
                ORDER BY similarity DESC
                LIMIT 100
                """,
                task_type,
                SIMILARITY_MERGE_THRESHOLD,
            )

            # 削除対象ID（低Q値側）を収集
            ids_to_delete = set()
            for pair in pairs:
                id_a, id_b = pair["id_a"], pair["id_b"]
                # 既に削除対象のものはスキップ
                if id_a in ids_to_delete or id_b in ids_to_delete:
                    continue
                # 低Q値側を削除
                if pair["q_a"] >= pair["q_b"]:
                    ids_to_delete.add(id_b)
                else:
                    ids_to_delete.add(id_a)

            if ids_to_delete:
                await conn.execute(
                    "DELETE FROM episodic_memory WHERE id = ANY($1::int[])",
                    list(ids_to_delete),
                )
                merged_count += len(ids_to_delete)
                logger.info(
                    f"類似エピソード統合: task_type={task_type}, "
                    f"{len(ids_to_delete)}件 削除"
                )

    return merged_count


async def _deduplicate_persona_memory() -> int:
    """同一category + 高類似度contentのペルソナ記憶を除去

    embeddingがある場合はcosine similarity、
    ない場合はcontent完全一致で判定する。
    """
    deduped = 0

    async with get_connection() as conn:
        # まずembeddingなしの完全一致重複を除去
        result = await conn.execute(
            """
            DELETE FROM persona_memory
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY category, content
                               ORDER BY updated_at DESC, id DESC
                           ) AS rn
                    FROM persona_memory
                ) sub
                WHERE rn > 1
            )
            """
        )
        exact_deduped = int(result.split()[-1]) if result else 0
        deduped += exact_deduped

        # embeddingベースの類似重複除去
        categories = await conn.fetch(
            "SELECT DISTINCT category FROM persona_memory WHERE embedding IS NOT NULL"
        )
        for row in categories:
            category = row["category"]
            pairs = await conn.fetch(
                """
                SELECT a.id AS id_a, b.id AS id_b,
                       1 - (a.embedding <=> b.embedding) AS similarity
                FROM persona_memory a
                JOIN persona_memory b ON a.id < b.id
                    AND a.category = b.category
                WHERE a.category = $1
                    AND a.embedding IS NOT NULL
                    AND b.embedding IS NOT NULL
                    AND 1 - (a.embedding <=> b.embedding) > $2
                ORDER BY similarity DESC
                LIMIT 50
                """,
                category,
                PERSONA_SIMILARITY_THRESHOLD,
            )

            ids_to_delete = set()
            for pair in pairs:
                id_a, id_b = pair["id_a"], pair["id_b"]
                if id_a in ids_to_delete or id_b in ids_to_delete:
                    continue
                # 新しいほう（id大）を残す
                ids_to_delete.add(id_a)

            if ids_to_delete:
                await conn.execute(
                    "DELETE FROM persona_memory WHERE id = ANY($1::int[])",
                    list(ids_to_delete),
                )
                deduped += len(ids_to_delete)

    if deduped > 0:
        logger.info(f"ペルソナ記憶重複除去: {deduped}件 削除")
    return deduped


async def _cleanup_semantic_cache() -> int:
    """セマンティックキャッシュの期限切れエントリ削除"""
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM semantic_cache WHERE expires_at < NOW()"
        )
        deleted = int(result.split()[-1]) if result else 0
        if deleted > 0:
            logger.info(f"セマンティックキャッシュ: {deleted}件 期限切れ削除")
        return deleted
