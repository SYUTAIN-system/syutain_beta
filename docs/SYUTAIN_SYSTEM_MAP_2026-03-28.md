# SYUTAINβ V25 - システム完全マップ

> 生成日: 2026-03-28 | 対象: SYUTAINβ Phase 1 稼働中システム

---

## 1. アーキテクチャ概要

```
┌─── ALPHA (Mac mini M4 Pro 16GB) ──────────────────────────────┐
│ OS_Kernel / ProposalEngine / ApprovalManager / ChatAgent      │
│ FastAPI Backend / Next.js Web UI / PostgreSQL / NATS Server   │
│ LLM: Qwen3.5-9B (MLX, オンデマンド起動)                       │
└───────────────────────────────────────────────────────────────┘
              ↕ NATS JetStream (6ストリーム)
    ┌─────────┼──────────┬──────────┐
    ↓         ↓          ↓          ↓
┌─BRAVO─┐ ┌─CHARLIE─┐ ┌─DELTA──┐  [外部API]
│RTX5070│ │RTX 3080 │ │GTX980Ti│  GPT-5.4 / Claude
│Browser│ │推論ワーカ│ │監視    │  Gemini / DeepSeek
│Comp.  │ │コンテンツ│ │情報収集│  Tavily / Jina
│Use    │ │生成     │ │        │
│9B     │ │9B       │ │4B      │
└───────┘ └─────────┘ └────────┘
```

### ノード構成

| ノード | ハードウェア | 役割 | ローカルLLM |
|--------|------------|------|------------|
| **ALPHA** | Mac mini M4 Pro 16GB | 司令塔・API・DB・NATS | Qwen3.5-9B (MLX, オンデマンド) |
| **BRAVO** | Ryzen + RTX 5070 12GB | ブラウザ操作・Computer Use | Qwen3.5-9B (Ollama) |
| **CHARLIE** | Ryzen 9 + RTX 3080 10GB | 推論・コンテンツ生成 | Qwen3.5-9B (Ollama) |
| **DELTA** | Xeon E5 + GTX 980Ti 6GB | 監視・情報収集・軽量推論 | Qwen3.5-4B (Ollama) |

### 通信

- **Tailscale VPN** でノード間接続
- **NATS JetStream** 6ストリーム: TASKS / AGENTS / PROPOSALS / MONITOR / BROWSER / INTEL
- HTTPは障害時フォールバックのみ

---

## 2. 5段階自律ループ

```
[1] PERCEIVE (知覚)
 └→ CapabilityAudit + Budget + MCP + 前回結果 + 市場文脈

[2] THINK (計画)
 └→ GoalPacket → TaskDAG → ノード割当 → フォールバック計画

[3] ACT (実行)
 └→ 承認ゲート → ツール選択 → LLM/ブラウザ/ComputerUse → 成果物保存

[4] VERIFY (検証)
 └→ 品質スコア → 進捗率 → リトライ価値判定 → エラー分類

[5] STOP/CONTINUE (判断)
 └→ LoopGuard 9層 → 完了/継続/リトライ/切替/エスカレーション/緊急停止
```

---

## 3. エージェント一覧（17体）

### 3.1 中核エージェント（agents/）

| エージェント | ファイル | 役割 | 稼働ノード |
|------------|---------|------|-----------|
| **OS_Kernel** | os_kernel.py | 司令塔。GoalPacket管理、5段階ループ駆動 | ALPHA |
| **Perceiver** | perceiver.py | 環境認知。4ノード状態・予算・MCP可用性を収集 | ALPHA |
| **Planner** | planner.py | タスクDAG生成。依存関係・ノード割当を計画 | ALPHA |
| **Executor** | executor.py | タスク実行。承認ゲート→ツール呼出→成果物保存 | ALPHA |
| **Verifier** | verifier.py | 結果検証。品質スコア・進捗率・リトライ判定 | ALPHA |
| **StopDecider** | stop_decider.py | 継続/停止判断。LoopGuard 9層チェック | ALPHA |
| **ProposalEngine** | proposal_engine.py | 3層提案生成（提案→反論→代替案）、収益スコアリング | ALPHA |
| **ApprovalManager** | approval_manager.py | 承認ワークフロー（Tier 1/2/3）管理 | ALPHA |
| **ChatAgent** | chat_agent.py | 双方向チャット。意図分類（6種）→ルーティング | ALPHA |
| **BrowserAgent** | browser_agent.py | 4層ブラウザ自動化（下記参照） | BRAVO |
| **ComputerUseAgent** | computer_use_agent.py | GPT-5.4 Computer Use（視覚ベースGUI操作） | BRAVO |
| **MonitorAgent** | monitor_agent.py | ノード死活監視（30秒間隔ハートビート） | DELTA |
| **InfoCollector** | info_collector.py | 情報収集スケジューリング（Tavily/Jina/RSS/YouTube） | DELTA |
| **CapabilityAudit** | capability_audit.py | システム能力スナップショット（毎時） | ALPHA |
| **NodeRouter** | node_router.py | ノード間メッセージルーティング | ALPHA |
| **LearningManager** | learning_manager.py | 週次学習レポート・モデルフィードバック | ALPHA |
| **MutationEngine** | mutation_engine.py | 制御された突然変異（SQLCipher隔離、秘匿） | DELTA |

