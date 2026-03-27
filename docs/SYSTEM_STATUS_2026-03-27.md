# SYUTAINβ システム状態レポート — 2026-03-27

生成日時: 2026-03-27 00:20 JST

---

## 1. コードベース概要

### ディレクトリ構造（2階層）

```
.
├── agents/          # エージェント群（OSカーネル、プランナー、エグゼキューター等）
├── bots/            # Discord Bot関連（会話、アクション、学習）
├── brain_alpha/     # Brain-α（SNSバッチ、記憶管理、相互評価、エスカレーション）
├── certs/           # TLS証明書
├── config/          # NATS設定等
├── data/
│   ├── artifacts/   # 生成成果物（夜間バッチ、noteドラフト）
│   ├── backup/      # バックアップ
│   ├── pids/        # PIDファイル
│   └── screenshots/ # スクリーンショット
├── docs/            # 運用ログ、設計書
├── logs/            # アプリケーションログ
├── mcp_servers/
│   └── syutain_tools/  # MCP連携ツール
├── memory/          # ローカルメモリストア
├── prompts/         # プロンプトテンプレート
├── scripts/         # バッチスクリプト（embeddings backfill等）
├── strategy/        # 戦略ファイル（ICP、チャネル、人格プロファイル）
├── tools/           # ツール群（LLMルーター、ループガード、SNS、コマース等）
├── venv/            # Python仮想環境
└── web/
    ├── public/      # 静的アセット
    └── src/         # Next.jsフロントエンド
```

### ファイル数と行数

| 種別 | ファイル数 | 行数 |
|------|-----------|------|
| Python (.py) | 6,412 | 2,416,625 (※venv含む) |
| TSX (.tsx) | 22 | 6,402 |
| TS (.ts) | 3,735 | 535,945 (※node_modules除外済) |
| Markdown (.md) | 818 | — |
| JSON (config, max depth 2) | 6 | — |
| Shell (.sh) | 11 | — |

> Note: Python行数はvenv/を含むため実コード量は大幅に少ない。

### 主要モジュールの役割一覧

| モジュール | 役割 |
|-----------|------|
| `app.py` | FastAPI メインAPIサーバー。認証(JWT)、タスク/ゴール/成果物API、WebSocket |
| `scheduler.py` | APScheduler ベースの44ジョブスケジューラー |
| `worker_main.py` | リモートノード用ワーカー（NATS購読、タスク実行） |
| `agents/os_kernel.py` | 5段階自律ループ（観察→計画→行動→検証→停止判断） |
| `agents/planner.py` | タスク分解・依存関係グラフ生成 |
| `agents/executor.py` | タスク実行（LLM/ブラウザ/CU/承認） |
| `agents/verifier.py` | 実行結果の品質検証・学習ループ |
| `agents/stop_decider.py` | 停止判断（続行/完了/スケーリング/エスカレーション/Emergency Kill） |
| `agents/approval_manager.py` | 3段階承認フロー（Tier 1: 人間承認, Tier 2: 自動+通知, Tier 3: 完全自動） |
| `agents/mutation_engine.py` | 突然変異エンジン（第24章、完全隔離） |
| `agents/node_router.py` | 4ノード動的ルーティング |
| `brain_alpha/sns_batch.py` | SNS 49件/日の生成・品質評価・投稿 |
| `brain_alpha/memory_manager.py` | persona_memory管理、セッション保存 |
| `brain_alpha/cross_evaluator.py` | Brain-α相互評価 |
| `bots/discord_bot.py` | Discord Bot メインループ |
| `bots/bot_actions.py` | 30 ACTIONハンドラー |
| `bots/bot_conversation.py` | 3段階モデル選択、対話深度検知 |
| `tools/llm_router.py` | LLMルーティング（choose_best_model_v6） |
| `tools/loop_guard.py` | 9層ループ防止壁 |
| `tools/emergency_kill.py` | 6条件Emergency Kill |
| `tools/budget_guard.py` | 予算監視 |
| `tools/social_tools.py` | X/Bluesky/Threads API連携 |
| `tools/info_pipeline.py` | 情報収集パイプライン |
| `tools/embedding_tools.py` | ベクトル埋め込み |

---

## 2. DB状態

### 全テーブル一覧とレコード数

| テーブル名 | レコード数 |
|-----------|-----------|
| agent_reasoning_trace | 2,878 |
| approval_queue | 207 |
| auto_fix_log | 16 |
| brain_alpha_reasoning | 4 |
| brain_alpha_session | 3 |
| brain_cross_evaluation | 14 |
| brain_handoff | 1 |
| browser_action_log | 7,282 |
| capability_snapshots | 222 |
| chat_messages | 224 |
| claude_code_queue | 0 |
| content_edit_log | 53 |
| crypto_trades | 0 |
| daichi_dialogue_log | 8 |
| daichi_writing_examples | 103 |
| discord_chat_history | 180 |
| embeddings | 0 |
| event_log | 15,239 |
| goal_packets | 67 |
| intel_digest | 1 |
| intel_items | 617 |
| llm_cost_log | 5,940 |
| loop_guard_events | 53 |
| model_quality_log | 373 |
| node_state | 4 |
| persona_memory | 415 |
| posting_queue | 258 |
| proposal_feedback | 2 |
| proposal_history | 39 |
| revenue_linkage | 0 |
| review_log | 0 |
| seasonal_revenue_correlation | 0 |
| settings | 1 |
| tasks | 631 |

**合計: 34テーブル**

