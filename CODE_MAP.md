# SYUTAINβ CODE_MAP.md
> 自動生成: 2026-03-20 23:22:33 JST
> ファイル構造と役割の一覧

## コアファイル
| ファイル | 行数 | 最終更新 | 主要クラス/関数 |
|----------|------|---------|---------------|
| app.py |     2148 | 03-20 22:56 | class LoginRequest,class ChatSendRequest,class GoalCreateReq |
| scheduler.py |     2018 | 03-20 22:56 | def get_power_mode,def get_power_config,class SyutainSchedul |
| worker_main.py |      367 | 03-20 01:43 | class Worker:,def main, |

## エージェント (agents/)
| ファイル | 行数 | 主要クラス/関数 |
|----------|------|---------------|
| approval_manager.py |      693 | class ApprovalManager:,def __init__,async def initialize,async def clo |
| browser_agent.py |      505 | class BrowserAgent:,def __init__,async def initialize,def _choose_laye |
| capability_audit.py |      456 | class CapabilityAudit:,def __init__,async def _get_pool,async def run_ |
| chat_agent.py |     1099 | class ChatAgent:,def __init__,async def initialize,async def close, |
| computer_use_agent.py |      308 | class ComputerUseAgent:,def __init__,async def initialize,async def ex |
| executor.py |      500 | class ExecutionResult:,def __init__,def to_dict,class Executor:, |
| info_collector.py |      271 | class InfoCollector:,def __init__,async def start,async def stop, |
| learning_manager.py |      423 | class LearningManager:,def __init__,async def initialize,async def tra |
| monitor_agent.py |      304 | class MonitorAgent:,def __init__,async def start,async def stop, |
| mutation_engine.py |      406 | class _MutationState:,def __init__,def _open_db,def load, |
| node_router.py |      273 | class NodeRouter:,def __init__,async def start,async def stop, |
| os_kernel.py |      723 | class GoalPacket:,def __init__,def to_dict,class OSKernel:, |
| perceiver.py |      263 | class Perceiver:,def __init__,async def _get_pool,async def perceive, |
| planner.py |      389 | class TaskNode:,def __init__,def to_dict,class TaskGraph:, |
| proposal_engine.py |      869 | class ProposalEngine:,def __init__,async def initialize,async def clos |
| stop_decider.py |      247 | class StopDecision:,def __init__,def to_dict,class StopDecider:, |
| verifier.py |      518 | class VerificationResult:,def __init__,def to_dict,class Verifier:, |

## ツール (tools/)
| ファイル | 行数 | 主要関数 |
|----------|------|---------|
| analytics_tools.py |      217 | def load_strategy_file,def load_icp,def load_channel_strategy,def load |
| budget_guard.py |      300 | class BudgetGuard:,def get_budget_guard, |
| commerce_tools.py |      237 | async def _require_approval,class StripeClient:,class BoothClient:,asy |
| competitive_analyzer.py |      189 | async def analyze_booth,async def analyze_note,async def run_competiti |
| computer_use_tools.py |      296 | class ComputerUseClient:, |
| content_multiplier.py |      308 | async def multiply_content,def _parse_list,def _parse_json,def _parse_ |
| content_tools.py |      238 | async def generate_note_draft,def _parse_note_output,async def generat |
| cross_goal_detector.py |      326 | class CrossGoalDetector:,def get_cross_goal_detector, |
| crypto_tools.py |      297 | class CryptoTrader:, |
| db_init.py |      368 | async def init_postgresql,def init_sqlite_local,async def init_all_dat |
| discord_notify.py |       58 | async def notify_discord,async def notify_approval_request,async def n |
| embedding_tools.py |       91 | async def get_embedding,async def embed_and_store_persona,async def se |
| emergency_kill.py |      235 | def _ensure_log_dir,def _write_kill_log,class EmergencyKill:,def get_e |
| event_logger.py |      140 | async def _get_pool,async def log_event,async def _notify_important_ev |
| info_pipeline.py |      491 | class InfoPipeline:, |
| jina_client.py |      145 | class JinaClient:, |
| lightpanda_tools.py |      224 | class LightpandaClient:,async def quick_extract, |
| llm_router.py |      897 | def _estimate_cost_jpy,def _calc_actual_cost_jpy,async def refresh_mod |
| loop_guard.py |      445 | class LoopGuardState:,class LoopGuard:,def get_loop_guard, |
| mcp_manager.py |      261 | class MCPServerInfo:,class MCPManager:,async def get_mcp_manager, |
| model_registry.py |      122 | def get_model_info,def get_tier, |
| nats_client.py |      247 | class SyutainNATSClient:,async def get_nats_client,async def init_nats |
| node_manager.py |      307 | class NodeState:,class NodeManager:,async def get_node_manager, |
| platform_ng_check.py |       98 | def check_platform_ng,async def check_and_log, |
| playwright_tools.py |      245 | class PlaywrightBrowser:, |
| pw_extract.py |       28 | async def main, |
| semantic_loop_detector.py |      214 | class SemanticLoopDetector:,def get_semantic_loop_detector, |
| social_tools.py |      594 | async def _require_approval,def _get_x_credentials,async def post_to_x |
| stagehand_tools.py |      192 | class StagehandClient:, |
| storage_tools.py |      303 | class PgHelper:,class SqliteHelper:,class ArtifactStorage:,def get_pg, |
| tavily_client.py |      174 | class TavilyClient:, |
| two_stage_refiner.py |      231 | async def two_stage_refine,async def _parallel_draft,async def _single |

