"""
SYUTAINβ V25 Tavily検索クライアント (Step 16)
設計書 第5章準拠

Tavily API経由でAI特化Web検索を実行する。
日本語サポート対応。
"""

import os
import asyncio
import logging
from datetime import date
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.tavily_client")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_API_URL = "https://api.tavily.com/search"

# 日次呼び出し上限（設計書 11.3準拠: 240回/日）
TAVILY_DAILY_LIMIT = int(os.getenv("TAVILY_DAILY_LIMIT", "240"))
# 1回あたりの概算コスト（円）
TAVILY_COST_PER_CALL_JPY = float(os.getenv("TAVILY_COST_PER_CALL_JPY", "2.0"))


class TavilyClient:
    """Tavily Search APIクライアント"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or TAVILY_API_KEY
        if not self.api_key:
            logger.warning("TAVILY_API_KEY未設定")
        # 日次呼び出しカウンタ
        self._daily_count: int = 0
        self._counter_date: date = date.today()

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
        include_domains: Optional[list] = None,
        exclude_domains: Optional[list] = None,
    ) -> dict:
        """
        Tavily検索を実行

        Args:
            query: 検索クエリ（日本語対応）
            max_results: 最大結果数 (1-10)
            search_depth: "basic" or "advanced"
            include_answer: AIによる回答を含めるか
            include_domains: 検索対象ドメインリスト
            exclude_domains: 除外ドメインリスト

        Returns:
            {"query": str, "answer": str, "results": [...]}
        """
        if not self.api_key:
            logger.error("TAVILY_API_KEY未設定: 検索を実行できません")
            return {"query": query, "answer": "", "results": [], "error": "API key not set"}

        # 日次リセット
        today = date.today()
        if today != self._counter_date:
            self._daily_count = 0
            self._counter_date = today

        # 日次上限チェック（設計書 11.3: 240回/日）
        if self._daily_count >= TAVILY_DAILY_LIMIT:
            logger.warning(f"Tavily日次上限到達: {self._daily_count}/{TAVILY_DAILY_LIMIT}")
            return {"query": query, "answer": "", "results": [], "error": f"Daily limit reached ({TAVILY_DAILY_LIMIT})"}

        # 予算ガード連携（情報収集予算として記録）
        try:
            from tools.budget_guard import get_budget_guard
            budget_guard = get_budget_guard()
            budget_check = await budget_guard.check_before_call(TAVILY_COST_PER_CALL_JPY)
            if not budget_check["allowed"]:
                remaining = budget_check.get("remaining_jpy", "?")
                from tools.discord_notify import notify_discord
                asyncio.create_task(notify_discord(
                    f"⚠️ Tavily検索スキップ: 予算超過（残¥{remaining}）。検索クエリ: {query[:60]}"
                ))
                logger.warning(f"Tavily検索: 予算超過でスキップ (残¥{remaining}, query={query[:40]})")
                return {"query": query, "answer": "", "results": [], "error": "Budget exceeded"}
        except Exception as e:
            logger.warning(f"Tavily予算チェック失敗（処理続行）: {e}")

        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": min(max_results, 10),
            "search_depth": search_depth,
            "include_answer": include_answer,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(TAVILY_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

                results = []
                for r in data.get("results", []):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                        "score": r.get("score", 0.0),
                    })

                # 呼び出し成功: カウンタ増加＆予算記録
                self._daily_count += 1
                try:
                    from tools.budget_guard import get_budget_guard
                    budget_guard = get_budget_guard()
                    await budget_guard.record_spend(
                        amount_jpy=TAVILY_COST_PER_CALL_JPY,
                        model="tavily-search",
                        tier="info",
                        is_info_collection=True,
                    )
                except Exception as e_budget:
                    logger.warning(f"Tavily予算記録失敗（処理続行）: {e_budget}")

                return {
                    "query": query,
                    "answer": data.get("answer", ""),
                    "results": results,
                    "daily_calls_used": self._daily_count,
                    "daily_calls_remaining": TAVILY_DAILY_LIMIT - self._daily_count,
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"Tavily APIエラー ({e.response.status_code}): {e}")
            return {"query": query, "answer": "", "results": [], "error": str(e)}
        except Exception as e:
            logger.error(f"Tavily検索失敗: {e}")
            return {"query": query, "answer": "", "results": [], "error": str(e)}

    async def search_japanese(self, query: str, **kwargs) -> dict:
        """日本語クエリ用ラッパー（日本語サイト優先）"""
        jp_domains = [
            "note.com", "qiita.com", "zenn.dev", "gigazine.net",
            "itmedia.co.jp", "impress.co.jp", "techcrunch.com",
        ]
        return await self.search(
            query=query,
            include_domains=kwargs.pop("include_domains", jp_domains),
            **kwargs,
        )

    async def search_tech(self, query: str, **kwargs) -> dict:
        """テック系検索（AI/開発関連ドメイン優先）"""
        tech_domains = [
            "arxiv.org", "huggingface.co", "github.com",
            "openai.com", "anthropic.com", "deepmind.google",
            "techcrunch.com", "theverge.com", "arstechnica.com",
        ]
        return await self.search(
            query=query,
            include_domains=kwargs.pop("include_domains", tech_domains),
            search_depth="advanced",
            **kwargs,
        )
