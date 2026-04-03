#!/bin/bash
# SYUTAINβ OPERATION_LOG.md 自動生成スクリプト（前日の運用ログ）
set -uo pipefail
cd "$(dirname "$0")/.."
NOW=$(date '+%Y-%m-%d %H:%M:%S JST')
YESTERDAY=$(date -v-1d '+%Y-%m-%d' 2>/dev/null || date -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date '+%Y-%m-%d')
OUTFILE="docs/OPERATION_LOG_${YESTERDAY}.md"
DB="syutain_beta"

cat > "$OUTFILE" << HEADER
# SYUTAINβ 運用ログ ${YESTERDAY}
> 自動生成: ${NOW}

HEADER

# --- 24時間サマリー ---
echo "## 24時間サマリー" >> "$OUTFILE"

GOALS_CREATED=$(psql -t $DB -c "SELECT count(*) FROM goal_packets WHERE created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
GOALS_COMPLETED=$(psql -t $DB -c "SELECT count(*) FROM goal_packets WHERE status='completed' AND completed_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
TASKS_TOTAL=$(psql -t $DB -c "SELECT count(*) FROM tasks WHERE created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
TASKS_SUCCESS=$(psql -t $DB -c "SELECT count(*) FROM tasks WHERE status IN ('success','completed') AND updated_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
LLM_TOTAL=$(psql -t $DB -c "SELECT count(*) FROM llm_cost_log WHERE recorded_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
LLM_LOCAL=$(psql -t $DB -c "SELECT count(*) FROM llm_cost_log WHERE (model ILIKE '%qwen%' OR tier='L') AND recorded_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
LLM_COST=$(psql -t $DB -c "SELECT COALESCE(round(SUM(amount_jpy)::numeric,2),0) FROM llm_cost_log WHERE recorded_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
INTEL_CNT=$(psql -t $DB -c "SELECT count(*) FROM intel_items WHERE created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
PROPOSALS=$(psql -t $DB -c "SELECT count(*) FROM proposal_history WHERE created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
APPROVALS=$(psql -t $DB -c "SELECT count(*) FROM approval_queue WHERE requested_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
EVENTS=$(psql -t $DB -c "SELECT count(*) FROM event_log WHERE created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
ERRORS=$(psql -t $DB -c "SELECT count(*) FROM event_log WHERE severity IN ('error','critical') AND created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')

cat >> "$OUTFILE" << EOF
| 指標 | 件数 |
|------|------|
| ゴール作成 | ${GOALS_CREATED:-0} (完了: ${GOALS_COMPLETED:-0}) |
| タスク実行 | ${TASKS_TOTAL:-0} (成功: ${TASKS_SUCCESS:-0}) |
| LLM呼び出し | ${LLM_TOTAL:-0} (ローカル: ${LLM_LOCAL:-0}, コスト: ¥${LLM_COST:-0}) |
| 情報収集 | ${INTEL_CNT:-0} |
| 提案生成 | ${PROPOSALS:-0} |
| 承認処理 | ${APPROVALS:-0} |
| イベント | ${EVENTS:-0} (エラー: ${ERRORS:-0}) |

EOF

# --- コスト分析 ---
echo "## コスト分析" >> "$OUTFILE"
echo "| モデル | 呼出数 | コスト |" >> "$OUTFILE"
echo "|--------|--------|--------|" >> "$OUTFILE"
psql -t $DB -c "
SELECT model, count(*) as cnt, COALESCE(round(SUM(amount_jpy)::numeric,2),0) as cost
FROM llm_cost_log WHERE recorded_at::date = '${YESTERDAY}'
GROUP BY model ORDER BY cnt DESC;" 2>/dev/null | while read -r MODEL CNT COST; do
  [ -n "$MODEL" ] && echo "| $MODEL | $CNT | ¥$COST |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

# --- エラー一覧 ---
echo "## エラー一覧" >> "$OUTFILE"
psql -t $DB -c "
SELECT to_char(created_at, 'HH24:MI') as time, event_type, source_node,
  COALESCE(substring(payload->>'error' from 1 for 80), substring(payload->>'reason' from 1 for 80), '')
FROM event_log WHERE severity IN ('error','critical') AND created_at::date = '${YESTERDAY}'
ORDER BY created_at;" 2>/dev/null | while read -r TIME TYPE NODE MSG; do
  [ -n "$TIME" ] && echo "- ${TIME} [${NODE}] ${TYPE}: ${MSG}" >> "$OUTFILE"
done
ERRCNT=$(psql -t $DB -c "SELECT count(*) FROM event_log WHERE severity IN ('error','critical') AND created_at::date = '${YESTERDAY}';" 2>/dev/null | tr -d ' ')
[ "${ERRCNT:-0}" -eq 0 ] && echo "- なし" >> "$OUTFILE"
echo "" >> "$OUTFILE"

# --- イベントカテゴリ別 ---
echo "## イベント内訳" >> "$OUTFILE"
echo "| カテゴリ | 件数 |" >> "$OUTFILE"
echo "|----------|------|" >> "$OUTFILE"
psql -t $DB -c "
SELECT category, count(*) FROM event_log WHERE created_at::date = '${YESTERDAY}'
GROUP BY category ORDER BY count DESC;" 2>/dev/null | while read -r CAT CNT; do
  [ -n "$CAT" ] && echo "| $CAT | $CNT |" >> "$OUTFILE"
done
echo "" >> "$OUTFILE"

LINES=$(wc -l < "$OUTFILE")
echo "---" >> "$OUTFILE"
echo "*自動生成完了: ${NOW} (${LINES}行)*" >> "$OUTFILE"
echo "OPERATION_LOG generated: ${OUTFILE} (${LINES} lines)"
