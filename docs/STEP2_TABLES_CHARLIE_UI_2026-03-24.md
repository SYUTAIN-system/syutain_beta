# STEP2: Brain-α基盤テーブル + CHARLIE Win11制御 + Web UI拡張

**実施日**: 2026-03-23 14:44〜15:00 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. PostgreSQL新規テーブル（10個）

| # | テーブル名 | 目的 | INSERT/SELECT/DELETE検証 |
|---|-----------|------|------------------------|
| 1 | agent_reasoning_trace | 全エージェント判断根拠 | OK |
| 2 | brain_alpha_session | セッション間記憶 | OK |
| 3 | brain_alpha_reasoning | Brain-α判断トレース | OK |
| 4 | brain_cross_evaluation | 相互評価 | OK |
| 5 | daichi_dialogue_log | Daichi対話ログ | OK |
| 6 | review_log | 精査記録 | OK |
| 7 | auto_fix_log | 自律修復記録 | OK |
| 8 | claude_code_queue | Brain-β→Brain-αタスクキュー | OK |
| 9 | node_state | 4ノード状態管理 | OK（4行初期データ挿入済み） |
| 10 | posting_queue | SNS自動投稿キュー | OK |

## 2. 既存テーブルへのカラム追加

| テーブル | カラム | デフォルト値 | 確認 |
|---------|--------|------------|------|
| tasks | review_flag | 'no_review_needed' | OK |
| intel_items | review_flag | 'pending_review' | OK |
| proposal_history | review_flag | 'pending_review' | OK |

## 3. インデックス（13個）

- 全新規テーブルのcreated_at
- agent_reasoning_trace(agent_name)
- claude_code_queue(status, priority) 複合
- posting_queue(platform, status, scheduled_at) 複合

## 4. CHARLIE Win11切り替えAPI

| メソッド | エンドポイント | 機能 | 検証 |
|---------|--------------|------|------|
| GET | /api/nodes/charlie/mode | 現在のモード取得 | OK |
| POST | /api/nodes/charlie/mode | win11/ubuntu切替 | OK |
| GET | /api/nodes/state | 全ノード状態取得 | OK |
| GET | /api/nodes/state/history | 変更履歴取得 | OK |

### API動作確認結果
```
POST {"mode":"win11"} → state=charlie_win11, event_log記録, Discord通知
POST {"mode":"ubuntu"} → state=healthy, event_log記録, Discord通知
GET charlie/mode → mode, state, reason, changed_by, changed_at
GET nodes/state → 4ノード全状態
GET nodes/state/history → event_logから変更履歴
```

## 5. Web UI（12ページ構成）

| # | パス | ページ | 状態 | HTTP |
|---|------|-------|------|------|
| 1 | / | ダッシュボード（node_stateバッジ+CHARLIE切替ボタン追加） | 更新 | 200 |
| 2 | /chat | チャット | 既存 | 200 |
| 3 | /tasks | タスク | 既存 | 200 |
| 4 | /proposals | 提案 | 既存 | 200 |
| 5 | /timeline | タイムライン | 既存 | 200 |
| 6 | /agent-ops | Agent Ops | 既存 | 200 |
| 7 | /brain-alpha | Brain-α（精査/記憶/接続/対話ログ） | **新規** | 200 |
| 8 | /node-control | ノード制御（4ノード詳細+CHARLIE制御+履歴） | **新規** | 200 |
| 9 | /revenue | 収益 | 既存 | 200 |
| 10 | /models | モデル | 既存 | 200 |
| 11 | /intel | 情報収集 | 既存 | 200 |
| 12 | /settings | 設定（Brain-αセクション追加） | 更新 | 200 |

### ダッシュボード追加要素
- node_stateバッジ: 各ノードの状態を色分け表示（healthy=緑, charlie_win11=黄, down=赤）
- CHARLIE Win11切替ボタン: ワンタップで切替、APIコール→DB更新→Discord通知

### ナビゲーション更新
- デスクトップ: 12リンク（gap-6→gap-4に調整）
- モバイル: mainTabs(4) + moreTabs(7) = 11項目（ダッシュボードはmainTabs）

## 6. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| app.py | CharlieModeRequest追加, 4エンドポイント追加 |
| web/src/app/layout.tsx | ナビゲーション12ページ構成 |
| web/src/app/page.tsx | node_stateバッジ+CHARLIE切替ボタン |
| web/src/app/brain-alpha/page.tsx | **新規**：Brain-αページ骨格 |
| web/src/app/node-control/page.tsx | **新規**：ノード制御ページ |
| web/src/app/settings/page.tsx | Brain-αセクション追加 |
| web/src/components/MobileTabBar.tsx | Brain-α+ノード追加 |

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
Brain-α: https://100.70.34.67:8443/brain-alpha
ノード制御: https://100.70.34.67:8443/node-control
```
