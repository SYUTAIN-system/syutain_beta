#!/bin/bash
# SYUTAINβ V25 ヘルスチェックスクリプト (Step 23)
# 全4ノード + PostgreSQL + NATS + Ollama の状態確認
# macOS互換（declare -A を使わない — CLAUDE.md ルール14）
#
# 使用法:
#   ./health_check.sh         — 全チェック
#   ./health_check.sh --json  — JSON出力

set -uo pipefail

# ===== 設定（.envから読み込み、なければデフォルト） =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "${PROJECT_DIR}/.env" ]; then
    # .envからexport可能な行だけ読み込む
    while IFS='=' read -r key value; do
        case "$key" in
            \#*|"") continue ;;  # コメントと空行をスキップ
            *)
                value="${value%\"}"
                value="${value#\"}"
                export "$key=$value" 2>/dev/null || true
                ;;
        esac
    done < "${PROJECT_DIR}/.env"
fi

NATS_URL="${NATS_URL:-nats://localhost:4222}"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
NEXTJS_PORT="${NEXTJS_PORT:-3000}"

# Tailscale経由のノードアドレス（配列ではなくプレーン変数で管理）
ALPHA_HOST="${ALPHA_HOST:-localhost}"
BRAVO_HOST="${BRAVO_HOST:-bravo}"
CHARLIE_HOST="${CHARLIE_HOST:-charlie}"
DELTA_HOST="${DELTA_HOST:-delta}"

# ===== 色付き出力 =====
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
JSON_MODE=false

if [ "${1:-}" = "--json" ]; then
    JSON_MODE=true
fi

# 結果格納用（JSONモード用）
RESULTS=""

check_result() {
    local name="$1"
    local status="$2"  # ok / warn / fail
    local detail="$3"

    if $JSON_MODE; then
        RESULTS="${RESULTS}{\"name\":\"${name}\",\"status\":\"${status}\",\"detail\":\"${detail}\"},"
    else
        case "$status" in
            ok)   echo -e "  ${GREEN}[OK]${NC}   ${name}: ${detail}" ;;
            warn) echo -e "  ${YELLOW}[WARN]${NC} ${name}: ${detail}" ;;
            fail) echo -e "  ${RED}[FAIL]${NC} ${name}: ${detail}" ;;
        esac
    fi
}

# ===== チェック関数 =====

check_postgresql() {
    if pg_isready -q 2>/dev/null; then
        check_result "PostgreSQL" "ok" "稼働中"
    else
        check_result "PostgreSQL" "fail" "停止中または接続不可"
    fi
}

check_nats() {
    # NATSの疎通確認（ポートチェック）
    local nats_host
    local nats_port
    nats_host=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f1)
    nats_port=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f2)
    nats_port="${nats_port:-4222}"

    if nc -z "$nats_host" "$nats_port" 2>/dev/null; then
        check_result "NATS" "ok" "稼働中 (${nats_host}:${nats_port})"
    else
        check_result "NATS" "fail" "停止中 (${nats_host}:${nats_port})"
    fi
}

check_ollama() {
    local host="${1:-localhost}"
    local port="${2:-11434}"
    local node_name="${3:-local}"

    if curl -s --connect-timeout 3 "http://${host}:${port}/api/tags" >/dev/null 2>&1; then
        local models
        models=$(curl -s --connect-timeout 3 "http://${host}:${port}/api/tags" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    names = [m['name'] for m in data.get('models', [])]
    print(', '.join(names) if names else 'モデルなし')
except:
    print('解析失敗')
" 2>/dev/null || echo "解析失敗")
        check_result "Ollama (${node_name})" "ok" "稼働中 — モデル: ${models}"
    else
        check_result "Ollama (${node_name})" "fail" "停止中 (${host}:${port})"
    fi
}

check_fastapi() {
    if curl -s --connect-timeout 3 "http://localhost:${FASTAPI_PORT}/health" >/dev/null 2>&1; then
        check_result "FastAPI" "ok" "稼働中 (port ${FASTAPI_PORT})"
    else
        check_result "FastAPI" "fail" "停止中 (port ${FASTAPI_PORT})"
    fi
}

check_nextjs() {
    if curl -s --connect-timeout 3 "http://localhost:${NEXTJS_PORT}" >/dev/null 2>&1; then
        check_result "Next.js" "ok" "稼働中 (port ${NEXTJS_PORT})"
    else
        check_result "Next.js" "fail" "停止中 (port ${NEXTJS_PORT})"
    fi
}

check_node_reachable() {
    local name="$1"
    local host="$2"

    if [ "$host" = "localhost" ] || [ "$host" = "127.0.0.1" ]; then
        check_result "${name}" "ok" "ローカル"
        return
    fi

    if ping -c 1 -W 3 "$host" >/dev/null 2>&1; then
        check_result "${name}" "ok" "到達可能 (${host})"
    else
        check_result "${name}" "fail" "到達不可 (${host})"
    fi
}

# ===== メイン =====

if ! $JSON_MODE; then
    echo ""
    echo "========== SYUTAINβ V25 ヘルスチェック =========="
    echo ""
    echo "--- インフラサービス ---"
fi

check_postgresql
check_nats

if ! $JSON_MODE; then
    echo ""
    echo "--- アプリケーション (ALPHA) ---"
fi

check_fastapi
check_nextjs

if ! $JSON_MODE; then
    echo ""
    echo "--- ノード到達性 ---"
fi

check_node_reachable "ALPHA" "$ALPHA_HOST"
check_node_reachable "BRAVO" "$BRAVO_HOST"
check_node_reachable "CHARLIE" "$CHARLIE_HOST"
check_node_reachable "DELTA" "$DELTA_HOST"

if ! $JSON_MODE; then
    echo ""
    echo "--- Ollama (ローカルLLM) ---"
fi

check_ollama "$ALPHA_HOST" 11434 "ALPHA"
check_ollama "$BRAVO_HOST" 11434 "BRAVO"
check_ollama "$CHARLIE_HOST" 11434 "CHARLIE"
check_ollama "$DELTA_HOST" 11434 "DELTA"

if ! $JSON_MODE; then
    echo ""
    echo "========== チェック完了 =========="
    echo ""
fi

# JSON出力
if $JSON_MODE; then
    # 末尾のカンマを除去して配列にする
    RESULTS="${RESULTS%,}"
    echo "[${RESULTS}]"
fi
