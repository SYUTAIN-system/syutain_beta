#!/bin/bash
# PDL Session B Worker — Phase 2: write capabilities + worktree isolation
# Runs via crontab every 10 minutes
set -euo pipefail

LOCK_FILE="/tmp/pdl_worker.lock"
LOG_FILE="$HOME/syutain_beta/logs/pdl_worker.log"
PROJECT_DIR="$HOME/syutain_beta"
WORKTREE_BASE="/tmp/pdl_worktrees"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# Prevent concurrent runs (macOS compatible — no flock)
if [ -f "$LOCK_FILE" ]; then
    # Check if the PID in lock file is still running
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "SKIP: Previous worker still running (PID $OLD_PID)"
        exit 0
    fi
    # Stale lock — remove it
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

log "START: PDL Worker (Phase 2)"

# Budget check — abort if over daily limit
BUDGET_STATUS=$(cd "$PROJECT_DIR" && python3 -c "from pdl.budget_tracker import check_budget_sync; check_budget_sync()" 2>/dev/null || echo "OK:999.0")
BUDGET_OK=$(echo "$BUDGET_STATUS" | cut -d: -f1)
BUDGET_REMAINING=$(echo "$BUDGET_STATUS" | cut -d: -f2)

if [ "$BUDGET_OK" = "OVER" ]; then
    log "BUDGET EXCEEDED: Session B daily limit reached (remaining: ${BUDGET_REMAINING}JPY)"
    exit 0
fi
log "BUDGET: remaining=${BUDGET_REMAINING}JPY"

# Check if there are pending tasks
TASK=$(cd "$PROJECT_DIR" && python3 -c "
import asyncio, json
from tools.db_pool import get_connection, init_pool
async def get_task():
    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        row = await conn.fetchrow(
            \"\"\"SELECT id, category, description, priority, context_files
               FROM claude_code_queue
               WHERE status = 'pending' AND session_type IN ('autonomous', 'interactive')
               ORDER BY
                   CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                   created_at ASC
               LIMIT 1
               FOR UPDATE SKIP LOCKED\"\"\"
        )
        if row:
            await conn.execute('UPDATE claude_code_queue SET status=\$1 WHERE id=\$2', 'processing', row['id'])
            print(json.dumps({
                'id': row['id'], 'category': row['category'],
                'description': row['description'][:500], 'priority': row['priority']
            }, ensure_ascii=False))
asyncio.run(get_task())
" 2>/dev/null)

if [ -z "$TASK" ]; then
    log "NO TASKS: Queue empty"
    exit 0
fi

TASK_ID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
TASK_DESC=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['description'][:300])")

log "TASK: id=$TASK_ID desc=$TASK_DESC"

# ===== Phase 2: Worktree isolation + write capabilities =====

WORKTREE_DIR="${WORKTREE_BASE}/task_${TASK_ID}"
BRANCH_NAME="pdl/fix-${TASK_ID}"
FORBIDDEN_FILE="/tmp/pdl_forbidden_$$.txt"

# Ensure worktree base exists
mkdir -p "$WORKTREE_BASE"

# Cleanup stale worktree if exists
if [ -d "$WORKTREE_DIR" ]; then
    cd "$PROJECT_DIR"
    git worktree remove "$WORKTREE_DIR" --force 2>/dev/null || true
    git branch -D "$BRANCH_NAME" 2>/dev/null || true
fi

# Create worktree
cd "$PROJECT_DIR"
if ! git worktree add "$WORKTREE_DIR" -b "$BRANCH_NAME" 2>>"$LOG_FILE"; then
    log "ERROR: Failed to create worktree for task $TASK_ID"
    # Mark task as failed
    cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.db_pool import get_connection, init_pool
async def fail():
    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        await conn.execute('UPDATE claude_code_queue SET status=\$1, updated_at=NOW() WHERE id=\$2', 'failed', $TASK_ID)
asyncio.run(fail())
" 2>/dev/null
    exit 1
