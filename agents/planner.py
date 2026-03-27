"""
SYUTAINβ V25 Task Graph Planner（思考・計画エンジン）— Step 8
設計書 第6章 6.2「② 思考（Think）」準拠

パースされたゴールをタスクDAGに分解し、
Capability Auditの結果に基づいて適切なノードにタスクを割り当てる。
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client

load_dotenv()

logger = logging.getLogger("syutain.planner")

# タスクタイプ定義
TASK_TYPES = [
    "research", "analysis", "content", "drafting", "coding",
    "browser_action", "computer_use", "approval_request",
    "batch_process", "data_extraction", "monitoring",
]


class TaskNode:
    """タスクDAGの1ノード"""

    def __init__(
        self,
        task_id: str,
        task_type: str,
        description: str,
        assigned_node: str = "auto",
        model_selection: Optional[dict] = None,
        depends_on: Optional[list[str]] = None,
        needs_approval: bool = False,
        estimated_cost_jpy: float = 0.0,
        estimated_time_min: float = 5.0,
        browser_layer: Optional[str] = None,
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.description = description
        self.assigned_node = assigned_node
        self.model_selection = model_selection
        self.depends_on = depends_on or []
        self.needs_approval = needs_approval
        self.estimated_cost_jpy = estimated_cost_jpy
        self.estimated_time_min = estimated_time_min
        self.browser_layer = browser_layer  # V25: lightpanda/stagehand/chromium/computer_use
        self.status = "pending"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "assigned_node": self.assigned_node,
            "model_selection": self.model_selection,
            "depends_on": self.depends_on,
            "needs_approval": self.needs_approval,
            "estimated_cost_jpy": self.estimated_cost_jpy,
            "estimated_time_min": self.estimated_time_min,
            "browser_layer": self.browser_layer,
            "status": self.status,
        }


class TaskGraph:
    """タスクDAG"""

    def __init__(self, goal_id: str):
        self.goal_id = goal_id
        self.nodes: dict[str, TaskNode] = {}
        self.execution_order: list[str] = []

    def add_task(self, task: TaskNode):
        self.nodes[task.task_id] = task

    def get_ready_tasks(self) -> list[TaskNode]:
        """依存関係が全て完了済みの実行可能タスクを返す"""
        ready = []
        for task in self.nodes.values():
            if task.status != "pending":
                continue
            deps_met = all(
                self.nodes[dep].status == "completed"
                for dep in task.depends_on
                if dep in self.nodes
            )
            if deps_met:
                ready.append(task)
        return ready

    def mark_completed(self, task_id: str):
        if task_id in self.nodes:
            self.nodes[task_id].status = "completed"

    def mark_failed(self, task_id: str):
        if task_id in self.nodes:
            self.nodes[task_id].status = "failed"

    def all_completed(self) -> bool:
        return all(t.status == "completed" for t in self.nodes.values())

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "tasks": {tid: t.to_dict() for tid, t in self.nodes.items()},
            "total_estimated_cost_jpy": sum(t.estimated_cost_jpy for t in self.nodes.values()),
            "total_estimated_time_min": sum(t.estimated_time_min for t in self.nodes.values()),
        }


class Planner:
    """Task Graph Planner — ゴールをタスクDAGに分解"""

    def __init__(self):
        pass

    async def plan(self, goal_packet: dict, perception: dict) -> TaskGraph:
        """
        ゴールパケットと認識データからタスクDAGを生成する。

        設計書 think_output:
        - primary_plan: steps, estimated_cost, tools_needed, models_selected, nodes_assigned
        - fallback_plan_1/2/3
        - abort_condition
        """
        goal_id = goal_packet["goal_id"]
        logger.info(f"タスク計画開始: goal_id={goal_id}")

        # LLMでタスク分解（choose_best_model_v6でモデル選択: CLAUDE.md ルール5）
        model_sel = choose_best_model_v6(
            task_type="strategy",
            quality="medium",
            budget_sensitive=True,
            is_agentic=True,
        )

        capability = perception.get("capability_snapshot", {})
        budget = perception.get("budget", {})
        persona_context = perception.get("persona_context", {})
        intel_context = perception.get("intel_context", {})

        plan_prompt = self._build_plan_prompt(goal_packet, capability, budget, persona_context, intel_context)

        try:
            llm_result = await call_llm(
                prompt=plan_prompt,
                system_prompt=(
                    "あなたはSYUTAINβのTask Graph Plannerです。"
                    "ゴールをタスクDAGに分解してください。"
                    "JSON形式で出力してください。各タスクにはtask_type, description, "
                    "assigned_node, estimated_cost_jpy, depends_onを含めてください。\n"
                    "コンテンツ生成タスクでは、対象ICPは非エンジニア28-39歳の実務クリエイター。"
                    "禁止語句（誰でも簡単に/絶対稼げる/完全自動/AI万能論）を使わせない指示を含めること。"
                    "チャネル戦略: note/Booth/Bluesky。失敗資産化の公式に従うこと。"
                ),
                model_selection=model_sel,
            )
            plan_text = llm_result.get("text", "")
        except Exception as e:
            logger.error(f"LLMによるタスク計画失敗: {e}")
            plan_text = ""

        # LLM出力からTaskGraphを生成
        task_graph = self._parse_plan(goal_id, plan_text, capability)

        # タスクをPostgreSQLに保存
        await self._save_tasks(task_graph)

        logger.info(f"タスク計画完了: {len(task_graph.nodes)}タスク生成")

        # 判断根拠トレース
        try:
            task_types = [t.task_type for t in task_graph.nodes.values()]
            assigned_nodes = [t.assigned_node for t in task_graph.nodes.values()]
            await self._record_trace(
                action="plan",
                reasoning=f"{len(task_graph.nodes)}タスク生成。種別: {task_types}。ノード: {assigned_nodes}",
                confidence=1.0 if task_graph.nodes else 0.3,
                context={"task_count": len(task_graph.nodes), "task_types": task_types, "assigned_nodes": assigned_nodes,
                         "total_estimated_cost": sum(t.estimated_cost_jpy for t in task_graph.nodes.values())},
                goal_id=goal_id,
            )
        except Exception:
            pass

        return task_graph

    def _build_plan_prompt(self, goal_packet: dict, capability: dict, budget: dict, persona_context: dict = None, intel_context: dict = None) -> str:
        """計画用プロンプトを生成"""
        nodes_available = []
        for node_name, node_info in capability.get("nodes", {}).items():
            if node_info.get("status") == "healthy":
                nodes_available.append(f"- {node_name}: {node_info.get('role', '不明')}")

        # ペルソナ情報をプロンプトに注入（CLAUDE.md ルール23準拠）
        persona_section = ""
        if persona_context:
            values = persona_context.get("values", [])
            taboos = persona_context.get("taboos", [])
            if values or taboos:
                persona_section = "\n## ペルソナ制約（島原大知）\n"
                if values:
                    persona_section += "- 価値観: " + ", ".join(str(v) for v in values[:5]) + "\n"
                if taboos:
                    persona_section += "- 禁止事項: " + ", ".join(str(t) for t in taboos[:5]) + "\n"

        return f"""以下のゴールをタスクDAGに分解してください。

