# STEP8: 自律修復（Self-Healing）+ 自律回復（Self-Recovery）

**実施日**: 2026-03-23 17:00〜17:30 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. brain_alpha/self_healer.py

### 自律修復5カテゴリ
| # | カテゴリ | 検出方法 | 修復方法 | テスト |
|---|---------|---------|---------|-------|
| 1 | サービスクラッシュ | HTTP応答チェック | launchctl/systemctl再起動 | OK (NATS再起動実行) |
| 2 | Ollamaモデル | SSH経由Ollama API確認 | systemctl restart ollama | OK |
| 3 | NATS接続 | :8222監視ポート確認 | launchctl再起動 | OK (自動検出→再起動) |
| 4 | PostgreSQL | asyncpg接続 | エラー時アラート | OK |
| 5 | FastAPI/Next.js | HTTP 200チェック | launchctl再起動 | OK |

### 自律回復3カテゴリ
| # | カテゴリ | 内容 | テスト |
|---|---------|------|-------|
| 1 | ノード停止回復 | SSH確認→CHARLIE=charlie_win11、他=down | OK |
| 2 | データ整合性 | stuck tasks→failed(8件修復)、72h承認→却下、7日handoff→expired、10万件log削減 | OK (8件修復) |
| 3 | Brain-α回復 | tmux brain_alpha生存確認 | OK (alive=true) |

### CHARLIE Win11対応（最重要）
```
判定フロー:
1. node_state='charlie_win11' → 修復試行しない。SSH復帰検出時に自動healthy復帰
2. node_state='healthy' + SSH応答なし → 10分猶予タイマー開始
3. 10分経過、まだ応答なし → charlie_win11に自動移行 + Discord通知
4. SSH復帰検出 → healthy自動復帰 + Discord通知
```

### ノード状態定義
| 状態 | 説明 |
|------|------|
| healthy | SSH応答あり、全サービス正常 |
| degraded | SSH応答あり、一部サービス異常 |
| charlie_win11 | CHARLIE固有: SSH応答なし（島原Win11使用中） |
| down | SSH応答なし（障害） |
| recovering | 復旧処理中 |

## 2. scheduler.pyジョブ追加

| ジョブ | 間隔 | 関数 |
|-------|------|------|
| self_heal_check | 5分 | 全ノードサービス確認+自動修復 |
| data_integrity_check | 毎日04:00 | データ整合性回復 |
| brain_alpha_health | 10分 | tmuxセッション監視 |

## 3. API追加

| メソッド | エンドポイント | テスト |
|---------|--------------|-------|
| GET | /api/self-healing/log?limit=20 | OK (1件) |
| GET | /api/self-healing/stats | OK (24h=1件, rate=100%) |

## 4. Web UI更新

| ページ | 追加要素 | HTTP |
|-------|---------|------|
| /node-control | 自律修復セクション: 24h件数+成功率、修復ログ一覧（結果色分け）。degraded/recoveringステータス追加 | 200 |
| / (ダッシュボード) | 修復ステータスカード（24h件数+成功率、/node-controlリンク） | 200 |

## 5. 検証結果

```
self_heal_check():
  ALPHA: degraded (NATS自動再起動)
  BRAVO: healthy ✅
  CHARLIE: healthy ✅
  DELTA: healthy ✅
  fixes: ["NATS再起動"]

data_integrity_check():
  stuck_tasks: 8件→failed ✅
  status: ok

brain_alpha_health_check():
  brain_alpha_alive: true ✅
  tmux: brain_alpha: 1 windows

GET /api/self-healing/stats:
  24h=1件, success_rate=100.0% ✅

Web UI: /node-control 200, / 200 ✅
```

## 6. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| brain_alpha/self_healer.py | **新規**: 自律修復+自律回復全機能 |
| scheduler.py | 3ジョブ追加 (self_heal_check, data_integrity_check, brain_alpha_health) |
| app.py | 2エンドポイント追加 (self-healing/log, stats) |
| web/src/app/node-control/page.tsx | 自律修復セクション + degraded/recoveringステータス追加 |
| web/src/app/page.tsx | 修復ステータスカード追加 |

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
ノード制御: https://100.70.34.67:8443/node-control
```
