# SYUTAINβ 完全設計書 V26

**バージョン:** V26.1 (2026-03-28)
**前バージョン:** V26 (2026-03-27) / V25 (2026-03-15)
**作成者:** SYUTAINβ Brain-α + 島原大知
**ステータス:** Phase 1 完了・Phase 2 本格移行中

---

## 第1章 システムアイデンティティ

### 1.1 名称・読み
- **正式名称:** SYUTAINβ (Sustainable Yield Utilizing Technology And Intelligence Network β)
- **読み:** シュタインベータ
- **Discord表示名:** SYUTAINβ
- **Xアカウント:** @syutain_beta

### 1.2 設計思想
4台のPCがPhase 1初日から全て連携し、NATSメッセージングで結ばれ、Web UIを通じてiPhoneからリアルタイム監視でき、マルチエージェントが自律的に認識・思考・行動・検証・停止判断を行い、目標だけを受けても道筋が変わっても自分で考え、自分で動き、自分で止まれる「自律分散型 事業OS」。

### 1.3 V25→V26→V26.1 主要変更点

| 変更領域 | V25 | V26.1 |
|---------|-----|-------|
| DBプール | 各モジュール独自プール(20+重) | **全モジュール統合完了** tools/db_pool.py集中管理 |
| 品質スコアリング | 6軸 | 7軸 + ハルシネーション検出 + 簡体字直接検出 |
| SNS自動承認閾値 | 0.60 | 0.75（0.60-0.74はpending_review） |
| Verifier検出 | AIパターン+品質スコア | +中国語混入+名前読み+AI自己開示+太字コロン+企業名ハルシネーション+簡体字直接検出 |
| 承認フロー | NATS request-reply（タイムアウト） | **ApprovalManager直接呼び出し**（social_tools/commerce_tools修正） |
| 相互評価 | write-only | フィードバックループ接続 + Brain-αエスカレーション |
| Discord bot | 部分的状況報告 | **全チャットにシステム状態注入**（LLMが正確に状況把握） |
| Discord通知 | 5関数未使用 | **全関数接続済み**（タスク完了/失敗/承認/日次サマリー/緊急停止） |
| Planner | 情報盲目（intel_digest未参照） | **intel_context + persona_context注入** |
| LLMモデル回避 | avoid_models 2/10パスのみ | **全ルーティングパスでavoid_models適用** |
| model_quality_log | verifier+learning_manager二重書き | **learning_managerに一元化** |
| content_multiplier | X投稿が承認キュー未投入 | **全プラットフォーム承認キュー投入** |
| 情報パイプライン | review_flag NULL→digest空 | **自動review_flag設定 + 正しいカラム名** |
| emergency_kill | ログファイルのみ | **Discord緊急通知追加** |
| Brain-β→α指示 | 手動エスカレーションのみ | **自動修復失敗時の自動エスカレーション** |
| 起動モード | 手動night/day切替 | **JST時刻自動判定** |
| 日次サマリー | なし | **毎日20:30 JST Discord通知** |
| executor goal_packet | 一部メソッドで欠落 | **全メソッドにgoal_packet伝播** |
| Feature Flags | Path未import NameError | **修正済み** |
| capability_audit | ensure_future使用 | **create_task使用に修正** |

---

## 第2章 ハードウェア構成

### 2.1 ノードレイアウト

| ノード | ハードウェア | 役割 | ローカルLLM | GPU |
|--------|-------------|------|------------|-----|
| ALPHA | Mac mini M4 Pro 16GB | オーケストレータ / Web UI / PostgreSQL / NATS Server / Brain-α | Qwen3.5-9B (MLX、オンデマンド起動) | M4 Pro |
| BRAVO | Ryzen + RTX 5070 12GB | ブラウザ操作 / Computer Use / コンテンツ生成 | Qwen3.5-9B (Ollama) | RTX 5070 |
| CHARLIE | Ryzen 9 + RTX 3080 10GB | 推論メイン / バッチ処理 | Qwen3.5-9B (Q4_K_M) | RTX 3080 |
| DELTA | Xeon E5 + GTX 980Ti 6GB + 48GB RAM | 監視 / 情報収集 / ヘルスチェック | Qwen3.5-4B (Q4) | GTX 980Ti |

### 2.2 ネットワーク
- **VPN:** Tailscale mesh (4ノード全接続)
- **メッセージング:** NATS v2.12.5 + JetStream (4ノードRAFTクラスタ)
- **NATS Server:** ALPHA (0.0.0.0:4222)、クラスタポート6222
- **JetStream:** 256MB メモリ / 1GB ファイル

