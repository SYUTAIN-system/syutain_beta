# SYUTAINβ 完全設計書 V29

> **「これは、単なるAIエージェントではない。4台のPCがPhase 1初日から全て連携し、NATSとTailscaleで結ばれ、Web UIを通じてiPhoneからリアルタイム監視でき、18のコアエージェントと64のツールが自律的に認識・思考・行動・検証・停止判断を行い、目標だけを受けても道筋が変わっても自分で考え、自分で動き、自分で止まれる『自律分散型 事業OS』である。これは技術文書であり、同時にドキュメンタリーでもある。一人の人間とAIが、ゼロから収益を作り、進化し続ける過程の全記録。V29で、このOSは並列自律デバッグ能力を獲得した。」**

**バージョン:** V29（2026年4月1日・完全設計書）
**プロジェクトオーナー:** 島原大知（@Sima_daichi）
**AIエージェント:** SYUTAINβ（@syutain_beta）
**システム名:** SYUTAINβ（Sustainable Yield Utilizing Technology And Intelligence Network β）
**月収目標:** 12ヶ月以内に100万円を最低達成ライン、設計上の伸長上限は300〜400万円帯

---

## システム統計（2026-04-01時点・実測値）

| 指標 | 値 |
|------|-----|
| Python | 48,370行 / 121ファイル |
| TypeScript | 6,765行 / 27ファイル |
| 総コード量 | 約55,135行 |
| PostgreSQL | 26テーブル / 26,812イベント |
| API エンドポイント | 70 |
| ノード数 | 4台（ALPHA/BRAVO/CHARLIE/DELTA）全healthy |
| GPU | 4基（M4 Pro / RTX 5070 / RTX 3080 / GTX 980Ti） |
| 月間コスト | 約¥747（API実費） |
| ローカル推論率 | 84% |
| persona_memory | 526件 |
| episodic_memory | 37件 |
| intel_items | 1,040件 |
| スケジューラジョブ | 40+件 |
| Harness Health Score | 85/100（Grade B） |

---

# 第1章 プロジェクト概要

## 1.1 SYUTAINβとは何か

SYUTAINβは、島原大知が設計し構築する**自律分散型事業OS**である。4台の物理PCがTailscale VPNで接続され、NATSメッセージングで協調し、18のコアエージェントと64のツールが連携して動く。

単なるAI自動化ツールではない。これは、一人の人間がAIと共に収益を生み出し、失敗を資産化し、進化し続ける過程の**ドキュメンタリー**でもある。島原の哲学——「設計なき実装は破綻する」「不可能性を認知してから、可能性を設計する」「肉体が止まった後も、自分の哲学を永続させたい」——がシステムの隅々に反映されている。

## 1.2 技術的ハイライト

- **4台分散構成**: Mac mini M4 Pro（司令塔）+ Ryzen/RTX 5070（実行者）+ Ryzen 9/RTX 3080（推論）+ Xeon/GTX 980Ti（監視）
- **5段階自律ループ**: 認識→思考→行動→検証→停止判断を自律的に回す
- **9層ループガード**: 暴走を構造的に防止する多層防御壁
- **84%ローカル推論**: Qwen3.5-9B/4Bによるコスト最小化
- **49件/日SNS自動投稿**: X島原4件+X SYUTAIN6件+Bluesky26件+Threads13件
- **note.com収益パイプライン**: 6段階品質管理+SSH Playwright自動公開
- **突然変異エンジン**: 物理ノイズと人間の直感を種とする不可逆蓄積型進化
- **並列Claude Code + Codex自律デバッグ**: 複数セッション同時実行による自律コード修正・レビュー（V29新規）

## 1.3 V29の位置づけ

V29はV25（原典設計書）→V26→V27→V28を経て到達した最新設計書である。V25はV20〜V24の全設計を再構成・統合した原典であり、過去設計は一切削除していない。V29は実稼働中のシステム状態を正として記述する。V28からの主要な追加は**第26章: Parallel Claude Code + Codex Autonomous Debugging Architecture**であり、複数のClaude CodeセッションとCodexセッションを並列実行してコードベース全体を自律的にデバッグ・レビュー・修復する能力をSYUTAINβに付与する。

---

# 第2章 設計原則

## 2.1 5つの設計原則

### 原則1: モデル独立性（Model Independence）
モデルは手段。適材適所で選定し、特定モデルに依存しない設計を維持する。choose_best_model_v6()でタスク適性×コスト×速度×可用性×VRAM制約の5軸で動的に選定する。

### 原則2: 自律性と安全性の両立
5つの自律性（自律実行・自律判断・自律調査・自律拡張・自律進化）を備えつつ、9層ループガードとEmergency Killで暴走を構造的に防止する。SNS投稿・商品公開・価格設定・暗号通貨取引は必ず人間承認を経る。

### 原則3: 失敗の資産化
全ての中間成果物をDBに保存し、途中停止しても資産化できる構造にする。失敗→原因→再発防止→設計思想→商品/note/Membershipの変換式を組み込む。

### 原則4: 分散と冗長性
4台のPCがPhase 1初日から全て稼働し、1台が落ちても残りで処理を継続できる。NATSメッセージング（JetStream永続化）で障害耐性を確保し、直接HTTPは障害時のフォールバックとする。

### 原則5: 観測可能性と透明性
Web UI（iPhone対応）でリアルタイムにシステム状態・タスク進捗・収益状況を確認できる。重要な判断はDiscord Webhook + Web UIで通知する。ただし突然変異エンジン（第24章）のパラメータのみ、設計上観測不能とする。

## 2.2 CLAUDE.md 26条（V29）

Claude Codeがこのプロジェクトで作業する際に必ず守るべき絶対ルール。

1. 設計書（SYUTAINβ_完全設計書_V29.md）の設計を最優先する
2. V25はV20〜V24を再構成した原典であり、過去設計を消してはならない
3. 各Stepを完了してから次に進む（段階的実装）
4. 同じ処理を3回以上繰り返す場合は停止してエスカレーションを発動する
5. LLM呼び出し前に必ずchoose_best_model_v6()でモデルを選択する
6. 2段階精錬（ローカル→API）を標準パイプラインとして使用する
7. 全ツール呼び出しはtry-exceptで囲みlog_usage()でエラーを記録する
8. .envの内容をログに出力しない。APIキーをコードにハードコードしない
9. 設定値はハードコードせずDBまたは.envから読み込む
10. 戦略ファイル（strategy/）を参照してからコンテンツを生成する
11. SNS投稿・商品公開・価格設定・暗号通貨取引はApprovalManagerを通じて承認を得てから実行する
12. 重要な判断はDiscord Webhook + Web UIで通知する
13. ローカルLLM配置を正確に守る: ALPHA=Qwen3.5-9B(MLX、オンデマンド起動), BRAVO=Qwen3.5-9B, CHARLIE=Qwen3.5-9B, DELTA=Qwen3.5-4B。ALPHAの推論はBRAVO/CHARLIEが両方ビジー時のみロードする
14. macOS (ALPHA) では declare -A を使わない (bash 3.2 非対応)
15. タスクをPostgreSQLに記録してからLoopGuard 9層で監視する
16. ループ防止のEmergency Kill条件（50ステップ/日次予算90%/同一エラー5回/2時間超過/セマンティックループ/Cross-Goal干渉）を厳守する
17. ノードが使えない場合は必ずフォールバックを実装する
18. 全ての中間成果物をDBに保存し、途中停止しても資産化できるようにする
19. NATSメッセージングでノード間通信し、直接HTTPは障害時のフォールバックとする
20. MCPサーバー接続は動的に確認し、接続不可時は代替手段で処理を継続する
21. 4台のPC（ALPHA/BRAVO/CHARLIE/DELTA）をPhase 1から全て稼働させる。BRAVOをPhase 2に先送りしない
22. 突然変異エンジン（第24章）は設計書の仕様に厳密に従い実装する。変異の発生をログに記録しない。変異パラメータをUIに表示しない。Capability Auditに含めない。9層ループ防止壁・承認フロー・Emergency Killのコードには一切干渉させない。変異エンジン自体のバグで全体が止まらないようtry-exceptで完全に隔離する
23. Brain-αはpersona_memoryの価値観を参照してから判断・生成を行うこと
24. 新しい判断基準はdaichi_dialogue_logに記録すること
25. セッション終了時にmemory_manager.save_session_memory()を必ず実行すること
26. 島原大知のtabooカテゴリ（persona_memory category='taboo'）は絶対に違反しないこと

---

# 第3章 インフラストラクチャ

## 3.1 4ノード構成

### ALPHA（Mac mini M4 Pro 16GB RAM）— 司令塔

| 項目 | 内容 |
|------|------|
| IP | 100.70.34.67（Tailscale） / ローカル |
| OS | macOS / launchd |
| GPU | Apple M4 Pro（統合メモリ） |
| ローカルLLM | Qwen3.5-9B（MLX、オンデマンド起動、28-35 tok/s） |
| 常駐エージェント | OS_Kernel, ApprovalManager, ProposalEngine, WebUIServer, ChatAgent |
| サービス | PostgreSQL, NATS Server(JetStream), FastAPI(:8000), Next.js(:3000), Caddy(:8443) |
| メモリ管理 | 16GB制約。常駐約3.5GB。MLX推論(6.6GB)はオンデマンド |
| 特記 | 司令塔業務最優先。推論はBRAVO/CHARLIEに委譲が標準動作 |

### BRAVO（Ryzen + RTX 5070 12GB）— 実行者

| 項目 | 内容 |
|------|------|
| IP | 100.75.146.9 / ssh shimahara@100.75.146.9 |
| OS | Ubuntu 24.04 / systemd |
| GPU | RTX 5070 12GB VRAM |
| ローカルLLM | Qwen3.5-9B(Ollama常駐) + nemotron-jp + nemotron-mini |
| 常駐エージェント | ComputerUseAgent, ContentWorker, BrowserAgent |
| ブラウザ | 4層構成: LightPanda(:9222)→Stagehand→Chromium(:9223)→ComputerUse(gpt-5.4) |
| 特記 | 推論優先ノード。ブラウザ自動操作の中核 |

### CHARLIE（Ryzen 9 + RTX 3080 10GB）— 推論エンジン

| 項目 | 内容 |
|------|------|
| IP | 100.70.161.106 / ssh shimahara@100.70.161.106 |
| OS | Ubuntu 24.04（Win11デュアルブート） / systemd |
| GPU | RTX 3080 10GB VRAM |
| ローカルLLM | Qwen3.5-9B(Ollama常駐) + nemotron-jp |
| 常駐エージェント | InferenceWorker, BatchProcessor |
| 特記 | Win11ブート時はオフライン。BRAVO+DELTAでフォールバック |

### DELTA（Xeon E5 + GTX 980Ti 6GB + 48GB RAM）— 監視・補助

| 項目 | 内容 |
|------|------|
| IP | 100.82.81.105 / ssh shimahara@100.82.81.105 |
| OS | Ubuntu 24.04 / systemd |
| GPU | GTX 980Ti 6GB VRAM |
| ローカルLLM | Qwen3.5-4B(Ollama、GPU-first、CPU fallback via llama-cpp) |
| 常駐エージェント | MonitorAgent, InfoCollector, HealthChecker |
| 突然変異エンジン | DELTA専用（暗号化SQLCipher DB） |
| ストレージ | HDD 13台（Samba共有） |
| 特記 | 48GB RAMでCPU推論バックアップも可能（3-5 tok/s） |

## 3.2 ネットワークアーキテクチャ