## フロントエンド (web/src/)
| ファイル | 行数 | ページ/コンポーネント |
|----------|------|-------------------|
| app/agent-ops |      480 | |
| app/chat |       12 | |
| app/intel |      178 | |
| app/layout |       82 | |
| app/models |      240 | |
| app |      347 | |
| app/proposals |      316 | |
| app/revenue |      262 | |
| app/settings |      654 | |
| app/tasks |      349 | |
| app/timeline |      214 | |
| components/AuthGate |       67 | |
| components/ChatInterface |      419 | |
| components/ClientErrorBoundary |       11 | |
| components/ErrorBoundary |       55 | |
| components/MobileTabBar |      122 | |
| components/NodeStatusPanel |       95 | |
| components/ProposalCard |      330 | |
| lib/api |      125 | |

## 設定ファイル
| ファイル | 行数 | 役割 |
|----------|------|------|
| .env |      131 | 環境変数・APIキー |
| feature_flags.yaml |       69 | 機能フラグ |
| CLAUDE.md |       26 | 絶対ルール22条 |
| Caddyfile |       42 | HTTPSリバースプロキシ |
| config/node_alpha.yaml |       33 | ノード/NATS設定 |
| config/node_bravo.yaml |       38 | ノード/NATS設定 |
| config/node_charlie.yaml |       25 | ノード/NATS設定 |
| config/node_delta.yaml |       33 | ノード/NATS設定 |
| config/nats-server.conf |       21 | ノード/NATS設定 |

## DBスキーマ (PostgreSQL)
| テーブル | カラム数 | 主なカラム |
|----------|---------|----------|
| approval_queue | 7 | id,request_type,request_data,status,requested_at |
| browser_action_log | 12 | id,node,action_type,target_url,layer_used |
| capability_snapshots | 4 | id,snapshot_data,diff_from_previous,created_at |
| chat_messages | 6 | id,session_id,role,content,metadata |
| crypto_trades | 10 | id,exchange,pair,side,amount |
| embeddings | 6 | id,content_type,content_id,metadata,created_at |
| event_log | 9 | id,event_type,category,severity,source_node |
| goal_packets | 13 | goal_id,raw_goal,parsed_objective,success_definition,hard_co |
| intel_items | 10 | id,source,keyword,title,summary |
| llm_cost_log | 7 | id,model,tier,amount_jpy,goal_id |
| loop_guard_events | 9 | id,goal_id,layer_triggered,layer_name,trigger_reason |
| model_quality_log | 9 | id,task_type,model_used,tier,quality_score |
| persona_memory | 10 | id,category,context,content,reasoning |
| proposal_feedback | 7 | id,proposal_id,layer_used,adopted,rejection_reason |
| proposal_history | 13 | id,proposal_id,title,target_icp,primary_channel |
| revenue_linkage | 9 | id,source_content_id,product_id,membership_offer_id,btob_off |
| seasonal_revenue_correlation | 7 | id,month,event_tag,product_category,revenue_impact_jpy |
| settings | 3 | key,value,updated_at |
| tasks | 15 | id,goal_id,type,status,assigned_node |

## コード規模
- Python:    21967行 (52ファイル)
- TypeScript/TSX:     4358行 (18ファイル)
- 合計: 26325行

---
*自動生成完了: 2026-03-20 23:22:33 JST (     132行)*
