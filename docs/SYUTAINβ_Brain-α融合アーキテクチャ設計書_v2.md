# SYUTAINβ Brain-α融合アーキテクチャ設計書
# 2026-03-21 策定 / 2026-03-23 最終更新
# ステータス: 実装中（2026-03-24〜）

---

## 1. ビジョン

SYUTAINβにClaude Codeを「Brain-α（前頭葉・意識）」として統合し、
既存の17エージェント+34ツールが動くBrain-β（自律神経・日常運転）との
**双方向フィードバック構造**を構築する。

全てが全てに影響し、全てが全てから学ぶ生態系。
Daichiの思考・哲学が中心に蓄積され、
SYUTAINとDaichiが互いに影響を与え合いながら共進化する。

これはβの完成形であり、γ（デジタル生命体）への直接的な土台となる。

---

## 2. Dual Brain構造

### 絶対原則: 既存を置き換えない、拡張する

SYUTAINβの既存機能は一切変更しない。

- 17エージェント + 34ツール → そのまま稼働
- BRAVOのPlaywright/LightPanda/Stagehand → そのまま稼働
- 4ノード構成（ALPHA/BRAVO/CHARLIE/DELTA）→ そのまま
- Cloud API（DeepSeek/Gemini/Claude/GPT-5）→ そのまま
- NATS JetStream → そのまま
- PostgreSQL + SQLite → そのまま
- 35ジョブのスケジューラー → そのまま
- Discord Webhook通知 → そのまま
- Brain-βはALPHAに残留。予期せぬ事態を防ぐため動かさない。

### 変更点

- ALPHAのQwen3.5-9B MLX → 廃止（6-7GBメモリ解放、Brain-α用）
- ローカルLLM → Nemotron-Nano-9B-v2-Japanese を BRAVO/CHARLIEに追加導入
  Qwen3.5-9Bは削除せず並存。タスク別にchoose_best_model_v6()で使い分け。
- Web UI → 10ページ → 12ページに拡張（/brain-alpha, /node-control 新設）
- 承認フロー → 手動承認撤廃、品質スコア基準の自動承認に移行
- SNS投稿 → 4プラットフォーム×2アカウント、計49件/日の自動投稿体制

Channels/Dispatch/Hooksは「新しい神経経路」として追加接続する。
Brain-αは既存エージェントと双方向に情報を共有し、互いに影響を与え合う対等な存在として接続する。

### 4PCの最終構成

```
ALPHA (M4 Mac mini 16GB): Brain-α + Brain-βインフラ。推論しない。
  Brain-β基盤（変更なし）:
    FastAPI, Next.js, PostgreSQL, NATS Server, Scheduler, Caddy
  Brain-α（新規追加）:
    Claude Code Channels (tmux永続セッション)
    Claude Desktop Cowork (Dispatch)
    brain_alpha/*.py (精査・記憶・自律修復・人格)
    Hooks (安全装置3フック)
    Bun runtime (Channelsプラグイン)
  廃止: Qwen3.5-9B MLX

BRAVO (RTX 5070 12GB): ローカルLLM主力 + ブラウザ操作
  既存: Playwright, LightPanda, Stagehand
  LLM: Nemotron 9B JP（第1候補）+ Qwen3.5-9B（フォールバック）
  CHARLIE Win11時は全推論を引き受ける

CHARLIE (RTX 3080 10GB): 副推論 + コンテンツ生成
  LLM: Nemotron 9B JP + Qwen3.5-9B
  Win11/Ubuntu切り替え: Web UIボタン + 自動検知
  島原使用中は全タスクBRAVO/DELTAに自動振替

DELTA (GTX 980Ti 6GB + 48GB RAM): 監視 + 軽量処理
  LLM: Qwen3.5-4B（フォールバック最終防衛線）
  MonitorAgent, InfoCollector
```

### インターフェース5層

```
1. Channels（Discord Bot）→ 開発・精査・対話・イベント駆動
2. Dispatch（スマホ → Claude Desktop）→ 外部操作・ファイル確認・ブラウザ
3. Web UI（12ページ）→ ダッシュボード・承認・ノード制御・Brain-α監視
4. Hooks（3フック）→ 安全装置・自動記録・セッション保存
5. Nemotron（日本語特化LLM）→ 品質1位の日本語コンテンツ生成
```

### ブラウザ操作の役割分担

```
BRAVOのPlaywright（既存・変更なし）:
  自動化パイプライン内のブラウザ操作、スケジューラーからの定期実行

Dispatch経由のブラウザ（追加）:
  オンデマンドのブラウザ操作、note/Booth管理画面、競合チェック

両者は独立動作。結果はPostgreSQLを通じて相互参照可能。
```

---

## 3. 双方向性の設計原理