### proposal_history: review_flag別件数

| review_flag | adopted | count |
|-------------|---------|-------|
| approved | true | 39 |

全39件が approved/adopted。pending/rejected なし。

#### proposal_history 全レコード

| id | proposal_id | title | channel | score | adopted | review_flag | created_at |
|----|-------------|-------|---------|-------|---------|-------------|------------|
| 39 | e053982e-... | 非エンジニアのためのDeepSeek V4活用：コードなしでAIを業務に組み込む失敗と実践ログ | note | 93 | t | approved | 2026-03-26 19:50 |
| 38 | 3b6635fe-... | 非エンジニアがDeepSeek V4を仕事で活かす！『コード不要のAIプロンプト実践ガイド - 失敗コスト削減版』note販売 | note | 93 | t | approved | 2026-03-26 13:50 |
| 37 | b4394978-... | 最新AIモデルの『非エンジニア的』落とし穴と、僕が見つけた回避策 | note | 88 | t | approved | 2026-03-26 07:50 |
| 36 | 49bac9d8-... | 最新AIモデル DeepSeek V4を非エンジニアが導入する際の『最初の壁』と、3つの回避策【島原大知の失敗談】 | note | 90 | t | approved | 2026-03-26 07:00 |
| 35 | 0b5dea0e-... | DeepSeek V4 を用いた『非エンジニア向け』AIエージェント作成と、その実装ログをnote 単発記事で公開 | note | 93 | t | approved | 2026-03-25 21:34 |
| 34 | 4500fc61-... | 【非エンジニアの僕が溶かしたAPIコスト】最新AIモデルに飛びつく前に確認する「撤退サイン」と「最小検証マップ」 | note | 87 | t | approved | 2026-03-25 13:43 |
| 33 | 79168c85-... | 【非エンジニア向け】AIコスト爆増を避ける！あなたの事業に『本当に必要なAIモデル』を高速見つける思考フレームワーク | note | 86 | t | approved | 2026-03-25 07:00 |
| 32 | 28958a61-... | 非エンジニア島原がAIと作った『売れるキャッチコピー』自動生成ノート：失敗から学んだプロンプト設計図 | note | 95 | t | approved | 2026-03-24 07:01 |
| 31 | 042305e0-... | 最新AIモデルの波に飲まれない『非エンジニアの僕』が溶かした時間とAPIコスト：失敗から導く実践的モデル選定軸 | note | 87 | t | approved | 2026-03-24 05:43 |
| 30 | b6ab1548-... | 『AIモデル、どれ使う？』非エンジニアの僕がSYUTAINβで失敗したから分かった『事業に繋がるモデル選定』の現実と導入ロードマップ | note | 93 | t | approved | 2026-03-23 14:15 |
| 29 | 5fbfbba6-... | AIエージェントが僕の時間を無限に溶かした日。非エンジニアのための『AI停止条件』設計ガイド | note | 87 | t | approved | 2026-03-23 09:02 |
| 28 | 0780f48e-... | 週次報告が『時間泥棒』になるあなたへ：非エンジニアの僕がAIで解決した『失敗コストゼロ』の裏側 | note | 91 | t | approved | 2026-03-23 09:02 |
| 27 | 8fb0f327-... | 非エンジニアの僕がAIに『ムダ金と時間』を溶かした瞬間：無限ループの泥沼から脱した『非エンジニア向け停止ルール』 | note | 95 | t | approved | 2026-03-23 09:01 |
| 26 | f60a1554-... | 非エンジニアが『最新AIモデル』のニュースに踊らされて費用を溶かす前に読むべき：実践的モデル選定チェックリスト | note | 85 | t | approved | 2026-03-23 08:15 |
| 25 | 138de368-... | VTuberの僕がAIと『追われるコンテンツ』を作るまで：非エンジニアが陥る「いいね0の罠」と抜け出し方 | note | 100 | t | approved | 2026-03-23 07:00 |
| 24 | 92a46152-... | 非エンジニアのための『AI導入判断マップ』と失敗コストゼロ戦略 | note | 89 | t | approved | 2026-03-23 02:15 |
| 23 | b0d85a1e-... | 非エンジニアの僕が『高性能AIを使いすぎた』結果、費用が3倍に。SYUTAINβが暴走した『AI過剰武装』問題と、僕が見つけたスリム化戦略 | note | 89 | t | approved | 2026-03-22 20:15 |
| 22 | 78873b0a-... | 非エンジニアの僕がAIモデル選びで数千円を無駄にした告白：『速さ』よりも大切な『費用対効果』の現実 | note | 87 | t | approved | 2026-03-22 14:15 |
| 21 | 75a2f657-... | DeepSeek V4を非エンジニアが『事業OSに組み込むまで』の泥臭い全記録：僕が初日に数千円溶かして学んだこと | note | 90 | t | approved | 2026-03-22 08:15 |
| 20 | d6a73d96-... | 非エンジニアがAI選択で迷う罠：僕が無駄金を溶かさずに「最適な一手」を見つける判断基準 | note | 84 | t | approved | 2026-03-22 07:00 |
| 19 | 7686f77e-... | 最新AIで数千円溶かした僕の教訓：非エンジニアが『AIに任せきり』で失敗しないための損切りチェックシート | note | 88 | t | approved | 2026-03-22 02:15 |
| 18 | eb9dc0e4-... | 【非エンジニア向け】VTuber8年で掴んだ『追われるコンテンツ』の法則をAIで再現する僕の失敗と設計図 | note | 88 | t | approved | 2026-03-21 20:15 |
| 17 | 48a26681-... | 【最新AIモデルの落とし穴】GeminiやDeepSeekをクリエイティブに活かす『VTuber式熱量設計』入門 | note | 88 | t | approved | 2026-03-21 14:15 |
| 16 | ecea02fa-... | 【非エンジニア向け】僕がAI導入で失敗した3つの『落とし穴』：事業を失速させない『SYUTAINβ式リスク評価シート』 | note | 92 | t | approved | 2026-03-21 08:15 |
| 15 | 0e6d4e9e-... | 非エンジニアの『AI設定ミス』が激減。最新LLMが手戻りを防ぐ「実践テンプレート」 | note | 84 | t | approved | 2026-03-21 07:00 |
| 14 | cfa3c576-... | AIを導入して『結局放置』を卒業する。非エンジニアのための、僕が半年で掴んだ『事業の相棒AI』育成ルーティン | note | 95 | t | approved | 2026-03-21 02:10 |
| 13 | 34b13349-... | 非エンジニアがAI導入で最初にハマる『情報の羅列地獄』から脱出する3ステップチェックリスト | note | 100 | t | approved | 2026-03-21 01:52 |
| 12 | b50aa93a-... | Gemini AI x VTuber 制作現場：「非エンジニア」が AI を使いこなし、動画生成コストを 80% 削減し収益化した実証実験レポート | note | 87 | t | approved | 2026-03-20 16:11 |
| 11 | e629d5bb-... | GPT-OSS / DeepSeek V4 を用いた「非エンジニア向け AI エージェント構築ガイド」の連載企画と早期アフィリエイト収益化 | note | 85 | t | approved | 2026-03-20 10:11 |
| 10 | 5c8037dc-... | Gemini AI 最新動向 vs 非エンジニア実装：24 時間で検証できる「音楽生成」の収益化実験レポート | note | 89 | t | approved | 2026-03-20 07:00 |
| 9 | e7580ac0-... | 【非エンジニア向け】AIで月3万円の副収入を設計する実践マニュアル - 失敗コスト公開版 | note | 90 | t | approved | 2026-03-19 19:33 |
| 8 | 35d1dcd2-... | 「非エンジニアのAI実装失敗集」note連載 × Booth限定商品化プロジェクト | note | 90 | t | approved | 2026-03-19 13:32 |
| 7 | 21c43d4f-... | 「AIツール実体験レビュー連載」×「限定セール」による収益最大化提案 | note | 91 | t | approved | 2026-03-19 07:32 |
| 6 | a6138ad8-... | 「AIに期待してるけど、何から始めればいいか分からない」非エンジニア向け・失敗コスト削減パッケージ（note限定販売） | note | 90 | t | approved | 2026-03-19 07:00 |
| 5 | 2150c9e9-... | 「非エンジニアのAI実装失敗集」note有料記事シリーズ + Boothテンプレートパックのセット販売 | note | 88 | t | approved | 2026-03-19 01:33 |
| 4 | 7f516ff2-... | 「AI時代のクリエイター生存戦略」note有料シリーズ第1弾：非エンジニアのためのAI実装マップ | note | 90 | t | approved | 2026-03-18 19:19 |
| 3 | 2dbdc2dc-... | 【非エンジニア向け】AI収益化の「詰まりポイント」解決パッケージ - 週次収益報告の失敗分析から生まれた実践テンプレート | note | 90 | t | approved | 2026-03-18 17:55 |
| 2 | e3958d7c-... | 「AI時代の副業設計書」note記事 + Booth商品化提案 | note | 90 | t | approved | 2026-03-18 16:44 |
| 1 | f460cac0-... | 【非エンジニア向け】AIで月3万円の副収益を設計する実践マニュアル（失敗コスト込み）note記事販売 | note | 88 | t | approved | 2026-03-18 05:46 |