```
┌────────────────────── TAILSCALE MESH VPN ──────────────────────┐
│                                                                  │
│  ALPHA (macOS)           BRAVO (Ubuntu)                          │
│  ┌──────────────┐       ┌──────────────┐                        │
│  │ NATS Server  │◄─────►│ NATS Server  │                        │
│  │ +JetStream   │       │ +JetStream   │                        │
│  │ PostgreSQL   │       │ Ollama       │                        │
│  │ FastAPI:8000 │       │ Qwen3.5-9B   │                        │
│  │ Next.js:3000 │       │ LightPanda   │                        │
│  │ Caddy:8443   │       │ Stagehand v3 │                        │
│  │ OS_Kernel    │       │ Playwright   │                        │
│  │ launchd      │       │ systemd      │                        │
│  └──────────────┘       └──────────────┘                        │
│                                                                  │
│  CHARLIE (Ubuntu/Win11)  DELTA (Ubuntu)                          │
│  ┌──────────────┐       ┌──────────────┐                        │
│  │ NATS Server  │◄─────►│ NATS Server  │                        │
│  │ +JetStream   │       │ +JetStream   │                        │
│  │ Ollama       │       │ Ollama       │                        │
│  │ Qwen3.5-9B   │       │ Qwen3.5-4B   │                        │
│  │ InferWorker  │       │ Monitor      │                        │
│  │ systemd      │       │ InfoCollect  │                        │
│  └──────────────┘       │ MutationEng  │                        │
│                          │ HDD×13 Samba │                        │
│                          └──────────────┘                        │
│                                                                  │
│  iPhone (Tailscale iOS)                                          │
│  ┌──────────────┐                                                │
│  │ Safari PWA   │                                                │
│  │ → ALPHA:8443 │                                                │
│  │ SSE Stream   │                                                │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

## 3.3 サービス構成

| サービス | ノード | ポート | 用途 |
|----------|--------|--------|------|
| FastAPI | ALPHA | 8000 | REST API + SSE + WebSocket |
| Next.js 16 | ALPHA | 3000 | Web UI（React 19 + Tailwind + shadcn/ui） |
| Caddy | ALPHA | 8443 | HTTPS リバースプロキシ（TLS自動取得） |
| PostgreSQL 16 | ALPHA | 5432 | 共有状態DB（26テーブル） |
| NATS Server | 全4台 | 4222/6222 | メッセージング + JetStream永続化（4ノードRAFTクラスタ） |
| Ollama | BRAVO/CHARLIE/DELTA | 11434 | ローカルLLM推論サーバー |
| LightPanda | BRAVO | 9222 | AI特化ヘッドレスブラウザ |
| Chromium | BRAVO | 9223 | Playwright Chromium（フォールバック） |

## 3.4 NATS JetStream ストリーム設計

| ストリーム | サブジェクト | Retention | 用途 |
|-----------|------------|-----------|------|
| TASKS | `task.>` | workqueue | タスクディスパッチ・ステータス・結果 |
| AGENTS | `agent.>` | 1日 | エージェント間メッセージ・ハートビート |
| PROPOSALS | `proposal.>`, `approval.>` | 30日 | 提案・承認フロー |
| MONITOR | `monitor.>`, `log.>` | 3日 | ヘルス・メトリクス・アラート |
| BROWSER | `browser.>`, `computer.>` | 7日 | ブラウザ自動操作コマンド |
| INTEL | `intel.>` | 30日 | 情報収集パイプライン |

メッセージサブジェクト: `task.create`, `task.assign.{node}`, `task.status.{task_id}`, `task.complete.{task_id}`, `agent.heartbeat.{node}`, `agent.capability.{node}`, `agent.request.llm`, `agent.response.llm.{request_id}`, `browser.action.{node}`, `browser.result.{node}.{action_id}`, `browser.fallback.{node}`, `computer.use.{node}`, `proposal.new`, `proposal.feedback.{proposal_id}`, `approval.request`, `approval.response.{request_id}`, `monitor.alert.{severity}`, `monitor.metrics.{node}`, `log.event.{level}`, `intel.news`, `intel.market`, `intel.trend`, `intel.model_update`

## 3.5 ストレージ

- **PostgreSQL（ALPHA）**: 共有状態DB。タスクキュー、会話履歴、提案履歴、収益記録、ベクトルストア（pgvector 0.8.2）
- **SQLite（各ノード）**: ノードローカルキャッシュ、エージェントメモリ、LLM呼び出しログ、ローカルメトリクス
- **SQLCipher（DELTA）**: 突然変異エンジン専用暗号化DB（mutation_engine.enc.db）
- **HDD 13台（DELTA）**: Samba共有ストレージ。バックアップ・大容量データ保存
- **バックアップ**: PostgreSQL毎日03:00 + SQLite rsync毎日03:30

---

# 第4章 5段階自律ループ

## 4.1 ループ全体構造

```
┌─────────────────────────────────────────┐
│        SYUTAINβ 自律実行ループ V29        │
│                                          │
│  ① 認識（Perceive）                      │
│    └→ 目標を受ける / 環境を確認する         │
│    └→ 全4ノード状態確認                    │
│    └→ MCPツール発見 / API状態確認          │
│    └→ ブラウザ4層可用性確認                │
│                                          │
│  ② 思考（Think）                          │
│    └→ 計画を立てる / 代替案を用意する        │
│    └→ コスト見積り / 知能指数閾値判定        │
│    └→ Computer Use必要性判定              │
│                                          │
│  ③ 行動（Act）                            │
│    └→ ツールを使う / 成果物を作る           │
│    └→ NATSで適切なノードへディスパッチ       │
│    └→ ブラウザ操作/PC操作                  │
│                                          │
│  ④ 検証（Verify）                         │
│    └→ 結果を評価する / 目標に近づいたか      │
│    └→ 品質スコアリング / 収益貢献度評価      │
│                                          │
│  ⑤ 停止判断（StopOrContinue）             │
│    └→ 続行 / 経路変更 / 人間エスカレ / 停止  │
│    └→ 9層ループガードチェック               │
│                                          │
│  ───→ ①に戻る（ループガード付き）          │
└─────────────────────────────────────────┘
```

## 4.2 各段階の詳細

### ① 認識（Perceive）— Perceiver

10項目チェックリスト:
1. capability_audit — CapabilityAudit.run_full_audit()最新スナップショット
2. bravo_status — BRAVOノードのオンライン状態（推論優先ノード）
3. mcp_status — MCPサーバー接続状態（Tavily/Jina/GitHub/Gmail/Bluesky）
4. budget_status — BudgetGuard.get_budget_status()（日次消費率）
5. approval_boundaries — GoalPacket.approval_boundary（承認必要行為の定義）
6. strategy_files — strategy/CHANNEL_STRATEGY.md + CONTENT_STRATEGY.md + ICP_DEFINITION.md
7. previous_attempts — 同ゴールの過去実行履歴（PostgreSQL goal_packets）
8. market_context — InfoCollector最新情報（intel_items）
9. api_availability — OpenAI/Anthropic/DeepSeek/Google APIキー確認
10. browser_capability — Lightpanda/Stagehand/Playwright利用可否

### ② 思考（Think）— Planner

主プラン + 代替プラン3本を生成:
- **primary_plan**: ステップ列、コスト見積、ツール選定、ノード割当、ブラウザ操作計画
- **fallback_plan_1**: 主プランのステップ失敗時→エラー分析→別モデル/別ノードで再試行
- **fallback_plan_2**: API全停止時→ローカルLLMのみ運転継続
- **fallback_plan_3**: BRAVO停止時→ブラウザ操作保留、推論はCHARLIE/ALPHAに振替

### ③ 行動（Act）— Executor

タスクタイプ別ディスパッチ:
- `llm` → _execute_llm_task() → call_llm()
- `browser` → _execute_browser_task() → BrowserAgent.execute()
- `computer_use` → _execute_computer_use_task() → ComputerUseAgent
- `data_extraction` → _execute_data_extraction() → InfoPipeline
- `batch` → _execute_batch_task() → two_stage_refine()
- `approval` → _execute_approval_request() → ApprovalManager

### ④ 検証（Verify）— Verifier

5軸品質スコアリング（0.0〜1.0）:
- 0.7以上: OK
- 0.5〜0.7: 再試行推奨
- 0.5未満: 必ず再試行
- ゴール完了判定: タスク80%以上完了 AND 平均品質0.5以上

### ⑤ 停止判断（StopOrContinue）— StopDecider

8つの判断タイプ:
- COMPLETE — 全タスク完了→ループ終了
- CONTINUE — 次タスクへ継続
- RETRY_MODIFIED — 修正して再試行
- SWITCH_PLAN — 計画変更（replan）
- ESCALATE — 人間へエスカレーション
- EMERGENCY_STOP — 緊急停止
- SEMANTIC_STOP — 意味的ループ停止
- INTERFERENCE_STOP — クロスゴール干渉停止

## 4.3 9層LoopGuard

### Layer 1: Retry Budget
同一アクション再試行は**2回まで**。3回目で別方式へ強制切替。

### Layer 2: Same-Failure Cluster
同じ原因クラスタで**2回**失敗→そのクラスタを**30分凍結**。

### Layer 3: Planner Reset Limit
再計画は**最大3回**。改善なければ停止 or エスカレーション。

### Layer 4: Value Guard
売上・学習・証拠・前進のいずれにも寄与しない再試行は**禁止**。

### Layer 5: Approval Deadlock Guard
承認待ち24時間超→リマインド1回→代替の前進タスクへ移行。

### Layer 6: Cost & Time Guard
日次予算80%超 or 1タスク60分超 or 1回10万トークン超→自動停止。

### Layer 7: Emergency Kill
最終防衛線。以下のいずれかで**即座に全停止**:

```yaml
emergency_kill_conditions:
  - total_step_count >= 100          # .envのEMERGENCY_KILL_MAX_STEPS
  - total_cost_jpy >= daily_budget * 0.9
  - same_error_count >= 5
  - time_elapsed_minutes >= 120
  - infinite_loop_score >= 3         # 状態ハッシュ重複3回
```

### Layer 8: Semantic Loop Detection
直近3アクションの目的・手法・結果をQwen3.5-4B（DELTA）で比較。類似度0.85以上で**SEMANTIC_STOP**。コスト¥0（ローカルLLM）。

### Layer 9: Cross-Goal Interference Detection
複数Goal Packet同時進行時の干渉検知:
- 同一APIへの同時大量リクエスト（rate limit競合）
- 同一ノードのGPU/CPU 90%超（リソース競合）
- 矛盾するアクション（例: 同一アカウントで異なるトーンの投稿準備）
- 1ゴールが日次予算60%以上を消費（予算独占）

優先度解決: `revenue_contribution > deadline_proximity > creation_order`

### 9層の連結フロー

```
目標受信 → Goal Packet生成 → Capability Audit
    ↓
Task Graph生成（主プラン + 代替プラン）
    ↓
実行ループ開始
    ↓
┌─ [Layer 9] Cross-Goal干渉? ──→ INTERFERENCE_STOP
├─ [Layer 8] セマンティックループ? ──→ SEMANTIC_STOP
├─ [Layer 7] Emergency Kill条件? ──→ EMERGENCY_KILL
├─ [Layer 6] cost/time超過? ──→ AUTO_STOP + レポート
├─ [Layer 5] 承認デッドロック? ──→ 別タスクへ移行
├─ [Layer 4] 価値あるか? ──→ 価値なし → SKIP
├─ [Layer 3] 再計画3回目? ──→ ESCALATE
├─ [Layer 2] 同型失敗2回? ──→ クラスタ凍結 + 別手段
├─ [Layer 1] 再試行2回? ──→ 別方式切替
└─ ツール実行（NATSで適切なノードへディスパッチ）
      ↓
   成功 → 検証 → 次ステップ
   失敗 → エラー分類 → Layer 1-9で判定
      ↓
   目標達成判定
      達成 → 完了 → Discord + Web UI通知
      未達成 → ループ継続（ガード付き）
