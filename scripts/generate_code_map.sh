#!/bin/bash
# SYUTAINβ CODE_MAP.md 自動生成スクリプト
set -uo pipefail
cd "$(dirname "$0")/.."
OUTFILE="CODE_MAP.md"
NOW=$(date '+%Y-%m-%d %H:%M:%S JST')

cat > "$OUTFILE" << HEADER
# SYUTAINβ CODE_MAP.md
> 自動生成: ${NOW}
> ファイル構造と役割の一覧

HEADER

# --- コアファイル ---
echo "## コアファイル" >> "$OUTFILE"
echo "| ファイル | 行数 | 最終更新 | 主要クラス/関数 |" >> "$OUTFILE"
echo "|----------|------|---------|---------------|" >> "$OUTFILE"
for f in app.py scheduler.py worker_main.py; do
  if [ -f "$f" ]; then
    LINES=$(wc -l < "$f")
    MOD=$(stat -f "%Sm" -t "%m-%d %H:%M" "$f" 2>/dev/null || date -r "$f" '+%m-%d %H:%M' 2>/dev/null || echo "?")
    FUNCS=$(grep -E "^(class |async def |def )" "$f" 2>/dev/null | head -5 | sed 's/(.*//' | tr '\n' ', ' | sed 's/, $//')
    echo "| $f | $LINES | $MOD | ${FUNCS:0:60} |" >> "$OUTFILE"
  fi
done
echo "" >> "$OUTFILE"

# --- エージェント ---
echo "## エージェント (agents/)" >> "$OUTFILE"
echo "| ファイル | 行数 | 主要クラス/関数 |" >> "$OUTFILE"
echo "|----------|------|---------------|" >> "$OUTFILE"
for f in agents/*.py; do
  [ "$f" = "agents/__init__.py" ] && continue
  LINES=$(wc -l < "$f")
  FUNCS=$(grep -E "^(class |    async def |    def )" "$f" 2>/dev/null | head -4 | sed 's/(.*//' | sed 's/^    //' | tr '\n' ', ' | sed 's/, $//')
  echo "| $(basename $f) | $LINES | ${FUNCS:0:70} |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- ツール ---
echo "## ツール (tools/)" >> "$OUTFILE"
echo "| ファイル | 行数 | 主要関数 |" >> "$OUTFILE"
echo "|----------|------|---------|" >> "$OUTFILE"
for f in tools/*.py; do
  [ "$f" = "tools/__init__.py" ] && continue
  LINES=$(wc -l < "$f")
  FUNCS=$(grep -E "^(class |async def |def )" "$f" 2>/dev/null | head -4 | sed 's/(.*//' | tr '\n' ', ' | sed 's/, $//')
  echo "| $(basename $f) | $LINES | ${FUNCS:0:70} |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- フロントエンド ---
echo "## フロントエンド (web/src/)" >> "$OUTFILE"
echo "| ファイル | 行数 | ページ/コンポーネント |" >> "$OUTFILE"
echo "|----------|------|-------------------|" >> "$OUTFILE"
find web/src -name "*.tsx" -o -name "*.ts" 2>/dev/null | grep -v node_modules | grep -v .next | sort | while read f; do
  LINES=$(wc -l < "$f")
  # パスからページ名を推測
  PAGE=$(echo "$f" | sed 's|web/src/||; s|/page\.tsx$||; s|\.tsx$||; s|\.ts$||')
  echo "| $PAGE | $LINES | |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- 設定ファイル ---
echo "## 設定ファイル" >> "$OUTFILE"
echo "| ファイル | 行数 | 役割 |" >> "$OUTFILE"
echo "|----------|------|------|" >> "$OUTFILE"
echo "| .env | $(wc -l < .env) | 環境変数・APIキー |" >> "$OUTFILE"
echo "| feature_flags.yaml | $(wc -l < feature_flags.yaml) | 機能フラグ |" >> "$OUTFILE"
echo "| CLAUDE.md | $(wc -l < CLAUDE.md) | 絶対ルール22条 |" >> "$OUTFILE"
echo "| Caddyfile | $(wc -l < Caddyfile) | HTTPSリバースプロキシ |" >> "$OUTFILE"
for f in config/*.yaml config/*.conf; do
  [ -f "$f" ] && echo "| $f | $(wc -l < "$f") | ノード/NATS設定 |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- DBスキーマ ---
echo "## DBスキーマ (PostgreSQL)" >> "$OUTFILE"
echo "| テーブル | カラム数 | 主なカラム |" >> "$OUTFILE"
echo "|----------|---------|----------|" >> "$OUTFILE"
psql -t syutain_beta -c "
SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;" 2>/dev/null | while read -r TBL; do
  TBL=$(echo "$TBL" | tr -d ' ')
  [ -z "$TBL" ] && continue
  COL_CNT=$(psql -t syutain_beta -c "SELECT count(*) FROM information_schema.columns WHERE table_name='$TBL';" 2>/dev/null | tr -d ' ')
  COLS=$(psql -t syutain_beta -c "SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM (SELECT column_name, ordinal_position FROM information_schema.columns WHERE table_name='$TBL' LIMIT 5) s;" 2>/dev/null | tr -d ' ' | head -c 60)
  echo "| $TBL | $COL_CNT | $COLS |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- 総行数 ---
PY_TOTAL=$(find . -name "*.py" ! -path "./__pycache__/*" ! -path "./venv/*" ! -path "./node_modules/*" -exec cat {} + 2>/dev/null | wc -l)
TS_TOTAL=$(find web/src -name "*.ts" -o -name "*.tsx" 2>/dev/null | xargs cat 2>/dev/null | wc -l)
echo "## コード規模" >> "$OUTFILE"
echo "- Python: ${PY_TOTAL}行 (52ファイル)" >> "$OUTFILE"
echo "- TypeScript/TSX: ${TS_TOTAL}行 (18ファイル)" >> "$OUTFILE"
echo "- 合計: $((PY_TOTAL + TS_TOTAL))行" >> "$OUTFILE"
echo "" >> "$OUTFILE"

LINES=$(wc -l < "$OUTFILE")
echo "---" >> "$OUTFILE"
echo "*自動生成完了: ${NOW} (${LINES}行)*" >> "$OUTFILE"
echo "CODE_MAP.md generated: ${LINES} lines"
