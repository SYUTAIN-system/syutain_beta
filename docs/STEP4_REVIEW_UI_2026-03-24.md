# STEP4: Brain-α精査サイクル + Git Worktree + Web UI表示

**実施日**: 2026-03-23 15:00〜15:20 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. Git Worktree設定

```
git init → 既に初期化済み
git add -A && git commit → "Brain-α fusion baseline 2026-03-23" (c090593)
修正時: claude --worktree fix-$(date +%H%M) で隔離作業
```

## 2. brain_alpha/startup_review.py

### 精査サイクル 8 Phase
| Phase | 内容 | データソース | テスト |
|-------|------|------------|-------|
| 1 | セッション復元 | brain_alpha_session | OK |
| 2 | Daichi思考参照 | daichi_dialogue_log (直近5件) | OK |
| 3 | 情報収集精査 | intel_items (24h新着/重要/pending) | OK |
| 4 | 成果物精査 | data/artifacts/ + tasks | OK |
| 5 | 品質推移 | tasks (7日平均 vs 前週) | OK |
| 6 | エラー分析 | event_log (error/critical 24h) | OK |
| 7 | 収益 | revenue_linkage + SNS投稿統計 | OK |
| 8 | トレース/キュー | agent_reasoning_trace (conf<0.5) + claude_code_queue | OK |

### 技術仕様
- LLM呼び出しなし（コストゼロ）
- PostgreSQLクエリのみ（asyncpg直接接続）
- 各PhaseをJSON構造体で返却
- 全Phaseをtry-exceptで隔離
- レポートをbrain_alpha_reasoningテーブルに保存
- Discord Webhook投稿（Markdown形式）

### 実行結果
```
精査完了 (15:19) / 情報61件 / 品質0.67 / エラー4件
推奨アクション:
1. intel_items 527件が未精査。重要度0.7+を優先確認
2. 重要情報 3件を検出（24h）。提案・戦略への反映を検討
3. 再発エラー: sns.post_failed (4回) → 根本原因修正
Discord投稿: HTTP 204 ✅
DB保存: brain_alpha_reasoning id=3 ✅
```

## 3. APIエンドポイント

| メソッド | エンドポイント | 機能 | テスト |
|---------|--------------|------|-------|
| GET | /api/brain-alpha/latest-report | 最新精査レポート取得 | OK |
| GET | /api/brain-alpha/reports?limit=N | 過去レポート一覧 | OK |
| POST | /api/brain-alpha/run-review | 精査サイクル手動実行 | OK |

## 4. Web UI更新

| ページ | 追加要素 | HTTP |
|-------|---------|------|
| /brain-alpha | 全面改修: 精査実行ボタン、最新レポート表示、警告/推奨アクション、Phase詳細(8段階折りたたみ)、過去レポート一覧 | 200 |
| / (ダッシュボード) | Brain-α精査サマリーカード: summary + warnings上位2件 + 推奨アクション上位3件。クリックで/brain-alphaに遷移 | 200 |
| /agent-ops | Brain-α精査Phase 1-8の完了/エラー状況をグリッド表示（緑=完了、赤=エラー、灰=未実行） | 200 |

## 5. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| brain_alpha/__init__.py | **新規**: パッケージ初期化 |
| brain_alpha/startup_review.py | **新規**: 精査サイクル全8Phase |
| app.py | 3エンドポイント追加 (brain-alpha/latest-report, reports, run-review) |
| web/src/app/brain-alpha/page.tsx | 全面改修: 精査レポート表示 |
| web/src/app/page.tsx | Brain-α精査サマリーカード追加 |
| web/src/app/agent-ops/page.tsx | Brain-α精査Phase表示追加 |

## 6. 検証結果

```
startup_review.py CLI実行: OK ✅
Discord Webhook投稿: HTTP 204 ✅
brain_alpha_reasoning DB保存: 2レコード確認 ✅
GET /api/brain-alpha/latest-report: summary, actions(3件), phases(8個) ✅
Web UI /brain-alpha: 200, 精査実行ボタン動作 ✅
Web UI /: 200, Brain-αサマリーカード表示 ✅
Web UI /agent-ops: 200, Phase 1-8グリッド表示 ✅
```

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
Brain-α: https://100.70.34.67:8443/brain-alpha
Agent Ops: https://100.70.34.67:8443/agent-ops
```