### goal_packets: status別件数

| status | count |
|--------|-------|
| completed | 24 |
| emergency_stopped | 23 |
| escalated | 12 |
| superseded | 8 |

**合計: 67ゴール**

### posting_queue: status別件数

| status | count |
|--------|-------|
| posted | 168 |
| pending | 62 |
| rejected | 28 |

**合計: 258件**

#### posting_queue 直近10件

| id | platform | content (60文字) | status | quality_score | scheduled_at | created_at |
|----|----------|------------------|--------|---------------|--------------|------------|
| 412 | threads | 映像業界で「クオリティ」って言葉、よく聞くよね。4K、HDR、120fps… | pending | 0.792 | 2026-03-27 22:38 | 2026-03-26 23:31 |
| 411 | threads | SunoAIで作った曲を聴いてて、ふと思った。「これ、自分の歌詞なのに... | pending | 0.731 | 2026-03-27 21:30 | 2026-03-26 23:31 |
| 410 | threads | 自分が何者か…と聞かれた時、つい肩書や実績を並べてしまう。 | pending | 0.676 | 2026-03-27 20:37 | 2026-03-26 23:31 |
| 409 | threads | 映像のカラーグレーディング、ずっと「正解」を探してた。 | pending | 0.726 | 2026-03-27 19:36 | 2026-03-26 23:31 |
| 408 | threads | VTuberの配信を見ていて、ふと思う。あの画面の向こうで… | pending | 0.691 | 2026-03-27 18:32 | 2026-03-26 23:31 |
| 407 | threads | 風が窓を撫でる音…今夜も、また灯りを消さずに残してきた。 | pending | 0.758 | 2026-03-27 17:35 | 2026-03-26 23:31 |
| 406 | threads | 映像編集の合間に、ふとSunoAIで作った曲を聴き返す。 | pending | 0.853 | 2026-03-27 16:36 | 2026-03-26 23:31 |
| 405 | threads | 風が窓を撫でる音 PCの電源はついているのに、画面は真っ暗だ | pending | 0.634 | 2026-03-27 14:30 | 2026-03-26 23:30 |
| 404 | threads | 風が静かに机の上をすり抜ける。PCのモニターには... | pending | 0.737 | 2026-03-27 13:38 | 2026-03-26 23:30 |
| 403 | threads | 風が窓を撫でる音 今夜も、またその灯りを消さずに残してきた | pending | 0.611 | 2026-03-27 11:37 | 2026-03-26 23:30 |

