# SYUTAINβ SYSTEM_STATE.md
> 自動生成: 2026-03-23 14:14:28 JST
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
| BRAVO | 100.75.146.9 | active | active | active | qwen3.5:9b | RTX5070-12GB |
| CHARLIE | 100.70.161.106 | active | active | active | qwen3.5:9b | RTX3080-10GB |
| DELTA | 100.82.81.105 | active | active | active | qwen3.5:4b | GTX980Ti-6GB |

## サービス状態
- FastAPI: ok (:8000)
- Next.js: HTTP 200 (:3000)
- Caddy: :8443 (HTTPS)

## DB統計
| テーブル | 件数 |
|----------|------|
| goal_packets | 20 |
| tasks | 114 |
| proposal_history | 29 |
| intel_items | 497 |
| chat_messages | 224 |
| llm_cost_log | 2080 |
| approval_queue | 62 |
| event_log | 5917 |
| revenue_linkage | 0 |
| browser_action_log | 3916 |

## LLM使用率
- api: 383件 (18.4%)
- local: 1697件 (81.6%)

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
| 日次提案生成 | 毎日 07:00 |
| 週次提案生成 | 月曜 09:00 |
| リアクティブ提案 | 6時間 |
| 週次学習レポート | 日曜 21:00 |
| 孤立タスク再ディスパッチ | 5分 |
| Bluesky投稿ドラフト生成 | 6時間 |
| X投稿ドラフト生成 SYUTAINβ | 8時間 |
| X投稿ドラフト生成 島原 | 12時間 |
| Threads投稿ドラフト生成 | 8時間 |
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
| ノードヘルスチェック | 5分 |
| 異常検知 | 5分 |

## 収益パイプライン (Stage 1-11)
- Stage1 情報収集: 61件(24h)
- Stage3 提案: 29件(7d)
- Stage5 ゴール: 0件active
- Stage6 タスク: 70件成功
- Stage8 品質平均: 0.67
- Stage9 成果物: 30件
- Stage10 SNS: 31件
- Stage11 収益: ¥0

## 直近エラー (24h)
- sns.post_failed [alpha] API access blocked.
- sns.post_failed [alpha] Server error '502 Bad Gateway' for url 'https://bsky.social/xrpc/com.atproto.repo.createRecord'+
- For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502
- sns.post_failed [alpha] API access blocked.
- sns.post_failed [alpha] API access blocked.

## 自動検出された課題
- 問題なければここは空

## 直近セッション引き継ぎ
- SESSION_HANDOFF_2026-03-20_O.md: *2026-03-20 LLMルーティング最適化。ローカル率71%達成。DELTA活用開始。情報収集12h間隔に変更。35ジョブ稼働中。*
- SESSION_HANDOFF_2026-03-20_FINAL.md: *2026-03-20 全日セッション統合。CRITICAL3件修正+SNS 4チャネル自動投稿+品質改善+アンチAI文体+デジタルツイン124件+content_multiplier 17件展開。35ジョブ・4ノード全て稼働中。*
- SESSION_HANDOFF_2026-03-20_N.md: *2026-03-20 Threads API実装完了。ドラフト生成+承認キュー投入成功。実投稿はトークン再取得待ち。35ジョブ稼働中。*

---
*自動生成完了: 2026-03-23 14:14:28 JST (     115行)*
