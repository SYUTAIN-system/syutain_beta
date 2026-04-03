# エージェント間相互接続診断 2026-03-21

## 情報パイプライン残り2項目
前回セッションで12/12全項目修正済み（INTEL_PIPELINE_DIAGNOSIS_2026-03-21.md参照）。

## 接続マトリクス（20項目）

### 収益パイプラインの背骨
| # | 接続 | 評価 | コード証拠 | データ実績 | 影響確認 |
|---|------|------|-----------|-----------|---------|
| 1 | ProposalEngine→OSKernel | ✅ | app.py:1012 execute_goal() | 2件adopted→goal作成 | 提案承認→ゴール自動起動確認 |
| 2 | OSKernel→Planner | ✅ | os_kernel.py:312 planner.plan() | 114タスク生成 | goal→taskGraph分解確認 |
| 3 | Executor→Verifier | ✅ | os_kernel.py:371 verifier.verify() | 67/114件にスコア付与 | 品質スコアが判断に使用 |
| 4 | Verifier→商品化候補 | ✅ | scheduler.py:1145 quality≥0.7 | 週次金曜実行 | 高品質成果物→multiply_content |
| 5 | SNS→Approval→投稿 | ✅ | content_multiplier→approval_queue→app.py | 32件approved | ドラフト→承認→API投稿 |

### 学習・フィードバックループ
| # | 接続 | 評価 | コード証拠 | データ実績 | 影響確認 |
|---|------|------|-----------|-----------|---------|
| 6 | Verifier→model_quality_log | ✅ | verifier.py:335-355 INSERT | 全verify呼び出しで記録 | モデル別品質蓄積 |
| 7 | model_quality_log→llm_router | ✅ | llm_router.py:65-95,248-253 | 毎時キャッシュ更新 | 品質0.6+ローカルモデル自動選定 |
| 8 | 却下理由→ProposalEngine | ✅ | proposal_engine.py:175-186 | proposal_feedback JOIN | **修正: title+rejection_reason注入** |
| 9 | LearningManager→各エージェント | ⚠️ | learning_manager.py:373 intel_items保存 | 週次日曜21:00 | intel_items経由で間接的に到達。get_recommendations()未使用 |
| 10 | approval結果→LearningManager | ✅ | app.py:1028-1031,1056-1060 | **修正: track_proposal_outcome()接続** | 承認/却下→proposal_feedback記録確認 |

### 情報→思考→行動
| # | 接続 | 評価 | コード証拠 | データ実績 | 影響確認 |
|---|------|------|-----------|-----------|---------|
| 11 | intel→SNS投稿ドラフト | ✅ | content_multiplier.py:71-91 | importance≥0.5上位3件 | 投稿に「Gemini AI」等反映確認 |
| 12 | intel→competitive_analyzer | ⚠️ | competitive_analyzer.py:157 WRITE ONLY | intel_itemsへの保存のみ | 読取りなし（外部ソースから直接分析） |
| 13 | competitive→ProposalEngine | ⚠️ | proposal_engine.py:108-114 intel_items経由 | intel_itemsに混在 | 48h+importance≥0.4で間接的に到達 |
| 14 | CapabilityAudit→Planner | ⚠️ | planner.py:162,312-339 perception経由 | コードあり、イベント0件 | perceive()実行時に流れる設計 |

### 人格・デジタルツイン
| # | 接続 | 評価 | コード証拠 | データ実績 | 影響確認 |
|---|------|------|-----------|-----------|---------|
| 15 | approval→persona_memory | ✅ | app.py:918-942 | **修正: 承認/却下パターンをpersona_memoryに記録** | id=125で記録確認、embedding非同期生成 |
| 16 | persona_memory→ChatAgent | ✅ | chat_agent.py:801,882-906 | 124件（+approval_pattern） | pgvector類似検索でLLMプロンプト注入 |
| 17 | persona_memory→ProposalEngine | ✅ | proposal_engine.py:189-203 | **修正: approval_patternから判断傾向を注入** | 直近5件をプロンプトに反映 |
| 18 | persona_memory→コンテンツ生成 | ✅ | content_multiplier.py:94-112 | **修正: value/preference/approval_pattern参照** | system_promptにpersona_hint注入 |

