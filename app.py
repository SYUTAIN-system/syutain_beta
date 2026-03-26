"""
SYUTAINβ FastAPI バックエンド — Step 12
設計書 第4章準拠

ALPHA上で動作するメインAPIサーバー
- SSE対応リアルタイムイベントストリーム
- JWT認証
- CORS（Next.jsフロントエンド連携）
- PostgreSQL + NATS 接続管理
"""

import io
import os
import json
import uuid
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

import asyncpg
import jwt
from fastapi import FastAPI, HTTPException, Depends, Request, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from tools.db_init import init_postgresql, init_sqlite_local
from tools.nats_client import init_nats_and_streams, get_nats_client
from agents.os_kernel import get_os_kernel
from agents.proposal_engine import get_proposal_engine
from agents.approval_manager import get_approval_manager
from agents.chat_agent import get_chat_agent
from tools.discord_notify import notify_discord, notify_goal_accepted

load_dotenv()

logger = logging.getLogger("syutain.app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ===== 設定（.envから読み込み、ハードコードしない）=====
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")
if not APP_SECRET_KEY:
    raise RuntimeError("APP_SECRET_KEY が .env に設定されていません。起動を中止します。")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
THIS_NODE = os.getenv("THIS_NODE", "alpha")

# SSEイベントキュー（インメモリ、複数クライアント向け）
_sse_subscribers: list[asyncio.Queue] = []


# ===== Pydantic モデル =====

class LoginRequest(BaseModel):
    password: str

class ChatSendRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class GoalCreateRequest(BaseModel):
    raw_goal: str
    priority: str = "medium"

class ApprovalResponse(BaseModel):
    approved: bool
    reason: str = ""

class ProposalActionRequest(BaseModel):
    reason: str = ""

class BudgetSettingsRequest(BaseModel):
    daily_budget_jpy: Optional[float] = None
    monthly_budget_jpy: Optional[float] = None
    chat_budget_jpy: Optional[float] = None

class ChatModelRequest(BaseModel):
    mode: str  # "auto" | "local" | "deepseek" | "gemini" | "claude"

class DiscordSettingsRequest(BaseModel):
    goal_accepted: Optional[bool] = None
    task_completed: Optional[bool] = None
    error_alert: Optional[bool] = None
    node_status: Optional[bool] = None
    proposal_created: Optional[bool] = None

class CharlieModeRequest(BaseModel):
    mode: str  # "win11" | "ubuntu"


# ===== JWT認証 =====

def create_jwt_token(data: dict) -> str:
    """JWTトークンを生成"""
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {**data, "exp": expire}
    return jwt.encode(payload, APP_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> dict:
    """JWTトークンを検証"""
    try:
        return jwt.decode(token, APP_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="トークン期限切れ")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="無効なトークン")


async def get_current_user(request: Request) -> dict:
    """リクエストからJWTトークンを取得・検証"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証が必要です")
    token = auth_header[7:]
    return verify_jwt_token(token)


# ===== SSE ヘルパー =====

async def broadcast_sse_event(event_type: str, data: dict):
    """全SSEサブスクライバにイベントをブロードキャスト"""
    message = {
        "event": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    disconnected = []
    for i, queue in enumerate(_sse_subscribers):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            disconnected.append(i)
    # 溢れたキューを除去
    for i in reversed(disconnected):
        _sse_subscribers.pop(i)


# ===== ノードメトリクスキャッシュ（NATSハートビートから更新）=====

_node_metrics: dict[str, dict] = {
    "alpha": {"status": "alive", "cpu_percent": 0, "memory_percent": 0, "last_heartbeat": 0},
    "bravo": {"status": "unknown", "cpu_percent": 0, "memory_percent": 0, "last_heartbeat": 0},
    "charlie": {"status": "unknown", "cpu_percent": 0, "memory_percent": 0, "last_heartbeat": 0},
    "delta": {"status": "unknown", "cpu_percent": 0, "memory_percent": 0, "last_heartbeat": 0},
}
# CHARLIE offline理由（"win11" | "unreachable" | None）
_charlie_offline_reason: Optional[str] = None


async def _heartbeat_listener(msg):
    """NATSハートビートを受信してメトリクスキャッシュを更新"""
    global _charlie_offline_reason
    try:
        data = json.loads(msg.data.decode())
        node = data.get("node", "")
        if node in _node_metrics:
            was_offline = _node_metrics[node].get("status") != "alive"
            _node_metrics[node] = {
                "status": "alive",
                "cpu_percent": data.get("cpu_percent", 0),
                "memory_percent": data.get("memory_percent", 0),
                "agents": data.get("agents", []),
                "timestamp": data.get("timestamp", ""),
                "last_heartbeat": time.time(),
            }
            # ノード復帰検知
            if was_offline and node == "charlie":
                _charlie_offline_reason = None
                logger.info("CHARLIE オンライン復帰検知")
                asyncio.create_task(_notify_node_online("charlie"))
            elif was_offline and node in ("bravo", "delta"):
                logger.info(f"{node.upper()} オンライン復帰検知")
    except Exception:
        pass


async def _notify_node_online(node: str):
    """ノード復帰時のDiscord通知とSSE"""
    try:
        from tools.discord_notify import notify_discord
        await notify_discord(f"CHARLIE オンライン復帰。4ノードで運転再開")
    except Exception as e:
        logger.warning(f"Discord復帰通知失敗: {e}")
    await broadcast_sse_event("node_status", {"node": node, "status": "online"})


async def _notify_node_offline(node: str, reason: str):
    """ノードオフライン時のDiscord通知・タスク再割当・SSE"""
    try:
        from tools.discord_notify import notify_discord
        if reason == "win11":
            msg = "CHARLIE オフライン（Win11切替）。BRAVO/DELTA/ALPHAの3ノードで運転継続中"
        else:
            msg = f"{node.upper()} オフライン。残存ノードで運転継続中"
        await notify_discord(msg)
    except Exception as e:
        logger.warning(f"Discordオフライン通知失敗: {e}")

    # CHARLIEに割り当て済みの未完了タスクをBRAVO/DELTAに再割当
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM tasks WHERE assigned_node = $1 AND status IN ('pending', 'running')",
                node,
            )
            for row in rows:
                new_node = "bravo"  # 主力フォールバック
                await conn.execute(
                    "UPDATE tasks SET assigned_node = $1, updated_at = NOW() WHERE id = $2",
                    new_node, row["id"],
                )
            if rows:
                logger.info(f"{len(rows)}件のタスクを{node}からbravoに再割当")
    except Exception as e:
        logger.error(f"タスク再割当失敗: {e}")

    await broadcast_sse_event("node_status", {"node": node, "status": "offline", "reason": reason})


# ===== PostgreSQL接続プール =====

_pg_pool: Optional[asyncpg.Pool] = None


async def get_pg_pool() -> asyncpg.Pool:
    """PostgreSQL接続プールを取得"""
    global _pg_pool
    if _pg_pool is None:
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://localhost:5432/syutain_beta"
        )
        try:
            _pg_pool = await asyncpg.create_pool(
                database_url, min_size=2, max_size=10
            )
        except Exception as e:
            logger.error(f"PostgreSQL接続プール作成エラー: {e}")
            raise HTTPException(status_code=503, detail="データベース接続エラー")
    return _pg_pool


async def _save_chat_message(session_id: str, role: str, content: str, metadata: dict = None):
    """チャットメッセージをPostgreSQLに保存"""
    try:
        pool = await get_pg_pool()
        await pool.execute(
            "INSERT INTO chat_messages (session_id, role, content, metadata) VALUES ($1, $2, $3, $4)",
            session_id, role, content, json.dumps(metadata) if metadata else None,
        )
    except Exception as e:
        logger.warning(f"チャットメッセージ保存失敗: {e}")


# ===== Lifespan（起動/終了処理）=====

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPIライフスパン: 起動時にDB・NATS初期化、終了時にクリーンアップ"""
    logger.info("SYUTAINβ FastAPI 起動開始...")

    # グローバルDB接続プール初期化
    try:
        from tools.db_pool import init_pool as _init_db_pool
        await _init_db_pool(min_size=2, max_size=10)
    except Exception as e:
        logger.error(f"DB接続プール初期化エラー: {e}")

    # PostgreSQL初期化
    try:
        pg_ok = await init_postgresql()
        if pg_ok:
            logger.info("PostgreSQL初期化完了")
        else:
            logger.warning("PostgreSQL初期化失敗（サービスは継続）")
    except Exception as e:
        logger.error(f"PostgreSQL初期化エラー: {e}")

    # SQLiteローカル初期化
    try:
        init_sqlite_local(THIS_NODE)
    except Exception as e:
        logger.error(f"SQLite初期化エラー: {e}")

    # NATS + JetStream初期化
    try:
        nats_ok = await init_nats_and_streams()
        if nats_ok:
            logger.info("NATS + JetStream初期化完了")
        else:
            logger.warning("NATS初期化失敗（HTTPフォールバックで継続）")
    except Exception as e:
        logger.error(f"NATS初期化エラー: {e}")

    # エージェント初期化
    try:
        await get_proposal_engine()
        await get_approval_manager()
        await get_chat_agent()
        logger.info("エージェント初期化完了")
    except Exception as e:
        logger.error(f"エージェント初期化エラー: {e}")

    # NATSハートビートリスナー開始
    try:
        nats_client = await get_nats_client()
        if nats_client and nats_client.nc and not nats_client.nc.is_closed:
            await nats_client.nc.subscribe("agent.heartbeat.>", cb=_heartbeat_listener)
            logger.info("NATSハートビートリスナー開始")
    except Exception as e:
        logger.error(f"ハートビートリスナー開始エラー: {e}")

    # task.createサブスクライバ → os_kernel 5段階自律ループ起動
    try:
        nats_client = await get_nats_client()
        if nats_client and nats_client.nc and not nats_client.nc.is_closed:
            async def _task_create_handler(msg):
                try:
                    data = json.loads(msg.data.decode())
                    goal_id = data.get("goal_id")
                    if not goal_id:
                        return
                    # goal_packetsからraw_goalを取得
                    pool = await get_pg_pool()
                    raw_goal = ""
                    if pool:
                        async with pool.acquire() as conn:
                            row = await conn.fetchrow(
                                "SELECT raw_goal FROM goal_packets WHERE goal_id = $1",
                                goal_id,
                            )
                            if row:
                                raw_goal = row["raw_goal"] or ""
                    if not raw_goal:
                        logger.warning(f"task.create: goal_id={goal_id} のraw_goalが空")
                        return
                    # os_kernelの5段階ループを非同期タスクで起動
                    kernel = get_os_kernel()
                    asyncio.create_task(kernel.execute_goal(raw_goal))
                    logger.info(f"5段階自律ループ起動: goal_id={goal_id}")
                except Exception as e:
                    logger.error(f"task.createハンドラエラー: {e}")

            await nats_client.nc.subscribe("task.create", cb=_task_create_handler)
            logger.info("task.createサブスクライバ開始")
    except Exception as e:
        logger.error(f"task.createサブスクライバ開始エラー: {e}")

    # charlie.going_offlineサブスクライバ（CHARLIE安全シャットダウン通知）
    try:
        nats_client = await get_nats_client()
        if nats_client and nats_client.nc and not nats_client.nc.is_closed:
            async def _charlie_offline_handler(msg):
                global _charlie_offline_reason
                try:
                    _charlie_offline_reason = "win11"
                    _node_metrics["charlie"]["status"] = "offline"
                    logger.info("CHARLIE安全シャットダウン通知受信（Win11切替）")
                    await _notify_node_offline("charlie", "win11")
                except Exception as e:
                    logger.error(f"charlieオフラインハンドラエラー: {e}")

            await nats_client.nc.subscribe("charlie.going_offline", cb=_charlie_offline_handler)
            logger.info("charlie.going_offlineサブスクライバ開始")
    except Exception as e:
        logger.error(f"charlie.going_offlineサブスクライバ開始エラー: {e}")

    # ALPHAメトリクス更新 + ノードハートビートタイムアウト検知
    import psutil
    async def _update_alpha_metrics():
        global _charlie_offline_reason
        while True:
            try:
                _node_metrics["alpha"]["cpu_percent"] = psutil.cpu_percent()
                _node_metrics["alpha"]["memory_percent"] = psutil.virtual_memory().percent
                _node_metrics["alpha"]["last_heartbeat"] = time.time()

                # ハートビートタイムアウト検知（60秒）
                now = time.time()
                for node in ("bravo", "charlie", "delta"):
                    last_hb = _node_metrics[node].get("last_heartbeat", 0)
                    was_alive = _node_metrics[node].get("status") == "alive"
                    if last_hb > 0 and (now - last_hb) > 60 and was_alive:
                        _node_metrics[node]["status"] = "offline"
                        reason = "win11" if node == "charlie" else "unreachable"
                        if node == "charlie":
                            _charlie_offline_reason = _charlie_offline_reason or "unreachable"
                            reason = _charlie_offline_reason
                        logger.warning(f"{node.upper()} ハートビートタイムアウト（60秒）")
                        asyncio.create_task(_notify_node_offline(node, reason))
            except Exception:
                pass
            await asyncio.sleep(10)
    asyncio.create_task(_update_alpha_metrics())

    logger.info("SYUTAINβ FastAPI 起動完了")

    yield  # アプリケーション稼働中

    # シャットダウン処理
    logger.info("SYUTAINβ FastAPI シャットダウン開始...")

    # エージェントクリーンアップ
    try:
        engine = await get_proposal_engine()
        await engine.close()
    except Exception:
        pass
    try:
        manager = await get_approval_manager()
        await manager.close()
    except Exception:
        pass
    try:
        agent = await get_chat_agent()
        await agent.close()
    except Exception:
        pass

    # NATS切断
    try:
        nats_client = await get_nats_client()
        await nats_client.close()
    except Exception:
        pass

    # PostgreSQLプール終了
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None

    # グローバルDB接続プール終了
    try:
        from tools.db_pool import close_pool as _close_db_pool
        await _close_db_pool()
    except Exception:
        pass

    logger.info("SYUTAINβ FastAPI シャットダウン完了")


# ===== FastAPIアプリケーション =====

app = FastAPI(
    title="SYUTAINβ API",
    description="自律分散型事業OS — FastAPIバックエンド",
    version="25.0.0",
    lifespan=lifespan,
)

# CORS設定（許可オリジンを限定 — Tailscale VPN内のみ）
_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://localhost:8443",
    "https://100.70.34.67:8443",
]
# .envで追加オリジンを設定可能
_extra = os.getenv("CORS_EXTRA_ORIGINS", "")
if _extra:
    _CORS_ORIGINS.extend(o.strip() for o in _extra.split(",") if o.strip())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== 認証エンドポイント =====

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """パスワードでログインしJWTトークンを取得"""
    if not APP_PASSWORD:
        raise HTTPException(status_code=500, detail="APP_PASSWORDが設定されていません")
    if req.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")
    token = create_jwt_token({"user": "shimabara", "role": "owner"})
    return {"token": token, "expires_in_hours": JWT_EXPIRE_HOURS}


