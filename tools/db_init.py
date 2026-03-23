"""
SYUTAINβ V25 データベース初期化
PostgreSQL（ALPHA共有状態）+ SQLite（ノードローカル）のハイブリッド構成
"""

import os
import sqlite3
import asyncio
import logging
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.db_init")

# ===== PostgreSQL DDL（ALPHA共有状態）=====
POSTGRESQL_DDL = """
-- タスク管理
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    assigned_node TEXT,
    model_used TEXT,
    tier TEXT,
    input_data JSONB,
    output_data JSONB,
    artifacts JSONB,
    cost_jpy REAL DEFAULT 0.0,
    quality_score REAL,
    browser_action BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Goal Packet
CREATE TABLE IF NOT EXISTS goal_packets (
    goal_id TEXT PRIMARY KEY,
    raw_goal TEXT NOT NULL,
    parsed_objective TEXT,
    success_definition JSONB,
    hard_constraints JSONB,
    soft_constraints JSONB,
    approval_boundary JSONB,
    status TEXT DEFAULT 'active',
    progress REAL DEFAULT 0.0,
    total_steps INTEGER DEFAULT 0,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 提案履歴
CREATE TABLE IF NOT EXISTS proposal_history (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT UNIQUE,
    title TEXT,
    target_icp TEXT,
    primary_channel TEXT,
    score INTEGER,
    adopted BOOLEAN DEFAULT FALSE,
    outcome_type TEXT,
    revenue_impact_jpy INTEGER DEFAULT 0,
    proposal_data JSONB,
    counter_data JSONB,
    alternative_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 提案フィードバック
CREATE TABLE IF NOT EXISTS proposal_feedback (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    layer_used TEXT NOT NULL,
    adopted BOOLEAN DEFAULT FALSE,
    rejection_reason TEXT,
    alternative_chosen TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 収益紐付け
CREATE TABLE IF NOT EXISTS revenue_linkage (
    id SERIAL PRIMARY KEY,
    source_content_id TEXT,
    product_id TEXT,
    membership_offer_id TEXT,
    btob_offer_id TEXT,
    conversion_stage TEXT,
    revenue_jpy INTEGER DEFAULT 0,
    platform TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 能力監査スナップショット
CREATE TABLE IF NOT EXISTS capability_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_data JSONB NOT NULL,
    diff_from_previous JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ループガードイベント
CREATE TABLE IF NOT EXISTS loop_guard_events (
    id SERIAL PRIMARY KEY,
    goal_id TEXT NOT NULL,
    layer_triggered INTEGER NOT NULL,
    layer_name TEXT NOT NULL,
    trigger_reason TEXT,
    action_taken TEXT,
    step_count_at_trigger INTEGER,
    cost_at_trigger_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- モデル品質ログ
CREATE TABLE IF NOT EXISTS model_quality_log (
    id SERIAL PRIMARY KEY,
    task_type TEXT NOT NULL,
    model_used TEXT NOT NULL,
    tier TEXT NOT NULL,
    quality_score REAL DEFAULT 0.0,
    refinement_needed BOOLEAN DEFAULT FALSE,
    refinement_model TEXT,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 季節収益相関
CREATE TABLE IF NOT EXISTS seasonal_revenue_correlation (
    id SERIAL PRIMARY KEY,
    month INTEGER,
    event_tag TEXT,
    product_category TEXT,
    revenue_impact_jpy INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 会話履歴（Web UIチャット用）
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 情報収集ログ
CREATE TABLE IF NOT EXISTS intel_items (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    keyword TEXT,
    title TEXT,
    summary TEXT,
    url TEXT,
    importance_score REAL DEFAULT 0.0,
    category TEXT,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 暗号通貨取引ログ
CREATE TABLE IF NOT EXISTS crypto_trades (
    id SERIAL PRIMARY KEY,
    exchange TEXT NOT NULL,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,
    amount REAL,
    price REAL,
    fee_jpy REAL,
    pnl_jpy REAL,
    strategy TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 承認キュー
CREATE TABLE IF NOT EXISTS approval_queue (
    id SERIAL PRIMARY KEY,
    request_type TEXT NOT NULL,
    request_data JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    response TEXT
);

-- ブラウザ操作ログ（V25新規）
CREATE TABLE IF NOT EXISTS browser_action_log (
    id SERIAL PRIMARY KEY,
    node TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_url TEXT,
    layer_used TEXT NOT NULL,
    fallback_from TEXT,
    screenshot_path TEXT,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    model_used TEXT,
    stagehand_cache_hit BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 設定（キーバリュー）
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLMコストログ（budget_guard用）
CREATE TABLE IF NOT EXISTS llm_cost_log (
    id SERIAL PRIMARY KEY,
    model TEXT NOT NULL,
    tier TEXT,
    amount_jpy REAL NOT NULL,
    goal_id TEXT,
    is_info BOOLEAN DEFAULT FALSE,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- ベクトルストア（pgvector）
-- CREATE EXTENSION IF NOT EXISTS vector;  -- 別途手動で有効化が必要
CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL,
    content_id TEXT NOT NULL,
    embedding BYTEA,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_node ON tasks(assigned_node);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_intel_items_source ON intel_items(source);
CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_browser_action_log_node ON browser_action_log(node);
CREATE INDEX IF NOT EXISTS idx_loop_guard_events_goal ON loop_guard_events(goal_id);
"""

