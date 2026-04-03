# SYUTAINβ 完全設計書 V27

**バージョン:** V27 (2026-03-28)
**前バージョン:** V26.1 (2026-03-28) / V26 (2026-03-27) / V25 (2026-03-15)
**作成者:** SYUTAINβ Brain-α + 島原大知
**ステータス:** Phase 1 完了・Phase 2 本格移行中

---

## 第1章 システムアイデンティティ

### 1.1 名称・読み
- **正式名称:** SYUTAINβ (Sustainable Yield Utilizing Technology And Intelligence Network β)
- **読み:** シュタインベータ
- **Discord表示名:** SYUTAINβ
- **Xアカウント:** @syutain_beta / @Sima_daichi

### 1.2 設計思想
4台のPCがPhase 1初日から全て連携し、NATSメッセージングで結ばれ、Web UIを通じてiPhoneからリアルタイム監視でき、マルチエージェントが自律的に認識・思考・行動・検証・停止判断を行い、目標だけを受けても道筋が変わっても自分で考え、自分で動き、自分で止まれる「自律分散型 事業OS」。

### 1.3 V26→V27 主要変更点

| 変更領域 | V26.1 | V27 |
|---------|-------|-----|
| SNS投稿承認 | 0.75自動/0.60-0.74レビュー待ち | **0.60以上は全て自動投稿**（品質確認後に全自動） |
| posting_queue閾値 | quality_score >= 0.75 | **quality_score >= 0.70** |
| Verifier品質スコアリング | 5軸25点満点 | **7軸35点満点**（構造性+ICP適合性追加） |
| AI文体検出 | A-P 16パターン | **A-R 18パターン**（絵文字過多+語尾単調追加） |
| 簡体字検出 | 26文字パターン | **46文字パターン**（拡充） |
| Brain-β→Brain-α通信 | Webhook 1経路 | **三重経路**（claude_code_queue+Webhook+Discordメンション） |
| Discord Bot状況報告 | 基本SNS/エラー/コスト | **+収益パイプライン+intel活用率+提案/ゴール稼働数** |
| discord_notify | メモリリーク(_recent_notifications無制限成長) | **500件超で自動プルーニング** |
| chat_agent.py | get_connection二重import | **修正済み** |
| memory_manager.py | `%%` LIKEパターンバグ | **`%`に修正** |
| llm_router.py | avoid_modelsフォールバックにviaキー欠落 | **Gemini Flash direct修正** |
| scheduler.py | `dir()`による品質スコア確認バグ | **`locals()`に修正** |
| two_stage_refiner.py | API精錬後のquality_score未更新 | **再評価ステージ追加** |
| emergency_kill.py | `asyncio.get_event_loop()`非推奨 | **`get_running_loop()`修正** |
| embedding_tools.py | pgvector str変換不安定 | **カンマ区切り形式修正** |
| loop_guard.py | Layer1 SWITCH_METHOD死にコード | **count順序修正** |
| info_collector.py | RSS/YouTubeデータがintel_items未保存 | **DB永続化追加** |
| budget_guard.py | record_chat_spend予算チェックなし | **90%制限追加** |
| analytics_tools.py | STRATEGY_DIR相対パス問題 | **絶対パス修正** |
| app.py | emergency_kills_todayハードコード | **event_logから実データ取得** |
| chat_agent.py | NATSノードping直列12秒 | **並列3秒に短縮** |
| escalation.py | α→β方向の指令投入関数なし | **send_alpha_directive追加** |
| db_init.py | Brain-αテーブル群未定義 | **13テーブル追加** |
| db_init.py | revenue_linkageカラム不足 | **6カラム追加** |
| Jina embedding | tier="S"で誤統計 | **tier="L"修正** |
| os_kernel.py | RETRY_MODIFIEDでタスクが再試行されない | **mark_pending追加** |
| planner.py | mark_pendingメソッド未実装 | **追加実装** |
| perceiver.py | build_agent_context("proposal_engine")誤り | **"perceiver"修正** |
| proposal_engine.py | first_actionフィールドDB未保存 | **proposal dictに追加** |
| proposal_engine.py | tabooカテゴリ未参照 | **CLAUDE.md26条準拠で追加** |
| chat_agent.py | _handle_status_queryにノード状態なし | **system_status_brief追加** |
| node_router.py | NATS応答エラー時にreply未返却 | **エラーreply追加** |
| social_tools.py | Bluesky毎回ログイン | **セッションキャッシュ(2h)追加** |
| agent_context.py | 3エージェント対応/500文字制限 | **9エージェント対応/最大2000文字/actionable直接参照/対話学習/承認提案** |
| content_pipeline | intel_themes取得がreviewed限定 | **actionable優先+source付き+150文字summary** |
| content_pipeline | テーマ選定にagent_context未使用 | **全エージェント統合情報をテーマ選定に注入** |