# ===== ヘルスチェック =====

@app.get("/health")
async def health_check():
    """システムヘルスチェック（認証不要）"""
    health = {
        "status": "ok",
        "node": THIS_NODE,
        "version": "25.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {},
    }

    # PostgreSQL接続確認
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        health["services"]["postgresql"] = "ok"
    except Exception:
        health["services"]["postgresql"] = "error"
        health["status"] = "degraded"

    # NATS接続確認
    try:
        nats_client = await get_nats_client()
        if nats_client.nc and not nats_client.nc.is_closed:
            health["services"]["nats"] = "ok"
        else:
            health["services"]["nats"] = "disconnected"
            health["status"] = "degraded"
    except Exception:
        health["services"]["nats"] = "error"
        health["status"] = "degraded"

    return health


# ===== ダッシュボード =====

@app.get("/api/dashboard")
async def get_dashboard(user: dict = Depends(get_current_user)):
    """ダッシュボードデータを取得"""
    dashboard = {
        "node": THIS_NODE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_goals": 0,
        "pending_tasks": 0,
        "running_tasks": 0,
        "completed_tasks_today": 0,
        "pending_approvals": 0,
        "recent_proposals": [],
    }

    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            dashboard["active_goals"] = await conn.fetchval(
                "SELECT COUNT(*) FROM goal_packets WHERE status = 'active'"
            ) or 0
            dashboard["pending_tasks"] = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
            ) or 0
            dashboard["running_tasks"] = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE status = 'running'"
            ) or 0
            dashboard["completed_tasks_today"] = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('success', 'completed') AND updated_at > NOW() - INTERVAL '1 day'"
            ) or 0
            dashboard["pending_approvals"] = await conn.fetchval(
                "SELECT COUNT(*) FROM approval_queue WHERE status = 'pending'"
            ) or 0

            # 最新の提案5件
            rows = await conn.fetch(
                """
                SELECT proposal_id, title, score, adopted, created_at
                FROM proposal_history
                ORDER BY created_at DESC LIMIT 5
                """
            )
            dashboard["recent_proposals"] = [
                {
                    **dict(r),
                    "status": "approved" if r["adopted"] is True
                              else "rejected" if r["adopted"] is False
                              else "pending",
                }
                for r in rows
            ]

            # 最近の成果物（各ゴールの最終タスクのみ、最新5件）
            artifact_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (goal_id)
                       id, type, status, assigned_node, model_used,
                       cost_jpy, output_data, updated_at, goal_id
                FROM tasks
                WHERE status IN ('success', 'completed', 'complete')
                  AND output_data IS NOT NULL
                  AND goal_id IS NOT NULL
                ORDER BY goal_id, updated_at DESC
                """
            )
            # goal_idごとに最終タスクだけ取得済み、更新日時で降順ソートして5件
            artifact_rows = sorted(artifact_rows, key=lambda r: r["updated_at"] or datetime.min, reverse=True)[:5]
            artifacts = []
            for ar in artifact_rows:
                output_text = ""
                try:
                    od = ar["output_data"]
                    if isinstance(od, str):
                        parsed = json.loads(od)
                        output_text = parsed.get("text", parsed.get("content", parsed.get("message", od[:200])))
                    elif isinstance(od, dict):
                        output_text = od.get("text", od.get("content", json.dumps(od)[:200]))
                    else:
                        output_text = str(od)[:200]
                except Exception:
                    output_text = str(ar["output_data"])[:200] if ar["output_data"] else ""
                artifacts.append({
                    "task_id": ar["id"],
                    "type": ar["type"],
                    "status": ar["status"],
                    "assigned_node": ar["assigned_node"],
                    "model_used": ar["model_used"],
                    "cost_jpy": float(ar["cost_jpy"]) if ar["cost_jpy"] else 0,
                    "output_preview": str(output_text)[:200],
                    "completed_at": ar["updated_at"].isoformat() if ar["updated_at"] else None,
                })
            dashboard["recent_artifacts"] = artifacts

    except Exception as e:
        logger.error(f"ダッシュボードデータ取得エラー: {e}")

    return dashboard


# ===== タスク =====

@app.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """タスク一覧を取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT id, goal_id, type, status, assigned_node,
                           model_used, tier, cost_jpy, quality_score,
                           output_data, artifacts,
                           created_at, updated_at
                    FROM tasks
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    status, limit, offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, goal_id, type, status, assigned_node,
                           model_used, tier, cost_jpy, quality_score,
                           output_data, artifacts,
                           created_at, updated_at
                    FROM tasks
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit, offset,
                )
            return {"tasks": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"タスク取得エラー: {e}")
        raise HTTPException(status_code=500, detail="タスク取得エラー")


# ===== タスク詳細 =====

@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str, user: dict = Depends(get_current_user)):
    """タスクの詳細と成果物を返す"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, goal_id, type, status, assigned_node,
                       model_used, tier, cost_jpy, quality_score,
                       input_data, output_data, artifacts,
                       created_at, updated_at
                FROM tasks WHERE id = $1
                """,
                task_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Task not found")
            result = dict(row)
            # datetime を文字列に変換
            for key in ("created_at", "updated_at"):
                if result.get(key):
                    result[key] = result[key].isoformat()
            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"タスク詳細取得エラー: {e}")
        raise HTTPException(status_code=500, detail="タスク詳細取得エラー")


# ===== 成果物 =====

# 商品化可能なタスクタイプ（内部分析・調査・SNS投稿・モニタリングは除外）
PUBLISHABLE_TASK_TYPES = ["content", "drafting", "review", "coding", "analysis", "note_article", "booth_product", "x_thread"]