### 2.3 ローカルLLM運用ルール（V26更新）
- ALPHAの推論はBRAVO/CHARLIEが両方ビジー時のみMLXでオンデマンドロード
- BRAVO/CHARLIEは常時Ollamaで9Bモデルを待機
- DELTAは4Bモデルで軽量タスク（情報収集スコアリング等）のみ
- **avoid_models（V26新規）:** model_quality_logで平均品質 < 0.4（5件以上）のモデルは自動回避

---

## 第3章 ソフトウェアアーキテクチャ

### 3.1 コードベース概要

| カテゴリ | ファイル数 | 総行数 | 主要ファイル |
|---------|-----------|--------|-------------|
| FastAPI Server | 1 | 3,336 | app.py |
| Scheduler | 1 | 2,642 | scheduler.py (55ジョブ) |
| Worker | 1 | 388 | worker_main.py |
| Agents | 17 | ~8,500 | os_kernel, planner, executor, verifier等 |
| Brain-α | 10 | ~4,500 | sns_batch, content_pipeline, memory_manager等 |
| Tools | 35 | ~9,000 | llm_router, db_pool, social_tools等 |
| Bots (Discord) | 8 | ~2,500 | discord_bot, bot_conversation, bot_actions等 |
| Web UI | 24 | - | Next.js 16 + React 19 PWA |
| **合計** | **97+** | **~33,600** | |

### 3.2 APIエンドポイント
61エンドポイント（認証1 + ヘルス1 + 機能59）

### 3.3 データベース

**PostgreSQL（ALPHA共有状態）: 21テーブル**

| テーブル | 用途 |
|---------|------|
| tasks | タスク管理（690行 at 2026-03-27） |
| goal_packets | ゴールライフサイクル |
| proposal_history / proposal_feedback | 提案管理 |
| revenue_linkage | 収益紐付け |
| capability_snapshots | 能力監査 |
| loop_guard_events | ループ防止イベント |
| model_quality_log | モデル品質ログ |
| seasonal_revenue_correlation | 季節収益相関 |
| chat_messages | Web UIチャット |
| intel_items | 情報収集（677行） |
| crypto_trades | 暗号通貨取引 |
| approval_queue | 承認キュー |
| browser_action_log | ブラウザ操作ログ（7,282行） |
| settings | 設定KVS |
| llm_cost_log | LLMコスト（6,238行） |
| embeddings | ベクトルストア |
| event_log | イベントログ（16,809行） |
| brain_handoff | Brain-αハンドオフ |
| node_state | ノード状態 |
| auto_fix_log | 自動修復ログ |

**追加テーブル（app.py/Brain-αで使用、db_init未登録）:**
- brain_alpha_session, persona_memory, daichi_dialogue_log
- agent_reasoning_trace, brain_cross_evaluation
- review_log, posting_queue, discord_chat_history
- intel_digest, claude_code_queue, note_quality_reviews

**SQLite（ノードローカル）: 4テーブル**
local_cache, agent_memory, local_metrics, llm_call_log

---

## 第4章 エージェントアーキテクチャ

### 4.1 5段階自律ループ

