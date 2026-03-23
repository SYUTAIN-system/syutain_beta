"""
SYUTAINβ V25 行動エンジン（Executor）— Step 8
設計書 第6章 6.2「③ 行動（Act）」準拠

タスクをツール（LLM、ブラウザ等）で実行し、
中間成果物をDBに保存する。
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client
from tools.budget_guard import get_budget_guard

load_dotenv()

logger = logging.getLogger("syutain.executor")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


class ExecutionResult:
    """タスク実行結果"""

    def __init__(
        self,
        task_id: str,
        status: str = "success",
        output: Optional[dict] = None,
        artifacts: Optional[list] = None,
        cost_jpy: float = 0.0,
        quality_score: float = 0.0,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
        task_type: str = "unknown",
    ):
        self.task_id = task_id
        self.status = status  # success / partial / failure
        self.output = output or {}
        self.artifacts = artifacts or []
        self.cost_jpy = cost_jpy
        self.quality_score = quality_score
        self.error_class = error_class
        self.error_message = error_message
        self.task_type = task_type

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "output": self.output,
            "artifacts": self.artifacts,
            "cost_jpy": self.cost_jpy,
            "quality_score": self.quality_score,
            "error_class": self.error_class,
            "error_message": self.error_message,
        }


class Executor:
    """行動エンジン — タスクの実行と成果物管理"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    async def execute_task(self, task: dict, goal_packet: dict) -> ExecutionResult:
        """
        1タスクを実行する。

        設計書 act_rules:
        - 1アクションにつき1つの明確な成果物を出す
        - 中間成果物はPostgreSQLに保存する
        - 外部API呼び出しは必ずtry-exceptで囲む
        - 実行前にツールの生存確認を行う
        - 承認が必要なアクションはApprovalManagerを通す
        - ローカルLLM呼び出しはchoose_best_model_v6()で選定
        """
        task_id = task.get("task_id", "unknown")
        task_type = task.get("task_type", "drafting")
        description = task.get("description", "")
        assigned_node = task.get("assigned_node", "alpha")

        logger.info(f"タスク実行開始: {task_id} ({task_type}) @ {assigned_node}")
        start_time = time.time()

        # タスクステータスを running に更新
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tasks SET status = 'running', updated_at = NOW() WHERE id = $1",
                        task_id,
                    )
        except Exception as e:
            logger.warning(f"タスクrunningステータス更新失敗 ({task_id}): {e}")

        # 承認チェック（CLAUDE.md ルール11）
        if task.get("needs_approval", False):
            approval_result = await self._request_approval(task)
            if not approval_result.get("approved", False):
                return ExecutionResult(
                    task_id=task_id,
                    status="pending_approval",
                    output={"message": "承認待ち", "approval_id": approval_result.get("approval_id")},
                )

        # タスクタイプに応じた実行
        try:
            if task_type in ["drafting", "content", "analysis", "coding", "research"]:
                result = await self._execute_llm_task(task, goal_packet)
            elif task_type == "browser_action":
                result = await self._execute_browser_task(task)
            elif task_type == "computer_use":
                result = await self._execute_computer_use_task(task)
            elif task_type == "data_extraction":
                result = await self._execute_data_extraction(task)
            elif task_type == "batch_process":
                result = await self._execute_batch_task(task)
            elif task_type == "approval_request":
                result = await self._execute_approval_request(task)
            else:
                result = await self._execute_llm_task(task, goal_packet)

            # 予算記録
            try:
                bg = get_budget_guard()
                await bg.record_spend(
                    amount_jpy=result.cost_jpy,
                    model=task.get("model_selection", {}).get("model", "unknown"),
                    tier=task.get("model_selection", {}).get("tier", "unknown"),
                    goal_id=goal_packet.get("goal_id", ""),
                )
            except Exception as e:
                logger.warning(f"予算記録失敗: {e}")

        except Exception as e:
            error_class = self._classify_error(e)
            logger.error(f"タスク実行失敗 ({task_id}): [{error_class}] {e}")
            result = ExecutionResult(
                task_id=task_id,
                status="failure",
                error_class=error_class,
                error_message=str(e),
                task_type=task_type,
            )

        # task_typeを結果に常に設定（学習ループのmodel_quality_log用）
        result.task_type = task_type

        elapsed = time.time() - start_time

        # 判断根拠を記録
        model_sel = task.get("model_selection") or {}
        await self._record_trace(
            task_id=task_id,
            goal_id=goal_packet.get("goal_id"),
            action="task_execution",
            reasoning=f"タスク{task_type}を{assigned_node}で実行。結果={result.status}, {elapsed:.1f}秒",
            confidence=0.8 if result.status == "success" else 0.3,
            context={
                "assigned_node": assigned_node,
                "node_reason": f"task指定ノード: {assigned_node}",
                "model": model_sel.get("model", "auto"),
                "model_reason": f"tier={model_sel.get('tier', 'auto')}, task_type={task_type}",
                "elapsed_sec": round(elapsed, 1),
                "cost_jpy": result.cost_jpy,
            },
        )

        logger.info(f"タスク実行完了: {task_id} ({result.status}, {elapsed:.1f}秒, ¥{result.cost_jpy:.0f})")

        # 中間成果物をDBに保存（CLAUDE.md ルール18: 途中停止しても資産化）
        await self._save_result(task_id, result, goal_packet.get("goal_id", ""))

        # NATSでステータス通知
        await self._notify_completion(task_id, result)

        return result

    async def _execute_llm_task(self, task: dict, goal_packet: dict) -> ExecutionResult:
        """LLMタスクの実行"""
        task_id = task.get("task_id", "")
        description = task.get("description", "")
        task_type = task.get("task_type", "drafting")

        # モデル選択（CLAUDE.md ルール5）
        model_sel = task.get("model_selection") or choose_best_model_v6(
            task_type=task_type,
            quality="medium",
            budget_sensitive=True,
        )

        # 予算事前チェック
        try:
            bg = get_budget_guard()
            budget_check = await bg.check_before_call(estimated_cost_jpy=5.0)
            if not budget_check["allowed"]:
                # Tier降格を試みる
                model_sel = choose_best_model_v6(
                    task_type=task_type,
                    quality="low",
                    budget_sensitive=True,
                    local_available=True,
                )
        except Exception as e:
            logger.warning(f"予算事前チェック失敗: {e}")

        # LLM呼び出し（try-except: CLAUDE.md ルール7）
        try:
            llm_result = await call_llm(
                prompt=description,
                system_prompt=f"タスク実行: {task_type}。ゴール: {goal_packet.get('raw_goal', '')}",
                model_selection=model_sel,
            )

            if llm_result.get("error"):
                return ExecutionResult(
                    task_id=task_id,
                    status="failure",
                    error_class="model",
                    error_message=llm_result["error"],
                )

            # コスト推定（トークン数ベース）
            prompt_tokens = llm_result.get("prompt_tokens", 0)
            completion_tokens = llm_result.get("completion_tokens", 0)
            cost = self._estimate_cost(model_sel, prompt_tokens, completion_tokens)

            return ExecutionResult(
                task_id=task_id,
                status="success",
                output={
                    "text": llm_result.get("text", ""),
                    "model_used": llm_result.get("model_used", ""),
                    "tokens": prompt_tokens + completion_tokens,
                },
                artifacts=[{"type": "text", "content": llm_result.get("text", "")}],
                cost_jpy=cost,
            )

        except Exception as e:
            raise

    async def _execute_browser_task(self, task: dict) -> ExecutionResult:
        """ブラウザタスクの実行（BRAVO 4層構成: V25）

        URLが指定されている場合はBRAVOにブラウザ操作をディスパッチ。
        URLがない場合やNATS通信失敗時はLLMで情報収集に代替する。
        """
        task_id = task.get("task_id", "")
        description = task.get("description", "")
        input_data = task.get("input_data", {})
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except Exception:
                input_data = {}

        # URLをinput_dataまたはdescriptionから抽出
        url = input_data.get("url", "") or input_data.get("target_url", "")
        if not url:
            # descriptionからURL抽出を試みる
            import re
            urls = re.findall(r'https?://[^\s<>"\']+', description)
            url = urls[0] if urls else ""

        # URLがない場合: LLMで調査代替（ブラウザ不要な情報収集）
        if not url:
            logger.info(f"ブラウザタスク {task_id}: URL未指定、LLM調査で代替")
            return await self._execute_llm_task({
                **task,
                "task_type": "research",
                "description": f"以下のブラウザ操作タスクをWeb検索なしで実行してください: {description}",
            })

        # NATSでBRAVOにブラウザ操作をディスパッチ
        try:
            nats_client = await get_nats_client()
            response = await nats_client.request(
                "req.browser.bravo",
                {
                    "task_id": task_id,
                    "action": description,
                    "url": url,
                    "action_type": input_data.get("action_type", "extract"),
                    "preferred_layer": task.get("browser_layer", "auto"),
                },
                timeout=60.0,
            )

            if response and response.get("success"):
                return ExecutionResult(
                    task_id=task_id,
                    status="success",
                    output=response,
                    artifacts=response.get("artifacts", []),
                )
            else:
                error_msg = response.get("error", "ブラウザ操作失敗") if response else "BRAVO応答なし"
                # ブラウザ失敗時はLLM代替にフォールバック
                logger.warning(f"ブラウザ操作失敗: {error_msg}。LLM代替にフォールバック")
                return await self._execute_llm_task({
                    **task,
                    "task_type": "research",
                    "description": f"以下のブラウザ操作タスクを調査で代替してください（URL: {url}）: {description}",
                })
        except Exception as e:
            logger.warning(f"NATS通信失敗: {e}。LLM代替にフォールバック")
            return await self._execute_llm_task({
                **task,
                "task_type": "research",
                "description": f"以下のブラウザ操作タスクを調査で代替してください: {description}",
            })

    async def _execute_computer_use_task(self, task: dict) -> ExecutionResult:
        """Computer Useタスクの実行（V25: GPT-5.4）"""
        task_id = task.get("task_id", "")

        # Computer Use → 強制GPT-5.4（CLAUDE.md ルール5）
        model_sel = choose_best_model_v6(task_type="computer_use", needs_computer_use=True)

        try:
            nats_client = await get_nats_client()
            response = await nats_client.request(
                "computer.use.bravo",
                {
                    "task_id": task_id,
                    "action": task.get("description", ""),
                    "model": model_sel.get("model", "gpt-5.4"),
                },
                timeout=120.0,
            )

            if response and response.get("success"):
                return ExecutionResult(
                    task_id=task_id,
                    status="success",
                    output=response,
                    cost_jpy=response.get("cost_jpy", 0),
                )
            else:
                return ExecutionResult(
                    task_id=task_id,
                    status="failure",
                    error_class="computer_use",
                    error_message=response.get("error", "Computer Use失敗") if response else "応答なし",
                )
        except Exception as e:
            return ExecutionResult(
                task_id=task_id,
                status="failure",
                error_class="network",
                error_message=f"Computer Use通信失敗: {e}",
            )

    async def _execute_data_extraction(self, task: dict) -> ExecutionResult:
        """データ抽出タスクの実行"""
        # LLMタスクとして実行（簡易実装）
        return await self._execute_llm_task(task, {"goal_id": "", "raw_goal": ""})

    async def _execute_batch_task(self, task: dict) -> ExecutionResult:
        """バッチ処理タスクの実行"""
        return await self._execute_llm_task(task, {"goal_id": "", "raw_goal": ""})

    async def _execute_approval_request(self, task: dict) -> ExecutionResult:
        """承認リクエストタスク"""
        task_id = task.get("task_id", "")

        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO approval_queue (request_type, request_data)
                        VALUES ($1, $2)
                        """,
                        task.get("task_type", "general"),
                        json.dumps(task, ensure_ascii=False, default=str),
                    )
            return ExecutionResult(
                task_id=task_id,
                status="pending_approval",
                output={"message": "承認キューに追加済み"},
            )
        except Exception as e:
            return ExecutionResult(
                task_id=task_id,
                status="failure",
                error_class="auth",
                error_message=f"承認リクエスト失敗: {e}",
            )

    async def _request_approval(self, task: dict) -> dict:
        """ApprovalManager経由で承認を取得（CLAUDE.md ルール11）"""
        try:
            nats_client = await get_nats_client()
            response = await nats_client.request(
                "approval.request",
                {
                    "task_id": task.get("task_id"),
                    "task_type": task.get("task_type"),
                    "description": task.get("description"),
                },
                timeout=5.0,
            )
            return response or {"approved": False}
        except Exception as e:
            logger.warning(f"承認リクエスト失敗: {e}")
            return {"approved": False, "error": str(e)}

    def _classify_error(self, error: Exception) -> str:
        """エラーを分類する"""
        err_str = str(error).lower()
        if "auth" in err_str or "api_key" in err_str or "401" in err_str or "403" in err_str:
            return "auth"
        elif "timeout" in err_str or "timed out" in err_str:
            return "timeout"
        elif "rate" in err_str or "429" in err_str:
            return "budget"
        elif "connection" in err_str or "network" in err_str:
            return "network"
        elif "model" in err_str or "500" in err_str:
            return "model"
        elif "browser" in err_str or "playwright" in err_str:
            return "browser"
        else:
            return "external"

    def _estimate_cost(self, model_sel: dict, prompt_tokens: int, completion_tokens: int) -> float:
        """トークン数からコストを推定（円換算）"""
        tier = model_sel.get("tier", "L")
        if tier == "L":
            return 0.0  # ローカルは無料

        # 概算レート（1M tokensあたりのUSD * 150円/USD / 1,000,000）
        rates = {
            "gpt-5.4": {"input": 2.50, "output": 15.0},
            "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
            "claude-opus-4-6": {"input": 5.0, "output": 25.0},
            "deepseek-v3.2": {"input": 0.28, "output": 0.42},
            "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
            "gpt-5-mini": {"input": 0.25, "output": 2.0},
        }
        model_name = model_sel.get("model", "")
        rate = rates.get(model_name, {"input": 1.0, "output": 5.0})
        usd_per_yen = 150.0

        cost_usd = (prompt_tokens * rate["input"] + completion_tokens * rate["output"]) / 1_000_000
        return round(cost_usd * usd_per_yen, 2)

    async def _record_trace(self, task_id: str, goal_id: str = None, action: str = "",
                           reasoning: str = "", confidence: float = None, context: dict = None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO agent_reasoning_trace
                           (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        "executor", goal_id, task_id, action, reasoning,
                        confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                    )
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    async def _save_result(self, task_id: str, result: ExecutionResult, goal_id: str):
        """実行結果をPostgreSQLに保存（CLAUDE.md ルール18）"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE tasks SET
                            status = $1,
                            output_data = $2,
                            artifacts = $3,
                            cost_jpy = $4,
                            quality_score = $5,
                            updated_at = NOW()
                        WHERE id = $6
                        """,
                        result.status,
                        json.dumps(result.output, ensure_ascii=False, default=str),
                        json.dumps(result.artifacts, ensure_ascii=False, default=str),
                        result.cost_jpy,
                        result.quality_score,
                        task_id,
                    )
        except Exception as e:
            logger.error(f"タスク結果保存失敗 ({task_id}): {e}")

    async def _notify_completion(self, task_id: str, result: ExecutionResult):
        """NATSでタスク完了を通知"""
        try:
            nats_client = await get_nats_client()
            await nats_client.publish(
                f"task.complete.{task_id}",
                {
                    "task_id": task_id,
                    "status": result.status,
                    "cost_jpy": result.cost_jpy,
                },
            )
        except Exception as e:
            logger.warning(f"タスク完了通知失敗 ({task_id}): {e}")

    async def close(self):
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")
