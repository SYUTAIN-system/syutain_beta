# 週末放置前チェック 2026-03-21

**実行時刻**: 2026-03-21 00:10 JST

## 稼働状態サマリー
- FastAPI: ✅ (ok, postgresql=ok, nats=ok)
- NATS: ✅ (PID=82298, monitoringポート8222は未公開だがサービス稼働中)
- PostgreSQL: ✅ (接続数6)
- Ollama ALPHA: ✅ (qwen3.5:4b, qwen3:4b)
- Ollama BRAVO: ✅ (qwen3.5:9b)
- Ollama CHARLIE: ✅ (qwen3.5:9b)
- Ollama DELTA: ✅ (qwen3.5:4b, /api/chat動作確認済み)
- SNS自動投稿: ✅（直近72h: posted 8件, draft_created 3件）
- 夜間バッチ: ✅（artifacts: 24件、night_batch_20260320_1〜3.md含む）
- 情報収集: ✅（intel_items 376件、最終: 2026-03-21 00:07 — 手動実行で94件追加）
- ディスク: ✅（8%使用、136GB空き）
- エラー（24h）: 14件（llm.error 12件 + sns.post_failed 2件）

## 品質スコア分布
- high (0.70+): 35件
- mid (0.30-0.69): 29件
- low (0.01-0.29): 3件
- zero (0.00): 16件（全て正当理由: 承認待ち/失敗/空テキスト）

## 修正した項目

### 1. 情報収集パイプライン再実行
- **問題**: 最終取得が3/20 02:11（約22時間前）
- **原因**: 前セッションで間隔を6h→12hに変更後、スケジューラー再起動でタイマーリセット
- **修正**: 手動実行で94件取得成功（Gmail:51, Tavily:20, Jina:10, RSS:5, YouTube:8）
- **結果**: intel_items 282件→376件

### 2. サービス再起動（最新.env読み込み）
- **問題**: Threads投稿が「Failed to decrypt」で2件失敗（スケジューラーが古いトークンを保持）
- **修正**: `./start.sh restart`で全サービス再起動、最新の.envを読み込み
- **結果**: FastAPI/Next.js/Caddy/Scheduler全正常起動

## 未修正の問題（月曜対応）
- **Anthropicクレジット**: Haikuは直接テストで成功するが、ルーター経由で一時的に400エラーが出る場合がある。フォールバックで動作は継続。残高が少ない可能性あり。

## エラー詳細
| エラー | 件数 | 原因 | 状態 |
|--------|------|------|------|
| llm.error (DELTA /api/generate 404) | 1 | DELTAの初回ロード時 | 修正不要（/api/chatにフォールバック） |
| llm.error (Anthropic 400) | 2 | クレジット残高低い | フォールバック動作中 |
| llm.error (Gemini Flash Lite 404) | 1 | 廃止モデル参照 | 過去エラー（修正済み） |
| llm.error (google genai import) | 1 | SDK問題 | 過去エラー（修正済み） |
| sns.post_failed (Threads decrypt) | 2 | 古いトークン | 再起動で解消 |

## 月曜に確認すべきこと
- data/artifacts/に土日の夜間バッチ成果物（night_batch_20260321/22）があるか
- SNS投稿件数の増加（Bluesky/X/Threadsそれぞれ）
- intel_itemsの増加（12h間隔で約100件/日の見込み）
- Discordの異常通知有無
- Threadsの投稿成功確認（トークン再起動で解消しているか）
- 品質スコアの新規タスクでの分布
