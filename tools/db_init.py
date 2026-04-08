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
    progress_log JSONB DEFAULT '[]',
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
    product_title TEXT,
    membership_offer_id TEXT,
    btob_offer_id TEXT,
    conversion_stage TEXT,
    revenue_jpy INTEGER DEFAULT 0,
    fee_jpy INTEGER DEFAULT 0,
    net_revenue_jpy INTEGER DEFAULT 0,
    platform TEXT,
    platform_order_id TEXT,
    buyer_info TEXT,
    notes TEXT,
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
    review_flag TEXT DEFAULT 'pending_review',
    metadata JSONB,
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

-- 商品パッケージ（note/Booth/Stripe）
CREATE TABLE IF NOT EXISTS product_packages (
    id SERIAL PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'note',
    source_review_id INTEGER,
    title TEXT NOT NULL,
    body_preview TEXT,
    body_full TEXT,
    price_jpy INTEGER DEFAULT 0,
    tags JSONB DEFAULT '[]',
    category TEXT,
    status TEXT DEFAULT 'ready',
    approved_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    publish_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- note記事品質レビュー
CREATE TABLE IF NOT EXISTS note_quality_reviews (
    id SERIAL PRIMARY KEY,
    filepath TEXT,
    article_title TEXT,
    article_length INTEGER,
    stage1_result JSONB,
    stage1_score REAL,
    stage1_fatal BOOLEAN DEFAULT FALSE,
    stage2_model TEXT,
    stage2_result JSONB,
    stage2_verdict TEXT,
    stage2_pricing INTEGER,
    final_status TEXT,
    checked_at TIMESTAMPTZ DEFAULT NOW()
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

-- イベントログ（self_healer, event_logger等で使用）
CREATE TABLE IF NOT EXISTS event_log (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    severity TEXT DEFAULT 'info',
    source_node TEXT,
    goal_id TEXT,
    task_id TEXT,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Brain-αハンドオフ
CREATE TABLE IF NOT EXISTS brain_handoff (
    id SERIAL PRIMARY KEY,
    goal_id TEXT,
    status TEXT DEFAULT 'pending',
    handoff_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ノード状態管理（self_healerで使用）
CREATE TABLE IF NOT EXISTS node_state (
    node_name TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'unknown',
    reason TEXT,
    changed_by TEXT,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 自動修復ログ（self_healer, auto_log.pyで使用）
CREATE TABLE IF NOT EXISTS auto_fix_log (
    id SERIAL PRIMARY KEY,
    fix_type TEXT,
    error_type TEXT NOT NULL,
    error_detail TEXT,
    fix_strategy TEXT,
    fix_result TEXT,
    files_modified JSONB,
    detail TEXT,
    strategy TEXT,
    result TEXT,
    files_affected JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_node ON tasks(assigned_node);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_intel_items_source ON intel_items(source);
CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_browser_action_log_node ON browser_action_log(node);
CREATE INDEX IF NOT EXISTS idx_loop_guard_events_goal ON loop_guard_events(goal_id);
CREATE INDEX IF NOT EXISTS idx_event_log_severity ON event_log(severity);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_event_log_source_node ON event_log(source_node);
CREATE INDEX IF NOT EXISTS idx_llm_cost_log_recorded_at ON llm_cost_log(recorded_at);
CREATE INDEX IF NOT EXISTS idx_llm_cost_log_goal_id ON llm_cost_log(goal_id);
CREATE INDEX IF NOT EXISTS idx_auto_fix_log_created_at ON auto_fix_log(created_at);
CREATE INDEX IF NOT EXISTS idx_brain_handoff_status ON brain_handoff(status);

-- ===== Brain-α テーブル群（V27追加） =====

-- persona_memory（Brain-α長期記憶）
CREATE TABLE IF NOT EXISTS persona_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    context TEXT,
    content TEXT NOT NULL,
    reasoning TEXT,
    emotion TEXT,
    source TEXT,
    session_id TEXT,
    priority_tier INTEGER DEFAULT 3,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_persona_memory_category ON persona_memory(category);

-- brain_alpha_session
CREATE TABLE IF NOT EXISTS brain_alpha_session (
    session_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    summary TEXT,
    key_decisions JSONB,
    unresolved_issues JSONB,
    next_session_context JSONB,
    daichi_interactions INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- daichi_dialogue_log
CREATE TABLE IF NOT EXISTS daichi_dialogue_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    user_message TEXT,
    alpha_response TEXT,
    philosophy_extracted JSONB,
    importance REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- agent_reasoning_trace
CREATE TABLE IF NOT EXISTS agent_reasoning_trace (
    id SERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    action TEXT,
    reasoning TEXT,
    confidence REAL,
    context JSONB,
    task_id TEXT,
    goal_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_reasoning_trace_agent ON agent_reasoning_trace(agent_name);

-- brain_alpha_reasoning
CREATE TABLE IF NOT EXISTS brain_alpha_reasoning (
    id SERIAL PRIMARY KEY,
    category TEXT,
    action TEXT,
    reasoning TEXT,
    decision TEXT,
    confidence REAL,
    evidence JSONB,
    report_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- brain_cross_evaluation
CREATE TABLE IF NOT EXISTS brain_cross_evaluation (
    id SERIAL PRIMARY KEY,
    evaluator TEXT,
    target_agent TEXT,
    evaluation_type TEXT,
    score REAL,
    feedback TEXT,
    recommendations JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- posting_queue（SNS投稿キュー）
CREATE TABLE IF NOT EXISTS posting_queue (
    id SERIAL PRIMARY KEY,
    platform TEXT NOT NULL,
    account TEXT,
    content TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ,
    status TEXT DEFAULT 'pending',
    quality_score REAL,
    theme_category TEXT,
    post_url TEXT,
    affiliate_url TEXT,
    engagement_data JSONB,
    error_message TEXT,
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_posting_queue_status ON posting_queue(status);
CREATE INDEX IF NOT EXISTS idx_posting_queue_scheduled ON posting_queue(scheduled_at);

-- claude_code_queue（Brain-αへの指示キュー）
CREATE TABLE IF NOT EXISTS claude_code_queue (
    id SERIAL PRIMARY KEY,
    category TEXT,
    description TEXT,
    priority TEXT DEFAULT 'normal',
    source_agent TEXT,
    context TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- discord_chat_history
CREATE TABLE IF NOT EXISTS discord_chat_history (
    id SERIAL PRIMARY KEY,
    channel_id TEXT,
    user_id TEXT,
    user_name TEXT,
    message TEXT,
    response TEXT,
    model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- posting_queue_engagement
CREATE TABLE IF NOT EXISTS posting_queue_engagement (
    id SERIAL PRIMARY KEY,
    posting_queue_id INTEGER,
    likes INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    checked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_posting_queue_engagement_posting_id ON posting_queue_engagement(posting_queue_id);
CREATE INDEX IF NOT EXISTS idx_posting_queue_engagement_checked_at ON posting_queue_engagement(checked_at);

-- Blueskyフォロー追跡（フォローバック率計測 + 非相互アンフォロー）
CREATE TABLE IF NOT EXISTS bluesky_follow_tracking (
    id SERIAL PRIMARY KEY,
    did TEXT NOT NULL UNIQUE,
    handle TEXT,
    source TEXT,
    followed_at TIMESTAMPTZ DEFAULT NOW(),
    followback_checked_at TIMESTAMPTZ,
    is_followback BOOLEAN DEFAULT FALSE,
    unfollowed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bluesky_follow_tracking_followed_at ON bluesky_follow_tracking(followed_at);
CREATE INDEX IF NOT EXISTS idx_bluesky_follow_tracking_unfollowed_at ON bluesky_follow_tracking(unfollowed_at);
CREATE INDEX IF NOT EXISTS idx_bluesky_follow_tracking_is_followback ON bluesky_follow_tracking(is_followback);

-- コマース取引ログ（日次サマリー・executive_briefing用）
CREATE TABLE IF NOT EXISTS commerce_transactions (
    id SERIAL PRIMARY KEY,
    platform TEXT,
    product_id TEXT,
    amount_jpy INTEGER DEFAULT 0,
    revenue_jpy INTEGER DEFAULT 0,
    currency TEXT DEFAULT 'JPY',
    status TEXT DEFAULT 'completed',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_commerce_transactions_created_at ON commerce_transactions(created_at);

-- セマンティックキャッシュ（LLM応答キャッシュ、API呼び出し30-50%削減）
CREATE TABLE IF NOT EXISTS semantic_cache (
    id SERIAL PRIMARY KEY,
    prompt_hash TEXT NOT NULL UNIQUE,
    prompt_text TEXT,
    system_prompt_hash TEXT DEFAULT '',
    model TEXT,
    response_text TEXT NOT NULL,
    embedding vector(1024),
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_hash ON semantic_cache(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_expires ON semantic_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_sys_hash ON semantic_cache(system_prompt_hash);

-- 失敗記憶（Harness Engineering: 同じ失敗を二度と繰り返さない）
CREATE TABLE IF NOT EXISTS failure_memory (
    id SERIAL PRIMARY KEY,
    failure_type TEXT NOT NULL,
    task_type TEXT,
    error_message TEXT NOT NULL,
    root_cause TEXT,
    prevention_rule TEXT,
    context JSONB,
    occurrence_count INTEGER DEFAULT 1,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    resolved BOOLEAN DEFAULT FALSE,
    embedding vector(1024)
);
CREATE INDEX IF NOT EXISTS idx_failure_memory_type ON failure_memory(failure_type);
CREATE INDEX IF NOT EXISTS idx_failure_memory_resolved ON failure_memory(resolved);
CREATE INDEX IF NOT EXISTS idx_failure_memory_last_seen ON failure_memory(last_seen);

-- A2A APIクレジット（x402 payment foundation）
CREATE TABLE IF NOT EXISTS api_credits (
    api_key TEXT PRIMARY KEY,
    credits_remaining REAL DEFAULT 0,
    total_spent REAL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used TIMESTAMPTZ
);

-- エピソード記憶（MemRL: 成功+失敗をQ値ベースで学習）
CREATE TABLE IF NOT EXISTS episodic_memory (
    id SERIAL PRIMARY KEY,
    task_type TEXT,
    description TEXT,
    outcome TEXT CHECK (outcome IN ('success', 'failure', 'partial')),
    lessons TEXT,
    context JSONB,
    quality_score REAL,
    q_value REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_task_type ON episodic_memory(task_type);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_outcome ON episodic_memory(outcome);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_q_value ON episodic_memory(q_value DESC);

-- スキル（エピソード記憶から抽出された再利用可能パターン）
CREATE TABLE IF NOT EXISTS skills (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    rule TEXT NOT NULL,
    source_episode_ids JSONB DEFAULT '[]',
    task_types JSONB DEFAULT '[]',
    success_count INTEGER DEFAULT 0,
    total_usage INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skills_task_types ON skills USING GIN (task_types);
CREATE INDEX IF NOT EXISTS idx_skills_confidence ON skills(confidence DESC);
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
            # マイグレーション: 既存テーブルに不足カラムを追加
            migrations = [
                "ALTER TABLE intel_items ADD COLUMN IF NOT EXISTS review_flag TEXT DEFAULT 'pending_review'",
                "ALTER TABLE intel_items ADD COLUMN IF NOT EXISTS metadata JSONB",
                "ALTER TABLE goal_packets ADD COLUMN IF NOT EXISTS progress_log JSONB DEFAULT '[]'",
                # product_packages: note自動公開用カラム追加
                "ALTER TABLE product_packages ADD COLUMN IF NOT EXISTS publish_url TEXT",
                "ALTER TABLE product_packages ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
                # posting_queue: アフィリエイトURL追跡用
                "ALTER TABLE posting_queue ADD COLUMN IF NOT EXISTS affiliate_url TEXT",
                "ALTER TABLE posting_queue ADD COLUMN IF NOT EXISTS engagement_data JSONB",
                # posting_queue: A/Bテスト用カラム
                "ALTER TABLE posting_queue ADD COLUMN IF NOT EXISTS ab_test_id TEXT",
                "ALTER TABLE posting_queue ADD COLUMN IF NOT EXISTS ab_variant TEXT",
                # feature_flags テーブル (エンゲージメント調整等)
                """CREATE TABLE IF NOT EXISTS feature_flags (
                    flag_name TEXT PRIMARY KEY,
                    flag_value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )""",
                # persona_memory: Claude Constitution優先度階層（1=absolute〜5=optional）
                "ALTER TABLE persona_memory ADD COLUMN IF NOT EXISTS priority_tier INTEGER DEFAULT 3",
                # semantic_cache: 旧スキーマからのマイグレーション（ベクトル検索対応）
                "ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS embedding vector(1024)",
                "ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS system_prompt_hash TEXT DEFAULT ''",
                "ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS prompt_text TEXT",
                "ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS response_text TEXT",
                # 旧カラム名 response → response_text へのデータ移行
                "UPDATE semantic_cache SET response_text = response WHERE response_text IS NULL AND response IS NOT NULL",
            ]
            for sql in migrations:
                try:
                    await conn.execute(sql)
                except Exception:
                    pass  # カラムが既に存在する場合は無視

            # persona_memory: カテゴリ別 priority_tier を設定
            tier_mapping = {
                "taboo": 1,        # absolute — 絶対に違反しない
                "correction": 2,   # high — ユーザーの修正指示
                "philosophy": 2,   # high — 核心的価値観
                "identity": 2,     # high — アイデンティティ
                "judgment": 3,     # medium — 判断基準
                "emotion": 4,      # low — 感情記録
                "preference": 4,   # low — 嗜好
            }
            for cat, tier in tier_mapping.items():
                try:
                    await conn.execute(
                        "UPDATE persona_memory SET priority_tier = $1 WHERE category = $2 AND priority_tier != $1",
                        tier, cat,
                    )
                except Exception:
                    pass
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
