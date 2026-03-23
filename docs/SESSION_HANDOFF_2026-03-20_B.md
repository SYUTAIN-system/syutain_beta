# SYUTAINβ セッション引き継ぎ資料

**作成日**: 2026-03-20
**最終更新**: 2026-03-20 01:35 JST
**作成者**: Claude Opus 4.6 (1M context)

---

## 1. 本セッションの成果

### os_kernel.pyイベント記録 [実装済み]
- goal.created / task.dispatched / task.completed / task.failed
- goal.completed / goal.escalated / loopguard.triggered
- quality.scored / quality.artifact
- execute_goal()のライフサイクル全体をevent_logに自動記録

### SNS投稿イベント記録 [実装済み]
- social_tools.py: sns.posted / sns.post_failed（Bluesky投稿成功/失敗）
- scheduler.py: sns.draft_created（ドラフト生成時）

### ノードヘルスチェックジョブ [実装済み]
- scheduler.pyに5分間隔ジョブ追加
- 各ノードのOllama応答確認（HTTP GET /api/tags）
- ALPHA CPU/MEM（psutil）記録
- event_logにnode.healthイベント記録
- テスト: 全4ノード分のnode.healthイベント確認、Ollama全ノードOK

### Agent Ops画面イベントログ表示 [実装済み]
- web/src/app/agent-ops/page.tsx にイベントログストリームセクション追加
- カテゴリ別フィルタ（llm/task/goal/sns/system/node）
- severity別表示（info=·、warning=W、error=E、critical=!!）
- 5秒間隔自動更新

### 異常検知→Discord通知 [実装済み]
- severity=errorが5分間に3件以上→Discord通知
- severity=critical→即時通知
- Ollamaダウン検知→Discord通知
- scheduler.pyのanomaly_detectionジョブ（5分間隔）

### Bluesky重複チェック [実装済み]
- _check_bluesky_duplicate(): 直近3投稿との文字重複率比較
- 類似度0.85以上→棄却、sns.duplicate_rejectedイベント記録
- 直近3投稿のテーマを取得してLLMに別テーマを指示
- CONTENT_STRATEGY.md参照してローテーション

### 根本バグ修正
1. **redispatch_orphan_tasks NATSメソッド修正**: `publish()`→`publish_simple()` でPubAckエラー解消
2. **redispatch_orphan_tasks フィールド名修正**: `task_type`→`type` でworkerが正しくタスクタイプを認識
3. **scheduler heartbeatにcpu_percent/memory_percent追加**: ALPHAのハートビートにpsutilメトリクス追加
4. **モデル使用統計API改善**: llm_cost_logからも集計、nullハンドリング追加

### ノードCPU問題の解決
- **根本原因特定**: ノードは実際にアイドル（BRAVO: 0.0% CPU, CHARLIE: 0.0% CPU, DELTA: 0.7% CPU）
- SSH直接確認とNATSハートビート値が一致（BRAVO: 0.1% CPU, 12.5% MEM）
- ハートビートは正常に動作しており、app.pyの_node_metricsに反映されている
- ダッシュボードは正しい値を表示（低い値は正常：ノードがアイドルのため）
- redispatchバグ修正により今後タスクが正しく分配されればCPUが上がる

---

## 2. 現在のシステム状態

### プロセス: 4つ稼働（ALPHA）
- FastAPI (uvicorn) :8000
- Next.js (next-server) :3000
- nats-server
- scheduler.py
- Caddy :8443

### リモートノード: 全台稼働
| ノード | Worker | NATS | Ollama | モデル |
|--------|--------|------|--------|--------|
| BRAVO | active | active | OK | qwen3.5:9b |
| CHARLIE | active | active | OK | qwen3.5:9b |
| DELTA | active | active | OK | qwen3:4b-q4_K_M |

### DB概要
| テーブル | 件数 |
|----------|------|
| event_log | 18+ |
| goals | 18 |
| tasks | 102 |
| proposals | 9 |
| llm_cost_log | 159 |

---

## 3. 残存課題

### 優先度: 高
1. **worker_main.pyのタスクタイプ対応**: `browser_action`タイプが未対応（worker側は`browser`として扱う必要あり）
2. **NATS JetStreamストリーム競合**: AGENTSストリームが`agent.>`をキャプチャし、Core NATSハートビートと競合する可能性

### 優先度: 中
3. Stripe未設定
4. pgvector未有効化
5. Litestream未設定
6. ノードヘルスチェックにSSH直接メトリクス取得を追加（現在はNATS request-replyが未応答）

---

## 4. 接続情報

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
Events: GET /api/events?category=node&limit=50
Node Health: event_log WHERE event_type='node.health'
```

---

*2026-03-20 イベントログ拡張完了。ノードヘルスチェック実装。異常検知→Discord実装。Bluesky重複チェック実装。ノードCPU問題根本原因特定（実際にアイドル＋redispatchバグ修正）。*