### persona_memory: カテゴリ別件数

**総件数: 415**

| category | count |
|----------|-------|
| daichi_trait | 111 |
| philosophy | 96 |
| conversation | 75 |
| approval_pattern | 37 |
| judgment | 28 |
| taboo | 21 |
| identity | 14 |
| writing_style | 8 |
| vtuber_insight | 7 |
| emotion | 7 |
| creative | 6 |
| preference | 5 |

### 収益関連テーブル

| テーブル | レコード数 | 備考 |
|---------|-----------|------|
| revenue_linkage | 0 | 未使用 |
| seasonal_revenue_correlation | 0 | 未使用 |
| crypto_trades | 0 | 未使用 |

---

## 3. サービス稼働状況

### ローカルサービス（ALPHA: Mac mini）

| サービス | 状態 | PID | 備考 |
|---------|------|-----|------|
| FastAPI (uvicorn) | **Running** ✅ (HTTP 200) | 73745 | `app:app --host 0.0.0.0 --port 8000` |
| Next.js | **Running** ✅ (HTTP 200) | — | port 3000 |
| NATS Server | **Running** ✅ | 71190 | Connected, RTT 47µs |
| PostgreSQL | **Running** ✅ | — | 16.13 (Homebrew), 34テーブル |
| Caddy | **Running** ✅ | 90491 | TLS reverse proxy, uptime: 3月11日〜 |
| Scheduler | **Running** ✅ | 73748 | APScheduler, CPU time 2:06 |
| Discord Bot | **Running** ✅ | 3216 | `bots/discord_bot.py` |

### リモートノード

| ノード | IP | SSH | Worker | Uptime | Load |
|--------|-----|-----|--------|--------|------|
| BRAVO | 100.75.146.9 | OK ✅ | Running (PID 13644, 3月17日〜) | 9 days | 0.00, 0.04, 0.06 |
| CHARLIE | 100.70.161.106 | OK ✅ | Running (PID 681720, 3月26日〜) | 8 days | 2.08, 2.05, 2.05 |
| DELTA | 100.82.81.105 | OK ✅ | Running (PID 1472631, 3月26日〜) | 8 days | 0.03, 0.06, 0.02 |

### node_state テーブル

| node_name | state | reason | changed_by | changed_at |
|-----------|-------|--------|------------|------------|
| alpha | healthy | initial | system | 2026-03-23 14:47 |
| bravo | healthy | initial | system | 2026-03-23 14:47 |
| charlie | healthy | Ubuntu復帰（Web UI） | web_ui | 2026-03-23 18:27 |
| delta | healthy | initial | system | 2026-03-23 14:47 |

---

## 4. スケジューラー

### 全ジョブ一覧（44ジョブ）

| ID | ジョブ名 | Trigger | 間隔/時刻 |
|----|---------|---------|----------|
| heartbeat | ハートビート | Interval | 30秒 |
| capability_audit | Capability Audit | Interval | 1時間 |
| info_pipeline | 情報収集パイプライン | Interval | 12時間 |
| auto_review_intel | intel_items自動レビュー | Interval | 6時間 |
| daily_proposal | 日次提案生成 | Cron | 07:00 |
| weekly_proposal | 週次提案生成 | Cron | 月曜 09:00 |
| reactive_proposal | リアクティブ提案 | Interval | 6時間 |
| weekly_learning_report | 週次学習レポート | Cron | 日曜 21:00 |
| redispatch_orphan | 孤児タスク再ディスパッチ | Interval | 5分 |
| night_batch_sns_1 | SNS生成1: X島原+SYUTAIN 10件 | Cron | 22:00 JST |
| night_batch_sns_2 | SNS生成2: Bluesky前半13件 | Cron | 22:30 JST |
| night_batch_sns_3 | SNS生成3: Bluesky後半13件 | Cron | 23:00 JST |
| night_batch_sns_4 | SNS生成4: Threads13件 | Cron | 23:30 JST |
| daily_content | 日次コンテンツ生成 | Cron | 09:30 JST |
| system_state_update | SYSTEM_STATE.md更新 | Interval | 1時間 |
| operation_log | 運用ログ生成 | Cron | 00:00 |
| pg_backup | PostgreSQLバックアップ | Cron | 03:00 |
| crypto_price | 暗号通貨価格取得 | Interval | 30分 |
| cost_forecast | コスト予測 | Interval | 6時間 |
| bluesky_engagement | Blueskyエンゲージメント取得 | Interval | 12時間 (起動5分後に初回) |
| x_engagement | Xエンゲージメント取得 | Interval | 12時間 (起動6分後に初回) |
| threads_engagement | Threadsエンゲージメント取得 | Interval | 12時間 (起動7分後に初回) |
| model_quality_refresh | モデル品質キャッシュ更新 | Interval | 1時間 (起動1分後に初回) |
| sqlite_backup | SQLiteバックアップ rsync | Cron | 03:30 |
| persona_question | ペルソナ質問 | Cron | 水・土 20:00 |
| night_mode | 夜間モード | Cron | 23:00 |
| day_mode | 日中モード | Cron | 07:00 |
| night_batch | 夜間バッチ | Cron | 23:30 |
| weekly_product | 週次商品生成 | Cron | 金曜 23:15 |
| note_draft | noteドラフト | Cron | 23:45 |
| competitive_analysis | 競合分析 | Cron | 日曜 03:00 |
| approval_timeout | 承認タイムアウト処理 | Interval | 1時間 |
| process_proposals | 提案自動承認→ゴール変換 | Interval | 30分 |
| expire_handoffs | brain_handoff期限切れ処理 | Interval | 24時間 |
| posting_queue_process | 投稿キュー処理 | Interval | 1分 |
| brain_cross_evaluate | Brain-α相互評価 | Cron | 06:00 JST |
| self_heal_check | セルフヒーリング | Interval | 5分 |
| data_integrity_check | データ整合性チェック | Cron | 04:00 JST |
| brain_alpha_health | Brain-αヘルスチェック | Interval | 10分 |
| node_health_check | ノードヘルスチェック | Interval | 5分 |
| anomaly_detection | 異常検知 | Interval | 5分 |
| dynamic_keyword_update | 動的キーワード更新 | Cron | 06:00 JST |
| generate_intel_digest | intel_digest生成 | Cron | 07:00 JST |
| deep_article_scrape | 深掘り記事スクレイプ | Cron | 12:00 JST |
| chat_learning | チャット学習 | Interval | 1時間 |