### 異常検知・自己修復
| # | 接続 | 評価 | コード証拠 | データ実績 | 影響確認 |
|---|------|------|-----------|-----------|---------|
| 19 | MonitorAgent→OSKernel再振替 | ✅ | monitor_agent.py:165-207 | **修正: ノードダウン時にタスク再振替** | status='running'→別ノードに'pending'で再割当 |
| 20 | LoopGuard→StopDecider | ⚠️ | stop_decider.py:113-164, os_kernel.py:471-531 | コード完備、発動実績0件 | 正常運用のため未発動（設計通り） |

## 総合スコア
- ✅: **15/20**
- ⚠️: **5/20** (9,12,13,14,20 — 設計上の間接接続 or 未発動だが正常)
- ❌: **0/20**
- **総合接続度: 75%（✅のみ）/ 100%（❌なし）**

## 修正した項目（6件）

### 1. 接続#10: approval結果→LearningManager (app.py)
- approve_proposal()にLearningManager.track_proposal_outcome(adopted=True)追加
- reject_proposal()にtrack_proposal_outcome(adopted=False, rejection_reason)追加
- 検証: 却下→proposal_feedbackにrejection_reason記録確認

### 2. 接続#8: 却下理由→ProposalEngine改善 (proposal_engine.py)
- proposal_historyとproposal_feedbackをJOINしてrejection_reasonも取得
- プロンプトに「却下理由を踏まえ、全く異なる切り口で提案すること」追加

### 3. 接続#15: approval→persona_memory (app.py)
- pending-approvals respond APIに、承認/却下パターンをpersona_memoryに保存する処理追加
- category='approval_pattern'、embed_and_store_personaで非同期ベクトル化
- バグ修正: req_typeの取得を承認/却下共通に移動（却下時に未定義だった）

### 4. 接続#17: persona_memory→ProposalEngine (proposal_engine.py)
- generate_proposal()でpersona_memory(category='approval_pattern')から直近5件取得
- 「DAICHIの判断傾向」としてLLMプロンプトに注入

### 5. 接続#18: persona_memory→コンテンツ生成 (content_multiplier.py)
- multiply_content()でpersona_memory(value/preference/writing_style/approval_pattern)取得
- Bluesky/X島原のsystem_promptにpersona_hint注入

### 6. 接続#19: MonitorAgent→タスク再振替 (monitor_agent.py)
- _reassign_tasks_from_down_node()メソッド追加
- ダウンノードのstatus='running'タスクを生存ノードにstatus='pending'で再割当
- event_log記録 + Discord通知

## ⚠️項目の詳細（修正不要の理由）
- #9: LearningManagerはintel_itemsに保存→ProposalEngineが読む。間接的だが情報は到達する
- #12: competitive_analyzerは外部ソース(booth/note)を直接分析する設計。intel_itemsは出力先
- #13: competitive_analyzer結果はintel_itemsに保存され、ProposalEngineが48h以内ならimportance≥0.4で取得
- #14: CapabilityAuditは1時間ごとにスナップショットを取得。Plannerはperception経由で参照する設計
- #20: LoopGuardは正常運用では発動しない（50ステップ/日次予算90%等の上限に達していない）

## 再起動確認
- health: ✅ ok (PostgreSQL ok, NATS ok)
- スケジューラー: 28ジョブ登録（エンゲージメント3件含む）
- 全ページ: 10/10 (/, /chat, /tasks, /proposals, /timeline, /agent-ops, /revenue, /models, /intel, /settings)
- ノード同期: BRAVO ✅ / CHARLIE ✅ / DELTA ✅