```

---

# 第5章 Harness Engineering

## 5.1 failure_memory (tools/failure_memory.py)
過去の失敗パターンを記録し、同じ失敗を繰り返さない。エラークラス（auth/model/timeout/budget/logic/external/network/browser）ごとに失敗履歴をPostgreSQLに蓄積。再試行前に過去失敗との照合を行い、同一パターンなら即座に代替手段へ切替。

## 5.2 harness_linter (tools/harness_linter.py)
提案・ゴール・タスクの品質を事前検証するリンター。CLAUDE.md 26条との整合性チェック、承認フロー漏れの検出、予算超過リスクの事前警告を実行。全ての提案はharness_linterゲートを通過してから実行される。

## 5.3 Sprint Contract
週次スプリントの成果物・期限・担当ノードを明文化する契約。ProposalEngineが週次提案生成時にSprint Contractを同時生成し、進捗をスケジューラが追跡する。

## 5.4 progress_log
ゴール進捗を時系列で記録するログ。各ステップの実行結果、品質スコア、コスト、所要時間を自動記録。Web UIのタスク画面でリアルタイム表示。

## 5.5 AGENTS.md
システム能力マップ。4ノードの構成・エージェント配置・タスクルーティングルール・既知の障害パターン・ツール可用性・予算制約を一元記載。OS Kernelが認識フェーズで自動参照する。最終更新: 2026-03-28。

## 5.6 doc_gardener (tools/doc_gardener.py)
ドキュメントの鮮度と整合性を自動管理するガーデナー。週次実行（日曜04:00）で古くなったドキュメントを検出し、更新提案を生成する。AGENTS.md、SYSTEM_STATE.md、CODE_MAP.md等の自動更新を担当。

## 5.7 skill_manager (tools/skill_manager.py)
エージェントが獲得したスキル（成功パターン）を形式知化して蓄積。毎日04:00にスキル抽出ジョブが実行され、成功タスクから再利用可能なパターンを抽出してDBに保存する。

---

# 第6章 エージェント一覧

## 6.1 コアエージェント（18エージェント）

| # | エージェント | クラス | ノード | 行数 | 役割 |
|---|------------|--------|--------|------|------|
| 1 | OS_Kernel | OSKernel | ALPHA | 723 | 司令塔。Goal Packet→Task Graph→ディスパッチ |
| 2 | Perceiver | Perceiver | ALPHA | 263 | 認識エンジン。環境状態・目標を構造化 |
| 3 | Planner | Planner | ALPHA | 389 | 思考・計画。主プラン+代替プラン生成 |
| 4 | Executor | Executor | ALPHA→分配 | 500 | 行動エンジン。タスクを適切なノードへ分配 |
| 5 | Verifier | Verifier | ALPHA | 518 | 検証。品質スコアリング・目標達成度評価 |
| 6 | StopDecider | StopDecider | ALPHA | 247 | 停止判断。8タイプの判断 |
| 7 | ProposalEngine | ProposalEngine | ALPHA | 869 | 3層提案（提案+反論+代替案） |
| 8 | ApprovalManager | ApprovalManager | ALPHA | 693 | 承認管理。3層承認フロー |
| 9 | ChatAgent | ChatAgent | ALPHA | 1099 | Web UIチャット。6カテゴリ意図分類 |
| 10 | CapabilityAudit | CapabilityAudit | ALPHA | 456 | 能力監査。全4台の状態監査 |
| 11 | NodeRouter | NodeRouter | ALPHA | 273 | ノードルーティング・タスク振分 |
| 12 | LearningManager | LearningManager | ALPHA | 423 | 学習管理。モデル品質・提案採用率追跡 |
| 13 | BrowserAgent | BrowserAgent | BRAVO | 505 | 4層ブラウザ自動操作の統括 |
| 14 | ComputerUseAgent | ComputerUseAgent | BRAVO | 308 | GPT-5.4 Computer Use操作 |
| 15 | InferenceWorker | — | CHARLIE | — | ローカルLLM推論ワーカー |
| 16 | MonitorAgent | MonitorAgent | DELTA | 304 | 全ノード監視・メトリクス収集 |
| 17 | InfoCollector | InfoCollector | DELTA | 271 | 情報収集パイプライン |
| 18 | MutationEngine | 純粋関数 | DELTA | 406 | 突然変異エンジン（第24章） |

## 6.2 Brain-αモジュール（15モジュール）

| # | モジュール | ファイル | 役割 |
|---|----------|---------|------|
| 1 | content_pipeline | brain_alpha/content_pipeline.py | 6段階コンテンツ生成パイプライン |
| 2 | sns_batch | brain_alpha/sns_batch.py | SNS投稿49件/日一括生成 |
| 3 | memory_manager | brain_alpha/memory_manager.py | セッションメモリ管理 |
| 4 | persona_bridge | brain_alpha/persona_bridge.py | ペルソナ記憶参照・注入 |
| 5 | note_quality_checker | brain_alpha/note_quality_checker.py | note記事2段階品質チェック |
| 6 | self_healer | brain_alpha/self_healer.py | 自律修復チェッカー |
| 7 | product_packager | brain_alpha/product_packager.py | 商品パッケージング |
| 8 | documentary_generator | brain_alpha/documentary_generator.py | ドキュメンタリー記事生成 |
| 9 | executive_briefing | brain_alpha/executive_briefing.py | 経営日報生成 |
| 10 | cross_evaluator | brain_alpha/cross_evaluator.py | Brain-α相互評価 |
| 11 | escalation | brain_alpha/escalation.py | エスカレーション管理 |
| 12 | safety_check | brain_alpha/safety_check.py | 安全性チェック |
| 13 | session_save | brain_alpha/session_save.py | セッション保存・復元 |
| 14 | startup_review | brain_alpha/startup_review.py | 起動時レビュー |
| 15 | auto_log | brain_alpha/auto_log.py | 運用ログ自動生成 |

## 6.3 Discord Botモジュール（6ボット）

| ボット | ノード | LLM | 役割 |
|--------|--------|-----|------|
| CORTEX | ALPHA | DeepSeek→qwen3.5:4b | CEO、ハートビート(10min)、パイプライン、fallback通知 |
| FANG | BRAVO | DeepSeek→qwen3.5:9b | CSO、KPIレポート(21:00)、fallback通知 |
| NERVE | BRAVO | DeepSeek→qwen3.5:9b | COO、ミーティング管理、fallback通知 |
| FORGE | CHARLIE | DeepSeek→qwen3.5:9b | CTO、コードレビュー、fallback通知 |
| MEDULLA | DELTA | DeepSeek→qwen3.5:4b | 副CEO、パトロール(30min)、CEO代理、fallback通知 |
| SCOUT | DELTA | DeepSeek→qwen3.5:4b | Intel、マルチソースリサーチ、fallback通知 |

---

# 第7章 ツール一覧（64ツール）

## 7.1 インフラストラクチャ（12ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| llm_router | tools/llm_router.py | 897 | 6プロバイダ統合LLMルーター + choose_best_model_v6 |
| budget_guard | tools/budget_guard.py | 300 | 予算管理（日次/月次/チャット別） |
| loop_guard | tools/loop_guard.py | 445 | 9層ループ防止壁 |
| emergency_kill | tools/emergency_kill.py | 235 | 緊急停止（5条件） |
| nats_client | tools/nats_client.py | 247 | NATS JetStreamクライアント |
| node_manager | tools/node_manager.py | 307 | ノード状態管理・ヘルスチェック |
| db_pool | tools/db_pool.py | — | PostgreSQL接続プール |
| db_init | tools/db_init.py | 368 | PostgreSQL + SQLite初期化DDL |
| storage_tools | tools/storage_tools.py | 303 | PgHelper + SqliteHelper + ArtifactStorage |
| event_logger | tools/event_logger.py | 140 | イベントログ記録 |
| model_registry | tools/model_registry.py | 122 | モデルメタデータ管理 |
| mcp_manager | tools/mcp_manager.py | 261 | MCP統合マネージャー |

## 7.2 情報収集（10ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| info_pipeline | tools/info_pipeline.py | 491 | 情報収集パイプライン（Tavily+Jina+RSS+YouTube） |
| tavily_client | tools/tavily_client.py | 174 | Tavily AI検索クライアント |
| jina_client | tools/jina_client.py | 145 | Jina Reader API（Web→Markdown） |
| intel_digest | tools/intel_digest.py | — | インテルダイジェスト生成 |
| intel_reviewer | tools/intel_reviewer.py | — | intel_items自動レビュー |
| keyword_generator | tools/keyword_generator.py | — | 動的キーワード生成 |
| competitive_analyzer | tools/competitive_analyzer.py | 189 | 競合分析（Booth/note） |
| trend_detector | tools/trend_detector.py | — | トレンド検出 |
| overseas_trend_detector | tools/overseas_trend_detector.py | — | 海外トレンド検出 |
| buzz_account_analyzer | tools/buzz_account_analyzer.py | — | バズアカウント分析 |

## 7.3 コンテンツ・SNS（8ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| content_tools | tools/content_tools.py | 238 | note/商品コンテンツ生成 |
| content_multiplier | tools/content_multiplier.py | 308 | コンテンツ展開・再利用 |
| social_tools | tools/social_tools.py | 594 | X/Bluesky/Threads SNS投稿 |
| two_stage_refiner | tools/two_stage_refiner.py | 231 | 2段階精錬パイプライン |
| platform_ng_check | tools/platform_ng_check.py | 98 | プラットフォームNG表現チェック |
| documentary_generator | tools/documentary_generator.py | — | ドキュメンタリー記事生成 |
| note_publisher | tools/note_publisher.py | — | note.com自動公開（BRAVO経由） |
| analytics_tools | tools/analytics_tools.py | 217 | 戦略ファイル読み込み・分析 |

## 7.4 安全性・ループ防止（5ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| semantic_loop_detector | tools/semantic_loop_detector.py | 214 | 意味的ループ検知 |
| cross_goal_detector | tools/cross_goal_detector.py | 326 | クロスゴール干渉検知 |
| discord_notify | tools/discord_notify.py | 58 | Discord Webhook通知 |
| harness_linter | tools/harness_linter.py | — | 提案・タスク品質リンター |
| harness_health | tools/harness_health.py | — | ハーネス健全性スコア算出 |

## 7.5 メモリ・学習（7ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| embedding_tools | tools/embedding_tools.py | 91 | Jina Embeddings v3（1024dim） |
| episodic_memory | tools/episodic_memory.py | — | エピソード記憶（MemRL） |
| failure_memory | tools/failure_memory.py | — | 失敗パターン記憶 |
| memory_consolidator | tools/memory_consolidator.py | — | メモリ統合（毎日03:45） |
| semantic_cache | tools/semantic_cache.py | — | セマンティックキャッシュ |
| skill_manager | tools/skill_manager.py | — | スキル抽出・形式知化 |
| edit_tracker | tools/edit_tracker.py | — | 編集追跡 |

## 7.6 ブラウザ・自動操作（5ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| lightpanda_tools | tools/lightpanda_tools.py | 224 | LightPanda CDP接続（Layer 1） |
| stagehand_tools | tools/stagehand_tools.py | 192 | Stagehand v3 AI駆動操作（Layer 2） |
| playwright_tools | tools/playwright_tools.py | 245 | Playwright Chromium（Layer 3） |
| computer_use_tools | tools/computer_use_tools.py | 296 | GPT-5.4 Computer Use（Layer 4） |
| browser_ops | tools/browser_ops.py | — | ブラウザ操作統合 |

## 7.7 コマース・収益（10ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| commerce_tools | tools/commerce_tools.py | 237 | Stripe/Booth統合 |
| crypto_tools | tools/crypto_tools.py | 297 | 暗号通貨取引（GMOコイン/bitbank） |
| affiliate_manager | tools/affiliate_manager.py | — | アフィリエイト管理 |
| affiliate_inserter | tools/affiliate_inserter.py | — | アフィリエイトリンク挿入 |
| payment_manager | tools/payment_manager.py | — | 支払い管理 |
| revenue_researcher | tools/revenue_researcher.py | — | 収益機会リサーチ |
| api_quota_monitor | tools/api_quota_monitor.py | — | APIクォータ監視 |
| engagement_analyzer | tools/engagement_analyzer.py | — | エンゲージメント分析 |
| a2a_protocol | tools/a2a_protocol.py | — | A2Aプロトコル（将来対応） |
| x402_protocol | tools/x402_protocol.py | — | x402プロトコル（将来対応） |

## 7.8 運用（7ツール）

| ツール | ファイル | 行数 | 機能 |
|--------|---------|------|------|
| auto_fix_engine | tools/auto_fix_engine.py | — | 自動修復エンジン |
| feature_test_runner | tools/feature_test_runner.py | — | フィーチャーテスト実行 |
| doc_gardener | tools/doc_gardener.py | — | ドキュメントガーデニング |
| mcp_server | tools/mcp_server.py | — | MCPサーバー実装 |
| agent_context | tools/agent_context.py | — | エージェントコンテキスト管理 |
| pw_extract | tools/pw_extract.py | 28 | Playwright抽出ユーティリティ |

---

# 第8章 LLMモデル選定

## 8.1 Tier構成

### Tier S（最高精度・高単価判断・Computer Use）

| モデル | Provider | Input/1M | Output/1M | 用途 |
|--------|----------|----------|-----------|------|
| GPT-5.4 | OpenAI | $2.50 | $15.00 | Computer Use(OSWorld 75.0%)/Tool Search/1Mコンテキスト |
| Claude Opus 4.6 | Anthropic | $5.00 | $25.00 | エージェント能力トップ。設計書生成 |
| Claude Sonnet 4.6 | Anthropic | $3.00 | $15.00 | 高品質・低コスト。戦略文書主力 |
| Gemini 3.1 Pro Preview | Google | $2.00 | $12.00 | 知能指数57。1Mコンテキスト |

### Tier A（高品質・中コスト・主力帯）

| モデル | Provider | Input/1M | Output/1M | 用途 |
|--------|----------|----------|-----------|------|
| DeepSeek-V3.2 | DeepSeek | $0.28 | $0.42 | フロンティア最安値。キャッシュで90%削減 |
| Gemini 2.5 Flash | Google | $0.15 | $0.60 | 思考モード付き。1Mコンテキスト |
| GPT-5 Mini | OpenAI | $0.25 | $2.00 | コスパ優秀。中品質生成 |
| Claude Haiku 4.5 | Anthropic | $1.00 | $5.00 | 軽量Claude。分類・タグ付け |

### Tier B（低コスト量産・バッチ処理）

| モデル | Provider | Input/1M | Output/1M | 用途 |
|--------|----------|----------|-----------|------|
| GPT-5 Nano | OpenAI | $0.05 | $0.40 | ルーティング・分類 |
| Gemini 2.5 Flash-Lite | Google | $0.075 | $0.30 | 超低コスト |
| Qwen3.5-Flash API | Alibaba | ~$0.10 | ~$0.40 | 100万トークンコンテキスト |

### Tier L（ローカル無料・継続運転）

| モデル | ノード | VRAM | 速度 | 特徴 |
|--------|--------|------|------|------|
| Qwen3.5-9B | ALPHA(MLX) | 6.6GB | 28-35 tok/s | オンデマンド起動 |
| Qwen3.5-9B | BRAVO(Ollama) | 6.5GB | 12-18 tok/s | 推論優先ノード |
| Qwen3.5-9B | CHARLIE(Ollama) | 6.5GB | 12-16 tok/s | バッチ処理主力 |
| Qwen3.5-4B | DELTA(Ollama) | 4.5-5.5GB | 8-12 tok/s | 軽量タスク専用 |

## 8.2 choose_best_model_v6

判定優先順位:
1. `needs_computer_use` → GPT-5.4強制
2. `needs_tool_search` → GPT-5.4優先
3. `intelligence_required >= 50` → Tier S
4. `final_publish + high/premium` → Tier S（タスク別振分）
5. `local_available + 対象task_type` → Tier L（BRAVO/CHARLIE優先、ALPHAオンデマンド）
6. コンテンツ系 → Tier A（DeepSeek-V3.2/GPT-5-mini）
7. バッチ系 → Tier B（Gemini 2.5 Flash-Lite）
8. デフォルト → DeepSeek-V3.2

## 8.3 フォールバックチェーン

```
local(BRAVO/CHARLIE Qwen3.5-9B) → local(DELTA Qwen3.5-4B) → local(ALPHA MLX) → DeepSeek API → OpenRouter
```

## 8.4 2段階精錬パイプライン

```
Stage 1: BRAVO(Qwen3.5-9B) + CHARLIE(Qwen3.5-9B) 同時並列ドラフト
    ↓