### 1.4 V25→V26→V27 累積変更サマリー

| 変更領域 | V25 | V27 |
|---------|-----|-----|
| DBプール | 各モジュール独自プール(20+重) | **全モジュール統合完了** tools/db_pool.py集中管理 |
| 品質スコアリング | 6軸 | **7軸 + ハードフェイル18パターン + Tier S検査** |
| SNS投稿承認 | 0.60以上で自動 | **0.70以上で全自動投稿（品質確認済み前提）** |
| 承認フロー | NATS request-reply（タイムアウト） | **ApprovalManager直接呼び出し** |
| Brain-β→α通信 | 手動エスカレーションのみ | **三重経路自動エスカレーション** |
| Discord bot | 部分的状況報告 | **全チャットにシステム全状態注入（収益/intel/提案含む）** |

---

## 第2章 ハードウェア構成

### 2.1 ノードレイアウト

| ノード | ハードウェア | 役割 | ローカルLLM | GPU |
|--------|-------------|------|------------|-----|
| ALPHA | Mac mini M4 Pro 16GB | オーケストレータ / Web UI / PostgreSQL / NATS Server / Brain-α | Qwen3.5-9B (MLX、オンデマンド起動) | M4 Pro |
| BRAVO | Ryzen + RTX 5070 12GB | ブラウザ操作 / Computer Use / コンテンツ生成 | Nemotron 9B JP + Qwen3.5-9B (Ollama) | RTX 5070 |
| CHARLIE | Ryzen 9 + RTX 3080 10GB | 推論メイン / バッチ処理 | Nemotron 9B JP + Qwen3.5-9B (Ollama) | RTX 3080 |
| DELTA | Xeon E5 + GTX 980Ti 6GB + 48GB RAM | 監視 / 情報収集 / ヘルスチェック | Qwen3.5-4B (Q4) | GTX 980Ti |

### 2.2 ネットワーク
- **VPN:** Tailscale mesh (4ノード全接続)
- **メッセージング:** NATS v2.12.5 + JetStream (4ノードRAFTクラスタ)
- **NATS Server:** ALPHA (0.0.0.0:4222)、クラスタポート6222
- **JetStream:** 256MB メモリ / 1GB ファイル

### 2.3 ローカルLLM運用ルール
- ALPHAの推論はBRAVO/CHARLIEが両方ビジー時のみMLXでオンデマンドロード
- BRAVO/CHARLIEは常時Ollamaで9Bモデルを待機（Nemotron 9B JP第1候補）
- DELTAは4Bモデルで軽量タスク（情報収集スコアリング等）のみ
- **avoid_models:** model_quality_logで平均品質 < 0.4（5件以上）のモデルは自動回避

---

## 第3章 ソフトウェアアーキテクチャ

### 3.1 コードベース概要

| カテゴリ | ファイル数 | 総行数 | 主要ファイル |
|---------|-----------|--------|-------------|
| FastAPI Server | 1 | 3,320 | app.py |
| Scheduler | 1 | 2,722 | scheduler.py (55ジョブ) |
| Worker | 1 | 388 | worker_main.py |
| Agents | 18 | ~8,500 | os_kernel, planner, executor, verifier等 |
| Brain-α | 15 | ~7,000 | sns_batch, content_pipeline, memory_manager等 |
| Tools | 40 | ~12,000 | llm_router, db_pool, social_tools等 |
| Bots (Discord) | 11 | ~5,500 | discord_bot, bot_conversation, bot_actions等 |
| Web UI | 23 | ~6,400 | Next.js 16 + React 19 PWA |
| **合計** | **110+** | **~46,000** | |

