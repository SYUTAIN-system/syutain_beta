"""
SYUTAINβ V25 Auto-Fix Engine (Harness Engineering)
失敗の自動学習ループ

「エージェントがミスしたら、そのミスが二度と起きない仕組みを環境に組み込む」
— Mitchell Hashimoto

event_logのエラーパターンを分析し、auto_fix_rulesテーブルに
再発防止ルールを登録。次回同パターン検知時に自動回避策を適用。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.auto_fix_engine")


async def ensure_table():
    """auto_fix_rulesテーブルが存在しなければ作成"""
    async with get_connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_fix_rules (
                id SERIAL PRIMARY KEY,
                error_pattern TEXT NOT NULL UNIQUE,
                error_category TEXT NOT NULL,
                fix_action TEXT NOT NULL,
                fix_params JSONB DEFAULT '{}',
                hit_count INTEGER DEFAULT 0,
                last_hit_at TIMESTAMPTZ,
                effectiveness_score REAL DEFAULT 0.5,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)


async def learn_from_failure(
    error_type: str,
    error_detail: str,
    source_node: Optional[str] = None,
    context: Optional[dict] = None,
) -> Optional[dict]:
    """
    失敗から学習し、auto_fix_rulesに登録/更新。

    Returns:
        既存ルールがあればその回避策を返す。なければ新規ルール候補を返す。
    """
    try:
        async with get_connection() as conn:
            await ensure_table()

            # エラーパターンの正規化
            pattern = _normalize_error_pattern(error_type, error_detail, source_node)

            # 既存ルールを検索
            existing = await conn.fetchrow(
                "SELECT * FROM auto_fix_rules WHERE error_pattern = $1", pattern
            )

            if existing:
                # ヒットカウント更新
                await conn.execute(
                    """UPDATE auto_fix_rules
                       SET hit_count = hit_count + 1, last_hit_at = NOW(), updated_at = NOW()
                       WHERE id = $1""",
                    existing["id"],
                )
                return {
                    "rule_found": True,
                    "rule_id": existing["id"],
                    "fix_action": existing["fix_action"],
                    "fix_params": _decode_fix_params(existing["fix_params"]),
                    "hit_count": existing["hit_count"] + 1,
                    "effectiveness": existing["effectiveness_score"],
                }

            # 新規ルールを自動生成
            fix_action, fix_params = _infer_fix_action(error_type, error_detail, source_node, context)

            await conn.execute(
                """INSERT INTO auto_fix_rules
                   (error_pattern, error_category, fix_action, fix_params, hit_count, last_hit_at)
                   VALUES ($1, $2, $3, $4, 1, NOW())
                   ON CONFLICT (error_pattern) DO UPDATE
                   SET hit_count = auto_fix_rules.hit_count + 1, last_hit_at = NOW()""",
                pattern, error_type, fix_action, json.dumps(fix_params, ensure_ascii=False),
            )

            return {
                "rule_found": False,
                "new_rule_created": True,
                "error_pattern": pattern,
                "fix_action": fix_action,
                "fix_params": fix_params,
            }

    except Exception as e:
        logger.error(f"learn_from_failure失敗: {e}")
        return None


async def check_known_pattern(
    error_type: str,
    error_detail: str,
    source_node: Optional[str] = None,
) -> Optional[dict]:
    """
    既知のエラーパターンかどうかを確認。
    既知であれば回避策を返す。
    """
    try:
        async with get_connection() as conn:
            await ensure_table()
            pattern = _normalize_error_pattern(error_type, error_detail, source_node)

            rule = await conn.fetchrow(
                "SELECT * FROM auto_fix_rules WHERE error_pattern = $1", pattern
            )
            if rule:
                return {
                    "known": True,
                    "fix_action": rule["fix_action"],
                    "fix_params": _decode_fix_params(rule["fix_params"]),
                    "hit_count": rule["hit_count"],
                    "effectiveness": rule["effectiveness_score"],
                }
            return {"known": False}
    except Exception as e:
        logger.error(f"check_known_pattern失敗: {e}")
        return {"known": False, "error": str(e)}


async def report_fix_outcome(error_pattern: str, success: bool):
    """
    修復結果をフィードバック。effectiveness_scoreを更新。
    """
    try:
        async with get_connection() as conn:
            await ensure_table()
            # EMAで有効性スコアを更新
            alpha = 0.3
            score_delta = 1.0 if success else 0.0
            await conn.execute(
                """UPDATE auto_fix_rules
                   SET effectiveness_score = effectiveness_score * (1 - $1) + $1 * $2,
                       updated_at = NOW()
                   WHERE error_pattern = $3""",
                alpha, score_delta, error_pattern,
            )
    except Exception as e:
        logger.error(f"report_fix_outcome失敗: {e}")


async def get_rules_summary() -> dict:
    """全ルールのサマリーを返す"""
    try:
        async with get_connection() as conn:
            await ensure_table()
            rules = await conn.fetch(
                """SELECT error_pattern, error_category, fix_action, hit_count,
                          effectiveness_score, last_hit_at, created_at
                   FROM auto_fix_rules ORDER BY hit_count DESC LIMIT 50"""
            )
            return {
                "total_rules": len(rules),
                "rules": [
                    {
                        "pattern": r["error_pattern"],
                        "category": r["error_category"],
                        "action": r["fix_action"],
                        "hits": r["hit_count"],
                        "effectiveness": round(r["effectiveness_score"], 2),
                        "last_hit": r["last_hit_at"].isoformat() if r["last_hit_at"] else None,
                    }
                    for r in rules
                ],
            }
    except Exception as e:
        return {"error": str(e)}


def _normalize_error_pattern(error_type: str, error_detail: str, source_node: Optional[str]) -> str:
    """エラーパターンを正規化キーに変換"""
    # ノード固有エラーはノード名を含める
    node_prefix = f"{source_node}:" if source_node else ""
    # 詳細からタイムスタンプ等の変動部分を除去
    detail_key = error_detail.split(":")[0].strip()[:80] if error_detail else ""
    return f"{node_prefix}{error_type}:{detail_key}"


def _decode_fix_params(raw) -> dict:
    """JSONBフィールドをdictに正規化する（asyncpgがdictを返すケースを吸収）。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _infer_fix_action(
    error_type: str,
    error_detail: str,
    source_node: Optional[str],
    context: Optional[dict],
) -> tuple[str, dict]:
    """エラータイプから修復アクションを推論"""

    # SNS投稿失敗
    if "sns" in error_type and "fail" in error_type:
        if "rate" in error_detail.lower() or "429" in error_detail:
            return "throttle_and_retry", {"wait_seconds": 300, "max_retries": 2}
        if "auth" in error_detail.lower() or "401" in error_detail:
            return "skip_and_alert", {"reason": "認証エラー。APIキー確認が必要"}
        return "retry_with_backoff", {"initial_wait": 60, "max_retries": 3}

    # LLMエラー
    if "llm" in error_type:
        if "timeout" in error_detail.lower():
            return "switch_model", {"fallback_tier": "local"}
        if "rate_limit" in error_detail.lower():
            return "throttle_and_retry", {"wait_seconds": 60, "max_retries": 2}
        return "retry_with_fallback_model", {"fallback": "qwen3.5-9b"}

    # ノードダウン
    if "node" in error_type and ("down" in error_detail.lower() or "unreachable" in error_detail.lower()):
        return "reassign_to_available_node", {"exclude_node": source_node}

    # ブラウザエラー
    if "browser" in error_type:
        return "fallback_browser_layer", {"current_layer": context.get("layer", "unknown") if context else "unknown"}

    # デフォルト
    return "log_and_skip", {"reason": "自動推論不可。手動確認推奨"}
