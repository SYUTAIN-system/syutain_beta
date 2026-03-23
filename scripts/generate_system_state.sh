#!/bin/bash
# SYUTAINβ SYSTEM_STATE.md 自動生成スクリプト
# Usage: bash scripts/generate_system_state.sh [--light]
# --light: DB統計とプロセス状態のみ（5分間隔の軽量更新用）

set -uo pipefail
cd "$(dirname "$0")/.."
OUTFILE="SYSTEM_STATE.md"
LIGHT_MODE="${1:-}"
NOW=$(date '+%Y-%m-%d %H:%M:%S JST')
DB="syutain_beta"

cat > "$OUTFILE" << HEADER
# SYUTAINβ SYSTEM_STATE.md
> 自動生成: ${NOW}
> このファイルはClaude Codeセッション開始時に最初に読むべきファイル

HEADER

# --- システム概要 ---
cat >> "$OUTFILE" << 'SECTION'
## システム概要
- プロジェクト: ~/syutain_beta
- 設計書: SYUTAINβ_完全設計書_V25.md
- 実装仕様: docs/IMPLEMENTATION_SPEC.md
- 絶対ルール: CLAUDE.md（22条）
- SSH: BRAVO=shimahara@100.75.146.9 / CHARLIE=shimahara@100.70.161.106 / DELTA=shimahara@100.82.81.105

SECTION

# --- ノード構成 ---
echo "## ノード構成" >> "$OUTFILE"
echo "| ノード | IP | worker | nats | ollama | LLMモデル | GPU |" >> "$OUTFILE"
echo "|--------|-----|--------|------|--------|-----------|-----|" >> "$OUTFILE"

# ALPHA
ALPHA_PROCS=$(ps aux | grep -E "uvicorn|next-server|nats-server|caddy|scheduler" | grep -v grep | wc -l | tr -d ' ')
echo "| ALPHA | local | ${ALPHA_PROCS}procs | ok | - | MLX(on-demand) | M4 Pro |" >> "$OUTFILE"

# Remote nodes
for NODE_INFO in "100.75.146.9:BRAVO:RTX5070-12GB" "100.70.161.106:CHARLIE:RTX3080-10GB" "100.82.81.105:DELTA:GTX980Ti-6GB"; do
  IFS=':' read -r IP NAME GPU <<< "$NODE_INFO"
  WORKER=$(ssh -o ConnectTimeout=3 shimahara@$IP "systemctl is-active syutain-worker-$(echo $NAME | tr '[:upper:]' '[:lower:]')" 2>/dev/null || echo "?")
  NATS=$(ssh -o ConnectTimeout=3 shimahara@$IP "systemctl is-active syutain-nats" 2>/dev/null || echo "?")
  OLLAMA=$(ssh -o ConnectTimeout=3 shimahara@$IP "systemctl is-active ollama" 2>/dev/null || echo "?")
  MODEL=$(ssh -o ConnectTimeout=3 shimahara@$IP "curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c \"import sys,json;d=json.load(sys.stdin);print(','.join(m['name'] for m in d.get('models',[])))\" 2>/dev/null" || echo "?")
  echo "| $NAME | $IP | $WORKER | $NATS | $OLLAMA | $MODEL | $GPU |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- サービス状態 ---
echo "## サービス状態" >> "$OUTFILE"
FASTAPI=$(curl -s http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','DOWN'))" 2>/dev/null || echo "DOWN")
NEXTJS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "000")
echo "- FastAPI: ${FASTAPI} (:8000)" >> "$OUTFILE"
echo "- Next.js: HTTP ${NEXTJS} (:3000)" >> "$OUTFILE"
echo "- Caddy: :8443 (HTTPS)" >> "$OUTFILE"
echo "" >> "$OUTFILE"

# --- DB統計 ---
echo "## DB統計" >> "$OUTFILE"
echo "| テーブル | 件数 |" >> "$OUTFILE"
echo "|----------|------|" >> "$OUTFILE"
for TBL in goal_packets tasks proposal_history intel_items chat_messages llm_cost_log approval_queue event_log revenue_linkage browser_action_log; do
  CNT=$(psql -t $DB -c "SELECT count(*) FROM $TBL;" 2>/dev/null | tr -d ' ')
  echo "| $TBL | ${CNT:-0} |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- LLM使用率 ---