```
Perceive → Think(Plan) → Act(Execute) → Verify → StopOrContinue
    ↑                                                    ↓
    ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

| 段階 | エージェント | 役割 |
|------|-------------|------|
| Perceive | Perceiver | ゴール解釈、persona_memory参照、環境認識 |
| Think | Planner | タスクDAG生成、依存関係解決 |
| Act | Executor | LLMタスク実行、ブラウザ操作、ツール呼び出し |
| Verify | Verifier | 7軸+品質スコアリング、AI検出、2段階精錬 |
| Stop | StopDecider | LoopGuard 9層チェック、価値根拠評価 |

### 4.2 支援エージェント

| エージェント | 役割 |
|-------------|------|
| OSKernel | 中央調整、ゴールパケット生成、タスクディスパッチ |
| NodeRouter | NATSベースのノード間ルーティング |
| ApprovalManager | 3層承認（人間/自動+通知/完全自動） |
| ProposalEngine | 3層提案生成（直感/分析/対抗） |
| BrowserAgent | 4層ブラウザ操作 |
| ComputerUseAgent | GPT-5.4 Computer Use API |
| MonitorAgent | ノード監視・異常検知 |
| InfoCollector | 情報収集パイプライン |
| LearningManager | 学習・フィードバック蓄積 |
| CapabilityAudit | 能力スナップショット |
| MutationEngine | 突然変異エンジン（第24章） |

### 4.3 DBプール統合状況（V26.1: 全完了）

| 状態 | モジュール |
|------|-----------|
| ✅ 統合済み | **全モジュール**: db_pool, event_logger, budget_guard, loop_guard, storage_tools, info_pipeline, cross_goal_detector, scheduler(21箇所), executor, planner, perceiver, verifier, capability_audit, os_kernel, proposal_engine, chat_agent(12箇所), approval_manager(8箇所), app.py |

合計約40箇所のpool使用サイトを`async with get_connection() as conn:`に統合。接続プールはtools/db_pool.pyが一元管理し、各モジュールは`close()`でプール解放不要。

---

## 第5章 Brain-α（自律知能層）

### 5.1 構成

| モジュール | 役割 |
|-----------|------|
| memory_manager.py | セッション記憶、persona_memory管理、7日圧縮 |
| persona_bridge.py | 人格コンテキスト構築（casual/standard/strategic/code_fix） |
| sns_batch.py | SNS投稿バッチ生成（7軸品質スコアリング） |
| content_pipeline.py | 5段階コンテンツパイプライン |
| cross_evaluator.py | 相互評価 + フィードバックループ（V26新規接続） |
| self_healer.py | 自動修復（検証付き） |
| startup_review.py | 8フェーズ起動レビュー（FastAPI lifespan統合） |
| escalation.py | エスカレーションパス（β→α/α→β） |
| session_save.py | セッション自動保存（実データ収集、V26修正） |
| safety_check.py | PreToolUseフック（破壊操作防止） |
| auto_log.py | PostToolUseフック（ファイル変更記録） |
| note_quality_checker.py | note記事2段階品質チェック |

### 5.2 7軸品質スコアリング（V26）

| 軸 | 重み | 検出内容 |
|----|------|---------|
| 人間味 | 0.17 | 具体例、感情表現、体験談 |
| 島原らしさ | 0.17 | VTuber経験、非エンジニア視点、一人称一貫性 |
| 完結性 | 0.16 | 起承転結、行動宣言で締める |
| エンゲージメント | 0.13 | 問いかけ、数字、フック |
| AI臭さの無さ | 0.13 | 禁止語句、テンプレート回避 |
| 読みやすさ | 0.08 | 文長バランス、改行 |
| 構造準拠 | 0.16 | Phase A(具体冒頭)/D(断言核心)/E(行動締め) |

**V26.1 ハードフェイル（スコア上限0.30）:**
- M. 簡体字直接検出（压/热/设/买等の簡体字をパターンマッチ）→ ペナルティ0.40
- M. 中国語混入（仮名なしCJK検出）→ ペナルティ0.30
- N. 島原大知の名前読み誤り（うらわら、おおとも等）→ ペナルティ0.50
- N2. 企業名ハルシネーション（Nvidia（英ビザ）等の誤読み生成）→ ペナルティ0.40
- O. AI自己開示（「AIです」「仮の私（AI）」等）→ ペナルティ0.40
- P. 太字コロン過多（3箇所以上）→ ペナルティ0.15

### 5.3 コンテンツパイプライン 5段階

```
Stage 1: テーマ選定（intel_items + persona_memory）
Stage 2: Phase A-E アウトライン生成
Stage 3: 初稿生成（500文字未満で失敗）
Stage 4: 島原の声でリライト（最大2回）
Stage 5: 品質検証（7軸スコアリング、閾値0.75）
```

---

## 第6章 LLMルーティング

### 6.1 ティア構成

| ティア | モデル | 用途 |
|--------|--------|------|
| S | GPT-5.4, Claude Opus 4.6, Gemini 3.1 Pro | Computer Use, 高品質生成 |
| A | DeepSeek-V3.2 ($0.28/1M), Claude Sonnet 4.6, GPT-5 Mini | 標準生成・分析 |
| B | Claude Haiku 4.5, GPT-5 Nano | 分類・スコアリング |
| L | Qwen3.5-9B (BRAVO/CHARLIE), Qwen3.5-4B (DELTA) | ローカル推論 |

### 6.2 コスト最適化
- **ローカルLLM使用率:** 85.8%（目標80%以上を達成）
- **日次予算:** ¥80
- **月次予算:** ¥1,500
- **情報収集月次予算:** ¥15,000
- **2段階精錬:** ローカルLLM → 品質 < 0.7 → API精錬

### 6.3 モデル品質学習ループ（V26.1完成）

```
call_llm() → record_spend()
     ↓
