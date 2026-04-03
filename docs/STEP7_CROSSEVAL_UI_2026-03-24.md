# STEP7: Brain-α相互評価エンジン + Web UI

**実施日**: 2026-03-23 16:30〜17:00 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. brain_alpha/cross_evaluator.py

| # | 関数 | 機能 | テスト |
|---|------|------|-------|
| 1 | evaluate_alpha_fix(id) | auto_fix_logの修正効果を24h後検証。エラー再発+品質変化を計測 | OK (verdict=regression, score=0.10) |
| 2 | evaluate_alpha_review(id) | review_logのスコア修正を後追い検証。後続品質と比較 | OK (accuracy=correct_downgrade, score=0.80) |
| 3 | schedule_evaluations() | 24h以上前の未評価レコードを自動評価 | OK (fixes=1, reviews=0) |

### 評価ロジック

**修正効果 (auto_fix)**:
- エラー減少 + 品質維持/向上 → `effective` (0.6-1.0)
- エラー0 → `neutral` (0.5)
- エラー増加 → `regression` (0.0-0.3)
- 判定不能 → `inconclusive` (0.5)

**レビュー効果 (review)**:
- 下方修正 + 後続品質低い → `correct_downgrade` (0.8)
- 下方修正 + 後続品質高い → `unnecessary_downgrade` (0.3)
- 上方修正 + 後続品質高い → `correct_upgrade` (0.8)
- 上方修正 + 後続品質低い → `overestimated` (0.4)

## 2. scheduler.pyジョブ追加

- `brain_cross_evaluate` 毎日06:00 → schedule_evaluations()実行

## 3. API追加

| メソッド | エンドポイント | テスト |
|---------|--------------|-------|
| GET | /api/brain-alpha/cross-evaluations?limit=N | OK (2件) |

## 4. Web UI更新

| ページ | 追加要素 | HTTP |
|-------|---------|------|
| /brain-alpha | 相互評価セクション: score色分け（0.7+緑, 0.4-0.69黄, 0.4未満赤）、verdict/accuracyバッジ | 200 |
| /models | Brain-α品質修正検証セクション: 修正履歴、品質変化/エラー変化表示 | 200 |

## 5. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| brain_alpha/cross_evaluator.py | **新規**: 相互評価エンジン3関数 |
| scheduler.py | brain_cross_evaluate日次ジョブ追加 |
| app.py | cross-evaluations APIエンドポイント追加 |
| web/src/app/brain-alpha/page.tsx | 相互評価セクション追加 |
| web/src/app/models/page.tsx | Brain-α品質修正検証セクション追加 |

## 6. 検証結果

```
evaluate_alpha_fix(2): verdict=regression, score=0.10, error_improvement=-2 ✅
evaluate_alpha_review(2): accuracy=correct_downgrade, score=0.80 ✅
schedule_evaluations(): fixes=1, reviews=0 ✅
GET /api/brain-alpha/cross-evaluations: 2件取得 ✅
テストデータ削除: 完了 ✅
/brain-alpha: 200 ✅
/models: 200 ✅
```

---

## 接続先URL

```
HTTPS: https://100.x.x.x:8443/
Brain-α: https://100.x.x.x:8443/brain-alpha
モデル: https://100.x.x.x:8443/models
```
