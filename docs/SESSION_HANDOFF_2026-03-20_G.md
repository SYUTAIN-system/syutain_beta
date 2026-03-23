# SYUTAINβ セッション引き継ぎ資料

**作成日**: 2026-03-20
**最終更新**: 2026-03-20 04:30 JST
**作成者**: Claude Opus 4.6 (1M context)

---

## 1. 修正したバグ

### A. 承認/却下が再出現する無限ループ
- **原因**: `app.py:803` 承認後にタスクを`pending`に戻していた → 5分毎の孤立タスク再ディスパッチが再検出 → 新規approval_queue INSERT → 無限ループ
- **修正**: 承認後ステータスを`completed`(approval_request) / `running`(その他)に変更。scheduler側に重複INSERT防止ロジック追加。`conn`スコープ外使用バグも修正
- **ファイル**: `app.py:803`, `scheduler.py:519-538`, `app.py:820`

### B. ダッシュボード成果物に中間タスク表示
- **修正**: `DISTINCT ON (goal_id)` で各ゴールの最終タスクのみ表示
- **ファイル**: `app.py:556`

### C. タスク詳細モーダル iPhone対応
- **修正**: iOS Safari対応（背景/モーダル分離、onTouchEnd、WebkitOverflowScrolling、固定ヘッダー/フッター、92dvh）
- **ファイル**: `web/src/app/tasks/page.tsx:228-`

## 2. チャットシステム大幅改修

### A. 会話の連続性
- **原因**: `get_chat_history`が最古10件を返していた
- **修正**: サブクエリで最新N件を時系列順に返す
- **ファイル**: `agents/chat_agent.py:712-734`

### B. 情報収集結果（intel_items）のチャット活用
- **修正**: `_get_relevant_intel()` 新設。キーワード抽出→intel_itemsマッチ→プロンプト注入
- **ファイル**: `agents/chat_agent.py`

### C. ベクトル検索長期記憶の接続
- **基盤**: pgvector 0.8.2 + Jina Embeddings v3（1024dim）は既にインストール済みだった
- **修正**: `_get_persona_memory()` / `_extract_and_store_memory()` 新設。会話からLLMで記憶抽出→ベクトル化→persona_memoryに保存。次回会話時にベクトル検索でリコール
- **現在のpersona_memory**: 5件（philosophy×4, judgment×1）全てベクトル化済み
- **ファイル**: `agents/chat_agent.py`, `tools/embedding_tools.py`

### D. 人格強化
- **修正**: `_build_system_prompt()` 新設。人格指針・記憶の使い方・情報の使い方・禁止事項を統合
- **ファイル**: `agents/chat_agent.py`

## 3. モデル選定システム修正

### 設計原則（島原より）
> モデルは手段であり、適材適所でタスクや状況に応じて選定する。モデルに依存しないのはSYUTAINβのシステム全体の設計思想。

### 修正箇所
| ファイル | 問題 | 修正 |
|---------|------|------|
| `two_stage_refiner.py:138-144` | BRAVO/CHARLIEモデル名ハードコード | `choose_best_model_v6()`に変更 |
| `two_stage_refiner.py:173-176` | DELTAモデル名ハードコード | 同上 |
| `two_stage_refiner.py:209-219` | API精錬先ハードコード | 同上 |
| `llm_router.py:569` | `_call_deepseek`が引数model無視 | 動的マッピング |
| `llm_router.py:663` | ストリーム版も同上 | 同上 |
| `llm_router.py:206` | chat→DeepSeek固定 | Gemini 2.5 Flash（無料枠） |
| `llm_router.py:216` | gemini-2.5-flash-lite廃止済み | gemini-2.5-flashに更新 |
| `llm_router.py:189` | Anthropicクレジット不足で常時失敗 | `ANTHROPIC_CREDITS_AVAILABLE`フラグ制御 |

### SDKインストール
- `google-genai`, `openai`, `anthropic` が未インストールだった → 全API直接呼び出しがローカルフォールバック依存
- `pip3 install --break-system-packages google-genai openai anthropic` で解決

### 全経路テスト結果（8/8成功、フォールバック0）
| 経路 | プロバイダ | モデル |
|------|-----------|--------|
| chat | Google | gemini-2.5-flash |
| drafting | local | qwen3.5-9b |
| classification | local | qwen3.5-9b |
| API fallback | deepseek | deepseek-v3.2 |
| batch | Google | gemini-2.5-flash |
| content(high) | OpenRouter | gpt-5-mini |
| Tier S | Google | gemini-2.5-pro |
| intelligence>=50 | Google | gemini-2.5-pro |

## 4. 残存課題

### 要対応
- **Anthropic APIクレジット補充**: `ANTHROPIC_CREDITS_AVAILABLE=true`に変更すればClaude Sonnet/Opusが自動的にTier Sに復帰
- **Bluesky投稿実績ゼロ**: ドラフト生成は動いているが実投稿なし

### 継続監視
- ローカルLLM使用率（現在ルーター修正により改善見込み）
- persona_memoryの蓄積状況（会話を重ねるほど成長）

## 5. 接続情報

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
```

---

*2026-03-20 承認ループ修正+iPhone対応+チャット長期記憶+モデル選定システム全面修正。SDKインストール。28ジョブ稼働中。*