echo "## LLM使用率" >> "$OUTFILE"
psql -t -A -F'|' $DB -c "
SELECT
  CASE WHEN model ILIKE '%qwen%' OR tier='L' THEN 'local' ELSE 'api' END as type,
  count(*) as cnt,
  round(count(*)::numeric / NULLIF((SELECT count(*) FROM llm_cost_log),0) * 100, 1) as pct
FROM llm_cost_log GROUP BY type ORDER BY type;" 2>/dev/null | while IFS='|' read -r TYPE CNT PCT; do
  [ -n "$TYPE" ] && echo "- ${TYPE}: ${CNT}件 (${PCT}%)" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- API接続状態 ---
echo "## API接続状態" >> "$OUTFILE"
for KEY in DEEPSEEK_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY BLUESKY_APP_PASSWORD TAVILY_API_KEY JINA_API_KEY YOUTUBE_API_KEY DISCORD_WEBHOOK_URL; do
  VAL=$(grep "^$KEY=" .env 2>/dev/null | cut -d= -f2)
  STATUS=$([ -n "$VAL" ] && echo "SET" || echo "NOT SET")
  echo "- $KEY: $STATUS" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# Light mode stops here
if [ "$LIGHT_MODE" = "--light" ]; then
  echo "---" >> "$OUTFILE"
  echo "*軽量更新モード ($(date '+%H:%M:%S'))*" >> "$OUTFILE"
  echo "SYSTEM_STATE.md generated (light): $(wc -l < "$OUTFILE") lines"
  exit 0
fi

# --- Schedulerジョブ ---
echo "## Schedulerジョブ" >> "$OUTFILE"
echo "| ジョブ | 間隔/時刻 |" >> "$OUTFILE"
echo "|--------|-----------|" >> "$OUTFILE"
grep -E "name=\".*（" scheduler.py 2>/dev/null | sed 's/.*name="/| /; s/",$//' | sed 's/（/ | /; s/）/ |/' >> "$OUTFILE"
echo "" >> "$OUTFILE"