### 直近24時間のevent_logジョブ活動

| event_type | count | last_run |
|------------|-------|----------|
| trade.price_snapshot | 22 | 2026-03-26 23:19 |
| system.power_mode | 2 | 2026-03-26 23:00 |
| intel.digest_generated | 1 | 2026-03-26 07:00 |
| keyword.updated | 1 | 2026-03-26 06:00 |
| system.sqlite_backup | 1 | 2026-03-26 03:30 |
| system.backup | 1 | 2026-03-26 03:00 |

### 直近24時間のエラー件数

| severity | count |
|----------|-------|
| error | 7 |

---

## 5. LLM状態

### 直近24時間の呼び出し（モデル別）

| model | calls | cost_jpy |
|-------|-------|----------|
| nemotron-jp | 306 | ¥0.00 |
| qwen3.5-4b | 80 | ¥0.00 |
| qwen3.5-9b | 49 | ¥0.00 |
| gemini-2.5-flash | 37 | ¥6.93 |
| claude-haiku-4-5 | 32 | ¥18.12 |
| deepseek-v3.2 | 16 | ¥1.27 |
| jina-reader | 10 | ¥5.00 |
| tavily-search | 6 | ¥12.00 |

### 24時間サマリー

| 指標 | 値 |
|------|-----|
| 総呼び出し数 | 536 |
| 総コスト | ¥43.32 |
| ローカルLLM比率 | 81.2% (435/536) |

### 累計

| 指標 | 値 |
|------|-----|
| 総呼び出し数（全期間） | 5,940 |
| 総コスト（全期間） | ¥336.03 |

### モデル品質ログ（上位15）

| task_type | model_used | tier | avg_quality | count |
|-----------|------------|------|-------------|-------|
| content | qwen3.5-9b | unknown | 0.709 | 78 |
| research | qwen3.5-9b | unknown | 0.590 | 69 |
| analysis | qwen3.5-9b | unknown | 0.598 | 50 |
| drafting | qwen3.5-9b | unknown | 0.716 | 46 |
| research | gemini-2.5-flash | unknown | 0.683 | 26 |
| content | deepseek-v3.2 | unknown | 0.448 | 20 |
| content | nemotron-jp | L | 0.490 | 13 |
| browser_action | qwen3.5-9b | L | 0.478 | 13 |
| analysis | nemotron-jp | L | 0.626 | 13 |
| coding | qwen3.5-9b | unknown | 0.556 | 8 |
| unknown | (empty) | unknown | 0.729 | 7 |
| analysis | nemotron-jp | unknown | 0.780 | 6 |
| drafting | nemotron-jp | L | 0.673 | 6 |
| analysis | deepseek-v3.2 | unknown | 0.500 | 5 |
| research | gemini-2.5-flash | A | 0.445 | 4 |

---

## 6. SNS状態

### プラットフォーム別投稿件数（全期間）

| platform | count |
|----------|-------|
| bluesky | 137 |
| threads | 67 |
| x | 52 |
| reminder | 2 |

**合計: 258件**

### 直近24時間

| platform | status | count |
|----------|--------|-------|
| bluesky | pending | 35 |
| bluesky | posted | 1 |
| reminder | posted | 1 |
| reminder | rejected | 1 |
| threads | pending | 19 |
| x | pending | 8 |

### 品質スコア分布

| 指標 | 値 |
|------|-----|
| 平均 | 0.673 |
| 中央値 | 0.676 |
| 最小 | 0.508 |
| 最大 | 1.000 |

### Pending投稿数: **62件**

---

## 7. 収益状態

### 商品・出品状況

