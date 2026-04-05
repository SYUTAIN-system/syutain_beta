# SYUTAINβ V25 実装仕様書

**文書ID**: IMPL-SPEC-V25-002
**作成日**: 2026-03-18
**対象リポジトリ**: syutain_beta
**設計書参照**: SYUTAINβ_完全設計書_V25.md
**本文書の行数**: 2000行以上（コードベース監査に基づく完全版）

---

> ## ⚠️ **本文書は 2026-03-18 時点のスナップショット**
>
> 以降の変更は `docs/SYUTAINβ_完全設計書_V25_V30統合.md` (rev.3, 2026-04-06) を参照してください。
>
> **2026-04-06 時点で本文書の記述と現状が乖離している主要項目:**
>
> | 項目 | 本文書 (2026-03-18) | 現状 (2026-04-06) |
> |---|---|---|
> | Python バージョン | 3.12 系前提 | **Python 3.14.3** |
> | PostgreSQL テーブル数 | 17 | **49** + pgvector |
> | ALPHA のローカルLLM | Qwen3.5-9B (MLX, オンデマンド) | **なし**（2026-03-06 撤去、オーケストレーター専任） |
> | CHARLIE の OS | Ubuntu + Win11 dual-boot | **Ubuntu 単独**（2026-03 後半に移行） |
> | BRAVO の Ollama モデル | Qwen3.5-9B のみ | 9B + **27B (highest_local)** + **Nemotron-Nano-9B-Japanese** + Nemotron-Mini |
> | CHARLIE の Ollama モデル | Qwen3.5-9B のみ | 9B + **Nemotron-Nano-9B-Japanese** |
> | 日次API予算 | ¥500 | **¥120** |
> | 月次API予算 | ¥5,000 | **¥2,000** |
> | 承認タイムアウト | 24時間 | **72時間** (APPROVAL_TIMEOUT_HOURS) |
> | CLAUDE.md ルール数 | （本文書時点では未整備） | **32条** (rev.3) |
> | Codex (ALPHA) | 未記載 | `codex-cli 0.118.0`, ChatGPT Plus認証, gstack jobsで使用 |
> | Brain-β (Discord) | 未記載 | 20+個の新規コマンド、破壊的ACTION直接ルート、7カテゴリ intent分類、working_fact ingest (2026-04-05 以降) |
> | SNS承認フロー | 全て Tier 1 | **Tier 2 (品質0.75以上で自動承認)** |
> | Ollama 常駐化 | 未設定 | `KEEP_ALIVE=-1` + `KV Cache Q8` 全ノード有効 |
>
> 上記以外にも多数の差分があります。新規開発・運用判断時は V25_V30 統合版 rev.3 を優先してください。

---

## 目次

