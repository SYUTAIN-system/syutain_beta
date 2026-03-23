"""
SYUTAINβ V25 Stagehand v3統合ツール (Step 19, Layer 2)
AI駆動ブラウザ操作・自己修復・アクションキャッシュ

Stagehand v3はNode.jsで動作するため、
PythonからはサブプロセスまたはHTTP API経由で呼び出す。
env=LOCAL モードで動作。
"""

import os
import json
import asyncio
import logging
from typing import Optional, Any
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.stagehand")

# Stagehand v3 ローカルHTTPサーバー設定
STAGEHAND_HOST = os.getenv("STAGEHAND_HOST", "127.0.0.1")
STAGEHAND_PORT = int(os.getenv("STAGEHAND_PORT", "3100"))
STAGEHAND_BASE_URL = f"http://{STAGEHAND_HOST}:{STAGEHAND_PORT}"

# アクションキャッシュ（同じセレクタの操作を高速化）
_action_cache: dict = {}


class StagehandClient:
    """
    Stagehand v3 Pythonクライアント

    Stagehand v3のact()/extract()/observe()インターフェースを
    Python側からHTTP API経由で呼び出す。
    Node.js側にstagehand-server.jsが起動している前提。
    """

    def __init__(self):
        self.base_url = STAGEHAND_BASE_URL
        self._available = False

    async def check_availability(self) -> bool:
        """Stagehandサーバーの疎通確認"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/health",
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    self._available = True
                    logger.info("Stagehand v3サーバー疎通確認OK")
                    return True
            self._available = False
            return False
        except Exception as e:
            logger.warning(f"Stagehandサーバー疎通確認失敗: {e}")
            self._available = False
            return False

    async def _post(self, endpoint: str, payload: dict) -> Optional[dict]:
        """Stagehand APIへのPOSTリクエスト"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}{endpoint}",
                    json=payload,
                    timeout=60.0,  # ブラウザ操作は時間がかかる場合がある
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Stagehand API呼び出し失敗 ({endpoint}): {e}")
            return None

    async def act(self, instruction: str, url: Optional[str] = None) -> Optional[dict]:
        """
        AI駆動アクション実行

        自然言語で操作を指示すると、Stagehandが最適なセレクタを
        自動で選択して操作を実行する。失敗時はセレクタを自動修復する。

        Args:
            instruction: 自然言語の操作指示 (例: "検索ボックスに'Python'と入力してEnterを押す")
            url: 操作対象のURL（指定時は先にナビゲート）
        """
        # キャッシュチェック
        cache_key = f"act:{instruction}:{url or ''}"
        if cache_key in _action_cache:
            cached = _action_cache[cache_key]
            logger.info(f"Stagehandアクションキャッシュヒット: {instruction[:50]}")
            # キャッシュされたセレクタを使って高速実行を試みる
            result = await self._post("/act", {
                "instruction": instruction,
                "url": url,
                "cached_selector": cached.get("selector"),
            })
            if result and result.get("success"):
                return result

        # 通常実行
        try:
            result = await self._post("/act", {
                "instruction": instruction,
                "url": url,
                "env": "LOCAL",
            })
            if result and result.get("success"):
                # アクションキャッシュに保存
                _action_cache[cache_key] = {
                    "selector": result.get("selector_used"),
                    "instruction": instruction,
                }
            return result
        except Exception as e:
            logger.error(f"Stagehand act失敗: {e}")
            return None

    async def extract(
        self, url: str, schema: dict, instruction: Optional[str] = None
    ) -> Optional[dict]:
        """
        AI駆動データ抽出

        Args:
            url: 抽出対象のURL
            schema: 抽出スキーマ (例: {"title": "string", "price": "number"})
            instruction: 抽出に関する補足指示
        """
        try:
            result = await self._post("/extract", {
                "url": url,
                "schema": schema,
                "instruction": instruction,
                "env": "LOCAL",
            })
            return result
        except Exception as e:
            logger.error(f"Stagehand extract失敗: {e}")
            return None

    async def observe(self, url: str, instruction: Optional[str] = None) -> Optional[dict]:
        """
        AI駆動ページ観察

        ページの状態を分析し、可能なアクションのリストを返す。

        Args:
            url: 観察対象のURL
            instruction: 観察に関する補足指示
        """
        try:
            result = await self._post("/observe", {
                "url": url,
                "instruction": instruction,
                "env": "LOCAL",
            })
            return result
        except Exception as e:
            logger.error(f"Stagehand observe失敗: {e}")
            return None

    async def navigate(self, url: str) -> bool:
        """URLへナビゲート"""
        try:
            result = await self._post("/navigate", {"url": url})
            return result is not None and result.get("success", False)
        except Exception as e:
            logger.error(f"Stagehand navigate失敗 ({url}): {e}")
            return False

    async def screenshot(self) -> Optional[str]:
        """スクリーンショットを取得（Base64文字列を返す）"""
        try:
            result = await self._post("/screenshot", {})
            if result:
                return result.get("screenshot_base64")
            return None
        except Exception as e:
            logger.error(f"Stagehandスクリーンショット取得失敗: {e}")
            return None

    def clear_cache(self):
        """アクションキャッシュをクリア"""
        global _action_cache
        _action_cache.clear()
        logger.info("Stagehandアクションキャッシュをクリアしました")
