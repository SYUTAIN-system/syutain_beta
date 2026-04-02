# SYUTAINβ SYSTEM_STATE.md
> 自動生成: 2026-04-02 18:23:08 JST
> このファイルはClaude Codeセッション開始時に最初に読むべきファイル

## システム概要
- プロジェクト: ~/syutain_beta
- 設計書: SYUTAINβ_完全設計書_V25.md
- 実装仕様: docs/IMPLEMENTATION_SPEC.md
- 絶対ルール: CLAUDE.md（22条）
- SSH: BRAVO=shimahara@100.75.146.9 / CHARLIE=shimahara@100.70.161.106 / DELTA=shimahara@100.82.81.105

## ノード構成
| ノード | IP | worker | nats | ollama | LLMモデル | GPU |
|--------|-----|--------|------|--------|-----------|-----|
| ALPHA | local | 5procs | ok | - | MLX(on-demand) | M4 Pro |
| BRAVO | 100.75.146.9 | active | active | active | hf.co/mmnga-o/NVIDIA-Nemotron-Nano-9B-v2-Japanese-GGUF:Q5_K_M,nemotron-jp:latest,nemotron-mini:latest,qwen3.5:9b | RTX5070-12GB |
| CHARLIE | 100.70.161.106 | active | active | activating
? | nemotron-jp:latest,qwen3.5:9b,hf.co/mmnga-o/NVIDIA-Nemotron-Nano-9B-v2-Japanese-GGUF:Q5_K_M | RTX3080-10GB |
| DELTA | 100.82.81.105 | active | active | active | qwen3.5:4b | GTX980Ti-6GB |

## サービス状態
- FastAPI: ok (:8000)
- Next.js: HTTP 200 (:3000)
- Caddy: :8443 (HTTPS)

## DB統計
| テーブル | 件数 |
|----------|------|
| goal_packets | 94 |
| tasks | 1030 |
| proposal_history | 66 |
| intel_items | 1266 |
| chat_messages | 224 |
| llm_cost_log | 9521 |
| approval_queue | 351 |
| event_log | 29277 |
| revenue_linkage | 0 |
| browser_action_log | 7285 |

## LLM使用率
- api: 1433件 (15.1%)
- local: 8088件 (84.9%)

## API接続状態
- DEEPSEEK_API_KEY: SET
- ANTHROPIC_API_KEY: SET
- OPENAI_API_KEY: SET
- GEMINI_API_KEY: SET
- OPENROUTER_API_KEY: SET
- BLUESKY_APP_PASSWORD: SET
- TAVILY_API_KEY: SET
- JINA_API_KEY: SET
- YOUTUBE_API_KEY: SET
- DISCORD_WEBHOOK_URL: SET

