# AGENTS_LLM - LLMルーティングサブシステム

## choose_best_model_v6() ルーティング

### ローカルモデル（¥0）

| モデル | ノード | 用途 |
|--------|--------|------|
| qwen3.5-9b | BRAVO/CHARLIE | ドラフト、SNS、チャット、分析 |
| qwen3.5-4b | DELTA | タグ付け、分類、圧縮、キーワード抽出 |
| nemotron-jp | BRAVO/CHARLIE | 日本語コンテンツ生成（優先） |
| qwen3.5-9b-mlx | ALPHA | BRAVO/CHARLIE両方ビジー時のみ |

### APIモデル

| モデル | コスト(¥/1K tok) | 用途 |
|--------|------------------|------|
| gemini-2.5-flash | ¥0.0021 | コンテンツレビュー |
| claude-haiku | ¥0.003 | 提案生成、品質精錬 |
| deepseek-v3.2 | ¥0.063 | 最終コンテンツのみ |
| gpt-5.4 | ¥2.25 | Computer Use、複雑計画 |

## 2段階精錬パイプライン

1. Stage 1（ローカル）: 高速ドラフト（¥0）
2. Stage 2（API）: quality < 0.7 の場合のみAPI精錬
3. 自動エスカレーション: 品質0.3-0.7の範囲でAPI介入

## 制約

- ALPHA MLXはオンデマンド起動のみ（メモリ制約）
- 日次予算¥80を厳守（DAILY_API_BUDGET_JPY）
- model_quality_logから14日間の実績を参照してルーティング最適化