### 核心思想

一方向の命令系統ではなく、双方向のフィードバックループが全体として知性を構成する。

```
Daichi → SYUTAINβの行動に影響 → 結果がDaichiの次の判断に影響
Brain-α → Brain-βの動作を改善 → Brain-βの実績がBrain-αの精度を上げる
エージェントA → エージェントBの入力 → BがAの次の判断を変える
```

### 双方向データフロー

```
Brain-α: 読む（trace/evaluation/event_log/dialogue_log/session）
         書く（review_log/auto_fix_log/handoff/reasoning/session/コード修正）
           ↕
共有記憶（PostgreSQL + 10新規テーブル）
           ↕
Brain-β: 読む（handoff/reasoning/review_log/auto_fix_log）
         書く（trace/handoff/evaluation/全通常出力）
```

---

## 4. 新規テーブル（10個）

1. agent_reasoning_trace — 全エージェント判断根拠
2. brain_alpha_session — セッション間記憶
3. brain_alpha_reasoning — Brain-α判断トレース
4. brain_cross_evaluation — 相互評価
5. daichi_dialogue_log — Daichi対話ログ（思考・哲学蓄積）
6. review_log — Brain-α精査記録
7. auto_fix_log — 自律修復記録
8. claude_code_queue — Brain-β→Brain-αタスクキュー
9. node_state — 4ノード状態管理（CHARLIE Win11制御の要）
10. posting_queue — SNS自動投稿キュー（4プラットフォーム×2アカウント）

---

## 5. Brain-αの精査・修復サイクル

Brain-α起動時にPhase 1-8を順次実行:

1. 前回セッション記憶復元（brain_alpha_session）
2. Daichiの思考参照（daichi_dialogue_log + persona_memory）
3. 情報収集精査（intel_items + trace）
4. 成果物精査（artifacts + Verifier trace → review_log）
5. タスク結果検証（tasks + trace → auto_fix_log or エスカレ）
6. エラー自律修復（event_log → コード修正 or git revert）
7. 売上・エンゲージメント分析（revenue_linkage + SNSデータ）
8. レポート + セッション記憶保存（Discord投稿 + brain_alpha_session）

---

## 6. 記憶階層（人間の脳を模倣）

```
感覚記憶     → channelイベント（数秒で消える）
短期記憶     → Claude Codeコンテキストウィンドウ
長期エピソード → brain_alpha_session（いつ何をして何が起きたか）
長期意味     → persona_memory（Daichiの人格・哲学）
長期手続き   → CLAUDE.md + コード自体
```

想起のコンテキスト量制御（OpenClaw教訓: 全記憶を注入しない）:
- casual: persona_memory上位5件
- standard: 上位10件 + strategy_identity + 直近セッション
- strategic: 上位20件 + 全strategy + 直近3セッション + Daichi対話10件
- code_fix: 直近セッション + 関連トレース10件

忘却メカニズム: 7日以上前のセッションは要約・圧縮。

---

## 7. 人格保持

セッション開始時に注入:
1. CLAUDE.md
2. persona_memory 上位20件
3. brain_alpha_session 最新1件
4. daichi_dialogue_log 直近5件
5. strategy_identity.md
6. SYSTEM_STATE.md

Daichiの哲学自動抽出: 対話中の価値判断・設計思想・好み・意思決定パターンを
extracted_philosophyに構造化し、重要なものはpersona_memoryに追加。

---

## 8. LLMルーティング（Nemotron統合後）

```
日本語コンテンツ生成 → Nemotron 9B JP → Qwen3.5-9B → Cloud API
日本語チャット       → Nemotron 9B JP (/no_think) → Qwen3.5-9B
Tool Calling        → Nemotron 9B JP → Qwen3.5-9B
分類・タグ付け       → Qwen3.5-4B (DELTA) → Nemotron (/no_think)
品質検証・推論      → Nemotron 9B JP (/think) → Cloud API
コード生成          → DeepSeek V3.2 (OpenRouter)

Nemotronの有効/無効: NEMOTRON_JP_ENABLED=true (.env)
Brain-αがmodel_quality_logを分析し、最適ルーティングを動的調整。
```

---

## 9. SNS自動投稿スケジュール

```
X島原大知:   10:00 / 13:00 / 17:00 / 20:00（4件/日）
X SYUTAIN:   11:00 / 13:30 / 15:00 / 17:30 / 19:00 / 21:00（6件/日）
Bluesky:     10:00〜22:00 毎時00分・30分（26件/日）
Threads:     10:00〜22:00 毎時30分（13件/日）※APIエラー要修正
合計:        49件/日
```

承認フロー: 品質≧0.65→自動承認、0.50-0.64→自動承認+Discord通知、<0.50→却下再生成
例外（手動維持）: 金銭言及、他者メンション、Brain-α要確認フラグ

