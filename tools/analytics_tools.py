"""
SYUTAINβ V25 分析ツール (Step 17)
設計書準拠

戦略ファイル読み込み（ICP・Channel・Content）、収益スコアリング。
戦略ファイルを参照してからコンテンツを生成する（CLAUDE.mdルール10）。
"""

import os
import logging
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.analytics_tools")

# 戦略ファイルパス
STRATEGY_DIR = Path(os.getenv("STRATEGY_DIR", "strategy"))


# ===== 戦略ファイル読み込み（CLAUDE.mdルール10）=====

def load_strategy_file(filename: str) -> str:
    """戦略ファイルを読み込む"""
    path = STRATEGY_DIR / filename
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
        else:
            logger.warning(f"戦略ファイルなし: {path}")
            return ""
    except Exception as e:
        logger.error(f"戦略ファイル読み込み失敗 ({filename}): {e}")
        return ""


def load_icp() -> str:
    """ICP定義を読み込む"""
    return load_strategy_file("ICP_DEFINITION.md")


def load_channel_strategy() -> str:
    """チャネル戦略を読み込む"""
    return load_strategy_file("CHANNEL_STRATEGY.md")


def load_content_strategy() -> str:
    """コンテンツ戦略を読み込む"""
    return load_strategy_file("CONTENT_STRATEGY.md")


def load_strategy_context() -> dict:
    """全戦略ファイルをまとめて読み込む"""
    return {
        "icp": load_icp(),
        "channel": load_channel_strategy(),
        "content": load_content_strategy(),
    }


# ===== 収益スコアリング =====

def score_revenue_potential(
    icp_match: float = 0.0,         # ICP適合性 (0-1)
    channel_match: float = 0.0,     # チャネル適合性 (0-1)
    gross_margin: float = 0.0,      # 粗利率 (0-1)
    reusability: float = 0.0,       # 再利用性 (0-1)
    continuity: float = 0.0,        # 継続性 (0-1)
    implementation_cost: float = 0.0,  # 実装コスト (0-1, 低いほど良い)
    market_timing: float = 0.0,     # 市場タイミング (0-1)
) -> dict:
    """
    収益ポテンシャルスコアリング（設計書 1.2準拠）

    7軸で収益タスクを優先順位付けする:
    ICP適合性 / チャネル適合性 / 粗利 / 再利用性 / 継続性 / 実装コスト / 市場タイミング

    Returns:
        {"total_score": float, "breakdown": dict, "priority": str}
    """
    # 重み付け
    weights = {
        "icp_match": 0.20,
        "channel_match": 0.15,
        "gross_margin": 0.20,
        "reusability": 0.10,
        "continuity": 0.15,
        "implementation_cost": 0.10,
        "market_timing": 0.10,
    }

    scores = {
        "icp_match": icp_match,
        "channel_match": channel_match,
        "gross_margin": gross_margin,
        "reusability": reusability,
        "continuity": continuity,
        "implementation_cost": 1.0 - implementation_cost,  # コストは反転
        "market_timing": market_timing,
    }

    total = sum(scores[k] * weights[k] for k in weights)

    # 優先度判定
    if total >= 0.7:
        priority = "high"
    elif total >= 0.4:
        priority = "medium"
    else:
        priority = "low"

    return {
        "total_score": round(total, 3),
        "breakdown": {k: round(v, 3) for k, v in scores.items()},
        "weights": weights,
        "priority": priority,
    }


async def analyze_task_priority(task_description: str) -> dict:
    """タスクの収益優先度をLLMで分析"""
    try:
        from tools.llm_router import call_llm, choose_best_model_v6

        strategy = load_strategy_context()

        system_prompt = f"""あなたはSYUTAINβの収益分析エンジンです。
以下の戦略に基づいてタスクの収益ポテンシャルを0.0-1.0で評価してください。

ICP定義:
{strategy['icp'][:500]}

チャネル戦略:
{strategy['channel'][:500]}

以下のJSON形式で出力してください:
{{
  "icp_match": 0.0-1.0,
  "channel_match": 0.0-1.0,
  "gross_margin": 0.0-1.0,
  "reusability": 0.0-1.0,
  "continuity": 0.0-1.0,
  "implementation_cost": 0.0-1.0,
  "market_timing": 0.0-1.0,
  "reasoning": "理由"
}}"""

        # choose_best_model_v6を使用（CLAUDE.mdルール5）
        selection = choose_best_model_v6(task_type="analysis", budget_sensitive=True)
        result = await call_llm(
            prompt=f"タスク: {task_description}",
            system_prompt=system_prompt,
            model_selection=selection,
        )

        # LLMレスポンスからJSONを抽出
        import json
        text = result.get("text", "{}")
        # JSON部分を探す
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            scores = json.loads(text[start:end])
            return score_revenue_potential(**{
                k: float(scores.get(k, 0.5))
                for k in ["icp_match", "channel_match", "gross_margin",
                          "reusability", "continuity", "implementation_cost", "market_timing"]
            })
    except Exception as e:
        logger.error(f"タスク優先度分析失敗: {e}")

    # デフォルトスコア
    return score_revenue_potential(
        icp_match=0.5, channel_match=0.5, gross_margin=0.5,
        reusability=0.5, continuity=0.5, implementation_cost=0.5,
        market_timing=0.5,
    )


# ===== 収益レポート =====

async def get_revenue_summary(days: int = 30) -> dict:
    """収益サマリーを取得"""
    try:
        import asyncpg
        database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
        conn = await asyncpg.connect(database_url)
        try:
            # プラットフォーム別収益
            rows = await conn.fetch(
                """
                SELECT platform, SUM(revenue_jpy) as total_jpy, COUNT(*) as count
                FROM revenue_linkage
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY platform
                ORDER BY total_jpy DESC
                """,
                days,
            )
            by_platform = {r["platform"]: {"total_jpy": r["total_jpy"], "count": r["count"]} for r in rows}

            # 合計
            total = sum(p["total_jpy"] for p in by_platform.values())

            return {
                "period_days": days,
                "total_jpy": total,
                "by_platform": by_platform,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"収益サマリー取得失敗: {e}")
        return {"period_days": days, "total_jpy": 0, "by_platform": {}, "error": str(e)}
