# STEP5: Brain-α記憶階層システム + Web UI

**実施日**: 2026-03-23 15:20〜15:45 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. brain_alpha/memory_manager.py

### 記憶階層（人間の脳を模倣）
```
感覚記憶     → channelイベント（数秒で消える）
短期記憶     → Claude Codeコンテキストウィンドウ
長期エピソード → brain_alpha_session（いつ何をして何が起きたか）
長期意味     → persona_memory（Daichiの人格・哲学）
長期手続き   → CLAUDE.md + コード自体
```

### 実装関数

| # | 関数 | 機能 | テスト |
|---|------|------|-------|
| 1 | save_session_memory() | セッション終了時にbrain_alpha_sessionに保存。前回のopen_issues自動引き継ぎ | OK |
| 2 | load_session_memory(limit=3) | 最新1件=フル詳細、2-3件目=要約のみ | OK (1件取得) |
| 3 | recall_relevant_memory(query, limit) | pgvectorコサイン類似度検索 + テキストフォールバック | OK (embedding_tools使用) |
| 4 | consolidate_memories(days=7) | 7日以上前のセッションを圧縮（重要判断は保持、ルーティンは短縮） | OK (nothing_to_consolidate) |
| 5 | extract_and_store_philosophy() | Daichi発言→ローカルLLMで哲学抽出→persona_memory保存→ベクトル化 | OK |
| 6 | get_context_for_intent(type) | 4段階のコンテキスト量制御 | OK |

### コンテキスト量制御（OpenClaw教訓）

| intent_type | 内容 | テスト |
|------------|------|-------|
| casual | persona_memory上位5件 + identity名 | OK (5件) |
| standard | 上位10件 + strategy_identity + 直近セッション | OK |
| strategic | 上位20件 + 全strategy + 直近3セッション + Daichi対話10件 | OK |
| code_fix | 直近セッション + 関連トレース10件 | OK (0件trace) |

## 2. APIエンドポイント

| メソッド | エンドポイント | 機能 | テスト |
|---------|--------------|------|-------|
| GET | /api/brain-alpha/sessions?limit=10 | セッション記憶一覧 | OK (1件) |
| GET | /api/brain-alpha/persona-stats | persona_memoryカテゴリ別統計 | OK (155件, 5カテゴリ) |

## 3. Web UI更新

| ページ | 追加要素 | HTTP |
|-------|---------|------|
| /brain-alpha | セッション記憶一覧（直近10件、最新は展開表示）、persona_memoryカテゴリ別グラフ（件数+割合+ベクトル化率） | 200 |
| /chat | Brain-αの記憶サイドパネル（折りたたみ式）: 前回セッション要約 + persona統計。デスクトップ=サイドバー、モバイル=オーバーレイ | 200 |

## 4. persona_memory現状

| カテゴリ | 件数 | ベクトル化 |
|---------|------|-----------|
| philosophy | 58 | 4 |
| conversation | 46 | 0 |
| approval_pattern | 31 | 29 |
| judgment | 16 | 1 |
| preference | 4 | 0 |
| **合計** | **155** | **34** |

## 5. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| brain_alpha/memory_manager.py | **新規**: 記憶階層マネージャー全6関数 |
| app.py | 2エンドポイント追加 (sessions, persona-stats) |
| web/src/app/brain-alpha/page.tsx | セッション記憶+persona統計セクション追加 |
| web/src/app/chat/page.tsx | Brain-α記憶サイドパネル追加 |

## 6. 検証結果

```
save_session_memory → OK (session_id: test-session-2026-03-23-001) ✅
load_session_memory → OK (1件, detail_level=full) ✅
consolidate_memories → OK (nothing_to_consolidate) ✅
get_context_for_intent(casual) → OK (persona=5件) ✅
get_context_for_intent(code_fix) → OK (traces=0件) ✅
GET /api/brain-alpha/sessions → OK (1件) ✅
GET /api/brain-alpha/persona-stats → OK (155件, 5カテゴリ) ✅
Web UI /brain-alpha → 200 ✅
Web UI /chat → 200 ✅
```

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
Brain-α: https://100.70.34.67:8443/brain-alpha
チャット: https://100.70.34.67:8443/chat
```