- **proposal_history**: 39件全てnote向け提案。全件 approved/adopted。
- **revenue_linkage**: 0件（実収益の記録なし）
- **seasonal_revenue_correlation**: 0件（季節性分析未実施）
- **crypto_trades**: 0件（暗号通貨取引未開始）

### settings（予算設定）

```json
{
  "chat_budget_jpy": 30.0,
  "daily_budget_jpy": 80.0,
  "monthly_budget_jpy": 1500.0
}
```

### feature_flags

専用テーブルなし。`settings` テーブルに budget 設定のみ存在。

### 収益関連API接続状態

| サービス | .envキー存在 | 状態 |
|---------|-------------|------|
| Gumroad | なし | 未設定 |
| BOOTH | なし | 未設定（提案のみ） |
| note | NOTE_EMAIL, NOTE_PASSWORD | キー存在 |
| Bluesky | BLUESKY_HANDLE, BLUESKY_APP_PASSWORD | キー存在 |
| X (Twitter) | X_CONSUMER_KEY 等 | キー存在 |
| Threads | THREADS_ACCESS_TOKEN, THREADS_USER_ID | キー存在 |
| Bitbank | BITBANK_API_KEY, BITBANK_API_SECRET | キー存在 |
| GMO | GMO_API_KEY, GMO_API_SECRET | キー存在 |
| Wise | WISE_API_TOKEN, WISE_PROFILE_ID | キー存在 |

---

## 8. 未解決の問題

### 直近24時間のエラーログ（severity=error以上）上位

| event_type | category | source_node | count |
|------------|----------|-------------|-------|
| llm.error | llm | bravo | 3 |
| llm.error | llm | delta | 2 |
| node.health | node | bravo | 1 |
| sns.post_failed | sns | alpha | 1 |

**合計: 7件（全てseverity=error、criticalなし）**

### emergency_stopped ゴール一覧（23件）

全23件が `total_steps=1`（計画直後に停止）。全て `(revenue)` タイプの提案→ゴール変換。

| goal_id | raw_goal (80文字) | steps | cost_jpy | created_at |
|---------|-------------------|-------|----------|------------|
| goal-0bb9514081c7 | 最新AIで数千円溶かした僕の教訓：非エンジニアが... | 1 | ¥0.17 | 2026-03-25 15:13 |
| goal-0de5cd7b266b | 【最新AIモデルの落とし穴】GeminiやDeepSeekを... | 1 | ¥0.29 | 2026-03-25 15:13 |
| goal-fab198705dc3 | 【非エンジニア向け】VTuber8年で掴んだ... | 1 | ¥0.28 | 2026-03-25 15:12 |
| goal-381192d1c487 | 「非エンジニアのAI実装失敗集」note連載... | 1 | ¥0.13 | 2026-03-25 14:13 |
| goal-35ba22e10604 | 非エンジニアのための『AI導入判断マップ』... | 1 | ¥0.22 | 2026-03-25 14:13 |
| goal-ee8826d2dbee | 【非エンジニア向け】AIで月3万円の副収益... | 1 | ¥0.19 | 2026-03-25 14:13 |
| goal-091f7799462f | 非エンジニアの僕が『高性能AIを使いすぎた』... | 1 | ¥0.28 | 2026-03-25 13:13 |
| goal-f0ba4f53e3de | Gemini AI 最新動向 vs 非エンジニア実装... | 1 | ¥0.14 | 2026-03-25 13:13 |
| goal-5cda87423ff2 | DeepSeek V4を非エンジニアが『事業OSに組み込む... | 1 | ¥0.08 | 2026-03-25 13:13 |
| goal-78bad69173d3 | 【非エンジニア向け】AIで月3万円の副収入... | 1 | ¥0.18 | 2026-03-25 12:13 |
| goal-02c9b197c817 | 「AIに期待してるけど、何から始めれば...」... | 1 | ¥0.22 | 2026-03-25 12:13 |
| goal-1acf51a63601 | 「非エンジニアのAI実装失敗集」note連載... | 1 | ¥0.13 | 2026-03-25 12:12 |
| goal-0f80409aeef6 | 「AI時代のクリエイター生存戦略」note有料シリーズ... | 1 | ¥0.22 | 2026-03-25 11:13 |
| goal-fa4b65c854a2 | 【非エンジニア向け】AI収益化の「詰まりポイント」... | 1 | ¥0.22 | 2026-03-25 11:13 |
| goal-526bcdcdaf8f | 「AI時代の副業設計書」note記事 + Booth... | 1 | ¥0.08 | 2026-03-25 11:12 |
| goal-da9bb7a94b55 | 「AIツール実体験レビュー連載」×「限定セール」... | 1 | ¥0.20 | 2026-03-25 10:13 |
| goal-72f72d016b81 | 週次報告が『時間泥棒』になるあなたへ... | 1 | ¥0.24 | 2026-03-25 10:13 |
| goal-2f4dc2f83718 | 【非エンジニア向け】僕がAI導入で失敗した... | 1 | ¥0.20 | 2026-03-25 10:12 |
| goal-24c9ec5c07d9 | AIを導入して『結局放置』を卒業する... | 1 | ¥0.26 | 2026-03-25 09:13 |
| goal-eb8d3d628734 | 『AIモデル、どれ使う？』非エンジニアの僕が... | 1 | ¥0.34 | 2026-03-25 09:13 |
| goal-7fe3d5b19635 | 非エンジニアの僕がAIに『ムダ金と時間』を溶かした... | 1 | ¥0.19 | 2026-03-25 09:12 |
| goal-4a153ffc9e5e | 非エンジニアがAI導入で最初にハマる... | 7 | ¥0.28 | 2026-03-25 08:13 |
| goal-9c7f95bd27ff | VTuberの僕がAIと『追われるコンテンツ』を... | 9 | ¥0.35 | 2026-03-25 08:13 |

