"""
SYUTAINβ V25 GPT-5.4 Computer Useエージェント (Step 19)
スクリーンショットベースの視覚操作エージェント

ログイン画面、CAPTCHA、複雑なUIなど、
従来のセレクタベースの自動操作では対応困難な場面で使用。
BrowserAgent Layer 4から呼び出される。
"""

import os
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.computer_use_agent")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
THIS_NODE = os.getenv("THIS_NODE", "bravo")

# マルチステップ操作の最大ステップ数
MAX_STEPS = int(os.getenv("COMPUTER_USE_MAX_STEPS", "20"))


class ComputerUseAgent:
    """
    GPT-5.4 Computer Use エージェント

    スクリーンショットを撮影→GPT-5.4に送信→操作指示を取得→実行
    のループを繰り返し、目標達成まで自律的に操作する。
    """

    def __init__(self):
        self.node = THIS_NODE
        self._cu_client = None
        self._playwright = None
        self._nats_client = None

    async def initialize(self) -> bool:
        """エージェントを初期化"""
        try:
            from tools.computer_use_tools import ComputerUseClient
            self._cu_client = ComputerUseClient()
            if not self._cu_client.api_key:
                logger.warning("OPENAI_API_KEY未設定。Computer Useエージェントは無効")
                return False
        except Exception as e:
            logger.error(f"ComputerUseClient初期化失敗: {e}")
            return False

        # Playwright（スクリーンショット取得用）
        try:
            from tools.playwright_tools import PlaywrightBrowser
            self._playwright = PlaywrightBrowser()
            if not await self._playwright.launch():
                logger.error("Playwright起動失敗")
                return False
        except Exception as e:
            logger.error(f"Playwright初期化失敗: {e}")
            return False

        # NATS
        try:
            from tools.nats_client import get_nats_client
            self._nats_client = await get_nats_client()
        except Exception as e:
            logger.warning(f"NATS接続スキップ: {e}")

        logger.info("ComputerUseAgent初期化完了")
        return True

    async def execute_multi_step(
        self,
        goal: str,
        start_url: str,
        max_steps: Optional[int] = None,
    ) -> dict:
        """
        マルチステップ視覚操作を実行

        GPT-5.4にスクリーンショットを見せながら、
        目標達成まで繰り返しアクションを実行する。

        Args:
            goal: 達成すべき目標（自然言語）
            start_url: 開始URL
            max_steps: 最大ステップ数

        Returns:
            {"success": bool, "steps_taken": int, "final_url": str, "history": [...]}
        """
        steps = max_steps or MAX_STEPS
        history = []
        context = ""

        # 開始URLへナビゲート
        try:
            if not await self._playwright.navigate(start_url):
                return {"success": False, "steps_taken": 0, "error": "初期ナビゲート失敗"}
        except Exception as e:
            return {"success": False, "steps_taken": 0, "error": str(e)}

        for step in range(steps):
            try:
                # スクリーンショット取得
                screenshot = await self._playwright.screenshot_bytes()
                if not screenshot:
                    logger.error(f"ステップ {step+1}: スクリーンショット取得失敗")
                    break

                # GPT-5.4に操作指示を要求
                instruction = (
                    f"目標: {goal}\n"
                    f"現在のステップ: {step+1}/{steps}\n"
                    f"これまでの操作:\n{context}\n"
                    f"画面を見て、次に実行すべき操作を返してください。"
                    f"目標が達成されていれば {{\"completed\": true}} を返してください。"
                )

                result = await self._cu_client.execute_task(
                    instruction=instruction,
                    screenshot=screenshot,
                    context=context,
                )

                if not result:
                    logger.error(f"ステップ {step+1}: Computer Use API応答なし")
                    break

                # 操作完了チェック
                if result.get("completed", False):
                    logger.info(f"目標達成（ステップ {step+1}）")
                    history.append({"step": step + 1, "action": "completed", "result": result})
                    # 判断根拠トレース
                    try:
                        await self._record_trace(
                            action="execute_multi_step:completed",
                            reasoning=f"目標達成（ステップ {step+1}）。ゴール: {goal[:80]}",
                            confidence=0.9,
                            context={"goal": goal[:200], "start_url": start_url, "steps_taken": step + 1, "success": True},
                        )
                    except Exception:
                        pass
                    return {
                        "success": True,
                        "steps_taken": step + 1,
                        "final_url": await self._playwright.get_current_url(),
                        "history": history,
                    }

                # アクションを実行
                actions = result.get("actions", [])
                for action in actions:
                    await self._execute_action(action)

                history.append({"step": step + 1, "actions": actions, "reasoning": result.get("reasoning", "")})
                context += f"\nステップ{step+1}: {json.dumps(actions, ensure_ascii=False)}"

                # 短いウェイト（ページ遷移を待つ）
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"ステップ {step+1} 例外: {e}")
                history.append({"step": step + 1, "error": str(e)})
                break

        # 最大ステップ到達
        result = {
            "success": False,
            "steps_taken": len(history),
            "final_url": await self._playwright.get_current_url() if self._playwright else None,
            "history": history,
            "error": f"最大ステップ数 ({steps}) に到達",
        }

        # 判断根拠トレース
        try:
            await self._record_trace(
                action="execute_multi_step:max_steps",
                reasoning=f"目標未達成で最大ステップ({steps})に到達。ゴール: {goal[:80]}",
                confidence=0.2,
                context={"goal": goal[:200], "start_url": start_url, "steps_taken": len(history), "success": False},
            )
        except Exception:
            pass

        return result

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "COMPUTER_USE_AGENT", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def _execute_action(self, action: dict):
        """単一アクションを実行"""
        action_type = action.get("type", "")

        try:
            if action_type == "click":
                x = action.get("x", 0)
                y = action.get("y", 0)
                await self._playwright.page.mouse.click(x, y)

            elif action_type == "type":
                text = action.get("text", "")
                await self._playwright.page.keyboard.type(text, delay=50)

            elif action_type == "press":
                key = action.get("key", "Enter")
                await self._playwright.page.keyboard.press(key)

            elif action_type == "scroll":
                direction = action.get("direction", "down")
                amount = action.get("amount", 300)
                delta = amount if direction == "down" else -amount
                await self._playwright.page.mouse.wheel(0, delta)

            elif action_type == "navigate":
                url = action.get("url", "")
                await self._playwright.navigate(url)

            elif action_type == "wait":
                duration = action.get("duration", 1.0)
                await asyncio.sleep(min(duration, 5.0))  # 最大5秒

            else:
                logger.warning(f"未知のアクションタイプ: {action_type}")

        except Exception as e:
            logger.error(f"アクション実行失敗 ({action_type}): {e}")

    async def handle_login(
        self,
        url: str,
        username: str,
        password_env_key: str,
    ) -> dict:
        """
        ログイン操作を実行

        Args:
            url: ログインページURL
            username: ユーザー名
            password_env_key: パスワードが格納されている.envのキー名
        """
        password = os.getenv(password_env_key, "")
        if not password:
            return {"success": False, "error": f"環境変数 {password_env_key} 未設定"}

        # セキュリティ: パスワードをLLMプロンプトに含めない（CLAUDE.md ルール8）
        return await self.execute_multi_step(
            goal=f"ユーザー名 '{username}' でログインする。パスワードは環境変数から自動入力される。",
            start_url=url,
            max_steps=5,
            credentials={"username": username, "password": password},
        )

    async def handle_captcha(self, url: str) -> dict:
        """CAPTCHA解決を試みる"""
        return await self.execute_multi_step(
            goal="画面に表示されているCAPTCHAを解決する",
            start_url=url,
            max_steps=3,
        )

    async def analyze_page(self, url: str, question: str) -> Optional[str]:
        """ページのスクリーンショットを見て質問に回答"""
        try:
            if not await self._playwright.navigate(url):
                return None
            screenshot = await self._playwright.screenshot_bytes()
            if not screenshot:
                return None
            return await self._cu_client.interpret_screen(screenshot, question)
        except Exception as e:
            logger.error(f"ページ分析失敗: {e}")
            return None

    async def handle_nats_request(self, msg):
        """NATS経由のComputer Useリクエストを処理"""
        try:
            data = json.loads(msg.data.decode())
            request_type = data.get("type", "multi_step")

            if request_type == "multi_step":
                result = await self.execute_multi_step(
                    goal=data.get("goal", ""),
                    start_url=data.get("url", ""),
                    max_steps=data.get("max_steps"),
                )
            elif request_type == "login":
                result = await self.handle_login(
                    url=data.get("url", ""),
                    username=data.get("username", ""),
                    password_env_key=data.get("password_env_key", ""),
                )
            elif request_type == "captcha":
                result = await self.handle_captcha(url=data.get("url", ""))
            elif request_type == "analyze":
                answer = await self.analyze_page(
                    url=data.get("url", ""),
                    question=data.get("question", ""),
                )
                result = {"success": answer is not None, "answer": answer}
            else:
                result = {"success": False, "error": f"未知のリクエストタイプ: {request_type}"}

            if msg.reply:
                await self._nats_client.nc.publish(
                    msg.reply,
                    json.dumps(result, default=str).encode(),
                )
        except Exception as e:
            logger.error(f"NATSリクエストハンドラエラー: {e}")

    async def start_listening(self):
        """NATSサブスクリプション開始"""
        if not self._nats_client:
            logger.error("NATS未接続")
            return
        subject = f"computer.action.{self.node}"
        await self._nats_client.subscribe(subject, self.handle_nats_request)
        logger.info(f"ComputerUseAgent NATSリスニング開始: {subject}")

    async def close(self):
        """リソースを解放"""
        try:
            if self._playwright:
                await self._playwright.close()
        except Exception:
            pass
        logger.info("ComputerUseAgent終了")
