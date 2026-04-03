"""
SYUTAINβ V25 Computer Use ツール (Step 19, Layer 4)
GPT-5.4 Computer Use APIラッパー

スクリーンショットベースの視覚操作。
ログイン画面、CAPTCHA、複雑なUIに対応。
"""

import os
import json
import base64
import asyncio
import logging
from datetime import date
from typing import Optional, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.computer_use")

# APIキーは.envから取得（ハードコード禁止 - CLAUDE.md ルール8）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
COMPUTER_USE_MODEL = os.getenv("COMPUTER_USE_MODEL", "gpt-5.4")

# Computer Use API設定
COMPUTER_USE_MAX_STEPS = int(os.getenv("COMPUTER_USE_MAX_STEPS", "20"))
COMPUTER_USE_TIMEOUT = int(os.getenv("COMPUTER_USE_TIMEOUT", "120"))

# 日次呼び出し上限（設計書 3.4準拠: 30回/日）
COMPUTER_USE_DAILY_LIMIT = int(os.getenv("COMPUTER_USE_DAILY_LIMIT", "30"))
# 1回あたりの概算コスト（円）
COMPUTER_USE_COST_PER_CALL_JPY = float(os.getenv("COMPUTER_USE_COST_PER_CALL_JPY", "13.3"))


