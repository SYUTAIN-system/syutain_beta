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

import yaml
from dotenv import load_dotenv

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client
from tools.budget_guard import get_budget_guard
from tools.failure_memory import record_failure, check_similar_failures
from tools.episodic_memory import get_episodic_memory
from tools.harness_linter import (
    APPROVAL_REQUIRED_ACTIONS,
    lint_output_content,
    lint_task_execution,
    sanitize_output,
)
from tools.skill_manager import get_skill_manager

load_dotenv()

logger = logging.getLogger("syutain.executor")

# ツール権限レベルのロード
_TOOL_PERMISSIONS: dict = {}


def _load_tool_permissions() -> dict:
    """config/tool_permissions.yaml からツール権限マップを読み込む"""
    global _TOOL_PERMISSIONS
    if _TOOL_PERMISSIONS:
        return _TOOL_PERMISSIONS
    try:
        permissions_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "tool_permissions.yaml"
        )
        with open(permissions_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        perms = data.get("permissions", {})
        # ツール名 → 権限レベルの逆引きマップを生成
        tool_map = {}
        for level in ("read", "write", "dangerous"):
            for tool_name in perms.get(level, []):
                tool_map[tool_name] = level
        _TOOL_PERMISSIONS = tool_map
        return tool_map
    except Exception as e:
        logger.warning(f"ツール権限設定読み込み失敗（デフォルトwrite適用）: {e}")
        return {}


def get_tool_permission_level(task_type: str) -> str:
    """タスクタイプからツール権限レベルを判定する。

    Returns:
        "read", "write", or "dangerous"
    """
    tool_map = _load_tool_permissions()
    # task_typeがツール名に直接対応しない場合のマッピング
    task_to_tool = {
        "browser_action": "browser_ops",
        "computer_use": "computer_use_tools",
        "research": "tavily_client",
        "analysis": "analytics_tools",
        "drafting": "content_tools",
        "content": "content_tools",
        "coding": "content_tools",
        "data_extraction": "info_pipeline",
        "monitoring": "api_quota_monitor",
        "batch_process": "content_tools",
        "approval_request": "event_logger",
    }
    tool_name = task_to_tool.get(task_type, task_type)
    return tool_map.get(tool_name, "write")


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
        pass

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

        # ツール権限レベルチェック
        permission_level = get_tool_permission_level(task_type)
        logger.info(f"タスク {task_id} 権限レベル: {permission_level}")
        if permission_level == "dangerous" and not task.get("needs_approval", False):
            # dangerousツールは承認必須に強制
            task["needs_approval"] = True
            logger.warning(f"タスク {task_id}: dangerousツール使用のため承認を強制")
        if task_type in APPROVAL_REQUIRED_ACTIONS and not task.get("needs_approval", False):
            task["needs_approval"] = True
            logger.warning(
                f"タスク {task_id}: {task_type} は承認必須のため needs_approval を強制"
            )
        # 権限レベルをevent_logに記録
        try:
            from tools.event_logger import log_event
            await log_event(
                "tool.permission_check", "system",
                {"task_id": task_id, "task_type": task_type, "permission_level": permission_level},
                severity="info",
                task_id=task_id,
                goal_id=goal_packet.get("goal_id", ""),
            )
        except Exception:
            pass

        # タスクステータスを running に更新
        try:
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE tasks SET status = 'running', updated_at = NOW() WHERE id = $1",
                    task_id,
                )
        except Exception as e:
            logger.warning(f"タスクrunningステータス更新失敗 ({task_id}): {e}")

        # 失敗記憶チェック（Harness Engineering: 類似失敗の防止策を注入）
        prevention_rules = []
        try:
            similar_failures = await check_similar_failures(
                f"{task_type} {description}", threshold=0.75
            )
            if similar_failures:
                prevention_rules = [
                    f"[{f['failure_type']}] {f['prevention_rule']}"
                    for f in similar_failures
                    if f.get("prevention_rule")
                ]
                if prevention_rules:
                    task["_prevention_rules"] = prevention_rules
                    logger.info(
                        f"タスク {task_id} に防止策{len(prevention_rules)}件を注入"
                    )
        except Exception as e:
            logger.debug(f"失敗記憶チェック失敗（無視）: {e}")

        # エピソード記憶検索（MemRL: 成功+失敗の教訓をQ値順で注入）
        retrieved_episodes = []
        try:
            em = get_episodic_memory()
            episodes = await em.retrieve_relevant(
                f"{task_type} {description}", task_type=task_type, top_k=3
            )
            if episodes:
                episode_lessons = []
                for ep in episodes:
                    if ep.get("lessons"):
                        episode_lessons.append(
                            f"[{ep['outcome']}|q={ep['q_value']:.2f}] {ep['lessons']}"
                        )
                    retrieved_episodes.append(ep)
                if episode_lessons:
                    task["_episode_lessons"] = episode_lessons
                    logger.info(
                        f"タスク {task_id} にエピソード記憶{len(episode_lessons)}件を注入"
                    )
        except Exception as e:
            logger.debug(f"エピソード記憶検索失敗（無視）: {e}")

        # スキル検索（高Q値エピソードから抽出された再利用パターンを注入）
        try:
            sm = get_skill_manager()
            applicable_skills = await sm.get_applicable_skills(task_type, description)
            if applicable_skills:
                skill_rules = [
                    f"[skill|conf={s['confidence']:.2f}] {s['rule']}"
                    for s in applicable_skills
                ]
                task["_skill_rules"] = skill_rules
                task["_skill_ids"] = [s["id"] for s in applicable_skills]
                logger.info(
                    f"タスク {task_id} にスキル{len(skill_rules)}件を注入"
                )
        except Exception as e:
            logger.debug(f"スキル検索失敗（無視）: {e}")

        # 承認チェック（CLAUDE.md ルール11）
        if task.get("needs_approval", False):
            approval_result = await self._request_approval(task)
            if not approval_result.get("approved", False):
                return ExecutionResult(
                    task_id=task_id,
                    status="pending_approval",
                    output={"message": "承認待ち", "approval_id": approval_result.get("approval_id")},
                )
            task["approval_id"] = approval_result.get("approval_id")

        # ===== browser_action URL事前チェック =====
        # URLがないbrowser_actionタスクはBRAVOにディスパッチせずローカルLLM代替
        if task_type == "browser_action":
            import re as _re
            _input_data = task.get("input_data", {})
            if isinstance(_input_data, str):
                try:
                    _input_data = json.loads(_input_data)
                except Exception:
                    _input_data = {}
            _url = (_input_data.get("url", "") or _input_data.get("target_url", "")
                    or ((_re.findall(r'https?://[^\s<>"\']+', description) or [""])[0]))
            if not _url:
                logger.warning(f"browser_actionタスク {task_id}: URL未指定のためBRAVOディスパッチをスキップ、ローカルLLM代替")
                assigned_node = "alpha"

        # ===== リモートノードディスパッチ（CLAUDE.md ルール19: NATSでノード間通信）=====
        # assigned_nodeがalpha以外の場合、NATSでリモートノードにタスクをディスパッチし、
        # request-replyで結果を受け取る。失敗時はALPHAローカル実行にフォールバック。
        this_node = os.getenv("THIS_NODE", "alpha")
        if assigned_node not in ("alpha", this_node, "", None):
            try:
                nats_client = await get_nats_client()
                nats_payload = {
                    "task_id": task_id,
                    "type": task_type,
                    "prompt": description,
                    "system_prompt": f"タスク実行: {task_type}。ゴール: {goal_packet.get('raw_goal', '')}",
                    "action": "dispatch",
                    "goal_id": goal_packet.get("goal_id", ""),
                }
                logger.info(f"タスク {task_id} をリモートノード {assigned_node} にNATSディスパッチ")
                # req.task.* はJetStreamストリーム外のCore NATS subjects
                # task.assign.* はJetStream TASKSストリーム(task.>)に捕捉されるため
                # request-replyにはreq.*プレフィックスを使用
                response = await nats_client.request(
                    f"req.task.{assigned_node}",
                    nats_payload,
                    timeout=180.0,
                )
                if response and response.get("status") == "success":
                    remote_output = response.get("output", {})
                    result = ExecutionResult(
                        task_id=task_id,
                        status="success",
                        output=remote_output if isinstance(remote_output, dict) else {"text": str(remote_output)},
                        artifacts=response.get("artifacts", []),
                        cost_jpy=response.get("cost_jpy", 0.0),
                        task_type=task_type,
                    )
                    logger.info(f"リモートノード {assigned_node} からの応答: success")
                elif response and response.get("status") == "error":
                    raise RuntimeError(f"リモートノード {assigned_node} エラー: {response.get('error', 'unknown')}")
                else:
                    raise RuntimeError(f"リモートノード {assigned_node} から無効な応答: {response}")
            except Exception as e:
                logger.warning(
                    f"リモートディスパッチ失敗 ({assigned_node}): {e}。ALPHAローカル実行にフォールバック"
                )
                # フォールバック: ALPHAローカルで実行（CLAUDE.md ルール17）
                result = await self._execute_task_locally(task, task_type, goal_packet)
        else:
            # ALPHAローカル実行
            result = await self._execute_task_locally(task, task_type, goal_packet)

        # 共通後処理: 予算記録
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

        # task_typeを結果に常に設定（学習ループのmodel_quality_log用）
        result.task_type = task_type

        elapsed = time.time() - start_time
        harness_lint_summary = await self._apply_harness_lint(
            task=task,
            task_type=task_type,
            result=result,
            goal_id=goal_packet.get("goal_id", ""),
        )

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
                "harness_lint": {
                    "violations": harness_lint_summary.get("violation_count", 0),
                    "warnings": harness_lint_summary.get("warning_count", 0),
                    "sanitized": harness_lint_summary.get("sanitized", False),
                },
            },
        )

        logger.info(f"タスク実行完了: {task_id} ({result.status}, {elapsed:.1f}秒, ¥{result.cost_jpy:.0f})")

        # event_logにタスク完了の構造化サマリーを記録
        try:
            from tools.event_logger import log_event
            output_text = ""
            if result.output and isinstance(result.output, dict):
                output_text = result.output.get("text", "") or result.output.get("message", "") or result.output.get("summary", "")
            elif result.error_message:
                output_text = result.error_message
            await log_event(
                "task.completed", "task",
                {
                    "task_id": task_id,
                    "task_type": task_type,
                    "assigned_node": assigned_node,
                    "model_used": model_sel.get("model", "unknown") if model_sel else "unknown",
                    "duration_sec": round(elapsed, 1),
                    "output_summary": str(output_text)[:200],
                    "status": result.status,
                    "cost_jpy": result.cost_jpy,
                    "error_class": result.error_class,
                    "harness_lint": {
                        "violation_count": harness_lint_summary.get("violation_count", 0),
                        "warning_count": harness_lint_summary.get("warning_count", 0),
                        "sanitized": harness_lint_summary.get("sanitized", False),
                    },
                },
                severity="info" if result.status == "success" else "warning",
                goal_id=goal_packet.get("goal_id", ""),
                task_id=task_id,
            )
        except Exception:
            pass

        # Discord通知（成功/失敗）
        try:
            if result.status == "success":
                from tools.discord_notify import notify_task_complete
                summary = result.output.get("summary", description[:100]) if result.output else description[:100]
                await notify_task_complete(f"{task_type}:{task_id}", summary)
            elif result.status == "failure":
                from tools.discord_notify import notify_task_failed
                await notify_task_failed(f"{task_type}:{task_id}", result.error_message or "不明")
        except Exception:
            pass

        # 中間成果物をDBに保存（CLAUDE.md ルール18: 途中停止しても資産化）
        goal_id = goal_packet.get("goal_id", "")
        await self._save_result(task_id, result, goal_id)

        # エピソード記憶に記録（MemRL: 成功も失敗も学習資産化）
        try:
            em = get_episodic_memory()
            outcome_map = {"success": "success", "failure": "failure", "partial": "partial"}
            ep_outcome = outcome_map.get(result.status, "partial")
            # lessonsを簡潔に生成
            ep_lessons = None
            if result.status == "failure" and result.error_message:
                ep_lessons = f"失敗: {result.error_message[:200]}"
            elif result.status == "success" and result.output:
                summary = result.output.get("summary", "") or result.output.get("text", "")
                if summary:
                    ep_lessons = f"成功: {str(summary)[:200]}"
            ep_quality = float(result.quality_score) if result.quality_score else 0.5
            ep_desc = (description or task_type)[:500]
            episode_id = await em.record_episode(
                task_type=task_type,
                description=ep_desc,
                outcome=ep_outcome,
                context={
                    "task_id": task_id,
                    "goal_id": goal_id,
                    "assigned_node": assigned_node,
                    "model": (task.get("model_selection") or {}).get("model"),
                    "cost_jpy": result.cost_jpy,
                },
                quality_score=ep_quality,
                lessons=ep_lessons,
            )
            # Q値フィードバック: 検索で注入されたエピソードが役立ったか判定
            if retrieved_episodes and result.status == "success":
                for ep in retrieved_episodes:
                    await em.update_q_value(ep["id"], was_helpful=True)
            elif retrieved_episodes and result.status == "failure":
                for ep in retrieved_episodes:
                    await em.update_q_value(ep["id"], was_helpful=False)
        except Exception as e:
            logger.warning(f"エピソード記憶記録失敗: {e}")

        # progress_logにステップ記録を追記（Harness Engineering）
        step_number = goal_packet.get("total_steps", 0)
        await self._append_progress_log(goal_id, task_id, result, step_number=step_number)

        # NATSでステータス通知
        await self._notify_completion(task_id, result)

        return result

    async def _execute_task_locally(self, task: dict, task_type: str, goal_packet: dict) -> ExecutionResult:
        """タスクをALPHAローカルで実行する（タスクタイプに応じたディスパッチ）"""
        task_id = task.get("task_id", "unknown")
        assigned_node = task.get("assigned_node", "alpha")
        description = task.get("description", "")

        try:
            if task_type in ["drafting", "content", "analysis", "coding", "research"]:
                result = await self._execute_llm_task(task, goal_packet)
            elif task_type == "browser_action":
                result = await self._execute_browser_task(task, goal_packet)
            elif task_type == "computer_use":
                result = await self._execute_computer_use_task(task, goal_packet)
            elif task_type == "data_extraction":
                result = await self._execute_data_extraction(task, goal_packet)
            elif task_type == "batch_process":
                result = await self._execute_batch_task(task, goal_packet)
            elif task_type == "approval_request":
                result = await self._execute_approval_request(task, goal_packet)
            else:
                result = await self._execute_llm_task(task, goal_packet)
            return result
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
            # 失敗記憶に記録（Harness Engineering）
            try:
                await record_failure(
                    failure_type="task_error",
                    error_message=str(e),
                    context={
                        "task_id": task_id,
                        "goal_id": goal_packet.get("goal_id"),
                        "assigned_node": assigned_node,
                        "error_class": error_class,
                        "model": task.get("model_selection", {}).get("model"),
                        "description": description[:300],
                    },
                    task_type=task_type,
                )
            except Exception as fm_err:
                logger.debug(f"失敗記憶記録失敗（無視）: {fm_err}")
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
            local_available=True,
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
                    "model_selection": model_sel,  # verifier品質ログ用
                },
                artifacts=[{"type": "text", "content": llm_result.get("text", "")}],
                cost_jpy=cost,
            )

        except Exception as e:
            logger.error(f"LLMタスク実行失敗 ({task.get('task_id', '?')}): [{type(e).__name__}] {e}")
            raise

    async def _execute_browser_task(self, task: dict, goal_packet: dict = None) -> ExecutionResult:
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
            }, goal_packet or {"goal_id": "", "raw_goal": ""})

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
                }, goal_packet or {"goal_id": "", "raw_goal": ""})
        except Exception as e:
            logger.warning(f"NATS通信失敗: {e}。LLM代替にフォールバック")
            return await self._execute_llm_task({
                **task,
                "task_type": "research",
                "description": f"以下のブラウザ操作タスクを調査で代替してください: {description}",
            }, goal_packet or {"goal_id": "", "raw_goal": ""})

    async def _execute_computer_use_task(self, task: dict, goal_packet: dict = None) -> ExecutionResult:
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

    async def _execute_data_extraction(self, task: dict, goal_packet: dict = None) -> ExecutionResult:
        """データ抽出タスクの実行"""
        return await self._execute_llm_task(task, goal_packet or {"goal_id": "", "raw_goal": ""})

    async def _execute_batch_task(self, task: dict, goal_packet: dict = None) -> ExecutionResult:
        """バッチ処理タスクの実行"""
        return await self._execute_llm_task(task, goal_packet or {"goal_id": "", "raw_goal": ""})

    async def _execute_approval_request(self, task: dict, goal_packet: dict = None) -> ExecutionResult:
        """承認リクエストタスク"""
        task_id = task.get("task_id", "")

        try:
            async with get_connection() as conn:
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

    async def _apply_harness_lint(
        self,
        task: dict,
        task_type: str,
        result: ExecutionResult,
        goal_id: str = "",
    ) -> dict:
        """実行結果にHarness Linterを適用し、必要なら秘匿情報をマスクする。"""
        summary = {
            "passed": True,
            "violation_count": 0,
            "warning_count": 0,
            "sanitized": False,
        }
        try:
            output_text = self._extract_primary_output_text(result)
            platform = task.get("platform")
            input_data = task.get("input_data")
            if isinstance(input_data, dict):
                platform = input_data.get("platform", platform)

            output_dict = result.output if isinstance(result.output, dict) else {}
            model_used = (
                output_dict.get("model_used")
                or (output_dict.get("model_selection") or {}).get("model", "")
                or (task.get("model_selection") or {}).get("model", "")
            )
            model_selection_method = (
                output_dict.get("model_selection_method")
                or (task.get("model_selection") or {}).get("selection_method")
                or task.get("model_selection_method")
                or ("v6" if model_used else None)
            )

            exec_lint = lint_task_execution(
                task_type=task_type,
                model_used=model_used or None,
                model_selection_method=model_selection_method,
                has_error_handling=True,
                output_text=output_text,
                log_text=result.error_message,
                approval_id=task.get("approval_id"),
                config_source=task.get("config_source", "env"),
                strategy_referenced=bool(task.get("strategy_referenced", True)),
            )
            content_lint = lint_output_content(output_text, platform=platform)

            violations = exec_lint.violations + content_lint.violations
            warnings = exec_lint.warnings + content_lint.warnings
            should_sanitize = self._has_secret_violation(violations)

            if should_sanitize:
                self._sanitize_execution_result(result)

            summary = {
                "passed": len(violations) == 0,
                "violation_count": len(violations),
                "warning_count": len(warnings),
                "sanitized": should_sanitize,
            }
            if isinstance(result.output, dict):
                result.output["harness_lint"] = summary

            if violations or warnings:
                from tools.event_logger import log_event
                await log_event(
                    "harness_lint.task_execution",
                    "harness",
                    {
                        "task_type": task_type,
                        "status": result.status,
                        "violations": violations,
                        "warnings": warnings,
                        "sanitized": should_sanitize,
                    },
                    severity="critical" if violations else "warning",
                    goal_id=goal_id or None,
                    task_id=task.get("task_id"),
                )
        except Exception as e:
            logger.warning(f"Harnessリント適用失敗（継続）: {e}")

        return summary

    def _extract_primary_output_text(self, result: ExecutionResult) -> str:
        """結果ペイロードから代表テキストを抽出する。"""
        if isinstance(result.output, dict):
            for key in ("text", "message", "summary"):
                value = result.output.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return result.error_message or ""

    def _sanitize_execution_result(self, result: ExecutionResult):
        """ExecutionResult内の文字列を再帰的にマスクする。"""
        result.output = self._sanitize_value(result.output)
        result.artifacts = self._sanitize_value(result.artifacts)
        if result.error_message:
            result.error_message = sanitize_output(result.error_message)

    def _sanitize_value(self, value):
        """dict/list/str を再帰的に走査して秘匿情報をマスクする。"""
        if isinstance(value, str):
            return sanitize_output(value)
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._sanitize_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def _has_secret_violation(violations: list[dict]) -> bool:
        """違反一覧に秘密情報露出系違反が含まれるか判定する。"""
        for violation in violations:
            rule = violation.get("rule")
            message = violation.get("message", "")
            if rule == 8 or "APIキー" in message or "シークレット" in message:
                return True
        return False

    async def _request_approval(self, task: dict) -> dict:
        """ApprovalManager経由で承認を取得（CLAUDE.md ルール11）"""
        try:
            from agents.approval_manager import ApprovalManager
            am = ApprovalManager()
            await am.initialize()
            response = await am.request_approval(
                request_type=task.get("task_type", "unknown"),
                request_data={
                    "task_id": task.get("task_id"),
                    "description": task.get("description", ""),
                },
            )
            await am.close()
            # ApprovalManagerのレスポンス: status="approved"(Tier2/3) or "pending"(Tier1)
            if response.get("status") in ("approved", "auto_approved"):
                return {"approved": True, "approval_id": response.get("approval_id")}
            else:
                return {"approved": False, "approval_id": response.get("approval_id"),
                        "status": response.get("status", "pending")}
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
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "executor", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    async def _append_progress_log(self, goal_id: str, task_id: str, result: ExecutionResult,
                                   step_number: int = 0):
        """goal_packetsのprogress_logにステップ記録を追記（Harness Engineering）"""
        try:
            now = datetime.now()
            # output_summaryを簡潔に生成
            output_summary = ""
            if result.output and isinstance(result.output, dict):
                text = result.output.get("text", "") or result.output.get("message", "")
                output_summary = text[:150] if text else ""
            elif result.error_message:
                output_summary = result.error_message[:150]

            progress_entry = {
                "step": step_number,
                "timestamp": now.isoformat(),
                "action": result.task_type,
                "status": result.status,
                "output_summary": output_summary,
                "node": os.getenv("THIS_NODE", "alpha"),
                "task_id": task_id,
                "cost_jpy": result.cost_jpy,
            }

            async with get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE goal_packets
                    SET progress_log = COALESCE(progress_log, '[]'::jsonb) || $1::jsonb
                    WHERE goal_id = $2
                    """,
                    json.dumps([progress_entry], ensure_ascii=False, default=str),
                    goal_id,
                )
        except Exception as e:
            logger.debug(f"progress_log追記失敗（無視）: {e}")

    async def _save_result(self, task_id: str, result: ExecutionResult, goal_id: str):
        """実行結果をPostgreSQLに保存（CLAUDE.md ルール18）"""
        try:
            async with get_connection() as conn:
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
        pass