# --- パイプライン状態 ---
echo "## 収益パイプライン (Stage 1-11)" >> "$OUTFILE"
INTEL_CNT=$(psql -t $DB -c "SELECT count(*) FROM intel_items WHERE created_at > NOW() - INTERVAL '24 hours';" 2>/dev/null | tr -d ' ')
PROPOSAL_CNT=$(psql -t $DB -c "SELECT count(*) FROM proposal_history WHERE created_at > NOW() - INTERVAL '7 days';" 2>/dev/null | tr -d ' ')
GOAL_ACTIVE=$(psql -t $DB -c "SELECT count(*) FROM goal_packets WHERE status='active';" 2>/dev/null | tr -d ' ')
TASK_SUCCESS=$(psql -t $DB -c "SELECT count(*) FROM tasks WHERE status IN ('success','completed');" 2>/dev/null | tr -d ' ')
QUALITY_AVG=$(psql -t $DB -c "SELECT round(avg(quality_score)::numeric,2) FROM tasks WHERE quality_score > 0;" 2>/dev/null | tr -d ' ')
ARTIFACT_CNT=$(ls data/artifacts/*.md 2>/dev/null | wc -l | tr -d ' ')
BSKY_CNT=$(psql -t $DB -c "SELECT count(*) FROM event_log WHERE event_type='sns.posted';" 2>/dev/null | tr -d ' ')
REV_TOTAL=$(psql -t $DB -c "SELECT COALESCE(SUM(revenue_jpy),0) FROM revenue_linkage;" 2>/dev/null | tr -d ' ')
echo "- Stage1 情報収集: ${INTEL_CNT:-0}件(24h)" >> "$OUTFILE"
echo "- Stage3 提案: ${PROPOSAL_CNT:-0}件(7d)" >> "$OUTFILE"
echo "- Stage5 ゴール: ${GOAL_ACTIVE:-0}件active" >> "$OUTFILE"
echo "- Stage6 タスク: ${TASK_SUCCESS:-0}件成功" >> "$OUTFILE"
echo "- Stage8 品質平均: ${QUALITY_AVG:-0}" >> "$OUTFILE"
echo "- Stage9 成果物: ${ARTIFACT_CNT:-0}件" >> "$OUTFILE"
echo "- Stage10 SNS: ${BSKY_CNT:-0}件" >> "$OUTFILE"
echo "- Stage11 収益: ¥${REV_TOTAL:-0}" >> "$OUTFILE"
echo "" >> "$OUTFILE"

# --- 直近エラー ---
echo "## 直近エラー (24h)" >> "$OUTFILE"
ERRORS=$(psql -t $DB -c "
SELECT event_type || ' [' || source_node || '] ' || COALESCE(payload->>'error', payload->>'reason', '')
FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC LIMIT 5;" 2>/dev/null)
if [ -n "$ERRORS" ]; then
  echo "$ERRORS" | while read -r line; do
    [ -n "$line" ] && echo "- $line" >> "$OUTFILE"
  done
else
  echo "- なし" >> "$OUTFILE"
fi
echo "" >> "$OUTFILE"

# --- 問題自動検出 ---
echo "## 自動検出された課題" >> "$OUTFILE"

# パイプライン切断
if [ "${INTEL_CNT:-0}" -eq 0 ]; then
  echo "- **WARNING**: Stage1 情報収集が24時間ゼロ" >> "$OUTFILE"
fi

# ノード遊び
LOCAL_CNT=$(psql -t $DB -c "SELECT count(*) FROM llm_cost_log WHERE (model ILIKE '%qwen%' OR tier='L') AND recorded_at > NOW() - INTERVAL '24 hours';" 2>/dev/null | tr -d ' ')
TOTAL_CNT=$(psql -t $DB -c "SELECT count(*) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours';" 2>/dev/null | tr -d ' ')
if [ "${TOTAL_CNT:-0}" -gt 0 ]; then
  LOCAL_PCT=$(echo "scale=0; ${LOCAL_CNT:-0} * 100 / ${TOTAL_CNT}" | bc 2>/dev/null || echo "0")
  if [ "${LOCAL_PCT:-0}" -lt 20 ]; then
    echo "- **WARNING**: ローカルLLM使用率${LOCAL_PCT}% — API過剰使用" >> "$OUTFILE"
  fi
fi

# エラー急増
ERR_1H=$(psql -t $DB -c "SELECT count(*) FROM event_log WHERE severity='error' AND created_at > NOW() - INTERVAL '1 hour';" 2>/dev/null | tr -d ' ')
if [ "${ERR_1H:-0}" -gt 10 ]; then
  echo "- **CRITICAL**: 直近1時間でエラー${ERR_1H}件" >> "$OUTFILE"
fi

# 成果物ゼロ
if [ "${ARTIFACT_CNT:-0}" -eq 0 ]; then
  echo "- **WARNING**: 品質0.5以上の成果物ファイルがゼロ" >> "$OUTFILE"
fi

# SNS停止
if [ "${BSKY_CNT:-0}" -eq 0 ]; then
  echo "- **INFO**: Bluesky投稿実績ゼロ（ドラフトは生成中）" >> "$OUTFILE"
fi

echo "- 問題なければここは空" >> "$OUTFILE"
echo "" >> "$OUTFILE"

# --- 直近セッション ---
echo "## 直近セッション引き継ぎ" >> "$OUTFILE"
ls -t docs/SESSION_HANDOFF_*.md 2>/dev/null | head -3 | while read f; do
  DATE=$(head -5 "$f" | grep "作成日" | head -1 | sed 's/.*: //')
  TITLE=$(tail -1 "$f" | head -1)
  echo "- $(basename $f): $TITLE" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

LINES=$(wc -l < "$OUTFILE")
echo "---" >> "$OUTFILE"
echo "*自動生成完了: ${NOW} (${LINES}行)*" >> "$OUTFILE"
echo "SYSTEM_STATE.md generated: ${LINES} lines"