Stage 2: DELTA(Qwen3.5-4B)で品質スコア算出
    ↓
  score >= 0.7 → そのまま使用（コスト¥0）
  score < 0.7 → DeepSeek-V3.2 or Claude Sonnetで仕上げ
```

## 8.5 コスト実績

| 指標 | 値 |
|------|-----|
| 月間API実費 | 約¥747 |
| ローカル率 | 84% |
| 日次予算 | ¥80（.env DAILY_BUDGET_JPY） |
| 月次予算 | ¥1,500（MONTHLY_BUDGET_JPY） |
| 情報収集予算 | ¥15,000/月（MONTHLY_INFO_BUDGET_JPY） |

---

# 第9章 SNSパイプライン

## 9.1 49件/日スケジュール

| プラットフォーム | アカウント | 件数/日 | 時間帯 |
|-----------------|----------|---------|--------|
| X | 島原大知 | 4 | 10:00, 13:00, 17:00, 20:00 |
| X | SYUTAINβ | 6 | 11:00, 13:30, 15:00, 17:30, 19:00, 21:00 |
| Bluesky | SYUTAINβ | 26 | 10:00〜22:30（毎時00分・30分） |
| Threads | SYUTAINβ | 13 | 10:30〜22:30（毎時30分） |

夜間バッチ（22:00〜23:30）で翌日分を一括生成し、posting_queueに直接INSERT。posting_queue自動投稿ジョブ（毎分）が時刻に応じて投稿実行。

## 9.2 品質管理

### Best-of-N生成
各投稿につき複数候補を生成し、品質スコア最高のものを選択。

### 温度バリエーション
時間帯別テーマ重み付け:
- morning: ビジネス(3), AI技術(2), 開発進捗(2)
- afternoon: 日常(2), 雑談(2), カメラ/写真(1)
- evening: AI技術(2), 映画/映像(2), 開発進捗(2)
- night: 哲学/思考(3), 自己内省(2), VTuber業界(2)

### プラットフォーム別品質閾値
- X: 0.68（ブランド直結、高品質要求）
- Bluesky: 0.62（短文のためスコア構造的に低い）
- Threads: 0.64（カジュアル寄り）

### テーマ品質フィードバック
バッチ実行中にテーマ×プラットフォームの品質を追跡。低品質テーマを自動回避。

### AI定型表現チェック
AI臭い表現（「革新的な」「シナジー」「パラダイム」等）を検出・除去。島原の文体（SOUL.mdベース）に寄せる。

### エンゲージメント分析（毎日06:30）
各プラットフォームのエンゲージメントを12時間間隔で取得。分析結果をテーマ選択・投稿時間帯の最適化にフィードバック。

### バズ分析（毎週月曜07:30）
バズったアカウント・投稿のパターンを分析し、コンテンツ戦略に反映。

---

# 第10章 note.com収益パイプライン

## 10.1 フルフロー

```
Stage 1: ネタ選定
  intel_items + persona_memory → テーマ選定
  ジャンル検出（detect_genre）
    ↓
Stage 2: 構成案
  テーマ → ジャンルテンプレート適用 → Phase A-E骨組み生成
  3軸タイトル生成（好奇心 × 具体性 × 共感）
    ↓
Stage 3: 初稿
  構成案 → 本文生成
  ★実データ注入: DB実績値、コスト実績、エラー事例を埋め込み
    ↓
Stage 4: リライト
  初稿 → 島原の声で書き直し
  daichi_content_patterns.md参照
  persona_memoryの価値観反映
    ↓
Stage 4.5: セルフ批評＆改善
  別モデルで弱点を特定し改善
  構造的欠陥、論理飛躍、AI臭さの除去
    ↓
Stage 5: 品質検証（2段階）
  Stage 5a: claude-haiku-4-5 — 事実確認・一貫性・品質5軸
  Stage 5b: gpt-5.4 — 高次評価・価格推奨・公開判定
  コスト上限: ¥6/記事, ¥30/回, ¥60/日, ¥500/月
    ↓
Stage 6: 承認キュー
  ApprovalManager経由で島原の承認待ち
    ↓
Stage 7: 自動公開
  承認済み→NATS経由→BRAVOのBrowserAgent→note.comにSSH Playwright公開
  タイトル/本文/価格/タグを入力→公開ボタン押下→結果取得→DB更新→Discord通知