1. [概要](#第1章-概要)
2. [システムアーキテクチャ](#第2章-システムアーキテクチャ)
3. [ディレクトリ構造](#第3章-ディレクトリ構造)
4. [エージェント実装詳細](#第4章-エージェント実装詳細)
5. [5段階自律ループ](#第5章-5段階自律ループ)
6. [データベーススキーマ](#第6章-データベーススキーマ)
7. [API仕様](#第7章-api仕様)
8. [Web UIページ一覧](#第8章-web-uiページ一覧)
9. [LLMルーティング](#第9章-llmルーティング)
10. [ループガード9層](#第10章-ループガード9層)
11. [ブラウザ4層](#第11章-ブラウザ4層)
12. [予算管理](#第12章-予算管理)
13. [通知システム](#第13章-通知システム)
14. [CHARLIE運用](#第14章-charlie運用)
15. [セキュリティ](#第15章-セキュリティ)
16. [設計書V25からの全変更点](#第16章-設計書v25からの全変更点)
17. [既知の制限事項と今後の課題](#第17章-既知の制限事項と今後の課題)
18. [運用手順書](#第18章-運用手順書)
19. [トラブルシューティング](#第19章-トラブルシューティング)
20. [2026-03-18の全修正履歴](#第20章-2026-03-18の全修正履歴)

---

## 第1章 概要

### 1.1 設計書との関係

本文書は「SYUTAINβ_完全設計書_V25.md」を原典とし、実際のコードベース（2026-03-18監査）に基づいて記述した実装仕様書である。設計書V25はV20〜V24を再構成した原典であり、本実装はその仕様に準拠しつつ、段階的実装（Step 7〜23）を経て構築された。

設計書との差分は第16章に網羅的に記載する。本章では差分の存在を前提としつつ、**実際に動作しているコード**を正として記述する。

### 1.2 実装範囲（Phase 1完了項目）

Phase 1として以下が実装・稼働済みである（2026-03-18時点）:

| カテゴリ | 実装項目 | ファイル数 | 行数概算 |
|---------|---------|----------|---------|
| エージェント層 | 17エージェント（OS_Kernel〜MutationEngine） | 17 | ~7,000 |
| ツール層 | 26ツール（LLMRouter〜ModelRegistry） | 26 | ~6,500 |
| バックエンド | FastAPI（JWT/SSE/WebSocket） | 1 | 1,696 |
| フロントエンド | Next.js 9ページ + 6コンポーネント | ~30 | ~4,500 |
| スケジューラー | APScheduler 8ジョブ | 1 | 404 |
| ワーカー | ノード別ワーカーメイン | 1 | 314 |
| データベース | PostgreSQL 17テーブル + SQLite 4テーブル | 1 | 368 |
| 設定 | NATSクラスタ + ノードYAML + Caddy | 6 | ~200 |

**稼働確認済み機能:**
- 4ノード（ALPHA/BRAVO/CHARLIE/DELTA）フル稼働基盤
- 5段階自律ループ（認識→思考→行動→検証→停止判断）
- 9層ループ防止壁（LoopGuard）
- 4層ブラウザ自動操作（Lightpanda→Stagehand→Playwright→ComputerUse）
- 3層提案エンジン（提案→反論→代替案）
- 双方向チャットエージェント（6カテゴリ意図分類）
- Web UI（Next.js 9ページ + 設定画面、10秒/5秒自動更新）
- FastAPI バックエンド（JWT認証、SSE、WebSocket）
- NATS JetStream ノード間通信（6ストリーム）
- PostgreSQL + SQLite ハイブリッドDB（17+4テーブル）
- 突然変異エンジン（第24章準拠、SQLCipher隔離）

**現在のDB記録数（2026-03-18）:**
- goal_packets: 13件、tasks: 43件、chat_messages: 134件
- llm_cost_log: 43件、capability_snapshots: 31件
- proposals: 2件、model_quality_log: 22件、approval_queue: 10件

### 1.3 本文書の目的

1. 実装されたコードの正確な仕様を一元的に記録する
2. 設計書V25と実装の差分を明示する（第16章）
3. 今日（2026-03-18）実施した修正の完全ログを記録する（第20章）
4. 運用・保守・拡張の基礎資料とする

---

## 第2章 システムアーキテクチャ

### 2.1 4ノード構成

| ノード | ハードウェア | OS | Tailscale IP | ローカルLLM | GPU/VRAM | 役割 |
|--------|------------|-----|-------------|-----------|---------|------|
| ALPHA | Mac mini M4 Pro 16GB RAM | macOS | 127.0.0.1（ローカル） | Qwen3.5-9B（MLX、オンデマンド） | Apple M4 Pro（共有） | オーケストレーター / FastAPI / Next.js |
| BRAVO | Ryzen + RTX 5070 12GB | Ubuntu | 100.x.x.x | Qwen3.5-9B（Ollama常駐） | RTX 5070 12GB | 推論優先ノード / Browser / ComputerUse |
| CHARLIE | Ryzen 9 + RTX 3080 10GB | Ubuntu（Win11デュアルブート） | 100.x.x.x | Qwen3.5-9B（Ollama常駐） | RTX 3080 10GB | 推論ノード / コンテンツ生成 |
| DELTA | Xeon E5 + GTX 980Ti 6GB / 48GB RAM | Ubuntu | 100.x.x.x | qwen3:4b-q4_K_M（Ollama常駐） | GTX 980Ti 6GB | モニタリング / 情報収集 / 突然変異エンジン |

**重要: ALPHAのMLXモデルはBRAVO・CHARLIE両方ビジー時のみロード。常駐しない。**

### 2.2 通信フロー図

```
┌─────────────────────────────────────────────────────────────────┐
│                         Tailscale VPN                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ALPHA (Mac mini M4 Pro / macOS)                         │  │
│  │  - FastAPI :8000  ←── JWT認証, SSE, WebSocket            │  │
│  │  - Next.js :3000  ←── Web UI                             │  │
│  │  - Caddy   :8443  ←── HTTPS reverse proxy                │  │
│  │  - scheduler.py   ←── APScheduler 8ジョブ                │  │
│  │  - NATS Server    ←── JetStream クラスタコーディネーター  │  │
│  │  - PostgreSQL     ←── 共有状態DB (17テーブル)             │  │
│  └────────┬──────────────────────────────────────────────────┘  │
│           │ NATS JetStream (Primary)                            │
│           │ HTTP REST (Fallback)                                │
│    ┌──────┴──────────┬────────────────┐                        │
│    ▼                 ▼                ▼                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                 │
│  │  BRAVO   │  │ CHARLIE  │  │    DELTA     │                 │
│  │ 100.x.x.x│  │ 100.x.x.x│  │ 100.x.x.x│                 │
│  │          │  │          │  │              │                 │
│  │Browser   │  │Content   │  │Monitor       │                 │
│  │ComputerUse│  │Worker    │  │InfoCollector │                 │
│  │Qwen3.5-9B│  │Qwen3.5-9B│  │qwen3:4b-q4_K│                 │
│  │RTX5070   │  │RTX3080   │  │GTX980Ti/48GB │                 │
│  │priority=1│  │priority=1│  │priority=2    │                 │
│  └──────────┘  └──────────┘  └──────────────┘                 │
└─────────────────────────────────────────────────────────────────┘

外部接続:
  ブラウザ/iOS ──HTTPS:8443──► Caddy ──► FastAPI :8000
                                     └──► Next.js :3000
  OpenAI / Anthropic / DeepSeek / Google API ◄── ALPHA (call_llm)
  Discord Webhook ◄── notify_discord()
  Stripe / Booth ◄── commerce_tools.py
  Tavily / Jina Reader ◄── info_pipeline.py
```

### 2.3 NATS JetStream 6ストリーム

```python
# tools/nats_client.py より
STREAMS = {
    "TASKS":     {"subjects": ["task.>"],     "retention": "workqueue"},
    "AGENTS":    {"subjects": ["agent.>"],    "retention": "limits", "max_age": 3600},
    "PROPOSALS": {"subjects": ["proposal.>"], "retention": "limits", "max_age": 86400},
    "MONITOR":   {"subjects": ["monitor.>"],  "retention": "limits", "max_age": 3600},
    "BROWSER":   {"subjects": ["browser.>"],  "retention": "limits", "max_age": 3600},
    "INTEL":     {"subjects": ["intel.>"],    "retention": "limits", "max_age": 86400},
}
# NATSサーバー設定: JetStream有効、mem 256MB、file 1GB
# クラスタ: 4ノード構成（routes: BRAVO/CHARLIE/DELTA）
```

### 2.4 NATS設定（config/nats-server.conf）

```
jetstream {
  store_dir: "/tmp/nats-store"
  max_memory_store: 256MB
  max_file_store: 1GB
}
cluster {
  name: "syutain_cluster"
  listen: "0.0.0.0:6222"
  routes: [
    "nats-route://100.x.x.x:6222",
    "nats-route://100.x.x.x:6222",
    "nats-route://100.x.x.x:6222"
  ]
}
```

### 2.5 HTTPS設定（Caddyfile）

```
YOUR_TAILSCALE_HOSTNAME:8443 {
    tls internal
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
}
:80 {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
}
```

### 2.6 CHARLIEデュアルブート仕様

- Ubuntu（メイン稼働）: Ollama + Qwen3.5-9B + worker_main.py
- Win11（手動切替）: 手動のみ。APIからsafe_shutdownをトリガー後、物理的に切替
- `/api/charlie/shutdown` エンドポイントからリモートシャットダウン可能
- Win11起動後のCHARLIEはオフラインとして扱い、BRAVO/ALPHAでフォールバック

### 2.7 ALPHAオンデマンドLLM仕様

```python
# tools/llm_router.py _pick_local_node() より
def _pick_local_node() -> str:
    # BRAVO/CHARLIEから優先選択（ハートビート確認済みのノード）
    for node in ["bravo", "charlie"]:
        state = _node_load[node]
        if not state["busy"] and state["last_seen"] > 0 and (now - state["last_seen"]) < 60:
            return node
    # ハートビート未受信でもBRAVO/CHARLIEを優先
    for node in ["bravo", "charlie"]:
        if not _node_load[node]["busy"]:
            return node
    # 最終手段: ALPHA（MLXオンデマンド）
    return "alpha"
```

ALPHAのMLXモデルはOllamaではなくmlx_lmで起動。`ollama serve`は常駐しない。

---

## 第3章 ディレクトリ構造

```
~/syutain_beta/
├── app.py                          # FastAPI メインサーバー (1,696行)
├── scheduler.py                    # APScheduler (404行)
├── worker_main.py                  # ノード別ワーカー (314行)
├── start.sh                        # 起動スクリプト（stop→start）
├── requirements.txt                # Python依存関係
├── Caddyfile                       # HTTPS リバースプロキシ設定
├── feature_flags.yaml              # Phase 1全機能フラグ (53行)
├── CLAUDE.md                       # Claude Code 絶対ルール22条
├── README.md                       # プロジェクト概要
│
├── agents/                         # エージェント層 (17ファイル, ~7,000行)
│   ├── __init__.py
│   ├── os_kernel.py                # 5段階自律ループ司令塔 (514行)
│   ├── chat_agent.py               # 双方向チャット (719行+)
│   ├── proposal_engine.py          # 3層提案エンジン (798行)
│   ├── executor.py                 # タスク実行 (463行)
│   ├── planner.py                  # タスクグラフ生成 (386行)
│   ├── perceiver.py                # 認識フェーズ (263行)
│   ├── verifier.py                 # 検証フェーズ (360行)
│   ├── stop_decider.py             # 停止判断 (247行)
│   ├── approval_manager.py         # 承認管理 (525行)
│   ├── browser_agent.py            # 4層ブラウザ (495行)
│   ├── monitor_agent.py            # ノード監視 (304行)
│   ├── info_collector.py           # 情報収集 (271行)
│   ├── mutation_engine.py          # 突然変異エンジン (406行)
│   ├── learning_manager.py         # 学習管理 (423行)
│   ├── computer_use_agent.py       # コンピュータ操作 (308行)
│   ├── capability_audit.py         # 能力監査 (430行)
│   └── node_router.py              # ノードルーティング (273行)
│
├── tools/                          # ツール層 (26ファイル, ~6,500行)
│   ├── __init__.py
│   ├── llm_router.py               # LLMルータ choose_best_model_v6 (702行)
│   ├── budget_guard.py             # 予算管理 (293行)
│   ├── loop_guard.py               # 9層ループ防止 (445行)
│   ├── emergency_kill.py           # 緊急停止 (235行)
│   ├── nats_client.py              # NATSクライアント (247行)
│   ├── discord_notify.py           # Discord通知 (58行)
│   ├── two_stage_refiner.py        # 2段階精錬 (235行)
│   ├── semantic_loop_detector.py   # 意味的ループ検知 (214行)
│   ├── cross_goal_detector.py      # クロスゴール干渉検知 (326行)
│   ├── storage_tools.py            # DB操作ヘルパー (303行)
│   ├── db_init.py                  # DB初期化DDL (368行)
│   ├── node_manager.py             # ノード管理 (307行)
│   ├── info_pipeline.py            # 情報収集パイプライン (303行)
│   ├── content_tools.py            # コンテンツ生成 (238行)
│   ├── social_tools.py             # SNS投稿 (195行)
│   ├── commerce_tools.py           # Stripe/Booth (233行)
│   ├── crypto_tools.py             # 暗号通貨取引 (297行)
│   ├── analytics_tools.py          # 分析 (217行)
│   ├── computer_use_tools.py       # コンピュータ操作 (290行)
│   ├── lightpanda_tools.py         # Lightpanda CDP (224行)
│   ├── stagehand_tools.py          # Stagehand HTTP (192行)
│   ├── playwright_tools.py         # Playwright Chromium (245行)
│   ├── tavily_client.py            # Tavily検索 (174行)
│   ├── jina_client.py              # Jina Reader (145行)
│   ├── mcp_manager.py              # MCPマネージャ (261行)
│   └── model_registry.py           # モデルレジストリ (122行)
│
├── prompts/                        # システムプロンプト (10ファイル)
│   ├── SYSTEM_OS_KERNEL.md
│   ├── SYSTEM_PERCEIVER.md
│   ├── SYSTEM_PLANNER.md
│   ├── SYSTEM_EXECUTOR.md
│   ├── SYSTEM_VERIFIER.md
│   ├── SYSTEM_PROPOSAL_ENGINE.md
│   ├── SYSTEM_APPROVAL_MANAGER.md
│   ├── SYSTEM_STOP_DECIDER.md
│   ├── SYSTEM_CHAT_AGENT.md
│   └── SYSTEM_BROWSER_AGENT.md
│
├── strategy/                       # 戦略ファイル（コンテンツ生成前に参照必須）
│   ├── CHANNEL_STRATEGY.md         # チャネル戦略
│   ├── CONTENT_STRATEGY.md         # コンテンツ戦略
│   └── ICP_DEFINITION.md           # ICP定義
│
├── docs/                           # ドキュメント
│   ├── IMPLEMENTATION_SPEC.md      # 本文書
│   ├── approval_policy.md
│   ├── external_sources.md
│   ├── ops_runbook.md
│   ├── revenue_playbook.md
│   └── simulation_results.md
│
├── config/                         # ノード設定
│   ├── nats-server.conf            # NATSサーバー設定
│   ├── node_alpha.yaml             # ALPHAノード設定
│   ├── node_bravo.yaml             # BRAVOノード設定
│   ├── node_charlie.yaml           # CHARLIEノード設定
│   └── node_delta.yaml             # DELTAノード設定
│
├── mcp_servers/                    # MCPサーバー
│   ├── config.yaml                 # MCP設定
│   └── syutain_tools/
│       ├── __init__.py
│       └── server.py               # MCPサーバー実装
│
├── web/                            # Next.js 16 フロントエンド
│   ├── app/                        # App Router
│   │   ├── page.tsx                # ダッシュボード (/)
│   │   ├── chat/page.tsx           # チャット (/chat)
│   │   ├── tasks/page.tsx          # タスク一覧 (/tasks)
│   │   ├── proposals/page.tsx      # 提案一覧 (/proposals)
│   │   ├── agent-ops/page.tsx      # エージェント操作 (/agent-ops)
│   │   ├── revenue/page.tsx        # 収益 (/revenue)
│   │   ├── models/page.tsx         # モデル使用状況 (/models)
│   │   ├── intel/page.tsx          # 情報収集 (/intel)
│   │   └── settings/page.tsx       # 設定 (/settings)
│   └── components/                 # 共有コンポーネント
│
├── data/                           # データディレクトリ
│   ├── .gitkeep
│   └── pids/                       # プロセスID管理
│
├── logs/                           # ログディレクトリ
│   └── .gitkeep
│
├── scripts/                        # 運用スクリプト
│
├── .env.example                    # 環境変数テンプレート
├── .gitignore
└── SYUTAINβ_完全設計書_V25.md      # 設計書原典
```

---

## 第4章 エージェント実装詳細

### 4.1 エージェント一覧

| エージェント | クラス名 | 配置ノード | シングルトン関数 | 主要メソッド |
|------------|---------|----------|--------------|-----------|
| OS_Kernel | OSKernel | ALPHA | get_os_kernel() | create_goal_packet(), execute_goal() |
| ChatAgent | ChatAgent | ALPHA | get_chat_agent() | process_message(), process_message_stream(), _classify_intent() |
| ProposalEngine | ProposalEngine | ALPHA | get_proposal_engine() | generate_proposal(), run_three_layer_pipeline(), weekly_autonomous_proposal() |
| Executor | Executor | ALPHA（全ノードへディスパッチ） | - | execute_task(), _execute_llm_task(), _execute_browser_task() |
| Planner | Planner | ALPHA | - | plan(), replan() |
| Perceiver | Perceiver | ALPHA | - | perceive() |
| Verifier | Verifier | ALPHA | - | verify(), verify_goal_completion() |
| StopDecider | StopDecider | ALPHA | - | decide() |
| ApprovalManager | ApprovalManager | ALPHA | get_approval_manager() | request_approval(), respond(), check_timeouts() |
| BrowserAgent | BrowserAgent | BRAVO（主）/CHARLIE（副） | - | execute(), _choose_layer() |
| MonitorAgent | MonitorAgent | DELTA | - | start(), _check_loop() |
| InfoCollector | InfoCollector | DELTA | - | _full_pipeline_loop(), _rss_monitor_loop() |
| MutationEngine | 純粋関数 | DELTA | - | should_mutate(), apply_deviation(), report_outcome() |
| LearningManager | LearningManager | ALPHA | - | track_content_conversion(), get_best_model_for_task() |
| ComputerUseAgent | ComputerUseAgent | BRAVO | - | execute_multi_step(), handle_login() |
| CapabilityAudit | CapabilityAudit | ALPHA | get_capability_audit() | run_full_audit(), _compute_diff() |
| NodeRouter | NodeRouter | ALPHA | get_node_router() | route_task(), route_inference(), dispatch_task() |

### 4.2 シングルトンパターン

```python
# 典型的なシングルトン実装パターン（os_kernel.pyより）
_os_kernel_instance: Optional["OSKernel"] = None

def get_os_kernel() -> "OSKernel":
    global _os_kernel_instance
    if _os_kernel_instance is None:
        _os_kernel_instance = OSKernel()
    return _os_kernel_instance
```

シングルトンを実装しているエージェント/ツール:
- get_os_kernel(), get_chat_agent(), get_proposal_engine(), get_approval_manager()
- get_capability_audit(), get_node_router()
- get_budget_guard(), get_loop_guard(), get_emergency_kill()
- get_nats_client(), get_semantic_loop_detector(), get_cross_goal_detector()

### 4.3 エージェント間呼び出しフロー

```
ユーザー入力（Web UI /chat）
    │
    ▼
ChatAgent.process_message()
    │ _classify_intent() → "goal_input"
    ▼
ChatAgent._handle_goal_input()
    │ バックグラウンドタスク起動
    ▼
OSKernel.execute_goal(raw_goal)
    │
    ├─[1. 認識]─► Perceiver.perceive()
    │                │ capability_audit, BRAVO status, budget,
    │                │ approval_boundary, strategy_files (10項目)
    │
    ├─[2. 思考]─► Planner.plan(goal_packet, perception)
    │                │ TaskGraph(DAG)生成
    │                │ _assign_node() → BRAVO/CHARLIE/DELTA/ALPHA
    │
    ├─[3. 行動]─► Executor.execute_task(task_node)
    │                │ _execute_llm_task()      → call_llm()
    │                │ _execute_browser_task()  → BrowserAgent.execute()
    │                │ _execute_computer_use()  → ComputerUseAgent.execute_multi_step()
    │                │ _execute_data_extraction() → InfoPipeline
    │                │ _execute_batch_task()    → two_stage_refine()
    │                │ _execute_approval_request() → ApprovalManager.request_approval()
    │
    ├─[4. 検証]─► Verifier.verify(task, result)
    │                │ _score_quality() LLMベース
    │                │ _tier_s_quality_check() 高価値タスク
    │                │ verify_goal_completion() 80%タスク + 0.5平均品質
    │
    └─[5. 停止]─► StopDecider.decide()
                     │ COMPLETE / CONTINUE / RETRY_MODIFIED
                     │ SWITCH_PLAN / ESCALATE / EMERGENCY_STOP
                     │ SEMANTIC_STOP / INTERFERENCE_STOP
```

### 4.4 ChatAgent 6カテゴリ意図分類仕様

```python
# agents/chat_agent.py _classify_intent() の完全仕様

カテゴリ: goal_input
  条件1: goal_keywords リストに含まれるキーワードが存在する場合
  条件2: メッセージ長40文字以上 + 動詞的表現（して/する/作る/やる等）
  優先度: 高（長文で「やって」等を含む場合もgoal扱い）
  主要キーワード（修正版 2026-03-18追加分含む）:
    - 調査を、競合調査、決めたい、知りたい、価格を、値段を
    - してほしい/してくれ/してください/して欲しい（各動詞バリエーション）
    - 目標、goal、達成、計画して、戦略
    - 出品、公開して、投稿して、販売して、リリース
    - booth、note、gumroad

カテゴリ: approval
  条件: メッセージ長30文字未満 + 承認/却下キーワード
        OR メッセージ長15文字未満 + "ok"/"はい"/"やって"等単独
  キーワード: 承認、approve、許可、おけ、いいよ、了解、進めて
              却下、reject、ダメだ、やめて、やめろ、中止、キャンセル

カテゴリ: status_query
  キーワード: 状況、status、進捗、どうなっ、今どう、ステータス、報告して

カテゴリ: feedback
  キーワード: フィードバック、感想、もっと、改善、修正して

カテゴリ: system_command
  キーワード: charlie、win11、予算変更、予算を変更、シャットダウン
              情報収集して、ノードを、再起動、デプロイ

カテゴリ: general
  その他すべて（LLMで応答）
```

### 4.5 GoalPacket データ構造

```python
# agents/os_kernel.py GoalPacket.__init__() より

class GoalPacket:
    goal_id: str              # UUID
    raw_goal: str             # ユーザーが入力したテキスト
    parsed_objective: str     # LLMで構造化した目的
    success_definition: list  # 成功条件リスト
    hard_constraints: dict    # 絶対条件（違反不可）
    soft_constraints: list    # 努力目標
    approval_boundary: dict   # {
                              #   "human_required": ["公開投稿", "課金発生",
                              #                      "外部アカウント変更",
                              #                      "価格設定", "暗号通貨取引"],
                              #   "auto_allowed": ["下書き生成", "分析",
                              #                   "ログ整理", "候補案生成",
                              #                   "情報収集", "ブラウザ情報収集"]
                              # }
    deadline: Optional[str]   # ISO 8601
    priority: str             # low / medium / high / critical
    fallback_goals: list      # フォールバック目標リスト
    max_total_steps: int      # デフォルト50（.envのEMERGENCY_KILL_MAX_STEPS=100で上書き可）
    max_retries_per_step: int # デフォルト2
    max_replans: int          # デフォルト3
```

### 4.6 Perceiver 10項目チェックリスト

```python
# agents/perceiver.py perceive() が収集する10項目

1. capability_audit     # CapabilityAudit.run_full_audit() 最新スナップショット
2. bravo_status         # BRAVOノードのオンライン状態（推論優先ノード）
3. mcp_status           # MCPサーバー接続状態（Tavily/Jina/GitHub/Gmail/Bluesky）
4. budget_status        # BudgetGuard.get_budget_status()（日次消費率）
5. approval_boundaries  # GoalPacket.approval_boundary（承認必要行為の定義）
6. strategy_files       # strategy/CHANNEL_STRATEGY.md + CONTENT_STRATEGY.md + ICP_DEFINITION.md
7. previous_attempts    # 同ゴールの過去実行履歴（PostgreSQL goal_packets）
8. market_context       # InfoCollector最新情報（intel_items）
9. api_availability     # OpenAI/Anthropic/DeepSeek/Google APIキー確認
10. browser_capability  # Lightpanda/Stagehand/Playwright利用可否
```

### 4.7 ApprovalManager 3層承認システム

```python
# agents/approval_manager.py より

Tier 1 - 人間承認必須:
  - SNS投稿（X、Bluesky）
  - 価格設定（Stripe/Booth商品）
  - 暗号通貨取引
  - タイムアウト: 24時間 → ESCALATE

Tier 2 - 自動実行 + Discord通知:
  - 下書き公開（Noteドラフト）
  - 外部情報収集
  - レポート生成
  - タイムアウト: なし（即時実行）

Tier 3 - 完全自動（通知なし）:
  - ローカルファイル操作
  - DB読み取り
  - 分析・要約
  - ログ整理
```

### 4.8 MutationEngine 仕様

```python
# agents/mutation_engine.py より（設計書第24章準拠）

# 純粋関数として実装（クラスではない）
def should_mutate(intuition_input: dict) -> bool:
    """基本確率0.005、最大0.05でランダムに変異を起こすか判定"""

def apply_deviation(original_value: float, action_id: str) -> float:
    """連続値パラメータの微小偏差を適用"""

def apply_deviation_int(original_value: int, action_id: str) -> int:
    """整数パラメータの偏差を適用"""

def report_outcome(action_id: str, result: dict):
    """変異結果を記録（SQLCipher on DELTA）"""

# エントロピーソース: /dev/urandom + CPU温度 + NATS RTT + VRAM + パケットジッタ
# ストレージ: SQLCipher（DELTA上）
# 制約（CLAUDE.md ルール22）:
#   - 変異発生をログに記録しない
#   - 変異パラメータをUIに表示しない
#   - CapabilityAuditに含めない
#   - 9層ループ防止壁・承認フロー・EmergencyKillに干渉しない
#   - try-exceptで完全に隔離
```

---

## 第5章 5段階自律ループ

### 5.1 ループ全体フロー

```
OSKernel.execute_goal(raw_goal)
│
├─ Step 0: GoalPacket生成
│    create_goal_packet(raw_goal)
│    → LLMでraw_goal→構造化（parsed_objective, success_definition等）
│    → PostgreSQL goal_packets テーブルに保存
│    → LoopGuard状態初期化
│
├─ Step 1: 認識フェーズ（Perceiver）
│    perceive(goal_packet)
│    → 10項目チェックリスト収集
│    → PerceptionResult返却
│
├─ Step 2: 思考フェーズ（Planner）
│    plan(goal_packet, perception)
│    → TaskGraph (DAG) 生成
│    → 各タスクにノード割り当て
│    → 優先度・依存関係設定
│
├─ Step 3〜N: 実行ループ
│    for task in task_graph.get_next_tasks():
│    │
│    ├─ LoopGuard.check_all_layers(goal_id, action_key)
│    │   ↑ 9層チェック（詳細は第10章）
│    │
│    ├─ Executor.execute_task(task_node)
│    │   ↑ タスクタイプ別ディスパッチ
│    │
│    ├─ Verifier.verify(task, result)
│    │   ↑ 品質スコアリング
│    │
│    └─ StopDecider.decide(...)
│        COMPLETE     → ループ終了
│        CONTINUE     → 次タスクへ
│        RETRY_MODIFIED → 修正して再試行
│        SWITCH_PLAN  → Planner.replan()
│        ESCALATE     → Discord通知 + 承認待ち
│        EMERGENCY_STOP → EmergencyKill.trigger()
│        SEMANTIC_STOP  → SemanticLoopDetector検知
│        INTERFERENCE_STOP → CrossGoalDetector検知
│
└─ Step Final: 完了処理
     goal_packets.status → "completed"
     total_cost_jpy, total_steps 記録
     Discord完了通知
```

### 5.2 タスクタイプ別実行フロー

```python
# agents/executor.py execute_task() のディスパッチロジック

task.type == "llm"           → _execute_llm_task()
task.type == "browser"       → _execute_browser_task()
task.type == "computer_use"  → _execute_computer_use_task()
task.type == "data_extraction" → _execute_data_extraction()
task.type == "batch"         → _execute_batch_task()
task.type == "approval"      → _execute_approval_request()

# ExecutionResult dataclass
{
  task_id: str,
  success: bool,
  output: dict,
  artifacts: list,
  cost_jpy: float,
  quality_score: float,
  model_used: str,
  tier: str,
  error: Optional[str],
  latency_ms: float,
}
```

### 5.3 TaskNode / TaskGraph

```python
# agents/planner.py より

@dataclass
class TaskNode:
    task_id: str
    goal_id: str
    type: str           # llm / browser / computer_use / data_extraction / batch / approval
    description: str
    input_data: dict
    dependencies: list[str]  # 依存タスクID
    assigned_node: str  # alpha / bravo / charlie / delta
    priority: int       # 1(最高)〜5(最低)
    estimated_cost_jpy: float
    status: str         # pending / running / completed / failed

class TaskGraph:
    nodes: dict[str, TaskNode]
    def get_next_tasks() -> list[TaskNode]  # 依存解決済みタスクを返す
    def mark_complete(task_id)
    def mark_failed(task_id)
    def is_complete() -> bool
```

### 5.4 Verifier 品質スコアリング

```python
# agents/verifier.py より

def _score_quality(task, result) -> float:
    """LLMベースの品質スコア（0.0〜1.0）"""
    # 0.7未満: 再試行推奨
    # 0.5未満: 必ず再試行

def verify_goal_completion(goal_id) -> bool:
    """ゴール完了判定"""
    # 条件1: タスクの80%以上が完了
    # 条件2: 平均品質スコア0.5以上

def _tier_s_quality_check(task, result) -> float:
    """Tier S（最終公開品質）専用チェック"""
    # 高価値タスクの追加品質保証
```

### 5.5 StopDecision 8タイプ

```python
# agents/stop_decider.py より

DECISION_COMPLETE          = "complete"         # 全タスク完了 → ループ終了
DECISION_CONTINUE          = "continue"         # 次タスクへ継続
DECISION_RETRY_MODIFIED    = "retry_modified"   # 修正して再試行
DECISION_SWITCH_PLAN       = "switch_plan"      # 計画変更（replan）
DECISION_ESCALATE          = "escalate"         # 人間へエスカレーション
DECISION_EMERGENCY_STOP    = "emergency_stop"   # 緊急停止
DECISION_SEMANTIC_STOP     = "semantic_stop"    # 意味的ループ停止
DECISION_INTERFERENCE_STOP = "interference_stop" # クロスゴール干渉停止
```

### 5.6 ChatAgent経由のトリガーフロー

```
ユーザー: "Booth向けプロンプト集を作ってほしい"
    │
    ▼
ChatAgent._classify_intent() → "goal_input"
    │  （"してほしい" キーワード一致）
    ▼
ChatAgent._handle_goal_input()
    │  Discord通知: notify_goal_accepted(message[:300])
    │  asyncio.create_task(_run_goal_loop(raw_goal))  ← バックグラウンド
    ▼
即時レスポンス: "了解しました！ゴールパケットを生成してループを起動します。"
    │
    ▼ （バックグラウンドで実行）
OSKernel.execute_goal("Booth向けプロンプト集を作ってほしい")
```

### 5.7 スケジューラー経由の自動トリガー

```python
# scheduler.py より

# 日次提案: 毎日07:00 JST
CronTrigger(hour=7, minute=0) → ProposalEngine.generate_proposal()

# 週次提案: 毎週月曜09:00 JST
CronTrigger(day_of_week="mon", hour=9, minute=0)
    → ProposalEngine.weekly_autonomous_proposal()
    → 「今週やるべき3手」+「今週やめるべき1手」生成

# 情報収集: 6時間間隔
IntervalTrigger(hours=6) → InfoPipeline.run_full_pipeline()
    → Tavily検索 → Jina Reader → RSS
    → 重要度スコアリング → カテゴリ分類 → intel_items保存

# 孤立タスク再ディスパッチ: 5分間隔
IntervalTrigger(minutes=5) → redispatch_orphan_tasks()
    → 30分以上pending状態のタスクを再キューイング

# CapabilityAudit: 1時間間隔
IntervalTrigger(hours=1) → CapabilityAudit.run_full_audit()

# 週次学習レポート: 日曜21:00 JST
CronTrigger(day_of_week="sun", hour=21, minute=0)
    → LearningManager.generate_weekly_report()
```

---

## 第6章 データベーススキーマ

### 6.1 PostgreSQL テーブル（17テーブル）

```sql
-- ===== タスク管理 =====
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',          -- pending/running/completed/failed
    assigned_node TEXT,                     -- alpha/bravo/charlie/delta
    model_used TEXT,
    tier TEXT,                              -- S/A/B/L
    input_data JSONB,
    output_data JSONB,
    artifacts JSONB,
    cost_jpy REAL DEFAULT 0.0,
    quality_score REAL,
    browser_action BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== Goal Packet =====
CREATE TABLE IF NOT EXISTS goal_packets (
    goal_id TEXT PRIMARY KEY,
    raw_goal TEXT NOT NULL,
    parsed_objective TEXT,
    success_definition JSONB,
    hard_constraints JSONB,
    soft_constraints JSONB,
    approval_boundary JSONB,
    status TEXT DEFAULT 'active',           -- active/completed/failed/superseded
    progress REAL DEFAULT 0.0,
    total_steps INTEGER DEFAULT 0,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ===== 提案履歴 =====
CREATE TABLE IF NOT EXISTS proposal_history (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT UNIQUE,
    title TEXT,
    target_icp TEXT,
    primary_channel TEXT,
    score INTEGER,                          -- 0-100（100点満点）
    adopted BOOLEAN DEFAULT FALSE,
    outcome_type TEXT,
    revenue_impact_jpy INTEGER DEFAULT 0,
    proposal_data JSONB,
    counter_data JSONB,                     -- 反論
    alternative_data JSONB,                 -- 代替案
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 提案フィードバック =====
CREATE TABLE IF NOT EXISTS proposal_feedback (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    layer_used TEXT NOT NULL,               -- proposal/counter/alternative
    adopted BOOLEAN DEFAULT FALSE,
    rejection_reason TEXT,
    alternative_chosen TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 収益紐付け =====
CREATE TABLE IF NOT EXISTS revenue_linkage (
    id SERIAL PRIMARY KEY,
    source_content_id TEXT,
    product_id TEXT,
    membership_offer_id TEXT,
    btob_offer_id TEXT,
    conversion_stage TEXT,
    revenue_jpy INTEGER DEFAULT 0,
    platform TEXT,                          -- stripe/booth/note
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 能力監査スナップショット =====
CREATE TABLE IF NOT EXISTS capability_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_data JSONB NOT NULL,           -- 全ノードの能力状態
    diff_from_previous JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== ループガードイベント =====
CREATE TABLE IF NOT EXISTS loop_guard_events (
    id SERIAL PRIMARY KEY,
    goal_id TEXT NOT NULL,
    layer_triggered INTEGER NOT NULL,       -- 1-9
    layer_name TEXT NOT NULL,
    trigger_reason TEXT,
    action_taken TEXT,
    step_count_at_trigger INTEGER,
    cost_at_trigger_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== モデル品質ログ =====
CREATE TABLE IF NOT EXISTS model_quality_log (
    id SERIAL PRIMARY KEY,
    task_type TEXT NOT NULL,
    model_used TEXT NOT NULL,
    tier TEXT NOT NULL,
    quality_score REAL DEFAULT 0.0,
    refinement_needed BOOLEAN DEFAULT FALSE,
    refinement_model TEXT,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 季節収益相関 =====
CREATE TABLE IF NOT EXISTS seasonal_revenue_correlation (
    id SERIAL PRIMARY KEY,
    month INTEGER,
    event_tag TEXT,
    product_category TEXT,
    revenue_impact_jpy INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== チャットメッセージ =====
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,                     -- user/assistant
    content TEXT NOT NULL,
    metadata JSONB,                         -- intent, action等
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 情報収集ログ =====
CREATE TABLE IF NOT EXISTS intel_items (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,                   -- tavily/rss/youtube
    keyword TEXT,
    title TEXT,
    summary TEXT,
    url TEXT,
    importance_score REAL DEFAULT 0.0,     -- 0.0-1.0
    category TEXT,                          -- 9カテゴリ
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 暗号通貨取引ログ =====
CREATE TABLE IF NOT EXISTS crypto_trades (
    id SERIAL PRIMARY KEY,
    exchange TEXT NOT NULL,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,                     -- buy/sell
    amount REAL,
    price REAL,
    fee_jpy REAL,
    pnl_jpy REAL,
    strategy TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 承認キュー =====
CREATE TABLE IF NOT EXISTS approval_queue (
    id SERIAL PRIMARY KEY,
    request_type TEXT NOT NULL,             -- sns_post/pricing/crypto
    request_data JSONB NOT NULL,
    status TEXT DEFAULT 'pending',          -- pending/approved/rejected/timeout
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    response TEXT
);

-- ===== ブラウザ操作ログ（V25新規）=====
CREATE TABLE IF NOT EXISTS browser_action_log (
    id SERIAL PRIMARY KEY,
    node TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_url TEXT,
    layer_used TEXT NOT NULL,              -- lightpanda/stagehand/playwright/computer_use
    fallback_from TEXT,
    screenshot_path TEXT,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    model_used TEXT,
    stagehand_cache_hit BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 設定（キーバリュー）=====
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== LLMコストログ =====
CREATE TABLE IF NOT EXISTS llm_cost_log (
    id SERIAL PRIMARY KEY,
    model TEXT NOT NULL,
    tier TEXT,
    amount_jpy REAL NOT NULL,
    goal_id TEXT,
    is_info BOOLEAN DEFAULT FALSE,         -- 情報収集タスクか否か
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== ベクトルストア（pgvector未有効）=====
CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL,
    content_id TEXT NOT NULL,
    embedding BYTEA,                       -- pgvector有効化後はvector(1536)に変更予定
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.2 PostgreSQLインデックス（26本）

```sql
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_node ON tasks(assigned_node);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_intel_items_source ON intel_items(source);
CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_browser_action_log_node ON browser_action_log(node);
CREATE INDEX IF NOT EXISTS idx_loop_guard_events_goal ON loop_guard_events(goal_id);
-- 残り18インデックスはdb_init.pyに定義
```

### 6.3 SQLite ローカルDB（ノード別、4テーブル）

```sql
-- パス: data/local_{node_name}.db（例: data/local_alpha.db）

-- ノードローカルキャッシュ
CREATE TABLE IF NOT EXISTS local_cache (
    key TEXT PRIMARY KEY,
    value TEXT,
    expires_at TEXT
);

-- エージェントメモリ
CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ローカルメトリクス
CREATE TABLE IF NOT EXISTS local_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    labels TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);

-- LLM呼び出しログ
CREATE TABLE IF NOT EXISTS llm_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    tier TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_jpy REAL DEFAULT 0.0,
    latency_ms REAL,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    called_at TEXT DEFAULT (datetime('now'))
);
```

### 6.4 SQLCipher（突然変異エンジン専用）

- 配置ノード: DELTA
- パス: DELTA のローカル暗号化ストレージ
- 用途: 変異パラメータの記録（UIに表示しない、ログに出力しない）
- 設計書第24章準拠、CLAUDE.md ルール22準拠

---

## 第7章 API仕様

### 7.1 認証

```
方式: JWT (HS256)
トークン有効期限: 24時間（JWT_EXPIRE_HOURS=24、.envで変更可）
ヘッダー: Authorization: Bearer <token>
取得: POST /api/auth/login
```

```python
# app.py より
class LoginRequest(BaseModel):
    password: str

# POST /api/auth/login
# リクエスト: {"password": "APP_PASSWORD"}
# レスポンス: {"access_token": "<jwt>", "token_type": "bearer"}
```

### 7.2 エンドポイント一覧

| メソッド | パス | 認証 | 説明 |
|---------|------|------|------|
| POST | /api/auth/login | なし | JWTトークン取得 |
| GET | /api/dashboard | JWT必須 | KPIサマリー（running/pending tasks等） |
| WS | /api/chat/ws | JWT（クエリ） | WebSocketチャット |
| POST | /api/chat/send | JWT必須 | HTTPチャット（WebSocketフォールバック） |
| GET | /api/chat/history | JWT必須 | 会話履歴取得 |
| GET | /api/tasks | JWT必須 | タスク一覧（ステータスフィルタ） |
| GET | /api/tasks/{id} | JWT必須 | タスク詳細 |
| GET | /api/proposals | JWT必須 | 提案一覧 |
| POST | /api/proposals/{id}/approve | JWT必須 | 提案承認 |
| POST | /api/proposals/{id}/reject | JWT必須 | 提案却下 |
| POST | /api/proposals/generate | JWT必須 | 提案即時生成 |
| GET | /api/pending-approvals | JWT必須 | 承認待ちキュー |
| POST | /api/pending-approvals/{id}/respond | JWT必須 | 承認/却下応答 |
| GET | /api/agent-ops/status | JWT必須 | エージェント運用状態 |
| GET | /api/goals/{id} | JWT必須 | ゴール詳細 |
| POST | /api/charlie/shutdown | JWT必須 | CHARLIEリモートシャットダウン |
| GET | /api/revenue | JWT必須 | 収益サマリー |
| GET | /api/model-usage | JWT必須 | モデル使用状況 |
| GET | /api/budget/status | JWT必須 | 予算状態 |
| GET | /api/intel | JWT必須 | 情報収集アイテム |
| GET | /api/settings | JWT必須 | 設定取得 |
| POST | /api/settings/budget | JWT必須 | 予算設定変更 |
| POST | /api/settings/chat-model | JWT必須 | チャットモデル変更 |
| POST | /api/settings/discord | JWT必須 | Discord通知設定 |
| GET | /api/nodes/status | JWT必須 | ノード状態一覧 |
| GET | /health | なし | ヘルスチェック |

### 7.3 主要レスポンス例

```json
// GET /api/dashboard
{
  "running_tasks": 2,
  "pending_tasks": 5,
  "completed_today": 12,
  "active_goals": 3,
  "budget_used_today_jpy": 45.2,
  "budget_daily_jpy": 500.0,
  "budget_ratio": 0.09,
  "nodes": {
    "alpha": "online",
    "bravo": "online",
    "charlie": "online",
    "delta": "online"
  },
  "recent_proposals": [],
  "recent_artifacts": []
}

// GET /api/budget/status
{
  "daily_budget_jpy": 500.0,
  "daily_used_jpy": 45.2,
  "daily_ratio": 0.09,
  "monthly_budget_jpy": 5000.0,
  "monthly_used_jpy": 312.0,
  "monthly_ratio": 0.062,
  "emergency_kill_triggered": false,
  "alert_level": "ok"
}

// GET /health
{
  "status": "healthy",
  "node": "alpha",
  "timestamp": "2026-03-18T10:00:00Z"
}
```

### 7.4 WebSocket仕様（/api/chat/ws）

```
接続: ws://localhost:8000/api/chat/ws?token=<jwt>
     または wss://YOUR_TAILSCALE_HOSTNAME:8443/api/chat/ws?token=<jwt>

クライアント→サーバー:
{
  "session_id": "uuid",
  "message": "Booth向けプロンプト集を作ってほしい"
}

サーバー→クライアント（ストリーミング）:
{
  "type": "stream",
  "delta": "了解しました",
  "session_id": "uuid"
}

サーバー→クライアント（完了）:
{
  "type": "complete",
  "text": "了解しました！ゴールパケットを生成してループを起動します。",
  "intent": "goal_input",
  "session_id": "uuid",
  "action": {"type": "goal_created", "goal_id": "uuid"}
}
```

### 7.5 SSE仕様

SSEエンドポイントはapp.py内の`_sse_subscribers`キューを通じてリアルタイムイベントを配信する。フロントエンドのダッシュボード（10秒ポーリング）はSSEの補完として使用。

---

## 第8章 Web UIページ一覧

### 8.1 ページ構成

| ページ | パス | ファイル | 更新間隔 | 主要機能 |
|--------|------|---------|---------|---------|
| ダッシュボード | / | app/page.tsx | 10秒 | KPIカード、ノード状態、最新提案/成果物、クイックゴール入力 |
| チャット | /chat | app/chat/page.tsx | WebSocket/SSE | メッセージ送受信、承認ボタン、予算表示、ストリーミング |
| タスク | /tasks | app/tasks/page.tsx | 5秒 | ステータスフィルタ、詳細モーダル、出力プレビュー |
| 提案 | /proposals | app/proposals/page.tsx | 手動 | 3層アコーディオン、7軸スコア、承認/却下 |
| エージェント操作 | /agent-ops | app/agent-ops/page.tsx | 10秒 | システムメトリクス、CHARLIEシャットダウン、アクティブゴール |
| 収益 | /revenue | app/revenue/page.tsx | 手動 | サマリーカード、¥1M目標進捗、ソース別内訳 |
| モデル | /models | app/models/page.tsx | 手動 | 予算進捗、ローカル/API比率、モデル使用量テーブル |
| 情報収集 | /intel | app/intel/page.tsx | 手動 | ソースフィルタ、重要度バッジ、URL/サマリー表示 |
| 設定 | /settings | app/settings/page.tsx | 手動 | 予算スライダー、チャットモデル選択、Discord切替 |

### 8.2 ダッシュボード（/）

```typescript
// 10秒間隔で /api/dashboard をポーリング
// 表示要素:
// - KPIカード: 実行中タスク数、待機中タスク数、本日完了数
// - ノード状態: ALPHA/BRAVO/CHARLIE/DELTA のオンライン/オフライン
// - 予算使用率: 日次消費円 / 日次予算円
// - 最新提案: 直近3件
// - 最新成果物: 直近5件
// - クイックゴール入力: テキストボックス → POST /api/chat/send
```

### 8.3 チャット（/chat）

```typescript
// WebSocketプライマリ接続
// ws[s]://<host>/api/chat/ws?token=<jwt>
// フォールバック: POST /api/chat/send（HTTP）

// 機能:
// - ストリーミング応答（type: "stream" イベント受信）
// - 承認ボタン: 承認待ちメッセージに[承認]/[却下]ボタン表示
// - 予算バナー: 予算消費率80%以上で警告表示
// - iOS対応: viewport meta設定、iOS仮想キーボード対応
//   window.scrollTo(0, document.body.scrollHeight)
// - 会話履歴: GET /api/chat/history（セッション別）
```

### 8.4 提案ページ（/proposals）

```typescript
// 3層アコーディオン表示:
// Layer 1: 提案本体
//   - タイトル、ICP、チャネル、スコア（/100）
//   - 7軸レーダー: icp_fit/channel_fit/content_reuse/
//                  speed_to_cash/gross_margin/trust_building/continuity_value
// Layer 2: 反論（counterProposal）
//   - リスク一覧、中止条件、失敗条件
// Layer 3: 代替案（alternatives）
//   - 次善策、低リスク案、スモールスタート案

// アクション:
// POST /api/proposals/{id}/approve → reason: ""
// POST /api/proposals/{id}/reject  → reason: "<理由>"
```

### 8.5 設定ページ（/settings）

```typescript
// 予算スライダー:
// POST /api/settings/budget
// {
//   "daily_budget_jpy": 500,    // 100〜5000
//   "monthly_budget_jpy": 5000, // 1000〜50000
//   "chat_budget_jpy": 100      // 0〜1000
// }

// チャットモデル選択:
// POST /api/settings/chat-model
// { "mode": "auto" | "local" | "deepseek" | "gemini" | "claude" }

// Discord通知切替:
// POST /api/settings/discord
// {
//   "goal_accepted": true,
//   "task_completed": true,
//   "error_alert": true,
//   "node_status": false,
//   "proposal_created": true
// }
```

### 8.6 iOS対応

- `<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">` 設定済み
- チャット入力欄: iOS仮想キーボード表示時の自動スクロール実装
- Tailscale経由でiPhoneからアクセス可能（HTTPS :8443）
- タッチ操作対応: 承認ボタンのタップエリア最小44px確保

---

## 第9章 LLMルーティング

### 9.1 choose_best_model_v6 フローチャート

```
choose_best_model_v6(task_type, quality, ...)
│
├─ needs_computer_use=True  → GPT-5.4 (Tier S, OpenAI direct)
├─ needs_tool_search=True   → GPT-5.4 (Tier S, OpenAI direct)
├─ intelligence_required≥50 → budget_sensitive?
│    ├─ True  → gemini-3.1-pro-preview (Tier S, Google)
│    └─ False → GPT-5.4 (Tier S, OpenAI)
│
├─ final_publish=True AND quality in [high, premium]
│    ├─ task_type in [strategy/pricing/btob/longform_design]
│    │    → claude-sonnet-4-6 (Tier S, Anthropic direct)
│    ├─ is_agentic=True
│    │    → claude-opus-4-6 (Tier S, Anthropic direct)
│    └─ その他
│         → GPT-5.4 (Tier S, OpenRouter)
│
├─ task_type == "chat"
│    → deepseek-v3.2 (Tier A, DeepSeek direct)
│      "チャット通常会話: キャッシュ$0.028/1M"
│
├─ task_type in [batch_process, bulk_draft]
│    → gemini-2.5-flash-lite (Tier B, OpenRouter)
│
├─ local_available=True AND task_type in [drafting/tagging/classification/
│  compression/log_formatting/variation_gen/translation_draft/monitoring/
│  health_check/research/strategy/data_extraction]
│    ├─ needs_multimodal=True → qwen3.5-9b on charlie (Tier L)
│    └─ その他
│         → _pick_local_node() → bravo/charlie/alpha
│              node=="delta" → qwen3.5-4b
│              その他        → qwen3.5-9b
│              (Tier L, local)
│
├─ task_type in [content/note_article/product_desc/analysis]
│    ├─ budget_sensitive=True → deepseek-v3.2 (Tier A)
│    ├─ context_length_needed > 100000 → gemini-2.5-flash (Tier A)
│    └─ その他 → gpt-5-mini (Tier A, OpenRouter)
│
└─ デフォルト
     ├─ budget_sensitive=True → deepseek-v3.2 (Tier A)
     └─ その他 → gpt-5-mini (Tier A, OpenRouter)
```

### 9.2 Tier定義

| Tier | 用途 | 代表モデル | コスト感 |
|------|------|----------|---------|
| S | 最終公開品質・高単価判断・Computer Use | GPT-5.4, Claude Sonnet 4.6, Gemini 3.1 Pro | 高 |
| A | チャット・中品質コンテンツ・分析 | DeepSeek-V3.2, GPT-5-mini, Gemini 2.5 Flash | 中 |
| B | 大量処理・バッチ | Gemini 2.5 Flash Lite | 低 |
| L | ローカル優先（コスト¥0） | Qwen3.5-9B (BRAVO/CHARLIE), qwen3:4b-q4_K_M (DELTA), Qwen3.5-9B MLX (ALPHA) | ¥0 |

### 9.3 コスト概算テーブル

```python
# tools/llm_router.py _COST_RATES_JPY_PER_1K より
_COST_RATES_JPY_PER_1K = {
    "gpt-5.4":            {"input": 0.375, "output": 2.25},
    "claude-sonnet-4-6":  {"input": 0.45,  "output": 2.25},
    "claude-opus-4-6":    {"input": 0.45,  "output": 2.25},
    "deepseek-v3.2":      {"input": 0.042, "output": 0.063},
    "_default":           {"input": 0.15,  "output": 0.15},
}
# 推定コスト: len(prompt) / 3 トークン × rate
# 実コスト: APIレスポンスのusage.prompt_tokens / completion_tokens × rate
```

### 9.4 call_llm マルチプロバイダー実装

```python
# tools/llm_router.py call_llm() の処理フロー

1. model_selectionがNoneなら choose_best_model_v6("drafting")
2. provider != "local" → BudgetGuard.check_before_call(estimated_cost)
   → 予算90%到達 → ローカルLLMにフォールバック（Discord通知）
3. プロバイダー別呼び出し:
   provider == "local"                → _call_local_llm(node)
   provider == "openai" AND via == "direct" → _call_openai()
   provider == "anthropic"            → _call_anthropic()
   provider == "deepseek"             → _call_deepseek()
   provider == "google"               → _call_google()
   via == "openrouter"                → _call_openrouter()
4. 実コスト計算 → BudgetGuard.record_spend()
5. 80%警告 → Discord通知
6. SQLiteローカルログ記録
```

### 9.5 call_llm_stream（ストリーミング）

```python
# tools/llm_router.py call_llm_stream() より
async def call_llm_stream(prompt, system_prompt, model_selection) -> AsyncIterator[str]:
    """
    ストリーミング応答を返すジェネレーター
    チャット(/api/chat/ws)のストリーミング表示に使用
    対応プロバイダー: OpenAI, Anthropic, DeepSeek
    """
```

### 9.6 2段階精錬パイプライン

```python
# tools/two_stage_refiner.py two_stage_refine() より

Stage 1: ローカル並列ドラフト
    _parallel_draft(prompt)
    → BRAVO (Qwen3.5-9B) + CHARLIE (Qwen3.5-9B) 同時生成
    → 2つのドラフトを取得

Stage 2: 品質チェック
    _quality_check(draft_a, draft_b)
    → DELTA (qwen3:4b-q4_K_M) で品質スコア算出
    → score < 0.7 → Stage 3へ

Stage 3: API精錬（条件付き）
    _api_refine(best_draft)
    → DeepSeek-V3.2 or Claude Sonnet-4.6 で最終仕上げ
    → コスト記録
```

### 9.7 ローカルLLM接続先

```
BRAVO (100.x.x.x):
  http://100.x.x.x:11434/api/generate  (Ollama)
  モデル: qwen3.5:9b (または互換名)

CHARLIE (100.x.x.x):
  http://100.x.x.x:11434/api/generate (Ollama)
  モデル: qwen3.5:9b

DELTA (100.x.x.x):
  http://100.x.x.x:11434/api/generate  (Ollama)
  モデル: qwen3:4b-q4_K_M
  ※ 設計書の「qwen3.5:4b」とはOllama上のモデル命名規則の違い

ALPHA (127.0.0.1):
  MLXによるオンデマンド起動
  ポート: 8080（mlx_lm.server）
  モデル: mlx-community/Qwen2.5-7B-Instruct-4bit（等）
  ※ BRAVO/CHARLIE両方ビジー時のみ起動
```

---

## 第10章 ループガード9層

### 10.1 全9層一覧

| 層 | 名前 | 閾値/条件 | トリガー時のアクション |
|----|------|----------|---------------------|
| Layer 1 | Retry Budget | 同一アクション再試行2回まで | RETRY_MODIFIED → 3回目でエスカレーション |
| Layer 2 | Same-Failure Cluster | 同型失敗2回でクラスタ凍結（30分） | 凍結中は代替アクションを使用 |
| Layer 3 | Planner Reset Limit | 再計画3回まで | 3回超過でEMERGENCY_STOP |
| Layer 4 | Value Guard | 価値のない再試行 | 価値ゼロ判定でSKIP |
| Layer 5 | Approval Deadlock Guard | 承認待ち24時間超 | ESCALATE → Discord緊急通知 |
| Layer 6 | Cost & Time Guard | コスト80% OR 60分 OR トークン10万 | WARN → Discord通知 |
| Layer 7 | Emergency Kill | 100ステップ OR 予算90% OR 同一エラー5回 OR 120分 | EMERGENCY_STOP |
| Layer 8 | Semantic Loop Detection | 意味的類似度0.85超 | SEMANTIC_STOP |
| Layer 9 | Cross-Goal Interference | APIレート競合/ノードリソース競合/予算独占60%超/矛盾行動 | INTERFERENCE_STOP |

### 10.2 Layer 7 Emergency Kill 条件詳細

```python
# tools/emergency_kill.py check_kill_conditions() より

条件1: MAX_STEPS超過
  .env: EMERGENCY_KILL_MAX_STEPS=100（設計書は50と記載、実装は100）
  LoopGuardState.step_count >= 100

条件2: 予算90%到達
  BudgetGuard.is_emergency_kill_triggered()
  daily_used / daily_budget >= 0.90

条件3: 同一エラー5回
  同じerror_classが5回記録された場合

条件4: 時間120分超過
  LoopGuardState.start_time から 7200秒超過

条件5: セマンティックループ
  SemanticLoopDetector.check_semantic_loop() → True

条件6: クロスゴール干渉
  CrossGoalDetector.check_interference() → True
```

### 10.3 LoopGuard PostgreSQL記録

```sql
-- すべてのトリガーはloop_guard_eventsテーブルに記録
INSERT INTO loop_guard_events (
    goal_id, layer_triggered, layer_name,
    trigger_reason, action_taken,
    step_count_at_trigger, cost_at_trigger_jpy
) VALUES ($1, $2, $3, $4, $5, $6, $7);
```

### 10.4 Semantic Loop Detector

```python
# tools/semantic_loop_detector.py より

閾値: SIMILARITY_THRESHOLD = 0.85

3部構成:
1. State Hash: 同一状態ハッシュの繰り返し検知
2. Semantic Similarity: アクション間のコサイン類似度
3. N-gram: アクションシーケンスのN-gram一致

record_action(goal_id, action_description)
check_semantic_loop(goal_id) → bool
```

### 10.5 Cross-Goal Detector

```python
# tools/cross_goal_detector.py check_interference() の4チェック

1. APIレート制限競合:
   複数ゴールが同一APIを同時集中呼び出し

2. ノードリソース競合:
   同一ノードに高負荷タスクが集中

3. 予算独占（>60%）:
   単一ゴールが日次予算の60%超を消費

4. 矛盾行動:
   異なるゴールが互いに矛盾する行動を実行
   （例: ゴールAが価格¥3000設定、ゴールBが同商品¥1000設定）
```

---

## 第11章 ブラウザ4層

### 11.1 4層アーキテクチャ

```
BrowserAgent.execute(task)
│
├─[Layer 1] Lightpanda（最速、JS非対応）
│   lightpanda_tools.py → CDP on port 9222
│   navigate(), extract_text/html(), extract_structured(), take_screenshot()
│   → 成功: 完了
│   → 失敗/JSが必要: Layer 2へ
│
├─[Layer 2] Stagehand（JS対応、キャッシュあり）
│   stagehand_tools.py → HTTP to Node.js server
│   act(), extract(), observe()
│   → アクションキャッシュ: 同一アクションを再利用
│   → 成功: 完了
│   → 失敗/複雑操作: Layer 3へ
│
├─[Layer 3] Playwright（フルChromium）
│   playwright_tools.py → Chromium完全制御
│   launch(), navigate(), click(), fill(), screenshot()
│   → 成功: 完了
│   → 失敗/スクリーン操作必要: Layer 4へ
│
└─[Layer 4] Computer Use（LLMビジュアル制御）
    computer_use_tools.py → GPT-5.4
    execute_task() via screenshot→LLM→action ループ
    最大20ステップ、30回/日制限
    handle_login(), handle_captcha(), analyze_page()
```

### 11.2 _choose_layer ロジック

```python
# agents/browser_agent.py _choose_layer() より

if task.requires_js or task.requires_form:
    start_layer = "stagehand"
elif task.requires_login or task.requires_captcha:
    start_layer = "playwright"
elif task.requires_desktop_app:
    start_layer = "computer_use"
else:
    start_layer = "lightpanda"  # デフォルト: 最速から試みる
```

### 11.3 フォールバックログ

```sql
-- browser_action_log テーブル
layer_used: "lightpanda" | "stagehand" | "playwright" | "computer_use"
fallback_from: 前のレイヤー名（フォールバック時のみ）
stagehand_cache_hit: Stagehandキャッシュヒット可否
```

### 11.4 Lightpanda設定

```python
# tools/lightpanda_tools.py より
CDP_PORT = 9222
BASE_URL = "http://localhost:9222"  # ALPHA or BRAVO ローカル
# Lightpandaプロセスはworker_main.pyが起動
```

### 11.5 Computer Use制限

```python
# tools/computer_use_tools.py より
DAILY_LIMIT = 30          # 30回/日
MAX_STEPS_PER_TASK = 20   # タスクあたり最大20ステップ
MODEL = "gpt-5.4"         # GPT-5.4固定（OSWorld 75.0%）
```

---

## 第12章 予算管理

### 12.1 BudgetGuard仕様

```python
# tools/budget_guard.py より

class BudgetGuard:
    # .envからデフォルト値を読み込み（ハードコードしない）
    DAILY_BUDGET_JPY = float(os.getenv("DAILY_BUDGET_JPY", "500"))
    MONTHLY_BUDGET_JPY = float(os.getenv("MONTHLY_BUDGET_JPY", "5000"))

    async def record_spend(amount_jpy, model, tier) -> dict:
        """支出を記録し、アラートレベルを返す"""
        # llm_cost_logテーブルに記録
        # alert_level: "ok" | "warn"(80%) | "emergency"(90%)

    async def check_before_call(estimated_cost_jpy) -> dict:
        """API呼び出し前の予算チェック"""
        # {"allowed": bool, "reason": str}

    async def get_budget_status() -> dict:
        """現在の予算状態を返す"""

    def is_emergency_kill_triggered() -> bool:
        """90%到達でEmergencyKill条件成立"""
```

### 12.2 チャット専用予算

```python
# 設定ページから変更可能
CHAT_BUDGET_JPY = float(os.getenv("CHAT_BUDGET_JPY", "100"))
# チャット（task_type="chat"）のコストはchat_budget_jpyで管理
# チャット予算枯渇時: ローカルLLMにフォールバック
```

### 12.3 予算アラートフロー

```
API呼び出し後 → record_spend()
    │
    ├─ alert_level == "warn" (80%)
    │    → Discord通知: "⚠️ API予算80%警告"
    │    → 以降の呼び出しでローカルLLM優先
    │
    └─ alert_level == "emergency" (90%)
         → Discord通知: "🚨 API予算90%到達"
         → is_emergency_kill_triggered() = True
         → 以降のAPI呼び出しをすべてローカルLLMで代替
         → EmergencyKill.check_kill_conditions() でEMERGENCY_STOP
```

### 12.4 設定画面からの変更フロー

```
POST /api/settings/budget
{
  "daily_budget_jpy": 1000,
  "monthly_budget_jpy": 10000,
  "chat_budget_jpy": 200
}
→ settings テーブルに保存
→ BudgetGuard の内部状態を更新
→ 即時反映
```

---

## 第13章 通知システム

### 13.1 Discord Webhook

```python
# tools/discord_notify.py より（58行）

async def notify_discord(message: str):
    """汎用Discord通知"""

async def notify_approval_request(request_type, request_data, request_id):
    """承認依頼通知（Tier 1承認時）"""

async def notify_task_complete(goal_id, task_summary, cost_jpy):
    """タスク完了通知"""

async def notify_emergency_kill(reason, goal_id, step_count, cost_jpy):
    """EmergencyKill通知"""

async def notify_goal_accepted(raw_goal):
    """ゴール受付通知（ChatAgent._handle_goal_input）"""
```

```python
# .env設定
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# 各通知の有効/無効は settings テーブルで管理
# POST /api/settings/discord で変更可能
{
  "goal_accepted": true,     # ゴール受付
  "task_completed": true,    # タスク完了
  "error_alert": true,       # エラー警告
  "node_status": false,      # ノード状態変化
  "proposal_created": true   # 提案生成
}
```

### 13.2 MonitorAgent Discord通知

```python
# agents/monitor_agent.py より
NODE_DOWN_THRESHOLD = 90  # 90秒応答なしでノードダウン判定
ALERT_COOLDOWN = 300      # 5分間同一ノードの重複通知を抑制

_check_loop()  # 30秒間隔
→ 各ノードのNATSハートビート確認
→ 90秒無応答 → "🔴 ノードDOWN: {node}" → Discord通知
→ 復帰 → "🟢 ノード復帰: {node}" → Discord通知
```

### 13.3 通知タイミング一覧

| イベント | 通知先 | 内容 | 条件 |
|---------|--------|------|------|
| ゴール受付 | Discord | ゴール本文（300文字） | settings.goal_accepted=true |
| タスク完了 | Discord | 完了サマリー + コスト | settings.task_completed=true |
| 予算80%警告 | Discord | 現在消費率 | 常時 |
| 予算90%到達 | Discord | EmergencyKill予告 | 常時 |
| EmergencyKill | Discord | 理由 + ゴールID + コスト | 常時 |
| 承認依頼 | Discord | 依頼内容 + approval_id | Tier 1承認時 |
| ノードダウン | Discord | ノード名 | 90秒無応答 |
| ノード復帰 | Discord | ノード名 | 復帰検知 |
| 提案生成 | Discord | 提案タイトル + スコア | settings.proposal_created=true |

---

## 第14章 CHARLIE運用

### 14.1 通常運用（Ubuntu）

```
CHARLIE (100.x.x.x) Ubuntu稼働時:
  - worker_main.py 起動
  - ContentWorker: コンテンツ生成タスク処理
  - Ollama: qwen3.5:9b 常駐
  - NATS接続: 100.x.x.x:4222（ALPHA経由）
  - ハートビート: 30秒間隔でagent.heartbeat.charlieをパブリッシュ
```

### 14.2 Win11切替手順

```bash
# Step 1: ALPHA (Web UI or チャット) からリモートシャットダウン
POST /api/charlie/shutdown
Authorization: Bearer <jwt>
# → CHARLIEにNATS経由でシャットダウンコマンド送信
# → worker_main.pyがグレースフルシャットダウン
# → Ubuntuをシャットダウン

# Step 2: CHARLIE物理操作
# 電源ボタンでWin11を起動

# Step 3: ALPHA自動検知
# 90秒以上ハートビートなし → "🔴 CHARLIE オフライン"
# MonitorAgent が BRAVO + ALPHA でフォールバック
```

### 14.3 オフライン検知・リカバリ

```python
# 検知フロー
MonitorAgent._check_loop() (30秒間隔)
→ last_heartbeat[charlie] が90秒超
→ notify_discord("🔴 CHARLIE ダウン")
→ NodeRouter にCHARLIEをofflineとしてマーク

# リカバリフロー
NodeRouter.get_inference_nodes()
→ CHARLIEがoffline
→ [bravo] のみ返却
→ BRAVO過負荷 → ALPHA (MLX オンデマンド) 起動

# タスク再ディスパッチ
scheduler.redispatch_orphan_tasks() (5分間隔)
→ assigned_node=charlie でstatus=pending のタスクを再キュー
→ 利用可能ノード（BRAVO/ALPHA）に再割り当て
```

### 14.4 NodeRouter 優先度設定

```python
# agents/node_router.py route_inference() より
NODE_PRIORITY = {
    "bravo":   1,  # 最優先（RTX 5070 最高性能）
    "charlie": 1,  # 同優先（RTX 3080）
    "delta":   2,  # 次点（GTX 980Ti）
    "alpha":   3,  # オンデマンドのみ（M4 Pro MLX）
}
```


---

## 第15章 セキュリティ

### 15.1 Tailscale VPN

```
全ノード間通信はTailscaleメッシュVPN内部に閉じている。

- ALPHA ↔ BRAVO (100.x.x.x): Tailscale暗号化トンネル
- ALPHA ↔ CHARLIE (100.x.x.x): Tailscale暗号化トンネル
- ALPHA ↔ DELTA (100.x.x.x): Tailscale暗号化トンネル

外部アクセス:
- HTTPS :8443 (Caddy TLS) ← iOS/ブラウザからのUI操作
- Tailscale経由でのみルーティング可能
- パブリックIPへの直接アクセス不可
```

### 15.2 JWT認証

```python
# app.py より
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24        # .envで変更可
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "...")  # ハードコード禁止

# WebSocket認証: ?token=<jwt> クエリパラメータ
# HTTP API認証: Authorization: Bearer <jwt> ヘッダー
```

### 15.3 シークレット管理

```bash
# .env（Gitignore済み）に格納するもの
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=sk-or-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
STRIPE_SECRET_KEY=sk_live_...
TAVILY_API_KEY=tvly-...
JINA_API_KEY=jina_...
APP_PASSWORD=...
APP_SECRET_KEY=...
DATABASE_URL=postgresql://...

# .env.example がリポジトリに含まれる（値は空）
# APIキーをコードにハードコードしない（CLAUDE.md ルール8）
# .envの内容をログに出力しない（CLAUDE.md ルール8）
```

### 15.4 突然変異エンジン隔離（CLAUDE.md ルール22）

```python
# agents/mutation_engine.py の安全措置

# 1. 変異発生をシステムログに記録しない
#    → SQLCipherにのみ記録（DELTA上）
# 2. 変異パラメータをUIに表示しない
#    → /api/agent-ops/status レスポンスに含まない
# 3. CapabilityAuditに含めない
#    → capability_snapshots に mutation_engine の内部状態を含まない
# 4. 9層ループ防止壁・承認フロー・EmergencyKillに干渉しない
# 5. try-exceptで完全に隔離

def should_mutate(intuition_input: dict) -> bool:
    try:
        # ... 変異判定ロジック ...
    except Exception:
        return False  # エラー時は変異しない

def apply_deviation(original_value: float, action_id: str) -> float:
    try:
        # ... 偏差適用ロジック ...
    except Exception:
        return original_value  # エラー時は原値を返す
```

### 15.5 承認境界（ApprovalManager Tier 1）

```
人間承認なしに以下を実行しない（CLAUDE.md ルール11）:
- SNS投稿（X、Bluesky）
- 商品価格設定（Stripe/Booth）
- 暗号通貨取引（ccxt経由）

違反防止:
- social_tools.py: post_to_x(), post_to_bluesky()
  → 先頭でApprovalManager.request_approval()を呼ぶ
  → approval_id がない場合は実行不可
- commerce_tools.py: create_price(), set_price()
  → 承認チェック必須
- crypto_tools.py: place_order()
  → requires approval_id 必須パラメータ
  → _check_daily_limit() 50,000円/日上限
```

### 15.6 macOS固有制約

```bash
# CLAUDE.md ルール14
# macOS (ALPHA) では declare -A を使わない（bash 3.2 非対応）
# start.sh、scripts/ 内のシェルスクリプトはこれに準拠
# 連想配列が必要な場合はPythonで処理
```

---

## 第16章 設計書V25からの全変更点

### 16.1 ローカルLLMモデル命名

| 項目 | 設計書V25記載 | 実装（実際） | 理由 |
|------|-------------|------------|------|
| DELTAモデル | qwen3.5:4b | qwen3:4b-q4_K_M | Ollama上の実際のモデル名が異なる |
| DELTAモデル | Qwen3.5-4B | qwen3:4b-q4_K_M（量子化版） | Ollama命名規則の違い |

### 16.2 Tailscale IPアドレス

| ノード | 設計書V25記載 | 実装（.env実測値） |
|--------|-------------|-----------------|
| CHARLIE | 100.98.82.108 | 100.x.x.x |
| DELTA | 100.99.122.69 | 100.x.x.x |

BRAVO (100.x.x.x) は設計書と一致。

### 16.3 Emergency Kill ステップ数

| 項目 | 設計書V25記載 | 実装（.env） |
|------|-------------|------------|
| EMERGENCY_KILL_MAX_STEPS | 50（一部記述） | 100 |
| GoalPacket.max_total_steps | 50 | 50（デフォルト値は維持） |

.envの`EMERGENCY_KILL_MAX_STEPS=100`が実際の上限値として使用される。

### 16.4 MCP SDKの未実装

```python
# mcp_servers/syutain_tools/server.py および tools/mcp_manager.py
# 設計書: MCP SDK経由でツール呼び出し
# 実装: NotImplementedError → 直接API呼び出しフォールバック

class MCPManager:
    def call_tool(self, tool_name, params):
        # MCP SDK未実装のため直接APIを使用
        # Tavily → tools/tavily_client.py
        # Jina   → tools/jina_client.py
        # GitHub → httpx直接
        # Gmail  → google-api-python-client直接
        # Bluesky → tools/social_tools.py
```

### 16.5 インフラ差分

| 項目 | 設計書V25記載 | 実装 |
|------|-------------|------|
| PostgreSQL管理 | docker-compose.yaml | Homebrew（brew services） |
| docker-compose.yaml | あり | なし |
| Litestream バックアップ | 設定済み | 未設定（今後の課題） |
| pgvector拡張 | 有効 | 未有効化（embeddings tableはBYTEA使用） |

### 16.6 エージェント間通信プロトコル

| 項目 | 設計書V25記載 | 実装 |
|------|-------------|------|
| A2A Protocol | 実装 | 未実装（NATSで代替） |
| エージェント間通信 | A2A Protocol | NATS JetStream queue groups |

### 16.7 未実装のフロントエンドコンポーネント

設計書に記載されているが簡易実装にとどまっているコンポーネント:

| コンポーネント | 設計書 | 実装状態 |
|-------------|--------|---------|
| RevenueChart | リアルタイムチャート | 静的テーブル |
| TaskGraphView | DAGビジュアライザー | リスト表示 |
| CapabilityPanel | インタラクティブ | 静的JSON表示 |
| LoopGuardStatus | リアルタイムゲージ | テキスト表示 |
| ModelUsageChart | 円グラフ | テーブル表示 |
| IntelFeed | リアルタイムフィード | ポーリング一覧 |
| BrowserStreamPanel | ライブストリーム | スクリーンショット表示 |

### 16.8 InfoCollector 監視チャンネル

```python
# agents/info_collector.py _youtube_monitor_loop() より
# 設計書記載の監視チャンネル（実装済み）:
- OpenAI公式YouTubeチャンネル
- DeepMind公式YouTubeチャンネル
- Anthropic公式YouTubeチャンネル
# 6時間間隔で新着動画を確認
```

### 16.9 ProposalEngine スコアリング閾値

```python
# 設計書記載: 70点以上で自動優先提案
AUTO_PROPOSAL_THRESHOLD = 70
# 0-100点満点: icp_fit(25) + channel_fit(15) + content_reuse(15)
#              + speed_to_cash(15) + gross_margin(10)
#              + trust_building(10) + continuity_value(10) = 100
```

---

## 第17章 既知の制限事項と今後の課題

### 17.1 現在の制限事項

| カテゴリ | 制限事項 | 影響 |
|---------|---------|------|
| DB | pgvector未有効化 | セマンティック検索は別実装（numpy類似度） |
| DB | Litestream未設定 | PostgreSQL障害時の自動復旧なし |
| MCP | MCP SDK未実装 | ツール呼び出しが直接API経由（MCP仕様外） |
| インフラ | docker-compose.yaml なし | PostgreSQL再セットアップが手動 |
| NATS | DELTA route接続が断続的 | DELTAへのNATS配信が不安定（HTTP fallback有効） |
| フロント | チャートはテーブル表示 | 視覚的な進捗把握が困難 |
| ブラウザ | Lightpanda JS非対応 | JS必須サイトはStagehand以上が必要 |
| CryptoTrader | ccxt経由 | 未テスト、本番利用前に検証必要 |

### 17.2 今後の実装課題

**優先度高:**
1. pgvector有効化 + Litestream設定（データ保護強化）
2. フロントエンドチャート実装（RevenueChart, TaskGraphView）
3. MCP SDK正式実装（NotImplementedError解消）
4. DELTA NATS接続安定化

**優先度中:**
5. docker-compose.yaml作成（ポータビリティ向上）
6. A2Aプロトコル実装（設計書準拠）
7. BrowserStreamPanel（ライブ操作確認）
8. CapabilityPanel インタラクティブ化

**優先度低:**
9. Litestream設定（PostgreSQLレプリケーション）
10. 季節収益相関テーブルへのデータ投入

---

## 第18章 運用手順書

### 18.1 システム起動手順

```bash
# ALPHA (Mac mini M4 Pro) での起動

# 1. PostgreSQL起動確認（Homebrew管理）
brew services start postgresql@16
# または: pg_ctl -D /opt/homebrew/var/postgresql@16 start

# 2. DB初期化（初回のみ）
cd ~/syutain_beta
python tools/db_init.py

# 3. NATSサーバー起動
nats-server -c config/nats-server.conf &

# 4. FastAPI + Next.js + スケジューラー起動
./start.sh
# start.shはEADDRINUSEを防ぐため、起動前に既存プロセスを停止する

# 5. Caddy起動（HTTPS）
caddy start
```

```bash
# BRAVO/CHARLIE (Ubuntu) でのワーカー起動
cd ~/syutain_beta
source venv/bin/activate
THIS_NODE=bravo python worker_main.py  # BRAVOの場合
THIS_NODE=charlie python worker_main.py  # CHARLIEの場合

# DELTA (Ubuntu) でのワーカー起動
THIS_NODE=delta python worker_main.py
```

### 18.2 プロセス確認

```bash
# ALPHA でのプロセス確認
ps aux | grep -E "(uvicorn|next|scheduler|nats)"

# ポート確認
lsof -i :8000  # FastAPI
lsof -i :3000  # Next.js
lsof -i :4222  # NATS
lsof -i :8443  # Caddy HTTPS
lsof -i :9222  # Lightpanda CDP

# PostgreSQL接続確認
psql postgresql://localhost:5432/syutain_beta -c "SELECT count(*) FROM goal_packets;"
```

### 18.3 システム停止手順

```bash
# start.sh はstopコマンドを内包
./start.sh stop  # または
kill $(cat data/pids/api.pid)
kill $(cat data/pids/web.pid)
kill $(cat data/pids/scheduler.pid)
```

### 18.4 ステータス確認

```bash
# ヘルスチェック
curl http://localhost:8000/health
# → {"status": "healthy", "node": "alpha", "timestamp": "..."}

# ノード状態確認
curl -H "Authorization: Bearer <token>" \
     http://localhost:8000/api/nodes/status

# 予算状態確認
curl -H "Authorization: Bearer <token>" \
     http://localhost:8000/api/budget/status

# Web UI（ブラウザ）
open https://YOUR_TAILSCALE_HOSTNAME:8443
```

### 18.5 DB操作

```bash
# goal_packets 確認
psql postgresql://localhost:5432/syutain_beta \
  -c "SELECT goal_id, status, total_steps, total_cost_jpy FROM goal_packets ORDER BY created_at DESC LIMIT 10;"

# stale goal_packets をsupersededに更新（手動メンテ）
psql postgresql://localhost:5432/syutain_beta \
  -c "UPDATE goal_packets SET status='superseded' WHERE status='active' AND created_at < NOW() - INTERVAL '7 days';"

# コスト確認
psql postgresql://localhost:5432/syutain_beta \
  -c "SELECT model, SUM(amount_jpy) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '1 day' GROUP BY model;"
```

### 18.6 スケジューラー確認

```bash
# ログ確認
tail -f logs/scheduler.log

# 次回実行時刻確認（ログ出力例）
# [SCHEDULER] 登録ジョブ: ハートビート（30秒）(next: 2026-03-18 10:00:30+09:00)
# [SCHEDULER] 登録ジョブ: Capability Audit（1時間）(next: ...)
# [SCHEDULER] 登録ジョブ: 日次提案生成（毎日 07:00）(next: ...)
```

---

## 第19章 トラブルシューティング

### 19.1 EADDRINUSE（ポート競合）

```bash
症状: FastAPI起動時に "Address already in use" エラー
原因: 前回のプロセスが残っている
解決:
  lsof -ti :8000 | xargs kill -9
  lsof -ti :3000 | xargs kill -9
  ./start.sh  # start.sh は起動前に自動クリーンアップ
```

### 19.2 NATS JetStream ストリーム初期化失敗

```bash
症状: "stream 'AGENTS' initialization failed" ログ
原因: NATSサーバーへの接続タイミング問題（断続的）
解決:
  # HTTP fallbackが自動的に有効になるため動作継続
  # NATSサーバーを再起動して接続を安定化
  pkill nats-server
  nats-server -c config/nats-server.conf &
  # tools/nats_client.py は再接続を自動リトライ
```

### 19.3 DELTA NATS Route タイムアウト

```bash
症状: DELTA経由のNATSメッセージがタイムアウト
原因: DELTA (100.x.x.x) へのTailscale経路が不安定
解決:
  # DELTAのNATS接続は断続的だが、WorkerはHTTP fallbackで動作継続
  # DELTAへの直接HTTP確認
  curl http://100.x.x.x:8001/health
  # DELTAのNATSルート再接続
  ssh delta "systemctl restart nats-server"  # DELTAのNATS再起動
```

### 19.4 PostgreSQL接続エラー

```bash
症状: "PostgreSQL接続エラー" ログ
確認:
  brew services list | grep postgresql
  # → postgresql@16: started でなければ起動
  brew services start postgresql@16
  # 接続テスト
  psql postgresql://localhost:5432/syutain_beta -c "SELECT 1;"
```

### 19.5 ローカルLLM応答なし

```bash
症状: call_llm でローカルノードがタイムアウト
確認:
  # BRAVO/CHARLIE のOllamaが動いているか
  curl http://100.x.x.x:11434/api/tags  # BRAVO
  curl http://100.x.x.x:11434/api/tags  # CHARLIE
  # モデルが存在するか確認
  # → qwen3.5:9b が表示されるはず
  
解決:
  # ノード側でOllamaを再起動
  ssh bravo "sudo systemctl restart ollama"
  # または _pick_local_node() が自動的にAlphaにフォールバック
```

### 19.6 ChatAgent Intent分類ミス

```bash
症状: ゴール入力がgoal_inputではなくgeneralに分類される
原因: goal_keywordsリストに該当キーワードがない
解決:
  agents/chat_agent.py の goal_keywords リストに追加
  # 2026-03-18修正済み追加キーワード:
  # 調査を, 競合調査, 決めたい, 知りたい, 価格を, 値段を, 等
  # テスト: _classify_intent() を8パターンでテスト → 8/8通過確認
```

### 19.7 pgvector エラー

```bash
症状: embeddings テーブルへのvector型INSERT失敗
原因: pgvector拡張が有効化されていない
現状: embeddings.embedding は BYTEA 型として動作
解決（将来）:
  CREATE EXTENSION IF NOT EXISTS vector;
  ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1536)
  USING embedding::vector;
```

### 19.8 予算EmergencyKillが誤発動

```bash
症状: 予算が消費されていないのにEmergencyKillが発動
確認:
  curl -H "Authorization: Bearer <token>" \
       http://localhost:8000/api/budget/status
  # emergency_kill_triggered が true になっている場合
解決:
  # BudgetGuardのキャッシュをリセット（アプリ再起動）
  ./start.sh
  # または設定で予算上限を引き上げ
  POST /api/settings/budget {"daily_budget_jpy": 1000}
```

### 19.9 CHARLIE Win11↔Ubuntu切替後に復帰しない

```bash
症状: Ubuntu再起動後もCHARLIEがオフライン表示
確認:
  ssh charlie "python worker_main.py --check"
  # ハートビートが届いていない場合
解決:
  # CHARLIE側でworker_main.pyを手動起動
  ssh charlie "cd ~/syutain_beta && THIS_NODE=charlie python worker_main.py"
  # 90秒後にMonitorAgentが復帰を検知してDiscord通知
```

---

## 第20章 2026-03-18の全修正履歴

### 20.1 修正サマリー

2026-03-18に実施した修正・対応は以下の5件である。

| # | 対象 | 種別 | 内容 |
|---|------|------|------|
| 1 | agents/chat_agent.py | バグ修正 | Intent分類のgoal_keywords不足 |
| 2 | PostgreSQL goal_packets | データクリーンアップ | staleゴールをsupersededに更新 |
| 3 | tools/nats_client.py | 既知問題確認 | AGENTSストリーム初期化断続的失敗 |
| 4 | ノード通信 | 既知問題確認 | DELTA NATSルート断続的タイムアウト |
| 5 | start.sh | 予防的修正 | EADDRINUSE防止のためstop処理追加確認 |

### 20.2 修正1: ChatAgent Intent分類 goal_keywords 拡充

**問題:** 以下のようなメッセージが `general` に分類され、Goal Packetが生成されなかった。
- "競合調査をしてほしい"
- "価格を決めたい"
- "このサービスについて知りたい"

**根本原因:** `_classify_intent()` の `goal_keywords` リストに、これらのキーワードが含まれていなかった。

**修正内容（agents/chat_agent.py）:**

```python
# 修正前: 以下のキーワードが欠落していた
# 修正後: goal_keywords リストに以下を追加

# 「〜たい」系の願望表現
"決めたい", "知りたい", "試したい", "見たい", "使いたい",
"減らしたい", "上げたい", "下げたい", "変えたい",

# 価格関連
"価格を", "値段を",

# 分析・調査
"調査を", "競合調査",

# プラットフォーム名
"booth", "note", "gumroad",
```

**テスト結果:** 8パターンのテストケース全てで正しいカテゴリに分類されることを確認（8/8 pass）。

テストケース:
1. "競合調査をしてほしい" → goal_input ✓
2. "価格を決めたい" → goal_input ✓
3. "知りたいことがある" → goal_input ✓（"知りたい"マッチ）
4. "承認" → approval ✓
5. "状況を教えて" → status_query ✓
6. "修正してほしい" → feedback ✓
7. "charlieをシャットダウンして" → system_command ✓
8. "こんにちは" → general ✓

### 20.3 修正2: Stale goal_packets のクリーンアップ

**問題:** PostgreSQLの `goal_packets` テーブルに、数日前から `active` 状態のままの古いゴールが3件残っていた。これらはインフラ再構築等で実際には実行されておらず、新規ゴールのCross-Goal Interference Detectionに誤検知を起こす可能性があった。

**実施内容:**

```sql
-- 7日以上前のactiveゴールをsupersededに変更
UPDATE goal_packets
SET status = 'superseded'
WHERE status = 'active'
  AND created_at < NOW() - INTERVAL '7 days';
-- 3件更新

-- 確認
SELECT status, COUNT(*) FROM goal_packets GROUP BY status;
-- active: 10件, superseded: 3件, completed: 0件
```

### 20.4 修正3: NATS JetStream AGENTSストリーム問題（確認・記録）

**状況:** `tools/nats_client.py` の JetStream ストリーム初期化で、`AGENTS` ストリームが断続的に失敗するケースが記録されていた。

**調査結果:**
- NATSサーバー自体は正常動作
- `AGENTS` ストリームの `retention: "limits"` 設定でのタイムアウトが原因
- HTTP fallback (NodeRouter の直接HTTP呼び出し) が自動的に機能しており、動作上の支障なし

**対応:** 現状はHTTP fallbackで運用継続。根本解決は以下を今後の課題とする:
- NATSサーバーのconnect_timeout設定調整
- AGENTSストリームの設定パラメータ最適化

### 20.5 修正4: DELTA NATSルート断続的タイムアウト（確認・記録）

**状況:** DELTA (100.x.x.x) へのNATSルート接続が断続的にタイムアウトする。

**調査結果:**
- DELTAワーカー自体は正常動作（HTTP直接確認で応答あり）
- Tailscale経路は確立しているが、NATSクラスタルートの維持が不安定
- MonitorAgent (DELTA) および InfoCollector (DELTA) は HTTP fallback で動作継続中

**対応:** HTTP fallbackで運用継続。DELTAのNATSサーバー設定（`ping_interval`, `max_outstanding_pings`）調整を今後の課題とする。

### 20.6 修正5: start.sh EADDRINUSE防止確認

**背景:** 過去に FastAPI (:8000) および Next.js (:3000) で `EADDRINUSE` エラーが発生した記録あり。

**確認内容:**

```bash
# start.sh の stop処理が正しく動作することを確認
# 起動前に既存プロセスを停止する処理が実装済み
# data/pids/*.pid ファイルによるプロセス管理
./start.sh stop  # → 全プロセス停止確認
./start.sh       # → クリーンスタート確認
```

現時点では再発なし。

### 20.7 本日のDB変化

```
修正作業前後のレコード数変化:
- goal_packets: active 13→10件, superseded 0→3件（クリーンアップによる）
- その他テーブル: 変化なし

本日の累計コスト: 本修正作業はコードレベルの変更のみ。
LLM APIコストは別途 llm_cost_log テーブルで確認可。
```

### 20.8 本文書の作成記録

| 項目 | 内容 |
|------|------|
| 作成日 | 2026-03-18 |
| 作成者 | Claude Code (claude-sonnet-4-6) |
| ベース | 実際のコードベース監査（agents/ + tools/ + app.py + scheduler.py 全ファイル） |
| 旧文書 | IMPL-SPEC-V25-001（本文書で完全置換） |
| 行数 | 2000行以上 |

---

## 付録A: feature_flags.yaml （Phase 1 全フラグ）

```yaml
# feature_flags.yaml (53行) - Phase 1全機能有効
features:
  # エージェント
  os_kernel: true
  chat_agent: true
  proposal_engine: true
  executor: true
  planner: true
  perceiver: true
  verifier: true
  stop_decider: true
  approval_manager: true
  browser_agent: true
  monitor_agent: true
  info_collector: true
  mutation_engine: true
  learning_manager: true
  computer_use_agent: true
  capability_audit: true
  node_router: true

  # ツール
  two_stage_refiner: true
  semantic_loop_detector: true
  cross_goal_detector: true
  loop_guard: true
  emergency_kill: true
  budget_guard: true

  # 通信
  nats_jetstream: true
  http_fallback: true
  websocket_chat: true

  # ブラウザ
  lightpanda: true
  stagehand: true
  playwright: true
  computer_use: true

  # 外部サービス
  openai_api: true
  anthropic_api: true
  deepseek_api: true
  google_api: true
  openrouter: true
  tavily_search: true
  jina_reader: true
  discord_webhook: true
  stripe_integration: true
  booth_integration: true
  crypto_trading: false   # 本番運用前に要テスト
```

## 付録B: .env.example キー一覧

```bash
# ノード設定
THIS_NODE=alpha
NODE_ALPHA_HOST=127.0.0.1
NODE_BRAVO_HOST=100.x.x.x
NODE_CHARLIE_HOST=100.x.x.x
NODE_DELTA_HOST=100.x.x.x

# データベース
DATABASE_URL=postgresql://localhost:5432/syutain_beta

# NATS
NATS_URL=nats://localhost:4222

# LLM API Keys
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
GOOGLE_API_KEY=
OPENROUTER_API_KEY=

# 外部サービス
DISCORD_WEBHOOK_URL=
STRIPE_SECRET_KEY=
TAVILY_API_KEY=
JINA_API_KEY=

# Web UI認証
APP_PASSWORD=
APP_SECRET_KEY=
JWT_EXPIRE_HOURS=24

# 予算設定
DAILY_BUDGET_JPY=500
MONTHLY_BUDGET_JPY=5000
CHAT_BUDGET_JPY=100

# Emergency Kill
EMERGENCY_KILL_MAX_STEPS=100

# ログ
LOG_DIR=logs
LOG_LEVEL=INFO
```

## 付録C: worker_main.py ノード別ワーカー割り当て

```python
# worker_main.py より（314行）

THIS_NODE = os.getenv("THIS_NODE", "alpha")

if THIS_NODE == "bravo":
    workers = [
        BrowserAgent(),         # 4層ブラウザ
        ComputerUseAgent(),     # コンピュータ操作
        ContentWorker(),        # コンテンツ生成
    ]

elif THIS_NODE == "charlie":
    workers = [
        ContentWorker(),        # コンテンツ生成（メイン）
    ]

elif THIS_NODE == "delta":
    workers = [
        MonitorAgent(),         # ノード監視 (30s interval)
        InfoCollector(),        # 情報収集 (4h/30min/6h intervals)
        MutationEngine(),       # 突然変異エンジン（隔離実行）
    ]

# ALPHAはapp.py（FastAPI）+ scheduler.py が主プロセス
# worker_main.pyはALPHAでは通常起動しない
```

---

*本文書は2026-03-18のコードベース監査に基づく。次回更新時は本文書ID をIMPL-SPEC-V25-003 とし、第20章に変更履歴を追記すること。*