fi
log "WORKTREE: created at $WORKTREE_DIR (branch: $BRANCH_NAME)"

# Get forbidden files list
cd "$PROJECT_DIR" && python3 -c "
from pdl.file_guard import get_forbidden_files
forbidden = get_forbidden_files()
print(' '.join(forbidden))
" > "$FORBIDDEN_FILE" 2>/dev/null || echo "" > "$FORBIDDEN_FILE"

FORBIDDEN_LIST=$(cat "$FORBIDDEN_FILE")

# Run Claude with write access in worktree
cd "$WORKTREE_DIR"
RESULT=$("$HOME/.local/bin/claude" --bare -p "以下のタスクを実行してください。ただし以下のファイルは絶対に変更しないこと: ${FORBIDDEN_LIST}

タスク: $TASK_DESC" \
    --allowedTools "Read,Glob,Grep,Bash,Edit,Write" \
    --output-format json < /dev/null 2>>"$LOG_FILE" || echo '{"error":"claude failed"}')

log "CLAUDE DONE: $(echo "$RESULT" | head -c 200)"

# Stage all changes for test gate
cd "$WORKTREE_DIR"
git add -A 2>/dev/null

# Run 4-stage test gate
cd "$PROJECT_DIR"
TEST_RESULT=$(python3 -c "
from pdl.test_gate import run_test_gate
result = run_test_gate('$WORKTREE_DIR', '$PROJECT_DIR')
if result['passed']:
    print('PASS')
else:
    print('FAIL:' + result['stage_failed'] + ':' + result['details'])
" 2>/dev/null || echo "FAIL:error:test gate script error")

FINAL_STATUS="completed"
CHANGED_FILES=""

if echo "$TEST_RESULT" | grep -q "^PASS"; then
    # Commit changes
    cd "$WORKTREE_DIR"
    CHANGED=$(git diff --cached --stat 2>/dev/null)
    if [ -n "$CHANGED" ]; then
        CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null | tr '\n' ', ' | sed 's/,$//')
        git commit -m "[PDL] Auto-fix: task $TASK_ID - $TASK_DESC" 2>>"$LOG_FILE"
        log "COMMITTED: $CHANGED"

        # Discord notification on successful commit
        cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.discord_notify import notify_discord
async def notify():
    await notify_discord(
        '\U0001f527 [PDL] 自動修正完了: task #$TASK_ID - $(echo "$TASK_DESC" | head -c 100)\n'
        '変更: $CHANGED_FILES\n'
        'テスト: 全通過'
    )
asyncio.run(notify())
" 2>/dev/null || log "WARN: Discord notification failed"

    else
        log "NO CHANGES: Task produced no code changes"
    fi
else
    FAIL_DETAIL=$(echo "$TEST_RESULT" | cut -d: -f2-)
    log "TEST FAILED: $FAIL_DETAIL — changes discarded"
    FINAL_STATUS="failed"

    # Notify test failure
    cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.discord_notify import notify_discord
async def notify():
    await notify_discord(
        '\u274c [PDL] テスト失敗: task #$TASK_ID - $(echo "$TASK_DESC" | head -c 100)\n'
        '失敗ステージ: $FAIL_DETAIL'
    )
asyncio.run(notify())
" 2>/dev/null || true
fi

# Update task status in DB
cd "$PROJECT_DIR" && python3 -c "
import asyncio, json, sys
from tools.db_pool import get_connection, init_pool
async def complete():
    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        await conn.execute(
            'UPDATE claude_code_queue SET status=\$1, updated_at=NOW() WHERE id=\$2',
            '$FINAL_STATUS', $TASK_ID
        )
asyncio.run(complete())
" 2>/dev/null

# Cleanup worktree
cd "$PROJECT_DIR"
git worktree remove "$WORKTREE_DIR" --force 2>/dev/null || true
git branch -D "$BRANCH_NAME" 2>/dev/null || true
rm -f "$FORBIDDEN_FILE"

log "COMPLETE: id=$TASK_ID status=$FINAL_STATUS"