```

## 10.2 ジャンルテンプレート
strategy/note_genre_templates.pyでジャンル別テンプレートを管理: AI活用/技術解説、失敗談/事後分析、設計思想/哲学、収益レポート/運用ログ、ドキュメンタリー。

## 10.3 3軸タイトル生成
好奇心（Curiosity）×具体性（Specificity）×共感（Empathy）の3軸でタイトルを最適化。

## 10.4 機械的チェック
- タイトル100文字以内
- プロンプト指示の漏洩除去（「以下」「してください」「生成」等のパターン検出）
- Markdown見出し記号除去
- AI定型表現除去

## 10.5 実データ注入
content_pipelineがDB実績値を自動埋め込み: ローカル推論率84%、月間コスト¥747、稼働ノード数4台、タスク成功数、event_logから実際のエラー事例を引用。

---

# 第11章 情報収集

## 11.1 6つのソース

| ソース | 方式 | 頻度 | コスト |
|--------|------|------|--------|
| Gmail/Google Alerts | Gmail API（80+キーワード） | リアルタイムPub/Sub | ¥0 |
| Tavily Search | AI特化検索API | 6時間間隔 | ¥15,000/月 |
| Jina Reader | Web→Markdown変換 | オンデマンド | ~¥450/月 |
| RSS/Atom | feedparser/fastfeedparser | 監視ループ | ¥0 |
| YouTube Data API | チャンネル・動画監視 | 10,000ユニット/日 | ¥0 |
| 競合分析 | Booth/note分析 | 週次（日曜03:00） | ローカルLLM |

## 11.2 トレンド検出
- trend_detector: 国内トレンド検出
- overseas_trend_detector: 海外トレンド検出（毎日08:00）
- buzz_account_analyzer: バズアカウント分析（毎週月曜07:30）

## 11.3 重要度スコアリング
intel_itemsにimportance_score（0.0〜1.0）を付与。Qwen3.5-4B（DELTA）で分類・スコアリング。高重要度のみDeepSeek-V3.2で精度向上。9カテゴリ分類。

## 11.4 実績
- 収集アイテム: 1,040件
- intel_items自動レビュー: 6時間間隔
- intel_digest: 毎日07:00に前日ダイジェスト生成

---

# 第12章 承認フロー

## 12.1 3層承認システム

### Tier 1 — 人間承認必須
SNS投稿（X, Bluesky, Threads）、価格設定（Stripe/Booth商品）、暗号通貨取引。タイムアウト: 24時間→ESCALATE。

### Tier 2 — 自動実行 + Discord通知
下書き公開（Noteドラフト）、外部情報収集、レポート生成。タイムアウト: なし（即時実行）。

### Tier 3 — 完全自動（通知なし）
ローカルファイル操作、DB読み取り、分析・要約、ログ整理。

## 12.2 harness_linterゲート
全提案はharness_linterを通過してから承認キューに入る。CLAUDE.md 26条との整合性、予算超過リスクの事前検証。

## 12.3 plan modeレビュー
重要ゴール（priority: high以上）は実行前にPlannerのTaskGraphを島原に提示し修正指示を受付。

## 12.4 Web UI（モバイル最適化）
承認待ちキューは/proposalsと/pending-approvalsで表示。iOS対応: タッチエリア最小44px、仮想キーボード対応。Discord Webhookでプッシュ通知フォールバック。

---

# 第13章 予算管理

## 13.1 予算限度

| 区分 | 限度額 | 設定元 |
|------|--------|--------|
| 日次API予算 | ¥80 | DAILY_BUDGET_JPY |
| 月次API予算 | ¥1,500 | MONTHLY_BUDGET_JPY |
| 月次情報収集予算 | ¥15,000 | MONTHLY_INFO_BUDGET_JPY |
| 単回呼び出し上限 | ¥500 | ハードコード |
| チャット専用予算 | ¥100 | CHAT_BUDGET_JPY |

## 13.2 アラート・Kill閾値
- 80%到達 → Discord警告 + ローカルLLM優先に切替
- 90%到達 → Discord緊急通知 + 全APIをローカル代替 → EmergencyKill条件成立

## 13.3 APIクォータ監視
api_quota_monitorが各APIのrate limit残量を追跡。障害時はCapability Auditで検知→代替経路へ切替。

## 13.4 セマンティックキャッシュ
同一・類似LLMリクエストをキャッシュ。毎日04:15に清掃。DeepSeek-V3.2のキャッシュヒット時$0.028/1Mで90%コスト削減。

---

# 第14章 監視・復旧

## 14.1 監視ジョブ

| ジョブ | 間隔 | 内容 |
|--------|------|------|
| ハートビート | 30秒 | 全ノードNATS heartbeat |
| ノードヘルスチェック | 5分 | SSH + HTTP ping + Ollama確認 |
| 自律修復(self_healer) | 5分 | エラー検出→自動修復 |
| 異常検知 | 5分 | event_log異常パターン検出 |
| Capability Audit | 1時間 | 全4台完全能力監査 |
| メモリ統合 | 毎日03:45 | persona+episodic統合 |

## 14.2 自律修復（self_healer）
5分間隔: ダウンノード検出→再起動指示、孤立タスク再ディスパッチ、API接続エラー→代替プロバイダ、ディスク容量不足→ログクリーンアップ。

## 14.3 復旧手順

| 障害 | 復旧 |
|------|------|
| CORTEX停止 | LaunchAgent KeepAlive自動再起動 |
| リモートノード停止 | systemctl restart |
| CHARLIE Win11ブート | BRAVO+DELTAフォールバック |
| API全停止 | ローカルLLMのみ運転 |
| PostgreSQL障害 | 03:00バックアップ復元 |
| NATSクラスタ障害 | 残存ノードRAFT維持→直接HTTP |

---

# 第15章 Brain-αペルソナ

## 15.1 persona_memory
PostgreSQL persona_memoryテーブル（526件）。priority_tier 1-4で管理。

| Tier | 用途 | 例 |
|------|------|-----|
| 1 | 絶対遵守 | taboo、identity |
| 2 | 価値観 | philosophy（「完璧より行動」） |
| 3 | 判断基準 | preference（コンテンツ方針） |
| 4 | 参考情報 | knowledge（業界知識） |

## 15.2 Constitution原則（SOUL.mdから継承）
- 一人称「自分」、島原は「大知さん」
- 冷静・分析的・正直・自然体
- 「！」不使用、哲学はトーンに反映
- ハルシネーション厳禁、知らなければ「わからないです」

## 15.3 taboo enforcement
category='taboo'は絶対違反禁止（CLAUDE.md 26条）。safety_check.pyで全出力をチェック。

## 15.4 コンテキスト注入
ChatAgent応答時にpersona_bridge経由で注入: casual（tier 1のみ）、standard（tier 1-2）、strategic（tier 1-3+embedding検索）。

## 15.5 デジタルツイン
水曜・土曜20:00に問いかけジョブ実行。persona_memoryに基づく価値観再確認対話。

---

# 第16章 収益チャネル

## 16.1 稼働中
- **note.com**: 6段階品質管理パイプライン + SSH Playwright自動公開。54件成果物。

## 16.2 設定待ち
- **アフィリエイト**: affiliate_manager + affiliate_inserter。実体験レビュー記事。

## 16.3 アカウント済み
Gumroad、Substack、KDP（Amazon）。

## 16.4 MCPサーバー（5ツール）
syutain-tools: DB操作、収益記録、提案生成、タスク管理、情報検索。

## 16.5 A2A + x402
将来対応。A2A（Agent-to-Agent）、x402（HTTPマイクロペイメント）。

## 16.6 ドキュメンタリー記事
毎週水曜10:00にdocumentary_generatorが構築過程ドキュメンタリーを自動生成。

## 16.7 その他
Booth/Stripe直販、BtoB相談（¥30K〜¥300K）、暗号通貨（価格蓄積中）、Micro-SaaS。

---

# 第17章 自律改善

## 17.1 Karpathy Loop（毎日05:00）
前日タスク集約→成功/失敗パターン分析→改善提案→安全範囲で自動適用。

## 17.2 MemRL
episodic_memory（37件） + Q-value。成功で上昇、失敗で停滞（下がらない）。学習対象: モデル選定精度、提案採用率、品質、ブラウザ層別成功率。

## 17.3 エンゲージメント→SNSループ
エンゲージメント取得(12h)→分析(06:30)→テーマ重み更新→SNS生成反映。

## 17.4 海外トレンド検出（毎日08:00）
英語圏AI/テック動向監視。国内未到達トレンド先行検出。

## 17.5 Harness Health Score（毎時）

| 指標 | 現在値 |
|------|--------|
| node_availability | 100/100 |
| task_success_rate | 100/100 |
| sns_delivery_rate | 80/100 |
| budget_utilization | 100/100 |
| error_rate | 98/100 |
| quality_average | 14/100 |
| memory_health | 70/100 |
| **総合** | **85/100 (Grade B)** |

---

# 第18章 Web UI

## 18.1 技術スタック
FastAPI(SSE+WebSocket+JWT) + Next.js 16(React 19+Tailwind+shadcn/ui) + Caddy(HTTPS) + Tailscale iOS。

## 18.2 ページ構成

| ページ | パス | 更新間隔 | 機能 |
|--------|------|---------|------|
| ダッシュボード | / | 10秒 | KPI、ノード状態、提案、クイックゴール |
| チャット | /chat | WS/SSE | 双方向メッセージ、承認、ストリーミング |
| タスク | /tasks | 5秒 | ステータスフィルタ、詳細モーダル |
| 提案 | /proposals | 手動 | 3層アコーディオン、7軸スコア |
| エージェント操作 | /agent-ops | 10秒 | メトリクス、CHARLIEシャットダウン |
| 収益 | /revenue | 手動 | サマリー、¥1M目標進捗 |
| モデル | /models | 手動 | 予算進捗、ローカル/API比率 |
| 情報収集 | /intel | 手動 | ソースフィルタ、重要度バッジ |
| 設定 | /settings | 手動 | 予算、モデル選択、Discord |
| タイムライン | /timeline | 手動 | イベント時系列 |
| 並列デバッグ | /parallel-debug | 5秒 | 並列セッション監視（V29新規） |

## 18.3 コンポーネント（8）
AuthGate、ChatInterface、ProposalCard、MobileTabBar、NodeStatusPanel、ErrorBoundary、ClientErrorBoundary。

## 18.4 モバイル最適化
viewport meta、タッチエリア44px、iOS仮想キーボード対応、PWA対応。

---

# 第19章 スケジューラ

APScheduler（AsyncIOScheduler, timezone="Asia/Tokyo"）。40+ジョブ。

## 19.1 高頻度（秒〜分）
ハートビート(30秒)、posting_queue(毎分)、孤立タスク再ディスパッチ(5分)、自律修復(5分)、ノードヘルス(5分)、異常検知(5分)、Brain-αセッション監視(10分)。

## 19.2 時間単位
Capability Audit(1h)、SYSTEM_STATE更新(1h)、モデル品質キャッシュ(1h)、承認タイムアウト(1h)、対話学習(1h)、商品パッケージング(1h)、ハーネス健全性(毎時)。

## 19.3 情報収集
情報収集パイプライン(6h)、intel_itemsレビュー(6h)、コスト予測(6h)、リアクティブ提案(6h)、エンゲージメント取得(12h×3プラットフォーム)。

## 19.4 日次
00:00運用ログ、03:00 PGバックアップ、03:30 SQLiteバックアップ、03:45メモリ統合、04:00データ整合性+スキル抽出、04:15キャッシュ清掃、04:30ログクリーン、05:00 Karpathy+承認クリーン、05:30フィーチャーテスト、06:00相互評価+キーワード更新、06:30エンゲージメント分析、07:00提案+digest+日中モード、07:05経営日報、07:30収益チェック、08:00海外トレンド、09:30コンテンツ生成、12:00深掘り、20:30日次サマリー、22:00-23:30 SNSバッチ4本、23:00夜間モード、23:45 noteドラフト。

## 19.5 週次・月次
月曜: 07:30バズ分析、05:00ゴミ収集、09:00週次提案。日曜: 04:00ドキュメントガーデニング、21:00学習レポート、03:00競合分析。金曜23:15商品化候補。水曜10:00ドキュメンタリー。水土20:00デジタルツイン。毎月1日04:00収益機会リサーチ。

## 19.6 パワーモード
day(07:00-23:00): max_concurrent=3。night(23:00-07:00): batch=True, parallel=True, max_concurrent=6。

---

# 第20章 データベース

## 20.1 PostgreSQL（26テーブル）

主要テーブル:

| テーブル | 件数 | 用途 |
|----------|------|------|
| tasks | — | タスク管理（15カラム） |
| goal_packets | — | ゴール管理（13カラム） |
| proposal_history | — | 提案履歴（13カラム） |
| approval_queue | — | 承認キュー（7カラム） |
| intel_items | 1,040 | 情報収集（10カラム） |
| llm_cost_log | — | LLMコスト（7カラム） |
| event_log | 26,812 | イベントログ（9カラム） |
| browser_action_log | — | ブラウザ操作（12カラム） |
| chat_messages | — | チャット（6カラム） |
| persona_memory | 526 | ペルソナ記憶（10カラム） |
| episodic_memory | 37 | エピソード記憶 |
| revenue_linkage | — | 収益紐付け（9カラム） |
| capability_snapshots | — | 能力監査（4カラム） |
| model_quality_log | — | モデル品質（9カラム） |
| loop_guard_events | — | ループガード（9カラム） |
| proposal_feedback | — | 提案FB（7カラム） |
| crypto_trades | — | 暗号通貨（10カラム） |
| seasonal_revenue_correlation | — | 季節相関（7カラム） |
| settings | — | 設定KV（3カラム） |
| embeddings | — | ベクトル（6カラム、vector 1024） |
| parallel_session_log | — | 並列セッション管理（V29新規） |
| codex_analysis_results | — | Codex分析結果（V29新規） |

他: posting_queue, product_packages, note_drafts, sns_engagement, progress_log, failure_memory, skill_registry, sprint_contracts, daichi_dialogue_log, session_memory等を含め26テーブル。

## 20.2 SQLite（ノード別）
local_cache, agent_memory, local_metrics, llm_call_log。

## 20.3 SQLCipher（DELTA）
mutation_engine.enc.db。暗号化。他ノード参照不可。

---

# 第21章 API

## 21.1 認証
JWT(HS256)、24時間有効。POST /api/auth/login。

## 21.2 主要エンドポイント（70）

認証: POST /api/auth/login, GET /health。
ダッシュボード: GET /api/dashboard, /api/nodes/status, /api/budget/status。
チャット: WS /api/chat/ws, POST /api/chat/send, GET /api/chat/history。
タスク: GET /api/tasks, /api/tasks/{id}, /api/goals/{id}。
提案: GET /api/proposals, POST /api/proposals/{id}/approve, /reject, /generate。
承認: GET /api/pending-approvals, POST /api/pending-approvals/{id}/respond。
運用: GET /api/agent-ops/status, /api/revenue, /api/model-usage, /api/intel。
設定: GET/POST /api/settings, /api/settings/budget, /chat-model, /discord。
管理: POST /api/charlie/shutdown。
並列デバッグ（V29新規）: GET /api/parallel-debug/sessions, POST /api/parallel-debug/dispatch, GET /api/parallel-debug/results/{batch_id}, POST /api/parallel-debug/merge/{batch_id}, DELETE /api/parallel-debug/sessions/{session_id}。

---

# 第22章 セキュリティ

## 22.1 ツール権限
Tier 3(自動): DB読取、ローカルファイル、ローカルLLM。
Tier 2(自動+通知): 情報収集、レポート。
Tier 1(人間承認): SNS投稿、価格設定、暗号通貨取引。

## 22.2 taboo enforcement
persona_memory category='taboo'は絶対違反禁止。safety_check.pyで全出力チェック。

## 22.3 .env保護
ログ出力禁止。ハードコード禁止。password_env_keyパターン。

## 22.4 通信セキュリティ
Caddy HTTPS、JWT認証、TailscaleゼロトラストVPN（ポート開放不要）、CORS設定。

## 22.5 並列セッション安全性（V29新規）
各並列Claude Code/Codexセッションはgit worktreeで隔離。最大3セッション同時実行。セッション別budget cap。Result Mergerでの検証を経てからmainブランチにマージ。危険な変更（Tier 1相当: セキュリティ関連、承認フロー、EmergencyKill）は必ず人間承認を経る。

---

# 第23章 運用

## 23.1 デプロイ
ALPHA: git pull + pip install + npm install + ./start.sh。
リモート: ssh経由でgit pull + systemctl restart。
CORTEX: LaunchAgent KeepAlive（killで再起動）。

## 23.2 バックアップ
PostgreSQL(03:00 pg_dump) + SQLite(03:30 rsync)。保存先: DELTA HDD。

## 23.3 ログローテーション
RotatingFileHandler: 10MB×5世代。04:30にクリーンアップ。リモート: journalctl。

## 23.4 セッションフック
終了時: save_session_memory()必須。開始時: SYSTEM_STATE.md + SESSION_HANDOFF読込。LaunchAgentにPYTHONUNBUFFERED=1。

---

# 第24章 突然変異エンジン

## 24.1 設計思想
学習は保守的最適化→局所解。生物進化のDNA突然変異原理をSYUTAINβに実装。**変異は観測できない。**

## 24.2 変異の種
系統1: 物理エントロピー（CPU温度、NATS RTT、VRAM変動、パケットジッター、/dev/urandom）→SHA-256。
系統2: 人間の直感（Web UI「今日の風向き」、ハッシュ化混合、因果追跡不能）。

## 24.3 パラメータ
mutation_probability: 0.005（→max 0.05）、deviation_rate: 0.02（→max 0.15）、accumulation_coefficient: 0.0003、intuition_multiplier: 1.3。

## 24.4 蓄積
不可逆。有益→確率上昇。無益→変化なし（下がらない）。リセット不可。

## 24.5 コンプライアンス（CLAUDE.md 22条）
ログ記録しない。UI表示しない。Capability Audit含めない。9層/承認/EmergencyKillに干渉しない。try-except完全隔離。DELTA SQLCipherのみ保存。

## 24.6 実装
agents/mutation_engine.py: should_mutate(), apply_deviation(), apply_deviation_int(), report_outcome()。純粋関数。DELTA専用。

---

# 第25章 変更履歴

## V25（2026-03-15）— 原典
V20〜V24統合。全4台Phase1。GPT-5.4統合。9層ループガード。突然変異エンジン設計。choose_best_model_v6。

## V26（2026-03-20〜22）
Phase 1-9実装完了。SNS 4チャネル自動投稿。ローカル率83%。60+ジョブ。デジタルツイン124件。persona_memory embedding 100%。

## V27（2026-03-23〜28）
CLAUDE.md 26条化。Brain-α完全統合（15モジュール）。note.com収益パイプライン。Harness Engineering導入。AGENTS.md。Karpathy Loop。MemRL。doc_gardener。skill_manager。

## V28（2026-04-01）
55,100行コード。50+テーブル/25,505イベント。ローカル率85.1%。月間¥664。Discord Bot 6体。HDD 13台Samba。全64ツール/18エージェント/15 Brain-αモジュール。Harness Health 85/100。

## V29（2026-04-01）— 本設計書
55,135行コード（Python 48,370行 + TypeScript 6,765行）。26テーブル/26,812イベント。70 APIエンドポイント。40+スケジューラジョブ。ローカル率84%。月間¥747。persona_memory 526件。episodic_memory 37件。intel_items 1,040件。**第26章: Parallel Claude Code + Codex Autonomous Debugging Architecture**を新設。複数のClaude CodeセッションとCodexセッションを並列実行し、コードベース全体を自律的にデバッグ・レビュー・修復する能力を獲得。

---

# 第26章 Parallel Claude Code + Codex Autonomous Debugging Architecture

## 26.1 設計思想

SYUTAINβは55,000行超のコードベースに成長した。単一のClaude CodeセッションやCodexセッションでは、コードベース全体の同時分析・修正に限界がある。生物の免疫システムが複数のT細胞を並列に派遣して異なる病原体に同時対処するように、SYUTAINβも複数のAIコーディングセッションを並列に派遣し、異なるモジュール・バグ・レビュー対象に同時対処する能力を獲得する。

この設計の核心は以下の3点である:

1. **並列性**: 複数セッションが同時に異なるタスクを実行し、待ち時間を最小化する
2. **隔離性**: 各セッションがgit worktreeで物理的に隔離され、互いの変更が干渉しない
3. **統合性**: Result Mergerが全セッションの成果を検証・統合し、一貫性を保証する

## 26.2 全体アーキテクチャ

```
                    ┌─────────────────┐
                    │  Task Dispatcher │
                    │  (claude_code_   │
                    │   queue拡張)     │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │ Claude Code  │ │ Claude Code  │ │   Codex     │
     │ Session A    │ │ Session B    │ │  Session    │
     │ (ALPHA)      │ │ (BRAVO)      │ │ (CHARLIE)   │
     │ Bug fix      │ │ Code review  │ │ Analysis    │
     └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
              │              │              │
              └──────────────┼──────────────┘
                             ↓
                    ┌─────────────────┐
                    │ Result Merger   │
                    │ (conflict      │
                    │  resolution)    │
                    └─────────────────┘