### 3.2 BrowserAgent 4層アーキテクチャ

```
Layer 1: Lightpanda   → 高速CDP、構造化データ抽出
Layer 2: Stagehand v3 → AI駆動、自己修復、アクションキャッシュ
Layer 3: Playwright   → 重量SPA（React/Angular/Vue）
Layer 4: GPT-5.4 CU   → CAPTCHA、ログイン、視覚UI操作
```

自動選択: ログイン/CAPTCHA→L4、重量SPA→L3、通常Web→L2、静的/API→L1
フォールバック: 失敗時は下位レイヤーに自動降格

### 3.3 ProposalEngine 3層構造

| 層 | 内容 | 目的 |
|----|------|------|
| Layer 1 | 主提案 | ICP適合・チャネル適合・収益性を最大化 |
| Layer 2 | 反論 | リスク・失敗条件・中断基準を明示 |
| Layer 3 | 代替案 | 低リスク版・小規模テスト版・次善策 |

**収益スコア（100点満点）**: ICP適合25 + チャネル適合15 + コンテンツ再利用15 + 収益化速度15 + 粗利率10 + 信頼構築10 + 継続性10

### 3.4 承認Tier

| Tier | 対象 | 承認方法 |
|------|------|---------|
| **Tier 1** | SNS投稿・商品公開・価格設定・暗号通貨取引 | 人間承認必須 |
| **Tier 2** | 情報パイプライン・モデル切替 | 自動承認＋通知 |
| **Tier 3** | ヘルスチェック・ログローテーション | 完全自動 |

---

## 4. ツール一覧（30+）

### 4.1 LLMルーティング

| ツール | ファイル | 機能 |
|--------|---------|------|
| **LLM Router V6** | llm_router.py | `choose_best_model_v6()` モデル自動選択 |
| **Model Registry** | model_registry.py | モデルメタデータ管理 |
| **Two-Stage Refiner** | two_stage_refiner.py | ローカル→API 2段階精錬 |

**モデルルーティング**:
```
quality="low"  → DELTA (qwen3.5-4b) ¥0
quality="med"  → BRAVO/CHARLIE (qwen3.5-9b) or nemotron-jp ¥0
quality="high" → Gemini Flash / Haiku / DeepSeek V3.2 ¥0.003〜
日本語コンテンツ → nemotron-jp 優先 ¥0
Computer Use   → GPT-5.4
```

### 4.2 安全機構

| ツール | ファイル | 機能 |
|--------|---------|------|
| **LoopGuard 9層** | loop_guard.py | 9層ループ防止壁 |
| **Emergency Kill** | emergency_kill.py | 緊急停止トリガー |
| **Budget Guard** | budget_guard.py | 日次/月次コスト制限 |
| **Semantic Loop Detector** | semantic_loop_detector.py | 意味的繰り返し検知 |
| **Cross-Goal Detector** | cross_goal_detector.py | ゴール間干渉検知（V25新規） |
| **Platform NG Check** | platform_ng_check.py | NGワードフィルタリング |

**LoopGuard 9層**:

| 層 | 名前 | 条件 | アクション |
|----|------|------|----------|
| 1 | リトライ予算 | 同一アクション3回 | エスカレーション |
| 2 | 同一障害クラスタ | 同一エラー2回 | 30分凍結 |
| 3 | Planner再計画上限 | 再計画3回以上 | エスカレーション |
| 4 | 価値ガード | 低価値リトライ | エスカレーション |
| 5 | 承認デッドロック | 24時間待機超過 | エスカレーション |
| 6 | コスト＆時間 | 予算80%/60分超過 | 警告/停止 |
| 7 | **Emergency Kill** | 50ステップ/予算90%/同一エラー5回/2時間超過 | **強制停止** |
| 8 | セマンティックループ | 同一状態ハッシュ3回 | 意味的停止 |
| 9 | Cross-Goal干渉 | リソース競合検知 | 干渉停止 |

### 4.3 情報収集

| ツール | ファイル | 機能 |
|--------|---------|------|
| **Info Pipeline** | info_pipeline.py | 情報収集統合パイプライン |
| **Tavily Client** | tavily_client.py | Web検索API |
| **Jina Client** | jina_client.py | コンテンツ抽出API |
| **Embedding Tools** | embedding_tools.py | pgvector + Jina Embeddings v3 |

**情報ソース**: Gmail(80+キーワード) / Tavily / Jina Reader / RSS / YouTube

### 4.4 ブラウザ・自動化

| ツール | ファイル | 機能 |
|--------|---------|------|
| **Lightpanda Tools** | lightpanda_tools.py | CDP高速データ抽出 |
| **Stagehand Tools** | stagehand_tools.py | AI駆動ブラウザ操作 |
| **Playwright Tools** | playwright_tools.py | Chromiumフォールバック |
| **Computer Use Tools** | computer_use_tools.py | GPT-5.4視覚操作 |

### 4.5 コンテンツ・SNS

| ツール | ファイル | 機能 |
|--------|---------|------|
| **Content Tools** | content_tools.py | note記事・Booth商品説明生成 |
| **Content Multiplier** | content_multiplier.py | 1素材→17派生物パイプライン |
| **Social Tools** | social_tools.py | Bluesky/X/Threads自動投稿 |
| **Analytics Tools** | analytics_tools.py | エンゲージメント追跡 |
| **Competitive Analyzer** | competitive_analyzer.py | 競合分析 |

### 4.6 インフラ・通信

| ツール | ファイル | 機能 |
|--------|---------|------|
| **NATS Client** | nats_client.py | JetStream初期化・メッセージブローカー |
| **DB Init** | db_init.py | PostgreSQL/SQLiteスキーマ管理 |
| **Node Manager** | node_manager.py | ノード間タスクディスパッチ |
| **MCP Manager** | mcp_manager.py | MCPサーバー動的接続 |
| **Event Logger** | event_logger.py | イベントログ記録 |
| **Edit Tracker** | edit_tracker.py | 変更追跡 |
| **Discord Notify** | discord_notify.py | Discord Webhook通知 |
| **Storage Tools** | storage_tools.py | ファイルストレージ管理 |

### 4.7 収益・取引

| ツール | ファイル | 機能 |
|--------|---------|------|
| **Commerce Tools** | commerce_tools.py | Stripe + Booth連携 |
| **Crypto Tools** | crypto_tools.py | BTC/JPY価格追跡（CCXT） |

---

## 5. データベーススキーマ

### PostgreSQL（ALPHA、共有状態）

**主要テーブル**:

```
goal_packets        - ゴール定義・進捗・制約
tasks               - タスク状態・ノード割当・品質スコア
proposal_history    - 3層提案履歴・収益スコア
approval_queue      - 承認キュー（Tier 1/2/3）
intel_items         - 収集情報・重要度スコア
chat_messages       - チャット履歴
posting_queue       - SNS投稿キュー・スケジュール
llm_cost_log        - LLMコスト追跡
event_log           - システムイベント（severity付）
browser_action_log  - ブラウザ操作ログ（4層）
agent_reasoning_trace - エージェント判断根拠
model_quality_log   - モデル品質フィードバック
loop_guard_events   - LoopGuard発動履歴
revenue_linkage     - 収益帰属追跡
crypto_trades       - 暗号通貨取引記録
node_state          - ノード状態管理
capability_snapshots - 能力スナップショット
settings            - 動的設定値
content_edit_log    - コンテンツ編集追跡
```

**Brain-α専用テーブル**:
```
brain_alpha_session    - セッション記憶（要約・未解決課題・対話数）
brain_alpha_reasoning  - 推論ログ
brain_cross_evaluation - クロス評価
brain_handoff          - セッション引継ぎ
daichi_dialogue_log    - 大知対話ログ（価値観抽出）
daichi_writing_examples - 文体サンプル
persona_memory         - ペルソナ記憶（価値観・タブー）
claude_code_queue      - Brain-α→Claude Codeタスクキュー
```

