"""
SYUTAINb V27 APIクオータ監視
外部APIの日次呼び出し回数を追跡し、閾値超過時に警告する。

追跡対象:
- Jina Reader API (日次上限: JINA_DAILY_LIMIT)
- Jina Embedding API (日次上限: JINA_EMBEDDING_DAILY_LIMIT)
- Tavily Search API (日次上限: TAVILY_DAILY_LIMIT)
- X (Twitter) API (日次上限: X_DAILY_POST_LIMIT, free tier=50)
- Bluesky API (日次上限: BLUESKY_DAILY_POST_LIMIT)
- LLM API (DeepSeek/OpenAI/Anthropic): budget_guardで管理済み
"""

import os
import logging
from datetime import date
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.api_quota_monitor")

# 日次上限設定（.envから読み込み、CLAUDE.md ルール9準拠）
JINA_DAILY_LIMIT = int(os.getenv("JINA_DAILY_LIMIT", "100"))
JINA_EMBEDDING_DAILY_LIMIT = int(os.getenv("JINA_EMBEDDING_DAILY_LIMIT", "500"))
TAVILY_DAILY_LIMIT = int(os.getenv("TAVILY_DAILY_LIMIT", "240"))
X_DAILY_POST_LIMIT = int(os.getenv("X_DAILY_POST_LIMIT", "50"))
BLUESKY_DAILY_POST_LIMIT = int(os.getenv("BLUESKY_DAILY_POST_LIMIT", "100"))

# 警告閾値
QUOTA_WARN_THRESHOLD = float(os.getenv("QUOTA_WARN_THRESHOLD", "0.8"))  # 80%


async def _count_from_event_log(conn, event_type: str, platform: Optional[str] = None) -> int:
    """event_logから当日の呼び出し回数を取得"""
    try:
        if platform:
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE event_type = $1
                   AND created_at::date = CURRENT_DATE
                   AND payload->>'platform' = $2""",
                event_type, platform,
            )
        else:
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE event_type = $1
                   AND created_at::date = CURRENT_DATE""",
                event_type,
            )
        return int(count) if count else 0
    except Exception as e:
        logger.debug(f"event_logカウント失敗 ({event_type}): {e}")
        return 0


async def _count_from_inmemory() -> dict:
    """インメモリカウンタから呼び出し回数を取得（event_logフォールバック）"""
    counts = {}

    # Jina Reader
    try:
        from tools.jina_client import JinaClient
        # シングルトンがなければインスタンスのカウンタは取得不能
        # event_logに依存する
    except Exception:
        pass

    # Jina Embedding
    try:
        from tools.embedding_tools import _embedding_daily_count
        counts["jina_embedding"] = _embedding_daily_count
    except Exception:
        pass

    # Tavily
    try:
        from tools.tavily_client import TavilyClient
        # シングルトンがなければevent_logに依存
    except Exception:
        pass

    return counts


