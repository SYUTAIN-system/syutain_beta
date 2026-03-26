"""SYUTAINβ ブラウザ操作ユーティリティ（公開ページのみ、ログイン不要）"""
import logging
import asyncio
from typing import Optional
import httpx

logger = logging.getLogger("syutain.browser_ops")

BRAVO_IP = "100.75.146.9"
JINA_FALLBACK = True  # Playwright不可時にJina Reader APIにフォールバック

async def scrape_page(url: str, timeout: int = 30) -> dict:
    """公開ページの全文を取得。Jina Reader APIを使用（ログイン不要ページのみ）"""
    try:
        from tools.jina_client import JinaClient
        jina = JinaClient()
        text = await jina.extract_markdown(url)
        return {"url": url, "text": text, "source": "jina", "error": None}
    except Exception as e:
        logger.warning(f"ページ取得失敗 {url}: {e}")
        return {"url": url, "text": "", "source": "error", "error": str(e)}

async def scrape_multiple(urls: list[str], delay: float = 3.0) -> list[dict]:
    """複数URL取得（ページ間3秒ウェイト）"""
    results = []
    for url in urls:
        result = await scrape_page(url)
        results.append(result)
        if delay > 0:
            await asyncio.sleep(delay)
    return results

async def search_and_scrape(query: str, num_results: int = 5) -> list[dict]:
    """Tavily検索 → 上位結果をJinaで全文取得"""
    try:
        from tools.tavily_client import TavilyClient
        tavily = TavilyClient()
        search_results = await tavily.search(query, max_results=num_results)
        urls = [r.get("url") for r in search_results if r.get("url")]
        return await scrape_multiple(urls[:num_results])
    except Exception as e:
        logger.error(f"検索+取得失敗: {e}")
        return []
