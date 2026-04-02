# AGENTS_SAFETY - 安全機構サブシステム

## 9層LoopGuard

| 層 | 名前 | トリガー | アクション |
|----|------|---------|----------|
| 1 | Retry Budget | 同一アクション3回 | ESCALATE |
| 2 | Same-Failure Cluster | 同型エラー2回 | 30分凍結 |
| 3 | Planner Reset | 再計画3回超 | ESCALATE |
| 4 | Value Guard | 価値根拠なし | SKIP |
| 5 | Approval Deadlock | 24時間待機超 | リマインド→代替 |
| 6 | Cost & Time | 予算80%/60分超/10万トークン超 | AUTO_STOP |
| 7 | Emergency Kill | 50ステップ/予算90%/エラー5回/2時間超 | KILL |
| 8 | Semantic Loop | 意味的繰り返し3回 | SEMANTIC_STOP |
| 9 | Cross-Goal干渉 | リソース競合 | INTERFERENCE_STOP |

## Emergency Kill条件（絶対厳守）

1. 単一Goal: 50ステップ超過
2. 日次予算: 90%消費
3. 同一エラー: 5回繰り返し
4. タスク時間: 2時間超過
5. セマンティックループ検出
6. Cross-Goal干渉検出

## 承認Tier

- Tier 1（人間必須）: SNS投稿、商品公開、価格設定、暗号通貨取引
- Tier 2（自動+通知）: 情報パイプライン、モデル切替
- Tier 3（完全自動）: ヘルスチェック、ログローテーション

## Harness Linter

タスク実行後に自動チェック:
- ルール5: choose_best_model_v6()使用確認
- ルール7: try-except適用確認
- ルール8: APIキー漏洩チェック
- ルール10: strategy/参照確認
- ルール11: 承認必須アクションの承認確認

## Auto-Fix Engine

エラー発生 → パターン分類 → auto_fix_rulesに登録 → 次回自動回避
