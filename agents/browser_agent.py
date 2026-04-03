"""
SYUTAINβ V25 ブラウザ操作エージェント (Step 19)
4層ブラウザ自動操作 — BRAVO常駐

Layer 1: Lightpanda (CDP, 高速データ抽出)
Layer 2: Stagehand v3 (AI駆動, 自己修復, アクションキャッシュ)
Layer 3: Playwright + Chromium (重いSPAフォールバック)
Layer 4: GPT-5.4 Computer Use (視覚操作, CAPTCHA, ログイン)

サイト特性に基づいて層を自動選択し、上位層→下位層へ自動フォールバックする。
操作ログはPostgreSQLのbrowser_action_logテーブルに記録する。
NATSサブジェクト: browser.action.{node}, browser.result.{node}.{action_id}
"""

import os
import json
import uuid
import asyncio
import logging
from typing import Optional, Any
from datetime import datetime, timezone

from dotenv import load_dotenv
from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.browser_agent")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
THIS_NODE = os.getenv("THIS_NODE", "bravo")

# サイト特性による自動層選択ルール
# 静的サイト / API → Layer 1 (Lightpanda)
# 標準的なWebアプリ → Layer 2 (Stagehand)
# 重いSPA (React/Angular/Vue) → Layer 3 (Playwright)
# CAPTCHA / ログイン / 複雑なUI → Layer 4 (Computer Use)

# SPAフレームワーク検出用パターン
_SPA_INDICATORS = [
    "react", "angular", "vue", "__next", "__nuxt",
    "webpack", "bundle.js", "app.js",
]

# Layer 4が必要な操作タイプ
_LAYER4_ACTIONS = ["login", "captcha", "complex_form", "visual_verify"]