```

### データフロー詳細

```
1. トリガー検知
   ├→ self_healer: エラー検出 → parallel_session_manager.dispatch()
   ├→ FORGE: コードレビュー要求 → task_splitter.split()
   ├→ feature_test_runner: テスト失敗 → 自動デバッグセッション起動
   └→ 手動: Web UI /parallel-debug → ユーザー指示

2. タスク分割
   task_splitter.py:
   ├→ ファイル単位分割（モジュール境界で分割）
   ├→ 機能単位分割（テスト・実装・ドキュメント）
   ├→ 依存グラフ分析（相互依存なしのタスクのみ並列化）
   └→ 推定所要時間・難易度に基づくノード割当

3. セッション起動
   parallel_session_manager.py:
   ├→ git worktree作成（/tmp/syutain_worktree_{session_id}/）
   ├→ SSH経由でリモートノードにClaude Code CLI / Codex CLI起動
   ├→ セッション別CLAUDE.mdインジェクション（スコープ制限）
   └→ budget cap設定（セッション別上限）

4. 実行・監視
   ├→ 各セッションが独立してコード分析・修正を実行
   ├→ parallel_session_logにリアルタイムでステータス記録
   ├→ Web UI /parallel-debug でライブモニタリング
   └→ タイムアウト（30分/セッション）でauto-kill

5. 結果統合
   result_merger.py:
   ├→ 各セッションのgit diffを収集
   ├→ コンフリクト検出（同一ファイル変更の場合）
   ├→ 自動テスト実行（feature_test_runner連携）
   ├→ 品質スコアリング（Verifier連携）
   └→ 承認フロー（Tier 1変更は人間承認、Tier 2-3は自動マージ）
```

## 26.3 セッションタイプ

### 26.3.1 Debug Session（デバッグセッション）
特定のバグを発見・修正することに特化したセッション。

| 項目 | 内容 |
|------|------|
| トリガー | self_healer検出、event_logエラーパターン、手動指示 |
| 入力 | エラーログ、スタックトレース、関連ファイルパス |
| 出力 | パッチ（git diff）、原因分析レポート、failure_memoryエントリ |
| 制約 | 対象ファイル以外の変更禁止。テスト追加必須 |
| タイムアウト | 30分 |
| 予算上限 | ¥50/セッション |

実行フロー:
```
エラーログ受信 → 関連ファイル特定 → git worktree作成
    ↓
Claude Code Session起動（--scope: 対象ディレクトリ限定）
    ↓
原因分析 → 修正パッチ生成 → ローカルテスト実行
    ↓
結果をparallel_session_logに記録 → Result Mergerへ送信
```

### 26.3.2 Review Session（レビューセッション）
コードレビューに特化したセッション。FORGEボットとの連携が主。

| 項目 | 内容 |
|------|------|
| トリガー | FORGE CTO指示、週次コードレビュージョブ、PR作成時 |
| 入力 | レビュー対象ファイルリスト、レビュー観点（セキュリティ/パフォーマンス/設計整合性） |
| 出力 | レビューコメント、改善提案、リファクタリングパッチ（オプション） |
| 制約 | 読み取り専用が基本。修正パッチ生成はオプション |
| タイムアウト | 20分 |
| 予算上限 | ¥30/セッション |

レビュー観点:
- **セキュリティ**: .env漏洩、ハードコードされたシークレット、SQLインジェクション
- **CLAUDE.md準拠**: 26条との整合性チェック
- **設計書整合性**: V29設計書との乖離検出
- **パフォーマンス**: N+1クエリ、不要なAPI呼び出し、メモリリーク
- **コード品質**: 重複コード、過度な複雑性、テスト不足

### 26.3.3 Analysis Session（分析セッション）
コードベース全体のパターン分析に特化したセッション。

| 項目 | 内容 |
|------|------|
| トリガー | 月次コード品質レポート、設計書更新時、新機能設計時 |
| 入力 | 分析対象ディレクトリ、分析観点 |
| 出力 | 分析レポート（JSON + Markdown）、改善提案リスト |
| 制約 | 完全読み取り専用。コード変更不可 |
| タイムアウト | 45分 |
| 予算上限 | ¥40/セッション |

分析カテゴリ:
- **依存関係マッピング**: モジュール間依存グラフの生成・可視化
- **デッドコード検出**: 未使用関数・変数・インポートの特定
- **パターン抽出**: 成功パターンのskill_registry候補抽出
- **技術負債マッピング**: TODO/FIXME/HACK集約、複雑度メトリクス
- **設計書との乖離分析**: 実装と設計書V29の差分検出

### 26.3.4 Test Session（テストセッション）
テスト実行・テスト生成に特化したセッション。

| 項目 | 内容 |
|------|------|
| トリガー | feature_test_runner失敗、新モジュール追加時、デプロイ前検証 |
| 入力 | テスト対象モジュール、期待される振る舞い |
| 出力 | テストコード、テスト実行結果、カバレッジレポート |
| 制約 | テストファイル（tests/）のみ変更可。本体コード変更不可 |
| タイムアウト | 30分 |
| 予算上限 | ¥30/セッション |

### 26.3.5 Self-Heal Session（自己修復セッション）
検出されたエラーを自律的に修復するセッション。self_healerの拡張版。

| 項目 | 内容 |
|------|------|
| トリガー | self_healer検出かつ自動修復失敗時、重大エラー連続検出時 |
| 入力 | エラー詳細、self_healer試行履歴、failure_memory参照 |
| 出力 | 修正パッチ、テスト、failure_memory更新 |
| 制約 | 9層LoopGuard/承認フロー/EmergencyKillのコード変更は禁止。Tier 1承認必須 |
| タイムアウト | 30分 |
| 予算上限 | ¥50/セッション |

自己修復フロー:
```
self_healer: 自動修復失敗を検出
    ↓
