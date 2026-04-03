#!/bin/bash
# SYUTAINβ V25 CHARLIE安全シャットダウンスクリプト
# デュアルブートWin11切り替え時に使用
#
# 使用法: bash ~/syutain_beta/scripts/safe_shutdown.sh
#   または Agent Opsの「Win11に切り替え」ボタンから実行

set -euo pipefail

echo "SYUTAINβ: CHARLIEの安全なシャットダウンを開始..."

# 1. worker_main.pyをgraceful shutdown（処理中タスクの完了を待つ、最大30秒）
echo "  [1/4] ワーカー停止中（最大30秒待機）..."
sudo systemctl stop syutain-worker-charlie 2>/dev/null || true
sleep 2

# 2. NATSに「charlie.going_offline」を送信（ALPHAのOS_Kernelに通知）
echo "  [2/4] NATS通知送信中..."
nats pub charlie.going_offline "shutdown_for_win11" 2>/dev/null || true
sleep 2

# 3. NATSを停止
echo "  [3/4] NATS停止中..."
sudo systemctl stop nats-server 2>/dev/null || true

# 4. シャットダウン
echo "  [4/4] SYUTAINβ: 5秒後にシャットダウンします..."
sleep 5
sudo shutdown now