class BrowserAgent:
    """4層ブラウザ自動操作エージェント"""

    def __init__(self):
        self.node = THIS_NODE
        self._lightpanda = None
        self._stagehand = None
        self._playwright = None
        self._computer_use = None
        self._nats_client = None

    async def initialize(self) -> bool:
        """エージェントを初期化（各レイヤーの疎通確認）"""
        layers_available = []

        # Layer 1: Lightpanda
        try:
            from tools.lightpanda_tools import LightpandaClient
            self._lightpanda = LightpandaClient()
            if await self._lightpanda.connect():
                layers_available.append("lightpanda")
            else:
                self._lightpanda = None
        except Exception as e:
            logger.warning(f"Lightpanda初期化スキップ: {e}")

        # Layer 2: Stagehand
        try:
            from tools.stagehand_tools import StagehandClient
            self._stagehand = StagehandClient()
            if await self._stagehand.check_availability():
                layers_available.append("stagehand")
            else:
                self._stagehand = None
        except Exception as e:
            logger.warning(f"Stagehand初期化スキップ: {e}")

        # Layer 3: Playwright（常に利用可能と想定）
        try:
            from tools.playwright_tools import PlaywrightBrowser
            self._playwright = PlaywrightBrowser()
            if await self._playwright.launch():
                layers_available.append("playwright")
            else:
                self._playwright = None
        except Exception as e:
            logger.warning(f"Playwright初期化スキップ: {e}")

        # Layer 4: Computer Use（APIキーがあれば利用可能）
        try:
            from tools.computer_use_tools import ComputerUseClient
            self._computer_use = ComputerUseClient()
            if self._computer_use.api_key:
                layers_available.append("computer_use")
            else:
                self._computer_use = None
        except Exception as e:
            logger.warning(f"Computer Use初期化スキップ: {e}")

        # NATS接続
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.warning(f"NATS接続スキップ（HTTPフォールバックで継続）: {e}")

        logger.info(f"BrowserAgent初期化完了: 利用可能レイヤー = {layers_available}")
        return len(layers_available) > 0

    def _choose_layer(self, action_type: str, url: str, site_hints: dict = None) -> str:
        """
        サイト特性に基づいて最適な層を自動選択

        Args:
            action_type: 操作タイプ ("extract", "navigate", "click", "login", "captcha", etc.)
            url: 対象URL
            site_hints: サイト特性ヒント（前回の操作結果等）

        Returns:
            "lightpanda", "stagehand", "playwright", or "computer_use"
        """
        # Layer 4必須の操作
        if action_type in _LAYER4_ACTIONS:
            if self._computer_use:
                return "computer_use"
            # フォールバック: Layer 3でできる範囲で試行
            if self._playwright:
                return "playwright"

        # SPA検出（site_hintsまたはURL解析）
        hints = site_hints or {}
        is_spa = hints.get("is_spa", False)
        is_heavy = hints.get("is_heavy", False)

        if is_heavy or is_spa:
            # 重いSPA → Layer 3 (Playwright)
            if self._playwright:
                return "playwright"
            if self._stagehand:
                return "stagehand"

        # データ抽出 → Layer 1 (Lightpanda) が最速
        if action_type in ("extract", "extract_text", "extract_links"):
            if self._lightpanda:
                return "lightpanda"
            if self._stagehand:
                return "stagehand"
            if self._playwright:
                return "playwright"

        # AI駆動操作 → Layer 2 (Stagehand)
        if action_type in ("act", "observe", "smart_click", "smart_fill"):
            if self._stagehand:
                return "stagehand"
            if self._playwright:
                return "playwright"

        # デフォルト: 利用可能な最上位レイヤー
        if self._lightpanda:
            return "lightpanda"
        if self._stagehand:
            return "stagehand"
        if self._playwright:
            return "playwright"
        if self._computer_use:
            return "computer_use"

        return "none"

    async def execute(
        self,
        action_type: str,
        url: str,
        params: dict = None,
        site_hints: dict = None,
        force_layer: Optional[str] = None,
    ) -> dict:
        """
        ブラウザ操作を実行（自動レイヤー選択 + フォールバック）

        Args:
            action_type: 操作タイプ
            url: 対象URL
            params: 操作パラメータ
            site_hints: サイト特性ヒント
            force_layer: レイヤー強制指定（テスト用）

        Returns:
            {"success": bool, "layer_used": str, "data": Any, "error": str?}
        """
        action_id = str(uuid.uuid4())[:8]
        params = params or {}

        # レイヤー選択
        chosen = force_layer or self._choose_layer(action_type, url, site_hints)
        fallback_from = None

        # レイヤー順序（上位→下位へフォールバック）
        layer_order = ["lightpanda", "stagehand", "playwright", "computer_use"]
        start_idx = layer_order.index(chosen) if chosen in layer_order else 0

        result = None
        for layer in layer_order[start_idx:]:
            try:
                result = await self._execute_on_layer(layer, action_type, url, params)
                if result and result.get("success"):
                    result["layer_used"] = layer
                    result["fallback_from"] = fallback_from
                    break
                # フォールバック
                fallback_from = layer
                logger.warning(f"Layer '{layer}' 失敗。次のレイヤーへフォールバック")
            except Exception as e:
                logger.error(f"Layer '{layer}' 例外: {e}")
                fallback_from = layer
                continue

        if not result or not result.get("success"):
            result = {
                "success": False,
                "layer_used": "none",
                "fallback_from": fallback_from,
                "error": "全レイヤーで操作失敗",
            }

        # PostgreSQLにログ記録
        await self._log_action(
            action_id=action_id,
            action_type=action_type,
            url=url,
            layer_used=result.get("layer_used", "none"),
            fallback_from=result.get("fallback_from"),
            success=result.get("success", False),
            error_message=result.get("error"),
        )

        # 判断根拠トレース
        try:
            await self._record_trace(
                action=f"browser_execute:{action_type}",
                reasoning=f"レイヤー選択: {chosen} → 使用: {result.get('layer_used', 'none')}, フォールバック: {result.get('fallback_from')}",
                confidence=1.0 if result.get("success") else 0.3,
                context={"url": url, "layer_used": result.get("layer_used"), "success": result.get("success"), "chosen_layer": chosen},
            )
        except Exception:
            pass

        # NATS結果通知
        await self._publish_result(action_id, result)

        return result

    async def _execute_on_layer(
        self, layer: str, action_type: str, url: str, params: dict
    ) -> Optional[dict]:
        """指定レイヤーで操作を実行"""

        if layer == "lightpanda" and self._lightpanda:
            return await self._exec_lightpanda(action_type, url, params)
        elif layer == "stagehand" and self._stagehand:
            return await self._exec_stagehand(action_type, url, params)
        elif layer == "playwright" and self._playwright:
            return await self._exec_playwright(action_type, url, params)
        elif layer == "computer_use" and self._computer_use:
            return await self._exec_computer_use(action_type, url, params)
        return None

    async def _exec_lightpanda(self, action_type: str, url: str, params: dict) -> dict:
        """Layer 1: Lightpandaで実行"""
        try:
            if not await self._lightpanda.navigate(url):
                return {"success": False, "error": "Lightpanda navigate失敗"}

            if action_type in ("extract", "extract_text"):
                text = await self._lightpanda.extract_text()
                return {"success": text is not None, "data": text}

            elif action_type == "extract_links":
                links = await self._lightpanda.extract_links()
                return {"success": True, "data": links}

            elif action_type == "extract_structured":
                selector = params.get("selector", "")
                fields = params.get("fields", {})
                data = await self._lightpanda.extract_structured(selector, fields)
                return {"success": True, "data": data}

            elif action_type == "screenshot":
                img = await self._lightpanda.take_screenshot()
                return {"success": img is not None, "data": img}

            else:
                return {"success": False, "error": f"Lightpandaは '{action_type}' 非対応"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _exec_stagehand(self, action_type: str, url: str, params: dict) -> dict:
        """Layer 2: Stagehandで実行"""
        try:
            if action_type in ("act", "smart_click", "smart_fill"):
                instruction = params.get("instruction", "")
                result = await self._stagehand.act(instruction, url=url)
                return {
                    "success": result is not None and result.get("success", False),
                    "data": result,
                    "stagehand_cache_hit": False,
                }

            elif action_type in ("extract", "extract_text", "extract_structured"):
                schema = params.get("schema", {})
                instruction = params.get("instruction")
                result = await self._stagehand.extract(url, schema, instruction)
                return {"success": result is not None, "data": result}

            elif action_type == "observe":
                instruction = params.get("instruction")
                result = await self._stagehand.observe(url, instruction)
                return {"success": result is not None, "data": result}

            elif action_type == "navigate":
                ok = await self._stagehand.navigate(url)
                return {"success": ok}

            else:
                return {"success": False, "error": f"Stagehandは '{action_type}' 非対応"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _exec_playwright(self, action_type: str, url: str, params: dict) -> dict:
        """Layer 3: Playwrightで実行（subprocess経由でNATSイベントループ競合を回避）"""
        try:
            if action_type in ("navigate", "extract", "extract_text", "extract_links"):
                # subprocess で pw_extract.py を実行（NATSイベントループとの競合回避）
                script = os.path.join(os.path.dirname(__file__), "..", "tools", "pw_extract.py")
                venv_python = os.path.join(os.path.dirname(__file__), "..", "venv", "bin", "python3")
                if not os.path.exists(venv_python):
                    venv_python = "python3"

                proc = await asyncio.create_subprocess_exec(
                    venv_python, script, url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.join(os.path.dirname(__file__), ".."),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=40.0)

                if proc.returncode == 0 and stdout:
                    result = json.loads(stdout.decode().strip())
                    logger.info(f"Playwright extract完了: {url}")
                    return result
                else:
                    err = stderr.decode().strip() if stderr else "unknown error"
                    logger.error(f"Playwright subprocess失敗: {err[:200]}")
                    return {"success": False, "error": err[:200]}
            else:
                return {"success": False, "error": f"Playwrightは '{action_type}' 非対応"}

        except asyncio.TimeoutError:
            logger.error(f"Playwright subprocess タイムアウト: {url}")
            return {"success": False, "error": "Playwright操作タイムアウト(40秒)"}
        except Exception as e:
            logger.error(f"Playwright実行エラー: {e}")
            return {"success": False, "error": str(e)}

    async def _exec_computer_use(self, action_type: str, url: str, params: dict) -> dict:
        """Layer 4: GPT-5.4 Computer Useで実行"""
        try:
            # まずPlaywrightでスクリーンショットを取得
            screenshot = None
            if self._playwright:
                if not await self._playwright.navigate(url):
                    return {"success": False, "error": "ナビゲーション失敗"}
                screenshot = await self._playwright.screenshot_bytes()

            if not screenshot:
                return {"success": False, "error": "スクリーンショット取得失敗"}

            if action_type == "captcha":
                result = await self._computer_use.solve_captcha(screenshot)
                return {"success": result is not None, "data": result}

            elif action_type == "login":
                username = params.get("username", "")
                password_env_key = params.get("password_env_key", "")
                result = await self._computer_use.handle_login(
                    screenshot, username, password_env_key
                )
                return {"success": result is not None, "data": result}

            else:
                instruction = params.get("instruction", f"{action_type} on {url}")
                result = await self._computer_use.execute_task(instruction, screenshot)
                return {"success": result is not None, "data": result}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "BROWSER_AGENT", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def _log_action(
        self,
        action_id: str,
        action_type: str,
        url: str,
        layer_used: str,
        fallback_from: Optional[str],
        success: bool,
        error_message: Optional[str] = None,
    ):
        """操作ログをPostgreSQLのbrowser_action_logに記録"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO browser_action_log
                        (node, action_type, target_url, layer_used,
                         fallback_from, success, error_message)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    self.node, action_type, url, layer_used,
                    fallback_from, success, error_message,
                )
        except Exception as e:
            logger.error(f"ブラウザ操作ログ保存失敗: {e}")

    async def _publish_result(self, action_id: str, result: dict):
        """NATS経由で操作結果を通知"""
        if not self._nats_client:
            return
        try:
            await self._nats_client.publish(
                f"browser.result.{self.node}.{action_id}",
                {
                    "action_id": action_id,
                    "node": self.node,
                    "success": result.get("success", False),
                    "layer_used": result.get("layer_used", "none"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as e:
            logger.error(f"NATS結果通知失敗: {e}")

    async def handle_nats_action(self, msg):
        """NATS経由のブラウザ操作リクエストを処理"""
        result = {"success": False, "error": "unknown"}
        try:
            data = json.loads(msg.data.decode())
            action_type = data.get("action_type", "extract")
            url = data.get("url", "")
            params = data.get("params", {})
            site_hints = data.get("site_hints", {})

            # 45秒タイムアウト（NATS requestのデフォルト60秒より短く）
            result = await asyncio.wait_for(
                self.execute(
                    action_type=action_type,
                    url=url,
                    params=params,
                    site_hints=site_hints,
                ),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.error("ブラウザ操作タイムアウト（45秒）")
            result = {"success": False, "error": "ブラウザ操作タイムアウト（45秒）"}
        except Exception as e:
            logger.error(f"NATSアクションハンドラエラー: {e}")
            result = {"success": False, "error": str(e)}
        finally:
            # 必ずリプライを返す（空結果でもALPHA側がハングしない）
            if msg.reply:
                try:
                    await self._nats_client.nc.publish(
                        msg.reply,
                        json.dumps(result, default=str).encode(),
                    )
                except Exception as e2:
                    logger.error(f"NATSリプライ送信失敗: {e2}")

    async def start_listening(self):
        """NATSサブスクリプション開始（ワーカーモード）"""
        if not self._nats_client:
            logger.error("NATS未接続。NATSリスニングを開始できません")
            return

        # JetStreamストリームBROWSER (browser.>) と衝突しないサブジェクト名を使用
        subject = f"req.browser.{self.node}"
        await self._nats_client.subscribe(subject, self.handle_nats_action)
        logger.info(f"BrowserAgent NATSリスニング開始: {subject}")

    async def close(self):
        """全レイヤーのリソースを解放"""
        try:
            if self._lightpanda:
                await self._lightpanda.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.close()
        except Exception:
            pass
        logger.info("BrowserAgent終了")