Verifier._log_quality() → learning_manager.track_model_quality()
     ↓                           ↓
     (V26.1: 二重書き削除)    model_quality_log INSERT
                                      ↓
refresh_model_quality_cache() → _model_quality_cache
                                      ↓
choose_best_model_v6() ← avoid_models 全パスチェック（V26.1修正）
  - Nemotron優先ルート: avoid_listチェック
  - DELTA軽量タスク: avoid_listチェック
  - LOCAL_OK: avoid_listチェック
  - デフォルトローカル: avoid_listチェック + フォールバック→claude-haiku-4-5
```

---

## 第7章 承認フロー

### 7.1 3層承認

| Tier | 条件 | 処理 |
|------|------|------|
| Tier 1（人間承認） | 金額・メンション含む投稿、Brain-αレビュー済み | Discord通知→人間判断 |
| Tier 2（自動+通知） | SNS投稿 品質 ≥ 0.75 | 自動承認 + Discord通知 |
| Tier 3（完全自動） | 内部タスク、情報収集 | 即座に実行 |

### 7.2 承認リクエスト方式（V26.1修正）

V26以前: social_tools/commerce_toolsがNATS request-reply (`approval.request`) でApprovalManagerに承認要求 → **ハンドラー未実装のため全リクエストがタイムアウト → 全SNS投稿・商取引がブロック**

V26.1: social_tools/commerce_toolsが **ApprovalManagerを直接import・呼び出し**（`manager.request_approval()`）。NATSは通知用途のみに限定。

### 7.3 品質ゲート統一（V26.1）

| チェックポイント | 閾値 |
|----------------|------|
| sns_batch生成 | ≥ 0.75 → pending、0.60-0.74 → pending_review、< 0.60 → rejected |
| approval_manager | ≥ 0.75 → Tier 2（自動承認） |
| posting_queue_process | ≥ 0.75 のみ実行（SQLフィルタ） |
| content_multiplier | ≥ 0.60 + AI clicheなし → 承認キュー投入 |

---

## 第8章 9層ループ防止壁

| Layer | 名称 | 条件 | アクション |
|-------|------|------|-----------|
| 1 | Step Counter | 50ステップ/ゴール | FORCE_STOP |
| 2 | Cost Guard | 日次予算90% | FORCE_STOP |
| 3 | Error Repeat | 同一エラー5回 | FORCE_STOP |
| 4 | Value Guard | value_justification未提供/空 | SKIP（V26修正: None→ブロック） |
| 5 | Time Guard | 2時間超過 | FORCE_STOP |
| 6 | Budget Guard | 月次予算90% | FORCE_STOP |
| 7 | Semantic Loop | 直近3アクション類似度 > 0.85 | FORCE_STOP |
| 8 | Quality Plateau | 品質改善なし3回連続 | SKIP |
| 9 | Cross-Goal | 同一API/ノード/予算競合 | INTERFERENCE_STOP |

---

## 第9章 SNS運用アーキテクチャ

### 9.1 4プラットフォーム

| プラットフォーム | アカウント | 投稿/日 | 文字数上限 |
|----------------|-----------|---------|-----------|
| X | @Sima_daichi（島原） | ~7本 | 280 |
| X | @syutain_beta | ~3本 | 280 |
| Bluesky | SYUTAINβ | ~5本 | 300 |
| Threads | 島原大知 | ~3本 | 500 |

### 9.2 投稿フロー

```
scheduler（22:00-23:30 JST）
    ↓
sns_batch.py（4プラットフォーム一括生成）
    ↓
7軸品質スコアリング + ハードフェイルチェック
    ↓
≥ 0.75 → posting_queue（時間分散投稿）
0.60-0.74 → pending_review（人間レビュー）
< 0.60 → rejected
    ↓
posting_queue_process（毎分実行）
    ↓
最終NGチェック + 重複チェック → 投稿実行
```

### 9.3 2アカウント戦略
- **島原大知 : SYUTAINβ = 7:3**（人が先、構造が後）
- 同日同テーマ: 島原が先に投稿 → SYUTAINβが構造的裏付け

---

## 第10章 情報収集パイプライン

### 10.1 収集フロー

```
keyword_generator → 検索キーワード生成
    ↓
info_pipeline → Jina Reader/Tavily で収集
    ↓
