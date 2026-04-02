# AGENTS_CONTENT - コンテンツ生成サブシステム

## パイプライン

1. ネタ選定: intel_items + persona_memory → テーマ決定
2. strategy/参照: ICP_DEFINITION.md + CHANNEL_STRATEGY.md + CONTENT_STRATEGY.md
3. persona_memory参照: 島原大知の価値観を確認（ルール23）
4. 2段階精錬: ローカルLLM → API精錬（quality < 0.7時）
5. anti_ai_writing.md適用: AI臭の除去
6. 品質スコアリング: 0.70以上で投稿キューへ
7. Content Multiplier: 1素材 → 17派生物

## 品質閾値

- 0.70以上: 自動投稿キュー（pending）
- 0.70未満: rejected
- note記事: stage1(Haiku) + stage2(GPT-5) 2段階品質チェック

## プラットフォーム別制約

- X: 280文字以内
- Bluesky: 300文字以内
- Threads: 500文字以内
- note: 5000字以上（stage1_fatalの閾値）

## 禁止事項

- tabooカテゴリ（persona_memory）の違反
- 架空エピソードの創作
- 経歴詐称
- APIキー・個人情報の混入