@app.get("/api/artifacts")
async def get_artifacts(
    type: Optional[str] = None,
    quality_min: float = Query(default=0.0, ge=0.0, le=1.0),
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, le=100),
    search: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """商品化可能な成果物の一覧（内部処理結果は除外）"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # フィルタ構築
            types_filter = [type] if type and type in PUBLISHABLE_TASK_TYPES else PUBLISHABLE_TASK_TYPES
            conditions = ["type = ANY($1::text[])", "output_data IS NOT NULL", "status IN ('completed','success')"]
            params: list = [types_filter]
            idx = 2

            if quality_min > 0:
                conditions.append(f"quality_score >= ${idx}")
                params.append(quality_min)
                idx += 1

            if search:
                conditions.append(f"output_data::text ILIKE '%' || ${idx} || '%'")
                params.append(search)
                idx += 1

            where = " AND ".join(conditions)
            order = {
                "newest": "created_at DESC",
                "oldest": "created_at ASC",
                "quality_desc": "quality_score DESC NULLS LAST",
                "quality_asc": "quality_score ASC NULLS LAST",
            }.get(sort, "created_at DESC")

            # 総件数
            total = await conn.fetchval(f"SELECT COUNT(*) FROM tasks WHERE {where}", *params)

            # データ取得
            offset = (page - 1) * per_page
            rows = await conn.fetch(
                f"""SELECT id, type, quality_score, model_used, assigned_node, cost_jpy,
                           output_data, created_at
                    FROM tasks WHERE {where}
                    ORDER BY {order}
                    LIMIT ${idx} OFFSET ${idx + 1}""",
                *params, per_page, offset,
            )

            items = []
            for r in rows:
                od = r["output_data"]
                text = ""
                title = ""
                if isinstance(od, dict):
                    text = od.get("text", "") or od.get("content", "") or ""
                    title = od.get("title", "") or text[:50]
                elif isinstance(od, str):
                    text = od
                    title = text[:50]
                else:
                    text = str(od) if od else ""
                    title = text[:50]

                items.append({
                    "id": r["id"],
                    "type": r["type"],
                    "title": title.strip().split("\n")[0][:80] if title else r["type"],
                    "content_preview": text[:200] if text else "",
                    "quality_score": float(r["quality_score"]) if r["quality_score"] else None,
                    "model": r["model_used"],
                    "node": r["assigned_node"],
                    "cost_jpy": float(r["cost_jpy"]) if r["cost_jpy"] else 0,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "word_count": len(text),
                })

            return {
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page if total else 0,
                "publishable_types": PUBLISHABLE_TASK_TYPES,
            }
    except Exception as e:
        logger.error(f"成果物一覧エラー: {e}")
        raise HTTPException(status_code=500, detail="成果物一覧取得エラー")


@app.get("/api/artifacts/stats")
async def get_artifact_stats(user: dict = Depends(get_current_user)):
    """成果物の統計サマリー"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT
                    COUNT(*) as total,
                    ROUND(AVG(quality_score)::numeric, 2) as avg_quality,
                    ROUND(SUM(cost_jpy)::numeric, 2) as total_cost,
                    COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) as today_count,
                    COUNT(*) FILTER (WHERE quality_score >= 0.65) as high_quality,
                    COUNT(*) FILTER (WHERE quality_score >= 0.50 AND quality_score < 0.65) as medium_quality,
                    COUNT(*) FILTER (WHERE quality_score < 0.50 OR quality_score IS NULL) as low_quality
                FROM tasks
                WHERE type = ANY($1::text[])
                AND output_data IS NOT NULL
                AND status IN ('completed','success')""",
                PUBLISHABLE_TASK_TYPES,
            )
            # タイプ別件数
            type_rows = await conn.fetch(
                """SELECT type, COUNT(*) as count
                FROM tasks
                WHERE type = ANY($1::text[]) AND output_data IS NOT NULL AND status IN ('completed','success')
                GROUP BY type ORDER BY count DESC""",
                PUBLISHABLE_TASK_TYPES,
            )
            return {
                "total": row["total"] or 0,
                "avg_quality": float(row["avg_quality"]) if row["avg_quality"] else 0,
                "total_cost_jpy": float(row["total_cost"]) if row["total_cost"] else 0,
                "today_count": row["today_count"] or 0,
                "by_quality": {
                    "high": row["high_quality"] or 0,
                    "medium": row["medium_quality"] or 0,
                    "low": row["low_quality"] or 0,
                },
                "by_type": {r["type"]: r["count"] for r in type_rows},
                "publishable_types": PUBLISHABLE_TASK_TYPES,
            }
    except Exception as e:
        logger.error(f"成果物統計エラー: {e}")
        raise HTTPException(status_code=500, detail="成果物統計エラー")


# ===== 成果物ダウンロード =====

@app.get("/api/artifacts/{task_id}/download")
async def download_artifact(task_id: str, user: dict = Depends(get_current_user)):
    """成果物をファイルとしてダウンロード"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, type, output_data, created_at FROM tasks WHERE id = $1",
                task_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Task not found")

            task_type = row["type"] or "task"
            task_id_short = task_id[:8]
            created_at = row["created_at"]
            date_str = created_at.strftime("%Y%m%d") if created_at else "unknown"
            filename = f"{task_type}_{task_id_short}_{date_str}.md"

            output_data = row["output_data"]

            # output_data が文字列の場合はJSONパースを試みる
            if isinstance(output_data, str):
                try:
                    output_data = json.loads(output_data)
                except (json.JSONDecodeError, TypeError):
                    pass

            # file_path キーがあればそのファイルを返す
            if isinstance(output_data, dict) and output_data.get("file_path"):
                file_path = output_data["file_path"]
                if os.path.isfile(file_path):
                    return FileResponse(
                        path=file_path,
                        filename=os.path.basename(file_path),
                        media_type="application/octet-stream",
                    )

            # テキスト/JSONの場合はMarkdownを動的生成
            md_lines = [
                f"# {task_type} - {task_id_short}",
                f"",
                f"- **Task ID**: {task_id}",
                f"- **Type**: {task_type}",
                f"- **Created**: {created_at.isoformat() if created_at else 'N/A'}",
                f"",
                f"## Output",
                f"",
            ]
            if isinstance(output_data, dict):
                md_lines.append("```json")
                md_lines.append(json.dumps(output_data, ensure_ascii=False, indent=2))
                md_lines.append("```")
            elif output_data:
                md_lines.append(str(output_data))
            else:
                md_lines.append("(出力データなし)")

            content = "\n".join(md_lines)
            buffer = io.BytesIO(content.encode("utf-8"))

            return StreamingResponse(
                buffer,
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"成果物ダウンロードエラー: {e}")
        raise HTTPException(status_code=500, detail="成果物ダウンロードエラー")


@app.get("/api/goals/{goal_id}")
async def get_goal_detail(goal_id: str, user: dict = Depends(get_current_user)):
    """ゴールの詳細、紐づくタスク一覧、進捗を返す"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            goal = await conn.fetchrow(
                "SELECT * FROM goal_packets WHERE goal_id = $1",
                goal_id,
            )
            if not goal:
                raise HTTPException(status_code=404, detail="Goal not found")

            tasks = await conn.fetch(
                """
                SELECT id, type, status, assigned_node, model_used,
                       quality_score, cost_jpy, output_data,
                       created_at, updated_at
                FROM tasks WHERE goal_id = $1
                ORDER BY created_at
                """,
                goal_id,
            )

            goal_dict = dict(goal)
            for key in ("created_at", "completed_at"):
                if goal_dict.get(key):
                    goal_dict[key] = goal_dict[key].isoformat()

            task_list = []
            for t in tasks:
                td = dict(t)
                for key in ("created_at", "updated_at"):
                    if td.get(key):
                        td[key] = td[key].isoformat()
                task_list.append(td)

            return {
                "goal": goal_dict,
                "tasks": task_list,
                "summary": {
                    "total": len(task_list),
                    "completed": sum(
                        1 for t in task_list
                        if t["status"] in ("success", "completed", "complete")
                    ),
                    "pending": sum(1 for t in task_list if t["status"] == "pending"),
                    "running": sum(1 for t in task_list if t["status"] == "running"),
                    "failed": sum(
                        1 for t in task_list
                        if t["status"] in ("failure", "failed")
                    ),
                },
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ゴール詳細取得エラー: {e}")
        raise HTTPException(status_code=500, detail="ゴール詳細取得エラー")


# ===== 承認待ち（認証不要） =====

@app.get("/api/pending-approvals")
async def get_pending_approvals_public(
    status: str = Query(default="pending"),
    user: dict = Depends(get_current_user),
):
    """承認待ち一覧を取得（全タイプ対応: タスク承認、Bluesky投稿、SNS投稿等）"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # statusフィルタ: "pending", "all", "approved", "rejected" 等
            if status == "all":
                where_clause = "1=1"
                params = []
            else:
                where_clause = "aq.status = $1"
                params = [status]

            rows = await conn.fetch(
                f"""
                SELECT aq.id as approval_id, aq.request_type, aq.status,
                       aq.request_data, aq.requested_at, aq.responded_at, aq.response,
                       t.id as task_id, t.type as task_type, t.goal_id,
                       t.assigned_node, t.output_data
                FROM approval_queue aq
                LEFT JOIN tasks t ON t.id = (aq.request_data->>'task_id')
                WHERE {where_clause}
                ORDER BY aq.requested_at DESC
                LIMIT 50
                """,
                *params,
            )
            approvals = []
            for row in rows:
                raw = row["request_data"] or {}
                req_data = json.loads(raw) if isinstance(raw, str) else raw
                # タイプに応じた説明文を生成
                description = req_data.get("description", "")
                if not description:
                    if row["request_type"] == "bluesky_post":
                        description = req_data.get("content", "")[:200]
                    elif row["request_type"] == "sns_post":
                        platform = req_data.get("platform", "")
                        description = f"[{platform}] {req_data.get('content', '')[:200]}"
                    elif row["request_type"] == "task_approval":
                        description = req_data.get("task_type", "") or "タスク承認リクエスト"
                    else:
                        description = json.dumps(req_data, ensure_ascii=False)[:200]

                approvals.append({
                    "approval_id": row["approval_id"],
                    "request_type": row["request_type"],
                    "status": row["status"],
                    "task_id": req_data.get("task_id", ""),
                    "description": description,
                    "content": req_data.get("content", ""),
                    "task_type": row["task_type"],
                    "goal_id": row["goal_id"],
                    "assigned_node": row["assigned_node"],
                    "requested_at": row["requested_at"].isoformat() if row["requested_at"] else None,
                    "responded_at": row["responded_at"].isoformat() if row.get("responded_at") else None,
                    "response": row.get("response"),
                })
            return {"approvals": approvals}
    except Exception as e:
        logger.error(f"承認待ち取得エラー: {e}")
        return {"approvals": []}