class ComputerUseClient:
    """GPT-5.4 Computer Use APIクライアント"""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.model = COMPUTER_USE_MODEL
        self.max_steps = COMPUTER_USE_MAX_STEPS
        # 日次呼び出しカウンタ
        self._daily_count: int = 0
        self._counter_date: date = date.today()

    async def execute_task(
        self,
        instruction: str,
        screenshot: bytes,
        context: Optional[str] = None,
        credentials: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        スクリーンショットベースのComputer Use操作

        Args:
            instruction: 操作指示（自然言語）
            screenshot: 現在画面のスクリーンショット（PNG bytes）
            context: 追加コンテキスト（前回の操作結果等）

        Returns:
            {"actions": [...], "reasoning": "...", "completed": bool}
        """
        if not self.api_key:
            logger.error("OPENAI_API_KEYが設定されていません")
            return None

        # 日次リセット
        today = date.today()
        if today != self._counter_date:
            self._daily_count = 0
            self._counter_date = today

        # 日次上限チェック（設計書 3.4: 30回/日）
        if self._daily_count >= COMPUTER_USE_DAILY_LIMIT:
            logger.warning(f"Computer Use日次上限到達: {self._daily_count}/{COMPUTER_USE_DAILY_LIMIT}")
            try:
                from tools.discord_notify import notify_discord
                asyncio.create_task(notify_discord(
                    f"\u26a0\ufe0f Computer Use日次上限到達（{COMPUTER_USE_DAILY_LIMIT}回）。本日の操作は停止します"
                ))
            except Exception:
                pass
            return None

        # 予算ガードチェック
        try:
            from tools.budget_guard import get_budget_guard
            budget_guard = get_budget_guard()
            budget_check = await budget_guard.check_before_call(COMPUTER_USE_COST_PER_CALL_JPY)
            if not budget_check["allowed"]:
                remaining = budget_check.get("remaining_jpy", "?")
                logger.warning(f"Computer Use: 予算超過でスキップ (残¥{remaining})")
                try:
                    from tools.discord_notify import notify_discord
                    asyncio.create_task(notify_discord(
                        f"⚠️ Computer Use: API予算超過のため操作をスキップ（残予算¥{remaining}、操作コスト¥{COMPUTER_USE_COST_PER_CALL_JPY}）"
                    ))
                except Exception:
                    pass
                return None
        except Exception as e:
            logger.warning(f"Computer Use予算チェック失敗（処理続行）: {e}")

        try:
            import httpx
            # CLAUDE.md ルール5: LLM呼び出し前にchoose_best_model_v6()でモデルを選択
            from tools.llm_router import choose_best_model_v6
            model_selection = choose_best_model_v6(
                task_type="computer_use", needs_computer_use=True
            )
            self.model = model_selection.get("model", COMPUTER_USE_MODEL)

            # スクリーンショットをBase64エンコード
            screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

            # メッセージ構築
            messages = [
                {
                    "role": "system",
                    "content": (
                        "あなたはコンピュータ操作を行うAIアシスタントです。"
                        "スクリーンショットを見て、指示された操作を実行してください。"
                        "操作はマウスクリック、キーボード入力、スクロールなどです。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_b64}",
                            },
                        },
                    ],
                },
            ]

            if context:
                messages[1]["content"].insert(
                    0, {"type": "text", "text": f"前回の操作コンテキスト:\n{context}"}
                )

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 4096,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=float(COMPUTER_USE_TIMEOUT),
                )
                resp.raise_for_status()
                result = resp.json()

            # レスポンス解析
            content = result["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = {"raw_response": content, "actions": [], "completed": False}

            # 呼び出し成功: カウンタ増加＆予算記録
            self._daily_count += 1
            try:
                from tools.budget_guard import get_budget_guard
                budget_guard = get_budget_guard()
                await budget_guard.record_spend(
                    amount_jpy=COMPUTER_USE_COST_PER_CALL_JPY,
                    model="gpt-5.4-computer-use",
                    tier="S",
                )
            except Exception as e_budget:
                logger.warning(f"Computer Use予算記録失敗（処理続行）: {e_budget}")

            logger.info(
                f"Computer Use実行完了: {len(parsed.get('actions', []))}アクション "
                f"(本日{self._daily_count}/{COMPUTER_USE_DAILY_LIMIT}回)"
            )
            return parsed

        except Exception as e:
            logger.error(f"Computer Use API呼び出し失敗: {e}")
            return None

    async def interpret_screen(self, screenshot: bytes, question: str) -> Optional[str]:
        """
        スクリーンショットを見て質問に回答（操作なし・解析のみ）

        Args:
            screenshot: 画面のスクリーンショット
            question: 画面に関する質問
        """
        if not self.api_key:
            logger.error("OPENAI_API_KEYが設定されていません")
            return None

        try:
            import httpx
            screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": question},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{screenshot_b64}",
                                        },
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 2048,
                    },
                    timeout=float(COMPUTER_USE_TIMEOUT),
                )
                resp.raise_for_status()
                result = resp.json()

            answer = result["choices"][0]["message"]["content"]

            # 予算記録（CLAUDE.md ルール7準拠）
            try:
                from tools.budget_guard import get_budget_guard
                bg = get_budget_guard()
                usage = result.get("usage", {})
                # GPT-5.4相当のコスト概算（入力: ¥0.02/1K, 出力: ¥0.08/1K）
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost_jpy = (input_tokens * 0.02 + output_tokens * 0.08) / 1000
                await bg.record_spend(cost_jpy, model=self.model, goal_id="computer_use")
            except Exception:
                pass

            self._daily_count += 1
            return answer

        except Exception as e:
            logger.error(f"画面解析失敗: {e}")
            return None

    async def solve_captcha(self, screenshot: bytes) -> Optional[dict]:
        """
        CAPTCHA解決を試みる

        Args:
            screenshot: CAPTCHAが表示されている画面のスクリーンショット

        Returns:
            {"captcha_type": "...", "solution": "...", "actions": [...]}
        """
        return await self.execute_task(
            instruction=(
                "画面にCAPTCHAが表示されています。"
                "CAPTCHAの種類を特定し、解決するための操作手順を返してください。"
                "テキストCAPTCHAの場合は文字列を読み取ってください。"
                "画像選択CAPTCHAの場合はクリックすべき座標を返してください。"
            ),
            screenshot=screenshot,
        )

    async def handle_login(
        self,
        screenshot: bytes,
        username: str,
        password_env_key: str,
    ) -> Optional[dict]:
        """
        ログイン画面を処理

        パスワードは.envの環境変数キーを指定（直接値を渡さない）

        Args:
            screenshot: ログイン画面のスクリーンショット
            username: ユーザー名
            password_env_key: パスワードが格納されている.envのキー名
        """
        password = os.getenv(password_env_key, "")
        if not password:
            logger.error(f"環境変数 {password_env_key} が設定されていません")
            return None

        # セキュリティ: パスワードをLLMプロンプトに含めない（CLAUDE.md ルール8）
        # LLMにはフィールド特定のみを指示し、入力値は直接ブラウザ操作で注入する
        return await self.execute_task(
            instruction=(
                f"ログイン画面が表示されています。"
                f"ユーザー名フィールドに '{username}' を入力し、"
                f"パスワードフィールドに入力した後、ログインボタンを押してください。"
                f"パスワードは環境変数から自動入力されます。"
            ),
            screenshot=screenshot,
            credentials={"username": username, "password": password},
        )
