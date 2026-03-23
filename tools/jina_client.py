"""
SYUTAINβ V25 Jina Readerクライアント (Step 16)
設計書 第5章準拠

Jina Reader APIでURLをMarkdownテキストに変換する。
"""

import os
import logging
from datetime import date
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.jina_client")

JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_READER_URL = "https://r.jina.ai"

# 日次呼び出し上限（安全リミット: 100回/日）
JINA_DAILY_LIMIT = int(os.getenv("JINA_DAILY_LIMIT", "100"))
# 1回あたりの概算コスト（円）— Free tierメインだが追跡する
JINA_COST_PER_CALL_JPY = float(os.getenv("JINA_COST_PER_CALL_JPY", "0.5"))


class JinaClient:
    """Jina Reader APIクライアント"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or JINA_API_KEY
        # 日次呼び出しカウンタ
        self._daily_count: int = 0
        self._counter_date: date = date.today()

    async def read_url(self, url: str, target_selector: Optional[str] = None) -> dict:
        """
        URLをMarkdownテキストに変換

        Args:
            url: 読み取るURL
            target_selector: 特定要素のCSSセレクタ（オプション）

        Returns:
            {"url": str, "title": str, "content": str}
        """
        if not url:
            return {"url": "", "title": "", "content": "", "error": "URL未指定"}

        # 日次リセット
        today = date.today()
        if today != self._counter_date:
            self._daily_count = 0
            self._counter_date = today

        # 日次上限チェック（安全リミット: 100回/日）
        if self._daily_count >= JINA_DAILY_LIMIT:
            logger.warning(f"Jina日次上限到達: {self._daily_count}/{JINA_DAILY_LIMIT}")
            return {"url": url, "title": "", "content": "", "error": f"Daily limit reached ({JINA_DAILY_LIMIT})"}

        headers = {
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if target_selector:
            headers["X-Target-Selector"] = target_selector

        # Jina Reader API: https://r.jina.ai/{url}
        reader_url = f"{JINA_READER_URL}/{url}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(reader_url, headers=headers)
                resp.raise_for_status()

                # 呼び出し成功: カウンタ増加＆コスト追跡
                self._daily_count += 1
                try:
                    from tools.budget_guard import get_budget_guard
                    budget_guard = get_budget_guard()
                    await budget_guard.record_spend(
                        amount_jpy=JINA_COST_PER_CALL_JPY,
                        model="jina-reader",
                        tier="info",
                        is_info_collection=True,
                    )
                except Exception as e_budget:
                    logger.warning(f"Jina予算記録失敗（処理続行）: {e_budget}")

                # JSONレスポンスの場合
                if "application/json" in resp.headers.get("content-type", ""):
                    data = resp.json()
                    return {
                        "url": url,
                        "title": data.get("data", {}).get("title", ""),
                        "content": data.get("data", {}).get("content", ""),
                        "description": data.get("data", {}).get("description", ""),
                    }
                else:
                    # テキストレスポンスの場合
                    text = resp.text
                    # タイトルを最初の行から抽出
                    lines = text.strip().split("\n")
                    title = lines[0].lstrip("#").strip() if lines else ""
                    return {
                        "url": url,
                        "title": title,
                        "content": text,
                    }
        except httpx.HTTPStatusError as e:
            logger.error(f"Jina APIエラー ({e.response.status_code}): {url}")
            return {"url": url, "title": "", "content": "", "error": str(e)}
        except Exception as e:
            logger.error(f"Jina読み取り失敗 ({url}): {e}")
            return {"url": url, "title": "", "content": "", "error": str(e)}

    async def extract_markdown(self, url: str) -> str:
        """URLからMarkdownテキストだけを抽出"""
        result = await self.read_url(url)
        return result.get("content", "")

    async def read_multiple(self, urls: list[str], concurrency: int = 3) -> list[dict]:
        """複数URLを並列で読み込み"""
        import asyncio

        semaphore = asyncio.Semaphore(concurrency)

        async def _read(u: str) -> dict:
            async with semaphore:
                return await self.read_url(u)

        tasks = [_read(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"URL読み込みエラー ({urls[i]}): {r}")
                output.append({"url": urls[i], "title": "", "content": "", "error": str(r)})
            else:
                output.append(r)
        return output