# ===== SQLite DDL（ノードローカル）=====
SQLITE_LOCAL_DDL = """
-- ノードローカルキャッシュ
CREATE TABLE IF NOT EXISTS local_cache (
    key TEXT PRIMARY KEY,
    value TEXT,
    expires_at TEXT
);

-- エージェントメモリ
CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ローカルメトリクス
CREATE TABLE IF NOT EXISTS local_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    labels TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);

-- LLM呼び出しログ
CREATE TABLE IF NOT EXISTS llm_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    tier TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_jpy REAL DEFAULT 0.0,
    latency_ms REAL,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    called_at TEXT DEFAULT (datetime('now'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent_name);
CREATE INDEX IF NOT EXISTS idx_local_metrics_name ON local_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_model ON llm_call_log(model);
"""


async def init_postgresql() -> bool:
    """PostgreSQLデータベースとテーブルを初期化"""
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

    # URLからDB名を抽出
    db_name = database_url.rsplit("/", 1)[-1]
    base_url = database_url.rsplit("/", 1)[0] + "/postgres"

    try:
        # DBが存在しなければ作成
        conn = await asyncpg.connect(base_url)
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
                logger.info(f"PostgreSQLデータベース '{db_name}' を作成しました")
        finally:
            await conn.close()

        # テーブル作成
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(POSTGRESQL_DDL)
            logger.info("PostgreSQLテーブルを初期化しました")
        finally:
            await conn.close()

        return True
    except Exception as e:
        logger.error(f"PostgreSQL初期化エラー: {e}")
        return False


def init_sqlite_local(node_name: str) -> bool:
    """ノードローカルSQLiteを初期化"""
    db_path = Path(f"data/local_{node_name}.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SQLITE_LOCAL_DDL)
        conn.close()
        logger.info(f"SQLite '{db_path}' を初期化しました")
        return True
    except Exception as e:
        logger.error(f"SQLite初期化エラー ({node_name}): {e}")
        return False


async def init_all_databases():
    """全データベースを初期化"""
    logging.basicConfig(level=logging.INFO)

    # PostgreSQL
    pg_ok = await init_postgresql()

    # ノードローカルSQLite
    node_name = os.getenv("THIS_NODE", "alpha")
    sqlite_ok = init_sqlite_local(node_name)

    if pg_ok and sqlite_ok:
        logger.info("全データベースの初期化が完了しました")
    else:
        logger.warning(f"一部のDB初期化に失敗: PostgreSQL={pg_ok}, SQLite={sqlite_ok}")

    return pg_ok, sqlite_ok


if __name__ == "__main__":
    asyncio.run(init_all_databases())
