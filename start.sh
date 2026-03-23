#!/bin/bash
# SYUTAINβ V25 ALPHA サービス管理スクリプト（launchd対応版）
# macOS互換（declare -A を使わない — CLAUDE.md ルール14）
#
# 使用法:
#   ./start.sh start   — 全サービス起動（launchd経由）
#   ./start.sh stop    — 全サービス停止
#   ./start.sh restart — 再起動
#   ./start.sh status  — ステータス確認
#
# 自律復帰: launchd KeepAlive=true により、プロセスが死んでも自動復帰する。
#           Mac再起動後も RunAtLoad=true で自動起動する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="${SCRIPT_DIR}/logs"
WEB_DIR="${SCRIPT_DIR}/web"
mkdir -p "$LOG_DIR"

# launchdサービス一覧（NATSは既存の com.syutain.nats-server を使用）
LAUNCHD_SERVICES="com.syutain.nats-server com.syutain.fastapi com.syutain.nextjs com.syutain.scheduler com.syutain.caddy"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[SYUTAIN]${NC} $1"; }
warn()  { echo -e "${YELLOW}[SYUTAIN]${NC} $1"; }
error() { echo -e "${RED}[SYUTAIN]${NC} $1"; }

# ===== PostgreSQL =====
ensure_postgresql() {
    if pg_isready -q 2>/dev/null; then
        info "PostgreSQL: 稼働中"
    else
        info "PostgreSQL 起動中..."
        brew services start postgresql@17 2>/dev/null || brew services start postgresql 2>/dev/null || true
        for i in $(seq 1 10); do
            pg_isready -q 2>/dev/null && break
            sleep 1
        done
        pg_isready -q 2>/dev/null && info "PostgreSQL: 起動完了" || warn "PostgreSQL: 起動に時間がかかっています"
    fi
}

# ===== コード同期 =====
sync_to_workers() {
    info "Code sync to workers..."
    for NODE in 100.75.146.9 100.70.161.106 100.82.81.105; do
        rsync -az --delete \
            --exclude '.env' --exclude 'node_modules' --exclude 'data/' \
            --exclude 'logs/' --exclude '.next/' --exclude '__pycache__/' \
            --exclude 'venv/' --exclude 'browser_layer2/node_modules' \
            "${SCRIPT_DIR}/" "shimahara@${NODE}:~/syutain_beta/" 2>/dev/null && \
            info "  ${NODE}: synced" || warn "  ${NODE}: sync failed (continuing)"
    done
}

# ===== launchdサービス制御 =====
start_services() {
    info "========== SYUTAINβ V25 起動（launchd） =========="

    ensure_postgresql

    # Next.jsビルド確認
    if [ ! -d "${WEB_DIR}/.next" ] || [ ! -f "${WEB_DIR}/.next/BUILD_ID" ]; then
        info "Next.js ビルド中..."
        cd "$WEB_DIR" && npm run build 2>&1 | tail -3
        cd "$SCRIPT_DIR"
    fi

    for svc in $LAUNCHD_SERVICES; do
        plist=~/Library/LaunchAgents/$svc.plist
        if [ -f "$plist" ]; then
            launchctl load "$plist" 2>/dev/null
            info "  Started: $svc"
        else
            warn "  Missing: $plist"
        fi
    done

    sleep 10
    info "========== 全サービス起動完了 =========="
    echo ""
    info "FastAPI:  http://localhost:8000"
    info "Next.js:  http://localhost:3000"
    info "NATS:     nats://localhost:4222"
    info "Caddy:    https://localhost:8443"
    echo ""
}

stop_services() {
    info "========== SYUTAINβ V25 停止 =========="

    for svc in $LAUNCHD_SERVICES; do
        plist=~/Library/LaunchAgents/$svc.plist
        if [ -f "$plist" ]; then
            launchctl unload "$plist" 2>/dev/null
            info "  Stopped: $svc"
        fi
    done

    # 残存プロセスのクリーンアップ
    pkill -f "uvicorn.*app:app" 2>/dev/null || true
    pkill -f "next-server" 2>/dev/null || true
    pkill -f "scheduler.py" 2>/dev/null || true
    lsof -ti :3000 2>/dev/null | xargs kill -9 2>/dev/null || true
    lsof -ti :8000 2>/dev/null | xargs kill -9 2>/dev/null || true
    caddy stop 2>/dev/null || true

    sleep 3
    info "========== 全サービス停止完了 =========="
}

show_status() {
    info "========== SYUTAINβ V25 ステータス =========="
    echo ""

    # PostgreSQL
    pg_isready -q 2>/dev/null && info "PostgreSQL: ${GREEN}稼働中${NC}" || error "PostgreSQL: ${RED}停止${NC}"

    # launchdサービス
    for svc in $LAUNCHD_SERVICES; do
        INFO=$(launchctl list 2>/dev/null | grep "$svc" || true)
        if [ -n "$INFO" ]; then
            PID=$(echo "$INFO" | awk '{print $1}')
            STATUS=$(echo "$INFO" | awk '{print $2}')
            info "$svc: ${GREEN}PID=$PID Status=$STATUS${NC}"
        else
            error "$svc: ${RED}NOT LOADED${NC}"
        fi
    done

    echo ""
    info "ポート確認:"
    for PORT_NAME in "4222:NATS" "8000:FastAPI" "3000:Next.js" "8443:Caddy"; do
        PORT="${PORT_NAME%%:*}"
        NAME="${PORT_NAME##*:}"
        PID=$(lsof -ti :$PORT 2>/dev/null | head -1)
        if [ -n "$PID" ]; then
            info "  $NAME(:$PORT): ${GREEN}PID=$PID${NC}"
        else
            error "  $NAME(:$PORT): ${RED}NOT LISTENING${NC}"
        fi
    done

    echo ""
    info "ヘルスチェック:"
    curl -s http://localhost:8000/health | python3 -c "import sys,json;print('  FastAPI:',json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "  FastAPI: DOWN"
    curl -s -o /dev/null -w "  Next.js: %{http_code}\n" http://localhost:3000/ 2>/dev/null
    curl -sk -o /dev/null -w "  HTTPS: %{http_code}\n" https://localhost:8443/ 2>/dev/null
    echo ""
}

# ===== エントリーポイント =====
case "${1:-start}" in
    start)
        sync_to_workers
        start_services
        show_status
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        sleep 3
        sync_to_workers
        start_services
        show_status
        ;;
    status)
        show_status
        ;;
    *)
        echo "使用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
