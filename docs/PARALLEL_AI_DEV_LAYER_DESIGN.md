# SYUTAINβ 並行AI開発レイヤー 完全設計書

> Version: 1.0 | Date: 2026-04-01
> Status: DESIGN REVIEW
> Scope: 既存48K行コードベースの上に載るオーバーレイ層。既存コードの改変ゼロ。

---

## 目次

1. [アーキテクチャ概要](#1-アーキテクチャ概要)
2. [セッション定義とライフサイクル](#2-セッション定義とライフサイクル)
3. [ファイル保護ルール](#3-ファイル保護ルール)
4. [並行制御](#4-並行制御)
5. [予算パーティショニング](#5-予算パーティショニング)
6. [テスト戦略](#6-テスト戦略)
7. [ロールバック手順](#7-ロールバック手順)
8. [監視とアラート](#8-監視とアラート)
9. [55K行コードベースの組織化ルール](#9-55k行コードベースの組織化ルール)
10. [セッション間コンテキスト共有](#10-セッション間コンテキスト共有)
11. [障害復旧](#11-障害復旧)
12. [全25リスクへの対応マトリクス](#12-全25リスクへの対応マトリクス)

---

## 1. アーキテクチャ概要

### 1.1 レイヤー構成図

```
┌─────────────────────────────────────────────────────────────┐
│                     Human Operator (daichi)                   │
│                    Session A: Interactive                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────┐   ┌─────────────────────────────────────┐  │
│  │  Session A   │   │        Parallel Dev Layer            │  │
│  │  (Claude Code │   │  ┌───────────────────────────────┐  │  │
│  │   Interactive)│   │  │   Session B Orchestrator      │  │  │
│  │              │   │  │   (pdl_orchestrator.py)        │  │  │
│  │  Works on:   │   │  │                               │  │  │
│  │  main branch │   │  │  ┌─────┐ ┌─────┐ ┌─────┐    │  │  │
│  │  ~/syutain_  │   │  │  │Slot1│ │Slot2│ │Slot3│    │  │  │
│  │  beta/       │   │  │  │(wt) │ │(wt) │ │(wt) │    │  │  │
│  │              │   │  │  └──┬──┘ └──┬──┘ └──┬──┘    │  │  │
│  └──────┬───────┘   │  │     │       │       │        │  │  │
│         │           │  │  ┌──┴───────┴───────┴──┐     │  │  │
│         │           │  │  │   Gate Keeper        │     │  │  │
│         │           │  │  │   (file locks,       │     │  │  │
│         │           │  │  │    budget, tests)     │     │  │  │
│         │           │  │  └──────────┬───────────┘     │  │  │
│         │           │  └─────────────┼─────────────────┘  │  │
│         │           └────────────────┼────────────────────┘  │
│         │                            │                        │
│  ┌──────┴────────────────────────────┴──────────────────────┐│
│  │              Shared Infrastructure                        ││
│  │  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────────┐  ││
│  │  │PostgreSQL│ │  NATS    │ │ Git    │ │ Lock Store   │  ││
│  │  │(shared)  │ │(shared)  │ │(main)  │ │ (PDL schema) │  ││
│  │  └──────────┘ └──────────┘ └────────┘ └──────────────┘  ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 1.2 コアコンポーネント

| コンポーネント | ファイル | 責務 |
|---|---|---|
| PDL Orchestrator | `pdl/pdl_orchestrator.py` | セッションBのライフサイクル管理、タスクキュー消費 |
| Gate Keeper | `pdl/gate_keeper.py` | ファイルロック、保護ファイルチェック、テスト合格ゲート |
| Budget Partition | `pdl/budget_partition.py` | 予算の分離管理（A:70% / B:30%） |
| Worktree Manager | `pdl/worktree_manager.py` | git worktreeの作成・クリーン・マージ |
| Task Queue | `pdl/task_queue.py` | PostgreSQLベースの優先度付きタスクキュー |
| Session Ledger | `pdl/session_ledger.py` | 全セッションの状態・変更・帰属を記録 |
| Merge Arbiter | `pdl/merge_arbiter.py` | コンフリクト検出と解決戦略 |
| Test Harness | `pdl/test_harness.py` | worktree内でのテスト実行とゲート判定 |
| Cleanup Daemon | `pdl/cleanup_daemon.py` | 古いworktree/ブランチの自動削除 |
| Recovery Agent | `pdl/recovery_agent.py` | 中断セッションの検出と復旧 |

### 1.3 ディレクトリ構造

```
~/syutain_beta/
├── pdl/                          # Parallel Dev Layer (新規、既存コードに触れない)
│   ├── __init__.py
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
│   └── schemas.py                # DB スキーマ定義
├── pdl_worktrees/                # worktree配置ディレクトリ (gitignore)
│   ├── session-b-abc123/
│   └── session-b-def456/
└── (既存ファイルは一切変更しない)
```

### 1.4 設計原則

1. **Zero Mutation**: 既存コードへの変更ゼロ。PDLは独立ディレクトリ `pdl/` に完結する
2. **Fail Closed**: 判断に迷ったら安全側（変更を拒否）
3. **Session A Priority**: Session Aは常に最優先。Session Bは譲る
4. **Atomic Changes**: Session Bの変更はPRとして提出され、全テスト通過まで本番に入らない
5. **Budget Isolation**: Session BがSession Aの予算を食い潰すことは構造的に不可能

---

## 2. セッション定義とライフサイクル

### 2.1 セッション種別

| 属性 | Session A (Interactive) | Session B (Autonomous) |
|---|---|---|
| トリガー | 人間がClaude Code CLI起動 | cron / タスクキュー / failure_memory |
| ブランチ | main (直接) | `pdl/session-b-{task_id}-{timestamp}` |
| 作業場所 | `~/syutain_beta/` | `~/syutain_beta/pdl_worktrees/{branch}/` |
| 予算上限 | 日次予算の70% (56円) | 日次予算の30% (24円) |
| ファイルアクセス | 無制限 | Gate Keeper経由のみ |
| デプロイ | 即座に反映 | PR→テスト通過→人間承認→マージ |
| 最大実行時間 | 制限なし | 45分 (ハードリミット) |
| 同時実行数 | 1 | 最大1 (将来3に拡張可能) |

### 2.2 Session B ライフサイクル

```
[QUEUED] → [CLAIMED] → [WORKTREE_CREATED] → [EXECUTING] → [TESTING] → [PR_CREATED] → [COMPLETED]
                                                  │              │
                                                  ↓              ↓
                                            [FAILED]      [TEST_FAILED]
                                                  │              │
                                                  ↓              ↓
                                            [ROLLED_BACK]  [ROLLED_BACK]
```

各状態遷移はPostgreSQLの `pdl_sessions` テーブルにアトミックに記録される。

### 2.3 Session B 起動条件

Session Bは以下の **全て** を満たす場合のみ起動する:

```python
def can_start_session_b() -> tuple[bool, str]:
    """Session B起動可否を判定"""
    # 1. 既存Session Bが実行中でない
    if active_session_b_exists():
        return False, "既にSession Bが実行中"

    # 2. Session Aがアクティブでない（ファイル競合回避）
    if session_a_is_active():
        return False, "Session Aがアクティブ"

    # 3. 日次予算のSession B枠に残高がある
    if get_session_b_remaining_budget() < 5.0:  # 最低5円
        return False, "Session B予算不足"

    # 4. タスクキューにタスクがある
    if not pending_tasks_exist():
        return False, "保留タスクなし"

    # 5. ディスク空き容量が1GB以上
    if get_disk_free_gb() < 1.0:
        return False, "ディスク空き不足"

    # 6. PostgreSQLコネクションプールに空きがある
    if get_pool_available_connections() < 3:
        return False, "DBコネクション不足"

    return True, "OK"
```

---

## 3. ファイル保護ルール

### 3.1 保護レベル定義

```python
# pdl/config.py

# LEVEL 0: Session Bが絶対に触れてはいけないファイル
FORBIDDEN_FILES = {
    # コアカーネル
    "agents/os_kernel.py",
    "agents/approval_manager.py",
    "tools/emergency_kill.py",
    "tools/loop_guard.py",
    "tools/budget_guard.py",
    "tools/semantic_loop_detector.py",
    "tools/cross_goal_detector.py",

    # 安全装置
    "brain_alpha/safety_check.py",
    "brain_alpha/self_healer.py",

    # 認証・秘密情報
    ".env",
    "credentials.json",
    "token.json",
    "config/node_alpha.yaml",
    "config/node_bravo.yaml",
    "config/node_charlie.yaml",
    "config/node_delta.yaml",
    "config/nats-server.conf",
    "certs/",

    # インフラ設定
    "Caddyfile",
    "start.sh",
    "worker_main.py",

    # PDL自体（自己改変防止）
    "pdl/",

    # ルールファイル
    "CLAUDE.md",
    "IDENTITY.md",
    "SOUL.md",
    "AGENTS.md",
    "feature_flags.yaml",
}

# LEVEL 1: 変更可能だが差分レビュー必須（PR説明に明示必要）
REVIEW_REQUIRED_FILES = {
    "app.py",
    "scheduler.py",
    "tools/llm_router.py",
    "tools/db_pool.py",
    "tools/db_init.py",
    "tools/nats_client.py",
    "tools/node_manager.py",
    "bots/discord_bot.py",
    "agents/executor.py",
    "agents/verifier.py",
}

# LEVEL 2: 自由に変更可能（テスト通過が条件）
# 上記以外の全ファイル
```

### 3.2 Gate Keeper 実装

```python
# pdl/gate_keeper.py

class GateKeeper:
    """Session Bのファイルアクセスを制御する門番"""

    def check_file_access(self, filepath: str, operation: str) -> GateDecision:
        """
        Returns:
            GateDecision(allowed=bool, reason=str, level=int)
        """
        rel = os.path.relpath(filepath, PROJECT_ROOT)

        # LEVEL 0: 絶対禁止
        for forbidden in FORBIDDEN_FILES:
            if rel == forbidden or rel.startswith(forbidden):
                return GateDecision(
                    allowed=False,
                    reason=f"FORBIDDEN: {rel} はSession Bの変更禁止ファイル",
                    level=0,
                )

        # LEVEL 1: レビュー必須フラグ
        for review_req in REVIEW_REQUIRED_FILES:
            if rel == review_req:
                return GateDecision(
                    allowed=True,
                    reason=f"REVIEW_REQUIRED: {rel} はPR説明で変更理由を明示すること",
                    level=1,
                )

        # LEVEL 2: 自由
        return GateDecision(allowed=True, reason="OK", level=2)

    def validate_worktree_changes(self, worktree_path: str) -> list[GateViolation]:
        """worktreeの全変更をスキャンし、違反を検出"""
        violations = []
        changed_files = git_diff_names(worktree_path)

        for f in changed_files:
            decision = self.check_file_access(f, "modify")
            if not decision.allowed:
                violations.append(GateViolation(file=f, decision=decision))

        return violations
```

### 3.3 ファイルロック機構

Session AとSession Bの同時編集を防ぐファイルレベルロック:

```python
# pdl/gate_keeper.py (続き)

# PostgreSQLのadvisory lockを使用
# ファイルパスのハッシュをlock IDとして使う

async def acquire_file_lock(filepath: str, session_id: str, timeout_sec: int = 10) -> bool:
    """
    ファイルロック取得。advisory lockを使用。
    Session Aは常にロックを持つ（暗黙的優先権）。
    Session Bはロック取得を試み、失敗したらそのファイルをスキップ。
    """
    lock_id = hash_filepath_to_int64(filepath)
    async with get_connection() as conn:
        # pg_try_advisory_lock: ブロックせずに即座に結果を返す
        result = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", lock_id
        )
        if result:
            # ロック取得成功→ledgerに記録
            await conn.execute("""
                INSERT INTO pdl_file_locks (filepath, session_id, acquired_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (filepath) DO UPDATE
                SET session_id = $2, acquired_at = NOW()
            """, filepath, session_id)
        return result

async def release_file_lock(filepath: str, session_id: str):
    lock_id = hash_filepath_to_int64(filepath)
    async with get_connection() as conn:
        await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
        await conn.execute(
            "DELETE FROM pdl_file_locks WHERE filepath = $1 AND session_id = $2",
            filepath, session_id,
        )
```

---

## 4. 並行制御

### 4.1 セッション排他制御

```
┌────────────────────────────────────────────────────────┐
│                    Lock Hierarchy                        │
│                                                          │
│  Level 1: Global Session Lock (pdl_global_lock)         │
│    └── 最大1つのSession Bのみ実行可能                     │
│                                                          │
│  Level 2: File-Level Advisory Locks                     │
│    └── ファイル単位の排他制御                              │
│                                                          │
│  Level 3: Service Restart Lock (pdl_service_locks)      │
│    └── サービス再起動の排他制御                            │
│                                                          │
│  Level 4: Merge Lock (pdl_merge_lock)                   │
│    └── mainへのマージは1つずつ                            │
└────────────────────────────────────────────────────────┘
```

### 4.2 Session A検出メカニズム

Session Aはインタラクティブなので明示的にロックを取得しない。代わりにSession BがSession Aのアクティビティを検出する:

```python
# pdl/pdl_orchestrator.py

def detect_session_a_activity() -> bool:
    """Session Aがアクティブかどうかを検出"""
    checks = [
        # 1. claude プロセスの存在確認
        _check_claude_process(),
        # 2. main branchのgit statusが dirty
        _check_git_dirty(),
        # 3. 最近のファイル変更 (5分以内)
        _check_recent_file_changes(minutes=5),
    ]
    return any(checks)

def _check_claude_process() -> bool:
    """claude CLIプロセスが~/syutain_beta/で動作中か確認"""
    result = subprocess.run(
        ["pgrep", "-f", "claude.*syutain"],
        capture_output=True, text=True,
    )
    return result.returncode == 0

def _check_git_dirty() -> bool:
    """mainブランチに未コミット変更があるか"""
    result = subprocess.run(
        ["git", "-C", PROJECT_ROOT, "status", "--porcelain"],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())

def _check_recent_file_changes(minutes: int = 5) -> bool:
    """プロジェクト内のPythonファイルが直近N分に変更されたか"""
    cutoff = time.time() - (minutes * 60)
    for root, _, files in os.walk(PROJECT_ROOT):
        if "venv" in root or "node_modules" in root or "pdl_worktrees" in root:
            continue
        for f in files:
            if f.endswith((".py", ".yaml", ".ts", ".tsx")):
                path = os.path.join(root, f)
                if os.path.getmtime(path) > cutoff:
                    return True
    return False
```

### 4.3 cron重複実行防止

```python
# pdl/pdl_orchestrator.py

LOCK_FILE = Path("/tmp/pdl_session_b.lock")

def acquire_process_lock() -> bool:
    """プロセスレベルのロック (flock)"""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode())
        # fdを閉じない（プロセス終了まで保持）
        return True
    except (OSError, IOError):
        return False  # 別プロセスがロック保持中
```

### 4.4 サービス再起動ロック

```python
# pdl/gate_keeper.py

async def acquire_service_restart_lock(service_name: str, session_id: str) -> bool:
    """サービス再起動の排他ロック"""
    lock_id = hash(f"service_restart:{service_name}") & 0x7FFFFFFFFFFFFFFF
    async with get_connection() as conn:
        result = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", lock_id
        )
        if result:
            await conn.execute("""
                INSERT INTO pdl_service_locks (service_name, session_id, locked_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (service_name) DO UPDATE
                SET session_id = $2, locked_at = NOW()
            """, service_name, session_id)
        return result
```

### 4.5 Priority Override (Session Aホットフィックス)

Session Aが Session B作業中のファイルに緊急変更が必要な場合:

```python
# pdl/pdl_orchestrator.py

async def handle_priority_override(target_file: str):
    """
    Session Aがホットフィックスを要求した場合:
    1. Session Bの当該ファイルロックを強制解放
    2. Session Bにパーシャルコミットを指示
    3. Session Bをサスペンド (SUSPENDED状態)
    4. Session A完了後、Session Bはrebaseして再開
    """
    active_session = await get_active_session_b()
    if not active_session:
        return

    # Session Bが当該ファイルを変更中か確認
    if target_file in active_session.modified_files:
        await suspend_session_b(
            active_session.id,
            reason=f"Session A priority override for {target_file}",
        )
        # Session Bのworktreeでstash
        subprocess.run(
            ["git", "-C", active_session.worktree_path, "stash"],
            capture_output=True,
        )
        await notify_discord(
            f"[PDL] Session B suspended: Session Aが {target_file} をホットフィックス中"
        )
```

---

## 5. 予算パーティショニング

### 5.1 予算分割

```
日次予算: 80円 (DAILY_BUDGET_JPY)
├── Session A (Interactive): 56円 (70%)
│   └── 人間が判断するので柔軟に使用可能
├── Session B (Autonomous):  24円 (30%)
│   └── 自動タスクには厳格な上限
│       ├── 単一タスク上限: 8円
│       └── 単一LLM呼び出し上限: 3円
└── 緊急リザーブ: 0円 (Session A枠に内包)
    └── Session Bが枠を使い切っても、Session Aの枠は侵食されない
```

### 5.2 実装

```python
# pdl/budget_partition.py

class BudgetPartition:
    """Session A/B間の予算を分離管理"""

    SESSION_A_RATIO = 0.70
    SESSION_B_RATIO = 0.30
    SESSION_B_SINGLE_TASK_MAX_JPY = 8.0
    SESSION_B_SINGLE_CALL_MAX_JPY = 3.0

    async def get_session_b_remaining(self) -> float:
        """Session Bの本日残予算を計算"""
        async with get_connection() as conn:
            # Session Bの今日の支出合計
            spent = await conn.fetchval("""
                SELECT COALESCE(SUM(amount_jpy), 0)
                FROM llm_cost_log
                WHERE created_at::date = CURRENT_DATE
                  AND metadata->>'session_type' = 'session_b'
            """)
            daily_limit = DAILY_BUDGET_JPY * self.SESSION_B_RATIO
            return max(0, daily_limit - (spent or 0))

    async def can_spend(self, amount_jpy: float, task_id: str) -> tuple[bool, str]:
        """Session Bが支出可能か判定"""
        remaining = await self.get_session_b_remaining()

        if amount_jpy > remaining:
            return False, f"予算不足: 残{remaining:.1f}円 < 要求{amount_jpy:.1f}円"

        if amount_jpy > self.SESSION_B_SINGLE_CALL_MAX_JPY:
            return False, f"単一呼び出し上限超過: {amount_jpy:.1f}円 > {self.SESSION_B_SINGLE_CALL_MAX_JPY}円"

        # タスク単位の累計チェック
        task_spent = await self._get_task_spent(task_id)
        if task_spent + amount_jpy > self.SESSION_B_SINGLE_TASK_MAX_JPY:
            return False, f"タスク予算超過: 累計{task_spent + amount_jpy:.1f}円 > {self.SESSION_B_SINGLE_TASK_MAX_JPY}円"

        return True, "OK"
```

### 5.3 Session B用LLMルーター統合

Session Bは既存の `llm_router.py` を **直接呼ばない**。PDL専用ラッパーを経由する:

```python
# pdl/budget_partition.py (続き)

async def session_b_call_llm(prompt: str, task_id: str, **kwargs) -> str:
    """Session B専用のLLM呼び出しラッパー"""
    # 1. 事前コスト見積もり
    estimated_cost = estimate_cost(prompt, kwargs.get("model"))

    # 2. 予算チェック
    can, reason = await budget_partition.can_spend(estimated_cost, task_id)
    if not can:
        raise BudgetExhaustedError(reason)

    # 3. Session Bはローカルモデル優先
    kwargs.setdefault("quality", "low")
    kwargs.setdefault("local_available", True)
    kwargs.setdefault("budget_sensitive", True)

    # 4. 既存ルーター経由で呼び出し
    model_sel = choose_best_model_v6(task_type=kwargs.get("task_type", "general"), **kwargs)
    result = await call_llm(prompt, model=model_sel["model"])

    # 5. 支出記録 (session_type=session_bをメタデータに付与)
    await record_cost(model_sel, task_id, session_type="session_b")

    return result
```

---

## 6. テスト戦略

### 6.1 テストゲート (Session Bの変更がmainに入る前に全て通過必須)

```
┌─────────────────────────────────────────────────────┐
│                    Test Pipeline                      │
│                                                       │
│  Stage 1: Static Analysis (即座)                     │
│  ├── Python syntax check (py_compile)                │
│  ├── Import cycle detection                          │
│  ├── FORBIDDEN_FILES violation check                 │
│  └── .env / credentials leak scan                    │
│                                                       │
│  Stage 2: Unit Tests (worktree内, ~2分)              │
│  ├── pytest pdl/tests/ (PDL自体のテスト)             │
│  └── pytest tests/ (既存テストがあれば)               │
│                                                       │
│  Stage 3: Integration Smoke Test (~3分)              │
│  ├── FastAPI起動確認 (import check)                  │
│  ├── Scheduler起動確認 (import check)                │
│  ├── 全モジュールimport可能確認                       │
│  └── DB接続確認 (read-only query)                    │
│                                                       │
│  Stage 4: Regression Detection (~5分)                │
│  ├── 変更前後のAPI応答比較                            │
│  ├── LLMルーター経路テスト (モック)                   │
│  └── 既存feature_flags全パス確認                     │
│                                                       │
│  ALL PASS → PR作成許可                                │
│  ANY FAIL → 自動ロールバック + Discord通知            │
└─────────────────────────────────────────────────────┘
```

### 6.2 テスト実装

```python
# pdl/test_harness.py

class TestHarness:
    """Session Bの変更に対するテストパイプライン"""

    async def run_all_gates(self, worktree_path: str) -> TestResult:
        """全テストゲートを順次実行"""
        results = []

        # Stage 1: Static Analysis
        r = await self._stage_static(worktree_path)
        results.append(r)
        if not r.passed:
            return TestResult(passed=False, stage="static", details=results)

        # Stage 2: Unit Tests
        r = await self._stage_unit(worktree_path)
        results.append(r)
        if not r.passed:
            return TestResult(passed=False, stage="unit", details=results)

        # Stage 3: Integration
        r = await self._stage_integration(worktree_path)
        results.append(r)
        if not r.passed:
            return TestResult(passed=False, stage="integration", details=results)

        # Stage 4: Regression
        r = await self._stage_regression(worktree_path)
        results.append(r)

        return TestResult(
            passed=all(r.passed for r in results),
            stage="complete",
            details=results,
        )

    async def _stage_static(self, wt: str) -> StageResult:
        """静的解析"""
        errors = []

        # Python syntax
        for py_file in glob.glob(f"{wt}/**/*.py", recursive=True):
            if "venv" in py_file or "node_modules" in py_file:
                continue
            try:
                py_compile.compile(py_file, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"Syntax error: {e}")

        # Import cycle detection
        cycles = detect_import_cycles(wt)
        if cycles:
            errors.append(f"Circular imports detected: {cycles}")

        # Forbidden file check
        gate_keeper = GateKeeper()
        violations = gate_keeper.validate_worktree_changes(wt)
        for v in violations:
            errors.append(f"Forbidden file modified: {v.file}")

        # Credential leak scan
        leaks = scan_for_credentials(wt)
        for leak in leaks:
            errors.append(f"Possible credential leak: {leak}")

        return StageResult(passed=len(errors) == 0, errors=errors)

    async def _stage_integration(self, wt: str) -> StageResult:
        """統合テスト: 全モジュールがimport可能か確認"""
        errors = []
        # worktreeのディレクトリをPYTHONPATHに追加してimportテスト
        env = os.environ.copy()
        env["PYTHONPATH"] = wt

        # 全.pyファイルのimportチェック
        for py_file in _find_project_modules(wt):
            module_name = _path_to_module(py_file, wt)
            result = subprocess.run(
                [sys.executable, "-c", f"import {module_name}"],
                capture_output=True, text=True, env=env, timeout=30,
                cwd=wt,
            )
            if result.returncode != 0:
                errors.append(f"Import failed: {module_name}: {result.stderr[:200]}")

        return StageResult(passed=len(errors) == 0, errors=errors)
```

### 6.3 本番環境差異への対処 (Edge Case #18)

```python
# pdl/test_harness.py (続き)

async def _stage_regression(self, wt: str) -> StageResult:
    """回帰テスト: 環境差異を含む"""
    errors = []

    # 1. .envの全変数がworktree内コードで参照可能か確認
    env_vars = parse_env_file(f"{PROJECT_ROOT}/.env")
    code_refs = find_env_references(wt)
    for var in code_refs:
        if var not in env_vars and not var.startswith("PDL_"):
            errors.append(f"コードが参照する環境変数 {var} が.envに未定義")

    # 2. DB schema互換性チェック
    # worktreeのCREATE TABLE文を解析し、実DBスキーマと照合
    new_tables = extract_create_table_statements(wt)
    for table_name, columns in new_tables.items():
        existing = await get_table_schema(table_name)
        if existing and not is_compatible(existing, columns):
            errors.append(f"DB schema非互換: {table_name}")

    return StageResult(passed=len(errors) == 0, errors=errors)
```

---

## 7. ロールバック手順

### 7.1 自動ロールバック (Session B失敗時)

```python
# pdl/worktree_manager.py

async def rollback_session(session_id: str, reason: str):
    """Session Bの変更を完全にロールバック"""
    session = await get_session(session_id)

    # 1. worktree内の変更を破棄
    subprocess.run(
        ["git", "-C", session.worktree_path, "checkout", "."],
        capture_output=True,
    )

    # 2. worktreeを削除
    subprocess.run(
        ["git", "-C", PROJECT_ROOT, "worktree", "remove", "--force",
         session.worktree_path],
        capture_output=True,
    )

    # 3. ブランチを削除
    subprocess.run(
        ["git", "-C", PROJECT_ROOT, "branch", "-D", session.branch_name],
        capture_output=True,
    )

    # 4. ファイルロックを全解放
    await release_all_locks(session_id)

    # 5. ledgerに記録
    await update_session_status(session_id, "ROLLED_BACK", reason=reason)

    # 6. Discord通知
    await notify_discord(
        f"[PDL] Session B rolled back\n"
        f"Task: {session.task_id}\n"
        f"Reason: {reason}"
    )
```

### 7.2 マージ後のロールバック

PRがマージされた後に問題が発覚した場合:

```python
async def rollback_merged_pr(pr_number: int, reason: str):
    """マージ済みPRのリバート"""
    # 1. リバートコミットを作成
    merge_commit = await get_merge_commit(pr_number)
    subprocess.run(
        ["git", "-C", PROJECT_ROOT, "revert", "--no-edit", merge_commit],
        capture_output=True,
    )

    # 2. サービス再起動
    await restart_affected_services()

    # 3. 記録
    await log_event(
        event_type="pdl_revert",
        category="parallel_dev",
        severity="high",
        source_node="alpha",
        detail=f"PR #{pr_number} reverted: {reason}",
    )
```

### 7.3 Session Aの変更はSession Bに影響しない

Session Bはworktreeで作業するため、Session Aがmainを変更してもSession Bの作業中コードには影響しない。マージ時にコンフリクトが発生した場合は Merge Arbiter が処理する（セクション4参照）。

---

## 8. 監視とアラート

### 8.1 監視ポイント

```python
# pdl/config.py

MONITORING_CHECKS = {
    # Check名: (間隔秒, 閾値, アクション)
    "session_b_duration": (60, 2700, "warn_then_kill"),    # 45分超過
    "session_b_budget":   (30, 0.9, "kill"),               # 予算90%到達
    "worktree_disk":      (300, 1073741824, "cleanup"),    # 1GB未満
    "worktree_count":     (600, 5, "cleanup"),             # 5個以上蓄積
    "db_pool_available":  (30, 2, "pause_session_b"),      # 空き2未満
    "merge_conflict":     (60, 0, "notify"),               # コンフリクト発生
    "test_failure_rate":  (3600, 0.5, "pause_session_b"),  # 失敗率50%超
}
```

### 8.2 Discord通知フォーマット

```python
# pdl/pdl_orchestrator.py

NOTIFICATION_TEMPLATES = {
    "session_started": "[PDL] Session B開始\nTask: {task_id}\nType: {task_type}\nBranch: {branch}",
    "session_completed": "[PDL] Session B完了\nTask: {task_id}\nPR: {pr_url}\nCost: {cost_jpy:.1f}円",
    "session_failed": "[PDL] Session B失敗\nTask: {task_id}\nStage: {stage}\nError: {error}",
    "budget_warning": "[PDL] 予算警告\nSession B残: {remaining:.1f}円 / {limit:.1f}円",
    "priority_override": "[PDL] Session A優先割込\nFile: {file}\nSession Bをサスペンド",
    "merge_conflict": "[PDL] マージコンフリクト\nBranch: {branch}\nFiles: {files}",
    "worktree_cleanup": "[PDL] Worktreeクリーンアップ\n削除: {count}個\n空き: {free_gb:.1f}GB",
}
```

### 8.3 PostgreSQL監視テーブル

```sql
-- pdl/schemas.py で定義、pdl_orchestrator.pyの初回起動時にCREATE IF NOT EXISTS

CREATE TABLE IF NOT EXISTS pdl_sessions (
    id TEXT PRIMARY KEY,            -- UUID
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    -- QUEUED, CLAIMED, WORKTREE_CREATED, EXECUTING, TESTING,
    -- PR_CREATED, COMPLETED, FAILED, ROLLED_BACK, SUSPENDED
    branch_name TEXT,
    worktree_path TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cost_jpy REAL DEFAULT 0,
    error_detail TEXT,
    modified_files TEXT[],          -- 変更したファイルリスト
    test_results JSONB,
    pr_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pdl_task_queue (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,            -- 'failure_memory', 'manual', 'scheduler', 'auto_fix'
    source_id TEXT,                  -- failure_memory.id等の元ID
    task_type TEXT NOT NULL,         -- 'bug_fix', 'enhancement', 'refactor', 'test'
    priority INTEGER DEFAULT 50,     -- 0=最高, 100=最低
    description TEXT NOT NULL,
    target_files TEXT[],            -- 対象ファイルのヒント
    status TEXT DEFAULT 'pending',   -- pending, claimed, completed, failed, skipped, deduped
    claimed_by TEXT,                -- session_id
    created_at TIMESTAMPTZ DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    dedup_key TEXT                   -- 重複排除キー
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pdl_task_dedup
    ON pdl_task_queue (dedup_key) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS pdl_file_locks (
    filepath TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pdl_service_locks (
    service_name TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pdl_merge_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    merge_commit TEXT,
    conflict_files TEXT[],
    resolution TEXT,                -- 'auto', 'manual', 'aborted'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 9. 55K行コードベースの組織化ルール

### 9.1 CODE_MAP統合

Session Bが作業を開始する前に読み込むコンテキスト:

```python
# pdl/pdl_orchestrator.py

SESSION_B_CONTEXT = """
# Session B コンテキスト

## 読み込み必須ファイル (作業前に全て読む)
1. CLAUDE.md - 26条ルール (絶対遵守)
2. CODE_MAP.md - ファイル構造と依存関係
3. feature_flags.yaml - 有効機能リスト
4. pdl/config.py - 保護ファイルリストと制約

## アーキテクチャ概要
- agents/ : オーケストレーション層 (os_kernel中心)
- tools/  : ユーティリティ層 (llm_router, db_pool が基盤)
- bots/   : Discord連携層
- brain_alpha/ : 上位判断層 (persona_memory参照)
- config/ : ノード設定 (YAML)

## 依存フロー (上→下)
  brain_alpha → agents → tools
  bots → tools
  app.py → agents, tools
  scheduler.py → agents, tools, brain_alpha

## import規則
- tools/ は agents/ を import しない (単方向依存)
- bots/ は agents/ を import しない
- brain_alpha/ は agents/ を import できる
- 循環import禁止 (テストゲートで検出)

## DB接続
- 必ず tools.db_pool.get_connection() を使う
- 直接 asyncpg.connect() は禁止
- コネクションは async with で必ずリリース

## LLM呼び出し
- 必ず tools.llm_router.choose_best_model_v6() を使う
- Session Bは pdl.budget_partition.session_b_call_llm() 経由
"""
```

### 9.2 依存グラフ検証

```python
# pdl/test_harness.py

ALLOWED_IMPORT_DIRECTIONS = {
    # from_module → to_module (許可方向)
    "brain_alpha": {"agents", "tools", "config"},
    "agents":      {"tools", "config"},
    "bots":        {"tools", "config"},
    "tools":       {"config"},
    "app":         {"agents", "tools", "bots", "brain_alpha", "config"},
    "scheduler":   {"agents", "tools", "brain_alpha", "config"},
    "pdl":         {"tools"},  # PDLはtoolsのみ参照可
}

FORBIDDEN_IMPORT_DIRECTIONS = {
    # 絶対禁止
    ("tools", "agents"),
    ("tools", "bots"),
    ("tools", "brain_alpha"),
    ("bots", "agents"),
    ("config", "tools"),
    ("config", "agents"),
}

def detect_import_cycles(worktree_path: str) -> list[str]:
    """importの循環を検出"""
    violations = []
    for py_file in find_all_py_files(worktree_path):
        module_dir = get_module_dir(py_file)
        imports = extract_imports(py_file)
        for imp in imports:
            target_dir = get_module_dir_from_import(imp)
            if (module_dir, target_dir) in FORBIDDEN_IMPORT_DIRECTIONS:
                violations.append(
                    f"{py_file}: {module_dir} → {target_dir} (forbidden import)"
                )
    return violations
```

### 9.3 変更帰属追跡

```python
# pdl/session_ledger.py

async def record_change_attribution(
    session_id: str,
    session_type: str,  # "session_a" or "session_b"
    filepath: str,
    change_type: str,   # "create", "modify", "delete"
    diff_summary: str,
    commit_hash: str,
):
    """全変更の帰属を記録"""
    async with get_connection() as conn:
        await conn.execute("""
            INSERT INTO pdl_change_log
            (session_id, session_type, filepath, change_type, diff_summary, commit_hash, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
        """, session_id, session_type, filepath, change_type, diff_summary, commit_hash)
```

---

## 10. セッション間コンテキスト共有

### 10.1 共有メカニズム

```
┌──────────────┐     ┌─────────────────────┐     ┌──────────────┐
│  Session A    │     │   Shared Context     │     │  Session B    │
│              │     │                     │     │              │
│  writes →    │     │  pdl_sessions table │     │  ← reads     │
│  (implicit)  │     │  pdl_task_queue     │     │              │
│              │     │  failure_memory     │     │  writes →    │
│  reads ←     │     │  event_log          │     │  (via PR)    │
│  (PR review) │     │  auto_fix_rules     │     │              │
│              │     │  git log (main)     │     │              │
└──────────────┘     └─────────────────────┘     └──────────────┘
```

### 10.2 Session Bの成果をSession Aが認識する

Session Bが作成したPRは以下の情報を含む:

```markdown
## [PDL] Auto-fix: {task_description}

### 変更概要
- 対象ファイル: {file_list}
- 変更種別: {bug_fix|enhancement|refactor}
- 元タスク: failure_memory #{source_id}

### テスト結果
- Static: PASS
- Unit: PASS
- Integration: PASS
- Regression: PASS

### 予算消費
- LLM費用: {cost_jpy:.1f}円
- モデル: {models_used}

### ロールバック手順
`git revert {commit_hash}`

---
*Generated by PDL Session B ({session_id})*
```

### 10.3 failure_memory重複排除 (Edge Case #17)

```python
# pdl/dedup_engine.py

async def dedup_failure_tasks() -> int:
    """failure_memoryからタスクを作成する際の重複排除"""
    async with get_connection() as conn:
        # 1. 同一error_patternの失敗を集約
        clusters = await conn.fetch("""
            SELECT error_pattern, COUNT(*) as cnt,
                   array_agg(id) as ids,
                   MAX(created_at) as latest
            FROM failure_memory
            WHERE status = 'unresolved'
            GROUP BY error_pattern
            HAVING COUNT(*) > 1
        """)

        deduped = 0
        for cluster in clusters:
            # 最新のものだけ残し、他は 'deduped' マーク
            ids = cluster["ids"]
            keep_id = ids[-1]  # 最新
            mark_ids = ids[:-1]

            if mark_ids:
                await conn.execute("""
                    UPDATE failure_memory SET status = 'deduped'
                    WHERE id = ANY($1)
                """, mark_ids)
                deduped += len(mark_ids)

        # 2. タスクキューの重複チェック (dedup_keyベース)
        # UNIQUE INDEX idx_pdl_task_dedup がDBレベルで排除

        return deduped
```

---

## 11. 障害復旧

### 11.1 中断復旧 (Edge Case #19)

```python
# pdl/recovery_agent.py

async def recover_interrupted_sessions():
    """
    システム再起動後に呼ばれる。
    中断されたSession Bを検出し、クリーンアップする。
    """
    async with get_connection() as conn:
        # 未完了セッションを検出
        orphaned = await conn.fetch("""
            SELECT * FROM pdl_sessions
            WHERE status IN ('CLAIMED', 'WORKTREE_CREATED', 'EXECUTING', 'TESTING')
              AND started_at < NOW() - INTERVAL '1 hour'
        """)

        for session in orphaned:
            logger.warning(f"Orphaned session detected: {session['id']}")

            # worktreeが残っていたらクリーン
            wt_path = session["worktree_path"]
            if wt_path and os.path.exists(wt_path):
                # 未コミットの変更があればスタッシュ
                result = subprocess.run(
                    ["git", "-C", wt_path, "stash"],
                    capture_output=True, text=True,
                )
                if "No local changes" not in result.stdout:
                    logger.info(f"Stashed changes in {wt_path}")

                # worktree削除
                subprocess.run(
                    ["git", "-C", PROJECT_ROOT, "worktree", "remove", "--force", wt_path],
                    capture_output=True,
                )

            # ブランチ削除
            if session["branch_name"]:
                subprocess.run(
                    ["git", "-C", PROJECT_ROOT, "branch", "-D", session["branch_name"]],
                    capture_output=True,
                )

            # ファイルロック解放
            await conn.execute(
                "DELETE FROM pdl_file_locks WHERE session_id = $1",
                session["id"],
            )

            # ステータス更新
            await conn.execute("""
                UPDATE pdl_sessions
                SET status = 'ROLLED_BACK',
                    error_detail = 'System restart recovery',
                    completed_at = NOW()
                WHERE id = $1
            """, session["id"])

            # タスクをキューに戻す
            await conn.execute("""
                UPDATE pdl_task_queue
                SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                WHERE claimed_by = $1 AND status = 'claimed'
            """, session["id"])

        return len(orphaned)
```

### 11.2 ネットワーク障害時の部分変更 (Edge Case #8)

```python
# pdl/worktree_manager.py

class WorktreeManager:
    """git worktreeのライフサイクル管理"""

    async def create_worktree(self, session_id: str, task_id: str) -> str:
        """worktree作成。失敗時は完全クリーン。"""
        branch = f"pdl/session-b-{task_id}-{int(time.time())}"
        wt_path = f"{PROJECT_ROOT}/pdl_worktrees/{branch.replace('/', '_')}"

        try:
            # ブランチ作成
            subprocess.run(
                ["git", "-C", PROJECT_ROOT, "branch", branch, "main"],
                check=True, capture_output=True,
            )
            # worktree作成
            subprocess.run(
                ["git", "-C", PROJECT_ROOT, "worktree", "add", wt_path, branch],
                check=True, capture_output=True,
            )
            return wt_path
        except subprocess.CalledProcessError as e:
            # 失敗したら途中のゴミを掃除
            self._force_cleanup(wt_path, branch)
            raise WorktreeCreationError(str(e))

    def _force_cleanup(self, wt_path: str, branch: str):
        """worktree/ブランチの強制クリーン"""
        if os.path.exists(wt_path):
            subprocess.run(
                ["git", "-C", PROJECT_ROOT, "worktree", "remove", "--force", wt_path],
                capture_output=True,
            )
        subprocess.run(
            ["git", "-C", PROJECT_ROOT, "branch", "-D", branch],
            capture_output=True,
        )
```

### 11.3 Worktreeクリーンアップ (Edge Case #14)

```python
# pdl/cleanup_daemon.py

async def cleanup_stale_worktrees():
    """古いworktreeを定期クリーンアップ"""
    wt_base = f"{PROJECT_ROOT}/pdl_worktrees"
    if not os.path.exists(wt_base):
        return 0

    cleaned = 0
    for entry in os.scandir(wt_base):
        if not entry.is_dir():
            continue

        # 24時間以上放置されたworktree
        age_hours = (time.time() - entry.stat().st_mtime) / 3600
        if age_hours > 24:
            # DBでセッション状態確認
            session = await find_session_by_worktree(entry.path)
            if session and session["status"] in ("COMPLETED", "ROLLED_BACK", "FAILED"):
                _force_remove_worktree(entry.path)
                cleaned += 1
            elif not session:
                # DBにレコードがない孤児worktree
                _force_remove_worktree(entry.path)
                cleaned += 1

    # ディスク空き確認
    free_gb = shutil.disk_usage(wt_base).free / (1024**3)
    if free_gb < 2.0:
        # 緊急クリーン: COMPLETED のworktreeを全削除
        cleaned += await _emergency_cleanup(wt_base)

    return cleaned

def _force_remove_worktree(path: str):
    """worktreeを強制削除"""
    # まずgit worktree removeを試す
    subprocess.run(
        ["git", "-C", PROJECT_ROOT, "worktree", "remove", "--force", path],
        capture_output=True,
    )
    # 残っていたらshutil
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
```

---

## 12. 全25リスクへの対応マトリクス

### Edge Cases & Failure Modes

| # | リスク | 検出 | 防止 | 復旧 | 監視 |
|---|--------|------|------|------|------|
| 1 | Session B modifies file Session A is editing | `detect_session_a_activity()` + advisory lock | Session Bはロック取得失敗時にファイルをスキップ | ファイルロック自動解放 (セッション終了時) | `pdl_file_locks` テーブル監視 |
| 2 | Session B introduces bug | 4段階テストゲート (static→unit→integration→regression) | テスト全通過までmainマージ禁止 | `git revert` による即座ロールバック | テスト失敗率トラッキング |
| 3 | Git worktree conflicts | `git merge --no-commit` でドライラン | Session Bはマージ前にmainをrebase | コンフリクト時は自動ロールバック、手動解決をリクエスト | `pdl_merge_log` でコンフリクト頻度追跡 |
| 4 | cron fires but previous Session B running | `flock` によるプロセスロック + DB状態チェック | ロック取得失敗時はcronジョブが即座に終了 | orphanedセッション検出 (1時間超過) | プロセスロックファイル + DBステータス |
| 5 | Session B exhausts budget | `BudgetPartition` による分離会計 | Session B上限=日次予算30%、Session A枠に侵食不可 | 予算超過時は即座にセッション終了 | 30秒間隔で残予算チェック |
| 6 | Review contradicts fix | PDLはCodex Reviewを使用しない。テストゲートが唯一の品質判定 | N/A (設計でこの状況を排除) | N/A | N/A |
| 7 | Session B modifies critical file | `FORBIDDEN_FILES` リスト (Level 0) | GateKeeperが変更前にチェック、静的解析ゲートで二重確認 | 禁止ファイル変更は即セッション終了 | `GateViolation` イベントログ |
| 8 | Network failure during execution | worktreeは完全ローカル。ネットワーク不要 | git操作はローカル完結。DBアクセス失敗はリトライ3回 | `recovery_agent` が中断セッションを検出→クリーンアップ | orphanedセッション定期スキャン |
| 9 | PostgreSQL connection pool exhausted | `get_pool_available_connections()` でチェック | Session B起動前に空き3以上を要求。Session BはDB接続を長期保持しない | Session Bを一時停止してコネクション解放 | 30秒間隔でプール状態チェック |
| 10 | Subtle regression passes tests | Stage 4 回帰テスト + PR人間レビュー | マージは人間承認必須 (自動マージしない) | `git revert` + failure_memoryに記録 | マージ後のevent_logでエラーパターン監視 |
| 11 | 5 pending tasks, 1 slot | `pdl_task_queue.priority` による優先度ソート | 優先度: bug_fix(10) > enhancement(50) > refactor(70) > test(80) | タスクはキューに残り、次回セッションで処理 | キュー深さとエイジング監視 |
| 12 | Session A needs hotfix on Session B's file | `handle_priority_override()` | Session Bをサスペンド、Session A完了後にrebase再開 | Session Bのworktreeでstash保存 | Discord即時通知 |
| 13 | Infinite loop (PR→trigger→PR→...) | `pdl/loop_breaker.py`: PRソースを追跡 | Session B作成PRには `[PDL]` プレフィックス。PDL PRにはtrigger発火しない | 同一タスクの連続実行を5回で凍結 | PDL起因のPR作成回数/時間を監視 |
| 14 | Worktrees fill disk | `cleanup_daemon` (1時間間隔) | worktree最大5個制限。24時間超過で自動削除 | 緊急時: COMPLETED worktreeを全削除 | ディスク使用量監視、2GB未満で警告 |
| 15 | CHARLIE in Win11 mode | `brain_alpha/self_healer.py` の `charlie_win11` 状態を参照 | `node_awareness.py` がノード状態をリアルタイムチェック | CHARLIEダウン時はBRAVO/DELTAにフォールバック | 既存のself_healer監視を利用 |
| 16 | Session B modifies .env/credentials | `FORBIDDEN_FILES` に `.env`, `credentials.json`, `token.json` 登録 | GateKeeper Level 0チェック + 静的解析ゲートでリーク検知 | 変更検出時は即セッション終了＋ロールバック | credential leakスキャン |
| 17 | Duplicate failure_memory entries | `dedup_engine.py`: error_patternでクラスタリング | `pdl_task_queue.dedup_key` のUNIQUE制約 | 重複タスクは `deduped` ステータス | 重複検出率の追跡 |
| 18 | Works in worktree, fails in production | Stage 3: 全モジュールimportテスト、Stage 4: env変数照合、DBスキーマ互換チェック | worktreeは本番と同じ.envを参照 (シンボリックリンク) | マージ後問題→即 `git revert` | マージ後30分のエラーレート監視 |
| 19 | System restart mid-execution | `recovery_agent.recover_interrupted_sessions()` | 起動時に自動実行。orphanedセッションを検出 | worktreeクリーン＋タスクをキューに戻す | orphaned sessions数の追跡 |
| 20 | Both sessions restart same service | `pdl_service_locks` + advisory lock | 再起動前にロック取得必須。取得失敗→スキップ | ロックは60秒TTLで自動解放 | サービス再起動ログ |

### Code Architecture Concerns

| # | リスク | 対応 |
|---|--------|------|
| 21 | New session understanding codebase | `SESSION_B_CONTEXT` テンプレート + CODE_MAP.md + CLAUDE.md 自動注入 |
| 22 | Circular imports | `ALLOWED_IMPORT_DIRECTIONS` / `FORBIDDEN_IMPORT_DIRECTIONS` + テストゲートで検出 |
| 23 | Session A/B changes compatibility | Session BはPR経由でのみmainに入る。マージ前にmainをrebase→テスト再実行 |
| 24 | Change attribution | `pdl_change_log` テーブル。全変更にsession_id + session_type付与 |
| 25 | Rollback Session B without affecting A | Session Bはworktree隔離。ロールバック = worktree削除 + ブランチ削除。mainの影響ゼロ |

---

## 付録A: cron設定例

```bash
# Session B: 毎時15分に起動試行 (夜間のみ: 23:00-07:00 JST)
15 23,0-6 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/pdl_orchestrator.py --mode=cron 2>&1 >> ~/syutain_beta/logs/pdl_cron.log

# Worktreeクリーンアップ: 毎日04:00 JST
0 4 * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/cleanup_daemon.py 2>&1 >> ~/syutain_beta/logs/pdl_cleanup.log

# 中断復旧チェック: 起動時 (LaunchAgent KeepAlive経由) + 毎時00分
0 * * * * ~/syutain_beta/venv/bin/python ~/syutain_beta/pdl/recovery_agent.py 2>&1 >> ~/syutain_beta/logs/pdl_recovery.log
```

## 付録B: git初期設定 (前提条件)

```bash
# syutain_beta をgitリポジトリとして初期化 (まだの場合)
cd ~/syutain_beta
git init
echo "pdl_worktrees/" >> .gitignore
echo "venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo "logs/" >> .gitignore
git add -A
git commit -m "Initial commit: SYUTAINβ codebase"
```

## 付録C: DBスキーマ初期化SQL

```sql
-- pdl/schemas.py の ensure_tables() から実行される
-- 既存テーブルには一切触れない

CREATE TABLE IF NOT EXISTS pdl_sessions (...);       -- セクション8.3参照
CREATE TABLE IF NOT EXISTS pdl_task_queue (...);
CREATE TABLE IF NOT EXISTS pdl_file_locks (...);
CREATE TABLE IF NOT EXISTS pdl_service_locks (...);
CREATE TABLE IF NOT EXISTS pdl_merge_log (...);

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

CREATE TABLE IF NOT EXISTS pdl_budget_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    amount_jpy REAL NOT NULL,
    model TEXT,
    remaining_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## 付録D: 実装優先度

| Phase | 実装内容 | 所要時間(見積) |
|-------|---------|--------------|
| Phase 1 | `config.py`, `schemas.py`, `gate_keeper.py`, `worktree_manager.py` | 4時間 |
| Phase 2 | `task_queue.py`, `budget_partition.py`, `session_ledger.py` | 3時間 |
| Phase 3 | `test_harness.py`, `pdl_orchestrator.py` | 5時間 |
| Phase 4 | `cleanup_daemon.py`, `recovery_agent.py`, `merge_arbiter.py` | 3時間 |
| Phase 5 | `dedup_engine.py`, `loop_breaker.py`, `node_awareness.py` | 2時間 |
| Phase 6 | cron設定、監視統合、ドキュメント | 2時間 |
| **合計** | | **19時間** |

---

*End of Design Document*