投稿生成: night_batchで翌日分49件一括生成 → Verifier → posting_queue
投稿実行: 毎分ジョブがposting_queueからscheduled_at<=NOWを投稿

島原大知の文体: Twitterアーカイブから文体パターン・テーマ分布・思考パターンを抽出。
daichi_writing_style.md + daichi_writing_examplesテーブルでfew-shot注入。
週間テーマスケジュール + thread_contextで文脈連鎖を確保。

---

## 10. CHARLIE Win11制御

```
Web UIからの明示的切り替え（基本）:
  ダッシュボードの「Win11切り替え」ボタン
  → POST /api/nodes/charlie/mode {"mode":"win11"}
  → node_state='charlie_win11'、Discord通知、タスク振替、ジョブ停止

自動検知フォールバック:
  SSH応答なし + node_state='healthy' + 他ノード正常
  → 10分猶予 → 自動でcharlie_win11に移行

復帰:
  Web UIの「Ubuntu復帰を記録」ボタン or MonitorAgent自動検出
  → node_state='healthy'、サービス確認、ジョブ再開

全エージェント・ツールがnode_stateを参照:
  charlie_win11の場合、CHARLIEにタスクを振らない。
```

---

## 11. 自律修復・自律回復

自律修復5カテゴリ:
1. サービスクラッシュ自動再起動（systemd二次対策）
2. Ollamaモデル自動リロード
3. NATS接続自動復旧
4. PostgreSQL接続自動復旧
5. FastAPI/Next.js自動復旧

自律回復3カテゴリ:
1. ノード完全停止からの回復（CHARLIE=charlie_win11、他=障害）
2. データ整合性回復（孤立タスク、期限切れ承認、ログ肥大化）
3. Brain-α自身の回復（tmux監視、Brain-βが再起動）

エスカレーション: Level 1(Brain-β即座) → Level 2(Brain-αリアルタイム) → Level 3(Daichiエスカレ)

---

## 12. Hooks安全装置

```
PreToolUse (Write|Edit|Bash): safety_check.py
  .env/start.sh/settings.json への書き込みブロック
  rm -rf/DROP TABLE/TRUNCATE 等の危険コマンドブロック

Stop: session_save.py
  セッション終了時にbrain_alpha_sessionに自動保存

PostToolUse (Write|Edit): auto_log.py
  ファイル修正をauto_fix_logに自動記録
```

---

## 13. 権限の段階設計

```
自律実行OK: 品質スコア修正、プロンプト調整、ログ分析、trace/review_log/handoff読み書き
Daichi承認後: agents/*.py/tools/*.py修正、scheduler変更、エンドポイント追加
絶対禁止: .env変更、start.sh変更、金銭操作、DB DROP/TRUNCATE、サービス停止
```

---

## 14. 起動モード

```
Mode 1: Brain-β only（デフォルト）— 24h常時稼働
Mode 2: Brain-α + Brain-β（通常運用）— Channels永続セッション + Brain-β並行
Mode 3: Brain-α only（緊急メンテナンス）— Brain-β停止、直接修正
```

---

## 15. 不在時プロトコル

```
1日以内: Brain-βのみ、Brain-α起動しない
2-3日:   Brain-α定時起動（精査のみ）、Discordに1日1回サマリー
4日以上: Brain-α定時+軽微修正自律実行（1日最大3件、git stash必須）
```

---

## 16. コスト

```
Claude Max: $100/月（Brain-α処理はMax内）
ローカルLLM: ¥0（Nemotron 9B JP + Qwen3.5-9B/4B）
Cloud API: 従量課金（品質が必要な場面で躊躇なく使用）
X API: 従量課金 $3/月（300投稿 × $0.01）
Bluesky: 無料（atproto API）
Threads: 無料（Graph API）
```

---

## 17. 将来拡張（γに向けて）

- マルチモーダル（キャラデザ、Live2D、3Dモデル評価）
- 音声（TTS統合、Brain-αとの音声対話）
- 分散Brain-α（dispatch OSS スキルで並列精査）
- GitHub Webhook統合（自動PR → CI → マージ）
- カスタムChannel開発（NATS→Channel変換ブリッジ）
- Cowork Scheduled Tasks / Skills / Projects
- 請求書自動作成（Google Drive連携、BtoB案件対応）
- Mac mini追加（Brain-α専用機、M2 24GB推奨）
- RTX 3090換装（CHARLIE、VRAM 10GB→24GB）

---

*2026-03-21策定、2026-03-23最終更新。*
*島原大知とClaude（Anthropic）の対話から生まれた構想。*
*SYUTAINβの完成形であり、SYUTAINγへの橋渡しとなる設計。*