> **注意**: 23件中21件が `total_steps=1` で停止。全て2026-03-25に集中（提案自動承認→ゴール変換の大量発火）。クールダウン追加（Commit 6）で対処済み。

### 品質スコア0.00のレコード

**0件** — 品質スコア0.00問題は解消済み。

### approval_queue pending

8件の `approval_request` が pending 状態。

---

## 9. Git状態

### 現在のブランチ: `main`

### 直近10コミット

```
38c426f ui: artifacts page, mobile fixes, JST time display, and API improvements
db79a58 data: agent improvements, persona embedding, logging, and operational docs
71ab1ff infra: NATS cluster config, worker resilience, and node routing fixes
1cd299c safety: loop prevention, runaway guards, and scheduler overhaul
c56a10d fix: critical bug fixes and infrastructure hardening
2be019a feat: Discord 30 ACTION handlers for centralized operations
f89d7e8 feat: chat quality and model auto-selection
69e9c68 perf: LLM routing optimization and model registry update
b71355d feat: SNS quality improvements
80751ca Brain-α fusion complete: 12 tables, 17 agent traces, Nemotron 9B JP, SNS 49/day
```

### git status

```
?? .claude/
```

未コミットは `.claude/` ディレクトリのみ（Claude Code設定、コミット不要）。

---

## 10. 設定ファイル

### .env キー一覧（81キー）

```
ALPHA_URL
ANTHROPIC_API_KEY
ANTHROPIC_CREDITS_AVAILABLE
API_DB_PATH
APP_ENV
APP_HOST
APP_PASSWORD
APP_PORT
APP_SECRET_KEY
BITBANK_API_KEY
BITBANK_API_SECRET
BLUESKY_APP_PASSWORD
BLUESKY_HANDLE
BRAIN_ALPHA_DISCORD_ID
BRAVO_LOCAL_MODEL
BRAVO_OLLAMA_URL
BRAVO_URL
CHARLIE_LOCAL_MODEL
CHARLIE_OLLAMA_URL
CHARLIE_URL
CHAT_DB_PATH
CHROMIUM_PORT
CORE_DB_PATH
DAILY_API_BUDGET_JPY
DATABASE_URL
DEEPSEEK_API_KEY
DELTA_LOCAL_MODEL
DELTA_OLLAMA_URL
DELTA_URL
DISCORD_BOT_TOKEN
DISCORD_GENERAL_CHANNEL_ID
DISCORD_SERVER_ID
DISCORD_WEBHOOK_URL
EMERGENCY_KILL_MAX_STEPS
GEMINI_API_KEY
GITHUB_TOKEN
GMAIL_ALERTS_LABEL
GMAIL_RAKUTEN_LABEL
GMO_API_KEY
GMO_API_SECRET
GTM_DB_PATH
INTERNAL_API_TOKEN
JINA_API_KEY
LEARNING_DB_PATH
LIGHTPANDA_DISABLE_TELEMETRY
LIGHTPANDA_PORT
LOG_FILE
LOG_LEVEL
MONTHLY_API_BUDGET_JPY
MONTHLY_INFO_BUDGET_JPY
NATS_URL
NEMOTRON_JP_ENABLED
NEMOTRON_JP_NODES
NOTE_EMAIL
NOTE_PASSWORD
OPENAI_API_KEY
OPENROUTER_API_KEY
SQLCIPHER_PASSPHRASE
STAGEHAND_ENV
TAVILY_API_KEY
THIS_NODE
THREADS_ACCESS_TOKEN
THREADS_USER_ID
TZ
WISE_API_TOKEN
WISE_PROFILE_ID
X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET
X_CLIENT_ID
X_CLIENT_SECRET
X_CONSUMER_KEY
X_CONSUMER_SECRET
X_SHIMAHARA_ACCESS_TOKEN
X_SHIMAHARA_ACCESS_TOKEN_SECRET
X_SHIMAHARA_CLIENT_ID
X_SHIMAHARA_CLIENT_SECRET
X_SHIMAHARA_CONSUMER_KEY
X_SHIMAHARA_CONSUMER_SECRET
YOUTUBE_API_KEY
```

### settings テーブル

| key | value | updated_at |
|-----|-------|------------|
| budget | `{"chat_budget_jpy": 30.0, "daily_budget_jpy": 80.0, "monthly_budget_jpy": 1500.0}` | 2026-03-18 16:22 |

### approval_queue status分布

| request_type | status | count |
|-------------|--------|-------|
| approval_request | auto_approved | 54 |
| approval_request | approved | 37 |
| browser_action | auto_approved | 20 |
| task_approval | approved | 18 |
| bluesky_post | approved | 16 |
| x_post | approved | 15 |
| task_approval | expired | 14 |
| threads_post | approved | 9 |
| approval_request | pending | 8 |
| content | auto_approved | 5 |
| sns_post | approved | 3 |
| task_approval | rejected | 2 |
| test | approved | 2 |
| drafting | auto_approved | 2 |
| analysis | auto_approved | 1 |

### strategy/ ディレクトリ