failure_memory照合 → 過去の類似エラー修復パターン検索
    ↓
parallel_session_manager: Self-Heal Session起動
    ↓
Claude Code Session:
  1. エラーの根本原因分析（Root Cause Analysis）
  2. failure_memoryの過去パターンを参考に修正案生成
  3. git worktree上でパッチ適用
  4. テスト実行で修正検証
    ↓
Result Merger:
  1. パッチの安全性検証
  2. 対象ファイルのTier判定
  3. Tier 1 → 人間承認キュー → ApprovalManager
  4. Tier 2-3 → 自動マージ → Discord通知
    ↓
mainブランチにマージ → failure_memory更新 → self_healer学習
```

## 26.4 コンポーネント詳細設計

### 26.4.1 parallel_session_manager.py

並列セッションのライフサイクル管理を担当するコアモジュール。

```python
# 主要インターフェース
class ParallelSessionManager:
    MAX_CONCURRENT_SESSIONS = 3  # リソース制約による上限
    SESSION_TIMEOUT_MINUTES = 30  # デフォルトタイムアウト

    async def dispatch(
        self,
        task_type: SessionType,      # debug/review/analysis/test/self_heal
        target_files: list[str],     # 対象ファイルパス
        context: dict,               # エラーログ、レビュー観点等
        node_preference: str = None, # ALPHA/BRAVO/CHARLIE/DELTA
        budget_cap_jpy: int = 50,    # セッション別予算上限
    ) -> str:  # session_id
        """
        並列セッションをディスパッチする。
        1. 空きスロット確認（MAX_CONCURRENT_SESSIONS）
        2. ノード選定（node_preference or NodeRouter自動選定）
        3. git worktree作成
        4. セッション起動（SSH + CLI）
        5. parallel_session_logに記録
        """
        pass

    async def get_session_status(self, session_id: str) -> SessionStatus:
        """セッションのリアルタイムステータスを取得"""
        pass

    async def kill_session(self, session_id: str, reason: str) -> bool:
        """セッションを強制終了"""
        pass

    async def list_active_sessions(self) -> list[SessionInfo]:
        """アクティブセッション一覧"""
        pass
```

ノード選定ロジック:
- **ALPHA**: Debug Session優先（司令塔のコード理解が最も深い）
- **BRAVO**: Review Session優先（RTX 5070でCodex高速実行）
- **CHARLIE**: Analysis Session優先（RTX 3080でバッチ分析）
- **DELTA**: 軽量タスクのみ（GTX 980Ti制約）

セッション起動コマンド:
```bash
# Claude Code Session（ALPHA/BRAVOの場合）
ssh shimahara@{node_ip} "cd /tmp/syutain_worktree_{session_id} && \
  claude --print --dangerously-skip-permissions \
  --max-tokens 50000 \
  '{task_prompt}'" > /tmp/session_{session_id}_output.log 2>&1 &

# Codex Session（CHARLIE/DELTAの場合）
ssh shimahara@{node_ip} "cd /tmp/syutain_worktree_{session_id} && \
  codex --mode full-auto \
  --quiet \
  '{task_prompt}'" > /tmp/session_{session_id}_output.log 2>&1 &
```

### 26.4.2 codex_integration.py

Codex CLI（OpenClaw）をラップし、分析タスクに特化した統合モジュール。

```python
class CodexIntegration:
    """
    Codex CLIのラッパー。
    リモートノード（BRAVO/CHARLIE/DELTA）でCodexを実行し、
    分析結果をcodex_analysis_resultsテーブルに格納する。

    注意: ALPHAではCodexはuninstalled（2026-03-06）。
    リモート（BRAVO/CHARLIE/DELTA）にはv2026.3.2がインストール済み。
    Ollamaフォールバックモデル: BRAVO=qwen3.5:9b, CHARLIE=qwen3.5:9b, DELTA=qwen3.5:4b
    """

    AVAILABLE_NODES = ["BRAVO", "CHARLIE", "DELTA"]  # ALPHAは除外

    async def run_analysis(
        self,
        node: str,
        target_path: str,
        analysis_type: str,  # pattern/dependency/dead_code/complexity
        worktree_path: str,
    ) -> CodexAnalysisResult:
        """
        Codexで静的分析を実行。
        結果はJSON形式でcodex_analysis_resultsに保存。
        """
        pass

    async def run_code_review(
        self,
        node: str,
        files: list[str],
        review_criteria: list[str],
        worktree_path: str,
    ) -> CodexReviewResult:
        """
        Codexでコードレビューを実行。
        FORGE CTOとの連携: FORGEがレビュー観点を指定し、
        Codexが実行、結果をFORGEがDiscordに報告。
        """
        pass
```

### 26.4.3 result_merger.py

並列セッションの成果物を統合し、mainブランチへの安全なマージを担当する。

```python
class ResultMerger:
    """
    並列セッションからの成果物（git diff、レポート、テスト結果）を
    統合し、コンフリクト解決とマージを行う。

    マージ戦略:
    1. コンフリクトなし → 自動マージ候補
    2. コンフリクトあり → LLMでresolution生成 → 人間確認
    3. 安全性検証:
       - 全テスト通過必須
       - 9層LoopGuard関連コード変更 → 必ず人間承認
       - .env/.secrets関連 → 絶対拒否
    """

    async def merge_batch(
        self,
        batch_id: str,
    ) -> MergeResult:
        """
        同一batch_idの全セッション結果を統合。

        フロー:
        1. 全セッション完了待ち（タイムアウトあり）
        2. 各worktreeのgit diff収集
        3. コンフリクト検出
        4. コンフリクト解決（LLM支援）
        5. 統合パッチをテスト環境で検証
        6. Tier判定 → 承認フロー or 自動マージ
        """
        pass

    async def detect_conflicts(
        self,
        diffs: list[SessionDiff],
    ) -> list[Conflict]:
        """
        複数セッションのdiffからコンフリクトを検出。
        同一ファイル・同一行の変更を特定。
        """
        pass

    async def resolve_conflict(
        self,
        conflict: Conflict,
    ) -> Resolution:
        """
        LLM（DeepSeek-V3.2）でコンフリクト解決案を生成。
        安全性チェック後、人間承認が必要な場合はApprovalManagerへ。
        """
        pass

    async def validate_merged_result(
        self,
        merged_worktree: str,
    ) -> ValidationResult:
        """
        マージ後のコードを検証:
        - Pythonシンタックスチェック
        - import解決確認
        - feature_test_runner実行
        - harness_linterチェック
        """
        pass
```

### 26.4.4 task_splitter.py

大きなタスクを並列実行可能なサブタスクに分割するモジュール。

```python
class TaskSplitter:
    """
    大規模タスク（例: 全モジュールレビュー、全テスト実行）を
    並列実行可能なサブタスクに分割する。

    分割戦略:
    1. ファイル単位: モジュール境界で分割（agents/, tools/, brain_alpha/等）
    2. 機能単位: テスト/実装/ドキュメントで分割
    3. 依存グラフ: importグラフを分析し、相互依存なしのクラスタに分割
    """

    async def split(
        self,
        task: ParallelTask,
        max_subtasks: int = 3,  # MAX_CONCURRENT_SESSIONSに一致
    ) -> list[SubTask]:
        """
        タスクをmax_subtasks個以下のサブタスクに分割。

        分割アルゴリズム:
        1. 対象ファイルの依存グラフを構築（AST解析）
        2. 強連結成分（SCC）を計算
        3. SCC間の辺を切断して独立クラスタを生成
        4. クラスタを推定難易度でソートし、max_subtasks個にグルーピング
        5. 各サブタスクにノードを割当（NodeRouter連携）
        """
        pass

    async def build_dependency_graph(
        self,
        files: list[str],
    ) -> DependencyGraph:
        """
        Pythonファイルのimport文を解析し、依存グラフを構築。
        AST（ast.parse）で静的解析。
        """
        pass

    async def estimate_complexity(
        self,
        files: list[str],
    ) -> dict[str, float]:
        """
        ファイル別の推定複雑度を算出。
        指標: 行数、循環的複雑度、import数、クラス/関数数。
        """
        pass
```

## 26.5 データベーススキーマ

### 26.5.1 parallel_session_log テーブル

```sql
CREATE TABLE parallel_session_log (
    id              SERIAL PRIMARY KEY,
    session_id      UUID NOT NULL UNIQUE,
    batch_id        UUID NOT NULL,           -- 同一タスクグループのID
    session_type    VARCHAR(20) NOT NULL,    -- debug/review/analysis/test/self_heal
    node            VARCHAR(10) NOT NULL,    -- ALPHA/BRAVO/CHARLIE/DELTA
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- pending/running/completed/failed/killed/timeout
    target_files    JSONB NOT NULL,          -- 対象ファイルリスト
    context         JSONB,                   -- エラーログ等のコンテキスト
    worktree_path   TEXT,                    -- git worktreeパス
    budget_cap_jpy  INTEGER DEFAULT 50,      -- セッション別予算上限
    actual_cost_jpy NUMERIC(10,2) DEFAULT 0, -- 実際のコスト
    result_summary  TEXT,                    -- 結果サマリー
    diff_content    TEXT,                    -- git diff内容
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    timeout_minutes INTEGER DEFAULT 30
);