intel_items テーブル（importance_score付き）
    ↓
intel_reviewer → LLM評価 → actionable/reference/noise分類
    ↓
intel_digest → エージェント別ダイジェスト生成（毎日07:00 JST）
    ↓
agent_context → 各エージェントが参照
```

### 10.2 V26.1修正済み
- ✅ info_pipeline INSERT時にreview_flagを自動設定（importance_score≥0.5→"reviewed"、<0.5→"raw"）
- ✅ content_pipeline._load_intel_themes()のカラム名修正（status→review_flag、relevance_score→importance_score）
- ✅ intel_digest.for_competitive にcompetitive/booth/note.com情報をルーティング
- ✅ Plannerがintel_contextをタスク計画プロンプトに注入

### 10.3 残存課題
- intel_digest.for_quality は未実装（verifierへのintel未提供）
- intel_reviewer実行頻度を上げるとactionable分類が増える（現在は控えめ）

---

## 第11章 収益化アーキテクチャ

### 11.1 収益目標
- **12ヶ月以内:** 月収100万円（最低）
- **設計上限:** 300〜400万円/月

### 11.2 収益ストリーム（8本柱）

| ストリーム | 実装状態 | 課題 |
|-----------|---------|------|
| Booth（入口商品 ¥980-¥2,980） | パイプライン構築済み、商品0 | 最優先: 初出品が必要 |
| Stripe直販（¥5,000+） | API接続済み | 商品未作成 |
| note有料記事 | ドラフト自動生成中 | 公開・課金設定未実施 |
| noteメンバーシップ | 未実装 | Phase 2以降 |
| BtoB相談 | 経路設計済み | リード獲得前 |
| 暗号通貨自動取引 | CryptoTraderクラス実装済み | 未統合（呼び出し元なし） |
| Micro-SaaS | 未実装 | Phase 3以降 |
| アフィリエイト | 未実装 | Phase 3以降 |

### 11.3 現在の収益: ¥0
revenue_linkage テーブル: 0行。商品が存在しないため収益化不可。

---

## 第12章 Discord統合

### 12.1 チャットボット機能（V26.1大幅強化）
- LLMベースの対話（Haiku/DeepSeek/Nemotron切替）
- **全チャットにシステム状態を自動注入** — LLMが常に正確な状況を把握
- ACTIONタグシステム: [ACTION:status_check], [ACTION:persona_check]等
- Brain-β → Brain-α(Claude Code) 直接指示送信機能
- 自動修復失敗時のBrain-αエスカレーション

### 12.2 システム状況報告（V26.1: LLM注入型）

**全チャット応答にシステム状態を自動注入（chat_agent._handle_general）:**
- 目標・タスク状況（稼働/実行中/待機/完了/失敗）
- 承認キュー件数
- LLMコスト（回数・金額）
- 24h情報収集件数
- エラーサマリー
- SNS投稿数
- 予算消化率（日次/月次）
- ノード稼働状況（NATS ping）
- パワーモード（夜間/日中 + JST時刻）

**クイックステータス（全チャットに付加）:**
- SNS投稿数、24hエラー数、コスト、ノード状態、承認待ち
- brain_handoff pending数、auto_fix 24h件数、content_pipeline最新状態

**フルレポート（[ACTION:status_check]トリガー、V26で16項目に拡張）:**

| # | 項目 | ソース |
|---|------|--------|
| 1 | ノード状態 | node_state |
| 2 | 本日のゴール | goal_packets |
| 3 | 本日のタスク | tasks |
| 4 | LLM使用量・コスト | llm_cost_log |
| 5 | SNS投稿状態 | posting_queue |
| 6 | 提案状態 | proposal_history |
| 7 | 情報収集 | intel_items |
| 8 | 直近エラー | event_log |
| 9 | 承認待ち | approval_queue |
| 10 | brain_handoffキュー | brain_handoff |
| 11 | claude_code_queue | claude_code_queue |
| 12 | 自動修復ログ(24h) | auto_fix_log |
| 13 | 相互評価結果(7日) | brain_cross_evaluation |
| 14 | note品質レビュー(7日) | note_quality_reviews |
| 15 | persona_memory統計 | persona_memory |
| 16 | posting_queue詳細 | posting_queue |

---

## 第13章 Web UI

### 13.1 技術スタック
- Next.js 16 + React 19 + Tailwind CSS v4
- PWA（Serwist）
- JWT認証
- 10秒ポーリング（ダッシュボード）/ 5秒ポーリング（Agent Ops）

### 13.2 ページ構成（14ページ）

| ページ | 機能 |
|--------|------|
| ダッシュボード | KPI、ノード状態、Brain-αレビュー、提案一覧、成果物一覧 |
| チャット | WebSocket対話、ゴール投入 |
| タスク | フィルタ付きタスク一覧、詳細モーダル、推論トレース |
| 提案 | 承認キュー管理、提案一覧 |
| タイムライン | ゴール別時系列ビュー |
| Agent Ops | NATS状態、LoopGuard、イベントログ、Brain-αフェーズ |
| Brain-α | セッション、ペルソナ統計、ハンドオフ、相互評価 |
| ノード制御 | ノード詳細、CHARLIE Ubuntu/Win11切替 |
| 収益 | 収益サマリー、履歴 |
| モデル | モデル使用統計 |
| 成果物 | 品質フィルタ付き成果物ブラウザ |
| 情報収集 | intel_items一覧 |
| 設定 | 予算、チャットモデル、Discord設定 |

---

## 第14章 セキュリティ

### 14.1 アクセス制御
- Web UI: JWT認証（24h有効期限）
- API: Bearer Token必須
- Discord: ペアリングベース（access.json管理）

### 14.2 安全装置
- safety_check.py（PreToolUse）: .env/start.sh書き込み防止、破壊コマンドブロック
- auto_log.py（PostToolUse）: 全ファイル変更を記録
- ApprovalManager: SNS投稿・商品公開・価格設定・暗号通貨取引は承認必須
- EmergencyKill: 50ステップ/日次予算90%/同一エラー5回で強制停止

### 14.3 persona_memoryのtaboo
- category='taboo'のpersona_memoryエントリは絶対違反禁止
- 全コンテンツ生成前にpersona_bridge経由でtabooを参照

---

## 第15章 自動修復（Self-Healing）

### 15.1 修復フロー（V26: 検証付き）

```
self_heal_check（5分間隔）
    ↓