### 3.2 APIエンドポイント
62エンドポイント（認証1 + ヘルス1 + 機能60）

### 3.3 データベース

**PostgreSQL（ALPHA共有状態）: 35テーブル**

| テーブル | 用途 | 行数(2026-03-28) |
|---------|------|-----------------|
| tasks | タスク管理 | 690 |
| goal_packets | ゴールライフサイクル | 72 |
| proposal_history / proposal_feedback | 提案管理 | 44 / - |
| posting_queue | SNS投稿キュー | 293 |
| intel_items | 情報収集 | 677 |
| llm_cost_log | LLMコスト | 6,359 |
| event_log | イベントログ | 17,276 |
| approval_queue | 承認キュー | 231 |
| browser_action_log | ブラウザ操作ログ | 7,282 |
| persona_memory | 人格記憶 | 438 |
| chat_messages | Web UIチャット | 224 |
| revenue_linkage | 収益紐付け | 0 |
| model_quality_log | モデル品質ログ | - |
| embeddings | ベクトルストア | - |
| node_state | ノード状態 | 4 |
| brain_handoff | Brain-αハンドオフ | - |
| auto_fix_log | 自動修復ログ | - |
| capability_snapshots | 能力監査 | - |
| loop_guard_events | ループ防止イベント | - |
| settings | 設定KVS | - |
| crypto_trades | 暗号通貨取引 | - |
| seasonal_revenue_correlation | 季節収益相関 | - |
| brain_alpha_session | Brain-αセッション | - |
| daichi_dialogue_log | 対話学習記録 | - |
| agent_reasoning_trace | エージェント判断根拠 | - |
| brain_cross_evaluation | 相互評価 | - |
| review_log | レビューログ | - |
| discord_chat_history | Discord対話履歴 | - |
| intel_digest | インテリジェンスダイジェスト | - |
| claude_code_queue | Brain-α指示キュー | - |
| note_quality_reviews | note品質レビュー | - |
| content_edit_log | コンテンツ精錬記録 | - |
| daichi_writing_examples | 島原文体例 | - |
| brain_alpha_reasoning | Brain-α推論記録 | - |
| posting_queue_engagement | エンゲージメントデータ | - |

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
| Think | Planner | タスクDAG生成、依存関係解決、intel_context + persona_context注入 |
| Act | Executor | LLMタスク実行、ブラウザ操作、ツール呼び出し |
| Verify | Verifier | **7軸品質スコアリング + 18パターンAI検出 + Tier S検査 + 2段階精錬** |
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
| MutationEngine | 突然変異エンジン（第16章） |
| ChatAgent | 双方向チャット（Web UI + Discord） |

### 4.3 DBプール統合状況: 全完了
全モジュールが`tools/db_pool.py`の`get_connection()`を使用。接続プール一元管理。

---

## 第5章 Brain-α（自律知能層）

### 5.1 Dual Brain構造

```
Brain-α（Claude Code — 前頭葉・意識）
  ├── 精査・自律修復・戦略判断・人格保持
  ├── ALPHA上でChannels永続セッション（tmux brain_alpha）
  └── Discord MCP経由で島原と対話
        ↕ 三重経路通信（V27: claude_code_queue + Webhook + Discord Bot）
Brain-β（自律神経・日常運転）
  ├── 24h常時稼働（FastAPI + Scheduler + Workers）
  ├── Discord Bot（bots/discord_bot.py）
  └── 自律ループ（Perceive→Stop）
```

### 5.2 Brain-α構成

