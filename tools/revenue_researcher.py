"""
SYUTAINβ V25 低コスト多数収益源リサーチャー
月次で収益機会を調査し、レポートを生成する。
"""

import logging
from datetime import datetime, timezone

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.revenue_researcher")

# 調査対象の収益モデル
REVENUE_MODELS = [
    {"model": "note有料記事", "category": "content", "cost": "low", "revenue_potential": "medium",
     "search_query": "note.com 有料記事 収益化 コツ 2026"},
    {"model": "プロンプト集販売", "category": "digital_product", "cost": "zero", "revenue_potential": "medium",
     "search_query": "AIプロンプト 販売 PromptBase Gumroad 2026"},
    {"model": "AIツールアフィリエイト", "category": "affiliate", "cost": "zero", "revenue_potential": "high",
     "search_query": "AI tool affiliate program 2026 commission"},
    {"model": "SNS運用代行", "category": "service", "cost": "low", "revenue_potential": "high",
     "search_query": "AI SNS運用代行 料金 個人事業"},
    {"model": "Notionテンプレート販売", "category": "digital_product", "cost": "zero", "revenue_potential": "medium",
     "search_query": "Notion template 販売 収益 2026"},
    {"model": "AI活用コミュニティ月額", "category": "subscription", "cost": "low", "revenue_potential": "high",
     "search_query": "AI community subscription Discord 月額"},
    {"model": "電子書籍(Kindle)", "category": "content", "cost": "low", "revenue_potential": "medium",
     "search_query": "AI 電子書籍 Kindle 出版 2026 印税"},
    {"model": "API-as-a-Service", "category": "saas", "cost": "medium", "revenue_potential": "high",
     "search_query": "AI API monetization MCP server 2026"},
    {"model": "海外AIサービス紹介アフィリ", "category": "affiliate", "cost": "zero", "revenue_potential": "high",
     "search_query": "overseas AI tool Japanese market first mover affiliate"},
    {"model": "AI研修・コンサル", "category": "service", "cost": "low", "revenue_potential": "very_high",
     "search_query": "AI研修 法人 料金 2026 個人事業主"},
]


async def research_revenue_opportunities() -> dict:
    """収益機会を調査しレポート生成"""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "opportunities": [],
        "recommended_priority": [],
    }

    for model in REVENUE_MODELS:
        opportunity = {
            "model": model["model"],
            "category": model["category"],
            "setup_cost": model["cost"],
            "revenue_potential": model["revenue_potential"],
            "syutain_readiness": _assess_readiness(model["model"]),
        }
        report["opportunities"].append(opportunity)

    # SYUTAINβの既存機能で即座に始められるものを優先
    ready = [o for o in report["opportunities"] if o["syutain_readiness"] == "ready"]
    partial = [o for o in report["opportunities"] if o["syutain_readiness"] == "partial"]
    report["recommended_priority"] = [o["model"] for o in ready] + [o["model"] for o in partial]

    # DBに保存
    try:
        async with get_connection() as conn:
            from tools.event_logger import log_event
            await log_event("revenue.research_completed", "system", {
                "total_opportunities": len(report["opportunities"]),
                "ready_count": len(ready),
                "partial_count": len(partial),
            })
    except Exception:
        pass

    return report


def _assess_readiness(model_name: str) -> str:
    """SYUTAINβの既存機能での実現可能性を評価"""
    ready_models = {
        "note有料記事": "ready",          # note_publisher実装済み
        "プロンプト集販売": "ready",       # content_pipeline + commerce_tools
        "AIツールアフィリエイト": "ready", # affiliate_inserter実装済み
        "SNS運用代行": "partial",          # sns_batchの転用が必要
        "Notionテンプレート販売": "partial",# BrowserAgent必要
        "AI活用コミュニティ月額": "partial",# Discord基盤あり
        "電子書籍(Kindle)": "partial",     # content_pipelineの拡張必要
        "API-as-a-Service": "partial",     # MCP server基盤あり
        "海外AIサービス紹介アフィリ": "ready",  # overseas_trend_detector + affiliate
        "AI研修・コンサル": "not_ready",   # 人間主導
    }
    return ready_models.get(model_name, "not_ready")
