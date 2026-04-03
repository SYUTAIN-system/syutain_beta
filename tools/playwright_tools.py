"""
SYUTAINβ V25 Playwright操作ツール (Step 19, Layer 3)
Chromiumフォールバック用ブラウザ自動操作

Layer 1 (Lightpanda) / Layer 2 (Stagehand) で対応できない
重いSPAサイトに対するフォールバックとして使用。
"""

import os
import asyncio
import logging
import base64
from typing import Optional, Any
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.playwright")

# スクリーンショット保存先
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "data/screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Playwrightブラウザ設定
HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]


class PlaywrightBrowser:
    """Playwright Chromiumブラウザ操作クラス"""

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self._initialized = False

    async def launch(self) -> bool:
        """Chromiumブラウザを起動"""
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self.browser = await self._pw.chromium.launch(
                headless=HEADLESS,
                args=CHROMIUM_ARGS,
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            self.page = await self.context.new_page()
            self._initialized = True
            logger.info("Playwright Chromiumブラウザ起動成功")
            return True
        except Exception as e:
            logger.error(f"Playwrightブラウザ起動失敗: {e}")
            return False

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> bool:
        """URLへナビゲート"""
        if not self._initialized:
            logger.error("ブラウザ未起動。先にlaunch()を呼んでください")
            return False
        try:
            await self.page.goto(url, wait_until=wait_until, timeout=30000)
            logger.info(f"Playwright navigate: {url}")
            return True
        except Exception as e:
            logger.error(f"Playwright navigate失敗 ({url}): {e}")
            return False

    async def click(self, selector: str, timeout: int = 10000) -> bool:
        """要素をクリック"""
        if not self._initialized:
            return False
        try:
            await self.page.click(selector, timeout=timeout)
            logger.info(f"Playwright click: {selector}")
            return True
        except Exception as e:
            logger.error(f"Playwright click失敗 ({selector}): {e}")
            return False

    async def fill(self, selector: str, value: str, timeout: int = 10000) -> bool:
        """フォームフィールドに入力"""
        if not self._initialized:
            return False
        try:
            await self.page.fill(selector, value, timeout=timeout)
            logger.info(f"Playwright fill: {selector}")
            return True
        except Exception as e:
            logger.error(f"Playwright fill失敗 ({selector}): {e}")
            return False

    async def type_text(self, selector: str, text: str, delay: int = 50) -> bool:
        """人間のようにテキストをタイプ入力"""
        if not self._initialized:
            return False
        try:
            await self.page.type(selector, text, delay=delay)
            logger.info(f"Playwright type: {selector}")
            return True
        except Exception as e:
            logger.error(f"Playwright type失敗 ({selector}): {e}")
            return False

    async def press(self, key: str) -> bool:
        """キーを押す（Enter, Tab, etc.）"""
        if not self._initialized:
            return False
        try:
            await self.page.keyboard.press(key)
            logger.info(f"Playwright press: {key}")
            return True
        except Exception as e:
            logger.error(f"Playwright press失敗 ({key}): {e}")
            return False

    async def get_text(self, selector: str = "body") -> Optional[str]:
        """要素のテキストコンテンツを取得"""
        if not self._initialized:
            return None
        try:
            return await self.page.inner_text(selector)
        except Exception as e:
            logger.error(f"テキスト取得失敗 ({selector}): {e}")
            return None

    async def get_html(self, selector: str = "html") -> Optional[str]:
        """要素のHTMLを取得"""
        if not self._initialized:
            return None
        try:
            return await self.page.inner_html(selector)
        except Exception as e:
            logger.error(f"HTML取得失敗 ({selector}): {e}")
            return None

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> bool:
        """セレクタが出現するまで待機"""
        if not self._initialized:
            return False
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.error(f"セレクタ待機タイムアウト ({selector}): {e}")
            return False

    async def evaluate(self, expression: str) -> Any:
        """JavaScriptを実行"""
        if not self._initialized:
            return None
        try:
            return await self.page.evaluate(expression)
        except Exception as e:
            logger.error(f"JS実行失敗: {e}")
            return None

    async def screenshot(self, filename: Optional[str] = None, full_page: bool = False) -> Optional[str]:
        """
        スクリーンショットを取得して保存

        Returns:
            保存先のファイルパス、またはNone
        """
        if not self._initialized:
            return None
        try:
            if filename is None:
                import time
                filename = f"pw_{int(time.time())}.png"
            path = SCREENSHOT_DIR / filename
            await self.page.screenshot(path=str(path), full_page=full_page)
            logger.info(f"スクリーンショット保存: {path}")
            return str(path)
        except Exception as e:
            logger.error(f"スクリーンショット取得失敗: {e}")
            return None

    async def screenshot_bytes(self) -> Optional[bytes]:
        """スクリーンショットをバイト列で取得"""
        if not self._initialized:
            return None
        try:
            return await self.page.screenshot()
        except Exception as e:
            logger.error(f"スクリーンショットバイト取得失敗: {e}")
            return None

    async def select_option(self, selector: str, value: str) -> bool:
        """セレクトボックスの値を選択"""
        if not self._initialized:
            return False
        try:
            await self.page.select_option(selector, value)
            logger.info(f"Playwright select: {selector} = {value}")
            return True
        except Exception as e:
            logger.error(f"Playwright select失敗 ({selector}): {e}")
            return False

    async def scroll_to_bottom(self) -> bool:
        """ページ末尾までスクロール"""
        if not self._initialized:
            return False
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"スクロール失敗: {e}")
            return False

    async def get_current_url(self) -> Optional[str]:
        """現在のURLを取得"""
        if not self._initialized:
            return None
        try:
            return self.page.url
        except Exception as e:
            logger.error(f"URL取得失敗: {e}")
            return None

    async def close(self):
        """ブラウザを閉じる"""
        try:
            if self.browser:
                await self.browser.close()
            if hasattr(self, "_pw") and self._pw:
                await self._pw.stop()
            self._initialized = False
            logger.info("Playwrightブラウザを閉じました")
        except Exception as e:
            logger.error(f"Playwrightブラウザ終了エラー: {e}")
