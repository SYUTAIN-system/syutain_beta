# SYUTAINβ セッション引き継ぎ資料

**作成日**: 2026-03-20
**最終更新**: 2026-03-20 01:55 JST
**作成者**: Claude Opus 4.6 (1M context)

---

## 1. 本セッションの成果

### orphanタスク修正効果検証 [確認済み]
- LLMルーティング: BRAVO→CHARLIE→BRAVOラウンドロビン正常動作
- worker_main.pyタスクタイプ拡張: browser_action, coding, analysis, research, strategy, proposal, note_article, booth_description, batch等を追加
- 前セッションの`type`フィールド修正+今回のタイプ拡張で棄却率大幅低下

### Ollama最適化 [全3ノード完了]
- BRAVO: OLLAMA_NUM_PARALLEL=4, KEEP_ALIVE=24h, active
- CHARLIE: OLLAMA_NUM_PARALLEL=4, KEEP_ALIVE=24h, active
- DELTA: OLLAMA_NUM_PARALLEL=2, KEEP_ALIVE=24h, active
- 全ノードHOST=0.0.0.0設定でTailscale経由アクセス許可

### 時間帯別パワーモード [実装済み]
- 夜間モード（23:00-07:00）: フルパワー、並列推論、バッチ生成
- 日中モード（07:00-23:00）: 省エネ、リアクティブ優先
- GPU温度監視: ヘルスチェックでnvidia-smi温度取得、閾値超えで警告イベント
- scheduler.pyにpower_mode切替ジョブ登録済み

### 夜間バッチジョブ [実装済み]
- 23:30 JST: 夜間バッチコンテンツ生成（Best-of-N並列、3トピック）
- 23:45 JST: note記事ドラフト自動生成（曜日別テーマ）
  - 月曜: 週次収益報告
  - 火/金: AI活用Tips
  - 水/木: AI開発失敗談
  - 土: 週末まとめ
  - 日: 自由テーマ
- 保存先: data/artifacts/note_drafts/
- 品質高ければDiscord通知

### Best-of-N並列生成 [実装・テスト済み]
- call_llm_parallel(): BRAVO+CHARLIEに同時送信
- 簡易品質スコア（日本語率+テキスト長）で最良を選択
- テスト: charlie選択（220chars）、bravo代替（277chars）

### ローカルLLM使用率向上 [実装済み]
- choose_best_model_v6()でローカル優先タスクタイプを大幅拡大
- 追加: coding, analysis, proposal, note_article, product_desc, booth_description, quality_scoring, content(medium/low)
- API専用: strategy(高品質時のみ), chat, btob, pricing
- ローカルLLMコスト記録: llm_cost_logにcost=0で記録するように修正
- 直近1時間実測: **ローカル50% / API50%**（改善前: 13%）

### 根本バグ修正
1. worker_main.pyタスクタイプ拡張（browser_action, coding等17タイプ追加）
2. ローカルLLM呼び出しのllm_cost_log記録追加

---

## 2. 現在のスケジューラージョブ一覧（15ジョブ）

| ジョブ | 間隔/時刻 | 説明 |
|--------|-----------|------|
| ハートビート | 30秒 | NATS heartbeat + CPU/MEM |
| 孤立タスク再ディスパッチ | 5分 | pending>30分のタスク再送 |
| ノードヘルスチェック | 5分 | Ollama+GPU温度+CPU/MEM |
| 異常検知 | 5分 | error3件/5分→Discord |
| Capability Audit | 1時間 | 全ノード能力スナップショット |
| 日次提案 | 07:00 | 自動提案生成 |
| 日中モード切替 | 07:00 | 省エネモード |
| 情報収集 | 6時間 | Tavily+Jina+RSS |
| リアクティブ提案 | 6時間 | 機会検出 |
| Blueskyドラフト | 8時間 | 投稿ドラフト+重複チェック |
| 夜間モード切替 | 23:00 | フルパワーモード |
| 夜間バッチ生成 | 23:30 | Best-of-N並列コンテンツ |
| note記事ドラフト | 23:45 | 曜日別テーマ |
| 週次学習レポート | 日曜21:00 | 学習データ集計 |
| 週次提案 | 月曜09:00 | 今週やるべき3手 |

---

## 3. 残存課題

### 優先度: 高
1. vLLMテスト未実施（Ollama最適化の効果確認が先）
2. data/artifacts/の成果物が少ない（夜間バッチで蓄積開始予定）

### 優先度: 中
3. Stripe未設定
4. pgvector未有効化
5. Booth出品フローの自動化

---

## 4. 接続情報

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
```

---

*2026-03-20 ローカルLLM最適化完了。Ollama並列化。時間帯別パワーモード。Best-of-N並列生成。note記事ドラフト自動生成。ローカルLLM使用率13%→50%。*