各ノードヘルスチェック（HTTP + SSH）
    ↓
異常検知 → 修復戦略選択
    ↓
修復実行 → 5秒待機 → 再チェック
    ↓
verified / failed → auto_fix_logに記録
    ↓
cross_evaluator（24h後）→ 修復効果評価
    ↓
apply_cross_evaluation_feedback → 低成功率戦略を警告
```

---

## 第16章 突然変異エンジン（第24章準拠）

設計書V25の仕様に厳密に従い実装。

- 物理ノイズ + 人間の直感をシードとする
- 不可逆蓄積型の変異をSQLCipher暗号化SQLiteに保存（DELTAのみ）
- 変異の発生をログに記録しない
- 変異パラメータをUIに表示しない
- Capability Auditに含めない
- 9層ループ防止壁・承認フロー・Emergency Killのコードには一切干渉させない
- try-exceptで完全隔離

---

## 第17章 フェーズロードマップ

### 17.1 Phase 1（現在位置: 完了）

| 項目 | 状態 |
|------|------|
| 4PC全稼働 | ✅ |
| Web UI | ✅ |
| 自律ループ（Perceive→Stop） | ✅ |
| ブラウザ4層 | ✅ |
| SNS自動投稿 | ✅（4プラットフォーム） |
| 品質スコアリング | ✅（7軸） |
| LoopGuard 9層 | ✅ |
| Brain-α | ✅ |
| Discord統合 | ✅ |
| 収益 | ❌ ¥0 |

### 17.2 Phase 2（次期目標、V26.1更新）

| 項目 | 優先度 | 状態 |
|------|--------|------|
| 初商品出品（Booth ¥980） | 最高 | 未着手 |
| note有料記事公開 | 高 | ドラフト自動生成中 |
| ~~agents層DBプール統合完了~~ | ~~高~~ | ✅ V26.1で完了 |
| content_pipeline → 承認 → 投稿 接続 | 高 | 新規 |
| proposal_engine → commerce_tools 接続 | 高 | 新規 |
| browser_ops 4層戦略実装 | 中 | Jina単層のみ |
| MCP SDK実装 | 中 | 未着手 |
| crypto_tools統合 | 低 | 後回し |

### 17.3 Phase 3-4（中長期）

| 月 | マイルストーン | 月収目標 |
|----|-------------|---------|
| 4-5 | Booth+note初収益、暗号通貨取引開始 | ¥5〜20万 |
| 6-7 | Stripe直販、メンバーシップ | ¥20〜50万 |
| 8-9 | BtoB、Micro-SaaS | ¥50〜100万 |
| 10-12 | 全ストリーム最適化 | ¥100〜250万 |

---

## 第18章 既知の問題と優先対応事項（V26.1更新）

### 18.1 クリティカル

| # | 問題 | 影響 | 対応方針 |
|---|------|------|---------|
| 1 | 収益¥0（商品未出品） | 事業目標未達 | Booth初商品を最優先で出品 |
| 2 | ~~agents層に独自DBプール9個残存~~ | ~~PostgreSQL接続枯渇リスク~~ | ✅ **V26.1で全統合完了** |

### 18.2 V26.1で解決済み

| # | 問題 | 対応 |
|---|------|------|
| 2 | DBプール分散 | ✅ 全モジュールdb_pool.get_connection()統合 |
| 6 | discord_notify 5関数未使用 | ✅ 全5関数接続済み（executor/approval/scheduler/emergency_kill） |
| 7 | intel_digest for_competitive常に空 | ✅ competitive/booth/note.comルーティング追加 |
| 8 | planner persona_context無視 | ✅ persona_context + intel_context注入 |
| 13 | capability_audit ensure_future | ✅ create_taskに修正 |
| - | social_tools/commerce_tools NATSタイムアウト | ✅ ApprovalManager直接呼び出しに修正 |
| - | llm_router avoid_models 2/10パスのみ | ✅ 全パスでチェック + モデル名修正 |
| - | model_quality_log二重書き込み | ✅ learning_managerに一元化 |
| - | content_multiplier X投稿未キュー | ✅ 全プラットフォーム承認キュー投入 |
| - | executor goal_packet欠落 | ✅ 全メソッドに伝播 |
| - | app.py Feature Flags Path未import | ✅ 修正済み |
| - | learning_manager updated_at不存在 | ✅ クエリから除去 |

### 18.3 高優先度（未解決）

| # | 問題 | 対応方針 |
|---|------|---------|
| 3 | content_pipeline → 承認 → 投稿の接続切れ | content_pipeline出力をapproval_queueに投入 |
| 4 | proposal_engine → commerce_toolsの接続切れ | 提案承認後のcommerce実行ハンドラー |
| 5 | mcp_manager完全未統合（0コールサイト） | MCP SDK実装 or app.py startup統合 |
| 6 | crypto_tools完全未統合（0コールサイト） | scheduler接続 or アーカイブ |
| 7 | browser_ops 4層戦略未実装（Jina単層のみ） | Playwright/Stagehand/ComputerUse統合 |
| 8 | self_healer → cross_evaluatorフィードバック片道 | 修復戦略の適応的選択 |
| 9 | cross_goal_detector メモリ内のみ（再起動で消失） | PostgreSQL永続化 |

### 18.4 中優先度

| # | 問題 |
|---|------|
| 10 | BRAVOノード ReadTimeout（慢性的、毎日発生） |
| 11 | DELTA typing_extensions バージョン不整合 |
| 12 | night_batchのトピック重複 |
| 14 | node_router._charlie_win11 デッドフラグ |
| 15 | discord_notify._recent_notifications 無制限成長 |
| 16 | ArtifactStorage未使用（PG/SQLiteスキーマ不整合） |
| 17 | strategy_file読み込み4箇所重複（統合すべき） |
| 18 | content_multiplier 6 LLM呼び出しが直列（並列化可能） |

---

## 第19章 監視・運用

### 19.1 スケジューラージョブ（55ジョブ）

**SNS（夜間バッチ 22:00-23:30 JST）:**
sns_batch × 4、bluesky_auto_draft、x_auto_draft_syutain、x_auto_draft_shimahara、threads_auto_draft

**定期（5分〜日次）:**
posting_queue_process(毎分)、anomaly_detection(5分)、node_health_check(5分)、self_heal_check(5分)、redispatch_orphan_tasks(5分)、heartbeat(30秒)

**日次:**
daily_proposal(07:00)、generate_intel_digest(07:00)、info_pipeline(3時間)、cost_forecast(6時間)、generate_operation_log(23:55)、update_system_state(30分)、**daily_summary_notify(20:30 JST)**、note_quality_check(30分)

**週次:**
weekly_learning_report(日曜21:00)、weekly_proposal(月曜07:00)、weekly_product_candidate(金曜23:15)、competitive_analysis(火曜/金曜)

### 19.2 ヘルスチェック
- `/health` エンドポイント（FastAPI）
- Next.js :3000 HTTP応答確認
- ノード別SSH + nvidia-smi
- Ollama APIレスポンス確認
- NATS JetStreamクラスタ状態

---

## 第20章 CLAUDE.md 絶対ルール（V26更新: 26条）

1. 設計書（本V26）の設計を最優先する
2. V25はV20〜V24を再構成した原典であり、過去設計を消してはならない
3. 各Stepを完了してから次に進む
4. 同じ処理を3回以上繰り返す場合は停止してエスカレーション
5. LLM呼び出し前に必ずchoose_best_model_v6()
6. 2段階精錬（ローカル→API）を標準パイプライン
7. 全ツール呼び出しはtry-exceptで囲みlog_usage()
8. .envの内容をログに出力しない。APIキーをハードコードしない
9. 設定値はハードコードせずDBまたは.env
10. 戦略ファイル（strategy/）を参照してからコンテンツ生成
11. SNS投稿・商品公開・価格設定・暗号通貨取引はApprovalManager経由
12. 重要な判断はDiscord + Web UIで通知
13. ローカルLLM配置を正確に守る
14. macOS (ALPHA) では declare -A を使わない
15. タスクをPostgreSQLに記録してからLoopGuard 9層で監視
16. Emergency Kill条件を厳守
17. ノードが使えない場合は必ずフォールバック
18. 全ての中間成果物をDBに保存
19. NATSメッセージングでノード間通信
20. MCPサーバー接続は動的に確認し、代替手段で処理継続
21. 4台のPCをPhase 1から全て稼働
22. 突然変異エンジンは設計書仕様に厳密従い実装（隔離ルール遵守）
23. Brain-αはpersona_memoryの価値観を参照してから判断・生成
24. 新しい判断基準はdaichi_dialogue_logに記録
25. セッション終了時にmemory_manager.save_session_memory()を必ず実行
26. 島原大知のtabooカテゴリは絶対に違反しない

---

## 付録A: NATSサブジェクト一覧

| サブジェクトグループ | 用途 |
|-------------------|------|
| task.> | タスク配信・結果報告 |
| agent.> | エージェントハートビート・状態 |
| proposal.> | 提案生成・承認 |
| approval.> | 承認リクエスト・レスポンス |
| monitor.> | 監視リクエスト |
| log.> | ログストリーム |
| browser.> | ブラウザ操作 |
| computer.> | Computer Use操作 |
| intel.> | 情報収集タスク |

## 付録B: 環境変数一覧

| 変数 | デフォルト | 用途 |
|------|-----------|------|
| DATABASE_URL | postgresql://localhost:5432/syutain_beta | PostgreSQL接続 |
| THIS_NODE | alpha | ノード名 |
| DAILY_BUDGET_JPY | 80 | 日次API予算 |
| MONTHLY_BUDGET_JPY | 1500 | 月次API予算 |
| MONTHLY_INFO_BUDGET_JPY | 15000 | 情報収集月次予算 |
| BUDGET_ALERT_WARN | 0.8 | 警告閾値 |
| BUDGET_ALERT_STOP | 0.9 | 停止閾値 |
| DISCORD_WEBHOOK_URL | - | Discord通知 |
| NATS_URL | nats://localhost:4222 | NATSサーバー |
| JWT_SECRET | - | Web UI認証 |

## 付録C: 品質閾値マトリクス

| チェックポイント | 閾値 | アクション |
|----------------|------|-----------|
| Verifier成功判定 | ≥ 0.50 | status="success" |
| 2段階精錬トリガー | < 0.70 | API精錬実行 |
| SNS自動承認 | ≥ 0.75 | Tier 2自動承認 |
| SNSレビュー送り | 0.60-0.74 | pending_review |
| SNS却下 | < 0.60 | rejected |
| content_multiplier | ≥ 0.60 + no AI cliche | 全プラットフォーム承認キュー投入（V26.1: X投稿追加） |
| ハードフェイル(M) | 簡体字直接検出 | ペナルティ0.40 |
| ハードフェイル(M) | 仮名なしCJK検出 | ペナルティ0.30 |
| ハードフェイル(N) | 島原大知名前誤読 | ペナルティ0.50 |
| ハードフェイル(N2) | 企業名ハルシネーション | ペナルティ0.40 |
| ハードフェイル(O) | AI自己開示 | ペナルティ0.40 |
| ハードフェイル(P) | 太字コロン3箇所以上 | ペナルティ0.15 |