### SQLite（各ノードローカル）
- PostgreSQL不可時のフォールバック
- 03:30 JSTにrsyncバックアップ

---

## 6. APIエンドポイント（app.py FastAPI）

**認証**: JWT Bearer (HS256, 24時間有効)

| メソッド | パス | 機能 |
|---------|------|------|
| POST | `/auth/login` | JWT発行 |
| POST | `/goals` | ゴール作成 |
| GET | `/goals/{id}` | ゴール状態取得 |
| POST | `/chat/send` | チャット送信 |
| GET | `/chat/stream` | SSEストリーム |
| WS | `/ws/chat` | WebSocketチャット |
| GET | `/proposals` | 提案一覧 |
| POST | `/proposals/{id}/feedback` | 提案承認/却下 |
| GET | `/approvals/pending` | 承認待ち一覧 |
| POST | `/approvals/{id}/approve` | 承認 |
| POST | `/approvals/{id}/reject` | 却下 |
| GET | `/intel/items` | 情報一覧 |
| GET | `/nodes/status` | ノード状態 |
| GET | `/models/available` | 利用可能モデル |
| GET | `/events/stream` | リアルタイムSSE |
| GET/POST | `/settings/*` | 設定管理 |

---

## 7. スケジューラジョブ（scheduler.py）

| ジョブID | トリガー | 間隔 | 内容 |
|---------|---------|------|------|
| heartbeat | Interval | 30秒 | ノードハートビート |
| capability_audit | Interval | 1時間 | 全ノード能力監査 |
| info_pipeline | Interval | 12時間 | 情報収集パイプライン |
| daily_proposal | Cron | 07:00 JST | 日次提案生成 |
| weekly_proposal | Cron | 月曜09:00 | 週次提案 |
| weekly_learning | Cron | 日曜21:00 | 週次学習レポート |
| redispatch_orphan | Interval | 5分 | 孤立タスク再配分 |
| night_batch_sns_1 | Cron | 22:00 | X島原+SYUTAIN (10件) |
| night_batch_sns_2 | Cron | 22:30 | Bluesky前半 (13件) |
| night_batch_sns_3 | Cron | 23:00 | Bluesky後半 (13件) |
| night_batch_sns_4 | Cron | 23:30 | Threads (13件) |
| posting_queue_process | Interval | 毎分 | 投稿キュー自動投稿 |
| self_heal_check | Interval | — | 自律修復チェック |
| brain_alpha_health | Interval | — | Brain-αヘルスチェック |
| postgresql_backup | Cron | 03:00 | DB日次バックアップ |
| sqlite_backup_rsync | Cron | 03:30 | ノードDB同期 |
| night_batch_content | Cron | — | 夜間コンテンツ生成 |

---

## 8. Web UI（Next.js）

### ページ構成（12ページ）

| パス | 機能 |
|------|------|
| `/` | ダッシュボード（ノード状態、最近のゴール） |
| `/chat` | チャットインターフェース（SSE+WebSocket） |
| `/proposals` | 提案一覧（3層表示） |
| `/tasks` | タスク監視・進捗表示 |
| `/intel` | 情報収集ステータス |
| `/revenue` | 収益パイプライン（ステージ1-11） |
| `/models` | モデル品質＋コストダッシュボード |
| `/agent-ops` | エージェント操作パネル |
| `/node-control` | ノード別制御 |
| `/brain-alpha` | デジタルツイン・ペルソナ |
| `/settings` | 設定画面 |
| `/timeline` | イベントタイムライン |

### コンポーネント
- `AuthGate.tsx` — JWT認証ゲート
- `ChatInterface.tsx` — SSE+WebSocketチャットUI
- `ProposalCard.tsx` — 3層提案カード
- `NodeStatusPanel.tsx` — ノード状態可視化
- `MobileTabBar.tsx` — モバイルナビ
- `ErrorBoundary.tsx` — エラーハンドリング

---

## 9. Brain-α（デジタルツイン）

### モジュール構成（brain_alpha/）

