"""
SYUTAINβ V25 Lightpanda操作ツール (Step 19, Layer 1)
CDP接続によるヘッドレスブラウザ高速データ抽出

Lightpandaはport 9222でServeモードで起動し、
Chrome DevTools Protocol (CDP)経由で接続する。
"""

import os
import json
import asyncio
import logging
from typing import Optional, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.lightpanda")

# Lightpanda CDPエンドポイント（.envから読み込み）
LIGHTPANDA_HOST = os.getenv("LIGHTPANDA_HOST", "127.0.0.1")
LIGHTPANDA_PORT = int(os.getenv("LIGHTPANDA_PORT", "9222"))


class LightpandaClient:
    """Lightpanda CDP接続クライアント（高速構造化データ抽出用）"""

    def __init__(self):
        self.ws = None
        self.msg_id = 0
        self._connected = False

    async def connect(self) -> bool:
        """WebSocket経由でLightpanda CDPに接続"""
        try:
            import websockets
            # CDPのWebSocketデバッガURLを取得
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://{LIGHTPANDA_HOST}:{LIGHTPANDA_PORT}/json/version",
                    timeout=5.0,
                )
                info = resp.json()
                ws_url = info.get("webSocketDebuggerUrl", "")

            if not ws_url:
                ws_url = f"ws://{LIGHTPANDA_HOST}:{LIGHTPANDA_PORT}"

            self.ws = await websockets.connect(ws_url)
            self._connected = True
            logger.info(f"Lightpanda CDP接続成功: {ws_url}")
            return True
        except Exception as e:
            logger.error(f"Lightpanda CDP接続失敗: {e}")
            self._connected = False
            return False

    async def _send_cdp(self, method: str, params: dict = None) -> Optional[dict]:
        """CDPコマンドを送信して結果を取得"""
        if not self.ws or not self._connected:
            logger.error("Lightpanda未接続")
            return None
        try:
            self.msg_id += 1
            message = {"id": self.msg_id, "method": method}
            if params:
                message["params"] = params
            await self.ws.send(json.dumps(message))
            # レスポンスを待つ（タイムアウト付き）
            response = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
            return json.loads(response)
        except Exception as e:
            logger.error(f"CDPコマンド失敗 ({method}): {e}")
            return None

    async def navigate(self, url: str) -> bool:
        """指定URLへナビゲート"""
        try:
            result = await self._send_cdp("Page.navigate", {"url": url})
            if result and "result" in result:
                # ページ読み込み完了を待つ
                await asyncio.sleep(1.0)
                logger.info(f"Lightpanda navigate: {url}")
                return True
            return False
        except Exception as e:
            logger.error(f"Lightpanda navigate失敗 ({url}): {e}")
            return False

    async def extract_text(self) -> Optional[str]:
        """ページのテキストコンテンツを抽出"""
        try:
            result = await self._send_cdp(
                "Runtime.evaluate",
                {"expression": "document.body.innerText", "returnByValue": True},
            )
            if result and "result" in result:
                return result["result"].get("result", {}).get("value", "")
            return None
        except Exception as e:
            logger.error(f"テキスト抽出失敗: {e}")
            return None

    async def extract_html(self) -> Optional[str]:
        """ページのHTML全体を取得"""
        try:
            result = await self._send_cdp(
                "Runtime.evaluate",
                {"expression": "document.documentElement.outerHTML", "returnByValue": True},
            )
            if result and "result" in result:
                return result["result"].get("result", {}).get("value", "")
            return None
        except Exception as e:
            logger.error(f"HTML取得失敗: {e}")
            return None

    async def extract_structured(self, css_selector: str, fields: dict) -> list:
        """
        CSS セレクタで要素群を取得し、構造化データとして抽出

        Args:
            css_selector: 対象要素のCSSセレクタ (例: "div.product-card")
            fields: フィールド名→子セレクタのマッピング
                    例: {"title": "h2.title", "price": "span.price"}
        Returns:
            抽出結果のリスト
        """
        try:
            js_code = f"""
            (() => {{
                const items = document.querySelectorAll('{css_selector}');
                const fields = {json.dumps(fields)};
                const results = [];
                items.forEach(item => {{
                    const obj = {{}};
                    for (const [key, sel] of Object.entries(fields)) {{
                        const el = item.querySelector(sel);
                        obj[key] = el ? el.innerText.trim() : null;
                    }}
                    results.push(obj);
                }});
                return JSON.stringify(results);
            }})()
            """
            result = await self._send_cdp(
                "Runtime.evaluate",
                {"expression": js_code, "returnByValue": True},
            )
            if result and "result" in result:
                value = result["result"].get("result", {}).get("value", "[]")
                return json.loads(value)
            return []
        except Exception as e:
            logger.error(f"構造化データ抽出失敗: {e}")
            return []

    async def extract_links(self) -> list:
        """ページ内の全リンクを抽出"""
        try:
            js_code = """
            (() => {
                const links = document.querySelectorAll('a[href]');
                return JSON.stringify(
                    Array.from(links).map(a => ({
                        text: a.innerText.trim(),
                        href: a.href
                    }))
                );
            })()
            """
            result = await self._send_cdp(
                "Runtime.evaluate",
                {"expression": js_code, "returnByValue": True},
            )
            if result and "result" in result:
                value = result["result"].get("result", {}).get("value", "[]")
                return json.loads(value)
            return []
        except Exception as e:
            logger.error(f"リンク抽出失敗: {e}")
            return []

    async def take_screenshot(self) -> Optional[bytes]:
        """スクリーンショットを取得（Base64→bytes）"""
        try:
            result = await self._send_cdp("Page.captureScreenshot", {"format": "png"})
            if result and "result" in result:
                import base64
                data = result["result"].get("data", "")
                return base64.b64decode(data)
            return None
        except Exception as e:
            logger.error(f"スクリーンショット取得失敗: {e}")
            return None

    async def close(self):
        """接続を閉じる"""
        try:
            if self.ws:
                await self.ws.close()
                self._connected = False
                logger.info("Lightpanda接続を閉じました")
        except Exception as e:
            logger.error(f"Lightpanda切断エラー: {e}")


async def quick_extract(url: str) -> Optional[str]:
    """URLからテキストを高速抽出するユーティリティ"""
    client = LightpandaClient()
    try:
        if not await client.connect():
            return None
        if not await client.navigate(url):
            return None
        text = await client.extract_text()
        return text
    except Exception as e:
        logger.error(f"quick_extract失敗 ({url}): {e}")
        return None
    finally:
        await client.close()