| モジュール | 役割 |
|-----------|------|
| memory_manager.py | セッション記憶、persona_memory管理、7日圧縮 |
| persona_bridge.py | 人格コンテキスト構築（casual/standard/strategic/code_fix） |
| sns_batch.py | SNS投稿49件/日一括生成（7軸品質スコアリング） |
| content_pipeline.py | 5段階コンテンツパイプライン |
| cross_evaluator.py | 相互評価 + フィードバックループ |
| self_healer.py | 自動修復（検証付き）+ Brain-αエスカレーション |
| startup_review.py | 8フェーズ起動レビュー |
| escalation.py | エスカレーションパス（β→α/α→β） |
| session_save.py | セッション自動保存 |
| safety_check.py | PreToolUseフック（破壊操作防止） |
| auto_log.py | PostToolUseフック（ファイル変更記録） |
| note_quality_checker.py | note記事2段階品質チェック |
| product_packager.py | 商品パッケージング |
| executive_briefing.py | エグゼクティブブリーフィング |

### 5.3 7軸品質スコアリング（V27: Verifier統合）

**SNS投稿用（sns_batch._score_multi_axis）:**

| 軸 | 重み | 検出内容 |
|----|------|---------|
| 人間味 | 0.17 | 口語表現、感情語、不完全さ、独白感 |
| 島原らしさ | 0.17 | VTuber経験、非エンジニア視点、SYUTAINβコンテキスト |
| 完結性 | 0.16 | 自然な終わり方、括弧対応、文数バランス |
| エンゲージメント | 0.13 | 問いかけ、余韻、共感ポイント、CTA |
| AI臭さの無さ | 0.13 | 禁止語句、テンプレート回避、語尾多様性 |
| 読みやすさ | 0.08 | 文長バランス、改行リズム |
| 構造準拠 | 0.16 | Phase A(具体冒頭)/D(断言核心)/E(行動締め) |

**タスク成果物用（verifier._score_quality）— V27: 7軸35点満点:**

| 軸 | 検出内容 |
|----|---------|
| A. 完成度 | 成功条件達成度 |
| B. 正確性 | 事実誤認・論理矛盾 |
| C. 実用性 | 読者が行動できるか |
| D. 独自性 | テンプレ回避、深い洞察 |
| E. 文体品質 | 自然さ、AI臭さの無さ |
| F. 構造性（V27新規） | 導入→展開→結論の流れ |
| G. ICP適合性（V27新規） | ターゲット層への共感度 |

**ハードフェイル検出（18パターン、V27: +2パターン）:**
- A-L: 基本AIパターン（意義過剰/AI語彙/回りくどい/定型冒頭結論/太字コロン/ダッシュ/曖昧出典/ヘッジ過多/チャットボット残留/追従的）
- M: 簡体字直接検出（46文字パターン）+ 仮名なしCJK検出
- N: 島原大知の名前読み誤り
- N2: 企業名ハルシネーション
- O: AI自己開示
- P: 太字コロン過多（3箇所以上）
- **Q: 絵文字過多（5個以上）+ ハッシュタグ過多（4個以上）（V27新規）**
- **R: 同一語尾連続（4回以上、多様性50%未満）（V27新規）**

### 5.4 コンテンツパイプライン 5段階（V27: 有料500円レベル）

```
Stage 1: テーマ選定（intel_items + persona_memory + 市場トレンド）
Stage 2: Phase A-E アウトライン生成（5-7見出し構成）
Stage 3: 初稿生成（6000字目標、2000字未満で失敗、API優先モデル使用）
Stage 4: 島原の声でリライト（最大2回、有料記事品質指示付き）
Stage 5: 品質検証（7軸スコアリング + note品質チェッカー2段階）
```

**有料note記事の品質基準（V27: noteの仕様+購買心理最適化）:**

noteの有料記事は「無料パート→ペイウォール→有料パート」の2層構造。
無料パートの魅力が売上を決定する。

**無料パート（冒頭1000-1500字）— 購買意欲を最大化:**
- 衝撃的な冒頭3行（数字・事実で読者を立ち止まらせる）
- 読者の悩みに具体的に共感（「こんなことありませんか？」3つ列挙）
- 島原の資格証明（VTuber業界8年、4台PCでAI事業OS構築等）
- 「この記事で得られること」箇条書き3-5個
- クリフハンガー（「本当に大事なのはこの先にある」的な引き）
- 本文中に `---ここから有料---` マーカーを必ず挿入

