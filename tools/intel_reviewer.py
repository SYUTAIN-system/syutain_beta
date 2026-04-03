"""intel_items自動レビュー — 多段階振り分け + LLMアクション判定

Phase 1: ルールベース振り分け（全件、コストゼロ）
Phase 2: LLMで高スコア候補のアクション判定（上位のみ、低コスト）
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.intel_reviewer")


async def auto_review_intel(batch_size: int = 100) -> dict:
    """pending_reviewのintel_itemsを多段階で自動振り分け。

    Phase 1 (ルールベース、全件):
        importance_score >= 0.45 → actionable候補
        importance_score 0.20-0.44 → reviewed
        importance_score < 0.20  → archived
        created_at older than 30 days → force archived
        title/summaryが空 → archived
        重複URL → archived（最新のみ残す）

    Phase 2 (LLM、actionable候補のみ):
        候補をまとめてLLMに投げ、実際にアクションが必要か判定
        → actionable or reviewed に最終振り分け

    Returns:
        {"actionable": N, "reviewed": N, "archived": N, "total": N, "llm_evaluated": N}
    """
    from tools.db_pool import get_connection

    summary = {"actionable": 0, "reviewed": 0, "archived": 0, "total": 0, "llm_evaluated": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT id, importance_score, created_at, title, summary, url, source, category
                   FROM intel_items
                   WHERE review_flag = 'pending_review'
                   ORDER BY importance_score DESC, created_at ASC
                   LIMIT $1""",
                batch_size,
            )

            if not rows:
                logger.info("auto_review_intel: 対象なし")
                return summary

            # 重複URL検出
            seen_urls = set()
            existing_urls = set()
            url_rows = await conn.fetch(
                "SELECT DISTINCT url FROM intel_items WHERE review_flag != 'pending_review' AND url IS NOT NULL AND url != ''"
            )
            for r in url_rows:
                existing_urls.add(r["url"])

            actionable_candidates = []

            # === Phase 1: ルールベース振り分け ===
            for row in rows:
                item_id = row["id"]
                score = row["importance_score"] or 0.0
                created = row["created_at"]
                title = row["title"] or ""
                item_summary = row["summary"] or ""
                url = row["url"] or ""

                # 強制アーカイブ条件
                if created and created < cutoff:
                    flag = "archived"
                elif not title.strip() and not item_summary.strip():
                    flag = "archived"
                elif url and (url in seen_urls or url in existing_urls):
                    flag = "archived"  # 重複
                else:
                    # スコアベース振り分け
                    if score >= 0.45:
                        # Phase 2のLLM評価候補
                        actionable_candidates.append(row)
                        if url:
                            seen_urls.add(url)
                        continue  # Phase 2で処理
                    elif score >= 0.20:
                        flag = "reviewed"
                    else:
                        flag = "archived"

                if url:
                    seen_urls.add(url)

                await conn.execute(
                    "UPDATE intel_items SET review_flag = $1 WHERE id = $2",
                    flag, item_id,
                )
                summary[flag] += 1

            # === Phase 2: LLMでactionable候補を評価 ===
            if actionable_candidates:
                actionable_ids = await _llm_evaluate_actionable(conn, actionable_candidates)
                summary["llm_evaluated"] = len(actionable_candidates)

                for row in actionable_candidates:
                    item_id = row["id"]
                    if item_id in actionable_ids:
                        flag = "actionable"
                    else:
                        flag = "reviewed"

                    await conn.execute(
                        "UPDATE intel_items SET review_flag = $1 WHERE id = $2",
                        flag, item_id,
                    )
                    summary[flag] += 1

            summary["total"] = len(rows)
            logger.info(
                f"auto_review_intel完了: {summary['total']}件 "
                f"(actionable={summary['actionable']}, reviewed={summary['reviewed']}, "
                f"archived={summary['archived']}, llm_evaluated={summary['llm_evaluated']})"
            )

    except Exception as e:
        logger.error(f"auto_review_intelエラー: {e}")
        summary["error"] = str(e)

    return summary


