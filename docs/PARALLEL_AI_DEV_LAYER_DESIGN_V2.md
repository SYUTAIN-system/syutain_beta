# SYUTAINβ 並行AI開発レイヤー (PDL) 完全設計書 V2

> Version: 2.0 | Date: 2026-04-01
> Status: DESIGN REVIEW (EXHAUSTIVE EDITION)
> Scope: 既存55K行コードベースの上に載るオーバーレイ層。既存コードの改変ゼロ。
> Supersedes: PARALLEL_AI_DEV_LAYER_DESIGN.md (V1)

---

## 目次

1. [完全アーキテクチャ](#1-完全アーキテクチャ)
   - 1.1 システムトポロジー全体図
   - 1.2 PDLレイヤー構成図
   - 1.3 データフロー: タスク作成→実行→レビュー→マージ→デプロイ
   - 1.4 NATSサブジェクトマッピング
   - 1.5 PostgreSQLテーブルインタラクション
   - 1.6 PDLコンポーネントと既存モジュールの相互作用
   - 1.7 コアコンポーネント一覧
   - 1.8 ディレクトリ構造
   - 1.9 設計原則
2. [詳細コンポーネント仕様](#2-詳細コンポーネント仕様)
   - 2.1 PDL Orchestrator
   - 2.2 Gate Keeper
   - 2.3 Budget Partition
   - 2.4 Worktree Manager
   - 2.5 Task Queue
   - 2.6 Session Ledger
   - 2.7 Merge Arbiter
   - 2.8 Test Harness
   - 2.9 Cleanup Daemon
   - 2.10 Recovery Agent
   - 2.11 Node Awareness
   - 2.12 Loop Breaker
   - 2.13 Dedup Engine
   - 2.14 Config
   - 2.15 Schemas
3. [完全セットアップ手順](#3-完全セットアップ手順)
4. [運用手順](#4-運用手順)
5. [包括的リスク分析 (35項目)](#5-包括的リスク分析)
6. [メリット・デメリット分析](#6-メリットデメリット分析)
7. [パフォーマンス・コスト予測](#7-パフォーマンスコスト予測)
8. [監視ダッシュボード設計](#8-監視ダッシュボード設計)
9. [55K行コードベース管理](#9-55k行コードベース管理)
10. [将来の進化パス](#10-将来の進化パス)

---

## 1. 完全アーキテクチャ

### 1.1 システムトポロジー全体図

PDLはSYUTAINβの既存4ノード分散システムの上に載るオーバーレイ層である。
既存システムは以下の構成:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SYUTAINβ SYSTEM TOPOLOGY                          │
│                                                                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐        │
│  │  ALPHA (macOS / daichi MBP)  │  │  BRAVO (Ubuntu / Tailscale)  │        │
│  │  100.x.x.x (local)          │  │  100.x.x.x                │        │
│  │                              │  │                              │        │
│  │  ┌────────────────────┐     │  │  ┌────────────────────┐     │        │
│  │  │ FastAPI (app.py)   │     │  │  │ FANG bot (CSO)     │     │        │
│  │  │ Scheduler          │     │  │  │ NERVE bot (COO)    │     │        │
│  │  │ Brain-α            │     │  │  │ worker_main.py     │     │        │
│  │  │ CORTEX bot (CEO)   │     │  │  │ Ollama qwen3.5:9b  │     │        │
│  │  │ Ollama qwen3.5:4b  │     │  │  └────────────────────┘     │        │
│  │  │ PostgreSQL         │     │  │                              │        │
│  │  │ NATS Server        │     │  └──────────────────────────────┘        │
│  │  │ Caddy (reverse px) │     │                                          │
│  │  └────────────────────┘     │  ┌──────────────────────────────┐        │
│  │                              │  │  CHARLIE (Ubuntu / Tailscale)│        │
│  │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐    │  │  100.x.x.x              │        │
│  │  │ PDL OVERLAY LAYER   │    │  │                              │        │
│  │  │ (NEW - this doc)    │    │  │  ┌────────────────────┐     │        │
│  │  │                     │    │  │  │ FORGE bot (CTO)    │     │        │
│  │  │ pdl_orchestrator    │    │  │  │ worker_main.py     │     │        │
│  │  │ gate_keeper         │    │  │  │ Ollama qwen3.5:9b  │     │        │
│  │  │ budget_partition    │    │  │  └────────────────────┘     │        │
│  │  │ worktree_manager    │    │  │                              │        │
│  │  │ task_queue          │    │  └──────────────────────────────┘        │
│  │  │ session_ledger      │    │                                          │
│  │  │ merge_arbiter       │    │  ┌──────────────────────────────┐        │
│  │  │ test_harness        │    │  │  DELTA (Ubuntu / Tailscale)  │        │
│  │  │ cleanup_daemon      │    │  │  100.x.x.x               │        │
│  │  │ recovery_agent      │    │  │                              │        │
│  │  │ node_awareness      │    │  │  ┌────────────────────┐     │        │
│  │  │ loop_breaker        │    │  │  │ MEDULLA bot (副CEO) │     │        │
│  │  │ dedup_engine        │    │  │  │ SCOUT bot (Intel)  │     │        │
│  │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    │  │  │ worker_main.py     │     │        │
│  │                              │  │  │ Ollama qwen3.5:4b  │     │        │
│  └──────────────────────────────┘  │  └────────────────────┘     │        │
│                                     │                              │        │
│                                     └──────────────────────────────┘        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     SHARED INFRASTRUCTURE                           │   │
│  │                                                                     │   │
│  │  PostgreSQL ──── NATS ──── Git (local) ──── Tailscale VPN          │   │
│  │  (ALPHA)        (ALPHA)    (ALPHA)          (all nodes)             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**重要**: PDLは **ALPHAノード上にのみ** 存在する。リモートノード(BRAVO/CHARLIE/DELTA)にはPDLコンポーネントは配置しない。PDLはローカルgit操作とPostgreSQLアクセスのみで動作する。

### 1.2 PDLレイヤー構成図

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PARALLEL DEV LAYER (PDL)                            │
│                         ALPHA node only                                     │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       CONTROL PLANE                                  │  │
│  │                                                                      │  │
│  │  ┌──────────────────┐   ┌───────────────────┐  ┌────────────────┐  │  │
│  │  │ PDL Orchestrator │──>│  Task Queue        │  │ Loop Breaker   │  │  │
│  │  │ (pdl_orchestrator│   │  (task_queue.py)   │  │ (loop_breaker  │  │  │
│  │  │  .py)            │   │                    │  │  .py)          │  │  │
│  │  │                  │   │  PostgreSQL-backed  │  │                │  │  │
│  │  │  Lifecycle mgmt  │   │  Priority queue     │  │  Cycle detect  │  │  │
│  │  │  Session B entry │   │  Dedup via key      │  │  5x freeze     │  │  │
│  │  └──────┬───────────┘   └───────┬───────────┘  └────────────────┘  │  │
│  │         │                       │                                    │  │
│  │         │  claims task          │  provides task                     │  │
│  │         v                       v                                    │  │
│  │  ┌──────────────────┐   ┌───────────────────┐  ┌────────────────┐  │  │
│  │  │ Session Ledger   │   │  Budget Partition  │  │ Dedup Engine   │  │  │
│  │  │ (session_ledger  │   │  (budget_partition │  │ (dedup_engine  │  │  │
│  │  │  .py)            │   │   .py)             │  │  .py)          │  │  │
│  │  │                  │   │                    │  │                │  │  │
│  │  │  State tracking  │   │  A:70% / B:30%     │  │  failure_memory│  │  │
│  │  │  Attribution     │   │  Per-task cap: 8¥   │  │  clustering    │  │  │
│  │  └──────────────────┘   │  Per-call cap: 3¥   │  └────────────────┘  │  │
│  │                         └───────────────────┘                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       EXECUTION PLANE                                │  │
│  │                                                                      │  │
│  │  ┌──────────────────┐   ┌───────────────────┐  ┌────────────────┐  │  │
│  │  │ Worktree Manager │   │  Gate Keeper       │  │ Node Awareness │  │  │
│  │  │ (worktree_manager│   │  (gate_keeper.py)  │  │ (node_awareness│  │  │
│  │  │  .py)            │   │                    │  │  .py)          │  │  │
│  │  │                  │   │  File locks        │  │                │  │  │
│  │  │  git worktree    │   │  Protection levels │  │  BRAVO/CHARLIE │  │  │
│  │  │  create/remove   │   │  Advisory locks    │  │  /DELTA status │  │  │
│  │  └──────┬───────────┘   └───────┬───────────┘  └────────────────┘  │  │
│  │         │                       │                                    │  │
│  │         │  provides workspace   │  guards files                      │  │
│  │         v                       v                                    │  │
│  │  ┌──────────────────┐   ┌───────────────────┐                       │  │
│  │  │ Test Harness     │   │  Merge Arbiter     │                       │  │
│  │  │ (test_harness.py)│   │  (merge_arbiter.py)│                       │  │
│  │  │                  │   │                    │                       │  │
│  │  │  4-stage gate    │   │  Conflict detect   │                       │  │
│  │  │  Static/Unit/    │   │  Rebase strategy   │                       │  │
│  │  │  Integration/    │   │  PR creation       │                       │  │
│  │  │  Regression      │   │                    │                       │  │
│  │  └──────────────────┘   └───────────────────┘                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       MAINTENANCE PLANE                              │  │
│  │                                                                      │  │
│  │  ┌──────────────────┐   ┌───────────────────┐                       │  │
│  │  │ Cleanup Daemon   │   │  Recovery Agent    │                       │  │
│  │  │ (cleanup_daemon  │   │  (recovery_agent   │                       │  │
│  │  │  .py)            │   │   .py)             │                       │  │
│  │  │                  │   │                    │                       │  │
│  │  │  Stale worktree  │   │  Orphan detect     │                       │  │
│  │  │  removal         │   │  Session resume    │                       │  │
│  │  │  Disk mgmt       │   │  Lock cleanup      │                       │  │
│  │  └──────────────────┘   └───────────────────┘                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 データフロー: タスク作成→実行→レビュー→マージ→デプロイ

#### シナリオ 1: failure_memory起因の自動バグ修正

```
Step 1: タスク発見
───────────────────
  failure_memory テーブル
       │
       │ dedup_engine が毎時スキャン
       │ error_pattern でクラスタリング
       │ 重複排除 (dedup_key UNIQUE制約)
       v
  pdl_task_queue テーブル
       │
       │ INSERT INTO pdl_task_queue (
       │   id, source='failure_memory', source_id=fm.id,
       │   task_type='bug_fix', priority=10,
       │   description=fm.error_message,
       │   target_files=fm.source_file,
       │   dedup_key=hash(fm.error_pattern)
       │ )
       v
  [タスク status='pending']

Step 2: セッション起動判定
─────────────────────────
  cron (毎時15分, 23:00-07:00 JST)
       │
       │ pdl_orchestrator.py --mode=cron
       │
       v
  can_start_session_b() チェック:
    ✓ active_session_b_exists() == False
    ✓ session_a_is_active() == False
    ✓ get_session_b_remaining_budget() >= 5.0
    ✓ pending_tasks_exist() == True
    ✓ get_disk_free_gb() >= 1.0
    ✓ get_pool_available_connections() >= 3
       │
       │ 全チェック通過
       v
  acquire_process_lock() via flock(/tmp/pdl_session_b.lock)
       │
       │ ロック取得成功
       v
  [続行]

Step 3: タスク取得
─────────────────
  pdl_task_queue から優先度最高のタスクを取得
       │
       │ SELECT * FROM pdl_task_queue
       │ WHERE status = 'pending'
       │ ORDER BY priority ASC, created_at ASC
       │ LIMIT 1
       │ FOR UPDATE SKIP LOCKED
       │
       v
  タスクを 'claimed' に更新
       │
       │ UPDATE pdl_task_queue
       │ SET status='claimed', claimed_by=session_id, claimed_at=NOW()
       │
       v
  pdl_sessions テーブルにレコード作成
       │
       │ INSERT INTO pdl_sessions (
       │   id=uuid, task_id, status='CLAIMED',
       │   started_at=NOW()
       │ )
       v
  [Session status: CLAIMED]

Step 4: Worktree作成
────────────────────
  worktree_manager.create_worktree(session_id, task_id)
       │
       │ branch = "pdl/session-b-{task_id}-{timestamp}"
       │ wt_path = ~/syutain_beta/pdl_worktrees/pdl_session-b-...
       │
       │ git branch {branch} main
       │ git worktree add {wt_path} {branch}
       │
       v
  [Session status: WORKTREE_CREATED]
  pdl_sessions.worktree_path = wt_path
  pdl_sessions.branch_name = branch

Step 5: コンテキスト注入 & コード実行
─────────────────────────────────────
  SESSION_B_CONTEXT テンプレートをロード
       │
       │ CLAUDE.md (26条ルール)
       │ CODE_MAP.md (ファイル構造)
       │ feature_flags.yaml (有効機能)
       │ pdl/config.py (保護ファイルリスト)
       │ task.description (タスク内容)
       │ task.target_files (対象ファイル)
       │
       v
  Gate Keeper でファイルアクセスチェック
       │
       │ 対象ファイルが FORBIDDEN_FILES → 即中止
       │ 対象ファイルが REVIEW_REQUIRED → フラグ付与
       │ それ以外 → 許可
       │
       v
  advisory lock でファイルロック取得
       │
       │ pg_try_advisory_lock(hash(filepath))
       │ 取得失敗 → そのファイルをスキップ
       │
       v
  [Session status: EXECUTING]
       │
       │ LLM呼び出し (session_b_call_llm 経由)
       │   → budget_partition.can_spend() で予算チェック
       │   → choose_best_model_v6(quality="low", budget_sensitive=True)
       │   → ローカルOllama優先 (BRAVO qwen3.5:9b)
       │   → 結果をworktree内のファイルに書き込み
       │
       │ 変更をworktree内でgit commit
       │   git -C {wt_path} add .
       │   git -C {wt_path} commit -m "[PDL] {task_description}"
       │
       v
  [コード変更完了]

Step 6: テスト実行
──────────────────
  test_harness.run_all_gates(wt_path)
       │
       │ Stage 1: Static Analysis (即座)
       │   ├── py_compile 全.pyファイル
       │   ├── detect_import_cycles()
       │   ├── GateKeeper.validate_worktree_changes()
       │   └── scan_for_credentials()
       │   → FAIL → [Session status: TEST_FAILED] → rollback
       │
       │ Stage 2: Unit Tests (~2分)
       │   ├── pytest pdl/tests/
       │   └── pytest tests/ (既存テスト)
       │   → FAIL → [Session status: TEST_FAILED] → rollback
       │
       │ Stage 3: Integration Smoke (~3分)
       │   ├── FastAPI import check
       │   ├── Scheduler import check
       │   ├── 全モジュール import 可能確認
       │   └── DB接続確認 (read-only)
       │   → FAIL → [Session status: TEST_FAILED] → rollback
       │
       │ Stage 4: Regression Detection (~5分)
       │   ├── 環境変数参照チェック
       │   ├── DBスキーマ互換性チェック
       │   ├── LLMルーター経路テスト (mock)
       │   └── feature_flags全パス確認
       │   → FAIL → [Session status: TEST_FAILED] → rollback
       │
       v
  [Session status: TESTING → 全PASS]

Step 7: マージ準備 & PR作成
──────────────────────────
  merge_arbiter.prepare_merge(session_id)
       │
       │ Step 7a: mainの最新をfetch & rebase
       │   git -C {wt_path} fetch origin main
       │   git -C {wt_path} rebase main
       │   → コンフリクト → [自動ロールバック + Discord通知]
       │
       │ Step 7b: rebase後にテスト再実行
       │   test_harness.run_all_gates(wt_path)
       │   → FAIL → [自動ロールバック]
       │
       │ Step 7c: PR作成
       │   git push origin {branch}
       │   gh pr create --title "[PDL] {task_description}"
       │                --body "{PR_TEMPLATE}"
       │                --base main
       │                --head {branch}
       │
       v
  [Session status: PR_CREATED]
  pdl_sessions.pr_url = pr_url

Step 8: 人間レビュー & マージ
────────────────────────────
  Discord通知
       │
       │ "[PDL] Session B完了
       │  Task: {task_id}
       │  PR: {pr_url}
       │  Cost: {cost_jpy}円"
       │
       v
  人間 (daichi) がPRをレビュー
       │
       │ Approve → GitHub merge → main更新
       │ Reject  → PR close → タスクを 'failed' に
       │ Request Changes → コメント残す (次回Session Bで対応)
       │
       v
  [Session status: COMPLETED]

Step 9: デプロイ (マージ後)
──────────────────────────
  main更新をALPHAが検出
       │
       │ (既存の仕組み or 手動)
       │ systemctl restart or kill -HUP
       │
       v
  サービス反映

Step 10: クリーンアップ
──────────────────────
  cleanup_daemon (次回実行時)
       │
       │ worktree削除 (COMPLETED/ROLLED_BACK, 24h超過)
       │ ブランチ削除 (マージ済み)
       │ ファイルロック解放 (セッション終了済み)
       │
       v
  [完全クリーン]
```

#### シナリオ 2: 手動タスク投入

```
人間 (daichi)
     │
     │ psql -c "INSERT INTO pdl_task_queue (id, source, task_type, priority, description, target_files)
     │          VALUES (gen_random_uuid(), 'manual', 'enhancement', 30, 'Add retry logic to jina_client', ARRAY['tools/jina_client.py'])"
     │
     │ もしくは: python pdl/task_queue.py --add --type=enhancement --desc="..." --files="tools/jina_client.py"
     │
     v
  pdl_task_queue に pending タスク追加
     │
     │ (以降はシナリオ1の Step 2 以降と同じフロー)
     v
  ...
```

#### シナリオ 3: Session Aホットフィックス割り込み

```
Session B実行中にSession A (daichi) が緊急修正開始
     │
     │ daichi が claude code を起動
     │ or daichi が手動でファイル編集
     │
     v
  pdl_orchestrator の定期チェック (60秒間隔)
     │
     │ detect_session_a_activity() == True
     │   ├── pgrep -f "claude.*syutain" → プロセス存在
     │   ├── git status --porcelain → 未コミット変更あり
     │   └── 直近5分以内のファイル変更あり
     │
     v
  handle_priority_override(target_file)
     │
     │ 1. Session BのworktreeでStash
     │    git -C {wt_path} stash
     │
     │ 2. Session Bステータス → SUSPENDED
     │    UPDATE pdl_sessions SET status='SUSPENDED'
     │
     │ 3. ファイルロック強制解放
     │    DELETE FROM pdl_file_locks WHERE session_id = {session_b_id}
     │
     │ 4. Discord通知
     │    "[PDL] Session B suspended: Session Aが {file} をホットフィックス中"
     │
     v
  Session A完了を待機 (detect_session_a_activity() == False になるまで)
     │
     │ 5分間隔でチェック
     │
     v
  Session B再開
     │
     │ 1. git -C {wt_path} stash pop
     │ 2. git -C {wt_path} rebase main (Session Aの変更を取り込み)
     │    → コンフリクト → ロールバック
     │    → 成功 → テスト再実行 → 続行
     │ 3. ステータス → EXECUTING
     │
     v
  通常フロー継続
```

#### シナリオ 4: テスト失敗→ロールバック

```
test_harness.run_all_gates() で Stage N が FAIL
     │
     v
  rollback_session(session_id, reason="Test failed at stage {N}: {error}")
     │
     │ 1. git -C {wt_path} checkout .
     │    (worktree内の変更を破棄)
     │
     │ 2. git -C PROJECT_ROOT worktree remove --force {wt_path}
     │    (worktree削除)
     │
     │ 3. git -C PROJECT_ROOT branch -D {branch}
     │    (ブランチ削除)
     │
     │ 4. release_all_locks(session_id)
     │    DELETE FROM pdl_file_locks WHERE session_id = {id}
     │    pg_advisory_unlock_all() for session
     │
     │ 5. UPDATE pdl_sessions SET status='ROLLED_BACK', error_detail=...
     │
     │ 6. UPDATE pdl_task_queue SET status='failed'
     │    WHERE claimed_by = {session_id}
     │
     │ 7. Discord通知
     │    "[PDL] Session B失敗
     │     Task: {task_id}
     │     Stage: {stage}
     │     Error: {error_detail}"
     │
     v
  [完全クリーン状態に復帰]
```

### 1.4 NATSサブジェクトマッピング

PDLは既存のNATSインフラを活用する。以下のサブジェクトをPDL専用に使用:

```
NATS Subject Hierarchy for PDL
═══════════════════════════════

pdl.>                                   # PDL全サブジェクトのワイルドカード

pdl.session.>                           # セッション関連
├── pdl.session.started                 # Session B開始通知
│   Payload: {session_id, task_id, task_type, branch, started_at}
│
├── pdl.session.status_changed          # ステータス変遷
│   Payload: {session_id, old_status, new_status, reason, timestamp}
│
├── pdl.session.completed               # Session B正常完了
│   Payload: {session_id, task_id, pr_url, cost_jpy, duration_sec}
│
├── pdl.session.failed                  # Session B失敗
│   Payload: {session_id, task_id, stage, error, cost_jpy}
│
├── pdl.session.suspended               # Session B一時停止
│   Payload: {session_id, reason, suspended_at}
│
└── pdl.session.resumed                 # Session B再開
    Payload: {session_id, resumed_at}

pdl.task.>                              # タスク関連
├── pdl.task.created                    # 新タスク作成
│   Payload: {task_id, source, task_type, priority, description}
│
├── pdl.task.claimed                    # タスクが取得された
│   Payload: {task_id, session_id, claimed_at}
│
└── pdl.task.deduped                    # タスクが重複排除された
    Payload: {task_id, original_id, dedup_key}

pdl.gate.>                              # Gate Keeper関連
├── pdl.gate.violation                  # 保護ファイル違反
│   Payload: {session_id, filepath, level, reason}
│
├── pdl.gate.lock_acquired              # ファイルロック取得
│   Payload: {session_id, filepath, lock_id}
│
└── pdl.gate.lock_released              # ファイルロック解放
    Payload: {session_id, filepath}

pdl.budget.>                            # 予算関連
├── pdl.budget.spent                    # 予算消費
│   Payload: {session_id, task_id, amount_jpy, model, remaining_jpy}
│
├── pdl.budget.warning                  # 予算警告 (残20%以下)
│   Payload: {remaining_jpy, limit_jpy, percentage}
│
└── pdl.budget.exhausted                # 予算枯渇
    Payload: {session_id, task_id, final_remaining_jpy}

pdl.test.>                              # テスト関連
├── pdl.test.stage_passed               # テストステージ通過
│   Payload: {session_id, stage, duration_sec}
│
├── pdl.test.stage_failed               # テストステージ失敗
│   Payload: {session_id, stage, errors, duration_sec}
│
└── pdl.test.all_passed                 # 全テスト通過
    Payload: {session_id, total_duration_sec}

pdl.merge.>                             # マージ関連
├── pdl.merge.conflict                  # マージコンフリクト
│   Payload: {session_id, branch, conflict_files}
│
├── pdl.merge.pr_created                # PR作成
│   Payload: {session_id, pr_url, pr_number}
│
└── pdl.merge.completed                 # マージ完了
    Payload: {session_id, merge_commit, pr_number}

pdl.cleanup.>                           # クリーンアップ関連
├── pdl.cleanup.worktree_removed        # Worktree削除
│   Payload: {path, age_hours, reason}
│
└── pdl.cleanup.disk_warning            # ディスク容量警告
    Payload: {free_gb, threshold_gb}

pdl.recovery.>                          # 復旧関連
├── pdl.recovery.orphan_detected        # 孤児セッション検出
│   Payload: {session_id, last_status, age_hours}
│
└── pdl.recovery.recovered              # 復旧完了
    Payload: {session_id, action_taken}
```

**NATS使用ポリシー**:
- PDLはNATSを **通知のみ** に使用する。制御フローはPostgreSQLの状態管理で行う
- 全メッセージは `nats_client.publish()` (既存ツール) 経由で送信
- サブスクライバーは `pdl.>` ワイルドカードで全PDLイベントを購読可能
- メッセージはJSON形式、UTF-8エンコーディング
- 最大メッセージサイズ: 1MB (NATSデフォルト)
- QoS: at-most-once (NATSコアのデフォルト)。重要な状態はPostgreSQLが真実の源

### 1.5 PostgreSQLテーブルインタラクション

各セッションがどのテーブルを読み書きするかの完全マトリクス:

```
                          ┌─────────────────────────────────────────────────────┐
                          │          PostgreSQL Table Interaction Matrix         │
                          ├──────────────────────┬────────┬─────────────────────┤
                          │ Table                │ Read   │ Write               │
                          ├──────────────────────┼────────┼─────────────────────┤
PDL Orchestrator          │ pdl_sessions         │   R    │   W (create/update) │
                          │ pdl_task_queue       │   R    │   W (claim)         │
                          │ pdl_file_locks       │   R    │   -                 │
                          │ feature_flags        │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Gate Keeper               │ pdl_file_locks       │   R    │   W (lock/unlock)   │
                          │ pdl_service_locks    │   R    │   W (lock/unlock)   │
                          │ pdl_sessions         │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Budget Partition          │ llm_cost_log         │   R    │   -                 │
                          │ pdl_budget_log       │   R    │   W (record spend)  │
                          │ pdl_sessions         │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Worktree Manager          │ pdl_sessions         │   R    │   W (paths)         │
                          │ pdl_file_locks       │   -    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Task Queue                │ pdl_task_queue       │   R    │   W (CRUD)          │
                          │ failure_memory       │   R    │   - (source only)   │
                          ├──────────────────────┼────────┼─────────────────────┤
Session Ledger            │ pdl_sessions         │   R    │   W                 │
                          │ pdl_change_log       │   R    │   W                 │
                          │ pdl_task_queue       │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Merge Arbiter             │ pdl_sessions         │   R    │   W (pr_url)        │
                          │ pdl_merge_log        │   R    │   W                 │
                          │ pdl_file_locks       │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Test Harness              │ pdl_sessions         │   R    │   W (test_results)  │
                          │ feature_flags        │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Cleanup Daemon            │ pdl_sessions         │   R    │   -                 │
                          │ pdl_file_locks       │   R    │   W (delete stale)  │
                          ├──────────────────────┼────────┼─────────────────────┤
Recovery Agent            │ pdl_sessions         │   R    │   W (status update) │
                          │ pdl_task_queue       │   R    │   W (re-queue)      │
                          │ pdl_file_locks       │   R    │   W (cleanup)       │
                          ├──────────────────────┼────────┼─────────────────────┤
Dedup Engine              │ failure_memory       │   R    │   W (mark deduped)  │
                          │ pdl_task_queue       │   R    │   W (create tasks)  │
                          ├──────────────────────┼────────┼─────────────────────┤
Loop Breaker              │ pdl_sessions         │   R    │   -                 │
                          │ pdl_task_queue       │   R    │   W (freeze)        │
                          │ pdl_merge_log        │   R    │   -                 │
                          ├──────────────────────┼────────┼─────────────────────┤
Node Awareness            │ node_health          │   R    │   -                 │
                          │ (existing table)     │        │                     │
                          └──────────────────────┴────────┴─────────────────────┘
```

**既存テーブルへの書き込みポリシー**:
- PDLは既存テーブルに対して **読み取りのみ** を行う (failure_memory.statusの更新を除く)
- failure_memory.status を 'deduped' に更新するのはdedup_engine のみ
- llm_cost_log への書き込みは既存の llm_router 経由で行われる (PDLは直接書かない)
- PDL専用テーブル (pdl_* プレフィックス) はPDLコンポーネントのみが読み書きする

### 1.6 PDLコンポーネントと既存モジュールの相互作用

```
既存モジュール                      PDLコンポーネント
═══════════════                     ═══════════════════

tools/llm_router.py  ←─── import ─── pdl/budget_partition.py
  choose_best_model_v6()              session_b_call_llm() がラップ
  call_llm()                          quality="low", budget_sensitive=True

tools/db_pool.py     ←─── import ─── pdl/*.py (全コンポーネント)
  get_connection()                    全DB操作はdb_pool経由

tools/nats_client.py ←─── import ─── pdl/pdl_orchestrator.py
  publish()                           NATS通知送信用

tools/discord_notify.py ←─ import ── pdl/pdl_orchestrator.py
  notify_discord()                    Discord通知送信用

tools/event_logger.py ←── import ─── pdl/session_ledger.py
  log_event()                         イベントログ記録用

tools/failure_memory.py ←─ read ──── pdl/dedup_engine.py
  failure_memory テーブル              error_pattern読み取り・重複マーク

brain_alpha/self_healer.py ←─ read ─ pdl/node_awareness.py
  ノード状態取得                       charlie_win11等の状態参照

feature_flags.yaml   ←─── read ──── pdl/test_harness.py
  有効機能リスト                       回帰テストで参照

CLAUDE.md            ←─── read ──── pdl/pdl_orchestrator.py
  26条ルール                          SESSION_B_CONTEXTに注入

CODE_MAP.md          ←─── read ──── pdl/pdl_orchestrator.py
  ファイル構造                        SESSION_B_CONTEXTに注入
```

**依存方向の厳守**: PDLは既存モジュールを **import する** 側。既存モジュールがPDLを import することは **絶対にない**。これにより、PDLを削除しても既存システムは一切影響を受けない。

### 1.7 コアコンポーネント一覧

| # | コンポーネント | ファイル | 責務 | 推定行数 |
|---|---|---|---|---|
| 1 | PDL Orchestrator | `pdl/pdl_orchestrator.py` | Session Bのライフサイクル管理、タスクキュー消費、Session A検出 | ~450行 |
| 2 | Gate Keeper | `pdl/gate_keeper.py` | ファイルロック、保護ファイルチェック、テスト合格ゲート | ~300行 |
| 3 | Budget Partition | `pdl/budget_partition.py` | 予算の分離管理（A:70% / B:30%）、LLMラッパー | ~250行 |
| 4 | Worktree Manager | `pdl/worktree_manager.py` | git worktreeの作成・クリーン・マージ | ~200行 |
| 5 | Task Queue | `pdl/task_queue.py` | PostgreSQLベースの優先度付きタスクキュー | ~200行 |
| 6 | Session Ledger | `pdl/session_ledger.py` | 全セッションの状態・変更・帰属を記録 | ~180行 |
| 7 | Merge Arbiter | `pdl/merge_arbiter.py` | コンフリクト検出と解決戦略、PR作成 | ~250行 |
| 8 | Test Harness | `pdl/test_harness.py` | worktree内での4段階テスト実行とゲート判定 | ~350行 |
| 9 | Cleanup Daemon | `pdl/cleanup_daemon.py` | 古いworktree/ブランチの自動削除 | ~150行 |
| 10 | Recovery Agent | `pdl/recovery_agent.py` | 中断セッションの検出と復旧 | ~180行 |
| 11 | Node Awareness | `pdl/node_awareness.py` | ノード状態認識（BRAVO/CHARLIE/DELTA） | ~120行 |
| 12 | Loop Breaker | `pdl/loop_breaker.py` | 無限ループ防止（PR→trigger→PR...） | ~130行 |
| 13 | Dedup Engine | `pdl/dedup_engine.py` | failure_memory重複排除 | ~150行 |
| 14 | Config | `pdl/config.py` | PDL設定定数、保護ファイルリスト | ~120行 |
| 15 | Schemas | `pdl/schemas.py` | DBスキーマ定義、マイグレーション | ~130行 |
| | **合計** | | | **~3,160行** |

### 1.8 ディレクトリ構造

```
~/syutain_beta/
├── pdl/                          # Parallel Dev Layer (新規、既存コードに触れない)
│   ├── __init__.py               # パッケージ初期化 (version, logger setup)
│   ├── pdl_orchestrator.py       # メインオーケストレーター
│   ├── gate_keeper.py            # ファイルロック＆保護
│   ├── budget_partition.py       # 予算分離
│   ├── worktree_manager.py       # git worktree管理
│   ├── task_queue.py             # タスクキュー
│   ├── session_ledger.py         # セッション記録
│   ├── merge_arbiter.py          # マージ仲裁
│   ├── test_harness.py           # テストゲート
│   ├── cleanup_daemon.py         # クリーンアップ
│   ├── recovery_agent.py         # 復旧エージェント
│   ├── node_awareness.py         # ノード状態認識
│   ├── loop_breaker.py           # 無限ループ防止
│   ├── dedup_engine.py           # failure_memory重複排除
│   ├── config.py                 # PDL設定定数
│   ├── schemas.py                # DB スキーマ定義
│   └── tests/                    # PDL自体のテスト
│       ├── __init__.py
│       ├── test_gate_keeper.py
│       ├── test_budget_partition.py
│       ├── test_worktree_manager.py
│       ├── test_task_queue.py
│       ├── test_test_harness.py
│       ├── test_loop_breaker.py
│       └── conftest.py           # pytest fixtures
├── pdl_worktrees/                # worktree配置ディレクトリ (gitignore)
│   ├── pdl_session-b-abc123-1711900000/
│   └── pdl_session-b-def456-1711903600/
└── (既存ファイルは一切変更しない)
```

### 1.9 設計原則

| # | 原則 | 説明 | 違反した場合 |
|---|------|------|------------|
| 1 | **Zero Mutation** | 既存コードへの変更ゼロ。PDLは独立ディレクトリ `pdl/` に完結する | PDLを丸ごと削除すれば元に戻る |
| 2 | **Fail Closed** | 判断に迷ったら安全側（変更を拒否、セッション終了） | 変更が本番に入るリスクを最小化 |
| 3 | **Session A Priority** | Session Aは常に最優先。Session Bは譲る。Session A検出で即サスペンド | Session Aの作業が阻害されない |
| 4 | **Atomic Changes** | Session Bの変更はPRとして提出され、全テスト通過まで本番に入らない | 部分変更が本番に漏れない |
| 5 | **Budget Isolation** | Session BがSession Aの予算を食い潰すことは構造的に不可能 | 日次予算超過しない |
| 6 | **Observability** | 全操作はPostgreSQLに記録、NATSで通知、Discordで報告 | 何が起きたか常に追跡可能 |
| 7 | **Idempotent Recovery** | 復旧操作は何度実行しても同じ結果になる | 再起動でシステムが壊れない |
| 8 | **Minimal Privilege** | Session BはGate Keeper経由でのみファイルにアクセス | 重要ファイルの誤変更を防止 |

---

## 2. 詳細コンポーネント仕様

### 2.1 PDL Orchestrator (`pdl/pdl_orchestrator.py`)

#### 2.1.1 目的 (なぜ存在するか)

PDL全体の中央制御装置。Session Bのライフサイクル（起動判定→タスク取得→実行→テスト→PR作成→クリーンアップ）を一貫して管理する唯一のエントリーポイント。cronから呼ばれる唯一のファイルでもある。

#### 2.1.2 入力/出力

**入力**:
- コマンドライン引数: `--mode=cron` (cron起動) / `--mode=manual` (手動起動) / `--mode=resume` (サスペンド再開)
- 環境変数: `.env` から `DATABASE_URL`, `NATS_URL`, `DISCORD_WEBHOOK_URL` を読み取り
- PostgreSQL: `pdl_task_queue` (保留タスク), `pdl_sessions` (既存セッション状態)
- ファイルシステム: `/tmp/pdl_session_b.lock` (プロセスロック)

**出力**:
- PostgreSQL: `pdl_sessions` レコード作成/更新
- Git: worktree作成, ブランチ作成, コミット, プッシュ
- GitHub: PR作成 (`gh pr create`)
- NATS: `pdl.session.*`, `pdl.task.*` メッセージ
- Discord: セッション開始/完了/失敗通知
- ログ: `logs/pdl_cron.log`

#### 2.1.3 アルゴリズム (詳細疑似コード)

```python
async def main(mode: str):
    """PDL Orchestratorメインエントリーポイント"""

    # ─── Phase 0: 初期化 ───
    logger.info(f"PDL Orchestrator starting in {mode} mode")
    await schemas.ensure_tables()          # DBスキーマ確認/作成
    await recovery_agent.recover_interrupted_sessions()  # 起動時復旧

    # ─── Phase 1: プロセスロック ───
    if not acquire_process_lock():
        logger.info("Another PDL process is running. Exiting.")
        return  # 別プロセスが実行中

    # ─── Phase 2: 起動条件チェック ───
    can_start, reason = await can_start_session_b()
    if not can_start:
        logger.info(f"Cannot start Session B: {reason}")
        return

    # ─── Phase 3: タスク取得 ───
    task = await task_queue.claim_next_task()
    if task is None:
        logger.info("No pending tasks")
        return

    session_id = str(uuid.uuid4())
    logger.info(f"Starting Session B: {session_id} for task {task['id']}")

    try:
        # ─── Phase 4: セッション記録 ───
        await session_ledger.create_session(
            session_id=session_id,
            task_id=task["id"],
            status="CLAIMED",
        )
        await nats_publish("pdl.session.started", {
            "session_id": session_id,
            "task_id": task["id"],
            "task_type": task["task_type"],
            "started_at": datetime.utcnow().isoformat(),
        })

        # ─── Phase 5: Worktree作成 ───
        wt_path = await worktree_manager.create_worktree(session_id, task["id"])
        await session_ledger.update_session(session_id, status="WORKTREE_CREATED",
                                            worktree_path=wt_path)

        # ─── Phase 6: ファイルアクセスチェック ───
        if task["target_files"]:
            for filepath in task["target_files"]:
                decision = gate_keeper.check_file_access(filepath, "modify")
                if not decision.allowed:
                    raise GateViolationError(
                        f"Cannot modify {filepath}: {decision.reason}"
                    )
                # ファイルロック取得
                locked = await gate_keeper.acquire_file_lock(filepath, session_id)
                if not locked:
                    raise FileLockError(f"Cannot lock {filepath}: held by another session")

        # ─── Phase 7: コード実行 ───
        await session_ledger.update_session(session_id, status="EXECUTING")

        # Session A活動の定期チェック開始 (バックグラウンドタスク)
        monitor_task = asyncio.create_task(
            _monitor_session_a_activity(session_id, wt_path)
        )

        # コンテキスト構築
        context = _build_session_b_context(task)

        # LLM呼び出しでコード変更を生成
        changes = await _execute_task(context, task, wt_path, session_id)

        # 変更をworktree内でコミット
        _commit_changes(wt_path, task)

        monitor_task.cancel()  # Session A監視を停止

        # ─── Phase 8: テスト実行 ───
        await session_ledger.update_session(session_id, status="TESTING")
        test_result = await test_harness.run_all_gates(wt_path)

        if not test_result.passed:
            raise TestFailedError(
                f"Tests failed at stage '{test_result.stage}': "
                f"{test_result.details}"
            )

        # ─── Phase 9: マージ準備 & PR作成 ───
        pr_url = await merge_arbiter.create_pr(session_id, task, wt_path)
        await session_ledger.update_session(
            session_id, status="PR_CREATED", pr_url=pr_url
        )

        # ─── Phase 10: 完了 ───
        cost = await budget_partition.get_task_spent(task["id"])
        await session_ledger.update_session(
            session_id, status="COMPLETED", cost_jpy=cost
        )
        await task_queue.complete_task(task["id"])

        await nats_publish("pdl.session.completed", {
            "session_id": session_id,
            "task_id": task["id"],
            "pr_url": pr_url,
            "cost_jpy": cost,
        })
        await notify_discord(NOTIFICATION_TEMPLATES["session_completed"].format(
            task_id=task["id"], pr_url=pr_url, cost_jpy=cost,
        ))

        logger.info(f"Session B completed: {session_id}, PR: {pr_url}")

    except GateViolationError as e:
        logger.error(f"Gate violation: {e}")
        await _handle_session_failure(session_id, task["id"], "gate_violation", str(e))

    except FileLockError as e:
        logger.error(f"File lock error: {e}")
        await _handle_session_failure(session_id, task["id"], "file_lock", str(e))

    except BudgetExhaustedError as e:
        logger.error(f"Budget exhausted: {e}")
        await _handle_session_failure(session_id, task["id"], "budget_exhausted", str(e))

    except TestFailedError as e:
        logger.error(f"Tests failed: {e}")
        await _handle_session_failure(session_id, task["id"], "test_failed", str(e))

    except WorktreeCreationError as e:
        logger.error(f"Worktree creation failed: {e}")
        await _handle_session_failure(session_id, task["id"], "worktree_error", str(e))

    except SessionSuspendedError as e:
        logger.warning(f"Session suspended: {e}")
        # サスペンド状態は失敗ではない。次回再開される。

    except Exception as e:
        logger.exception(f"Unexpected error in Session B: {e}")
        await _handle_session_failure(session_id, task["id"], "unexpected", str(e))

    finally:
        # ファイルロック解放
        await gate_keeper.release_all_locks(session_id)
        # プロセスロック解放 (fdクローズで自動解放)


async def _handle_session_failure(session_id: str, task_id: str, stage: str, error: str):
    """セッション失敗の共通ハンドラ"""
    await worktree_manager.rollback_session(session_id, f"{stage}: {error}")
    await task_queue.fail_task(task_id)
    cost = await budget_partition.get_task_spent(task_id)
    await session_ledger.update_session(
        session_id, status="ROLLED_BACK" if stage != "budget_exhausted" else "FAILED",
        error_detail=f"{stage}: {error}", cost_jpy=cost,
    )
    await nats_publish("pdl.session.failed", {
        "session_id": session_id, "task_id": task_id,
        "stage": stage, "error": error, "cost_jpy": cost,
    })
    await notify_discord(NOTIFICATION_TEMPLATES["session_failed"].format(
        task_id=task_id, stage=stage, error=error[:200],
    ))


async def _monitor_session_a_activity(session_id: str, wt_path: str):
    """Session A活動の定期監視 (バックグラウンド)"""
    while True:
        await asyncio.sleep(60)  # 60秒間隔
        if detect_session_a_activity():
            logger.warning("Session A activity detected, suspending Session B")
            await handle_priority_override_all(session_id, wt_path)
            raise SessionSuspendedError("Session A became active")


def _build_session_b_context(task: dict) -> str:
    """Session B用のコンテキスト文字列を構築"""
    parts = [SESSION_B_CONTEXT]
    parts.append(f"\n## 今回のタスク\n")
    parts.append(f"- タスクID: {task['id']}")
    parts.append(f"- 種別: {task['task_type']}")
    parts.append(f"- 説明: {task['description']}")
    if task.get("target_files"):
        parts.append(f"- 対象ファイル: {', '.join(task['target_files'])}")
    if task.get("source") == "failure_memory":
        parts.append(f"- 元failure_memory ID: {task['source_id']}")
    return "\n".join(parts)
```

#### 2.1.4 エラーハンドリング (全例外パス)

| 例外 | 発生条件 | ハンドリング |
|------|---------|------------|
| `GateViolationError` | 保護ファイルへのアクセス試行 | セッション即終了、ロールバック、Discord通知 |
| `FileLockError` | ファイルロック取得失敗 | セッション即終了、ロールバック |
| `BudgetExhaustedError` | 予算枯渇 | セッション即終了、消費分は記録済み |
| `TestFailedError` | テストゲート不通過 | ロールバック、失敗ステージとエラー詳細を記録 |
| `WorktreeCreationError` | git worktree作成失敗 | 中途半端なworktree/ブランチをクリーン |
| `SessionSuspendedError` | Session A検出 | Stash→サスペンド (失敗ではない) |
| `subprocess.CalledProcessError` | gitコマンド失敗 | ロールバック、コマンド出力を記録 |
| `asyncpg.PostgresError` | DB操作失敗 | 3回リトライ後ロールバック |
| `ConnectionRefusedError` | NATS/DB接続不可 | NATS通知はスキップ (ベストエフォート)。DB不可はセッション中止 |
| `TimeoutError` | 45分ハードリミット超過 | セッション強制終了、ロールバック |
| `OSError` | ディスクフル等 | セッション即終了、ロールバック |
| `Exception` (catchall) | 想定外エラー | ロールバック、スタックトレース記録、Discord通知 |

#### 2.1.5 設定オプション

| 設定名 | デフォルト値 | 環境変数 | 説明 |
|--------|------------|---------|------|
| `SESSION_B_HARD_TIMEOUT_SEC` | 2700 (45分) | `PDL_SESSION_B_TIMEOUT` | セッション最大実行時間 |
| `SESSION_A_CHECK_INTERVAL_SEC` | 60 | `PDL_SESSION_A_CHECK_INTERVAL` | Session A検出チェック間隔 |
| `SESSION_A_RECENT_CHANGE_MINUTES` | 5 | `PDL_SESSION_A_CHANGE_WINDOW` | ファイル変更検出の時間窓 |
| `MAX_CONCURRENT_SESSION_B` | 1 | `PDL_MAX_SESSIONS` | Session B同時実行数 |
| `LOCK_FILE_PATH` | `/tmp/pdl_session_b.lock` | `PDL_LOCK_FILE` | プロセスロックファイル |
| `LOG_FILE` | `logs/pdl_cron.log` | `PDL_LOG_FILE` | ログ出力先 |
| `CRON_HOURS` | `[23,0,1,2,3,4,5,6]` | `PDL_CRON_HOURS` | cron起動を許可する時間帯 (JST) |

#### 2.1.6 依存関係

```python
# 標準ライブラリ
import asyncio, uuid, os, sys, time, fcntl, subprocess, logging, argparse
from datetime import datetime
from pathlib import Path

# 既存モジュール (読み取りのみ)
from tools.db_pool import get_connection
from tools.nats_client import publish as nats_publish
from tools.discord_notify import notify_discord
from tools.event_logger import log_event

# PDL内部モジュール
from pdl.config import *
from pdl.schemas import ensure_tables
from pdl.gate_keeper import GateKeeper
from pdl.budget_partition import BudgetPartition, BudgetExhaustedError
from pdl.worktree_manager import WorktreeManager, WorktreeCreationError
from pdl.task_queue import TaskQueue
from pdl.session_ledger import SessionLedger
from pdl.merge_arbiter import MergeArbiter
from pdl.test_harness import TestHarness, TestFailedError
from pdl.recovery_agent import RecoveryAgent
from pdl.loop_breaker import LoopBreaker
```

#### 2.1.7 DBテーブル

読み取り: `pdl_task_queue`, `pdl_sessions`, `pdl_file_locks`, `feature_flags`
書き込み: `pdl_sessions` (create/update)

#### 2.1.8 推定コードサイズ

約450行 (テスト除く)

---

### 2.2 Gate Keeper (`pdl/gate_keeper.py`)

#### 2.2.1 目的

Session Bのファイルアクセスを制御する「門番」。3段階の保護レベルでファイルを分類し、禁止ファイルへの変更を絶対に阻止する。PostgreSQLのadvisory lockを使ったファイルレベルの排他制御も提供する。

#### 2.2.2 入力/出力

**入力**:
- ファイルパス (相対パス)
- 操作種別 ("modify", "create", "delete")
- セッションID
- worktreeパス (validate_worktree_changes用)

**出力**:
- `GateDecision(allowed: bool, reason: str, level: int)` - アクセス可否判定
- `GateViolation(file: str, decision: GateDecision)` - 違反レコード
- `bool` - ファイルロック取得結果

#### 2.2.3 アルゴリズム

```python
# ─── 保護レベル判定 ───

def check_file_access(filepath: str, operation: str) -> GateDecision:
    """
    Step 1: filepathをプロジェクトルートからの相対パスに正規化
    Step 2: FORBIDDEN_FILES (Level 0) とのマッチング
      - 完全一致チェック (rel == forbidden)
      - プレフィックスマッチ (rel.startswith(forbidden))
        → "pdl/" はプレフィックスマッチで pdl/ 以下全てを保護
      - マッチ → GateDecision(allowed=False, level=0)
    Step 3: REVIEW_REQUIRED_FILES (Level 1) とのマッチング
      - 完全一致のみ
      - マッチ → GateDecision(allowed=True, level=1, reason="REVIEW_REQUIRED")
    Step 4: それ以外 → GateDecision(allowed=True, level=2)
    """

# ─── ファイルロック ───

async def acquire_file_lock(filepath: str, session_id: str, timeout_sec: int = 10) -> bool:
    """
    Step 1: filepathからint64ハッシュを生成
      lock_id = int(hashlib.sha256(filepath.encode()).hexdigest()[:15], 16) & 0x7FFFFFFFFFFFFFFF
    Step 2: pg_try_advisory_lock(lock_id) を実行 (ノンブロッキング)
      - True → ロック取得成功
      - False → 別セッションがロック保持中
    Step 3: 成功時、pdl_file_locks テーブルにINSERT (ON CONFLICT DO UPDATE)
    Step 4: 結果を返す
    """

async def release_file_lock(filepath: str, session_id: str):
    """
    Step 1: lock_idを再計算
    Step 2: pg_advisory_unlock(lock_id)
    Step 3: pdl_file_locks テーブルからDELETE
    """

async def release_all_locks(session_id: str):
    """
    Step 1: pdl_file_locks WHERE session_id = ? を全取得
    Step 2: 各ロックに対して pg_advisory_unlock(lock_id)
    Step 3: pdl_file_locks WHERE session_id = ? をDELETE
    """

# ─── Worktree変更検証 ───

def validate_worktree_changes(worktree_path: str) -> list[GateViolation]:
    """
    Step 1: git diff --name-only HEAD でworktree内の変更ファイル一覧取得
    Step 2: 各ファイルに対して check_file_access() を実行
    Step 3: allowed=False のものを GateViolation として収集
    Step 4: 違反リストを返す
    """

# ─── サービス再起動ロック ───

async def acquire_service_restart_lock(service_name: str, session_id: str) -> bool:
    """
    Step 1: "service_restart:{service_name}" からlock_idを生成
    Step 2: pg_try_advisory_lock(lock_id) (ノンブロッキング)
    Step 3: 成功時、pdl_service_locks にINSERT
    Step 4: 結果を返す
    """
```

#### 2.2.4 エラーハンドリング

| 例外 | 発生条件 | ハンドリング |
|------|---------|------------|
| `asyncpg.PostgresError` | DB接続/クエリ失敗 | Fail Closed: ロック取得失敗として扱う (安全側) |
| `ValueError` | 不正なfilepathフォーマット | Fail Closed: アクセス拒否 |
| `OSError` | ファイルシステムエラー | Fail Closed: アクセス拒否 |
| `subprocess.CalledProcessError` | git diffコマンド失敗 | 空のdiffとして扱い、全ファイルをチェック対象に |

#### 2.2.5 設定オプション

| 設定名 | デフォルト値 | 説明 |
|--------|------------|------|
| `FORBIDDEN_FILES` | (config.pyで定義、31エントリ) | Level 0: 変更絶対禁止 |
| `REVIEW_REQUIRED_FILES` | (config.pyで定義、11エントリ) | Level 1: 変更可能だがレビュー必須 |
| `LOCK_TIMEOUT_SEC` | 10 | ロック取得タイムアウト |
| `SERVICE_LOCK_TTL_SEC` | 60 | サービスロックの自動解放時間 |

#### 2.2.6 FORBIDDEN_FILES 完全リスト

```python
FORBIDDEN_FILES = {
    # コアカーネル (システムの心臓部)
    "agents/os_kernel.py",            # タスクオーケストレーション中核
    "agents/approval_manager.py",     # 人間承認フロー

    # 安全装置 (ループ防止・予算防止・緊急停止)
    "tools/emergency_kill.py",        # 緊急停止ツール
    "tools/loop_guard.py",            # 9層ループ防止壁
    "tools/budget_guard.py",          # 予算ガード
    "tools/semantic_loop_detector.py",# セマンティックループ検出
    "tools/cross_goal_detector.py",   # Cross-Goal干渉検出

    # 上位判断層安全装置
    "brain_alpha/safety_check.py",    # 安全チェック
    "brain_alpha/self_healer.py",     # 自己修復

    # 認証・秘密情報
    ".env",                           # 環境変数 (全APIキー)
    "credentials.json",               # Google認証情報
    "token.json",                     # Google OAuthトークン
    "config/node_alpha.yaml",         # ALPHAノード設定
    "config/node_bravo.yaml",         # BRAVOノード設定
    "config/node_charlie.yaml",       # CHARLIEノード設定
    "config/node_delta.yaml",         # DELTAノード設定
    "config/nats-server.conf",        # NATSサーバー設定
    "certs/",                         # TLS証明書ディレクトリ

    # インフラ設定
    "Caddyfile",                      # リバースプロキシ設定
    "start.sh",                       # 起動スクリプト
    "worker_main.py",                 # ワーカーメインプロセス

    # PDL自体 (自己改変防止)
    "pdl/",                           # PDL全体

    # ルールファイル (AIの行動規範)
    "CLAUDE.md",                      # 26条ルール
    "IDENTITY.md",                    # アイデンティティ定義
    "SOUL.md",                        # 魂定義
    "AGENTS.md",                      # エージェント定義
    "feature_flags.yaml",             # 機能フラグ
}
```

#### 2.2.7 依存関係

```python
import os, hashlib, subprocess, logging
from dataclasses import dataclass
from tools.db_pool import get_connection
from pdl.config import FORBIDDEN_FILES, REVIEW_REQUIRED_FILES, PROJECT_ROOT
```

#### 2.2.8 DBテーブル

読み取り: `pdl_file_locks`, `pdl_service_locks`, `pdl_sessions`
書き込み: `pdl_file_locks` (INSERT/DELETE), `pdl_service_locks` (INSERT/DELETE)

#### 2.2.9 推定コードサイズ

約300行

---

### 2.3 Budget Partition (`pdl/budget_partition.py`)

#### 2.3.1 目的

Session AとSession Bの予算を構造的に分離し、Session Bが暴走してSession Aの予算を食い潰すことを不可能にする。3段階の支出制限（日次B枠、タスク単位、呼び出し単位）でコスト暴走を防止する。

#### 2.3.2 入力/出力

**入力**:
- `amount_jpy: float` - 推定コスト (円)
- `task_id: str` - タスクID
- `prompt: str` - LLMプロンプト
- `model: str` - モデル名 (オプション)

**出力**:
- `(bool, str)` - (支出可否, 理由)
- `float` - 残予算 (円)
- `str` - LLM応答テキスト

**データ形式**:
```json
// pdl_budget_log レコード
{
  "session_id": "uuid-...",
  "task_id": "task-...",
  "amount_jpy": 1.5,
  "model": "qwen3.5:9b",
  "remaining_jpy": 18.5,
  "created_at": "2026-04-01T23:15:00Z"
}
```

#### 2.3.3 アルゴリズム

```python
class BudgetPartition:
    DAILY_BUDGET_JPY = 80.0           # 日次予算合計
    SESSION_A_RATIO = 0.70             # Session A: 70% = 56円
    SESSION_B_RATIO = 0.30             # Session B: 30% = 24円
    SESSION_B_SINGLE_TASK_MAX_JPY = 8.0  # タスク単位上限: 8円
    SESSION_B_SINGLE_CALL_MAX_JPY = 3.0  # 呼び出し単位上限: 3円
    MIN_START_BUDGET_JPY = 5.0         # セッション開始に必要な最低残予算

    async def get_session_b_remaining(self) -> float:
        """
        Step 1: llm_cost_log から今日のSession B支出合計を取得
          SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log
          WHERE created_at::date = CURRENT_DATE
            AND metadata->>'session_type' = 'session_b'
        Step 2: 日次上限 (24円) - 支出合計 = 残予算
        Step 3: max(0, 残予算) を返す
        """

    async def can_spend(self, amount_jpy: float, task_id: str) -> tuple[bool, str]:
        """
        Step 1: 残予算チェック
          remaining = await get_session_b_remaining()
          if amount_jpy > remaining:
            return False, "予算不足: 残{remaining}円 < 要求{amount_jpy}円"

        Step 2: 単一呼び出し上限チェック
          if amount_jpy > SESSION_B_SINGLE_CALL_MAX_JPY:
            return False, "単一呼び出し上限超過"

        Step 3: タスク累計チェック
          task_spent = await _get_task_spent(task_id)
          if task_spent + amount_jpy > SESSION_B_SINGLE_TASK_MAX_JPY:
            return False, "タスク予算超過"

        Step 4: return True, "OK"
        """

    async def _get_task_spent(self, task_id: str) -> float:
        """
        SELECT COALESCE(SUM(amount_jpy), 0)
        FROM pdl_budget_log WHERE task_id = $1
        """

    async def record_spend(self, session_id, task_id, amount_jpy, model):
        """
        Step 1: pdl_budget_log にINSERT
        Step 2: 残予算を計算
        Step 3: 残予算が20%以下なら NATS + Discord警告
        """


async def session_b_call_llm(prompt: str, task_id: str, session_id: str, **kwargs) -> str:
    """Session B専用LLMラッパー"""
    # Step 1: 事前コスト見積もり
    estimated_cost = estimate_cost(prompt, kwargs.get("model"))

    # Step 2: 予算チェック
    can, reason = await budget_partition.can_spend(estimated_cost, task_id)
    if not can:
        raise BudgetExhaustedError(reason)

    # Step 3: Session Bはローカルモデル優先
    kwargs.setdefault("quality", "low")
    kwargs.setdefault("local_available", True)
    kwargs.setdefault("budget_sensitive", True)

    # Step 4: 既存ルーター経由で呼び出し
    model_sel = choose_best_model_v6(
        task_type=kwargs.get("task_type", "general"), **kwargs
    )
    result = await call_llm(prompt, model=model_sel["model"])

    # Step 5: 実際のコストを記録
    actual_cost = calculate_actual_cost(model_sel, result)
    await budget_partition.record_spend(
        session_id, task_id, actual_cost, model_sel["model"]
    )

    # Step 6: llm_cost_log にも記録 (session_type=session_b メタデータ付き)
    await record_cost(model_sel, task_id, session_type="session_b")

    return result


def estimate_cost(prompt: str, model: str = None) -> float:
    """
    トークン数からコストを推定
    - ローカルOllama: 0円 (電気代のみ)
    - DeepSeek: ~0.14円/1K tokens (入力)
    - Claude: ~2.5円/1K tokens (入力)
    Session Bはローカル優先なので、多くの場合0円に近い
    """
```

#### 2.3.4 エラーハンドリング

| 例外 | 発生条件 | ハンドリング |
|------|---------|------------|
| `BudgetExhaustedError` | 予算不足 | 呼び出し元 (orchestrator) にバブルアップ |
| `asyncpg.PostgresError` | DB接続失敗 | 3回リトライ。失敗時は Fail Closed (支出不可) |
| `TimeoutError` | LLM呼び出しタイムアウト | コストは推定値で記録。結果はエラー |
| `ValueError` | 不正なamount_jpy | 0以下は拒否 |

#### 2.3.5 設定オプション

| 設定名 | デフォルト値 | 環境変数 | 説明 |
|--------|------------|---------|------|
| `DAILY_BUDGET_JPY` | 80.0 | `PDL_DAILY_BUDGET_JPY` | 日次予算合計 (CLAUDE.mdの設定に従う) |
| `SESSION_B_RATIO` | 0.30 | `PDL_SESSION_B_RATIO` | Session Bの予算割合 |
| `SESSION_B_SINGLE_TASK_MAX_JPY` | 8.0 | `PDL_TASK_MAX_JPY` | タスク単位上限 |
| `SESSION_B_SINGLE_CALL_MAX_JPY` | 3.0 | `PDL_CALL_MAX_JPY` | 呼び出し単位上限 |
| `BUDGET_WARNING_THRESHOLD` | 0.20 | `PDL_BUDGET_WARN_PCT` | 残予算警告閾値 (20%) |

#### 2.3.6 依存関係

```python
from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import publish
from tools.discord_notify import notify_discord
from pdl.config import DAILY_BUDGET_JPY
```

#### 2.3.7 DBテーブル

読み取り: `llm_cost_log` (Session B支出集計), `pdl_budget_log` (タスク累計)
書き込み: `pdl_budget_log` (支出記録)

#### 2.3.8 推定コードサイズ

約250行

---

### 2.4 Worktree Manager (`pdl/worktree_manager.py`)

#### 2.4.1 目的

Git worktreeのライフサイクルを管理する。Session Bの作業空間をmainブランチから隔離し、失敗時は完全にクリーンアップする。mainの安全性を保証する物理的な防壁。

#### 2.4.2 入力/出力

**入力**:
- `session_id: str`, `task_id: str` - ワークツリー作成時の識別子
- `worktree_path: str`, `branch_name: str` - クリーンアップ対象
- `reason: str` - ロールバック理由

**出力**:
- `str` - 作成されたworktreeの絶対パス
- `None` - ロールバック/クリーン操作は戻り値なし

#### 2.4.3 アルゴリズム

```python
class WorktreeManager:
    WORKTREE_BASE = f"{PROJECT_ROOT}/pdl_worktrees"
    MAX_WORKTREES = 5

    async def create_worktree(self, session_id: str, task_id: str) -> str:
        """
        Step 1: ブランチ名とworktreeパスを決定
          branch = f"pdl/session-b-{task_id}-{int(time.time())}"
          wt_path = f"{WORKTREE_BASE}/{branch.replace('/', '_')}"

        Step 2: 既存worktree数チェック
          count = len([d for d in os.scandir(WORKTREE_BASE) if d.is_dir()])
          if count >= MAX_WORKTREES:
            raise WorktreeCreationError("Too many worktrees")

        Step 3: ブランチ作成
          git -C PROJECT_ROOT branch {branch} main
          → CalledProcessError → _force_cleanup() → raise

        Step 4: worktree作成
          git -C PROJECT_ROOT worktree add {wt_path} {branch}
          → CalledProcessError → _force_cleanup() → raise

        Step 5: worktreeに.envのシンボリックリンクを作成
          ln -sf {PROJECT_ROOT}/.env {wt_path}/.env
          (テスト時に本番と同じ環境変数を参照するため)

        Step 6: pdl_sessions.worktree_path と branch_name を更新

        Step 7: return wt_path
        """

    async def rollback_session(self, session_id: str, reason: str):
        """
        Step 1: pdl_sessions からセッション情報取得
        Step 2: worktree内の変更を破棄
          git -C {wt_path} checkout .
        Step 3: worktreeを削除
          git -C PROJECT_ROOT worktree remove --force {wt_path}
        Step 4: ブランチを削除
          git -C PROJECT_ROOT branch -D {branch}
        Step 5: ファイルロックを全解放
          await gate_keeper.release_all_locks(session_id)
        Step 6: pdl_sessions.status = 'ROLLED_BACK'
        Step 7: Discord通知
        """

    def _force_cleanup(self, wt_path: str, branch: str):
        """
        Step 1: wt_pathが存在すれば git worktree remove --force
        Step 2: 残っていれば shutil.rmtree (最終手段)
        Step 3: git branch -D {branch} (存在すれば)
        """

    def _commit_changes(self, wt_path: str, task: dict):
        """
        Step 1: git -C {wt_path} add .
        Step 2: git -C {wt_path} commit -m "[PDL] {task['description'][:72]}"
        Step 3: コミットハッシュを取得して返す
          git -C {wt_path} rev-parse HEAD
        """
```

#### 2.4.4 エラーハンドリング

| 例外 | 発生条件 | ハンドリング |
|------|---------|------------|
| `WorktreeCreationError` | ブランチ/worktree作成失敗 | `_force_cleanup()` で中途半端な状態を解消 |
| `subprocess.CalledProcessError` | git コマンド失敗 | エラー出力をログ、`_force_cleanup()` |
| `OSError` | ディスクフル、パーミッションエラー | ログ記録、エラー伝播 |
| `shutil.Error` | rmtree失敗 | ignore_errors=True で無視 |

#### 2.4.5 設定オプション

| 設定名 | デフォルト値 | 説明 |
|--------|------------|------|
| `WORKTREE_BASE` | `~/syutain_beta/pdl_worktrees` | worktree配置ディレクトリ |
| `MAX_WORKTREES` | 5 | 同時存在可能なworktree数 |

#### 2.4.6 依存関係

```python
import os, subprocess, shutil, time, logging
from pdl.config import PROJECT_ROOT
from pdl.gate_keeper import GateKeeper
from pdl.session_ledger import SessionLedger
from tools.discord_notify import notify_discord
```

#### 2.4.7 DBテーブル

読み取り: `pdl_sessions`
書き込み: `pdl_sessions` (worktree_path, branch_name更新)

#### 2.4.8 推定コードサイズ

約200行

---

### 2.5 Task Queue (`pdl/task_queue.py`)

#### 2.5.1 目的

PostgreSQLベースの優先度付きタスクキュー。failure_memory、手動投入、スケジューラーからタスクを受け付け、Session Bに供給する。重複排除キーによるDBレベルの重複防止を提供。

#### 2.5.2 入力/出力

**入力 (タスク追加)**:
```json
{
  "source": "failure_memory|manual|scheduler|auto_fix",
  "source_id": "fm-123",
  "task_type": "bug_fix|enhancement|refactor|test",
  "priority": 10,
  "description": "Fix timeout error in jina_client.py",
  "target_files": ["tools/jina_client.py"],
  "dedup_key": "sha256:abc..."
}
```

**出力 (タスク取得)**:
```json
{
  "id": "task-uuid",
  "source": "failure_memory",
  "source_id": "fm-123",
  "task_type": "bug_fix",
  "priority": 10,
  "description": "Fix timeout error in jina_client.py",
  "target_files": ["tools/jina_client.py"],
  "status": "claimed",
  "claimed_by": "session-uuid",
  "claimed_at": "2026-04-01T23:15:00Z"
}
```

#### 2.5.3 アルゴリズム

```python
class TaskQueue:
    PRIORITY_MAP = {
        "bug_fix": 10,       # 最高優先度
        "security": 15,      # セキュリティ修正
        "enhancement": 50,   # 機能改善
        "refactor": 70,      # リファクタリング
        "test": 80,          # テスト追加
        "doc": 90,           # ドキュメント
    }

    async def add_task(self, source, source_id, task_type, description,
                       target_files=None, priority=None, dedup_key=None) -> str:
        """
        Step 1: 優先度の決定
          priority = priority or PRIORITY_MAP.get(task_type, 50)

        Step 2: dedup_keyの生成 (未指定時)
          dedup_key = dedup_key or hashlib.sha256(
            f"{task_type}:{':'.join(sorted(target_files or []))}:{description[:100]}"
            .encode()
          ).hexdigest()

        Step 3: INSERT (UNIQUE制約によるDB自然重複排除)
          INSERT INTO pdl_task_queue (...) VALUES (...)
          ON CONFLICT (dedup_key) WHERE status = 'pending' DO NOTHING

        Step 4: NATS通知
          publish("pdl.task.created", {...})

        Step 5: タスクIDを返す
        """

    async def claim_next_task(self) -> dict | None:
        """
        Step 1: 優先度順に取得 (FOR UPDATE SKIP LOCKED で排他)
          SELECT * FROM pdl_task_queue
          WHERE status = 'pending'
          ORDER BY priority ASC, created_at ASC
          LIMIT 1
          FOR UPDATE SKIP LOCKED

        Step 2: status='claimed', claimed_by=session_id に更新

        Step 3: loop_breaker チェック
          if loop_breaker.is_frozen(task_id):
            skip and try next

        Step 4: NATS通知
          publish("pdl.task.claimed", {...})

        Step 5: タスクを返す (None if キュー空)
        """

    async def complete_task(self, task_id: str):
        """UPDATE pdl_task_queue SET status='completed', completed_at=NOW()"""

    async def fail_task(self, task_id: str):
        """UPDATE pdl_task_queue SET status='failed'"""

    async def requeue_task(self, task_id: str):
        """UPDATE SET status='pending', claimed_by=NULL, claimed_at=NULL"""

    async def get_queue_depth(self) -> int:
        """SELECT COUNT(*) FROM pdl_task_queue WHERE status='pending'"""

    async def get_queue_stats(self) -> dict:
        """
        SELECT status, COUNT(*) FROM pdl_task_queue GROUP BY status
        → {"pending": 5, "claimed": 1, "completed": 42, "failed": 3}
        """
```

#### 2.5.4 エラーハンドリング

| 例外 | 発生条件 | ハンドリング |
|------|---------|------------|
| `asyncpg.UniqueViolationError` | dedup_key重複 | 正常: 重複タスクは無視 (DO NOTHING) |
| `asyncpg.PostgresError` | DB接続失敗 | 3回リトライ後 None を返す |
| `ValueError` | 不正なtask_type | PRIORITY_MAP にない場合はデフォルト優先度50 |

#### 2.5.5 設定オプション

| 設定名 | デフォルト値 | 説明 |
|--------|------------|------|
| `DEFAULT_PRIORITY` | 50 | デフォルト優先度 |
| `MAX_QUEUE_DEPTH` | 100 | キュー最大深さ (超えたら古いものから削除) |
| `TASK_TTL_DAYS` | 30 | completed/failedタスクの保持期間 |

#### 2.5.6 依存関係

```python
import hashlib, uuid, logging
from tools.db_pool import get_connection
from tools.nats_client import publish
from pdl.loop_breaker import LoopBreaker
```

#### 2.5.7 DBテーブル

読み取り: `pdl_task_queue`, `failure_memory`
書き込み: `pdl_task_queue` (INSERT/UPDATE)

#### 2.5.8 推定コードサイズ

約200行

---

### 2.6 Session Ledger (`pdl/session_ledger.py`)

#### 2.6.1 目的

全セッション（AとB両方）の状態・変更・帰属を包括的に記録する台帳。どのファイルがどのセッションで変更されたか、いつ何が起きたかの完全な監査証跡を提供する。

#### 2.6.2 アルゴリズム

```python
class SessionLedger:
    async def create_session(self, session_id, task_id, status="CLAIMED"):
        """INSERT INTO pdl_sessions (id, task_id, status, started_at) VALUES (...)"""

    async def update_session(self, session_id, **kwargs):
        """
        動的にSET句を構築:
        UPDATE pdl_sessions SET status=$2, worktree_path=$3, ...
        WHERE id = $1
        + NATS通知 pdl.session.status_changed
        """

    async def record_change_attribution(self, session_id, session_type, filepath,
                                        change_type, diff_summary, commit_hash):
        """
        INSERT INTO pdl_change_log (session_id, session_type, filepath,
          change_type, diff_summary, commit_hash, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        """

    async def get_file_history(self, filepath, limit=10) -> list:
        """
        SELECT * FROM pdl_change_log
        WHERE filepath = $1
        ORDER BY created_at DESC LIMIT $2
        """

    async def get_session_stats(self, days=30) -> dict:
        """
        SELECT status, COUNT(*), AVG(cost_jpy), AVG(EXTRACT(EPOCH FROM completed_at - started_at))
        FROM pdl_sessions
        WHERE created_at > NOW() - INTERVAL '{days} days'
        GROUP BY status
        """
```

#### 2.6.3 エラーハンドリング

| 例外 | ハンドリング |
|------|------------|
| `asyncpg.PostgresError` | ログ記録のみ (ledger書き込み失敗でセッション停止はしない) |

#### 2.6.4 DBテーブル

読み取り: `pdl_sessions`, `pdl_change_log`, `pdl_task_queue`
書き込み: `pdl_sessions`, `pdl_change_log`

#### 2.6.5 推定コードサイズ

約180行

---

### 2.7 Merge Arbiter (`pdl/merge_arbiter.py`)

#### 2.7.1 目的

Session Bの変更をmainにマージするための仲裁者。コンフリクト検出、rebase、PR作成を管理する。自動マージは行わない（人間承認必須）。

#### 2.7.2 アルゴリズム

```python
class MergeArbiter:
    async def prepare_merge(self, session_id: str, wt_path: str) -> bool:
        """
        Step 1: mainの最新をfetch
          git -C {wt_path} fetch origin main

        Step 2: ドライランマージでコンフリクト検出
          git -C {wt_path} merge --no-commit --no-ff main
          → コンフリクト → git merge --abort → return False

        Step 3: コンフリクトなし → rebase
          git -C {wt_path} rebase main
          → 成功 → return True
          → 失敗 → git rebase --abort → return False
        """

    async def create_pr(self, session_id: str, task: dict, wt_path: str) -> str:
        """
        Step 1: prepare_merge() を実行
          → False → raise MergeConflictError

        Step 2: rebase後にテスト再実行
          test_result = await test_harness.run_all_gates(wt_path)
          → False → raise TestFailedError

        Step 3: push
          git -C {wt_path} push -u origin {branch}

        Step 4: PR作成
          gh pr create --title "[PDL] {task_description}"
                       --body "{PR_TEMPLATE}"
                       --base main --head {branch}

        Step 5: PR URLをpdl_merge_logに記録

        Step 6: return pr_url
        """

    def _build_pr_body(self, session_id, task, cost_jpy, test_results,
                       changed_files, commit_hash) -> str:
        """
        PR本文のマークダウンテンプレートを構築:
        - 変更概要
        - 対象ファイル一覧
        - テスト結果 (4ステージ全て)
        - 予算消費
        - ロールバック手順
        - Session B情報
        """
```

#### 2.7.3 PR本文テンプレート

```markdown
## [PDL] Auto-fix: {task_description}

### 変更概要
- 対象ファイル: {file_list}
- 変更種別: {bug_fix|enhancement|refactor}
- 元タスク: {source} #{source_id}

### テスト結果
| Stage | Result | Duration |
|-------|--------|----------|
| Static | PASS | 0.3s |
| Unit | PASS | 45.2s |
| Integration | PASS | 62.1s |
| Regression | PASS | 118.5s |

### 予算消費
- LLM費用: {cost_jpy:.1f}円
- モデル: {models_used}
- Session B残予算: {remaining_jpy:.1f}円

### ロールバック手順
```
git revert {commit_hash}
```

### 変更差分サマリー
{diff_summary}

---
*Generated by PDL Session B ({session_id}) at {timestamp}*
```

#### 2.7.4 エラーハンドリング

| 例外 | ハンドリング |
|------|------------|
| `MergeConflictError` | Discord通知、手動解決をリクエスト、セッション失敗 |
| `subprocess.CalledProcessError` (push失敗) | 3回リトライ後失敗 |
| `subprocess.CalledProcessError` (gh pr create失敗) | GitHub API制限の可能性、5分後リトライ |

#### 2.7.5 DBテーブル

読み取り: `pdl_sessions`, `pdl_file_locks`
書き込み: `pdl_sessions` (pr_url), `pdl_merge_log`

#### 2.7.6 推定コードサイズ

約250行

---

### 2.8 Test Harness (`pdl/test_harness.py`)

#### 2.8.1 目的

Session Bの変更がmainに入る前の品質ゲート。4段階のテストパイプラインで、構文エラーからリグレッションまでを検出する。1つでも失敗すればマージを阻止する。

#### 2.8.2 4段階テストパイプライン詳細

**Stage 1: Static Analysis (即座、~10秒)**
```python
async def _stage_static(self, wt: str) -> StageResult:
    errors = []

    # 1-a: Python構文チェック (py_compile)
    for py_file in glob.glob(f"{wt}/**/*.py", recursive=True):
        if any(skip in py_file for skip in ["venv", "node_modules", "__pycache__"]):
            continue
        try:
            py_compile.compile(py_file, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"Syntax error in {py_file}: {e}")

    # 1-b: Import cycle detection
    cycles = detect_import_cycles(wt)
    for cycle in cycles:
        errors.append(f"Circular import: {cycle}")

    # 1-c: FORBIDDEN_FILES violation check
    violations = gate_keeper.validate_worktree_changes(wt)
    for v in violations:
        errors.append(f"FORBIDDEN file modified: {v.file} (Level {v.decision.level})")

    # 1-d: Credential leak scan
    #   - .env値がソースコードにハードコードされていないか
    #   - APIキーパターン (sk-..., ghp_..., etc) のgrepスキャン
    leaks = scan_for_credentials(wt)
    for leak in leaks:
        errors.append(f"Possible credential leak: {leak}")

    # 1-e: 新規ファイルがPDL外に作成されていないか
    new_files = _get_new_files(wt)
    for f in new_files:
        if not f.startswith("pdl/"):
            # 新規ファイル作成はLevel 2でも注意
            pass  # 許可だがログ記録

    return StageResult(passed=len(errors) == 0, errors=errors, duration=elapsed)
```

**Stage 2: Unit Tests (~2分)**
```python
async def _stage_unit(self, wt: str) -> StageResult:
    errors = []
    env = os.environ.copy()
    env["PYTHONPATH"] = wt

    # 2-a: PDL自体のテスト
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"{wt}/pdl/tests/", "-v", "--tb=short",
         "--timeout=120"],
        capture_output=True, text=True, env=env, timeout=180, cwd=wt,
    )
    if result.returncode != 0:
        errors.append(f"PDL unit tests failed:\n{result.stdout[-500:]}\n{result.stderr[-500:]}")

    # 2-b: 既存テスト (存在すれば)
    if os.path.exists(f"{wt}/tests/"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", f"{wt}/tests/", "-v", "--tb=short",
             "--timeout=120"],
            capture_output=True, text=True, env=env, timeout=180, cwd=wt,
        )
        if result.returncode != 0:
            errors.append(f"Existing tests failed:\n{result.stdout[-500:]}\n{result.stderr[-500:]}")

    return StageResult(passed=len(errors) == 0, errors=errors, duration=elapsed)
```

**Stage 3: Integration Smoke (~3分)**
```python
async def _stage_integration(self, wt: str) -> StageResult:
    errors = []
    env = os.environ.copy()
    env["PYTHONPATH"] = wt

    # 3-a: 全モジュールimport可能確認
    for py_file in _find_project_modules(wt):
        module_name = _path_to_module(py_file, wt)
        result = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            capture_output=True, text=True, env=env, timeout=30, cwd=wt,
        )
        if result.returncode != 0:
            errors.append(f"Import failed: {module_name}: {result.stderr[:200]}")

    # 3-b: FastAPI起動テスト (import app のみ)
    result = subprocess.run(
        [sys.executable, "-c", "from app import app; print('FastAPI OK')"],
        capture_output=True, text=True, env=env, timeout=30, cwd=wt,
    )
    if result.returncode != 0:
        errors.append(f"FastAPI import failed: {result.stderr[:200]}")

    # 3-c: DB接続確認 (read-only)
    result = subprocess.run(
        [sys.executable, "-c",
         "import asyncio; from tools.db_pool import get_connection; "
         "asyncio.run(get_connection().__aenter__())"],
        capture_output=True, text=True, env=env, timeout=15, cwd=wt,
    )
    if result.returncode != 0:
        errors.append(f"DB connection failed: {result.stderr[:200]}")

    return StageResult(passed=len(errors) == 0, errors=errors, duration=elapsed)
```

**Stage 4: Regression Detection (~5分)**
```python
async def _stage_regression(self, wt: str) -> StageResult:
    errors = []

    # 4-a: .env変数照合
    env_vars = parse_env_file(f"{PROJECT_ROOT}/.env")
    code_refs = find_env_references(wt)
    for var in code_refs:
        if var not in env_vars and not var.startswith("PDL_"):
            errors.append(f"Code references undefined env var: {var}")

    # 4-b: DBスキーマ互換性チェック
    new_tables = extract_create_table_statements(wt)
    for table_name, columns in new_tables.items():
        existing = await get_table_schema(table_name)
        if existing and not is_compatible(existing, columns):
            errors.append(f"DB schema incompatible: {table_name}")

    # 4-c: feature_flags参照チェック
    flags = load_feature_flags(f"{wt}/feature_flags.yaml")
    code_flag_refs = find_feature_flag_references(wt)
    for ref in code_flag_refs:
        if ref not in flags:
            errors.append(f"Code references undefined feature flag: {ref}")

    # 4-d: 依存方向チェック (ALLOWED_IMPORT_DIRECTIONS)
    direction_violations = check_import_directions(wt)
    for v in direction_violations:
        errors.append(f"Import direction violation: {v}")

    return StageResult(passed=len(errors) == 0, errors=errors, duration=elapsed)
```

#### 2.8.3 データ構造

```python
@dataclass
class StageResult:
    passed: bool
    errors: list[str]
    duration: float  # 秒

@dataclass
class TestResult:
    passed: bool
    stage: str       # 失敗したステージ名 or "complete"
    details: list[StageResult]
    total_duration: float
```

#### 2.8.4 エラーハンドリング

| 例外 | ハンドリング |
|------|------------|
| `subprocess.TimeoutExpired` | そのステージを失敗扱い |
| `FileNotFoundError` | テストファイル不在はスキップ (テスト自体がない場合) |
| `asyncpg.PostgresError` | Stage 4のDB関連テストを失敗扱い |
| `yaml.YAMLError` | feature_flags.yaml パースエラーは失敗扱い |

#### 2.8.5 推定コードサイズ

約350行

---

### 2.9 Cleanup Daemon (`pdl/cleanup_daemon.py`)

#### 2.9.1 目的

古いworktreeとブランチを自動削除し、ディスク容量を管理する。cronで定期実行される。

#### 2.9.2 アルゴリズム

```python
async def cleanup_stale_worktrees() -> int:
    """
    Step 1: pdl_worktrees/ 内のディレクトリをスキャン
    Step 2: 各ディレクトリの最終更新日時を確認
    Step 3: 24時間超過 & DB上COMPLETED/ROLLED_BACK/FAILED → 削除
    Step 4: DB上にレコードなし (孤児) → 削除
    Step 5: ディスク空き2GB未満 → COMPLETED worktreeを緊急全削除
    Step 6: 削除したworktree数を返す
    """

async def cleanup_merged_branches() -> int:
    """
    Step 1: pdl/session-b-* パターンのローカルブランチ一覧取得
      git branch --list 'pdl/session-b-*'
    Step 2: 各ブランチについてマージ済みか確認
      git branch --merged main
    Step 3: マージ済みブランチを削除
      git branch -d {branch}
    Step 4: 削除数を返す
    """

async def cleanup_old_db_records() -> int:
    """
    Step 1: 30日超過の pdl_sessions (COMPLETED/ROLLED_BACK) を削除
    Step 2: 30日超過の pdl_task_queue (completed/failed) を削除
    Step 3: 30日超過の pdl_change_log を削除
    Step 4: 30日超過の pdl_budget_log を削除
    Step 5: 削除レコード数を返す
    """

async def main():
    """
    cron エントリーポイント
    1. cleanup_stale_worktrees()
    2. cleanup_merged_branches()
    3. cleanup_old_db_records()
    4. Discord通知 (削除があった場合のみ)
    """
```

#### 2.9.3 推定コードサイズ

約150行

---

### 2.10 Recovery Agent (`pdl/recovery_agent.py`)

#### 2.10.1 目的

システム再起動やクラッシュ後に中断されたSession Bを検出し、安全にクリーンアップする。孤児worktreeの解消、ファイルロックの解放、タスクの再キューイングを行う。

#### 2.10.2 アルゴリズム

```python
async def recover_interrupted_sessions() -> int:
    """
    Step 1: 未完了セッションを検出
      SELECT * FROM pdl_sessions
      WHERE status IN ('CLAIMED', 'WORKTREE_CREATED', 'EXECUTING', 'TESTING')
        AND started_at < NOW() - INTERVAL '1 hour'

    Step 2: 各孤児セッションについて:
      a. worktreeが残っていたら
        - git stash (未コミット変更を保存)
        - git worktree remove --force
      b. ブランチが残っていたら
        - git branch -D
      c. ファイルロック解放
        - DELETE FROM pdl_file_locks WHERE session_id = ?
      d. advisory lock解放
        - pg_advisory_unlock_all() (セッションのコネクション分)
      e. ステータス更新
        - UPDATE pdl_sessions SET status='ROLLED_BACK', error_detail='System restart recovery'
      f. タスク再キューイング
        - UPDATE pdl_task_queue SET status='pending' WHERE claimed_by=? AND status='claimed'

    Step 3: 復旧セッション数を返す
    Step 4: 各復旧についてNATS通知 + Discord通知
    """

async def check_stale_locks() -> int:
    """
    Step 1: pdl_file_locks で1時間以上経過したロックを検出
    Step 2: 対応するセッションが終了済みか確認
    Step 3: 終了済みセッションのロックを解放
    Step 4: 解放数を返す
    """

async def check_stale_service_locks() -> int:
    """
    Step 1: pdl_service_locks で60秒以上経過したロックを検出
    Step 2: advisory unlock + DELETE
    Step 3: 解放数を返す
    """
```

#### 2.10.3 推定コードサイズ

約180行

---

### 2.11 Node Awareness (`pdl/node_awareness.py`)

#### 2.11.1 目的

BRAVO/CHARLIE/DELTAノードの状態をリアルタイムで認識し、LLMルーティングの判断材料を提供する。特にCHARLIEのWin11モード（デュアルブート）検出が重要。

#### 2.11.2 アルゴリズム

```python
class NodeAwareness:
    NODES = {
        "bravo":   {"host": "100.x.x.x",   "ollama_model": "qwen3.5:9b"},
        "charlie": {"host": "100.x.x.x",  "ollama_model": "qwen3.5:9b"},
        "delta":   {"host": "100.x.x.x",   "ollama_model": "qwen3.5:4b"},
    }

    async def get_available_nodes(self) -> list[dict]:
        """
        Step 1: 各ノードにping (timeout 5秒)
        Step 2: self_healer の状態DB確認 (charlie_win11等)
        Step 3: 応答あり & 異常状態なし → available
        Step 4: 利用可能ノードリストを返す
        """

    async def get_best_llm_node(self) -> dict | None:
        """
        Step 1: get_available_nodes()
        Step 2: 9bモデル搭載ノード (BRAVO, CHARLIE) を優先
        Step 3: 両方ビジーなら4bモデル (DELTA, ALPHA)
        Step 4: 全ビジーならNone (API fallback)
        """
```

#### 2.11.3 推定コードサイズ

約120行

---

### 2.12 Loop Breaker (`pdl/loop_breaker.py`)

#### 2.12.1 目的

PDLが無限ループに陥ることを防止する。同じタスクの連続実行、PR→trigger→PR循環、同一エラーの繰り返し修正を検出して凍結する。

#### 2.12.2 アルゴリズム

```python
class LoopBreaker:
    MAX_CONSECUTIVE_FAILURES = 5    # 同一タスクの連続失敗上限
    MAX_SAME_FILE_PER_DAY = 3       # 同一ファイルの日次変更上限
    FREEZE_DURATION_HOURS = 24      # 凍結期間

    def is_frozen(self, task_id: str) -> bool:
        """
        Step 1: pdl_task_queue で同一dedup_keyの過去失敗を検索
        Step 2: 過去24時間以内にMAX_CONSECUTIVE_FAILURES回以上失敗
          → return True (凍結)
        Step 3: return False
        """

    def check_file_repetition(self, target_files: list[str]) -> bool:
        """
        Step 1: pdl_change_log で今日の同一ファイル変更回数を確認
        Step 2: MAX_SAME_FILE_PER_DAY以上 → return True (拒否)
        Step 3: return False
        """

    def check_pr_loop(self, session_id: str) -> bool:
        """
        Step 1: pdl_merge_log で直近の[PDL] PR作成履歴を確認
        Step 2: 過去1時間で3回以上 → return True (ループ検出)
        Step 3: return False
        """
```

#### 2.12.3 推定コードサイズ

約130行

---

### 2.13 Dedup Engine (`pdl/dedup_engine.py`)

#### 2.13.1 目的

failure_memoryテーブルから重複エラーパターンを排除し、同じエラーに対するタスクが複数作成されることを防ぐ。

#### 2.13.2 アルゴリズム

```python
async def dedup_failure_tasks() -> int:
    """
    Step 1: failure_memory から未解決エントリを取得
      SELECT error_pattern, COUNT(*), array_agg(id), MAX(created_at)
      FROM failure_memory
      WHERE status = 'unresolved'
      GROUP BY error_pattern
      HAVING COUNT(*) > 1

    Step 2: 各クラスターで最新以外を 'deduped' マーク
      UPDATE failure_memory SET status = 'deduped'
      WHERE id = ANY(older_ids)

    Step 3: 残った最新エントリからタスクを作成
      task_queue.add_task(
        source='failure_memory',
        source_id=latest_id,
        task_type='bug_fix',
        description=error_message,
        target_files=[source_file],
        dedup_key=hash(error_pattern),
      )

    Step 4: 重複排除数を返す
    """

async def scan_and_create_tasks() -> tuple[int, int]:
    """
    Step 1: dedup_failure_tasks() で重複排除
    Step 2: 未解決 & 未タスク化のfailure_memoryからタスクを作成
    Step 3: return (created_count, deduped_count)
    """
```

#### 2.13.3 推定コードサイズ

約150行

---

### 2.14 Config (`pdl/config.py`)

#### 2.14.1 目的

PDL全体の設定定数を一箇所に集約。保護ファイルリスト、予算設定、タイムアウト値、監視閾値を定義。

#### 2.14.2 内容

```python
import os
from pathlib import Path

# ─── パス ───
PROJECT_ROOT = Path(os.environ.get("PDL_PROJECT_ROOT", os.path.expanduser("~/syutain_beta")))
WORKTREE_BASE = PROJECT_ROOT / "pdl_worktrees"
LOCK_FILE = Path("/tmp/pdl_session_b.lock")

# ─── 予算 ───
DAILY_BUDGET_JPY = float(os.environ.get("PDL_DAILY_BUDGET_JPY", "80.0"))
SESSION_A_RATIO = 0.70
SESSION_B_RATIO = 0.30
SESSION_B_SINGLE_TASK_MAX_JPY = 8.0
SESSION_B_SINGLE_CALL_MAX_JPY = 3.0

# ─── タイムアウト ───
SESSION_B_HARD_TIMEOUT_SEC = 2700  # 45分
SESSION_A_CHECK_INTERVAL_SEC = 60
SESSION_A_RECENT_CHANGE_MINUTES = 5

# ─── 制限 ───
MAX_CONCURRENT_SESSION_B = 1
MAX_WORKTREES = 5
MAX_QUEUE_DEPTH = 100

# ─── 保護ファイル ───
FORBIDDEN_FILES = { ... }       # Level 0 (31エントリ)
REVIEW_REQUIRED_FILES = { ... } # Level 1 (11エントリ)

# ─── 監視閾値 ───
MONITORING_CHECKS = {
    "session_b_duration": (60, 2700, "warn_then_kill"),
    "session_b_budget":   (30, 0.9, "kill"),
    "worktree_disk":      (300, 1073741824, "cleanup"),
    "worktree_count":     (600, 5, "cleanup"),
    "db_pool_available":  (30, 2, "pause_session_b"),
    "merge_conflict":     (60, 0, "notify"),
    "test_failure_rate":  (3600, 0.5, "pause_session_b"),
}

# ─── Discord通知テンプレート ───
NOTIFICATION_TEMPLATES = { ... }

# ─── 優先度マップ ───
PRIORITY_MAP = {
    "bug_fix": 10,
    "security": 15,
    "enhancement": 50,
    "refactor": 70,
    "test": 80,
    "doc": 90,
}

# ─── 依存方向ルール ───
ALLOWED_IMPORT_DIRECTIONS = { ... }
FORBIDDEN_IMPORT_DIRECTIONS = { ... }
```

#### 2.14.3 推定コードサイズ

約120行

---

### 2.15 Schemas (`pdl/schemas.py`)

#### 2.15.1 目的

PDL専用のDBテーブルスキーマを定義し、初回起動時に自動作成する。既存テーブルには一切触れない。

#### 2.15.2 テーブル一覧

```sql
-- Table 1: pdl_sessions (セッション管理)
CREATE TABLE IF NOT EXISTS pdl_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    branch_name TEXT,
    worktree_path TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cost_jpy REAL DEFAULT 0,
    error_detail TEXT,
    modified_files TEXT[],
    test_results JSONB,
    pr_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdl_sessions_status ON pdl_sessions (status);
CREATE INDEX IF NOT EXISTS idx_pdl_sessions_created ON pdl_sessions (created_at);

-- Table 2: pdl_task_queue (タスクキュー)
CREATE TABLE IF NOT EXISTS pdl_task_queue (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    task_type TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    description TEXT NOT NULL,
    target_files TEXT[],
    status TEXT DEFAULT 'pending',
    claimed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    dedup_key TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pdl_task_dedup
    ON pdl_task_queue (dedup_key) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pdl_task_status ON pdl_task_queue (status, priority);

-- Table 3: pdl_file_locks (ファイルロック)
CREATE TABLE IF NOT EXISTS pdl_file_locks (
    filepath TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 4: pdl_service_locks (サービスロック)
CREATE TABLE IF NOT EXISTS pdl_service_locks (
    service_name TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table 5: pdl_merge_log (マージ履歴)
CREATE TABLE IF NOT EXISTS pdl_merge_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    merge_commit TEXT,
    conflict_files TEXT[],
    resolution TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdl_merge_session ON pdl_merge_log (session_id);

-- Table 6: pdl_change_log (変更帰属記録)
CREATE TABLE IF NOT EXISTS pdl_change_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    session_type TEXT NOT NULL,
    filepath TEXT NOT NULL,
    change_type TEXT NOT NULL,
    diff_summary TEXT,
    commit_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdl_change_filepath ON pdl_change_log (filepath);
CREATE INDEX IF NOT EXISTS idx_pdl_change_session ON pdl_change_log (session_id);

-- Table 7: pdl_budget_log (予算消費記録)
CREATE TABLE IF NOT EXISTS pdl_budget_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    amount_jpy REAL NOT NULL,
    model TEXT,
    remaining_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdl_budget_date ON pdl_budget_log (created_at);
CREATE INDEX IF NOT EXISTS idx_pdl_budget_task ON pdl_budget_log (task_id);
```

#### 2.15.3 推定コードサイズ

約130行

---

## 3. 完全セットアップ手順

### 3.0 前提条件

| 項目 | 要件 | 確認方法 |
|------|------|---------|
| macOS | ALPHA ノード (MBP) | `uname -s` → "Darwin" |
| Python | 3.12+ (venvで管理) | `~/syutain_beta/venv/bin/python --version` |
| PostgreSQL | 起動中、syutainβ DBアクセス可能 | `psql -c "SELECT 1"` |
| NATS | 起動中 | `nc -z localhost 4222` |
| Git | 2.20+ (worktree機能) | `git --version` |
| GitHub CLI | `gh` インストール済み & 認証済み | `gh auth status` |
| ディスク空き | 2GB以上 | `df -h ~/syutain_beta` |
| 既存プロジェクト | `~/syutain_beta/` に55K行コードベース | `ls ~/syutain_beta/app.py` |

### 3.1 Gitリポジトリ初期化

```bash
# syutain_beta がまだgitリポジトリでない場合
cd ~/syutain_beta

# Step 1: git初期化
git init

# Step 2: .gitignore設定
cat >> .gitignore << 'EOF'
pdl_worktrees/
venv/
__pycache__/
*.pyc
logs/
.env
credentials.json
token.json
*.log
EOF

# Step 3: 初回コミット
git add -A
git commit -m "Initial commit: SYUTAINβ codebase"

# Step 4: GitHubリポジトリ作成 & push (プライベート)
gh repo create syutain-beta --private --source=. --remote=origin --push

# 確認
git remote -v
git log --oneline -1
```

### 3.2 PDLディレクトリ作成

```bash
# Step 1: pdl/ ディレクトリ作成
mkdir -p ~/syutain_beta/pdl/tests

# Step 2: pdl_worktrees/ ディレクトリ作成
mkdir -p ~/syutain_beta/pdl_worktrees

# Step 3: __init__.py作成
cat > ~/syutain_beta/pdl/__init__.py << 'EOF'
"""Parallel Dev Layer (PDL) - SYUTAINβの並行AI開発オーバーレイ"""
__version__ = "0.1.0"

import logging
logger = logging.getLogger("pdl")
EOF

cat > ~/syutain_beta/pdl/tests/__init__.py << 'EOF'
EOF

# 確認
ls -la ~/syutain_beta/pdl/
```

### 3.3 環境変数追加 (.envに追記)

```bash
# .envにPDL設定を追記 (既存の内容は変更しない)
cat >> ~/syutain_beta/.env << 'EOF'

# === PDL (Parallel Dev Layer) Settings ===
PDL_ENABLED=true
PDL_DAILY_BUDGET_JPY=80.0
PDL_SESSION_B_RATIO=0.30
PDL_SESSION_B_TIMEOUT=2700
PDL_TASK_MAX_JPY=8.0
PDL_CALL_MAX_JPY=3.0
PDL_MAX_SESSIONS=1
PDL_CRON_HOURS=23,0,1,2,3,4,5,6
PDL_LOG_LEVEL=INFO
EOF

# 確認 (キー値は表示しない)
grep "^PDL_" ~/syutain_beta/.env | cut -d= -f1
```

### 3.4 データベースマイグレーション

```bash
# Step 1: PDLテーブル作成SQLを実行
psql -d syutain -f - << 'EOSQL'
-- PDL Sessions
CREATE TABLE IF NOT EXISTS pdl_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    branch_name TEXT,
    worktree_path TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cost_jpy REAL DEFAULT 0,
    error_detail TEXT,
    modified_files TEXT[],
    test_results JSONB,
    pr_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_sessions_status ON pdl_sessions (status);
CREATE INDEX IF NOT EXISTS idx_pdl_sessions_created ON pdl_sessions (created_at);

-- PDL Task Queue
CREATE TABLE IF NOT EXISTS pdl_task_queue (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    task_type TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    description TEXT NOT NULL,
    target_files TEXT[],
    status TEXT DEFAULT 'pending',
    claimed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    dedup_key TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pdl_task_dedup
    ON pdl_task_queue (dedup_key) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pdl_task_status ON pdl_task_queue (status, priority);

-- PDL File Locks
CREATE TABLE IF NOT EXISTS pdl_file_locks (
    filepath TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ DEFAULT NOW()
);

-- PDL Service Locks
CREATE TABLE IF NOT EXISTS pdl_service_locks (
    service_name TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ DEFAULT NOW()
);

-- PDL Merge Log
CREATE TABLE IF NOT EXISTS pdl_merge_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    merge_commit TEXT,
    conflict_files TEXT[],
    resolution TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_merge_session ON pdl_merge_log (session_id);

-- PDL Change Log
CREATE TABLE IF NOT EXISTS pdl_change_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    session_type TEXT NOT NULL,
    filepath TEXT NOT NULL,
    change_type TEXT NOT NULL,
    diff_summary TEXT,
    commit_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_change_filepath ON pdl_change_log (filepath);
CREATE INDEX IF NOT EXISTS idx_pdl_change_session ON pdl_change_log (session_id);

-- PDL Budget Log
CREATE TABLE IF NOT EXISTS pdl_budget_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    amount_jpy REAL NOT NULL,
    model TEXT,
    remaining_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_budget_date ON pdl_budget_log (created_at);
CREATE INDEX IF NOT EXISTS idx_pdl_budget_task ON pdl_budget_log (task_id);
EOSQL

# Step 2: テーブル作成確認
psql -d syutain -c "\dt pdl_*"
```

### 3.5 Crontab設定

```bash
# Step 1: 現在のcrontabをバックアップ
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d).txt

# Step 2: PDLエントリ追加
(crontab -l 2>/dev/null; cat << 'EOF'

# === PDL (Parallel Dev Layer) ===
# Session B: 毎時15分に起動試行 (夜間のみ: 23:00-07:00 JST)
15 23,0-6 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/pdl_orchestrator.py --mode=cron >> ~/syutain_beta/logs/pdl_cron.log 2>&1

# Worktreeクリーンアップ: 毎日04:00 JST
0 4 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/cleanup_daemon.py >> ~/syutain_beta/logs/pdl_cleanup.log 2>&1

# 中断復旧チェック: 毎時00分
0 * * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/recovery_agent.py >> ~/syutain_beta/logs/pdl_recovery.log 2>&1

# failure_memory重複排除: 毎時30分
30 * * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/dedup_engine.py >> ~/syutain_beta/logs/pdl_dedup.log 2>&1
EOF
) | crontab -

# Step 3: 確認
crontab -l | grep PDL
```

### 3.6 GitHub設定

```bash
# Step 1: GitHub CLI認証確認
gh auth status

# Step 2: リポジトリのデフォルトブランチ確認
gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
# → "main"

# Step 3: ブランチ保護ルール設定 (PR必須)
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --field required_pull_request_reviews='{"required_approving_review_count":0}' \
  --field enforce_admins=false

# 注: Session B PR用にreview必須を0に設定 (daichi自身がマージするため)
# 将来的にはbotアカウントのPRにはレビュー必須に変更可能
```

### 3.7 ログディレクトリ確認

```bash
# ログディレクトリが存在することを確認
mkdir -p ~/syutain_beta/logs

# PDLログファイル作成 (cron初回実行前に存在させる)
touch ~/syutain_beta/logs/pdl_cron.log
touch ~/syutain_beta/logs/pdl_cleanup.log
touch ~/syutain_beta/logs/pdl_recovery.log
touch ~/syutain_beta/logs/pdl_dedup.log
```

### 3.8 検証手順

```bash
# === Test 1: DB接続 ===
~/syutain_beta/venv/bin/python -c "
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect('postgresql://localhost/syutain')
    count = await conn.fetchval('SELECT COUNT(*) FROM pdl_sessions')
    print(f'pdl_sessions: {count} rows')
    await conn.close()
asyncio.run(test())
"
# 期待: "pdl_sessions: 0 rows"

# === Test 2: Git worktree機能 ===
cd ~/syutain_beta
git worktree add /tmp/pdl_test_worktree -b pdl/test-branch main
ls /tmp/pdl_test_worktree/app.py  # ファイルが存在すること
git worktree remove /tmp/pdl_test_worktree
git branch -D pdl/test-branch
echo "Worktree test: OK"

# === Test 3: GitHub CLI ===
gh auth status 2>&1 | head -3
echo "GitHub CLI test: OK"

# === Test 4: NATS接続 ===
~/syutain_beta/venv/bin/python -c "
import asyncio
from nats.aio.client import Client as NATS
async def test():
    nc = NATS()
    await nc.connect('nats://localhost:4222')
    print(f'NATS connected: {nc.is_connected}')
    await nc.close()
asyncio.run(test())
"
# 期待: "NATS connected: True"

# === Test 5: ディスク容量 ===
free_gb=$(df -g ~/syutain_beta | tail -1 | awk '{print $4}')
echo "Free disk: ${free_gb}GB (need >= 2GB)"

# === Test 6: PDLインポートテスト ===
cd ~/syutain_beta
PYTHONPATH=. ~/syutain_beta/venv/bin/python -c "
from pdl import __version__
print(f'PDL version: {__version__}')
"
# 期待: "PDL version: 0.1.0"
```

### 3.9 ロールバック手順 (セットアップ失敗時)

```bash
# === PDLを完全に撤去する手順 ===

# Step 1: cronエントリ削除
crontab -l | grep -v "PDL" | crontab -

# Step 2: PDLテーブル削除
psql -d syutain -c "
DROP TABLE IF EXISTS pdl_budget_log CASCADE;
DROP TABLE IF EXISTS pdl_change_log CASCADE;
DROP TABLE IF EXISTS pdl_merge_log CASCADE;
DROP TABLE IF EXISTS pdl_service_locks CASCADE;
DROP TABLE IF EXISTS pdl_file_locks CASCADE;
DROP TABLE IF EXISTS pdl_task_queue CASCADE;
DROP TABLE IF EXISTS pdl_sessions CASCADE;
"

# Step 3: worktree全削除
cd ~/syutain_beta
git worktree list | grep pdl_worktrees | awk '{print $1}' | xargs -I{} git worktree remove --force {}
git branch --list 'pdl/*' | xargs -I{} git branch -D {}

# Step 4: PDLディレクトリ削除
rm -rf ~/syutain_beta/pdl
rm -rf ~/syutain_beta/pdl_worktrees

# Step 5: .envからPDL設定削除
sed -i '' '/^PDL_/d' ~/syutain_beta/.env
sed -i '' '/^# === PDL/d' ~/syutain_beta/.env

# Step 6: ログ削除
rm -f ~/syutain_beta/logs/pdl_*.log

# Step 7: プロセスロック削除
rm -f /tmp/pdl_session_b.lock

# Step 8: 確認
psql -d syutain -c "\dt pdl_*"
# → "Did not find any relations."
echo "PDL completely removed."
```

---

## 4. 運用手順

### 4.1 日常運用 (自動で起こること)

```
時刻 (JST)   イベント                              コンポーネント
─────────────────────────────────────────────────────────────────
毎時00分      中断復旧チェック                      recovery_agent.py
毎時15分      Session B起動試行 (23:00-07:00のみ)   pdl_orchestrator.py
毎時30分      failure_memory重複排除                dedup_engine.py
04:00         worktreeクリーンアップ                cleanup_daemon.py
```

### 4.2 週次メンテナンスタスク

| タスク | 頻度 | 手順 | 推定時間 |
|--------|------|------|---------|
| PDLログレビュー | 週1回 | `tail -100 logs/pdl_cron.log` でエラー確認 | 5分 |
| セッション統計確認 | 週1回 | `psql -c "SELECT status, COUNT(*) FROM pdl_sessions WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY status"` | 2分 |
| 予算消費確認 | 週1回 | `psql -c "SELECT SUM(amount_jpy) FROM pdl_budget_log WHERE created_at > NOW() - INTERVAL '7 days'"` | 2分 |
| 未処理タスク確認 | 週1回 | `psql -c "SELECT * FROM pdl_task_queue WHERE status = 'pending' ORDER BY priority"` | 3分 |
| ディスク使用量確認 | 週1回 | `du -sh ~/syutain_beta/pdl_worktrees/` | 1分 |
| マージ済みブランチ確認 | 週1回 | `git branch --list 'pdl/*' | wc -l` | 1分 |

### 4.3 新しいタスク種別の追加

```python
# Step 1: pdl/config.py の PRIORITY_MAP に追加
PRIORITY_MAP = {
    "bug_fix": 10,
    "security": 15,
    "enhancement": 50,
    "new_task_type": 45,    # ← 追加
    "refactor": 70,
    "test": 80,
    "doc": 90,
}

# Step 2: タスク投入時に新種別を使用
psql -c "INSERT INTO pdl_task_queue (id, source, task_type, priority, description)
         VALUES (gen_random_uuid(), 'manual', 'new_task_type', 45, '...')"
```

### 4.4 新しい保護ファイルの追加

```python
# pdl/config.py を編集

# Level 0 (絶対禁止) に追加
FORBIDDEN_FILES = {
    ...
    "new_critical_file.py",    # ← 追加
}

# または Level 1 (レビュー必須) に追加
REVIEW_REQUIRED_FILES = {
    ...
    "new_important_file.py",   # ← 追加
}

# 注意: config.py自体がFORBIDDEN_FILES ("pdl/" プレフィックス) で保護されているため、
# この変更はSession Aでのみ実行可能
```

### 4.5 予算配分の変更

```bash
# .envを編集
# 例: Session B予算を40%に増やす
PDL_SESSION_B_RATIO=0.40
PDL_TASK_MAX_JPY=12.0    # タスク上限も増額
PDL_CALL_MAX_JPY=5.0     # 呼び出し上限も増額

# 注意: DAILY_BUDGET_JPYの合計を超えないこと
# Session A = 80 * (1-0.40) = 48円
# Session B = 80 * 0.40 = 32円
```

### 4.6 Session Bの手動起動

```bash
# 手動でSession Bを起動 (cron時間外でもOK)
cd ~/syutain_beta
venv/bin/python pdl/pdl_orchestrator.py --mode=manual

# ログをリアルタイム監視
tail -f logs/pdl_cron.log
```

### 4.7 並行処理の一時停止/再開

```bash
# === 一時停止 ===

# 方法1: cronを無効化
crontab -l | sed 's/^\(.*pdl_orchestrator.*\)/#\1/' | crontab -

# 方法2: 環境変数で無効化
# .envに追加:
PDL_ENABLED=false

# 方法3: 実行中Session Bをサスペンド
psql -c "UPDATE pdl_sessions SET status = 'SUSPENDED' WHERE status IN ('EXECUTING', 'TESTING')"

# === 再開 ===

# 方法1: cronを再有効化
crontab -l | sed 's/^#\(.*pdl_orchestrator.*\)/\1/' | crontab -

# 方法2: 環境変数
PDL_ENABLED=true

# 方法3: サスペンドセッションの再開
venv/bin/python pdl/pdl_orchestrator.py --mode=resume
```

### 4.8 失敗タスクの調査

```bash
# Step 1: 失敗セッション一覧
psql -c "
SELECT s.id, s.task_id, s.status, s.error_detail, s.cost_jpy,
       t.description, t.target_files
FROM pdl_sessions s
JOIN pdl_task_queue t ON s.task_id = t.id
WHERE s.status IN ('FAILED', 'ROLLED_BACK')
ORDER BY s.created_at DESC
LIMIT 10
"

# Step 2: 特定セッションの詳細
SESSION_ID="..."
psql -c "SELECT * FROM pdl_sessions WHERE id = '$SESSION_ID'"
psql -c "SELECT * FROM pdl_change_log WHERE session_id = '$SESSION_ID'"
psql -c "SELECT * FROM pdl_budget_log WHERE session_id = '$SESSION_ID'"

# Step 3: テスト結果の確認
psql -c "SELECT test_results FROM pdl_sessions WHERE id = '$SESSION_ID'" | python -m json.tool

# Step 4: ログ確認
grep "$SESSION_ID" logs/pdl_cron.log
```

### 4.9 マージコンフリクトの解決

```bash
# Step 1: コンフリクトを特定
psql -c "
SELECT * FROM pdl_merge_log
WHERE resolution = 'aborted'
ORDER BY created_at DESC LIMIT 5
"

# Step 2: 対応するタスクを確認
TASK_ID="..."
psql -c "SELECT * FROM pdl_task_queue WHERE id = '$TASK_ID'"

# Step 3: 選択肢
# Option A: タスクを再キューイング (mainを最新にしてから再試行)
psql -c "UPDATE pdl_task_queue SET status = 'pending', claimed_by = NULL WHERE id = '$TASK_ID'"

# Option B: タスクをスキップ
psql -c "UPDATE pdl_task_queue SET status = 'skipped' WHERE id = '$TASK_ID'"

# Option C: 手動でマージ (Session Aで対応)
# → daichi自身がSession Aで修正を行う
```

---

## 5. 包括的リスク分析

### 5.1 セッション競合リスク (8項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 1 | Session BがSession A編集中のファイルを変更 | Medium | High | `detect_session_a_activity()` + advisory lock | Session B起動前にSession A検出チェック。ファイルロック取得失敗でスキップ | ファイルロック自動解放 (セッション終了時) | `pdl_file_locks` テーブル監視、Discord通知 | Session Aの変更とSession Bの変更が同一ファイルでないか確認 |
| 2 | Session A緊急ホットフィックスとSession Bが衝突 | Low | Critical | Session Aプロセス検出 (pgrep) + git dirty check | `handle_priority_override()` でSession Bを即サスペンド | Session B stash → Session A完了後rebase → テスト再実行 | Discord即時通知 "[PDL] Session B suspended" | rebase後のテスト結果確認、コンフリクトの有無 |
| 3 | cron多重起動でSession Bが同時に2つ走る | Low | High | `flock` プロセスロック + DB状態チェック | `/tmp/pdl_session_b.lock` のflockがO_NONBLOCK | orphanedセッション検出 (recovery_agent) | プロセスロックファイルの存在監視 | `pdl_sessions` で同時刻のCLAIMED/EXECUTINGが複数ないか |
| 4 | Session BのLLM呼び出し中にSession Aが同一モデルを使用 | Medium | Low | 直接的な検出は不要 (異なるコンテキスト) | Session Bはローカルモデル優先。APIモデルはrate limitで自然に制御 | LLM API側のrate limit error → リトライ3回 → 失敗時セッション中止 | LLMエラーレート監視 | API使用ログの確認 |
| 5 | Session Bの作業中にmainブランチがforce pushされる | Very Low | Critical | worktree内のgit fetch失敗 | ブランチ保護ルール (force push禁止) をGitHubで設定 | Session B自動ロールバック。worktreeを新mainベースで再作成 | git fetch/rebaseの失敗検出 | mainブランチの履歴整合性確認 |
| 6 | Session Bのcommitメッセージが不正 | Low | Low | PR作成時に自動チェック | `[PDL]` プレフィックス強制 | コミット修正 (amend) | N/A (影響軽微) | PR本文との整合性 |
| 7 | Session Bが同一ファイルを複数回変更 (1日以内) | Medium | Medium | `loop_breaker.check_file_repetition()` | 同一ファイル日次変更上限 (3回) | 上限到達でタスク凍結 (24時間) | `pdl_change_log` の日次ファイル変更回数 | 凍結解除後の変更が有意義か確認 |
| 8 | Session Bがgit lock (index.lock) を残す | Low | Medium | `recovery_agent` がindex.lockファイル検出 | プロセス正常終了時にgit操作を確実に完了 | index.lock ファイルの手動削除 | worktree内のindex.lock存在チェック | git操作が正常に完了したか確認 |

### 5.2 コード品質リスク (8項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 9 | Session Bがバグを導入 | Medium | High | 4段階テストゲート (static→unit→integration→regression) | テスト全通過必須。PR人間レビュー必須 | `git revert` による即座ロールバック | テスト失敗率トラッキング。マージ後エラーレート | failure_memoryに新規エントリが増えていないか |
| 10 | テストで検出できない微妙なリグレッション | Low | Critical | Stage 4回帰テスト + マージ後のevent_log監視 | PR人間レビュー (自動マージしない) | `git revert` + failure_memoryに記録 | マージ後30分のエラーレート比較 | 影響を受けたモジュールの全機能テスト |
| 11 | Session Bがimport循環を作成 | Medium | Medium | `detect_import_cycles()` (Stage 1 Static) | `ALLOWED_IMPORT_DIRECTIONS` / `FORBIDDEN_IMPORT_DIRECTIONS` ルール | テスト失敗→自動ロールバック | 循環import検出イベント | 依存グラフの可視化確認 |
| 12 | Session Bが未定義の環境変数を参照するコードを追加 | Low | Medium | Stage 4: env変数照合チェック | worktreeが本番.envのシンボリックリンクを使用 | テスト失敗→自動ロールバック | 新規環境変数参照の検出 | .envと新コードの環境変数一致確認 |
| 13 | Session Bが既存APIの後方互換性を破壊 | Low | Critical | Stage 3: import check、Stage 4: regression | PR人間レビュー | `git revert` | APIレスポンス比較テスト | 影響を受けるクライアントの動作確認 |
| 14 | Session Bがパフォーマンスリグレッションを導入 | Medium | Medium | 直接的な検出は難しい | PR人間レビュー。コード変更のO(n)分析 | `git revert` | 既存のレスポンスタイム監視 | 変更前後のベンチマーク比較 |
| 15 | Session Bが重複コードを作成 | Medium | Low | コードレビュー時に確認 | SESSION_B_CONTEXT内のCODE_MAP.md参照 | リファクタリングタスクとして再投入 | N/A (影響軽微) | 重複コードの検出ツール実行 |
| 16 | Session Bが既存のfeature_flagを無視するコードを追加 | Low | Medium | Stage 4: feature_flags全パス確認 | SESSION_B_CONTEXTでfeature_flags.yamlを注入 | テスト失敗→自動ロールバック | feature_flag参照のない新コード検出 | 全フラグのon/off両方でテスト |

### 5.3 インフラリスク (8項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 17 | worktreeでディスクが埋まる | Low | High | `cleanup_daemon` (1時間間隔) + ディスク監視 | worktree最大5個制限。24時間超過で自動削除 | 緊急クリーン: COMPLETED worktreeを全削除 | ディスク空き2GB未満で警告 | 空き容量確認、不要ファイルの特定 |
| 18 | PostgreSQLコネクションプール枯渇 | Low | High | `get_pool_available_connections()` チェック | Session B起動前に空き3以上を要求。DB接続を長期保持しない | Session Bを一時停止してコネクション解放 | 30秒間隔でプール状態チェック | プール設定の最大接続数見直し |
| 19 | NATS接続断 | Low | Low | NATS publish失敗 | NATSは通知のみ使用。接続断でもPDLの制御フローは影響なし | NATS再接続はnats_client.pyの既存ロジック | NATS接続状態監視 | 通知漏れがないか確認 |
| 20 | システム再起動でSession Bが中断 | Medium | Medium | `recovery_agent.recover_interrupted_sessions()` | 起動時に自動実行 | worktreeクリーン→ファイルロック解放→タスク再キュー | orphanedセッション数の追跡 | 復旧後のDB状態整合性確認 |
| 21 | サービス再起動がSession AとBで衝突 | Low | High | `pdl_service_locks` + advisory lock | 再起動前にロック取得必須。失敗→スキップ | ロックは60秒TTLで自動解放 | サービス再起動ログ | サービス状態の確認 |
| 22 | CHARLIEがWin11モードでLLM不可 | Medium | Low | `node_awareness.py` + self_healer状態参照 | CHARLIEダウン時はBRAVO/DELTAにフォールバック | 自動フォールバック | 既存self_healer監視 | フォールバック先ノードの負荷確認 |
| 23 | GitHub API制限でPR作成不可 | Low | Low | `gh pr create` の exit code | rate limit到達前に5分待機→リトライ | PR作成を次回セッションに延期 | GitHub API残クォータ | PR作成が成功したか確認 |
| 24 | git操作中の電源断 | Very Low | High | `.git/index.lock` の残存、`git status` の異常出力 | UPS/バッテリー (MBP) | `git fsck` + `git prune` + index.lock削除 | git status定期チェック | リポジトリ整合性の完全チェック |

### 5.4 予算・コストリスク (5項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 25 | Session Bが予算を使い果たす | Medium | Low | `BudgetPartition.can_spend()` (毎呼び出し前) | 3段階制限 (日次B枠24円, タスク8円, 呼び出し3円) | 予算超過時は即セッション終了。Session A枠は侵食されない | 30秒間隔で残予算チェック。残20%でDiscord警告 | 翌日の予算リセット確認 |
| 26 | コスト見積もりが実際と乖離 | Low | Low | `pdl_budget_log` で見積もり vs 実際を比較 | ローカルモデル優先で実コスト最小化 | 実コストが見積もりの2倍超→次回から見積もり係数を調整 | 見積もり精度トラッキング | 見積もりアルゴリズムの調整 |
| 27 | Session Bが高額モデルを選択 | Low | Medium | `choose_best_model_v6()` のbudget_sensitiveフラグ | `quality="low"`, `budget_sensitive=True` デフォルト | 単一呼び出し上限3円で制限 | 使用モデルの集計 | ローカルモデル使用率の確認 |
| 28 | 予算カウンターの時刻ずれ (日次リセット) | Very Low | Low | UTC vs JST の日付境界 | CURRENT_DATE はPostgreSQLのタイムゾーン設定依存。Asia/Tokyoで統一 | 手動で予算カウンターリセット | N/A | DB timezone設定の確認 |
| 29 | 同一タスクへの無駄な再投資 | Medium | Medium | `loop_breaker.is_frozen()` | 同一dedup_keyの5回連続失敗で24時間凍結 | 凍結解除は手動。根本原因を修正してから | 凍結タスク数の監視 | 凍結理由の分析、根本原因修正 |

### 5.5 セキュリティリスク (4項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 30 | Session Bが.envやcredentialsを変更/漏洩 | Very Low | Critical | GateKeeper Level 0 + credential leakスキャン (Stage 1) | `.env`, `credentials.json`, `token.json` はFORBIDDEN_FILES | 変更検出時は即セッション終了→ロールバック。PRには秘密値が含まれない | credential leakスキャン結果 | 漏洩の有無確認。必要ならキーローテーション |
| 31 | Session BがPDL自体を改変 (自己改変) | Very Low | Critical | GateKeeper Level 0 (`pdl/` はFORBIDDEN) | `pdl/` ディレクトリ全体がLevel 0保護 | テストゲートStage 1で検出→即ロールバック | GateViolation イベント | PDLコードの整合性チェック |
| 32 | Session Bがルールファイルを改変 (CLAUDE.md等) | Very Low | Critical | GateKeeper Level 0 | `CLAUDE.md`, `IDENTITY.md`, `SOUL.md`, `AGENTS.md` はFORBIDDEN | 即セッション終了→ロールバック | GateViolation イベント | ルールファイルのハッシュ比較 |
| 33 | Session Bが外部サーバーにデータ送信するコードを追加 | Very Low | High | コードレビュー (人間) | SESSION_B_CONTEXTにネットワーク制限注意を含める | `git revert` | PR人間レビューで確認 | 新規ネットワーク呼び出しの監査 |

### 5.6 運用リスク (2項目)

| # | リスク | 確率 | 影響 | 検出 | 防止 | 復旧 | 監視アラート | 事後確認 |
|---|--------|------|------|------|------|------|------------|---------|
| 34 | 無限ループ (PR→trigger→PR...) | Low | Medium | `loop_breaker.check_pr_loop()` | [PDL]プレフィックスPRにはtrigger発火しない。1時間3回上限 | 同一タスクの連続実行を5回で凍結 | PDL起因のPR作成回数/時間を監視 | trigger設定の確認 |
| 35 | failure_memoryの重複タスクが大量生成 | Medium | Low | `dedup_engine.dedup_failure_tasks()` | `pdl_task_queue.dedup_key` UNIQUE制約 | 重複タスクは 'deduped' ステータス | 重複検出率の追跡 | dedup_keyの生成ロジック確認 |

---

## 6. メリット・デメリット分析

### 6.1 メリット (Advantages)

#### 開発速度

| メリット | 説明 | 定量的効果 |
|---------|------|-----------|
| 夜間自動修正 | daichi不在時 (23:00-07:00) にバグ修正が進行 | +8時間/日の開発帯域 |
| failure_memory自動解決 | 蓄積されたエラーが自動的にPR化 | 手動対応比で70%時間削減 |
| 並行タスク処理 | Session Aが新機能開発中にSession Bがバグ修正 | 2倍の並行処理 |
| PR即座レビュー可 | 朝起きたらPRが待っている | レビュー待ち時間ゼロ |
| リファクタリング自動化 | 低優先度のコード改善が夜間に進行 | 技術的負債の継続的削減 |

#### コード品質

| メリット | 説明 |
|---------|------|
| 4段階テストゲート | Session Bの変更は人間の変更より厳しいテストを通過 |
| 自動import循環検出 | 依存方向ルールの機械的な強制 |
| credential leakスキャン | APIキーのハードコード防止 |
| 変更帰属追跡 | 全変更のsession_id + session_type記録 |
| 強制PRフロー | Session Bの変更は必ずPRレビューを通過 |

#### 55K行コードベース固有のメリット

| メリット | 説明 |
|---------|------|
| モジュール依存の機械的強制 | 55K行の依存関係を人間が覚えるのは不可能。PDLが自動チェック |
| CODE_MAP.md自動認識 | Session Bはコンテキストを自動注入されるため、巨大コードベースでも適切な変更が可能 |
| 変更影響範囲の限定 | GateKeeperがcriticalファイルを保護し、影響範囲を制限 |
| 回帰テストの自動化 | 55K行全体のimportチェック、環境変数照合、DBスキーマ互換性 |

#### コスト効率

| メリット | 説明 |
|---------|------|
| ローカルモデル優先 | Session Bはqwen3.5:9b/4bを優先。API費用ほぼゼロ |
| 予算分離 | Session Bが暴走してもSession Aの予算は安全 |
| 3段階コスト制限 | 日次/タスク/呼び出し単位の上限で暴走防止 |
| 夜間リソース活用 | daichi不在時のマシンリソースを有効活用 |

#### 運用安全性

| メリット | 説明 |
|---------|------|
| Zero Mutation設計 | 既存コードに一切触れない。PDL削除で完全復元 |
| worktree隔離 | Session Bの変更はmainに影響しない |
| 自動ロールバック | テスト失敗で即座に変更破棄 |
| 中断復旧 | システム再起動後に自動クリーンアップ |
| 監査証跡 | pdl_sessions, pdl_change_log, pdl_budget_logで完全記録 |

### 6.2 デメリット (Disadvantages)

#### 複雑性の増加

| デメリット | 影響度 | 緩和策 |
|-----------|--------|--------|
| 3,160行の新規コード | 全体の約6%増加 (55K→58K) | pdl/ 独立ディレクトリで隔離。削除で元に戻る |
| 7つの新規DBテーブル | DBスキーマの複雑化 | pdl_ プレフィックスで名前空間分離 |
| 4つのcronジョブ追加 | crontab管理の複雑化 | 全てコメント付き。PDLセクションで明確に分離 |
| git worktreeの学習コスト | 新概念の理解が必要 | WorktreeManagerが全操作をカプセル化 |
| 15コンポーネントの相互依存 | デバッグの複雑化 | 明確な責務分離、ログによるトレーサビリティ |

#### 新しい障害モード

| デメリット | 影響度 | 緩和策 |
|-----------|--------|--------|
| worktree残骸の蓄積 | ディスク圧迫 | cleanup_daemonで自動削除 |
| advisory lockの残留 | ファイルアクセスブロック | recovery_agentで自動解放 |
| タスクキューの肥大化 | DB性能低下 | 30日超過レコード自動削除 |
| PDL自体のバグ | Session B全停止 | PDLはFail Closed設計。バグ→Session B停止のみ。既存システムに影響なし |
| cron実行漏れ | 夜間タスク未処理 | 翌日手動起動可能。cronログ監視 |

#### コストオーバーヘッド

| デメリット | 影響度 | 緩和策 |
|-----------|--------|--------|
| Session B予算 (日次24円、月720円) | 月間コスト増 | ローカルモデル優先で実質0-5円/日 |
| ディスク使用 (worktree 1つ約200MB) | 最大1GB | cleanup_daemonで24時間後に削除 |
| DB負荷 (7テーブル+インデックス) | 微増 | 30日超過レコード自動削除 |
| CPU使用 (テスト実行) | 夜間のみ | cron時間帯を23:00-07:00に限定 |

#### メンテナンス負担

| デメリット | 影響度 | 緩和策 |
|-----------|--------|--------|
| 週次ログレビュー | 5分/週 | 自動アラートで異常のみ通知 |
| FORBIDDEN_FILESの更新 | 新ファイル追加時 | Session Aでのみ変更可能 |
| テストの保守 | PDLのテスト自体のメンテ | PDLテストは単純なユニットテスト |
| 予算チューニング | 月1回程度 | .envで簡単に変更可能 |

#### AI生成コードのリスク

| デメリット | 影響度 | 緩和策 |
|-----------|--------|--------|
| AI幻覚によるバグ | Medium | 4段階テスト + 人間レビュー |
| コンテキスト断片化 | Session Bは55K行全体を理解できない | SESSION_B_CONTEXT + CODE_MAP.mdで重要部分を注入 |
| スタイルの不統一 | AI生成コードと手動コードの差異 | PRレビューで統一を確認 |
| 不必要な変更 | AIが「改善」と判断した不要な変更 | テストゲート + PRレビューで却下 |
| 依存関係の見落とし | 変更ファイル以外への波及 | Stage 3: 全モジュールimportテスト |

---

## 7. パフォーマンス・コスト予測

### 7.1 トークン使用量推定 (タスク種別ごと)

| タスク種別 | 入力トークン | 出力トークン | モデル | 推定コスト |
|-----------|------------|------------|--------|-----------|
| bug_fix (小規模) | 3,000-5,000 | 500-1,500 | qwen3.5:9b (ローカル) | 0円 |
| bug_fix (中規模) | 8,000-15,000 | 2,000-5,000 | qwen3.5:9b (ローカル) | 0円 |
| bug_fix (大規模) | 20,000-40,000 | 5,000-10,000 | DeepSeek API | 2-5円 |
| enhancement | 10,000-25,000 | 3,000-8,000 | qwen3.5:9b (ローカル) | 0円 |
| refactor | 5,000-15,000 | 2,000-5,000 | qwen3.5:9b (ローカル) | 0円 |
| test | 8,000-20,000 | 3,000-8,000 | qwen3.5:9b (ローカル) | 0円 |

**注**: SYUTAINβはBRAVO/CHARLIE/DELTAにOllama qwen3.5をデプロイ済み。Session Bはこれらを優先使用するため、LLM API費用は多くの場合0円。

### 7.2 月次コスト予測

```
                          Best Case    Typical     Worst Case
                          ─────────    ───────     ──────────
LLM API費用/月             0円         50円        720円
  (Session Bのみ)

ディスク使用量/月          200MB        500MB       1.5GB
  (worktree一時使用)

CPU使用時間/月             8時間        20時間      60時間
  (夜間テスト実行)

PostgreSQL追加負荷         1%           3%          5%
  (7テーブル、インデックス)

GitHub Actions費用         0円          0円         0円
  (使用しない)

GitHub Storage費用         0円          0円         0円
  (PRブランチのみ、マージ後削除)

────────────────────────────────────────────────────────
合計月間コスト              ~0円        ~50円       ~720円
```

### 7.3 期待される時間節約

```
                          Without PDL   With PDL    Savings
                          ───────────   ────────    ───────
failure_memory手動対応     3時間/週      0.5時間/週  2.5時間/週
リファクタリング           2時間/週      0.5時間/週  1.5時間/週
テスト追加                 1時間/週      0.3時間/週  0.7時間/週
PRレビュー (Session B)     0時間/週      0.5時間/週  -0.5時間/週
PDLメンテナンス            0時間/週      0.3時間/週  -0.3時間/週
────────────────────────────────────────────────────────
週間合計                                             3.9時間/週
月間合計                                            ~16時間/月
```

### 7.4 期待される品質改善

| メトリクス | 現状 (推定) | PDL導入後 (目標) |
|-----------|------------|----------------|
| failure_memory未解決数 | 蓄積 | 週次で50%削減 |
| import循環検出 | 手動レビュー | 自動 (100%検出) |
| credential leak | 手動確認 | 自動スキャン (100%検出) |
| テストカバレッジ | 不明 | Session Bがテスト追加タスク処理 |
| コード変更の追跡性 | git logのみ | session_id + session_type付き完全記録 |

### 7.5 損益分岐点分析

```
初期セットアップコスト:
  - 実装時間: ~19時間 (セクション10.1のPhase計画参照)
  - 月次運用コスト: ~50円 + 0.3時間/週

月次リターン:
  - 時間節約: ~16時間/月
  - daichi時給換算: 16時間 × ∞ (プライスレス...だが仮に2,000円/hとして) = 32,000円/月

損益分岐点:
  - 19時間 / (16時間/月 - 0.3×4時間/月) ≈ 1.3ヶ月

→ 約1.3ヶ月で初期投資を回収。以降は月間約15時間の純利益。
```

---

## 8. 監視ダッシュボード設計

### 8.1 追跡メトリクス

| カテゴリ | メトリクス | 計算方法 | 更新間隔 |
|---------|-----------|---------|---------|
| セッション | 実行中Session B数 | `SELECT COUNT(*) FROM pdl_sessions WHERE status = 'EXECUTING'` | 30秒 |
| セッション | 今日の完了数 | `SELECT COUNT(*) FROM pdl_sessions WHERE status = 'COMPLETED' AND created_at::date = CURRENT_DATE` | 60秒 |
| セッション | 今日の失敗数 | 同上 status IN ('FAILED', 'ROLLED_BACK') | 60秒 |
| セッション | 成功率 (7日平均) | completed / (completed + failed + rolled_back) | 300秒 |
| セッション | 平均実行時間 | `AVG(completed_at - started_at)` | 300秒 |
| 予算 | Session B本日残 | `24 - SUM(amount_jpy) WHERE date = today` | 30秒 |
| 予算 | 今日の消費 | `SUM(amount_jpy) WHERE date = today` | 60秒 |
| 予算 | 使用モデル分布 | `GROUP BY model` | 300秒 |
| タスク | キュー深さ | `COUNT(*) WHERE status = 'pending'` | 60秒 |
| タスク | 凍結タスク数 | loop_breaker凍結数 | 300秒 |
| タスク | 重複排除数 (今日) | `COUNT(*) WHERE status = 'deduped'` | 300秒 |
| インフラ | worktree数 | `ls pdl_worktrees/ | wc -l` | 300秒 |
| インフラ | ディスク空き | `shutil.disk_usage()` | 300秒 |
| インフラ | DBプール空き | pool available connections | 30秒 |
| インフラ | ファイルロック数 | `COUNT(*) FROM pdl_file_locks` | 60秒 |
| テスト | ステージ別失敗率 | 各ステージの失敗数/実行数 | 600秒 |
| テスト | 平均テスト時間 | 各ステージの平均duration | 600秒 |
| マージ | PR作成数 (7日) | `COUNT(*) FROM pdl_merge_log WHERE created_at > -7d` | 600秒 |
| マージ | コンフリクト率 | conflict / total merge attempts | 600秒 |

### 8.2 アラート閾値

| アラート | 条件 | レベル | アクション |
|---------|------|--------|-----------|
| Session B長時間実行 | duration > 40分 | WARNING | Discord通知 |
| Session B超過 | duration > 45分 | CRITICAL | 強制終了 + Discord通知 |
| 予算残少 | remaining < 20% (4.8円) | WARNING | Discord通知 |
| 予算枯渇 | remaining < 1円 | CRITICAL | Session B起動禁止 + Discord通知 |
| ディスク容量 | free < 2GB | WARNING | cleanup_daemon緊急実行 + Discord通知 |
| ディスク容量 | free < 500MB | CRITICAL | Session B起動禁止 + Discord通知 |
| テスト失敗率 | rate > 50% (直近10セッション) | WARNING | Session B一時停止 + Discord通知 |
| コンフリクト率 | rate > 30% (直近10セッション) | WARNING | Discord通知 |
| DBプール | available < 3 | WARNING | Session B起動延期 |
| DBプール | available < 1 | CRITICAL | Session B強制停止 |
| orphanedセッション | count > 0 | WARNING | recovery_agent実行 + Discord通知 |
| worktree数 | count >= 5 | WARNING | cleanup_daemon緊急実行 |
| ファイルロック残留 | lock_age > 2時間 | WARNING | ロック強制解放 |

### 8.3 Web UI (`/parallel-debug`) ページレイアウト

```
┌─────────────────────────────────────────────────────────────┐
│ PDL Dashboard (/parallel-debug)                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────┐  ┌──────────────────────────┐│
│  │ SESSION STATUS           │  │ BUDGET STATUS             ││
│  │                          │  │                           ││
│  │ Active: 0                │  │ Session B Today:          ││
│  │ Today Completed: 3       │  │ ██████████░░░░░░ 62%      ││
│  │ Today Failed: 1          │  │ Spent: 14.9 / 24.0 ¥     ││
│  │ 7d Success Rate: 75%     │  │                           ││
│  │ Avg Duration: 12min      │  │ Per-Task Cap: 8.0 ¥      ││
│  │                          │  │ Per-Call Cap: 3.0 ¥       ││
│  └──────────────────────────┘  └──────────────────────────┘│
│                                                              │
│  ┌──────────────────────────┐  ┌──────────────────────────┐│
│  │ TASK QUEUE               │  │ INFRASTRUCTURE            ││
│  │                          │  │                           ││
│  │ Pending: 5               │  │ Worktrees: 2/5            ││
│  │ Frozen: 1                │  │ Disk Free: 45.2 GB        ││
│  │ Deduped Today: 3         │  │ DB Pool: 8/10 avail       ││
│  │                          │  │ File Locks: 0             ││
│  │ Next: bug_fix (pri 10)   │  │ NATS: Connected           ││
│  │   "Fix timeout in        │  │                           ││
│  │    jina_client.py"       │  │ Nodes:                    ││
│  │                          │  │  BRAVO:  ● Online         ││
│  │                          │  │  CHARLIE: ● Online        ││
│  │                          │  │  DELTA:  ● Online         ││
│  └──────────────────────────┘  └──────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ RECENT SESSIONS                                          ││
│  │                                                          ││
│  │ ID        Task    Status     Duration  Cost   PR         ││
│  │ ─────────────────────────────────────────────────────── ││
│  │ a1b2c3  bug_fix  COMPLETED  8min      0.0¥  #42        ││
│  │ d4e5f6  enhance  COMPLETED  15min     1.5¥  #41        ││
│  │ g7h8i9  refactor ROLLED_BACK 3min     0.0¥  -          ││
│  │ j0k1l2  bug_fix  COMPLETED  11min     0.0¥  #40        ││
│  │ m3n4o5  test     FAILED     22min     2.1¥  -          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ TEST PIPELINE STATS (7 days)                             ││
│  │                                                          ││
│  │ Stage        Pass  Fail  Rate   Avg Duration             ││
│  │ ──────────────────────────────────────────               ││
│  │ Static       28    2     93%    0.8s                     ││
│  │ Unit         26    4     87%    45s                      ││
│  │ Integration  24    6     80%    62s                      ││
│  │ Regression   22    8     73%    118s                     ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ ACTIONS                                                  ││
│  │                                                          ││
│  │ [Manual Session B]  [Pause PDL]  [Resume PDL]           ││
│  │ [Cleanup Now]  [Recovery Scan]  [View Logs]              ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 8.4 FastAPIエンドポイント

```python
# app.py に追加するルート (既存ファイルは変更しない。pdl/web_routes.pyで定義)

@router.get("/parallel-debug")
async def parallel_debug_page():
    """PDLダッシュボードHTML"""
    return HTMLResponse(content=render_pdl_dashboard())

@router.get("/api/pdl/status")
async def pdl_status():
    """PDLステータスJSON API"""
    return {
        "sessions": await get_session_stats(),
        "budget": await get_budget_stats(),
        "queue": await get_queue_stats(),
        "infrastructure": await get_infra_stats(),
        "tests": await get_test_stats(),
    }

@router.post("/api/pdl/trigger")
async def trigger_session_b():
    """手動Session B起動"""
    # ... (pdl_orchestrator.pyを呼び出し)

@router.post("/api/pdl/pause")
async def pause_pdl():
    """PDL一時停止"""

@router.post("/api/pdl/resume")
async def resume_pdl():
    """PDL再開"""
```

### 8.5 Discord通知テンプレート

```
# ─── Session開始 ───
[PDL] Session B開始
Task: {task_id}
Type: {task_type}
Branch: {branch}
Priority: {priority}

# ─── Session完了 ───
[PDL] Session B完了 ✓
Task: {task_id}
PR: {pr_url}
Cost: {cost_jpy:.1f}円
Duration: {duration_min}分
Files: {modified_files}

# ─── Session失敗 ───
[PDL] Session B失敗 ✗
Task: {task_id}
Stage: {failed_stage}
Error: {error_detail[:200]}
Cost: {cost_jpy:.1f}円

# ─── 予算警告 ───
[PDL] 予算警告
Session B残: {remaining:.1f}円 / {limit:.1f}円
本日消費: {spent:.1f}円
使用モデル: {models_used}

# ─── Session Aホットフィックス割込 ───
[PDL] Session A優先割込
File: {file}
Session Bをサスペンド中...
再開条件: Session A完了後

# ─── マージコンフリクト ───
[PDL] マージコンフリクト
Branch: {branch}
Conflict Files: {files}
Action Required: 手動解決 or タスクスキップ

# ─── 復旧完了 ───
[PDL] 孤児セッション復旧
Recovered: {count}件
Actions: {actions}
```

---

## 9. 55K行コードベース管理

### 9.1 モジュール依存ルール (完全マトリクス)

```
                依存先 →
依存元 ↓       agents  tools  bots  brain_α  config  app  scheduler  pdl  web
─────────────────────────────────────────────────────────────────────────────
agents           -       ✓      ✗      ✗        ✓     ✗      ✗        ✗    ✗
tools            ✗       -      ✗      ✗        ✓     ✗      ✗        ✗    ✗
bots             ✗       ✓      -      ✗        ✓     ✗      ✗        ✗    ✗
brain_alpha      ✓       ✓      ✗      -        ✓     ✗      ✗        ✗    ✗
config           ✗       ✗      ✗      ✗        -     ✗      ✗        ✗    ✗
app              ✓       ✓      ✓      ✓        ✓     -      ✗        ✗    ✓
scheduler        ✓       ✓      ✗      ✓        ✓     ✗      -        ✗    ✗
pdl              ✗       ✓      ✗      ✗        ✓     ✗      ✗        -    ✗
web              ✗       ✓      ✗      ✗        ✓     ✗      ✗        ✗    -

✓ = 許可  ✗ = 禁止  - = 自身
```

**絶対禁止ルール**:
1. `tools/` は `agents/` を import しない (単方向依存)
2. `tools/` は `bots/` を import しない
3. `tools/` は `brain_alpha/` を import しない
4. `bots/` は `agents/` を import しない
5. `config/` は何もimportしない (最下層)
6. `pdl/` は `tools/` のみ import可能 (最小権限)
7. 循環import禁止 (全モジュール間)

### 9.2 Import ポリシー

```python
# pdl/test_harness.py で強制

ALLOWED_IMPORT_DIRECTIONS = {
    "brain_alpha": {"agents", "tools", "config"},
    "agents":      {"tools", "config"},
    "bots":        {"tools", "config"},
    "tools":       {"config"},
    "app":         {"agents", "tools", "bots", "brain_alpha", "config", "web"},
    "scheduler":   {"agents", "tools", "brain_alpha", "config"},
    "pdl":         {"tools", "config"},
    "web":         {"tools", "config"},
}

FORBIDDEN_IMPORT_DIRECTIONS = {
    ("tools", "agents"),
    ("tools", "bots"),
    ("tools", "brain_alpha"),
    ("tools", "pdl"),
    ("bots", "agents"),
    ("bots", "brain_alpha"),
    ("config", "tools"),
    ("config", "agents"),
    ("config", "bots"),
    ("config", "brain_alpha"),
    ("pdl", "agents"),
    ("pdl", "bots"),
    ("pdl", "brain_alpha"),
    ("pdl", "app"),
    ("pdl", "scheduler"),
}
```

### 9.3 CODE_MAP.md 自動生成アルゴリズム

```python
async def generate_code_map() -> str:
    """
    CODE_MAP.mdを自動生成するアルゴリズム

    Step 1: ディレクトリスキャン
      - ~/syutain_beta/ 以下の全.pyファイルをリスト
      - venv/, __pycache__/, node_modules/ を除外

    Step 2: モジュール分類
      - 各ファイルを所属ディレクトリ (agents/, tools/, etc.) で分類
      - ファイルサイズ (行数) を記録

    Step 3: 依存グラフ構築
      - 各ファイルのimport文を解析
      - from X import Y, import X パターンを検出
      - モジュール間の依存エッジを構築

    Step 4: 機能サマリー
      - 各ファイルの先頭docstringを抽出
      - docstringがない場合はクラス名/関数名一覧

    Step 5: マークダウン生成
      ## Module: {dir_name}/
      | File | Lines | Purpose | Dependencies |
      |------|-------|---------|--------------|
      | {file} | {lines} | {docstring} | {imports} |

    Step 6: 依存グラフ (ASCII)
      brain_alpha → agents → tools → config
      bots → tools → config
      app → all

    Step 7: ファイル書き出し
      CODE_MAP.md に書き出し
    """
```

### 9.4 変更影響分析アルゴリズム

```python
async def analyze_change_impact(changed_files: list[str]) -> dict:
    """
    変更されたファイルの影響範囲を分析

    Step 1: 直接依存の特定
      - changed_filesを import しているファイルを逆引き
      - 例: tools/jina_client.py を変更
        → agents/info_collector.py が import
        → bots/discord_bot.py が import

    Step 2: 間接依存の特定 (2段階まで)
      - 直接依存ファイルをさらに import しているファイル
      - 例: agents/info_collector.py
        → brain_alpha/content_pipeline.py
        → scheduler.py

    Step 3: 影響スコアリング
      - Level 0 (直接変更): changed_files → score=1.0
      - Level 1 (直接依存): importers → score=0.7
      - Level 2 (間接依存): importers of importers → score=0.3

    Step 4: リスクレベル判定
      - 影響ファイル数 > 10 → HIGH
      - 影響ファイル数 > 5  → MEDIUM
      - 影響ファイル数 <= 5 → LOW

    Return:
      {
        "changed": ["tools/jina_client.py"],
        "direct_impact": ["agents/info_collector.py", "bots/discord_bot.py"],
        "indirect_impact": ["brain_alpha/content_pipeline.py", "scheduler.py"],
        "risk_level": "MEDIUM",
        "total_affected_files": 5,
        "total_affected_lines": 2500,
      }
    """
```

### 9.5 テストカバレッジ要件 (モジュール別)

| モジュール | 最低カバレッジ | 理由 |
|-----------|-------------|------|
| `tools/emergency_kill.py` | テスト対象外 (FORBIDDEN) | 安全装置は手動テストのみ |
| `tools/loop_guard.py` | テスト対象外 (FORBIDDEN) | 安全装置は手動テストのみ |
| `tools/budget_guard.py` | テスト対象外 (FORBIDDEN) | 安全装置は手動テストのみ |
| `agents/os_kernel.py` | テスト対象外 (FORBIDDEN) | コアカーネルは手動テストのみ |
| `tools/llm_router.py` | import check のみ | REVIEW_REQUIREDだが基盤モジュール |
| `tools/db_pool.py` | import check + 接続テスト | REVIEW_REQUIREDだがDB基盤 |
| `agents/executor.py` | import check のみ | REVIEW_REQUIRED |
| `pdl/*.py` | pytest ユニットテスト必須 | PDL自体の品質保証 |
| その他 Level 2 ファイル | import check + 構文チェック | Session Bが変更可能な範囲 |

### 9.6 コードオーナーシップマッピング

```
Session A (daichi interactive) のみが変更可能:
  ├── agents/os_kernel.py
  ├── agents/approval_manager.py
  ├── tools/emergency_kill.py
  ├── tools/loop_guard.py
  ├── tools/budget_guard.py
  ├── tools/semantic_loop_detector.py
  ├── tools/cross_goal_detector.py
  ├── brain_alpha/safety_check.py
  ├── brain_alpha/self_healer.py
  ├── .env, credentials.json, token.json
  ├── config/*.yaml
  ├── Caddyfile, start.sh, worker_main.py
  ├── pdl/ (PDL自体)
  ├── CLAUDE.md, IDENTITY.md, SOUL.md, AGENTS.md
  └── feature_flags.yaml

Session A (daichi) がレビュー必須 (Session B PR可):
  ├── app.py
  ├── scheduler.py
  ├── tools/llm_router.py
  ├── tools/db_pool.py
  ├── tools/db_init.py
  ├── tools/nats_client.py
  ├── tools/node_manager.py
  ├── bots/discord_bot.py
  ├── agents/executor.py
  └── agents/verifier.py

Session B が自由に変更可能 (テスト通過条件):
  ├── tools/ (上記以外の ~60ファイル)
  ├── agents/ (上記以外の ~15ファイル)
  ├── bots/ (discord_bot.py以外の ~10ファイル)
  ├── brain_alpha/ (safety/self_healer以外の ~15ファイル)
  ├── web/ (全ファイル)
  ├── scripts/ (全ファイル)
  ├── prompts/ (全ファイル)
  ├── strategy/ (全ファイル)
  └── data/ (全ファイル)
```

---

## 10. 将来の進化パス

### 10.1 Phase 1-4 ロールアウト計画

#### Phase 1: 基盤構築 (Week 1-2)

**目標日**: 2026-04-14
**内容**: 最小限のPDLを構築し、手動でSession Bを起動できる状態にする

| 日 | タスク | 成果物 | 所要時間 |
|---|--------|--------|---------|
| Day 1 | Git初期化、GitHub設定 | .gitignore, リモートリポジトリ | 1時間 |
| Day 2 | `config.py`, `schemas.py` 実装 | 設定定数、DBスキーマ | 2時間 |
| Day 3 | `gate_keeper.py` 実装 | ファイル保護、advisory lock | 3時間 |
| Day 4 | `worktree_manager.py` 実装 | worktree作成/削除/ロールバック | 2時間 |
| Day 5 | DBマイグレーション実行、テスト | 7テーブル作成、基本テスト | 1時間 |
| Day 6 | `task_queue.py` 実装 | タスク追加/取得/完了 | 2時間 |
| Day 7 | `budget_partition.py` 実装 | 予算分離、LLMラッパー | 2時間 |
| Day 8 | `session_ledger.py` 実装 | セッション記録、変更帰属 | 2時間 |
| Day 9 | Phase 1テスト、ドキュメント | 全コンポーネント単体テスト通過 | 2時間 |

**Phase 1成功基準**:
- [x] `gate_keeper.check_file_access()` が全FORBIDDEN_FILESを正しく拒否
- [x] `worktree_manager.create_worktree()` が正常にworktreeを作成・削除
- [x] `budget_partition.can_spend()` が予算制限を正しく判定
- [x] `task_queue.add_task()` / `claim_next_task()` が正常動作
- [x] 7つのPDLテーブルが存在し、空

#### Phase 2: コア実装 (Week 3-4)

**目標日**: 2026-04-28
**内容**: Session Bの完全なライフサイクルを実現

| 日 | タスク | 成果物 | 所要時間 |
|---|--------|--------|---------|
| Day 10 | `test_harness.py` Stage 1-2 実装 | 静的解析 + ユニットテスト | 3時間 |
| Day 11 | `test_harness.py` Stage 3-4 実装 | 統合テスト + 回帰テスト | 3時間 |
| Day 12 | `pdl_orchestrator.py` 基本実装 | Session Bライフサイクル | 4時間 |
| Day 13 | `merge_arbiter.py` 実装 | コンフリクト検出、PR作成 | 3時間 |
| Day 14 | 手動Session B実行テスト | 1つのタスクをE2Eで処理 | 2時間 |

**Phase 2成功基準**:
- [x] 手動で `python pdl/pdl_orchestrator.py --mode=manual` を実行
- [x] タスクキューからタスクを取得→worktree作成→コード変更→テスト→PR作成
- [x] テスト失敗時に自動ロールバック
- [x] PR本文に全情報が含まれる

#### Phase 3: 自動化 (Week 5-6)

**目標日**: 2026-05-12
**内容**: cronによる自動起動、復旧機能、クリーンアップ

| 日 | タスク | 成果物 | 所要時間 |
|---|--------|--------|---------|
| Day 15 | `cleanup_daemon.py` 実装 | worktree自動削除 | 2時間 |
| Day 16 | `recovery_agent.py` 実装 | 中断セッション復旧 | 2時間 |
| Day 17 | `loop_breaker.py` 実装 | 無限ループ防止 | 1.5時間 |
| Day 18 | `dedup_engine.py` 実装 | failure_memory重複排除 | 1.5時間 |
| Day 19 | `node_awareness.py` 実装 | ノード状態認識 | 1時間 |
| Day 20 | cron設定、1週間観察 | 夜間自動実行開始 | 1時間 |

**Phase 3成功基準**:
- [x] cron夜間実行 (23:00-07:00) が正常動作
- [x] Session A検出でSession Bが正しくサスペンド
- [x] 中断復旧が起動時に自動実行
- [x] worktreeクリーンアップが24時間後に自動実行
- [x] failure_memory重複排除が動作

#### Phase 4: 監視・最適化 (Week 7-8)

**目標日**: 2026-05-26
**内容**: 監視ダッシュボード、Discord統合、パフォーマンス最適化

| 日 | タスク | 成果物 | 所要時間 |
|---|--------|--------|---------|
| Day 21 | `/parallel-debug` Web UI実装 | ダッシュボードHTML/CSS | 3時間 |
| Day 22 | API エンドポイント実装 | `/api/pdl/status`, `/api/pdl/trigger` | 2時間 |
| Day 23 | Discord通知統合テスト | 全通知テンプレート動作確認 | 1時間 |
| Day 24 | NATS統合テスト | 全サブジェクトの送受信確認 | 1時間 |
| Day 25 | パフォーマンス計測・最適化 | ボトルネック特定・改善 | 2時間 |
| Day 26 | ドキュメント最終化 | 運用手順書完成 | 1時間 |

**Phase 4成功基準**:
- [x] `/parallel-debug` でリアルタイム状態が確認可能
- [x] Discord通知が全イベントで正しく送信
- [x] 1セッションの平均実行時間が15分以下
- [x] 1週間の無人運転で重大問題なし

### 10.2 Phase別の機能追加

| Phase | 機能 | 説明 |
|-------|------|------|
| Phase 1 | 基本コンポーネント | config, schemas, gate_keeper, worktree_manager, task_queue, budget_partition, session_ledger |
| Phase 2 | コア機能 | test_harness, pdl_orchestrator, merge_arbiter |
| Phase 3 | 自動化 | cleanup_daemon, recovery_agent, loop_breaker, dedup_engine, node_awareness, cron |
| Phase 4 | 監視・UI | Web dashboard, Discord integration, NATS integration, performance tuning |
| Phase 5 (将来) | 複数スロット | MAX_CONCURRENT_SESSION_B=3, 複数worktree並行 |
| Phase 6 (将来) | 自動マージ | テスト通過 & 簡単な変更は自動マージ (人間レビュー省略) |
| Phase 7 (将来) | 学習機能 | 過去のSession B成功/失敗パターンからタスク優先度を自動調整 |

### 10.3 各Phase進行の判断基準

| 判断基準 | Phase 1→2 | Phase 2→3 | Phase 3→4 |
|---------|-----------|-----------|-----------|
| テスト通過率 | 基本テスト100% | E2E 1回成功 | 7日連続運転問題なし |
| 重大バグ | 0件 | 0件 | 0件 |
| ロールバック発生 | N/A | 失敗時に正常ロールバック確認 | 自動復旧が動作 |
| データ損失 | 0件 | 0件 | 0件 |

### 10.4 スケーリング戦略 (Session C, D)

```
Current (Phase 1-4): 1 Session B Slot
─────────────────────────────────────
  cron → Session B (1 worktree)
         ├── 夜間のみ (23:00-07:00)
         └── 最大1つ同時実行

Future (Phase 5): 3 Session B Slots
─────────────────────────────────────
  cron → Session B-1 (worktree 1) → bug_fix tasks
         Session B-2 (worktree 2) → enhancement tasks
         Session B-3 (worktree 3) → refactor/test tasks

  条件:
  - ファイルレベルのadvisory lockで衝突回避
  - 各スロットが異なるタスク種別を処理
  - 予算は3スロット共有 (合計30%上限は変更なし)
  - 各スロットのタスク上限を8円→4円に引き下げ

Future (Phase 6+): Session C (Reviewer)
─────────────────────────────────────
  Session C: AI Reviewer
  - Session Bの PR を自動レビュー
  - テスト結果 + コード品質 + アーキテクチャ適合性を評価
  - approve / request changes を自動判定
  - 人間レビューの負荷を軽減

Future (Phase 7+): Session D (Planner)
─────────────────────────────────────
  Session D: AI Planner
  - failure_memory, event_log, performance metrics を分析
  - 次に取り組むべきタスクを自動生成
  - タスクの優先度を動的に調整
  - 中長期の改善ロードマップを提案
```

**Session C/D追加のトリガー**:
- Session Bの週間PR数が10以上に安定
- 人間レビューがボトルネック化
- failure_memory の自動解決率が50%超

### 10.5 長期ビジョン

```
2026 Q2: PDL基盤構築 (Phase 1-4)
  - Session B 夜間自動バグ修正
  - 手動タスク投入 → 自動処理
  - 基本的な監視・通知

2026 Q3: PDL最適化 (Phase 5)
  - 3スロット並行処理
  - Session B成功率 > 80%
  - 月間50+ PR自動生成

2026 Q4: PDL拡張 (Phase 6-7)
  - AI Reviewer (Session C)
  - AI Planner (Session D)
  - 自動マージ (低リスク変更)

2027 Q1: PDL自律化
  - 人間の介入は週1回のレビューのみ
  - 24時間365日の継続的改善
  - コードベースの自己進化
```

---

## 付録A: 完全cron設定

```bash
# === PDL (Parallel Dev Layer) ===

# Session B: 毎時15分に起動試行 (夜間のみ: 23:00-07:00 JST)
15 23,0-6 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/pdl_orchestrator.py --mode=cron >> ~/syutain_beta/logs/pdl_cron.log 2>&1

# Worktreeクリーンアップ: 毎日04:00 JST
0 4 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/cleanup_daemon.py >> ~/syutain_beta/logs/pdl_cleanup.log 2>&1

# 中断復旧チェック: 毎時00分
0 * * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/recovery_agent.py >> ~/syutain_beta/logs/pdl_recovery.log 2>&1

# failure_memory重複排除: 毎時30分
30 * * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/dedup_engine.py >> ~/syutain_beta/logs/pdl_dedup.log 2>&1
```

## 付録B: 完全DBスキーマSQL

```sql
-- ============================================
-- PDL Database Schema
-- Execute on syutain database
-- All tables use pdl_ prefix
-- Existing tables are NOT modified
-- ============================================

-- Session management
CREATE TABLE IF NOT EXISTS pdl_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED','CLAIMED','WORKTREE_CREATED','EXECUTING',
                          'TESTING','PR_CREATED','COMPLETED','FAILED',
                          'ROLLED_BACK','SUSPENDED')),
    branch_name TEXT,
    worktree_path TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cost_jpy REAL DEFAULT 0,
    error_detail TEXT,
    modified_files TEXT[],
    test_results JSONB,
    pr_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_sessions_status ON pdl_sessions (status);
CREATE INDEX IF NOT EXISTS idx_pdl_sessions_created ON pdl_sessions (created_at);

-- Task queue
CREATE TABLE IF NOT EXISTS pdl_task_queue (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL
        CHECK (source IN ('failure_memory','manual','scheduler','auto_fix')),
    source_id TEXT,
    task_type TEXT NOT NULL
        CHECK (task_type IN ('bug_fix','security','enhancement','refactor','test','doc')),
    priority INTEGER DEFAULT 50,
    description TEXT NOT NULL,
    target_files TEXT[],
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending','claimed','completed','failed','skipped','deduped','frozen')),
    claimed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    dedup_key TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pdl_task_dedup
    ON pdl_task_queue (dedup_key) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pdl_task_status ON pdl_task_queue (status, priority);

-- File locks
CREATE TABLE IF NOT EXISTS pdl_file_locks (
    filepath TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ DEFAULT NOW()
);

-- Service restart locks
CREATE TABLE IF NOT EXISTS pdl_service_locks (
    service_name TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ DEFAULT NOW()
);

-- Merge log
CREATE TABLE IF NOT EXISTS pdl_merge_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    merge_commit TEXT,
    conflict_files TEXT[],
    resolution TEXT CHECK (resolution IN ('auto','manual','aborted')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_merge_session ON pdl_merge_log (session_id);

-- Change attribution log
CREATE TABLE IF NOT EXISTS pdl_change_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    session_type TEXT NOT NULL CHECK (session_type IN ('session_a','session_b')),
    filepath TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('create','modify','delete')),
    diff_summary TEXT,
    commit_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_change_filepath ON pdl_change_log (filepath);
CREATE INDEX IF NOT EXISTS idx_pdl_change_session ON pdl_change_log (session_id);
CREATE INDEX IF NOT EXISTS idx_pdl_change_created ON pdl_change_log (created_at);

-- Budget spending log
CREATE TABLE IF NOT EXISTS pdl_budget_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    amount_jpy REAL NOT NULL CHECK (amount_jpy >= 0),
    model TEXT,
    remaining_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pdl_budget_date ON pdl_budget_log (created_at);
CREATE INDEX IF NOT EXISTS idx_pdl_budget_task ON pdl_budget_log (task_id);
```

## 付録C: 実装優先度 (時間見積もり)

| Phase | 実装内容 | 所要時間 | 累積時間 |
|-------|---------|---------|---------|
| Phase 1 | `config.py`, `schemas.py`, `gate_keeper.py`, `worktree_manager.py`, `task_queue.py`, `budget_partition.py`, `session_ledger.py` | 9時間 | 9時間 |
| Phase 2 | `test_harness.py`, `pdl_orchestrator.py`, `merge_arbiter.py` | 6時間 | 15時間 |
| Phase 3 | `cleanup_daemon.py`, `recovery_agent.py`, `loop_breaker.py`, `dedup_engine.py`, `node_awareness.py` | 5時間 | 20時間 |
| Phase 4 | Web UI, Discord/NATS統合, cron設定, ドキュメント | 5時間 | 25時間 |
| **合計** | **15コンポーネント + インフラ** | **25時間** | |

## 付録D: 用語集

| 用語 | 定義 |
|------|------|
| PDL | Parallel Dev Layer。並行AI開発オーバーレイ層 |
| Session A | 人間 (daichi) がClaude Code CLIで対話的に作業するセッション |
| Session B | PDLが自動的に起動する自律セッション。worktreeで隔離 |
| Gate Keeper | ファイルアクセス制御の門番コンポーネント |
| worktree | git worktree。mainブランチから分岐した独立作業ディレクトリ |
| advisory lock | PostgreSQLのpg_advisory_lock。アプリケーションレベルのロック |
| dedup_key | タスク重複排除キー。UNIQUE制約でDB自然重複排除 |
| Fail Closed | 判断に迷ったら安全側に倒す設計原則 |
| Zero Mutation | 既存コードを一切変更しない設計原則 |
| FORBIDDEN_FILES | Session Bが絶対に変更できないファイル (Level 0) |
| REVIEW_REQUIRED_FILES | Session Bが変更可能だがPRで明示が必要なファイル (Level 1) |

## 付録E: トラブルシューティング

| 症状 | 原因 | 解決策 |
|------|------|--------|
| Session Bが起動しない | Session Aがアクティブ | Session Aを終了してから再試行 |
| Session Bが起動しない | 予算不足 | 翌日の予算リセットを待つ。または.envで上限変更 |
| Session Bが起動しない | キュー空 | `psql -c "SELECT * FROM pdl_task_queue WHERE status='pending'"` で確認 |
| Session Bが起動しない | プロセスロック残留 | `rm /tmp/pdl_session_b.lock` |
| Session Bが起動しない | DBプール枯渇 | 他の接続を確認。`SELECT * FROM pg_stat_activity` |
| worktreeが残る | cleanup_daemonが未実行 | `python pdl/cleanup_daemon.py` を手動実行 |
| ファイルロックが残る | セッション異常終了 | `python pdl/recovery_agent.py` を手動実行 |
| テストが常に失敗 | 環境変数不足 | `.env` シンボリックリンク確認 |
| PR作成失敗 | GitHub認証切れ | `gh auth refresh` |
| マージコンフリクト頻発 | mainとの乖離が大きい | Session B頻度を上げる (worktree最新化) |
| 予算が急速に消費 | API高額モデル選択 | `pdl_budget_log` でモデル確認。`quality="low"` 強制 |
| 同じタスクが何度も失敗 | 根本原因未解決 | `loop_breaker` が5回で凍結。手動で根本原因修正 |
| Discord通知が来ない | NATS/Discord接続断 | `nc -z localhost 4222` でNATS確認。Webhook URL確認 |

---

*Generated: 2026-04-01 | Version: 2.0 | Lines: ~2500*
*This document supersedes PARALLEL_AI_DEV_LAYER_DESIGN.md (V1)*