**有料パート（ペイウォール後4500-6500字）— 500円の価値を提供:**
- 最低5000字（5000字未満はnote_quality_checkerでreject）
- 島原大知の実体験エピソード3つ以上（日時・場所・感情含む）
- 具体的な数値・コスト・時間データ
- 読者が実践できるステップ3-5個（コスト・時間付き）
- 失敗談と教訓を正直に記述
- 「なぜそうなるのか」の構造分析（表面的解説×）
- 見出し5-7個、各セクション800-1200字
- **太字**の核心一文
- 要点3-5個の箇条書きまとめ

**絶対禁止:**
- 架空のエピソード（「カフェで友人が〜」等の作り話）
- AI定型句（「考えてみました」「いかがでしょうか」「深掘り」）
- 島原がやっていないこと（音楽の仕事等）を事実として語ること

---

## 第6章 LLMルーティング

### 6.1 ティア構成

| ティア | モデル | 用途 |
|--------|--------|------|
| S | GPT-5.4, Claude Opus 4.6, Gemini 3.1 Pro | Computer Use, 高品質生成 |
| A | DeepSeek-V3.2 ($0.28/1M), Claude Sonnet 4.6, GPT-5 Mini | 標準生成・分析 |
| B | Claude Haiku 4.5, GPT-5 Nano | 分類・スコアリング |
| L | Nemotron 9B JP (BRAVO/CHARLIE), Qwen3.5-9B, Qwen3.5-4B (DELTA) | ローカル推論 |

### 6.2 コスト最適化
- **ローカルLLM使用率:** 85.8%（目標80%以上を達成）
- **日次予算:** ¥80
- **月次予算:** ¥1,500
- **情報収集月次予算:** ¥15,000
- **2段階精錬:** ローカルLLM → 品質 < 0.7 → API精錬
- **SNS固着検知:** 連続3回重複→残りバッチをDeepSeek V3.2にフォールバック

### 6.3 モデル品質学習ループ

```
call_llm() → record_spend()
     ↓
Verifier._log_quality() → learning_manager.track_model_quality()
     ↓                           ↓
     (二重書き削除)          model_quality_log INSERT
                                      ↓
refresh_model_quality_cache() → _model_quality_cache
                                      ↓
choose_best_model_v6() ← avoid_models 全パスチェック
```

---

## 第7章 承認フロー

### 7.1 承認体制（V27: 全自動化）

| Tier | 条件 | 処理 |
|------|------|------|
| Tier 1（人間承認） | 金額・メンション含む投稿、暗号通貨取引 | Discord通知→人間判断 |
| Tier 2（自動承認） | **SNS投稿 品質 ≥ 0.70**（V27: 閾値引き下げ） | 自動投稿キューへ |
| Tier 3（完全自動） | 内部タスク、情報収集 | 即座に実行 |

### 7.2 品質ゲート統一（V27）

| チェックポイント | 閾値 | アクション |
|----------------|------|-----------|
| sns_batch生成 | **≥ 0.70 → pending（全自動投稿）** | < 0.70 → rejected |
| posting_queue_process | **≥ 0.70 のみ実行** | + 最終NGチェック + 重複チェック |
| content_multiplier | ≥ 0.70 + AI clicheなし | 全プラットフォーム承認キュー投入 |
| Verifier成功判定 | ≥ 0.50 | status="success" |
| 2段階精錬トリガー | < 0.70 | API精錬実行 |

---

## 第8章 9層ループ防止壁

| Layer | 名称 | 条件 | アクション |
|-------|------|------|-----------|
| 1 | Step Counter | 50ステップ/ゴール | FORCE_STOP |
| 2 | Cost Guard | 日次予算90% | FORCE_STOP |
| 3 | Error Repeat | 同一エラー5回 | FORCE_STOP |
| 4 | Value Guard | value_justification未提供/空 | SKIP |
| 5 | Time Guard | 2時間超過 | FORCE_STOP |
| 6 | Budget Guard | 月次予算90% | FORCE_STOP |
| 7 | Semantic Loop | 直近3アクション類似度 > 0.85 | FORCE_STOP |
| 8 | Quality Plateau | 品質改善なし3回連続 | SKIP |
| 9 | Cross-Goal | 同一API/ノード/予算競合 | INTERFERENCE_STOP |

