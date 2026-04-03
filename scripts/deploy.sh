#!/bin/bash
# SYUTAINβ デプロイスクリプト — BRAVO/CHARLIE/DELTAへの主要ファイル同期 + worker再起動
# macOS bash 3.2互換（declare -A 不使用）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSH_USER="${REMOTE_SSH_USER:-user}"

# ノード定義（declare -A 不使用 / .envから読むか、ここに記入）
BRAVO_IP="${BRAVO_IP:-127.0.0.1}"
CHARLIE_IP="${CHARLIE_IP:-127.0.0.1}"
DELTA_IP="${DELTA_IP:-127.0.0.1}"

NODE_NAMES="bravo charlie delta"
REMOTE_DIR="~/syutain_beta"

# Discord通知用Webhook
DISCORD_WEBHOOK="${DISCORD_WEBHOOK_URL:-}"

# 同期対象ファイル
SYNC_FILES="
agents/
brain_alpha/
tools/
bots/
worker_main.py
scheduler.py
CLAUDE.md
"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

notify_discord() {
    if [ -n "$DISCORD_WEBHOOK" ]; then
        curl -s -H "Content-Type: application/json" \
            -d "{\"username\": \"SYUTAINβ Deploy\", \"content\": \"$1\"}" \
            "$DISCORD_WEBHOOK" > /dev/null 2>&1 || true
    fi
}

get_ip() {
    case "$1" in
        bravo)  echo "$BRAVO_IP" ;;
        charlie) echo "$CHARLIE_IP" ;;
        delta)  echo "$DELTA_IP" ;;
        *)      echo "" ;;
    esac
}

deploy_node() {
    local node="$1"
    local ip
    ip="$(get_ip "$node")"

    if [ -z "$ip" ]; then
        log "ERROR: 不明なノード: $node"
        return 1
    fi

    log "[$node] デプロイ開始 ($ip)"

    # SSH疎通チェック（3秒タイムアウト）
    if ! ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" "echo ok" > /dev/null 2>&1; then
        log "[$node] SSH接続失敗 — スキップ"
        return 1
    fi

    # ファイル同期
    local sync_ok=true
    for item in $SYNC_FILES; do
        local src="${PROJECT_DIR}/${item}"
        local dst="${SSH_USER}@${ip}:${REMOTE_DIR}/${item}"

        if [ -d "$src" ]; then
            # ディレクトリ
            scp -r -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
                "$src" "${SSH_USER}@${ip}:${REMOTE_DIR}/" 2>/dev/null || sync_ok=false
        elif [ -f "$src" ]; then
            # ファイル
            scp -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
                "$src" "$dst" 2>/dev/null || sync_ok=false
        fi
    done

    if [ "$sync_ok" = false ]; then
        log "[$node] 一部ファイル同期失敗"
    fi

    # worker再起動
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" \
        "cd ${REMOTE_DIR} && sudo systemctl restart syutain-worker 2>/dev/null || true" 2>/dev/null || true

    log "[$node] デプロイ完了"
    return 0
}

# メイン処理
main() {
    log "=== SYUTAINβ デプロイ開始 ==="
    notify_discord "🚀 デプロイ開始: BRAVO/CHARLIE/DELTA"

    local success_nodes=""
    local failed_nodes=""

    for node in $NODE_NAMES; do
        if deploy_node "$node"; then
            success_nodes="${success_nodes} ${node}"
        else
            failed_nodes="${failed_nodes} ${node}"
        fi
    done

    # 結果通知
    local msg="🚀 デプロイ完了"
    if [ -n "$success_nodes" ]; then
        msg="${msg}\n✅ 成功:${success_nodes}"
    fi
    if [ -n "$failed_nodes" ]; then
        msg="${msg}\n❌ 失敗:${failed_nodes}"
    fi

    log "=== デプロイ完了 ==="
    notify_discord "$msg"
}

main "$@"
