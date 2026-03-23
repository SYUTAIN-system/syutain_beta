# STEP3: 判断根拠トレース実装 + Web UI表示

**実施日**: 2026-03-23 15:00〜15:20 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## 1. トレース実装（5エージェント）

| # | エージェント | 記録タイミング | 記録内容 | テスト |
|---|------------|--------------|---------|-------|
| 1 | agents/verifier.py | 品質スコア付与時 | task_id, スコア値, ai_patterns検出数/詳細, model_used | OK |
| 2 | agents/proposal_engine.py | 提案生成時 | proposal_id, 参照intel件数, persona_memory使用有無, テーマ選定理由, model_used, total_score | OK |
| 3 | agents/executor.py | タスク実行時 | goal_id, task_id, ノード選定理由, モデル選定理由, elapsed_sec, cost_jpy | OK |
| 4 | tools/info_pipeline.py | パイプライン完了時 | total_saved, ソース別件数, 上位5件(title/score/category), scoring_method | OK |
| 5 | agents/learning_manager.py | 週次レポート生成時 | period, task統計, 採用率, 検出傾向, 推奨改善アクション | OK |

### 実装パターン（共通）
```python
async def _record_trace(self, action="", reasoning="", confidence=None, context=None):
    """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
    try:
        # INSERT INTO agent_reasoning_trace ...
    except Exception as e:
        logger.debug(f"トレース記録失敗（無視）: {e}")
```

## 2. APIエンドポイント

| メソッド | エンドポイント | 機能 | テスト |
|---------|--------------|------|-------|
| GET | /api/traces?target_id={id} | task_id or goal_id絞り込み | OK |
| GET | /api/traces?agent_name={name} | エージェント別フィルタ | OK |
| GET | /api/traces/recent?limit=20 | 直近トレース一覧 | OK |

## 3. Web UI更新

| ページ | 追加要素 | 確認 |
|-------|---------|------|
| /tasks | タスク詳細モーダルに「判断根拠」折りたたみ。confidence色分け（80%+緑, 50-79%黄, 50%未満赤）。詳細コンテキスト展開可能 | HTTP 200 |
| /proposals | ProposalCardに「なぜこの提案か」折りたたみ。target_icp, チャネル, モデル, 参照intel件数を表示 | HTTP 200 |
| /intel | review_flagバッジ（未精査=黄, 精査済=緑）。importance_score色分けは既存 | HTTP 200 |

## 4. 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| agents/verifier.py | _record_trace()追加, verify()にトレース記録 |
| agents/executor.py | _record_trace()追加, execute_task()にトレース記録 |
| agents/proposal_engine.py | _record_trace()追加, generate_proposal()にトレース記録 |
| tools/info_pipeline.py | _record_trace()追加, run_full_pipeline()にトレース記録 |
| agents/learning_manager.py | _record_trace()追加, generate_weekly_report()にトレース記録 |
| app.py | /api/traces, /api/traces/recent エンドポイント追加 |
| web/src/app/tasks/page.tsx | 判断根拠セクション追加（traces state, Brain icon） |
| web/src/components/ProposalCard.tsx | 「なぜこの提案か」折りたたみ追加 |
| web/src/app/intel/page.tsx | review_flagバッジ追加 |

## 5. 検証結果

### テストデータINSERT→API取得→DELETE
- 5エージェント分のトレースデータ挿入: OK
- GET /api/traces/recent: 5件全て返却、confidence/context正常 ✅
- GET /api/traces?target_id=test-task-001: verifier+executor 2件返却 ✅
- テストデータ削除: 5件 ✅

### Web UIビルド
- next build: Compiled successfully ✅
- 全12ページ HTTP 200 ✅

---

## 接続先URL

```
HTTPS: https://100.70.34.67:8443/
タスク: https://100.70.34.67:8443/tasks
提案: https://100.70.34.67:8443/proposals
情報収集: https://100.70.34.67:8443/intel
```