@app.post("/api/pending-approvals/{approval_id}/respond")
async def respond_pending_approval(approval_id: int, body: ApprovalResponse, user: dict = Depends(get_current_user)):
    """承認リクエストに応答（認証必須 — Web UI用）"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # approval_queue更新
            await conn.execute(
                """
                UPDATE approval_queue SET status = $1, responded_at = NOW(), response = $2
                WHERE id = $3
                """,
                "approved" if body.approved else "rejected",
                body.reason or ("承認" if body.approved else "却下"),
                approval_id,
            )
            # 関連タスクのステータスも更新
            row = await conn.fetchrow(
                "SELECT request_data FROM approval_queue WHERE id = $1", approval_id
            )
            if row and row["request_data"]:
                rd = row["request_data"]
                rd = json.loads(rd) if isinstance(rd, str) else rd
                task_id = rd.get("task_id")
                if task_id:
                    # approval_requestタイプのタスクは承認で完了、それ以外はrunningに戻す
                    task_row = await conn.fetchrow(
                        "SELECT type FROM tasks WHERE id = $1", task_id
                    )
                    task_type = task_row["type"] if task_row else ""
                    if body.approved:
                        new_status = "completed" if task_type == "approval_request" else "running"
                    else:
                        new_status = "cancelled"
                    await conn.execute(
                        "UPDATE tasks SET status = $1, updated_at = NOW() WHERE id = $2",
                        new_status, task_id,
                    )
        # request_typeを取得（承認/却下共通で使用）
        req_type = ""
        try:
            async with pool.acquire() as conn_rt:
                request_type_row = await conn_rt.fetchrow(
                    "SELECT request_type FROM approval_queue WHERE id = $1", approval_id
                )
            req_type = request_type_row["request_type"] if request_type_row else ""
        except Exception:
            pass

        # 承認時: request_typeに応じて実際のアクションを実行
        if body.approved and row and row["request_data"]:
            rd = row["request_data"]
            rd = json.loads(rd) if isinstance(rd, str) else rd

            if req_type == "bluesky_post":
                # Bluesky投稿を実行
                content = rd.get("content", "")
                if content:
                    try:
                        from tools.social_tools import execute_approved_bluesky
                        result = await execute_approved_bluesky(content)
                        if result.get("success"):
                            logger.info(f"Bluesky承認済み投稿成功: {result.get('uri', '')}")
                        else:
                            logger.error(f"Bluesky承認済み投稿失敗: {result.get('reason', '')}")
                    except Exception as e:
                        logger.error(f"Bluesky投稿実行エラー: {e}")

            elif req_type == "x_post":
                # X投稿を実行
                content = rd.get("content", "")
                account = rd.get("account", "syutain")
                if content:
                    try:
                        from tools.social_tools import execute_approved_x
                        result = await execute_approved_x(content, account=account)
                        if result.get("success"):
                            logger.info(f"X承認済み投稿成功: {result.get('url', '')}")
                        else:
                            logger.error(f"X承認済み投稿失敗: {result.get('reason', '')}")
                    except Exception as e:
                        logger.error(f"X投稿実行エラー: {e}")

            elif req_type == "threads_post":
                # Threads投稿を実行
                content = rd.get("content", "")
                if content:
                    try:
                        from tools.social_tools import execute_approved_threads
                        result = await execute_approved_threads(content)
                        if result.get("success"):
                            logger.info(f"Threads承認済み投稿成功: {result.get('url', '')}")
                        else:
                            logger.error(f"Threads承認済み投稿失敗: {result.get('reason', '')}")
                    except Exception as e:
                        logger.error(f"Threads投稿実行エラー: {e}")

        # event_log記録
        try:
            from tools.event_logger import log_event
            await log_event(
                f"approval.{'approved' if body.approved else 'rejected'}", "approval",
                {
                    "approval_id": approval_id,
                    "request_type": req_type or "unknown",
                    "action": "approved" if body.approved else "rejected",
                    "reason": body.reason or "",
                },
                severity="info",
            )
        except Exception:
            pass

        # persona_memoryに判断パターンを蓄積（接続#15修正）
        try:
            pool_pm = await get_pg_pool()
            async with pool_pm.acquire() as conn_pm:
                rd_pm = row["request_data"] if row else {}
                if isinstance(rd_pm, str):
                    rd_pm = json.loads(rd_pm)
                content_preview = (
                    rd_pm.get("content", "") or rd_pm.get("title", "")
                    or rd_pm.get("description", "") or json.dumps(rd_pm, ensure_ascii=False)[:100]
                )[:100]
                if not content_preview or content_preview.strip() in ("", "{}"):
                    # persona_memoryに有意義な情報がないのでスキップ
                    logger.debug(f"persona_memory: 空content、記録スキップ ({req_type})")
                else:
                    action_str = "承認" if body.approved else "却下"
                    reason_str = f" 理由: {body.reason}" if body.reason else ""
                    persona_text = f"DAICHIは{req_type or 'unknown'}の{action_str}を行った。内容: {content_preview}。{reason_str}"
                    new_id = await conn_pm.fetchval(
                        """INSERT INTO persona_memory (category, context, content, reasoning, emotion, source, session_id)
                        VALUES ('approval_pattern', $1, $2, $3, '', 'approval_manager', 'system')
                        RETURNING id""",
                        f"{req_type or 'unknown'}の{action_str}",
                        persona_text,
                        body.reason or "",
                    )
                    if new_id:
                        from tools.embedding_tools import embed_and_store_persona
                        import asyncio
                        asyncio.create_task(embed_and_store_persona(new_id, persona_text))
        except Exception as e:
            logger.warning(f"persona_memory記録エラー: {e}")

        # SSE通知
        await broadcast_sse_event("approval_responded", {
            "approval_id": approval_id,
            "approved": body.approved,
        })

        return {"success": True, "approval_id": approval_id, "approved": body.approved}
    except Exception as e:
        logger.error(f"承認応答エラー: {e}")
        raise HTTPException(status_code=500, detail="承認応答エラー")


# ===== 提案 =====

@app.get("/api/proposals")
async def get_proposals(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """提案一覧を取得"""
    try:
        engine = await get_proposal_engine()
        proposals = await engine.get_proposals(limit=limit, offset=offset)
        return {"proposals": proposals}
    except Exception as e:
        logger.error(f"提案一覧取得エラー: {e}")
        raise HTTPException(status_code=500, detail="提案一覧取得エラー")


@app.post("/api/proposals/generate")
async def generate_proposal(user: dict = Depends(get_current_user)):
    """3層提案を手動生成"""
    try:
        engine = await get_proposal_engine()
        # 現在の状況を収集
        pool = await get_pg_pool()
        context_parts = []
        async with pool.acquire() as conn:
            active = await conn.fetchval("SELECT COUNT(*) FROM goal_packets WHERE status = 'active'")
            completed = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'completed'")
            pending = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
            context_parts.append(f"アクティブ目標: {active}件, 完了タスク: {completed}件, 待機中: {pending}件")

        context = "\n".join(context_parts) if context_parts else "初回提案生成"
        proposal_packet = await engine.run_three_layer_pipeline(context=context)

        await broadcast_sse_event("proposal_created", {
            "proposal_id": proposal_packet["proposal_id"],
            "title": proposal_packet["title"],
            "score": proposal_packet.get("total_score", 0),
        })

        return proposal_packet
    except Exception as e:
        logger.error(f"提案生成エラー: {e}")
        raise HTTPException(status_code=500, detail=f"提案生成エラー: {str(e)[:200]}")


@app.post("/api/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    body: ProposalActionRequest = ProposalActionRequest(),
    user: dict = Depends(get_current_user),
):
    """提案を採用 → ゴール自動作成 → 自律ループ起動"""
    try:
        engine = await get_proposal_engine()
        ok = await engine.approve_proposal(proposal_id)
        if ok:
            await broadcast_sse_event("proposal_approved", {
                "proposal_id": proposal_id,
            })

            # 提案のタイトルを取得してゴールに変換
            goal_id = None
            try:
                pool = await get_pg_pool()
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT title, proposal_data FROM proposal_history WHERE proposal_id = $1",
                        proposal_id,
                    )
                if row and row["title"]:
                    title = row["title"]
                    # ゴールテキストを構成
                    goal_text = f"提案「{title}」を実行してください。"

                    # OS_Kernelでゴールを起動（バックグラウンド）
                    from agents.os_kernel import get_os_kernel
                    kernel = get_os_kernel()

                    async def _run_goal():
                        try:
                            await kernel.execute_goal(goal_text)
                        except Exception as e:
                            logger.error(f"提案ゴール実行エラー: {e}")

                    import asyncio
                    asyncio.create_task(_run_goal())
                    goal_id = "auto-created"
                    logger.info(f"提案承認→ゴール自動作成: {title[:50]}")
            except Exception as e:
                logger.error(f"ゴール自動作成エラー（提案承認は成功）: {e}")

            # LearningManagerに採用結果を記録（接続#10修正）
            try:
                from agents.learning_manager import LearningManager
                lm = LearningManager()
                await lm.track_proposal_outcome(proposal_id, adopted=True)
            except Exception as e:
                logger.warning(f"LearningManager記録エラー: {e}")

            return {
                "status": "approved",
                "proposal_id": proposal_id,
                "goal_created": goal_id is not None,
            }
        raise HTTPException(status_code=404, detail="提案が見つかりません")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提案承認エラー: {e}")
        raise HTTPException(status_code=500, detail="提案承認エラー")


@app.post("/api/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    body: ProposalActionRequest = ProposalActionRequest(),
    user: dict = Depends(get_current_user),
):
    """提案を却下（代替案が自動生成される）"""
    try:
        engine = await get_proposal_engine()
        result = await engine.reject_proposal(proposal_id, body.reason)
        await broadcast_sse_event("proposal_rejected", {
            "proposal_id": proposal_id,
            "alternative": result,
        })

        # LearningManagerに却下結果を記録（接続#10修正）
        try:
            from agents.learning_manager import LearningManager
            lm = LearningManager()
            await lm.track_proposal_outcome(proposal_id, adopted=False, rejection_reason=body.reason)
        except Exception as e:
            logger.warning(f"LearningManager記録エラー: {e}")

        return result
    except Exception as e:
        logger.error(f"提案却下エラー: {e}")
        raise HTTPException(status_code=500, detail="提案却下エラー")


# ===== チャット =====

@app.get("/api/chat/history")
async def get_chat_history(
    session_id: str = Query(default="default"),
    limit: int = Query(default=50, le=200),
    user: dict = Depends(get_current_user),
):
    """チャット履歴をPostgreSQLから取得（認証必須 — フロント初期化用）"""
    try:
        pool = await get_pg_pool()
        rows = await pool.fetch(
            """
            SELECT id, session_id, role, content, metadata, created_at
            FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id, limit,
        )
        messages = [
            {
                "id": str(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["created_at"].isoformat() if r["created_at"] else datetime.now(timezone.utc).isoformat(),
                "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
            }
            for r in reversed(rows)  # DESC→昇順に戻す
        ]
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        logger.error(f"チャット履歴取得エラー: {e}")
        return {"session_id": session_id, "messages": []}


@app.post("/api/chat/send")
async def send_chat_message(req: ChatSendRequest, user: dict = Depends(get_current_user)):
    """チャットメッセージを送信（認証必須 — WebSocketフォールバック用）"""
    session_id = req.session_id or "default"

    try:
        # ChatAgentがDB保存を担当（2重保存防止）
        agent = await get_chat_agent()
        response = await agent.process_message(
            session_id=session_id,
            user_message=req.message,
            metadata={"via": "http_fallback"},
        )

        reply_text = response.get("text", "")

        # Discord通知と自律ループはChatAgent._handle_goal_input()が直接起動するため不要

        return {
            "session_id": session_id,
            "reply": reply_text,
            "action": response.get("action"),
            "metadata": response.get("metadata", {}),
            "approval_required": response.get("approval_required", False),
            "approval_id": response.get("approval_id"),
        }
    except Exception as e:
        logger.error(f"チャット送信エラー: {e}")
        raise HTTPException(status_code=500, detail="チャット送信エラー")


# ===== CHARLIE デュアルブート操作 =====

@app.post("/api/charlie/shutdown")
async def charlie_shutdown(user: dict = Depends(get_current_user)):
    """CHARLIEの安全シャットダウン（Win11切替用）"""
    global _charlie_offline_reason
    try:
        import asyncio as _aio
        proc = await _aio.create_subprocess_exec(
            "ssh", "shimahara@100.70.161.106",
            "bash", "/home/shimahara/syutain_beta/scripts/safe_shutdown.sh",
            stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
        )
        # バックグラウンドで実行（shutdownは時間がかかる）
        _charlie_offline_reason = "win11"
        asyncio.create_task(_wait_charlie_shutdown(proc))
        return {"status": "shutdown_initiated", "message": "CHARLIEの安全シャットダウンを開始しました"}
    except Exception as e:
        logger.error(f"CHARLIEシャットダウンエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _wait_charlie_shutdown(proc):
    """CHARLIEシャットダウンプロセスの完了を待つ"""
    try:
        await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("CHARLIEシャットダウンSSHタイムアウト（正常: shutdown nowで接続が切れる）")
    except Exception as e:
        logger.error(f"CHARLIEシャットダウン待機エラー: {e}")


# ===== Agent Ops ステータス =====

@app.get("/api/agent-ops/status")
async def get_agent_ops_status(user: dict = Depends(get_current_user)):
    """Agent Ops画面用ステータス（認証必須）"""
    try:
        from tools.budget_guard import get_budget_guard
        bg = get_budget_guard()
        budget_status = await bg.get_budget_status()
        daily_pct = budget_status.get("daily_usage_pct", 0)
    except Exception:
        daily_pct = 0

    nats_connected = any(
        _node_metrics.get(n, {}).get("status") == "alive"
        for n in ["bravo", "charlie", "delta"]
    )

    total_steps = 0
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            total_steps = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE created_at::date = CURRENT_DATE"
            ) or 0
    except Exception:
        pass

    # アクティブなゴールをDBから取得
    active_goals = []
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT goal_id, raw_goal, parsed_objective, status, created_at
                FROM goal_packets
                WHERE status = 'active'
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
            for row in rows:
                # 関連タスクの進捗を取得
                task_stats = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as total,
                           COUNT(*) FILTER (WHERE status IN ('success', 'completed')) as done,
                           COUNT(*) FILTER (WHERE status = 'running') as running
                    FROM tasks WHERE goal_id = $1
                    """,
                    row["goal_id"],
                )
                total = task_stats["total"] if task_stats else 0
                done = task_stats["done"] if task_stats else 0
                running = task_stats["running"] if task_stats else 0
                # runningタスクは0.5歩分として計上
                step = done + (running * 0.5)
                node = "alpha"
                if running > 0:
                    # 実行中のノードを表示
                    running_node = await conn.fetchval(
                        "SELECT assigned_node FROM tasks WHERE goal_id = $1 AND status = 'running' LIMIT 1",
                        row["goal_id"],
                    )
                    if running_node:
                        node = running_node
                # raw_goalを優先表示（parsed_objectiveはLLM分類語"general"等が入りうる）
                raw = row["raw_goal"] or ""
                parsed = row["parsed_objective"] or ""
                desc = raw if raw else parsed
                # parsed_objectiveが短い分類語（general, content等）なら使わない
                if not desc or (len(desc) < 15 and raw and len(raw) > len(desc)):
                    desc = raw
                active_goals.append({
                    "id": row["goal_id"][:12],
                    "description": desc[:100] if desc else row["goal_id"],
                    "node": node,
                    "step": round(step, 1),
                    "max_steps": max(int(total), 1),
                })
    except Exception as e:
        logger.error(f"active_goals取得エラー: {e}")

    return {
        "nats_connected": nats_connected,
        "loop_guard_active": True,
        "emergency_kills_today": 0,
        "total_steps_today": int(total_steps),
        "daily_budget_used": round(daily_pct, 1),
        "active_goals": active_goals,
    }


# ===== ノードステータス =====

@app.get("/api/nodes/status")
async def get_nodes_status(user: dict = Depends(get_current_user)):
    """4ノードのステータスを取得（NATSハートビートキャッシュから）"""
    roles = {
        "alpha": {"role": "司令塔", "os": "macOS"},
        "bravo": {"role": "実行者", "os": "Ubuntu"},
        "charlie": {"role": "推論エンジン", "os": "Ubuntu"},
        "delta": {"role": "監視・補助", "os": "Ubuntu"},
    }
    nodes = {}
    for name, info in roles.items():
        m = _node_metrics.get(name, {})
        import time as _t
        last_hb = m.get("last_heartbeat", 0)
        node_data = {
            **info,
            "status": m.get("status", "unknown"),
            "cpu_percent": m.get("cpu_percent", 0),
            "memory_percent": m.get("memory_percent", 0),
            "last_heartbeat_ago": round(_t.time() - last_hb) if last_hb > 0 else -1,
        }
        if name == "charlie" and _charlie_offline_reason:
            node_data["offline_reason"] = _charlie_offline_reason
        nodes[name] = node_data
    return {"nodes": nodes}


# ===== モデル使用統計 =====

@app.get("/api/models/usage")
async def get_model_usage(user: dict = Depends(get_current_user)):
    """モデル使用統計を取得"""
    usage = {"models": [], "tier_summary": {}, "total_cost_jpy": 0}

    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # モデル別使用回数
            rows = await conn.fetch(
                """
                SELECT model_used, tier, COUNT(*) as call_count,
                       SUM(cost_jpy) as total_cost
                FROM tasks
                WHERE model_used IS NOT NULL
                GROUP BY model_used, tier
                ORDER BY call_count DESC
                """
            )
            usage["models"] = [
                {**dict(r), "total_cost": float(r["total_cost"] or 0), "call_count": int(r["call_count"] or 0)}
                for r in rows
            ]

            # llm_cost_logからも集計（tasksに記録されないLLM呼び出しを補完）
            cost_rows = await conn.fetch(
                """
                SELECT model, tier, COUNT(*) as call_count,
                       SUM(amount_jpy) as total_cost
                FROM llm_cost_log
                GROUP BY model, tier
                ORDER BY call_count DESC
                """
            )
            # tasksにないモデルをllm_cost_logから追加
            existing_models = {r["model_used"] for r in rows if r["model_used"]}
            for cr in cost_rows:
                if cr["model"] and cr["model"] not in existing_models:
                    usage["models"].append({
                        "model_used": cr["model"],
                        "tier": cr["tier"],
                        "call_count": int(cr["call_count"] or 0),
                        "total_cost": float(cr["total_cost"] or 0),
                    })

            # Tier別サマリー
            tier_rows = await conn.fetch(
                """
                SELECT tier, COUNT(*) as count, SUM(cost_jpy) as cost
                FROM tasks
                WHERE tier IS NOT NULL
                GROUP BY tier
                """
            )
            usage["tier_summary"] = {r["tier"]: {**dict(r), "cost": float(r["cost"] or 0)} for r in tier_rows}

            # 総コスト (tasks + llm_cost_log)
            total_tasks = await conn.fetchval(
                "SELECT COALESCE(SUM(cost_jpy), 0) FROM tasks"
            )
            total_llm = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log"
            )
            usage["total_cost_jpy"] = float(max(total_tasks or 0, total_llm or 0))

    except Exception as e:
        logger.error(f"モデル使用統計取得エラー: {e}")

    return usage


# ===== モデル使用統計（フロントエンド互換エイリアス）=====

@app.get("/api/model-usage")
async def get_model_usage_alias(user: dict = Depends(get_current_user)):
    """モデル使用統計（/api/models/usageのエイリアス）"""
    return await get_model_usage()


# ===== 予算状態 =====

@app.get("/api/budget/status")
async def get_budget_status_api(user: dict = Depends(get_current_user)):
    """予算状態を取得（認証必須）"""
    try:
        from tools.budget_guard import get_budget_guard
        bg = get_budget_guard()
        status = await bg.get_budget_status()
        # フロントエンド互換フィールドを追加
        status["daily_used_jpy"] = status.get("daily_spent_jpy", 0)
        status["daily_limit_jpy"] = status.get("daily_budget_jpy", 80)
        status["monthly_used_jpy"] = status.get("monthly_spent_jpy", 0)
        status["monthly_limit_jpy"] = status.get("monthly_budget_jpy", 1500)
        status["daily_percent"] = status.get("daily_usage_pct", 0)
        status["monthly_percent"] = status.get("monthly_usage_pct", 0)
        # チャット予算
        status["chat_budget_jpy"] = float(os.getenv("DAILY_CHAT_BUDGET_JPY", "30"))
        # chat_spent_jpy は BudgetGuard.get_budget_status() から取得済み（未設定の場合は0）
        if "chat_spent_jpy" not in status:
            status["chat_spent_jpy"] = 0
        return status
    except Exception as e:
        logger.error(f"予算状態取得エラー: {e}")
        daily = float(os.getenv("DAILY_BUDGET_JPY", os.getenv("DAILY_API_BUDGET_JPY", "80")))
        monthly = float(os.getenv("MONTHLY_BUDGET_JPY", os.getenv("MONTHLY_API_BUDGET_JPY", "1500")))
        return {
            "daily_budget_jpy": daily,
            "daily_spent_jpy": 0,
            "daily_remaining_jpy": daily,
            "daily_usage_pct": 0,
            "daily_used_jpy": 0,
            "daily_limit_jpy": daily,
            "daily_percent": 0,
            "monthly_budget_jpy": monthly,
            "monthly_spent_jpy": 0,
            "monthly_remaining_jpy": monthly,
            "monthly_usage_pct": 0,
            "monthly_used_jpy": 0,
            "monthly_limit_jpy": monthly,
            "monthly_percent": 0,
            "chat_budget_jpy": 30,
            "chat_spent_jpy": 0,
        }


# ===== 収益 =====

@app.get("/api/revenue")
async def get_revenue(user: dict = Depends(get_current_user)):
    """収益データを取得（認証必須）"""
    data = {"today_revenue": 0, "monthly_revenue": 0, "entries": []}
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            today = await conn.fetchval(
                "SELECT COALESCE(SUM(revenue_jpy), 0) FROM revenue_linkage WHERE created_at::date = CURRENT_DATE"
            )
            data["today_revenue"] = float(today) if today else 0
            monthly = await conn.fetchval(
                "SELECT COALESCE(SUM(revenue_jpy), 0) FROM revenue_linkage WHERE created_at >= date_trunc('month', CURRENT_DATE)"
            )
            data["monthly_revenue"] = float(monthly) if monthly else 0
            rows = await conn.fetch(
                "SELECT * FROM revenue_linkage ORDER BY created_at DESC LIMIT 20"
            )
            data["entries"] = [
                {
                    **dict(r),
                    # フロントエンド互換フィールド
                    "amount": r.get("revenue_jpy", 0),
                    "source": r.get("platform", ""),
                    "description": r.get("product_id", ""),
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"収益データ取得エラー: {e}")
    return data


@app.post("/api/revenue")
async def create_revenue(body: dict, user: dict = Depends(get_current_user)):
    """収益レコードを登録"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO revenue_linkage
                (source_content_id, product_id, revenue_jpy, platform, conversion_stage)
                VALUES ($1, $2, $3, $4, $5)""",
                body.get("source_content_id", ""),
                body.get("product_id", ""),
                float(body.get("revenue_jpy", 0)),
                body.get("platform", "manual"),
                body.get("conversion_stage", "direct"),
            )
        return {"success": True}
    except Exception as e:
        logger.error(f"収益登録エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 収益記録フロー（拡張） =====

class RevenueRecordRequest(BaseModel):
    platform: str
    product_title: str
    revenue_jpy: int
    fee_jpy: int = 0
    net_revenue_jpy: int = 0
    platform_order_id: Optional[str] = None
    source_content_id: Optional[str] = None
    buyer_info: Optional[str] = None
    notes: Optional[str] = None
    conversion_stage: str = "direct"


@app.post("/api/revenue/record")
async def record_revenue(body: RevenueRecordRequest, user: dict = Depends(get_current_user)):
    """収益を記録し、event_logに残し、Discord通知を送信する"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO revenue_linkage
                (platform, product_title, revenue_jpy, fee_jpy, net_revenue_jpy,
                 platform_order_id, source_content_id, buyer_info, notes, conversion_stage)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id, created_at""",
                body.platform,
                body.product_title,
                body.revenue_jpy,
                body.fee_jpy,
                body.net_revenue_jpy,
                body.platform_order_id or "",
                body.source_content_id or "",
                body.buyer_info or "",
                body.notes or "",
                body.conversion_stage,
            )
            record_id = row["id"]
            created_at = row["created_at"]

        # event_log記録
        try:
            from tools.event_logger import log_event
            await log_event(
                "revenue.recorded", "revenue",
                {
                    "record_id": record_id,
                    "platform": body.platform,
                    "product_title": body.product_title,
                    "revenue_jpy": body.revenue_jpy,
                    "net_revenue_jpy": body.net_revenue_jpy,
                    "fee_jpy": body.fee_jpy,
                },
                severity="info",
            )
        except Exception as e:
            logger.error(f"収益event_log記録エラー: {e}")

        # Discord通知
        try:
            await notify_discord(
                f"💰 売上記録: {body.product_title}\n"
                f"プラットフォーム: {body.platform}\n"
                f"売上: ¥{body.revenue_jpy:,} / 手数料: ¥{body.fee_jpy:,} / 純収益: ¥{body.net_revenue_jpy:,}",
                username="SYUTAINβ Revenue",
            )
        except Exception as e:
            logger.error(f"収益Discord通知エラー: {e}")

        return {
            "success": True,
            "record_id": record_id,
            "created_at": created_at.isoformat() if created_at else None,
        }
    except Exception as e:
        logger.error(f"収益記録エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/revenue/summary")
async def get_revenue_summary(
    days: int = Query(default=30, le=365),
    user: dict = Depends(get_current_user),
):
    """指定期間の収益サマリーを返す"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # 合計
            totals = await conn.fetchrow(
                """SELECT
                    COALESCE(SUM(revenue_jpy), 0) AS total_revenue,
                    COALESCE(SUM(net_revenue_jpy), 0) AS total_net_revenue,
                    COALESCE(SUM(fee_jpy), 0) AS total_fee,
                    COUNT(*) AS count
                FROM revenue_linkage
                WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL""",
                str(days),
            )
            # プラットフォーム別
            platform_rows = await conn.fetch(
                """SELECT platform,
                    COALESCE(SUM(revenue_jpy), 0) AS revenue,
                    COALESCE(SUM(net_revenue_jpy), 0) AS net_revenue,
                    COUNT(*) AS count
                FROM revenue_linkage
                WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
                GROUP BY platform ORDER BY revenue DESC""",
                str(days),
            )
            # 商品別
            product_rows = await conn.fetch(
                """SELECT COALESCE(product_title, product_id, '不明') AS product,
                    COALESCE(SUM(revenue_jpy), 0) AS revenue,
                    COALESCE(SUM(net_revenue_jpy), 0) AS net_revenue,
                    COUNT(*) AS count
                FROM revenue_linkage
                WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
                GROUP BY COALESCE(product_title, product_id, '不明') ORDER BY revenue DESC""",
                str(days),
            )
        return {
            "days": days,
            "total_revenue": int(totals["total_revenue"]),
            "total_net_revenue": int(totals["total_net_revenue"]),
            "total_fee": int(totals["total_fee"]),
            "count": int(totals["count"]),
            "platform_breakdown": [
                {"platform": r["platform"] or "不明", "revenue": int(r["revenue"]),
                 "net_revenue": int(r["net_revenue"]), "count": int(r["count"])}
                for r in platform_rows
            ],
            "product_breakdown": [
                {"product": r["product"], "revenue": int(r["revenue"]),
                 "net_revenue": int(r["net_revenue"]), "count": int(r["count"])}
                for r in product_rows
            ],
        }
    except Exception as e:
        logger.error(f"収益サマリーエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/revenue/history")
async def get_revenue_history(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """最近の収益レコードを返す"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, platform, product_title, revenue_jpy, fee_jpy,
                    net_revenue_jpy, platform_order_id, buyer_info, notes,
                    conversion_stage, source_content_id, created_at
                FROM revenue_linkage
                ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
        return {
            "records": [
                {
                    "id": r["id"],
                    "platform": r["platform"] or "",
                    "product_title": r["product_title"] or r.get("product_id", ""),
                    "revenue_jpy": int(r["revenue_jpy"] or 0),
                    "fee_jpy": int(r["fee_jpy"] or 0),
                    "net_revenue_jpy": int(r["net_revenue_jpy"] or 0),
                    "platform_order_id": r["platform_order_id"] or "",
                    "buyer_info": r["buyer_info"] or "",
                    "notes": r["notes"] or "",
                    "conversion_stage": r["conversion_stage"] or "",
                    "source_content_id": r["source_content_id"] or "",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"収益履歴エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== イベントログ =====

@app.get("/api/events")
async def get_events(
    category: str = Query(default="", description="カテゴリフィルタ"),
    severity: str = Query(default="", description="重要度フィルタ"),
    limit: int = Query(default=50, le=200),
    user: dict = Depends(get_current_user),
):
    """イベントログを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            query = "SELECT * FROM event_log WHERE 1=1"
            params = []
            idx = 1
            if category:
                query += f" AND category = ${idx}"
                params.append(category)
                idx += 1
            if severity:
                query += f" AND severity = ${idx}"
                params.append(severity)
                idx += 1
            query += f" ORDER BY created_at DESC LIMIT ${idx}"
            params.append(limit)
            rows = await conn.fetch(query, *params)
            events = []
            for r in rows:
                events.append({
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "category": r["category"],
                    "severity": r["severity"],
                    "source_node": r["source_node"],
                    "goal_id": r["goal_id"],
                    "task_id": r["task_id"],
                    "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                })
            return {"events": events, "total": len(events)}
    except Exception as e:
        logger.error(f"イベントログ取得エラー: {e}")
        return {"events": [], "total": 0}


# ===== コンテンツ編集追跡 =====

class EditLogRequest(BaseModel):
    content_type: str
    original: str
    edited: str
    model_used: Optional[str] = None
    quality_score_before: Optional[float] = None
    quality_score_after: Optional[float] = None


@app.post("/api/content/edit-log")
async def post_edit_log(req: EditLogRequest, user: dict = Depends(get_current_user)):
    """コンテンツ編集ログを記録"""
    try:
        from tools.edit_tracker import record_edit
        record_id = await record_edit(
            content_type=req.content_type,
            original=req.original,
            edited=req.edited,
            model_used=req.model_used,
            quality_score_before=req.quality_score_before,
            quality_score_after=req.quality_score_after,
        )
        if record_id is None:
            raise HTTPException(status_code=500, detail="編集ログの記録に失敗しました")
        return {"id": record_id, "status": "recorded"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"編集ログ記録エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/content/edit-stats")
async def get_edit_stats_api(
    content_type: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    days: int = Query(default=30, le=365),
    user: dict = Depends(get_current_user),
):
    """コンテンツ編集統計を取得"""
    try:
        from tools.edit_tracker import get_edit_stats, get_recent_edits
        stats = await get_edit_stats(content_type=content_type, model=model, days=days)
        recent = await get_recent_edits(limit=5)
        return {"stats": stats, "recent_edits": recent}
    except Exception as e:
        logger.error(f"編集統計取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 情報収集 =====

@app.get("/api/intel")
async def get_intel(user: dict = Depends(get_current_user)):
    """収集した情報を取得（認証必須）"""
    items = []
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM intel_items ORDER BY created_at DESC LIMIT 100"
            )
            items = [
                {
                    **dict(r),
                    # フロントエンド互換フィールド
                    "importance": r.get("importance_score", 0),
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"情報収集データ取得エラー: {e}")
    return {"items": items}


# ===== 設定 =====

@app.get("/api/settings/feature-flags")
async def get_feature_flags():
    """Feature Flagsを取得（認証不要）"""
    try:
        import yaml
        ff_path = Path("feature_flags.yaml")
        if ff_path.exists():
            with open(ff_path, "r") as f:
                flags = yaml.safe_load(f)
            return {"flags": flags}
    except Exception as e:
        logger.error(f"Feature Flags取得エラー: {e}")
    return {"flags": {}}


@app.get("/api/settings")
async def get_all_settings(user: dict = Depends(get_current_user)):
    """全設定を取得"""
    settings = {
        "budget": {
            "daily_budget_jpy": 80,
            "monthly_budget_jpy": 1500,
            "chat_budget_jpy": 30,
        },
        "chat_model": {"mode": "auto"},
        "discord": {
            "goal_accepted": True,
            "task_completed": True,
            "error_alert": True,
            "node_status": True,
            "proposal_created": True,
        },
    }
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # Ensure settings table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            rows = await conn.fetch("SELECT key, value FROM settings")
            for row in rows:
                try:
                    settings[row["key"]] = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"設定取得エラー: {e}")
    return settings


@app.post("/api/settings/budget")
async def update_budget_settings(req: BudgetSettingsRequest, user: dict = Depends(get_current_user)):
    """予算設定を更新"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            value = {}
            if req.daily_budget_jpy is not None:
                value["daily_budget_jpy"] = req.daily_budget_jpy
            if req.monthly_budget_jpy is not None:
                value["monthly_budget_jpy"] = req.monthly_budget_jpy
            if req.chat_budget_jpy is not None:
                value["chat_budget_jpy"] = req.chat_budget_jpy

            await conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES ('budget', $1::jsonb, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = settings.value || $1::jsonb, updated_at = NOW()""",
                json.dumps(value),
            )

            # Update budget_guard in-memory values
            try:
                from tools.budget_guard import get_budget_guard, DAILY_BUDGET_JPY, MONTHLY_BUDGET_JPY
                import tools.budget_guard as bg_module
                if req.daily_budget_jpy is not None:
                    bg_module.DAILY_BUDGET_JPY = req.daily_budget_jpy
                if req.monthly_budget_jpy is not None:
                    bg_module.MONTHLY_BUDGET_JPY = req.monthly_budget_jpy
            except Exception:
                pass

        return {"status": "ok", "updated": value}
    except Exception as e:
        logger.error(f"予算設定更新エラー: {e}")
        raise HTTPException(status_code=500, detail="予算設定更新エラー")


@app.post("/api/settings/chat-model")
async def update_chat_model(req: ChatModelRequest, user: dict = Depends(get_current_user)):
    """チャットモデル設定を更新"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES ('chat_model', $1::jsonb, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $1::jsonb, updated_at = NOW()""",
                json.dumps({"mode": req.mode}),
            )
        return {"status": "ok", "mode": req.mode}
    except Exception as e:
        logger.error(f"チャットモデル設定更新エラー: {e}")
        raise HTTPException(status_code=500, detail="チャットモデル設定更新エラー")


@app.post("/api/settings/discord")
async def update_discord_settings(req: DiscordSettingsRequest, user: dict = Depends(get_current_user)):
    """Discord通知設定を更新"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            value = req.model_dump(exclude_none=True)
            await conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES ('discord', $1::jsonb, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = settings.value || $1::jsonb, updated_at = NOW()""",
                json.dumps(value),
            )
        return {"status": "ok", "updated": value}
    except Exception as e:
        logger.error(f"Discord通知設定更新エラー: {e}")
        raise HTTPException(status_code=500, detail="Discord通知設定更新エラー")


# ===== SSEイベントストリーム =====

@app.get("/api/stream/events")
async def sse_event_stream(request: Request, user: dict = Depends(get_current_user)):
    """SSEイベントストリーム（リアルタイム更新）"""

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        _sse_subscribers.append(queue)

        try:
            # 接続確認イベント
            yield f"event: connected\ndata: {json.dumps({'node': THIS_NODE})}\n\n"

            while True:
                # クライアント切断チェック
                if await request.is_disconnected():
                    break

                try:
                    # 30秒のタイムアウトでキューからイベントを取得
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = message.get("event", "update")
                    data = json.dumps(message.get("data", {}), ensure_ascii=False, default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # キープアライブ（30秒ごと）
                    yield f"event: ping\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
        finally:
            if queue in _sse_subscribers:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== 目標（Goal）=====

@app.post("/api/goals")
async def create_goal(
    req: GoalCreateRequest,
    user: dict = Depends(get_current_user),
):
    """新しい目標（Goal Packet）を作成"""
    goal_id = str(uuid.uuid4())

    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO goal_packets (goal_id, raw_goal, status)
                VALUES ($1, $2, 'active')
                """,
                goal_id,
                req.raw_goal,
            )

        # NATS通知
        try:
            nats_client = await get_nats_client()
            await nats_client.publish(
                "task.create",
                {
                    "goal_id": goal_id,
                    "raw_goal": req.raw_goal,
                    "priority": req.priority,
                    "source": "api",
                },
            )
        except Exception as e:
            logger.error(f"NATS Goal通知エラー: {e}")

        # SSE通知
        await broadcast_sse_event("goal_created", {
            "goal_id": goal_id,
            "raw_goal": req.raw_goal,
        })

        return {"goal_id": goal_id, "status": "active", "raw_goal": req.raw_goal}

    except Exception as e:
        logger.error(f"目標作成エラー: {e}")
        raise HTTPException(status_code=500, detail="目標作成エラー")


# ===== ゴール追跡タイムライン =====

@app.get("/api/goals/{goal_id}/timeline")
async def get_goal_timeline(goal_id: str, user: dict = Depends(get_current_user)):
    """ゴールの全経緯をタイムラインで取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # ゴール情報
            goal = await conn.fetchrow(
                "SELECT * FROM goal_packets WHERE goal_id = $1", goal_id
            )
            if not goal:
                raise HTTPException(status_code=404, detail="ゴールが見つかりません")

            timeline = []

            # ゴール作成イベント
            timeline.append({
                "type": "goal_created",
                "timestamp": goal["created_at"].isoformat() if goal["created_at"] else None,
                "data": {
                    "raw_goal": goal["raw_goal"],
                    "hard_constraints": goal.get("hard_constraints"),
                    "status": goal["status"],
                },
            })

            # タスク一覧
            tasks = await conn.fetch(
                """SELECT id, type, status, assigned_node, quality_score,
                          output_data, created_at, updated_at
                FROM tasks WHERE goal_id = $1
                ORDER BY created_at ASC""",
                goal_id,
            )
            for t in tasks:
                timeline.append({
                    "type": "task",
                    "timestamp": t["created_at"].isoformat() if t["created_at"] else None,
                    "data": {
                        "task_id": t["id"],
                        "task_type": t["type"],
                        "status": t["status"],
                        "assigned_node": t["assigned_node"],
                        "quality_score": float(t["quality_score"]) if t["quality_score"] else None,
                        "output_preview": str(t["output_data"])[:200] if t["output_data"] else None,
                        "updated_at": t["updated_at"].isoformat() if t["updated_at"] else None,
                    },
                })

            # event_logからゴール関連イベント
            events = await conn.fetch(
                """SELECT event_type, category, severity, payload, source_node, created_at
                FROM event_log
                WHERE payload->>'goal_id' = $1
                ORDER BY created_at ASC
                LIMIT 100""",
                goal_id,
            )
            for e in events:
                payload = e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"]) if e["payload"] else {}
                timeline.append({
                    "type": "event",
                    "timestamp": e["created_at"].isoformat() if e["created_at"] else None,
                    "data": {
                        "event_type": e["event_type"],
                        "category": e["category"],
                        "severity": e["severity"],
                        "source_node": e["source_node"],
                        "payload": payload,
                    },
                })

            # LLMコストログ
            llm_logs = await conn.fetch(
                """SELECT model, tier, amount_jpy, recorded_at
                FROM llm_cost_log WHERE goal_id = $1
                ORDER BY recorded_at ASC""",
                goal_id,
            )
            for l in llm_logs:
                timeline.append({
                    "type": "llm_call",
                    "timestamp": l["recorded_at"].isoformat() if l["recorded_at"] else None,
                    "data": {
                        "model": l["model"],
                        "tier": l["tier"],
                        "cost_jpy": float(l["amount_jpy"]) if l["amount_jpy"] else 0,
                    },
                })

            # 承認リクエスト（task_id経由）
            task_ids = [t["id"] for t in tasks]
            if task_ids:
                approvals = await conn.fetch(
                    """SELECT id, request_type, status, requested_at, responded_at, response
                    FROM approval_queue
                    WHERE request_data->>'task_id' = ANY($1::text[])
                    ORDER BY requested_at ASC""",
                    task_ids,
                )
                for a in approvals:
                    timeline.append({
                        "type": "approval",
                        "timestamp": a["requested_at"].isoformat() if a["requested_at"] else None,
                        "data": {
                            "approval_id": a["id"],
                            "request_type": a["request_type"],
                            "status": a["status"],
                            "responded_at": a["responded_at"].isoformat() if a["responded_at"] else None,
                            "response": a["response"],
                        },
                    })

            # 時系列ソート
            timeline.sort(key=lambda x: x["timestamp"] or "")

            return {
                "goal_id": goal_id,
                "goal": {
                    "raw_goal": goal["raw_goal"],
                    "status": goal["status"],
                    "created_at": goal["created_at"].isoformat() if goal["created_at"] else None,
                },
                "timeline": timeline,
                "summary": {
                    "total_tasks": len(tasks),
                    "completed_tasks": sum(1 for t in tasks if t["status"] == "completed"),
                    "total_events": len(events),
                    "total_llm_calls": len(llm_logs),
                    "total_cost_jpy": sum(float(l.get("amount_jpy") or 0) for l in llm_logs),
                },
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"タイムライン取得エラー: {e}")
        raise HTTPException(status_code=500, detail="タイムライン取得エラー")


@app.get("/api/goals")
async def list_goals(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """ゴール一覧を取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT goal_id, raw_goal, status, created_at
                FROM goal_packets ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {"goals": [
                {
                    "goal_id": r["goal_id"],
                    "raw_goal": r["raw_goal"],
                    "status": r["status"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]}
    except Exception as e:
        logger.error(f"ゴール一覧取得エラー: {e}")
        raise HTTPException(status_code=500, detail="ゴール一覧取得エラー")


# ===== 承認 =====

@app.get("/api/approvals")
async def get_approvals(
    status: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """承認キューを取得"""
    try:
        manager = await get_approval_manager()
        if status == "pending":
            approvals = await manager.get_pending_approvals()
        else:
            approvals = await manager.get_all_approvals()
        return {"approvals": approvals}
    except Exception as e:
        logger.error(f"承認キュー取得エラー: {e}")
        raise HTTPException(status_code=500, detail="承認キュー取得エラー")


@app.post("/api/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: int,
    body: ApprovalResponse,
    user: dict = Depends(get_current_user),
):
    """承認リクエストに応答"""
    try:
        manager = await get_approval_manager()
        result = await manager.respond(
            approval_id=approval_id,
            approved=body.approved,
            reason=body.reason,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # SSE通知
        status = "approved" if body.approved else "rejected"
        await broadcast_sse_event(f"approval_{status}", {
            "approval_id": approval_id,
            "status": status,
        })

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"承認応答エラー: {e}")
        raise HTTPException(status_code=500, detail="承認応答エラー")


# ===== WebSocket チャット =====

@app.websocket("/api/chat/ws")
async def websocket_chat(ws: WebSocket):
    """WebSocketチャットエンドポイント"""
    await ws.accept()
    session_id = "default"
    logger.info(f"WebSocket接続: session={session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({
                    "id": str(uuid.uuid4()),
                    "role": "system",
                    "content": "不正なメッセージ形式です",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "approval_required": False,
                })
                continue

            msg_type = data.get("type", "message")

            if msg_type == "message":
                user_text = data.get("content", "").strip()
                if not user_text:
                    continue

                try:
                    agent = await get_chat_agent()
                    msg_id = str(uuid.uuid4())
                    full_text = ""
                    action = None
                    model_used = None
                    approval_required = False
                    approval_id = None

                    # 即座に「処理中」を返す（タイムアウト防止）
                    await ws.send_json({
                        "id": msg_id,
                        "role": "assistant",
                        "content": "",
                        "streaming": True,
                        "done": False,
                        "status": "processing",
                    })

                    # ストリーミング応答
                    async for chunk in agent.process_message_stream(
                        session_id=session_id,
                        user_message=user_text,
                        metadata={"via": "websocket"},
                    ):
                        if chunk.get("done"):
                            action = chunk.get("action")
                            model_used = chunk.get("model_used")
                            if chunk.get("token"):
                                full_text = chunk["token"]
                            # 最終メッセージ送信
                            await ws.send_json({
                                "id": msg_id,
                                "role": "assistant",
                                "content": full_text,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "approval_required": approval_required,
                                "approval_id": approval_id,
                                "model_used": model_used,
                                "action": action,
                                "done": True,
                            })
                        else:
                            token = chunk.get("token", "")
                            full_text += token
                            # トークン単位でストリーミング送信
                            await ws.send_json({
                                "id": msg_id,
                                "role": "assistant",
                                "content": token,
                                "streaming": True,
                                "done": False,
                            })

                    # チャット予算記録
                    try:
                        from tools.budget_guard import get_budget_guard
                        bg = get_budget_guard()
                        # LLMルーターが既にrecord_spend済みなので、チャット固有の追跡のみ
                        # cost_jpyはストリーミング完了チャンクのmetadataから取得不可のため
                        # budget_statusから最新のdaily_spentを返す
                        budget_status = await bg.get_budget_status()
                        await ws.send_json({
                            "type": "budget_update",
                            "chat_spent_jpy": budget_status.get("chat_spent_jpy", 0),
                            "daily_spent_jpy": budget_status.get("daily_spent_jpy", 0),
                        })
                    except Exception:
                        pass

                    # Discord通知とゴール自律ループはChatAgent._handle_goal_input()が直接起動するため
                    # WebSocketハンドラでは二重起動しない
                    if action == "goal_created":
                        logger.info(f"ゴール受付完了（自律ループはChatAgentが起動済み）")

                except Exception as e:
                    logger.error(f"WebSocketチャット処理エラー: {e}")
                    await ws.send_json({
                        "id": str(uuid.uuid4()),
                        "role": "system",
                        "content": f"処理エラー: {str(e)[:100]}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "approval_required": False,
                    })

            elif msg_type == "approval":
                approval_id = data.get("approval_id")
                approved = data.get("approved", False)
                try:
                    manager = await get_approval_manager()
                    result = await manager.respond(
                        approval_id=approval_id,
                        approved=approved,
                        reason="WebSocket経由の承認",
                    )
                    await ws.send_json({
                        "id": str(uuid.uuid4()),
                        "role": "system",
                        "content": f"承認ID {approval_id}: {'承認' if approved else '却下'}しました",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "approval_required": False,
                    })
                except Exception as e:
                    logger.error(f"WebSocket承認処理エラー: {e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket切断: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocketエラー: {e}")


# ===== Brain-α 精査レポート API =====

@app.get("/api/brain-alpha/latest-report")
async def get_latest_brain_alpha_report(user: dict = Depends(get_current_user)):
    """最新のBrain-α精査レポートを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, reasoning as summary, decision as actions, evidence as report,
                          created_at
                   FROM brain_alpha_reasoning
                   WHERE category = 'startup_review'
                   ORDER BY created_at DESC LIMIT 1"""
            )
            if not row:
                return {"report": None}
            report_data = json.loads(row["report"]) if isinstance(row["report"], str) else row["report"]
            actions = json.loads(row["actions"]) if isinstance(row["actions"], str) else row["actions"]
            return {
                "report": {
                    "id": row["id"],
                    "summary": row["summary"],
                    "recommended_actions": actions,
                    "phases": report_data.get("phases", {}),
                    "warnings": report_data.get("warnings", []),
                    "generated_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            }
    except Exception as e:
        logger.error(f"Brain-αレポート取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/reports")
async def get_brain_alpha_reports(
    limit: int = Query(default=10, le=50),
    user: dict = Depends(get_current_user),
):
    """過去のBrain-α精査レポート一覧"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, reasoning as summary, decision as actions, created_at
                   FROM brain_alpha_reasoning
                   WHERE category = 'startup_review'
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "reports": [
                    {
                        "id": r["id"],
                        "summary": r["summary"],
                        "actions": json.loads(r["actions"]) if isinstance(r["actions"], str) else r["actions"],
                        "generated_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"Brain-αレポート一覧取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/brain-alpha/run-review")
async def run_brain_alpha_review(user: dict = Depends(get_current_user)):
    """Brain-α精査サイクルを手動実行"""
    try:
        from brain_alpha.startup_review import run_startup_review, format_discord_report
        report = await run_startup_review()
        # Discord投稿
        try:
            discord_md = format_discord_report(report)
            await notify_discord(discord_md)
        except Exception:
            pass
        return {"status": "ok", "report": report}
    except Exception as e:
        logger.error(f"Brain-α精査実行エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/sessions")
async def get_brain_alpha_sessions(
    limit: int = Query(default=10, le=50),
    user: dict = Depends(get_current_user),
):
    """Brain-αセッション記憶一覧"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, started_at, ended_at, summary,
                          key_decisions, unresolved_issues, daichi_interactions, created_at
                   FROM brain_alpha_session
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "sessions": [
                    {
                        "id": r["id"],
                        "session_id": r["session_id"],
                        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                        "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                        "summary": r["summary"],
                        "key_decisions": json.loads(r["key_decisions"]) if isinstance(r["key_decisions"], str) else r["key_decisions"],
                        "unresolved_issues": json.loads(r["unresolved_issues"]) if isinstance(r["unresolved_issues"], str) else r["unresolved_issues"],
                        "daichi_interactions": r["daichi_interactions"] or 0,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"セッション一覧取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/persona-stats")
async def get_persona_stats(user: dict = Depends(get_current_user)):
    """persona_memoryカテゴリ別統計"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT category, COUNT(*) as count,
                          COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                   FROM persona_memory
                   GROUP BY category ORDER BY count DESC"""
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM persona_memory")
            return {
                "total": total or 0,
                "categories": [
                    {"category": r["category"], "count": r["count"], "embedded": r["embedded"]}
                    for r in rows
                ],
            }
    except Exception as e:
        logger.error(f"persona統計取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/handoffs")
async def get_brain_handoffs(
    direction: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """brain_handoffを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            conditions = []
            args = []
            idx = 1
            if direction:
                conditions.append(f"direction = ${idx}")
                args.append(direction)
                idx += 1
            if status:
                conditions.append(f"status = ${idx}")
                args.append(status)
                idx += 1
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            args.append(limit)
            rows = await conn.fetch(
                f"""SELECT id, direction, category, source_agent, title, detail,
                          context, status, created_at
                   FROM brain_handoff
                   {where}
                   ORDER BY created_at DESC LIMIT ${idx}""",
                *args,
            )
            return {
                "handoffs": [
                    {
                        "id": r["id"],
                        "direction": r["direction"],
                        "category": r["category"],
                        "source_agent": r["source_agent"],
                        "title": r["title"],
                        "detail": r["detail"],
                        "context": json.loads(r["context"]) if isinstance(r["context"], str) else r["context"],
                        "status": r["status"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"handoff取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/queue")
async def get_brain_queue(
    status: str = Query(default="pending"),
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """claude_code_queueを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, priority, category, description, auto_solvable,
                          source_agent, status, created_at
                   FROM claude_code_queue
                   WHERE status = $1
                   ORDER BY
                     CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                     created_at ASC
                   LIMIT $2""",
                status, limit,
            )
            return {
                "queue": [
                    {
                        "id": r["id"],
                        "priority": r["priority"],
                        "category": r["category"],
                        "description": r["description"],
                        "auto_solvable": r["auto_solvable"],
                        "source_agent": r["source_agent"],
                        "status": r["status"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"queue取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/cross-evaluations")
async def get_cross_evaluations(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """相互評価結果を取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, evaluator, evaluated_agent, target_id, target_type,
                          score, evaluation, recommendations, created_at
                   FROM brain_cross_evaluation
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "evaluations": [
                    {
                        "id": r["id"],
                        "evaluator": r["evaluator"],
                        "evaluated_agent": r["evaluated_agent"],
                        "target_id": r["target_id"],
                        "target_type": r["target_type"],
                        "score": float(r["score"]) if r["score"] else None,
                        "evaluation": r["evaluation"],
                        "recommendations": json.loads(r["recommendations"]) if isinstance(r["recommendations"], str) else r["recommendations"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"相互評価取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/dialogues")
async def get_brain_alpha_dialogues(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """Daichi対話ログを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, channel, daichi_message, system_response,
                          extracted_philosophy, context_level, session_id, created_at
                   FROM daichi_dialogue_log ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "dialogues": [
                    {
                        "id": r["id"],
                        "channel": r["channel"],
                        "daichi_message": r["daichi_message"],
                        "system_response": (r["system_response"] or "")[:200],
                        "extracted_philosophy": json.loads(r["extracted_philosophy"]) if isinstance(r["extracted_philosophy"], str) else r["extracted_philosophy"],
                        "session_id": r["session_id"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"対話ログ取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/brain-alpha/personality")
async def get_personality(user: dict = Depends(get_current_user)):
    """人格サマリーを取得"""
    try:
        from brain_alpha.persona_bridge import get_personality_summary
        return await get_personality_summary()
    except Exception as e:
        logger.error(f"人格サマリー取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 自律修復 API =====

@app.get("/api/self-healing/log")
async def get_self_healing_log(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """自律修復ログ"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, error_type, error_detail, fix_strategy, fix_result, files_modified, created_at
                   FROM auto_fix_log ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "log": [
                    {
                        "id": r["id"],
                        "error_type": r["error_type"],
                        "error_detail": r["error_detail"],
                        "fix_strategy": r["fix_strategy"],
                        "fix_result": r["fix_result"],
                        "files_modified": json.loads(r["files_modified"]) if isinstance(r["files_modified"], str) else r["files_modified"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"修復ログ取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/self-healing/stats")
async def get_self_healing_stats(user: dict = Depends(get_current_user)):
    """自律修復統計"""
    try:
        from brain_alpha.self_healer import get_healing_stats
        stats = await get_healing_stats()
        return stats
    except Exception as e:
        logger.error(f"修復統計取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 判断根拠トレース API =====

@app.get("/api/traces")
async def get_traces(
    target_id: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """判断根拠トレースを取得（task_id or goal_idで絞り込み）"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if target_id:
                rows = await conn.fetch(
                    """SELECT id, agent_name, goal_id, task_id, action, reasoning,
                              confidence, context, created_at
                       FROM agent_reasoning_trace
                       WHERE task_id = $1 OR goal_id = $1
                       ORDER BY created_at DESC LIMIT $2""",
                    target_id, limit,
                )
            elif agent_name:
                rows = await conn.fetch(
                    """SELECT id, agent_name, goal_id, task_id, action, reasoning,
                              confidence, context, created_at
                       FROM agent_reasoning_trace
                       WHERE agent_name = $1
                       ORDER BY created_at DESC LIMIT $2""",
                    agent_name, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, agent_name, goal_id, task_id, action, reasoning,
                              confidence, context, created_at
                       FROM agent_reasoning_trace
                       ORDER BY created_at DESC LIMIT $1""",
                    limit,
                )
            return {
                "traces": [
                    {
                        "id": r["id"],
                        "agent_name": r["agent_name"],
                        "goal_id": r["goal_id"],
                        "task_id": r["task_id"],
                        "action": r["action"],
                        "reasoning": r["reasoning"],
                        "confidence": float(r["confidence"]) if r["confidence"] else None,
                        "context": json.loads(r["context"]) if isinstance(r["context"], str) else r["context"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"トレース取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/traces/recent")
async def get_recent_traces(
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
):
    """直近の判断根拠トレースを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, agent_name, goal_id, task_id, action, reasoning,
                          confidence, context, created_at
                   FROM agent_reasoning_trace
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            return {
                "traces": [
                    {
                        "id": r["id"],
                        "agent_name": r["agent_name"],
                        "goal_id": r["goal_id"],
                        "task_id": r["task_id"],
                        "action": r["action"],
                        "reasoning": r["reasoning"],
                        "confidence": float(r["confidence"]) if r["confidence"] else None,
                        "context": json.loads(r["context"]) if isinstance(r["context"], str) else r["context"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"直近トレース取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== CHARLIE Win11 モード切替 =====

@app.get("/api/nodes/charlie/mode")
async def get_charlie_mode(user: dict = Depends(get_current_user)):
    """CHARLIE の現在のモードを取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state, reason, changed_by, changed_at FROM node_state WHERE node_name = 'charlie'"
            )
            if not row:
                return {"mode": "unknown", "state": "unknown"}
            state = row["state"]
            mode = "win11" if state == "charlie_win11" else "ubuntu"
            return {
                "mode": mode,
                "state": state,
                "reason": row["reason"],
                "changed_by": row["changed_by"],
                "changed_at": row["changed_at"].isoformat() if row["changed_at"] else None,
            }
    except Exception as e:
        logger.error(f"CHARLIEモード取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/nodes/charlie/mode")
async def set_charlie_mode(req: CharlieModeRequest, user: dict = Depends(get_current_user)):
    """CHARLIE の Win11/Ubuntu モードを切り替える"""
    if req.mode not in ("win11", "ubuntu"):
        raise HTTPException(status_code=400, detail="mode must be 'win11' or 'ubuntu'")

    try:
        pool = await get_pg_pool()
        new_state = "charlie_win11" if req.mode == "win11" else "healthy"
        reason = "Win11切替（Web UI）" if req.mode == "win11" else "Ubuntu復帰（Web UI）"

        async with pool.acquire() as conn:
            # node_state更新
            await conn.execute(
                """UPDATE node_state
                   SET state = $1, reason = $2, changed_by = 'web_ui', changed_at = NOW()
                   WHERE node_name = 'charlie'""",
                new_state, reason,
            )

            # event_log記録
            await conn.execute(
                """INSERT INTO event_log (event_type, category, payload, severity, source_node)
                   VALUES ($1, 'node', $2, 'info', 'alpha')""",
                f"charlie.mode_{'win11' if req.mode == 'win11' else 'ubuntu'}",
                json.dumps({"node": "charlie", "new_state": new_state, "reason": reason}, ensure_ascii=False),
            )

        # Discord通知
        try:
            if req.mode == "win11":
                await notify_discord(f"CHARLIE → Win11モードに切替。タスクはBRAVO/DELTAに振替されます。")
            else:
                await notify_discord(f"CHARLIE → Ubuntu復帰。推論ノードとして再稼働します。")
        except Exception:
            pass

        # SSE通知
        await broadcast_sse_event("charlie_mode_change", {"mode": req.mode, "state": new_state})

        logger.info(f"CHARLIE モード切替: {req.mode} (state={new_state})")
        return {"status": "ok", "mode": req.mode, "state": new_state, "reason": reason}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CHARLIEモード切替エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/nodes/state")
async def get_all_node_states(user: dict = Depends(get_current_user)):
    """全ノードの状態を取得"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT node_name, state, reason, changed_by, changed_at FROM node_state ORDER BY node_name"
            )
            return {
                "nodes": [
                    {
                        "node_name": r["node_name"],
                        "state": r["state"],
                        "reason": r["reason"],
                        "changed_by": r["changed_by"],
                        "changed_at": r["changed_at"].isoformat() if r["changed_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"ノード状態取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/nodes/state/history")
async def get_node_state_history(
    node: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    user: dict = Depends(get_current_user),
):
    """ノード状態変更履歴（event_logから）"""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            if node:
                rows = await conn.fetch(
                    """SELECT event_type, payload, created_at
                       FROM event_log
                       WHERE category = 'node'
                         AND event_type LIKE 'charlie.mode_%'
                         AND payload->>'node' = $1
                       ORDER BY created_at DESC LIMIT $2""",
                    node, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT event_type, payload, created_at
                       FROM event_log
                       WHERE category = 'node'
                         AND event_type LIKE '%.mode_%'
                       ORDER BY created_at DESC LIMIT $1""",
                    limit,
                )
            return {
                "history": [
                    {
                        "event_type": r["event_type"],
                        "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"ノード履歴取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 開発用起動 =====

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
        log_level="info",
    )