| ファイル | サイズ | 更新日 |
|---------|-------|--------|
| CHANNEL_STRATEGY.md | 10,806 bytes | 2026-03-17 |
| CONTENT_STRATEGY.md | 12,188 bytes | 2026-03-17 |
| daichi_content_patterns.md | 4,858 bytes | 2026-03-24 |
| daichi_deep_profile.md | 2,159 bytes | 2026-03-23 |
| daichi_writing_style.md | 3,300 bytes | 2026-03-23 |
| ICP_DEFINITION.md | 11,294 bytes | 2026-03-17 |
| 島原大知_詳細プロファイリング超完全版.md | 18,270 bytes | 2026-03-25 |
| 島原大知_深層プロファイル.md | 13,711 bytes | 2026-03-23 |
| 島原大知_人格思想哲学プロファイル.md | 11,221 bytes | 2026-03-23 |

#### 各ファイル先頭5行

**CHANNEL_STRATEGY.md**
```
# CHANNEL_STRATEGY.md
## 0. Purpose
本書は、SYUTAINβの「どこで・どう届けるか」の最終定義です。
特に今回の設計では、チャネルごとの人格衝突を防ぐこと、送客の順番を固定すること、
固定ポストから収益導線までを一気通貫で定義することを重視します。
```

**CONTENT_STRATEGY.md**
```
# CONTENT_STRATEGY.md
## 0. Purpose
本書は、SYUTAINβの「何を話すか・どう話すか」の最終基準です。
今回は特に以下を強化します。
```

**daichi_content_patterns.md**
```
# 島原大知 コンテンツ構造パターン
# 2026-03-24策定 — 実際の記事12本+note2本から抽出
## 1. 構成パターン（全記事共通の骨格）
```

**daichi_deep_profile.md**
```
# 島原大知 深層プロファイル — 人格再現の核心ルール
# SYUTAINβ Brain-α用
# Twitterアーカイブ 2,909件 + 深層分析 から抽出
## 1. 人格の六面体
```

**daichi_writing_style.md**
```
# 島原大知 文体ルール
# Twitterアーカイブ2,909件分析 統合版
# SNS投稿生成時にsystem promptに注入
## 基本統計
```

**ICP_DEFINITION.md**
```
# ICP_DEFINITION.md
## 0. Purpose
この文書は、SYUTAINβのGTM活動における「誰に届けるか」の最終定義です。
単なるペルソナ表ではなく、以下を区別するための基準文書として使います。
```

**島原大知_詳細プロファイリング超完全版.md**
```
# 島原大知 詳細プロファイリングレポート・超完全版
# SYUTAINβ Brain-α / Brain-β 全コンポーネント参照用
# 2026-03-25 作成・統合
```

**島原大知_深層プロファイル.md**
```
# 島原大知 深層プロファイル
# SYUTAINβ persona_memory + Brain-α人格注入用
# Twitterアーカイブ 2,909件 完全分析
# 2026-03-23 作成
```

**島原大知_人格思想哲学プロファイル.md**
```
# 島原大知 人格・思想・哲学プロファイル
# Twitterアーカイブ（3,855ツイート / オリジナル2,909件）から抽出
# SYUTAINβ persona_memory + daichi_writing_style 注入用
# 2026-03-23 分析
```

### daichi_dialogue_log（全8件）

| id | channel | daichi_message | context_level | created_at |
|----|---------|---------------|---------------|------------|
| 9 | discord_dm | 昨日、今日とで関心深いニュースなどはあった？ | standard | 2026-03-26 02:07 |
| 8 | discord_dm | 今、チャット機能で出来ることを教えて | standard | 2026-03-26 02:06 |
| 7 | discord_dm | 保留中の内容見れる？ | standard | 2026-03-26 02:03 |
| 6 | discord_dm | 昨日のSNS投稿で反応良かったのって何？ | standard | 2026-03-26 02:03 |
| 5 | discord_dm | 島原大知について、どれだけ理解出来てる？ | standard | 2026-03-26 02:02 |
| 4 | discord_dm | 貴方の事を教えてほしい | standard | 2026-03-26 01:55 |
| 3 | discord_dm | 今、各エージェントの動きを知りたい | standard | 2026-03-26 01:54 |
| 2 | discord_dm | 今の承認待ちはない？ | standard | 2026-03-26 01:54 |

### intel_items カテゴリ別

| category | count |
|----------|-------|
| ai_model | 495 |
| other | 45 |
| ai_tool | 42 |
| crypto | 14 |
| business | 11 |
| social | 6 |
| competitor | 2 |
| learning_report | 1 |
| security | 1 |

**合計: 617件**

### intel_digest

| id | digest_date | summary |
|----|-------------|---------|
| 1 | 2026-03-24 | 今日の注目: GPT-5 - Wikipedia / DeepSeek V4: Everything We Know About th / Latest ope... |

---

## サマリー

### 健全性スコアカード

| 項目 | 状態 |
|------|------|
| 全サービス稼働 | ✅ 7/7 |
| リモートノード | ✅ 3/3 |
| 24hエラー数 | ⚠️ 7件（LLM 5件, node 1件, SNS 1件） |
| Emergency Stopped | ⚠️ 23件（全て2026-03-25、対策済み） |
| 品質スコア0.00 | ✅ 0件（解消済み） |
| Pending投稿 | ⚠️ 62件（主にThreads/Bluesky） |
| Pending承認 | ⚠️ 8件 |
| 24hコスト | ✅ ¥43.32（日次予算¥80以下） |
| 累計コスト | ✅ ¥336.03（月次予算¥1,500以下） |
| 収益実績 | ❌ ¥0（revenue_linkage空） |