async def check_api_quotas() -> dict:
    """Check remaining quotas for all external APIs.

    Returns dict of {api_name: {used, limit, remaining, percent_used}}
    """
    quotas = {}

    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            # --- Jina Reader ---
            # llm_cost_logのtier='jina'またはevent_logからカウント
            jina_reader_count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE event_type LIKE 'jina.%'
                   AND created_at::date = CURRENT_DATE"""
            )
            # フォールバック: llm_cost_logのmodel LIKE 'jina%'かつis_info=true
            if not jina_reader_count:
                jina_reader_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM llm_cost_log
                       WHERE model LIKE 'jina%%' AND tier = 'info'
                       AND recorded_at::date = CURRENT_DATE"""
                )
            jina_used = int(jina_reader_count) if jina_reader_count else 0
            quotas["jina_reader"] = {
                "used": jina_used,
                "limit": JINA_DAILY_LIMIT,
                "remaining": max(0, JINA_DAILY_LIMIT - jina_used),
                "percent_used": round(jina_used / JINA_DAILY_LIMIT * 100, 1) if JINA_DAILY_LIMIT > 0 else 0,
            }

            # --- Jina Embedding ---
            try:
                from tools.embedding_tools import _embedding_daily_count, _embedding_counter_date
                today_str = date.today().isoformat()
                embed_used = _embedding_daily_count if _embedding_counter_date == today_str else 0
            except Exception:
                embed_used = 0
            quotas["jina_embedding"] = {
                "used": embed_used,
                "limit": JINA_EMBEDDING_DAILY_LIMIT,
                "remaining": max(0, JINA_EMBEDDING_DAILY_LIMIT - embed_used),
                "percent_used": round(embed_used / JINA_EMBEDDING_DAILY_LIMIT * 100, 1) if JINA_EMBEDDING_DAILY_LIMIT > 0 else 0,
            }

            # --- Tavily ---
            tavily_count = await conn.fetchval(
                """SELECT COUNT(*) FROM event_log
                   WHERE event_type LIKE 'tavily.%'
                   AND created_at::date = CURRENT_DATE"""
            )
            # フォールバック: llm_cost_logのmodel LIKE 'tavily%'
            if not tavily_count:
                tavily_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM llm_cost_log
                       WHERE model LIKE 'tavily%%'
                       AND recorded_at::date = CURRENT_DATE"""
                )
            tavily_used = int(tavily_count) if tavily_count else 0
            quotas["tavily"] = {
                "used": tavily_used,
                "limit": TAVILY_DAILY_LIMIT,
                "remaining": max(0, TAVILY_DAILY_LIMIT - tavily_used),
                "percent_used": round(tavily_used / TAVILY_DAILY_LIMIT * 100, 1) if TAVILY_DAILY_LIMIT > 0 else 0,
            }

            # --- X (Twitter) posts ---
            x_count = await _count_from_event_log(conn, "sns.posted", "x")
            quotas["x_post"] = {
                "used": x_count,
                "limit": X_DAILY_POST_LIMIT,
                "remaining": max(0, X_DAILY_POST_LIMIT - x_count),
                "percent_used": round(x_count / X_DAILY_POST_LIMIT * 100, 1) if X_DAILY_POST_LIMIT > 0 else 0,
            }

            # --- Bluesky posts ---
            bsky_count = await _count_from_event_log(conn, "sns.posted", "bluesky")
            quotas["bluesky_post"] = {
                "used": bsky_count,
                "limit": BLUESKY_DAILY_POST_LIMIT,
                "remaining": max(0, BLUESKY_DAILY_POST_LIMIT - bsky_count),
                "percent_used": round(bsky_count / BLUESKY_DAILY_POST_LIMIT * 100, 1) if BLUESKY_DAILY_POST_LIMIT > 0 else 0,
            }

            # --- LLM API (budget_guardから取得) ---
            try:
                from tools.budget_guard import get_budget_guard
                bg = get_budget_guard()
                status = await bg.get_budget_status()
                quotas["llm_budget"] = {
                    "used": round(status["daily_spent_jpy"], 1),
                    "limit": round(status["daily_budget_jpy"], 1),
                    "remaining": round(status["daily_remaining_jpy"], 1),
                    "percent_used": round(status["daily_usage_pct"], 1),
                    "unit": "JPY",
                }
            except Exception as e:
                logger.debug(f"LLM予算取得失敗: {e}")

    except Exception as e:
        logger.warning(f"APIクオータチェック失敗: {e}")
        # インメモリフォールバック
        inmem = await _count_from_inmemory()
        if "jina_embedding" in inmem:
            used = inmem["jina_embedding"]
            quotas["jina_embedding"] = {
                "used": used,
                "limit": JINA_EMBEDDING_DAILY_LIMIT,
                "remaining": max(0, JINA_EMBEDDING_DAILY_LIMIT - used),
                "percent_used": round(used / JINA_EMBEDDING_DAILY_LIMIT * 100, 1) if JINA_EMBEDDING_DAILY_LIMIT > 0 else 0,
            }

    return quotas


async def get_quota_warnings() -> list[str]:
    """80%以上消費しているAPIの警告リストを返す"""
    warnings = []
    try:
        quotas = await check_api_quotas()
        for api_name, info in quotas.items():
            pct = info.get("percent_used", 0)
            if pct >= QUOTA_WARN_THRESHOLD * 100:
                unit = info.get("unit", "calls")
                if pct >= 95:
                    level = "CRITICAL"
                elif pct >= 90:
                    level = "DANGER"
                else:
                    level = "WARNING"
                warnings.append(
                    f"[{level}] {api_name}: {pct:.0f}% ({info['used']}/{info['limit']} {unit})"
                )
    except Exception as e:
        logger.warning(f"クオータ警告チェック失敗: {e}")
    return warnings