## ゴール
{goal_packet.get('raw_goal', '')}

## 成功条件
{json.dumps(goal_packet.get('success_definition', []), ensure_ascii=False)}

## 制約
- 予算残: 日次{budget.get('daily_remaining_jpy', 'N/A')}円, 月次{budget.get('monthly_remaining_jpy', 'N/A')}円
- 利用可能ノード:
{chr(10).join(nodes_available) if nodes_available else '  情報なし'}
{persona_section}{self._build_intel_section(intel_context)}
## 承認が必要な操作
公開投稿, 課金発生, 外部アカウント変更, 価格設定, 暗号通貨取引

## 出力形式（JSON）
{{
  "tasks": [
    {{
      "task_type": "research|analysis|content|drafting|coding|browser_action|approval_request",
      "description": "タスクの説明",
      "assigned_node": "alpha|bravo|charlie|delta",
      "estimated_cost_jpy": 0,
      "estimated_time_min": 5,
      "depends_on": [],
      "needs_approval": false,
      "browser_layer": null
    }}
  ]
}}
"""

    def _build_intel_section(self, intel_context: dict = None) -> str:
        """インテリジェンスコンテキストをプロンプトに注入"""
        if not intel_context:
            return ""
        section = "\n## 直近のインテリジェンス\n"
        digest = intel_context.get("intel_digest", {})
        if digest:
            section += f"- サマリー: {digest.get('summary', 'N/A')}\n"
            items = digest.get("for_content", []) or digest.get("for_proposals", [])
            for item in items[:5]:
                title = item.get("title", "")[:60] if isinstance(item, dict) else str(item)[:60]
                section += f"  - {title}\n"
        trends = intel_context.get("recent_intel", [])
        if trends:
            section += "- 直近の注目情報:\n"
            for t in trends[:3]:
                title = t.get("title", "")[:60] if isinstance(t, dict) else str(t)[:60]
                section += f"  - {title}\n"
        return section

    def _parse_plan(self, goal_id: str, plan_text: str, capability: dict) -> TaskGraph:
        """LLM出力からTaskGraphを生成"""
        graph = TaskGraph(goal_id)

        # JSON抽出を試みる
        tasks_data = []
        try:
            # JSON部分を抽出
            import re
            json_match = re.search(r"\{[\s\S]*\}", plan_text)
            if json_match:
                parsed = json.loads(json_match.group())
                tasks_data = parsed.get("tasks", [])
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"タスク計画JSONパース失敗: {e}")

        if not tasks_data:
            # フォールバック: デフォルトの基本タスクを生成
            logger.info("LLM出力パース失敗のため、デフォルトタスクを生成")
            tasks_data = [
                {
                    "task_type": "research",
                    "description": f"ゴール分析: {goal_id}",
                    "assigned_node": "charlie",
                    "estimated_cost_jpy": 0,
                    "estimated_time_min": 5,
                },
            ]

        # TaskNodeに変換
        task_ids = []
        for i, td in enumerate(tasks_data):
            task_id = f"{goal_id}-t{i+1:03d}-{uuid.uuid4().hex[:6]}"
            task_ids.append(task_id)

            # ノード割り当て最適化（有効なノード名のみ許可）
            valid_nodes = {"alpha", "bravo", "charlie", "delta", "auto"}
            assigned = td.get("assigned_node", "auto")
            if assigned not in valid_nodes:
                assigned = "auto"
            if assigned == "auto":
                assigned = self._assign_node(td.get("task_type", ""), capability)

            # モデル選択（CLAUDE.md ルール5: choose_best_model_v6使用）
            task_type = td.get("task_type", "drafting")
            needs_browser = task_type == "browser_action"
            needs_cu = task_type == "computer_use"

            model_sel = choose_best_model_v6(
                task_type=task_type,
                quality="medium",
                budget_sensitive=True,
                needs_computer_use=needs_cu,
            )

            # 依存関係の解決（前方参照・自己参照・範囲外を安全に無視）
            depends_raw = td.get("depends_on", [])
            depends = []
            for dep in depends_raw:
                if isinstance(dep, int) and 0 <= dep < len(task_ids):
                    dep_id = task_ids[dep]
                    if dep_id != task_id:  # 自己参照を除外
                        depends.append(dep_id)
                elif isinstance(dep, str) and dep in task_ids and dep != task_id:
                    depends.append(dep)

            node = TaskNode(
                task_id=task_id,
                task_type=task_type,
                description=td.get("description", ""),
                assigned_node=assigned,
                model_selection=model_sel,
                depends_on=depends,
                needs_approval=td.get("needs_approval", False),
                estimated_cost_jpy=td.get("estimated_cost_jpy", 0),
                estimated_time_min=td.get("estimated_time_min", 5),
                browser_layer=td.get("browser_layer"),
            )
            graph.add_task(node)

        return graph

    def _assign_node(self, task_type: str, capability: dict) -> str:
        """タスクタイプとCapability Auditに基づいてノードを割り当て"""
        nodes = capability.get("nodes", {})

        # ブラウザ操作 → BRAVO
        if task_type in ["browser_action", "computer_use"]:
            if nodes.get("bravo", {}).get("status") == "healthy":
                return "bravo"

        # 推論・コンテンツ生成 → CHARLIE（主力推論）優先、BRAVOにフォールバック
        if task_type in ["drafting", "content", "analysis", "coding"]:
            if nodes.get("charlie", {}).get("status") == "healthy":
                return "charlie"
            if nodes.get("bravo", {}).get("status") == "healthy":
                return "bravo"

        # 監視・情報収集 → DELTA
        if task_type in ["monitoring", "data_extraction"]:
            if nodes.get("delta", {}).get("status") == "healthy":
                return "delta"

        # バッチ処理 → CHARLIE
        if task_type == "batch_process":
            if nodes.get("charlie", {}).get("status") == "healthy":
                return "charlie"

        # デフォルト: ALPHA（司令塔）
        return "alpha"

    async def _save_tasks(self, graph: TaskGraph):
        """タスクをPostgreSQLに保存"""
        try:
            async with get_connection() as conn:
                for task in graph.nodes.values():
                    await conn.execute(
                        """
                        INSERT INTO tasks (id, goal_id, type, status, assigned_node, model_used, tier, input_data, browser_action)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (id) DO UPDATE SET
                            status = EXCLUDED.status,
                            assigned_node = EXCLUDED.assigned_node,
                            updated_at = NOW()
                        """,
                        task.task_id,
                        graph.goal_id,
                        task.task_type,
                        task.status,
                        task.assigned_node,
                        task.model_selection.get("model") if task.model_selection else None,
                        task.model_selection.get("tier") if task.model_selection else None,
                        json.dumps(task.to_dict(), ensure_ascii=False, default=str),
                        task.task_type in ["browser_action", "computer_use"],
                    )
            logger.info(f"タスク{len(graph.nodes)}件をPostgreSQLに保存")
        except Exception as e:
            logger.error(f"タスク保存失敗: {e}")

    async def _record_trace(self, action="", reasoning="", confidence=None, context=None, task_id=None, goal_id=None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    "PLANNER", goal_id, task_id, action, reasoning,
                    confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

    async def replan(self, goal_packet: dict, perception: dict, failure_context: dict) -> TaskGraph:
        """
        失敗コンテキストを踏まえて再計画する。
        設計書: 各再計画時に「前回との差分」を明示
        """
        logger.info(f"再計画開始: goal_id={goal_packet['goal_id']}, 失敗理由={failure_context.get('reason', '不明')}")

        # 再計画でも同じplanメソッドを使うが、失敗情報をperceptionに追加
        perception["failure_context"] = failure_context
        return await self.plan(goal_packet, perception)

    async def close(self):
        pass
