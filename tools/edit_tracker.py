"""
SYUTAINβ V25 編集追跡ツール
コンテンツ編集のパターン・品質変化を記録し、モデル改善に活用する。

content_edit_logテーブルに編集前後のテキスト、diff情報、編集距離を保存。
"""

import json
import logging
from typing import Optional
from datetime import datetime, timezone
from difflib import SequenceMatcher, unified_diff

from tools.storage_tools import get_pg, PgHelper

logger = logging.getLogger("syutain.edit_tracker")


def _compute_edit_metrics(original: str, edited: str) -> dict:
    """
    difflib.SequenceMatcherで編集距離・編集率を計算する。

    Returns:
        dict with keys: edit_distance, edit_ratio, diff_summary, edit_patterns
    """
    matcher = SequenceMatcher(None, original, edited)
    ratio = matcher.ratio()  # 0.0〜1.0 (1.0 = identical)
    edit_ratio = round(1.0 - ratio, 4)  # 編集率 (0.0 = no change)

    # 編集距離（opcodeベースの変更文字数）
    edit_distance = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            edit_distance += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            edit_distance += i2 - i1
        elif tag == "insert":
            edit_distance += j2 - j1

    # diff_summary（unified diff、最大500文字）
    orig_lines = original.splitlines(keepends=True)
    edit_lines = edited.splitlines(keepends=True)
    diff_lines = list(unified_diff(orig_lines, edit_lines, lineterm=""))
    diff_summary = "\n".join(diff_lines[:30])
    if len(diff_summary) > 500:
        diff_summary = diff_summary[:500] + "..."

    # edit_patterns: 編集の種類を分析
    patterns = {
        "replacements": 0,
        "insertions": 0,
        "deletions": 0,
        "original_length": len(original),
        "edited_length": len(edited),
        "length_change": len(edited) - len(original),
    }
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            patterns["replacements"] += 1
        elif tag == "insert":
            patterns["insertions"] += 1
        elif tag == "delete":
            patterns["deletions"] += 1

    return {
        "edit_distance": edit_distance,
        "edit_ratio": edit_ratio,
        "diff_summary": diff_summary,
        "edit_patterns": patterns,
    }


async def record_edit(
    content_type: str,
    original: str,
    edited: str,
    model_used: Optional[str] = None,
    quality_score_before: Optional[float] = None,
    quality_score_after: Optional[float] = None,
) -> Optional[int]:
    """
    編集ログを記録する。

    Args:
        content_type: コンテンツ種別 (article, product, sns等)
        original: 編集前テキスト
        edited: 編集後テキスト
        model_used: 使用モデル名
        quality_score_before: 編集前品質スコア
        quality_score_after: 編集後品質スコア

    Returns:
        挿入されたレコードのID、失敗時はNone
    """
    try:
        metrics = _compute_edit_metrics(original, edited)
        pg = get_pg()
        record_id = await pg.fetchval(
            """
            INSERT INTO content_edit_log
                (content_type, original_text, edited_text, diff_summary,
                 edit_patterns, model_used, quality_score_before,
                 quality_score_after, edit_distance, edit_ratio)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            content_type,
            original,
            edited,
            metrics["diff_summary"],
            json.dumps(metrics["edit_patterns"], ensure_ascii=False),
            model_used,
            quality_score_before,
            quality_score_after,
            metrics["edit_distance"],
            metrics["edit_ratio"],
        )
        logger.info(
            f"編集ログ記録: id={record_id}, type={content_type}, "
            f"edit_ratio={metrics['edit_ratio']}, distance={metrics['edit_distance']}"
        )
        return record_id
    except Exception as e:
        logger.error(f"編集ログ記録失敗: {e}")
        return None


async def get_edit_stats(
    content_type: Optional[str] = None,
    model: Optional[str] = None,
    days: int = 30,
) -> dict:
    """
    編集統計を取得する。

    Args:
        content_type: フィルタ（コンテンツ種別）
        model: フィルタ（モデル名）
        days: 集計期間（日数）

    Returns:
        dict with avg_edit_ratio, total_count, breakdown_by_type
    """
    try:
        pg = get_pg()

        # 動的WHERE句の構築
        conditions = ["created_at >= NOW() - INTERVAL '1 day' * $1"]
        params: list = [days]
        idx = 2

        if content_type:
            conditions.append(f"content_type = ${idx}")
            params.append(content_type)
            idx += 1
        if model:
            conditions.append(f"model_used = ${idx}")
            params.append(model)
            idx += 1

        where = " AND ".join(conditions)

        # 全体統計
        summary = await pg.fetchrow(
            f"""
            SELECT
                COUNT(*) as total_count,
                COALESCE(AVG(edit_ratio), 0) as avg_edit_ratio,
                COALESCE(AVG(edit_distance), 0) as avg_edit_distance,
                COALESCE(AVG(quality_score_before), 0) as avg_quality_before,
                COALESCE(AVG(quality_score_after), 0) as avg_quality_after
            FROM content_edit_log
            WHERE {where}
            """,
            *params,
        )

        # content_type別の内訳
        breakdown = await pg.fetch(
            f"""
            SELECT
                content_type,
                COUNT(*) as count,
                ROUND(AVG(edit_ratio)::numeric, 4) as avg_edit_ratio,
                ROUND(AVG(edit_distance)::numeric, 1) as avg_edit_distance
            FROM content_edit_log
            WHERE {where}
            GROUP BY content_type
            ORDER BY count DESC
            """,
            *params,
        )

        return {
            "total_count": summary["total_count"] if summary else 0,
            "avg_edit_ratio": round(float(summary["avg_edit_ratio"]), 4) if summary else 0,
            "avg_edit_distance": round(float(summary["avg_edit_distance"]), 1) if summary else 0,
            "avg_quality_before": round(float(summary["avg_quality_before"]), 2) if summary else 0,
            "avg_quality_after": round(float(summary["avg_quality_after"]), 2) if summary else 0,
            "period_days": days,
            "filters": {
                "content_type": content_type,
                "model": model,
            },
            "breakdown_by_type": [
                {
                    "content_type": r["content_type"],
                    "count": r["count"],
                    "avg_edit_ratio": float(r["avg_edit_ratio"]),
                    "avg_edit_distance": float(r["avg_edit_distance"]),
                }
                for r in breakdown
            ],
        }
    except Exception as e:
        logger.error(f"編集統計取得失敗: {e}")
        return {
            "total_count": 0,
            "avg_edit_ratio": 0,
            "avg_edit_distance": 0,
            "period_days": days,
            "breakdown_by_type": [],
            "error": str(e),
        }


async def get_recent_edits(limit: int = 10) -> list:
    """
    最近の編集ログを取得する。

    Args:
        limit: 取得件数（最大50）

    Returns:
        list of edit records
    """
    try:
        limit = min(limit, 50)
        pg = get_pg()
        rows = await pg.fetch(
            """
            SELECT id, content_type, model_used, edit_distance, edit_ratio,
                   quality_score_before, quality_score_after,
                   edit_patterns, diff_summary, created_at
            FROM content_edit_log
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        result = []
        for r in rows:
            record = dict(r)
            # datetimeをISO文字列に変換
            if "created_at" in record and record["created_at"]:
                record["created_at"] = record["created_at"].isoformat()
            # edit_patternsがstr の場合はパース
            if isinstance(record.get("edit_patterns"), str):
                try:
                    record["edit_patterns"] = json.loads(record["edit_patterns"])
                except Exception:
                    pass
            result.append(record)
        return result
    except Exception as e:
        logger.error(f"最近の編集ログ取得失敗: {e}")
        return []
