#!/bin/bash
# SYUTAINβ V25 systemdサービス設定 (Step 23)
# BRAVO / CHARLIE / DELTA 用 systemd ユニットファイル生成
#
# 使用法（対象ノード上で実行）:
#   sudo bash setup_systemd.sh bravo
#   sudo bash setup_systemd.sh charlie
#   sudo bash setup_systemd.sh delta

set -euo pipefail

NODE="${1:-}"
if [ -z "$NODE" ]; then
    echo "使用法: sudo bash $0 {bravo|charlie|delta}"
    exit 1
fi

# ===== 設定 =====
SYUTAIN_USER="${SYUTAIN_USER:-$(whoami)}"
SYUTAIN_DIR="${SYUTAIN_DIR:-/home/${SYUTAIN_USER}/syutain_beta}"
VENV_DIR="${SYUTAIN_DIR}/venv"
PYTHON="${VENV_DIR}/bin/python"
SERVICE_NAME="syutain-worker-${NODE}"

echo "========== SYUTAINβ systemd設定 =========="
echo "ノード:       ${NODE}"
echo "ユーザー:     ${SYUTAIN_USER}"
echo "ディレクトリ: ${SYUTAIN_DIR}"
echo "Python:       ${PYTHON}"
echo ""

# ===== ワーカーサービス =====
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=SYUTAINβ V25 Worker (${NODE})
After=network-online.target postgresql.service nats-server.service
Wants=network-online.target

[Service]
Type=simple
User=${SYUTAIN_USER}
Group=${SYUTAIN_USER}
WorkingDirectory=${SYUTAIN_DIR}
Environment="THIS_NODE=${NODE}"
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=${SYUTAIN_DIR}/.env
ExecStart=${PYTHON} ${SYUTAIN_DIR}/worker_main.py
Restart=always
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=5

# リソース制限
LimitNOFILE=65536
LimitNPROC=4096

# ログ
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
UNIT

echo "[OK] ${SERVICE_NAME}.service を作成しました"

# ===== NATSサービス（ノード側クライアントは不要だが、念のためサーバーのユニットも用意） =====
if [ ! -f "/etc/systemd/system/nats-server.service" ]; then
    cat > "/etc/systemd/system/nats-server.service" <<UNIT
[Unit]
Description=NATS Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nats-server -c /etc/nats/nats-server.conf
Restart=always
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
    echo "[OK] nats-server.service を作成しました（必要な場合のみ）"
fi

# ===== Ollama サービス（ローカルLLM用） =====
OLLAMA_SERVICE="syutain-ollama-${NODE}"
cat > "/etc/systemd/system/${OLLAMA_SERVICE}.service" <<UNIT
[Unit]
Description=Ollama LLM Server for SYUTAINβ (${NODE})
After=network-online.target

[Service]
Type=simple
User=${SYUTAIN_USER}
Group=${SYUTAIN_USER}
Environment="OLLAMA_HOST=0.0.0.0:11434"
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

echo "[OK] ${OLLAMA_SERVICE}.service を作成しました"

# ===== systemd リロード・有効化 =====
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl enable "${OLLAMA_SERVICE}.service"

echo ""
echo "========== 設定完了 =========="
echo ""
echo "以下のコマンドでサービスを管理できます:"
echo ""
echo "  起動:    sudo systemctl start ${SERVICE_NAME}"
echo "  停止:    sudo systemctl stop ${SERVICE_NAME}"
echo "  再起動:  sudo systemctl restart ${SERVICE_NAME}"
echo "  状態:    sudo systemctl status ${SERVICE_NAME}"
echo "  ログ:    sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  Ollama:  sudo systemctl start ${OLLAMA_SERVICE}"
echo ""
echo "全サービス一括起動:"
echo "  sudo systemctl start ${OLLAMA_SERVICE} && sudo systemctl start ${SERVICE_NAME}"
echo ""