| ファイル | 機能 |
|---------|------|
| memory_manager.py | セッション記憶の保存・復元 |
| persona_bridge.py | ペルソナ統合 |
| content_pipeline.py | コンテンツ生成フロー |
| sns_batch.py | SNSバッチ生成 |
| startup_review.py | セッション開始時精査（8フェーズ） |
| executive_briefing.py | デイリーブリーフィング |
| cross_evaluator.py | マルチゴール評価 |
| escalation.py | エスカレーションテンプレート |
| safety_check.py | コンテンツ安全性検証 |
| note_quality_checker.py | 記事品質チェック |
| product_packager.py | 商品説明生成 |
| session_save.py | セッション永続化 |
| auto_log.py | 判断自動ログ |

### 記憶構造
- **感覚記憶**: チャネルイベント（秒単位）
- **短期記憶**: Claude コンテキストウィンドウ
- **長期エピソード記憶**: brain_alpha_session（何を・いつ・結果）
- **長期意味記憶**: persona_memory（哲学・価値観・パターン）
- **長期手続き記憶**: CLAUDE.md + コード

---

## 10. 戦略ファイル（strategy/）

| ファイル | 内容 |
|---------|------|
| ICP_DEFINITION.md | ターゲット顧客定義（30代実務クリエイター） |
| CHANNEL_STRATEGY.md | チャネル別配信戦略 |
| CONTENT_STRATEGY.md | コンテンツアーキタイプ・トーン |

**ICP**: 「追いつきたいけどコード地獄には入りたくない30代実務クリエイター」
- 28-39歳、非エンジニア（デザイナー・マーケター・ライター）
- 年収300-600万、月間自由予算3,000-15,000円
- AI希望+不安、失敗の現実性を求める

---

## 11. 設定ファイル

### feature_flags.yaml（Phase 1 有効）
```
✅ web_ui, discord_notifications, nats_messaging, postgresql
✅ local_llm_alpha_mlx, local_llm_bravo/charlie/delta
✅ loop_guard_9layer, semantic_loop, cross_goal, emergency_kill
✅ two_stage_refinement, info_pipeline, mcp_integration
✅ browser: playwright/lightpanda/stagehand/gpt54
✅ bluesky/x/threads_auto_post, mutation_engine
❌ note_auto_publish, booth_auto_publish (Phase 2)
❌ crypto_auto_trading, stripe_integration (Phase 2)
```

### nats-server.conf
```
ALPHA (hub): 0.0.0.0:4222, JetStream 256MB mem / 1GB file
Cluster routes: BRAVO / CHARLIE / DELTA (Tailscale IPs)
```

---

## 12. ファイル構造

