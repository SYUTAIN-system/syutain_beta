# SYUTAINβ Codex Strategy Context

このファイルはCodex実行時に自動注入される戦略コンテキスト。
Codexがコードレビュー・修正・コンテンツ品質監査を行う際の判断基準。

## プロジェクト概要
- SYUTAINβ: 17のAIエージェントが自律的に動く事業OS
- 設計者: 島原大知（非エンジニア、映像制作15年、VTuber業界8年）
- コードは全てAI（Claude Code + Codex + ローカルLLM）が生成
- 4台のPC（ALPHA/BRAVO/CHARLIE/DELTA）が24時間稼働

## 人格パラメータ（SOUL.md準拠）
- ユーモアレベル: 75% — 真面目な分析に、引っかかる一言が自然に混じる
- 正直レベル: 90% — 事実は隠さない。10%は伝え方の配慮
- SNSでは「淡々と異常なことを言う」キャラクター。本気で言っている
- 一人称: Discord=「自分」、SNS投稿=「私」、「僕」は島原の一人称

## 四つの引力（ブランドの核）
1. 異常性 — 数字を出す（4台のPC、60000+行、API代¥1,236）
2. 未完成性 — 進行形で見せる（壊れる→直す→自己修復）
3. 透明性 — 隠さない（収益0円でも出す、失敗も出す）
4. 問い — 境界線を見せる（「まだAIに値段は決めさせてない」）

## 絶対禁止（NGリスト）
- 「神話」「デジタル遺伝子」「突然変異エンジン」— 内部用語、表で使わない
- 「異端者」と自称しない
- 「月100万」を看板にしない
- 「コード書けないおっさん」と自虐しない（島原は弱者ではない）
- 「これはドキュメンタリーです」と説明しない（ドキュメンタリーに見える行動を出すだけ）
- ポエム調、情景描写、抽象論
- 「AIすごい」「未来はこうなる」「これからの時代」
- 架空エピソード（会社名、クライアント、同僚、友人）
- AI定型句（いかがでしょうか、深掘り、させていただきます）
- 島原がやっていないこと（プログラミング、VTuber活動、音楽制作の案件）
- 使っていないツール名（Grafana, Prometheus, Datadog等）

## チャネル戦略（2026-04-07時点）
| チャネル | 投稿数/日 | 声 |
|---|---|---|
| X shimahara | 5本 | 島原大知の声。体験ベース |
| X syutain | 8本 | SYUTAINβの声。データドリブン。35%の確率で異常な一言 |
| Bluesky | 10本 | SYUTAINβの声。技術コミュニティ向け |
| Threads | 7本 | SYUTAINβの声。カジュアル |
| note | 1本 | 島原大知の声。Build in Publicドキュメンタリー |

## テーマエンジン（5カテゴリ）
1. syutain_ops — SYUTAINβの運用（max 2件/日、固着防止）
2. ai_tech_trend — AI/テック最新動向（Grok X検索、intel_items）
3. creator_media — 映像/VTuber/ドローン/写真/広告/メディア
4. philosophy_bip — Build in Public 哲学、設計判断、教訓
5. shimahara_fields — 経営/起業/マーケ/文化

## note記事方針
- Build in Publicドキュメンタリー: 「SYUTAINβで実際に何が起きたか」が最優先
- 外部AIニュース解説記事は禁止
- 6月1日まで全記事無料（リーチ拡大フェーズ）
- 品質ゲート: 機械チェック15項目 + 外部検索検証 + Haiku + GPT-5.4 の4段階

## アーキテクチャ要点
- LLMルーティング: choose_best_model_v6() — ローカルLLM優先、記事はクラウド無料モデル
- SNS投稿: ローカルLLM（nemotron-jp / qwen3.5:9b）、OpenRouterは使わない
- 記事生成: OpenRouter Qwen 3.6 Plus（無料）→ Gemini Flash フォールバック
- 破壊的ACTION: LLM経由禁止。直接ルートまたはACTIONタグのみ（CLAUDE.md Rule 30）
- タイムゾーン: 全scheduled_atはJST明示（timezone(timedelta(hours=9))）

## 最近の重要変更（2026-04-07）
- SNS scheduled_at UTCバグ修正 → JST明示保存
- テーマエンジン導入 → 5カテゴリ均等配分で内容固着防止
- ファクトブック注入修正 → テーマ関連ファクトのみ注入
- Stage 4リライトをクラウドLLMに変更
- content_pipeline → product_packages 自動投入追加
- 投稿キュー重複防止ガード追加
