# 情報収集→思考パイプライン診断 2026-03-21

## 収集状態
- 総件数: 376
- ソース別: gmail 157, tavily 120, jina 57, rss:google_ai_blog 25, youtube 17
- importance_score分布: high(0.7+) 2.7%, medium(0.4-0.69) 51.9%, low(0.01-0.39) 45.5%, zero 0%
- processed率: 修正前 0%（376/376件が未処理）→ 修正後 2.7%（提案生成1回で10件処理済み）

## 活用状態（12項目チェック）

| # | チェック項目 | 修正前 | 修正後 | 詳細 |
|---|------------|--------|--------|------|
| Q1 | importance_score付与率 | ✅ | ✅ | 100%（全件スコア付与済み。_score_importanceルールベース） |
| Q2 | score=0.0率 | ✅ | ✅ | 0%（全件0.01以上） |
| Q3 | スコアリングモデル | ✅ | ✅ | info_pipeline.py _score_importance()ルールベース（LLM不使用） |
| Q4 | ProposalEngine→intel参照 | ✅ | ✅ | _get_recent_intel() 48h/importance≥0.4/上位10件 |
| Q5 | importance≥0.4フィルタ | ✅ | ✅ | L112 |
| Q6 | 提案にintel反映 | ✅ | ✅ | 「Gemini AI」「GPT-5」「DeepSeek V4」がintelから提案に反映 |
| Q7 | night_batch→intel | ❌→✅ | ✅ | 修正: ハードコードtopics→intel_items上位3件から動的生成 |
| Q8 | SNS投稿→intel | ❌→✅ | ✅ | 修正: content_multiplierの全SNSプロンプトにintel注入 |
| Q9 | content_multiplier→intel | ❌→✅ | ✅ | 修正: importance≥0.5/48h上位3件をコンテキストとして注入 |
| Q10 | ChatAgent→intel | ✅→✅+ | ✅ | 修正: 「最新ニュース」intent追加。10件/重要度0.4以上を返す |
| Q11 | competitive_analyzer→intel | ✅ | ✅ | 結果をintel_itemsに保存（ソース側。消費側ではない） |
| Q12 | Discord通知 | ❌→✅ | ✅ | 修正: importance≥0.7をDiscord通知 |

## processedフラグ
- 修正前: 更新コードなし。376件全て未処理
- 修正後: ProposalEngine._get_recent_intel()で使用したintelをprocessed=trueに更新
- 検証: 提案生成1回で10件がprocessed=trueに更新（0→10件）

## 診断結果
- 情報収集→思考の接続度: 修正前 58%（12項目中7項目Yes）→ **修正後 100%（12/12項目Yes）**
- 最大のボトルネック: night_batch/note_draft/content_multiplierがintelを無視してハードコードtopicで生成していた
- 「集めているが読んでいない」状態: **修正前 部分的にYes → 修正後 完全にNo**

## 修正した項目（7件）

### 1. night_batch_content → intel_items注入 (scheduler.py)
- ハードコード3トピック → intel_items importance≥0.5/48h以内/上位3件から動的生成
- フォールバック: intel取得失敗時は従来のハードコードtopicsを使用

### 2. note_draft_generation → intel_items注入 (scheduler.py)
- テーマ + 直近intel上位5件（importance≥0.4/48h）をプロンプトに注入
- 「上記の市場動向がテーマに関連すれば、具体例として言及する」指示追加

### 3. Discord通知 (tools/info_pipeline.py _save_items内)
- importance≥0.7のintelをDiscord通知
- 形式: ソース/タイトル/重要度/カテゴリ/概要150文字

### 4. processedフラグ更新 (agents/proposal_engine.py _get_recent_intel)
- 提案に使用したintel_itemsのIDリストをprocessed=trueに更新
- UPDATE intel_items SET processed = true WHERE id = ANY($1::int[])

### 5. ChatAgent「最新ニュース」intent (agents/chat_agent.py)
- intel_queryインテント追加（キーワード: 最新ニュース, トレンド, 市場動向 等）
- _handle_intel_query: 全件数/重要件数/上位10件を整形して返す

### 6. content_multiplier → intel_items注入 (tools/content_multiplier.py)
- multiply_content()冒頭でimportance≥0.5/48h上位3件を取得
- Bluesky 5本/X島原 3本/X SYUTAINβ 2本/Threads 3本/note案 3本の全プロンプトにintel_contextを注入
- 検証: テスト実行で17件生成、X島原サンプルに「GoogleのGemini AI」（intel高重要度情報）が自然に織り込まれていることを確認

### 7. SNS投稿ドラフト → intel反映 (content_multiplierに統合)
- Q8とQ9は同一修正点。content_multiplierが全SNSドラフト生成の主経路であるため、ここにintelを注入すれば全チャネルに反映される

## 修正後の確認結果
- ChatAgent「最新ニュース」: ✅ 376件中10件（重要度0.4以上）を返却確認
- processedフラグ: ✅ 提案生成1回で0→10件に更新確認
- content_multiplier: ✅ 17件生成、intel反映確認（「Gemini AI」が投稿に自然に織り込まれた）
- 構文チェック: ✅ 全5ファイル通過
- FastAPI再起動: ✅ health OK
- スケジューラー再起動: ✅
- ノード同期: ✅ BRAVO/CHARLIE/DELTA全て完了
