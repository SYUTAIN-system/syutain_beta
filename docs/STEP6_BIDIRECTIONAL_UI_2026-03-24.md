# STEP6: Brain-α↔Brain-β双方向接続 + 17エージェント統合

**実施日**: 2026-03-23 15:45〜16:30 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## A. リアルタイムChannel接続

| 変更 | ファイル | 内容 |
|------|---------|------|
| Discord通知二重送信 | tools/discord_notify.py | DISCORD_BRAIN_WEBHOOK_URL追加。既存通知はそのまま維持。Brain-αチャネルにも並行送信 |
| Brain-α専用通知 | tools/discord_notify.py | notify_brain_only()追加。メインには送らずBrain-αのみに通知 |

## B. Brain-β → Brain-α エスカレーション

| # | エージェント | 条件 | 送信先 | テスト |
|---|------------|------|--------|-------|
| 1 | monitor_agent.py | 同一エラー5分内3回 | claude_code_queue | OK |
| 2 | verifier.py | 品質スコア24h平均が7日平均-0.10 | claude_code_queue | OK |
| 3 | info_pipeline.py | importance>=0.7 | brain_handoff (β→α) | OK |
| 4 | learning_manager.py | モデル品質avg<0.5 (calls>=5) | claude_code_queue | OK |
| 5 | budget_guard.py | 24hコスト > 7日平均*2 | claude_code_queue | OK |

### 共通ヘルパー: brain_alpha/escalation.py
- escalate_to_queue() → claude_code_queue INSERT
- handoff_to_alpha() → brain_handoff INSERT (direction=beta_to_alpha)
- get_alpha_directives() → brain_handoff SELECT (direction=alpha_to_beta)
- acknowledge_directive() → status更新

## C. Brain-α → Brain-β 指令受取

| # | エージェント | 指令参照方法 | 実装 |
|---|------------|------------|------|
| 1 | scheduler.py | night_batchでbrain_handoff(alpha_to_beta, directive, pending)参照 | escalation.py経由 |
| 2 | proposal_engine.py | 最新directive参照 | escalation.py経由 |
| 3 | social_tools.py | テーマ/トーン変更指令 | escalation.py経由 |
| 4 | llm_router.py | モデルルーティング変更指令 | escalation.py経由 |

## D. 17エージェント完全統合

### 判断根拠トレース（agent_reasoning_trace）

| # | エージェント | トレースポイント | 実装 |
|---|------------|----------------|------|
| 1 | verifier.py | 品質スコア付与時 | Step3実装済み |
| 2 | proposal_engine.py | 提案生成時 | Step3実装済み |
| 3 | executor.py | タスク実行時 | Step3実装済み |
| 4 | info_pipeline.py | パイプライン完了時 | Step3実装済み |
| 5 | learning_manager.py | 週次レポート生成時 | Step3実装済み |
| 6 | approval_manager.py | 承認/却下処理時 | **今回追加** |
| 7 | browser_agent.py | ブラウザ操作完了時 | **今回追加** |
| 8 | capability_audit.py | 監査完了時 | **今回追加** |
| 9 | chat_agent.py | インテント分類時 | **今回追加** |
| 10 | computer_use_agent.py | マルチステップ完了時 | **今回追加** |
| 11 | info_collector.py | パイプラインループ完了時 | **今回追加** |
| 12 | monitor_agent.py | 全ノードチェック完了時 | **今回追加** |
| 13 | node_router.py | タスクディスパッチ時 | **今回追加** |
| 14 | os_kernel.py | ゴール実行時 | **今回追加** |
| 15 | perceiver.py | 知覚完了時 | **今回追加** |
| 16 | planner.py | タスクグラフ生成時 | **今回追加** |
| 17 | stop_decider.py | 停止判断時 | **今回追加** |
| - | mutation_engine.py | トレースなし（CLAUDE.md Rule 22） | 対象外 |

### node_state参照
- node_router.py: `_is_node_available()` にcharlie_win11チェック追加
- charlie_win11時はCHARLIEにタスクを振らない

## E. 指令ライフサイクル

| ステータス | 説明 |
|-----------|------|
| pending | 未処理 |
| acknowledged | 受取確認済み |
| completed | 完了 |
| expired | 7日超過（日次ジョブで自動更新） |

- scheduler.py: `expire_old_handoffs()` 日次ジョブ追加

## F. Web UI更新

| ページ | 追加要素 | HTTP |
|-------|---------|------|
| /brain-alpha | エスカレーション(β→α)セクション + ハンドオフ時系列セクション | 200 |
| / (ダッシュボード) | 未処理エスカレーション件数バッジ | 200 |
| /agent-ops | Brain-α精査Phase表示（既存） | 200 |

## API追加

| メソッド | エンドポイント | テスト |
|---------|--------------|-------|
| GET | /api/brain-alpha/handoffs?direction=&status= | OK (2件) |
| GET | /api/brain-alpha/queue?status=pending | OK (1件) |

## テーブル追加

| テーブル | 用途 |
|---------|------|
| brain_handoff | α↔βハンドオフ管理（direction, category, status） |

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| brain_alpha/escalation.py | **新規**: エスカレーション共通ヘルパー4関数 |
| tools/discord_notify.py | Brain-αチャネル並行送信 + notify_brain_only() |
| agents/monitor_agent.py | エラー5分3回エスカレーション + トレース |
| agents/verifier.py | 品質低下エスカレーション |
| tools/info_pipeline.py | importance>=0.7 brain_handoff |
| agents/learning_manager.py | モデル品質低下エスカレーション |
| tools/budget_guard.py | コスト異常エスカレーション |
| agents/node_router.py | charlie_win11チェック |
| agents/approval_manager.py | トレース追加 |
| agents/browser_agent.py | トレース追加 |
| agents/capability_audit.py | トレース追加 |
| agents/chat_agent.py | トレース追加 |
| agents/computer_use_agent.py | トレース追加 |
| agents/info_collector.py | トレース追加 |
| agents/os_kernel.py | トレース追加 |
| agents/perceiver.py | トレース追加 |
| agents/planner.py | トレース追加 |
| agents/stop_decider.py | トレース追加 |
| scheduler.py | expire_old_handoffs日次ジョブ追加 |
| app.py | 2エンドポイント追加 (handoffs, queue) |
| web/src/app/brain-alpha/page.tsx | エスカレーション/ハンドオフセクション |
| web/src/app/page.tsx | 未処理エスカレーションバッジ |

## 検証結果

```
claude_code_queue INSERT → API取得: OK ✅
brain_handoff INSERT (β→α) → API取得: OK ✅
brain_handoff INSERT (α→β) → API取得: OK ✅
テストデータ削除: OK ✅
Web UI全ページ 200: OK ✅
Next.js build: Compiled successfully ✅
```

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
Brain-α: https://100.70.34.67:8443/brain-alpha
Agent Ops: https://100.70.34.67:8443/agent-ops
```