## Schedulerジョブ
| ジョブ | 間隔/時刻 |
|--------|-----------|
| ハートビート | 30秒 |
| Capability Audit | 1時間 |
| 情報収集パイプライン | 6時間 |
| intel_items自動レビュー | 6時間 |
| 日次提案生成 | 毎日 07:00 |
| 週次提案生成 | 月曜 09:00 |
| リアクティブ提案 | 6時間 |
| 週次学習レポート | 日曜 21:00 |
| 孤立タスク再ディスパッチ | 5分 |
| SNS生成1: X島原+SYUTAIN 10件 | 22:00 |
| SNS生成2: Bluesky前半13件 | 22:30 |
| SNS生成3: Bluesky後半13件 | 23:00 |
| SNS生成4: Threads13件 | 23:30 |
| 日次コンテンツ#1 海外トレンド先取り | 07:30 |
| 日次コンテンツ#2 実データベース | 12:00 |
| 日次コンテンツ#3 自由テーマ | 18:00 |
| SYSTEM_STATE.md更新 | 1時間 |
| 運用ログ生成 | 00:00 |
| PostgreSQLバックアップ | 03:00 |
| 暗号通貨価格取得 | 30分 |
| コスト予測 | 6時間 |
| Blueskyエンゲージメント取得 | 12時間 |
| Xエンゲージメント取得 | 12時間 |
| Threadsエンゲージメント取得 | 12時間 |
| エンゲージメント分析 | 毎日06:30 |
| モデル品質キャッシュ更新 | 1時間 |
| SQLiteバックアップ | 03:30 |
| デジタルツイン問いかけ | 水土20:00 |
| 夜間モード切替 | 23:00 |
| 日中モード切替 | 07:00 |
| 夜間バッチ生成 | 23:30 |
| 週次商品化候補生成 | 金曜23:15 |
| note記事ドラフト生成 翌日向け | 23:45 |
| 競合分析 | 日曜03:00 |
| 承認タイムアウトチェック | 1時間 |
| 提案自動承認→ゴール変換 | 30分 |
| brain_handoff期限切れ処理 | 日次 |
| posting_queue自動投稿 | 毎分 |
| Brain-α相互評価 | 毎日06:00 |
| 自律修復チェック | 5分 |
| データ整合性チェック | 毎日04:00 |
| Brain-αセッション監視 | 10分 |
| ノードヘルスチェック | 5分 |
| 異常検知 | 5分 |
| 動的キーワード更新 | 毎日06:00 |
| intel_digest生成 | 毎日07:00 |
| 深掘り記事取得バッチ | 毎日12:00 |
| 対話学習 | 1時間 |
| note記事品質チェック | 30分 |
| 日次サマリーDiscord通知 | 20:30 |
| 商品パッケージング | 1時間 |
| 経営日報 | 毎日07:05 |
| エンゲージメント分析 | 毎日06:30 |
| 海外トレンド検出 | 毎日08:00 |
| ドキュメンタリー記事生成#1 | 毎週水曜10:00 |
| ドキュメンタリー記事生成#2 | 毎週土曜10:00 |
| バズ分析 | 毎週月曜07:30 |
| 収益機会リサーチ | 毎月1日04:00 |
| セマンティックキャッシュ清掃 | 毎日04:15 |
| Karpathy自律改善 | 毎日05:00 |
| 収益パイプラインチェック | 毎日07:30 |
| ゴミ収集 | 毎週月曜05:00 |
| フィーチャーテスト | 毎日05:30 |
| ドキュメントガーデニング | 日曜04:00 |
| note.com自動公開チェック | 30分 |
| ログクリーンアップ | 毎日04:30 |
| 承認キュー自動クリーンアップ | 毎日05:00 |
| メモリ統合 | 毎日03:45 |
| 海外トレンド検出 | 毎日08:00 |
| スキル抽出 | 毎日04:00 |
| ハーネス健全性スコア | 毎時 |

## 収益パイプライン (Stage 1-11)
- Stage1 情報収集: 226件(24h)
- Stage3 提案: 28件(7d)
- Stage5 ゴール: 1件active
- Stage6 タスク: 804件成功
- Stage8 品質平均: 0.66
- Stage9 成果物: 57件
- Stage10 SNS: 443件
- Stage11 収益: ¥0

## 直近エラー (24h)
- sns.post_failed [alpha] An unexpected error has occurred. Please retry your request later.

## 自動検出された課題
- 問題なければここは空

## 直近セッション引き継ぎ
- SESSION_HANDOFF_2026-03-23.md: *2026-03-23 総合デバッグ70件+Brain-α検証修正12件。Phase 1-9完了。全サービス稼働中。ローカル83%、7日間コスト¥201。persona_memory embedding 100%。*
- SESSION_HANDOFF_2026-03-20_O.md: *2026-03-20 LLMルーティング最適化。ローカル率71%達成。DELTA活用開始。情報収集12h間隔に変更。35ジョブ稼働中。*
- SESSION_HANDOFF_2026-03-20_FINAL.md: *2026-03-20 全日セッション統合。CRITICAL3件修正+SNS 4チャネル自動投稿+品質改善+アンチAI文体+デジタルツイン124件+content_multiplier 17件展開。35ジョブ・4ノード全て稼働中。*

---
*自動生成完了: 2026-04-02 18:23:08 JST (     151行)*

## Harness Health Score: 81/100 (Grade B)
- node_availability: 100/100 — 正常ノード: 4/4
- task_success_rate: 100/100 — 成功7/失敗0 (率100%)
- sns_delivery_rate: 86/100 — 投稿33/失敗5 (率87%)
- budget_utilization: 15/100 — 本日API支出: ¥101.1/¥120 (84%)
- error_rate: 99/100 — エラー1/2358件 (率0.0%)
- quality_average: 15/100 — 平均品質: 0.16 (66件)
- memory_health: 100/100 — persona=537, episodic=102, session=137

**Recommendations:**
- API予算の消費が激しいです。コスト最適化を検討してください
- タスク品質スコアが低下しています。2段階精錬の適用率を確認してください
