#!/bin/bash
# Nemotron-Nano-8B-v2-Japanese インストールスクリプト
# 使用方法:
#   1. HuggingFaceでnvidiaモデルのライセンスに同意
#   2. HF_TOKEN=hf_xxxxx を設定
#   3. このスクリプトをBRAVO/CHARLIEで実行
#
# bash install_nemotron.sh [bravo|charlie]

set -e

NODE=${1:-bravo}
HF_TOKEN=${HF_TOKEN:-""}
MODEL_DIR="/home/shimahara/models"
GGUF_FILE="Nemotron-Nano-8B-v2-Japanese-Q4_K_M.gguf"
GGUF_URL="https://huggingface.co/mmnga/Nemotron-Nano-8B-v2-Japanese-gguf/resolve/main/${GGUF_FILE}"

if [ -z "$HF_TOKEN" ]; then
    echo "エラー: HF_TOKEN を設定してください"
    echo "  export HF_TOKEN=hf_xxxxxxxx"
    echo "  bash install_nemotron.sh"
    exit 1
fi

echo "=== Nemotron-Nano-8B-v2-Japanese インストール ==="
echo "ノード: $NODE"
echo "モデルディレクトリ: $MODEL_DIR"

# ディレクトリ作成
mkdir -p "$MODEL_DIR"

# ダウンロード
echo "GGUFダウンロード中..."
curl -L -H "Authorization: Bearer $HF_TOKEN" \
     -o "${MODEL_DIR}/${GGUF_FILE}" \
     "$GGUF_URL"

FILESIZE=$(stat -c%s "${MODEL_DIR}/${GGUF_FILE}" 2>/dev/null || stat -f%z "${MODEL_DIR}/${GGUF_FILE}")
if [ "$FILESIZE" -lt 1000000 ]; then
    echo "エラー: ダウンロード失敗（ファイルサイズ: ${FILESIZE}バイト）"
    echo "HF_TOKENを確認してください"
    cat "${MODEL_DIR}/${GGUF_FILE}"
    exit 1
fi

echo "ダウンロード完了: ${FILESIZE} バイト"

# Modelfile作成
cat > "${MODEL_DIR}/Modelfile.nemotron-jp" << 'EOF'
FROM ./Nemotron-Nano-8B-v2-Japanese-Q4_K_M.gguf

PARAMETER num_ctx 32768
PARAMETER temperature 0.7
PARAMETER top_p 0.9

TEMPLATE """{{- if .System }}<extra_id_0>System
{{ .System }}
{{ end }}<extra_id_1>User
{{ .Prompt }}
<extra_id_1>Assistant
{{ .Response }}"""

SYSTEM "あなたは島原大知のAI事業パートナー SYUTAINβ です。日本語で正確かつ自然に応答してください。"
EOF

# Ollamaに登録
echo "Ollamaにモデル登録中..."
cd "$MODEL_DIR"
ollama create nemotron-jp -f Modelfile.nemotron-jp

# 動作確認
echo "=== 動作確認 ==="
ollama run nemotron-jp "こんにちは。一言で自己紹介してください。" --verbose 2>&1 | head -10

echo ""
echo "=== ollama list ==="
ollama list

echo ""
echo "=== インストール完了 ==="
echo "モデル名: nemotron-jp"
echo "コマンド: ollama run nemotron-jp"
