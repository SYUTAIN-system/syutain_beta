# SYUTAINβ SYSTEM_STATE.md
> 自動生成: 2026-03-28 01:04:35 JST
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
| goal_packets | 72 |
| tasks | 690 |
| proposal_history | 44 |
| intel_items | 677 |
| chat_messages | 224 |
| llm_cost_log | 6359 |
| approval_queue | 231 |
| event_log | 17136 |
| revenue_linkage | 0 |
| browser_action_log | 7282 |

## LLM使用率
- api: 900件 (14.2%)
- local: 5459件 (85.8%)

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
| 日次コンテンツ生成 | 09:30 |
| SYSTEM_STATE.md更新 | 1時間 |
| 運用ログ生成 | 00:00 |
| PostgreSQLバックアップ | 03:00 |
| 暗号通貨価格取得 | 30分 |
| コスト予測 | 6時間 |
| Blueskyエンゲージメント取得 | 12時間 |
| Xエンゲージメント取得 | 12時間 |
| Threadsエンゲージメント取得 | 12時間 |
| モデル品質キャッシュ更新 | 1時間 |
| SQLiteバックアップ | 03:30 |
| デジタルツイン問いかけ | 水土20:00 |
| 夜間モード切替 | 23:00 |
| 日中モード切替 | 07:00 |
| 夜間バッチ生成 | 23:30 |
| 週次商品化候補生成 | 金曜23:15 |
| note記事ドラフト生成 | 23:45 |
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

## 収益パイプライン (Stage 1-11)
- Stage1 情報収集: 60件(24h)
- Stage3 提案: 32件(7d)
- Stage5 ゴール: 0件active
- Stage6 タスク: 484件成功
- Stage8 品質平均: 0.70
- Stage9 成果物: 42件
- Stage10 SNS: 265件
- Stage11 収益: ¥0

## 直近エラー (24h)
- llm.error [bravo] ReadTimeout(no message)

## 自動検出された課題
- 問題なければここは空

## 直近セッション引き継ぎ
- SESSION_HANDOFF_2026-03-23.md: *2026-03-23 総合デバッグ70件+Brain-α検証修正12件。Phase 1-9完了。全サービス稼働中。ローカル83%、7日間コスト¥201。persona_memory embedding 100%。*
- SESSION_HANDOFF_2026-03-20_O.md: *2026-03-20 LLMルーティング最適化。ローカル率71%達成。DELTA活用開始。情報収集12h間隔に変更。35ジョブ稼働中。*
- SESSION_HANDOFF_2026-03-20_FINAL.md: *2026-03-20 全日セッション統合。CRITICAL3件修正+SNS 4チャネル自動投稿+品質改善+アンチAI文体+デジタルツイン124件+content_multiplier 17件展開。35ジョブ・4ノード全て稼働中。*

---
*自動生成完了: 2026-03-28 01:04:35 JST (     127行)*