async def _llm_evaluate_actionable(conn, candidates: list) -> set:
    """LLMでactionable候補を評価し、実際にアクションが必要なIDのsetを返す。

    バッチで評価（最大15件をまとめて1回のLLM呼び出し）。コスト最小化。
    """
    actionable_ids = set()

    try:
        from tools.llm_router import choose_best_model_v6, call_llm

        model_sel = choose_best_model_v6(
            task_type="classification",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        # 最大15件ずつバッチ処理
        for i in range(0, len(candidates), 15):
            batch = candidates[i:i + 15]
            items_text = ""
            for idx, row in enumerate(batch):
                items_text += (
                    f"[{idx + 1}] ID={row['id']} | {row['source']} | "
                    f"score={row['importance_score']:.2f}\n"
                    f"    title: {(row['title'] or '')[:100]}\n"
                    f"    summary: {(row['summary'] or '')[:150]}\n"
                )

            result = await call_llm(
                prompt=f"""以下の情報アイテムを評価し、SYUTAINβプロジェクトにとって
「今すぐアクションが必要」なものの番号のみを列挙してください。

アクションが必要な基準:
- 使用中の技術（DeepSeek, Qwen, Ollama, NATS, FastAPI, Playwright等）のリリース・破壊的変更・脆弱性
- 直接的な収益機会（新プラットフォーム、API料金変更、競合の動き）
- ICP（AIに関心がある非エンジニアのクリエイター28-39歳）に高い関心を持たれるニュース
- 単なる概要記事・一般的なAIニュースはアクション不要

{items_text}

アクションが必要な番号をカンマ区切りで出力（例: 1,3,7）。該当なしなら「なし」。""",
                system_prompt="情報トリアージエージェント。番号のみ出力。",
                model_selection=model_sel,
            )

            response = result.get("text", "").strip()
            if response and response != "なし":
                import re
                numbers = re.findall(r'\d+', response)
                for n in numbers:
                    idx = int(n) - 1
                    if 0 <= idx < len(batch):
                        actionable_ids.add(batch[idx]["id"])

    except Exception as e:
        logger.warning(f"LLM actionable評価失敗（スコアベースにフォールバック）: {e}")
        # フォールバック: スコア0.45以上は全てactionable
        for row in candidates:
            if (row["importance_score"] or 0.0) >= 0.45:
                actionable_ids.add(row["id"])

    return actionable_ids


async def rescore_all_intel(batch_size: int = 100) -> dict:
    """既存の全intel_itemsを新しいスコアリングロジックで再評価する。

    info_pipeline._score_importance()の改善版で再スコアリングし、
    auto_review_intelで再振り分ける。
    """
    from tools.db_pool import get_connection
    from tools.info_pipeline import InfoPipeline

    pipeline = InfoPipeline()
    result = {"total": 0, "rescored": 0, "score_changes": {"up": 0, "down": 0, "same": 0}}

    try:
        async with get_connection() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM intel_items")
            result["total"] = total

            offset = 0
            while offset < total:
                rows = await conn.fetch(
                    """SELECT id, source, keyword, title, summary, url,
                              importance_score, category
                       FROM intel_items
                       ORDER BY id
                       LIMIT $1 OFFSET $2""",
                    batch_size, offset,
                )

                if not rows:
                    break

                for row in rows:
                    old_score = row["importance_score"] or 0.0
                    new_score = pipeline._score_importance({
                        "title": row["title"] or "",
                        "content": (row["summary"] or "") + " " + (row["keyword"] or ""),
                    })

                    if abs(new_score - old_score) > 0.01:
                        await conn.execute(
                            "UPDATE intel_items SET importance_score = $1, review_flag = 'pending_review' WHERE id = $2",
                            new_score, row["id"],
                        )
                        if new_score > old_score:
                            result["score_changes"]["up"] += 1
                        else:
                            result["score_changes"]["down"] += 1
                    else:
                        result["score_changes"]["same"] += 1

                    result["rescored"] += 1

                offset += batch_size

            logger.info(f"rescore_all_intel完了: {result}")

    except Exception as e:
        logger.error(f"rescore_all_intelエラー: {e}")
        result["error"] = str(e)

    return result