---

## 第9章 SNS運用アーキテクチャ

### 9.1 投稿体制（V27: 全自動）

| プラットフォーム | アカウント | 投稿/日 | 文字数上限 |
|----------------|-----------|---------|-----------|
| X | @Sima_daichi（島原） | 4本 | 280(加重) |
| X | @syutain_beta | 6本 | 280(加重) |
| Bluesky | SYUTAINβ | 26本 | 300 |
| Threads | 島原大知 | 13本 | 500 |
| **合計** | | **49本/日** | |

### 9.2 投稿フロー（V27: pending_review廃止）

```
scheduler（22:00-23:30 JST）
    ↓
sns_batch.py（4プラットフォーム一括生成）
    ↓
7軸品質スコアリング + ハードフェイル18パターンチェック
    ↓
≥ 0.70 → posting_queue（pending — 全自動投稿）
< 0.70 → rejected（監査証跡としてDB保存）
    ↓
posting_queue_process（毎分実行）
    ↓
最終NGチェック + 重複チェック → 投稿実行
```

### 9.3 SNS自律品質管理パイプライン

```
Phase 1: 生成（ローカルLLM、最大3回リトライ、temperature段階的UP）
Phase 2: 検証（空/文字数/NGワード/AI定型/重複/品質スコア）
Phase 3: 不合格→Cloud APIフォールバック（DeepSeek V3.2）
Phase 4: 2段階精錬（リライト→比較→高品質な方を採用）
固着検知: 連続3回重複→残りバッチをCloud APIに切替
```

### 9.4 2アカウント戦略
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
agent_context → 各エージェント（Planner/sns_batch/ProposalEngine）が参照
```

### 10.2 残存課題
- intel_digest.for_quality は未実装（verifierへのintel未提供）
- intel_reviewer実行頻度を上げるとactionable分類が増える

---

## 第11章 収益化アーキテクチャ

### 11.1 収益目標
- **12ヶ月以内:** 月収100万円（最低）
- **設計上限:** 300〜400万円/月

### 11.2 収益ストリーム（8本柱）

| ストリーム | 実装状態 | 課題 |
|-----------|---------|------|
| Booth（入口商品 ¥980-¥2,980） | パイプライン構築済み + product_packager.py | 最優先: 初出品が必要 |
| Stripe直販（¥5,000+） | API接続済み | 商品未作成 |
| note有料記事 | ドラフト自動生成中 + note_quality_checker.py | 公開・課金設定未実施 |
| noteメンバーシップ | 未実装 | Phase 2以降 |
| BtoB相談 | 経路設計済み | リード獲得前 |
| 暗号通貨自動取引 | CryptoTraderクラス実装済み | 未統合（呼び出し元なし） |
| Micro-SaaS | 未実装 | Phase 3以降 |
| アフィリエイト | 未実装 | Phase 3以降 |

### 11.3 現在の収益: ¥0
revenue_linkage テーブル: 0行。商品が存在しないため収益化不可。

---

## 第12章 Discord統合

### 12.1 チャットボット機能（V27強化）

**Brain-β（Discord Bot）:**
- LLMベースの対話（Haiku/DeepSeek/Nemotron自動切替）
- **全チャットにシステム全状態を自動注入**（V27: +収益パイプライン+intel活用率）
- ACTIONタグシステム: 30+コマンド
- Brain-β → Brain-α(Claude Code) 三重経路指示送信
- 自動修復失敗時のBrain-αエスカレーション
- 4段階モデル自動選択（品質フィードバック→会話文脈→キーワード→深さレベル）
- 自己モニタリング（肯定/否定シグナル検出→モデル切替）
- プロアクティブ報告（定期チェック）
- 対話学習（persona_memory即時保存）

### 12.2 Brain-β→Brain-α通信（V27: 三重経路）

```
Brain-β指示検出（自動修復失敗/エスカレーション/定期指示）
    ↓