```
syutain_beta/
├── app.py                    # FastAPI バックエンド (~1,700行)
├── scheduler.py              # APScheduler ジョブ管理 (~400行)
├── worker_main.py            # ノードワーカー (~310行)
├── start.sh                  # 起動スクリプト
├── requirements.txt          # Python依存関係
├── feature_flags.yaml        # 機能フラグ
├── .env                      # 環境変数（秘匿）
├── CLAUDE.md                 # 絶対ルール22条
│
├── agents/                   # エージェント (17体)
│   ├── os_kernel.py
│   ├── perceiver.py
│   ├── planner.py
│   ├── executor.py
│   ├── verifier.py
│   ├── stop_decider.py
│   ├── proposal_engine.py
│   ├── approval_manager.py
│   ├── chat_agent.py
│   ├── browser_agent.py
│   ├── computer_use_agent.py
│   ├── monitor_agent.py
│   ├── info_collector.py
│   ├── capability_audit.py
│   ├── node_router.py
│   ├── learning_manager.py
│   └── mutation_engine.py
│
├── tools/                    # ツール (30+)
│   ├── llm_router.py         # V6モデルルーティング
│   ├── loop_guard.py         # 9層ループ防止
│   ├── emergency_kill.py     # 緊急停止
│   ├── budget_guard.py       # コスト制限
│   ├── semantic_loop_detector.py
│   ├── cross_goal_detector.py
│   ├── nats_client.py        # NATSメッセージング
│   ├── db_init.py            # DBスキーマ
│   ├── info_pipeline.py      # 情報収集
│   ├── tavily_client.py
│   ├── jina_client.py
│   ├── embedding_tools.py
│   ├── content_tools.py
│   ├── content_multiplier.py
│   ├── two_stage_refiner.py
│   ├── social_tools.py       # SNS 4チャネル
│   ├── analytics_tools.py
│   ├── competitive_analyzer.py
│   ├── lightpanda_tools.py
│   ├── stagehand_tools.py
│   ├── playwright_tools.py
│   ├── computer_use_tools.py
│   ├── node_manager.py
│   ├── mcp_manager.py
│   ├── event_logger.py
│   ├── edit_tracker.py
│   ├── discord_notify.py
│   ├── model_registry.py
│   ├── storage_tools.py
│   ├── commerce_tools.py
│   ├── crypto_tools.py
│   └── platform_ng_check.py
│
├── brain_alpha/              # デジタルツイン
│   ├── memory_manager.py
│   ├── persona_bridge.py
│   ├── content_pipeline.py
│   ├── sns_batch.py
│   ├── startup_review.py
│   ├── executive_briefing.py
│   ├── cross_evaluator.py
│   ├── escalation.py
│   ├── safety_check.py
│   ├── note_quality_checker.py
│   ├── product_packager.py
│   ├── session_save.py
│   └── auto_log.py
│
├── config/                   # ノード設定
│   ├── nats-server.conf
│   ├── node_alpha.yaml
│   ├── node_bravo.yaml
│   ├── node_charlie.yaml
│   └── node_delta.yaml
│
├── prompts/                  # システムプロンプト
│   ├── SYSTEM_OS_KERNEL.md
│   ├── SYSTEM_PLANNER.md
│   ├── SYSTEM_EXECUTOR.md
│   ├── SYSTEM_VERIFIER.md
│   ├── SYSTEM_STOP_DECIDER.md
│   ├── SYSTEM_PERCEIVER.md
│   ├── SYSTEM_PROPOSAL_ENGINE.md
│   ├── SYSTEM_APPROVAL_MANAGER.md
│   ├── SYSTEM_BROWSER_AGENT.md
│   ├── SYSTEM_CHAT_AGENT.md
│   ├── anti_ai_writing.md
│   ├── bluesky_worldview.md
│   └── strategy_identity.md
│
├── strategy/                 # 戦略ファイル
│   ├── ICP_DEFINITION.md
│   ├── CHANNEL_STRATEGY.md
│   └── CONTENT_STRATEGY.md
│
├── web/                      # Next.js フロントエンド
│   ├── app/
│   │   ├── page.tsx          # ダッシュボード
│   │   ├── chat/page.tsx
│   │   ├── proposals/page.tsx
│   │   ├── tasks/page.tsx
│   │   ├── intel/page.tsx
│   │   ├── revenue/page.tsx
│   │   ├── models/page.tsx
│   │   ├── agent-ops/page.tsx
│   │   ├── node-control/page.tsx
│   │   ├── brain-alpha/page.tsx
│   │   ├── settings/page.tsx
│   │   └── timeline/page.tsx
│   └── components/
│       ├── AuthGate.tsx
│       ├── ChatInterface.tsx
│       ├── ProposalCard.tsx
│       ├── NodeStatusPanel.tsx
│       ├── MobileTabBar.tsx
│       └── ErrorBoundary.tsx
│
├── mcp_servers/              # MCPサーバー
│   ├── config.yaml
│   └── syutain_tools/
│       └── server.py
│
├── scripts/                  # ユーティリティスクリプト
├── data/                     # データ・成果物
│   ├── artifacts/
│   └── .gitkeep
├── logs/                     # ログ
└── docs/                     # ドキュメント
    ├── approval_policy.md
    ├── external_sources.md
    ├── ops_runbook.md
    ├── revenue_playbook.md
    ├── simulation_results.md
    ├── IMPLEMENTATION_SPEC.md
    ├── SESSION_HANDOFF_*.md
    └── OPERATION_LOG_*.md
```

---

## 13. 設計上の重要な判断

| 判断 | 理由 |
|------|------|
| 4ノード分散 | 役割分離（司令/操作/推論/監視）でリソース最適化 |
| 9層LoopGuard | 行動→価値→緊急→意味→ゴール間の多層防御 |
| 2段階精錬 | ローカル(¥0)で高速ドラフト→API(少額)で最終品質 |
| 3層提案 | 提案+反論+代替で意思決定の質を担保 |
| 4層ブラウザ | 速度→AI駆動→SPA→視覚操作の段階的フォールバック |
| NATS JetStream | ノード間非同期通信、障害耐性、メッセージ永続化 |
| 突然変異エンジン隔離 | 安全機構に一切干渉させない完全隔離設計 |

---

*このドキュメントはSYUTAINβ V25のコードベースを直接分析して生成されました。*
