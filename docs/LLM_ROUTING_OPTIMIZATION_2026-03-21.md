# LLMルーティング最適化 2026-03-21

## 現状（累計 ≠ 現在の動作）
- ローカル使用率（累計）: 46.9% — **ただしこれは最適化前のデータを含む**
- DeepSeek累計128回は最適化前（3/20 23:00以前）のルーティングによるもの

## 最適化済みルーティング（3/20 23:48に適用）

### シミュレーション結果: **ローカル率90%**

全20パターン（ローカル可能18 + 不可2）でテスト:
- DELTA（qwen3.5:4b）: classification/tagging/compression/monitoring → 4パターン
- BRAVO/CHARLIE（qwen3.5-9b）: content/drafting/analysis/research/proposal/chat/coding等 → 14パターン
- API: ローカル不可時のみ（Gemini Flash / Claude Haiku）→ 2パターン

### 最適化の内訳

| 変更 | Before | After | 効果 |
|------|--------|-------|------|
| chatタスク | Gemini Flash | ローカル（BRAVO/CHARLIE） | コスト¥0化 |
| デフォルトフォールバック | DeepSeek V3.2 | ローカル | コスト¥0化 |
| DELTA活用 | 未使用（2回） | classification/tagging等に積極活用 | 分散負荷 |
| batch_process/bulk_draft | Gemini Flash | ローカル | コスト¥0化 |
| quality="low" | 条件分岐 | 強制ローカル | 漏れなし |

### 追加修正なし
前セッションで_LOCAL_MEDIUM_TASKSに17タスクタイプ、_DELTA_TASKSに10タスクタイプを定義済み。
シミュレーション結果90%は十分であり、追加修正は不要。

## 期待される効果
- ローカル使用率: 46.9%（累計）→ 推定85-90%（今後の新規呼び出し）
- 月間コスト削減: DeepSeek ¥10/週 → ¥1/週（推定）
- API使用: final_publish/quality_verification/ローカル不可時のみ