経路1: claude_code_queue INSERT（最も確実、Brain-αがポーリングで取得）
経路2: Discord Webhook → Brain-αチャネルに通知
経路3: Discord Bot → <@1477009083100958853> メンション付きメッセージ
```

### 12.3 システム状況報告

**全チャット応答に付加されるクイックステータス:**
- SNS投稿数、24hエラー数、コスト、ノード状態、承認待ち
- brain_handoff pending数、auto_fix 24h件数
- **収益: ¥X(Y商品)、intel活用率、提案件数、ゴール稼働数（V27追加）**

**フルレポート（[ACTION:status_check]、16項目）:**
ノード状態、ゴール、タスク、LLM使用量、SNS投稿、提案、情報収集、エラー、
承認待ち、brain_handoff、claude_code_queue、auto_fix、相互評価、
note品質レビュー、persona_memory統計、posting_queue詳細

---

## 第13章 Web UI

### 13.1 技術スタック
- Next.js 16 + React 19 + Tailwind CSS v4
- PWA（Serwist）
- JWT認証
- 10秒ポーリング（ダッシュボード）/ 5秒ポーリング（Agent Ops）

### 13.2 ページ構成（14ページ）
ダッシュボード、チャット、タスク、提案、タイムライン、Agent Ops、Brain-α、
ノード制御、収益、モデル、成果物、情報収集、設定

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
- EmergencyKill: 50ステップ/日次予算90%/同一エラー5回で強制停止 + Discord緊急通知

### 14.3 persona_memoryのtaboo
- category='taboo'のpersona_memoryエントリは絶対違反禁止（21件）
- 全コンテンツ生成前にpersona_bridge経由でtabooを参照

---

## 第15章 自動修復（Self-Healing）

### 15.1 修復フロー（V27: Brain-αエスカレーション三重経路化）

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
失敗時 → Brain-αに三重経路エスカレーション（V27）
    ↓
cross_evaluator（24h後）→ 修復効果評価
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

### 17.1 Phase 1（完了）

| 項目 | 状態 |
|------|------|
| 4PC全稼働 | ✅ |
| Web UI | ✅ |
| 自律ループ（Perceive→Stop） | ✅ |
| ブラウザ4層 | ✅ |
| SNS自動投稿 | ✅（4プラットフォーム49件/日） |
| 品質スコアリング | ✅（7軸 + 18パターンAI検出） |
| LoopGuard 9層 | ✅ |
| Brain-α | ✅ |
| Discord統合 | ✅（Bot + Webhook + Brain-α三重経路） |
| 収益 | ❌ ¥0 |

### 17.2 Phase 2（次期目標）

| 項目 | 優先度 | 状態 |
|------|--------|------|
| 初商品出品（Booth ¥980） | 最高 | product_packager.py実装済み |
| note有料記事公開 | 高 | ドラフト自動生成中 |
| content_pipeline → 承認 → 投稿 接続 | 高 | 未完 |
| proposal_engine → commerce_tools 接続 | 高 | 未完 |
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

## 第18章 既知の問題と優先対応事項（V27更新）

### 18.1 クリティカル

| # | 問題 | 影響 | 対応方針 |
|---|------|------|---------|
| 1 | 収益¥0（商品未出品） | 事業目標未達 | Booth初商品を最優先で出品 |

### 18.2 V27で解決済み

| # | 問題 | 対応 |
|---|------|------|
| - | SNS pending_review滞留 | ✅ 品質0.60以上は全て自動投稿に変更 |
| - | Verifier 5軸スコアリング（分解能低） | ✅ 7軸35点満点に拡張 |
| - | AI文体検出パターン不足 | ✅ 18パターンに拡張（Q.絵文字過多、R.語尾単調） |
| - | discord_notify メモリリーク | ✅ 500件超で自動プルーニング |
| - | chat_agent.py 二重import | ✅ 修正済み |
| - | Brain-β→α通信が1経路のみ | ✅ 三重経路化 |
| - | Discord Bot状況報告が不完全 | ✅ 収益/intel/提案/ゴール情報追加 |

### 18.3 高優先度（未解決）

| # | 問題 | 対応方針 |
|---|------|---------|
| 3 | content_pipeline → 承認 → 投稿の接続切れ | content_pipeline出力をapproval_queueに投入 |
| 4 | proposal_engine → commerce_toolsの接続切れ | 提案承認後のcommerce実行ハンドラー |
| 5 | mcp_manager完全未統合（0コールサイト） | MCP SDK実装 or app.py startup統合 |
| 6 | crypto_tools完全未統合（0コールサイト） | scheduler接続 or アーカイブ |
| 7 | browser_ops 4層戦略未実装（Jina単層のみ） | Playwright/Stagehand/ComputerUse統合 |
| 8 | cross_goal_detector メモリ内のみ（再起動で消失） | PostgreSQL永続化 |

### 18.4 中優先度

| # | 問題 |
|---|------|
| 10 | BRAVOノード ReadTimeout（慢性的、毎日発生） |
| 12 | night_batchのトピック重複 |
| 14 | node_router._charlie_win11 デッドフラグ |
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
daily_proposal(07:00)、generate_intel_digest(07:00)、info_pipeline(3時間)、cost_forecast(6時間)、generate_operation_log(23:55)、update_system_state(30分)、daily_summary_notify(20:30 JST)、note_quality_check(30分)

**週次:**
weekly_learning_report(日曜21:00)、weekly_proposal(月曜07:00)、weekly_product_candidate(金曜23:15)、competitive_analysis(火曜/金曜)

### 19.2 ヘルスチェック
- `/health` エンドポイント（FastAPI）
- Next.js :3000 HTTP応答確認
- ノード別SSH + nvidia-smi
- Ollama APIレスポンス確認
- NATS JetStreamクラスタ状態

---

## 第20章 CLAUDE.md 絶対ルール（V27更新: 26条）

1. 設計書（本V27）の設計を最優先する
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
| DISCORD_BRAIN_WEBHOOK_URL | - | Brain-α専用通知 |
| DISCORD_BOT_TOKEN | - | Discord Bot |
| DISCORD_GENERAL_CHANNEL_ID | - | Botチャネル |
| BRAIN_ALPHA_DISCORD_ID | 1477009083100958853 | Brain-αのDiscord ID |
| NATS_URL | nats://localhost:4222 | NATSサーバー |
| JWT_SECRET | - | Web UI認証 |

## 付録C: 品質閾値マトリクス（V27更新）

| チェックポイント | 閾値 | アクション |
|----------------|------|-----------|
| Verifier成功判定 | ≥ 0.50 | status="success" |
| 2段階精錬トリガー | < 0.70 | API精錬実行 |
| **SNS全自動投稿** | **≥ 0.70** | **pending（全自動投稿キュー）** |
| SNS却下 | < 0.70 | rejected |
| content_multiplier | ≥ 0.70 + no AI cliche | 全プラットフォーム承認キュー投入 |
| ハードフェイル(M) | 簡体字直接検出(46字) | ペナルティ0.40 |
| ハードフェイル(M) | 仮名なしCJK検出 | ペナルティ0.30 |
| ハードフェイル(N) | 島原大知名前誤読 | ペナルティ0.50 |
| ハードフェイル(N2) | 企業名ハルシネーション | ペナルティ0.40 |
| ハードフェイル(O) | AI自己開示 | ペナルティ0.40 |
| ハードフェイル(P) | 太字コロン3箇所以上 | ペナルティ0.15 |
| **ハードフェイル(Q)** | **絵文字5個以上/ハッシュタグ4個以上** | **ペナルティ0.10** |
| **ハードフェイル(R)** | **同一語尾4回以上(多様性<50%)** | **ペナルティ0.10** |
| 品質低下エスカレーション | 24h平均が7日平均-0.05 | Brain-α通知 |