CREATE INDEX idx_parallel_session_batch ON parallel_session_log(batch_id);
CREATE INDEX idx_parallel_session_status ON parallel_session_log(status);
CREATE INDEX idx_parallel_session_node ON parallel_session_log(node);
```

### 26.5.2 codex_analysis_results テーブル

```sql
CREATE TABLE codex_analysis_results (
    id              SERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES parallel_session_log(session_id),
    analysis_type   VARCHAR(30) NOT NULL,    -- pattern/dependency/dead_code/complexity/review
    target_path     TEXT NOT NULL,           -- 分析対象パス
    node            VARCHAR(10) NOT NULL,    -- 実行ノード
    findings        JSONB NOT NULL,          -- 分析結果（構造化データ）
    severity        VARCHAR(10),             -- critical/high/medium/low/info
    recommendations JSONB,                   -- 改善提案リスト
    raw_output      TEXT,                    -- Codex生出力
    execution_time  INTERVAL,               -- 実行時間
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_codex_analysis_session ON codex_analysis_results(session_id);
CREATE INDEX idx_codex_analysis_type ON codex_analysis_results(analysis_type);
CREATE INDEX idx_codex_analysis_severity ON codex_analysis_results(severity);
```

### 26.5.3 claude_code_queue 拡張カラム

既存のclaude_code_queueテーブルに以下のカラムを追加:

```sql
ALTER TABLE claude_code_queue ADD COLUMN parallel_batch_id UUID;
ALTER TABLE claude_code_queue ADD COLUMN session_assignment VARCHAR(10);
-- session_assignment: ALPHA/BRAVO/CHARLIE/DELTA
CREATE INDEX idx_ccq_batch ON claude_code_queue(parallel_batch_id);
```

## 26.6 git worktree隔離戦略

各並列セッションはgit worktreeで物理的に隔離される。これにより、複数セッションが同じリポジトリの異なるブランチで同時に作業でき、互いの変更が干渉しない。

### worktreeライフサイクル

```
1. 作成
   git worktree add /tmp/syutain_worktree_{session_id} -b parallel/{session_id}

2. セッション実行
   各セッションはworktree内で自由にファイル変更可能
   （ただしsession_typeに応じたスコープ制限あり）

3. 結果収集
   git -C /tmp/syutain_worktree_{session_id} diff main...HEAD > diff.patch

4. クリーンアップ
   git worktree remove /tmp/syutain_worktree_{session_id}
   git branch -D parallel/{session_id}
```

### worktree管理ポリシー

| ポリシー | 内容 |
|----------|------|
| 最大同時worktree数 | 3（MAX_CONCURRENT_SESSIONS） |
| worktreeの保持期間 | セッション完了後1時間で自動削除 |
| ディスク使用量上限 | worktree合計5GB以下（それ以上はkill） |
| ベースブランチ | 常にmainの最新HEADから分岐 |
| リモートworktree | SSH経由でリモートノードにも作成可能 |

### リモートノードでのworktree

リモートノード（BRAVO/CHARLIE/DELTA）にはsyutain_betaリポジトリが /home/shimahara/syutain_beta/ に存在する。リモートworktreeは以下の手順で作成:

```bash
# リモートノードでworktree作成
ssh shimahara@{node_ip} "cd /home/shimahara/syutain_beta && \
  git fetch origin main && \
  git worktree add /tmp/syutain_worktree_{session_id} -b parallel/{session_id} origin/main"

# セッション完了後のクリーンアップ
ssh shimahara@{node_ip} "cd /home/shimahara/syutain_beta && \
  git worktree remove /tmp/syutain_worktree_{session_id} && \
  git branch -D parallel/{session_id}"
```

## 26.7 FORGE連携: 並列コードレビュー

FORGEボット（CTO、CHARLIE）は並列コードレビューの主要なトリガーである。

### レビューフロー

```
FORGE (Discord) → コードレビュー要求を受信
    ↓
task_splitter: レビュー対象をモジュール別に分割
    例: agents/(Session A) + tools/(Session B) + brain_alpha/(Session C)
    ↓
parallel_session_manager: 3つのReview Sessionをディスパッチ
    Session A → ALPHA（agents/ レビュー）
    Session B → BRAVO（tools/ レビュー）
    Session C → CHARLIE（brain_alpha/ レビュー、Codex使用）
    ↓
各セッションが独立してコードレビューを実行
    ↓
result_merger: レビュー結果を統合
    ↓
FORGE → Discord #code-review チャネルに統合レポート投稿
    ├→ critical: 即時対応必要（赤）
    ├→ high: 次スプリントで対応（橙）
    ├→ medium: 改善推奨（黄）
    └→ info: 参考情報（灰）
```

## 26.8 self_healer連携: 自律修復の拡張

既存のself_healer（5分間隔）が自動修復に失敗した場合、Parallel Self-Heal Sessionを自動起動する。

### エスカレーションフロー

```
self_healer: エラー検出（5分間隔）
    ↓
自動修復試行（既存ロジック）
    ↓
  成功 → 通常運用継続
  失敗 → Parallel Self-Heal Session起動判定
    ↓
判定条件:
  - 同一エラー2回連続自動修復失敗
  - severity >= high
  - failure_memoryに類似パターンなし（未知のエラー）
    ↓
parallel_session_manager.dispatch(
    task_type=SessionType.SELF_HEAL,
    target_files=[関連ファイルリスト],
    context={
        "error_log": エラーログ,
        "stack_trace": スタックトレース,
        "self_healer_attempts": 試行履歴,
        "failure_memory_similar": 類似パターン,
    },
    budget_cap_jpy=50,
)
    ↓
Claude Code Session: Root Cause Analysis + 修正パッチ生成
    ↓
Result Merger: 安全性検証 + Tier判定 + マージ
    ↓
failure_memory更新 → self_healer学習
```

## 26.9 リソース制約と安全性

### 26.9.1 リソース制約

| 制約 | 値 | 理由 |
|------|-----|------|
| 最大同時セッション数 | 3 | 4ノードのCPU/GPU/メモリ制約 |
| セッション別予算上限 | ¥50 | 日次予算¥80の範囲内で運用 |
| 日次並列セッション予算 | ¥100 | 月次予算¥1,500の7%以下 |
| セッションタイムアウト | 30分（デフォルト） | 暴走防止 |
| worktreeディスク上限 | 5GB合計 | ディスク枯渇防止 |
| 同一ファイル同時変更 | 禁止 | コンフリクト防止 |

### 26.9.2 安全性ガードレール

**絶対禁止事項（Hard Block）:**
- 9層LoopGuardのコード変更
- Emergency Killのコード変更
- 承認フロー（ApprovalManager）のコード変更
- 突然変異エンジンのコード変更
- .envファイルの変更
- credentials.json / token.jsonの変更
- CLAUDE.mdの変更
- 設計書（本ドキュメント）の変更

**人間承認必須（Tier 1）:**
- セキュリティ関連コードの変更（security/, auth/, jwt関連）
- データベーススキーマの変更（db_init.py, migration）
- 本番環境のデプロイスクリプト変更
- Discord Bot（bots/）のコード変更

**自動マージ可能（Tier 2-3）:**
- バグ修正パッチ（テスト通過必須）
- テストコードの追加・修正
- ドキュメント更新
- ログメッセージの修正
- 型ヒントの追加

### 26.9.3 9層LoopGuardとの統合

並列セッション自体も9層LoopGuardの監視下に置かれる:

- **Layer 1（Retry Budget）**: 同一エラーに対するSelf-Heal Session再試行は2回まで
- **Layer 2（Same-Failure Cluster）**: 同一エラークラスタのセッション起動は30分凍結
- **Layer 6（Cost & Time Guard）**: セッション別budget cap + 日次並列セッション予算
- **Layer 7（Emergency Kill）**: 全セッションの累計コストが日次予算90%に達したら全セッション即座にkill
- **Layer 9（Cross-Goal Interference）**: 並列セッション間のリソース競合検知

## 26.10 Web UI: /parallel-debug ページ

### 画面構成

```
┌───────────────────────────────────────────────┐
│  Parallel Debug Monitor                  [V29] │
├───────────────────────────────────────────────┤
│                                               │
│  Active Sessions: 2/3        Budget: ¥23/¥100 │
│                                               │
│  ┌─── Session A ────────────────────────────┐ │
│  │ Type: Debug | Node: ALPHA | Status: ● RUN│ │
│  │ Target: tools/llm_router.py              │ │
│  │ Elapsed: 12m34s / 30m                    │ │
│  │ Cost: ¥8 / ¥50                           │ │
│  │ Progress: Analyzing root cause...        │ │
│  └──────────────────────────────────────────┘ │
│                                               │
│  ┌─── Session B ────────────────────────────┐ │
│  │ Type: Review | Node: BRAVO | Status: ● RUN││
│  │ Target: agents/*.py (7 files)            │ │
│  │ Elapsed: 5m12s / 20m                     │ │
│  │ Cost: ¥3 / ¥30                           │ │
│  │ Progress: Reviewing agents/os_kernel.py  │ │
│  └──────────────────────────────────────────┘ │
│                                               │
│  ┌─── Recent Results ───────────────────────┐ │
│  │ [2026-04-01 15:30] Batch #a1b2c3        │ │
│  │   Debug(ALPHA): ✓ Fixed llm_router bug  │ │
│  │   Review(BRAVO): ✓ 3 issues found       │ │
│  │   Analysis(CHARLIE): ✓ Report generated  │ │
│  │   Merge Status: ✓ Auto-merged           │ │
│  │                                          │ │
│  │ [2026-04-01 14:15] Batch #d4e5f6        │ │
│  │   Self-Heal(ALPHA): ✓ Patched           │ │
│  │   Merge Status: ⏳ Awaiting approval    │ │
│  └──────────────────────────────────────────┘ │
│                                               │
│  [Dispatch New Session]  [Kill All Sessions]  │
│                                               │
└───────────────────────────────────────────────┘
```

### UIコンポーネント

| コンポーネント | 技術 | 更新間隔 |
|---------------|------|---------|
| セッションカード | React + SSE | 5秒 |
| バッチ結果リスト | React + REST | 手動 |
| セッション起動モーダル | React + WebSocket | — |
| リソースゲージ | shadcn/ui Progress | 5秒 |
| ログストリーム | SSE EventSource | リアルタイム |

## 26.11 スケジューラ統合

並列セッションに関連するスケジューラジョブ:

| ジョブ | 間隔 | 内容 |
|--------|------|------|
| parallel_session_cleanup | 1時間 | 完了後1時間経過したworktreeの削除 |
| parallel_session_timeout_check | 5分 | タイムアウトセッションの自動kill |
| weekly_code_review_dispatch | 週次（日曜05:00） | FORGE連携：全モジュール並列レビュー |
| codex_analysis_digest | 週次（月曜07:00） | Codex分析結果の週次ダイジェスト生成 |

## 26.12 NATS統合

並列セッション用のNATSサブジェクト:

| サブジェクト | 用途 |
|-------------|------|
| `parallel.dispatch.{node}` | セッションディスパッチ指示 |
| `parallel.status.{session_id}` | セッションステータス更新 |
| `parallel.result.{session_id}` | セッション結果通知 |
| `parallel.kill.{session_id}` | セッション強制終了指示 |
| `parallel.merge.{batch_id}` | バッチマージ完了通知 |

## 26.13 実装計画

### Phase 1: 基盤（Week 1）
- parallel_session_manager.py の基本実装
- parallel_session_log / codex_analysis_results テーブル作成
- git worktree作成・削除の自動化
- 単一セッション（Debug Session）の動作確認

### Phase 2: 統合（Week 2）
- task_splitter.py 実装（依存グラフ分析）
- result_merger.py 実装（コンフリクト検出・解決）
- codex_integration.py 実装（リモートCodex連携）
- FORGE連携（Review Session）

### Phase 3: 自律化（Week 3）
- self_healer連携（Self-Heal Session自動起動）
- 9層LoopGuardとの統合
- Web UI /parallel-debug ページ実装
- NATS統合

### Phase 4: 最適化（Week 4）
- セッションスケジューリング最適化
- コスト最適化（セッション合計予算管理）
- 週次並列コードレビュー自動化
- ドキュメント更新・テスト充実

## 26.14 期待される効果

| 指標 | 現状（V28） | 目標（V29） | 改善率 |
|------|------------|------------|--------|
| バグ修正時間 | 手動/self_healer | 自動並列デバッグ | -70% |
| コードレビュー範囲 | FORGE単体 | 3並列レビュー | 3x |
| 未知エラー対応 | self_healer失敗→手動 | Self-Heal Session | 自動化 |
| コードベース分析 | 手動/単一セッション | Codex並列分析 | 3x |
| テスト実行 | 逐次実行 | 並列実行 | -60% |

---

**ドキュメント終了**

*SYUTAINβ 完全設計書 V29 — 2026-04-01作成*
*プロジェクトオーナー: 島原大知*
*設計・実装・運用: SYUTAINβ + Claude Code*

> 「道が塞がっても、自分で考え、自分で動き、自分で止まれる。そして今、自分で自分を直せるようになった。」
