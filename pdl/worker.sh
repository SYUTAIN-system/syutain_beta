#!/bin/bash
# PDL Session B Worker — Phase 4: auto-merge + auto-deploy
# Runs via crontab every 10 minutes
set -euo pipefail

LOCK_FILE="/tmp/pdl_worker.lock"
LOG_FILE="$HOME/syutain_beta/logs/pdl_worker.log"
PROJECT_DIR="$HOME/syutain_beta"
WORKTREE_BASE="/tmp/pdl_worktrees"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# ===== Kill switch: create pdl/PAUSE to halt all PDL operations =====
if [ -f "$PROJECT_DIR/pdl/PAUSE" ]; then
    log "PAUSED: pdl/PAUSE file exists. Remove to resume."
    exit 0
fi

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

# Load environment (.env for API keys) without executing file contents
if [ -f "$PROJECT_DIR/.env" ]; then
    while IFS= read -r kv; do
        [ -z "$kv" ] && continue
        key=${kv%%=*}
        value=${kv#*=}
        export "$key=$value"
    done < <(python3 - "$PROJECT_DIR/.env" <<'PY'
import re
import sys

env_path = sys.argv[1]
with open(env_path, encoding="utf-8") as fh:
    for raw in fh:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        print(f"{key}={value}")
PY
)
fi
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:$PATH"

log "START: PDL Worker (Phase 4)"

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
RESULT=$(codex exec "以下のタスクを実行してください。ただし以下のファイルは絶対に変更しないこと: ${FORBIDDEN_LIST}

タスク: $TASK_DESC" \
    --output-last-message /tmp/pdl_result_${TASK_ID}.txt \
    < /dev/null 2>>"$LOG_FILE" || echo '{"error":"codex failed"}')
# Codex output is in the last message file
if [ -f "/tmp/pdl_result_${TASK_ID}.txt" ]; then
    RESULT=$(cat "/tmp/pdl_result_${TASK_ID}.txt")
    rm -f "/tmp/pdl_result_${TASK_ID}.txt"
fi

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
PR_URL=""

if echo "$TEST_RESULT" | grep -q "^PASS"; then
    # Commit changes
    cd "$WORKTREE_DIR"
    CHANGED=$(git diff --cached --stat 2>/dev/null)
    if [ -n "$CHANGED" ]; then
        CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null | tr '\n' ', ' | sed 's/,$//')
        git commit -m "[PDL] Auto-fix: task $TASK_ID - $TASK_DESC" 2>>"$LOG_FILE"
        log "COMMITTED: $CHANGED"

        # Run gstack code review on changes (quality gate before PR)
        REVIEW_OUTPUT_FILE="/tmp/pdl_review_${TASK_ID}.txt"
        codex exec "/gstack-review --uncommitted" --output-last-message "$REVIEW_OUTPUT_FILE" < /dev/null 2>>"$LOG_FILE" || true
        if [ -f "$REVIEW_OUTPUT_FILE" ]; then
            REVIEW_TEXT=$(cat "$REVIEW_OUTPUT_FILE")
            rm -f "$REVIEW_OUTPUT_FILE"
            log "GSTACK REVIEW: $(echo "$REVIEW_TEXT" | head -c 200)"
        else
            log "GSTACK REVIEW: no output file"
        fi

        # ===== Phase 4: Push, PR, Auto-merge, Auto-deploy =====

        # Push branch to GitHub
        cd "$WORKTREE_DIR"
        if git push origin "$BRANCH_NAME" 2>>"$LOG_FILE"; then
            log "PUSHED: branch $BRANCH_NAME"
        else
            log "PUSH FAILED: branch $BRANCH_NAME"
            FINAL_STATUS="failed"
        fi

        # Create PR
        PR_URL=$(cd "$WORKTREE_DIR" && gh pr create \
            --base main \
            --head "$BRANCH_NAME" \
            --title "[PDL] Auto-fix: task $TASK_ID" \
            --body "Automated fix by PDL Session B (Codex)

Task: $TASK_DESC

Files changed: $CHANGED_FILES

Test gate: PASSED" \
            2>>"$LOG_FILE") || true

        if [ -n "$PR_URL" ]; then
            log "PR CREATED: $PR_URL"

            # Update DB with PR URL
            cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.db_pool import get_connection, init_pool
async def update():
    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        await conn.execute('UPDATE claude_code_queue SET pr_url=\$1 WHERE id=\$2', '$PR_URL', $TASK_ID)
asyncio.run(update())
" 2>/dev/null || log "WARN: PR URL DB update failed"

            # Determine task tier for auto-merge decision
            # Tier 3 = non-critical tasks safe for auto-merge
            TASK_CATEGORY=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category',''))" 2>/dev/null || echo "")
            TIER=$(TASK_CATEGORY="$TASK_CATEGORY" python3 -c "
import os

tier3_categories = {'quality_decline', 'model_quality_decline', 'cost_spike', 'brain_beta_instruction'}
category = os.environ.get('TASK_CATEGORY', '')
print('3' if category in tier3_categories else '1')
" 2>/dev/null || echo "1")

            if [ "$TIER" = "3" ]; then
                # Wait for GitHub Actions checks (max 2 minutes)
                log "AUTO-MERGE: Tier 3 task, waiting for CI checks..."
                sleep 30

                # Check PR status
                CHECK_STATUS=$(gh pr checks "$PR_URL" --json state --jq '.[].state' 2>/dev/null | sort -u || true)

                if echo "$CHECK_STATUS" | grep -q "FAILURE"; then
                    log "AUTO-MERGE BLOCKED: PR checks failed"
                elif echo "$CHECK_STATUS" | grep -q "PENDING"; then
                    # Enable auto-merge so GitHub merges when checks pass
                    gh pr merge "$PR_URL" --squash --auto 2>>"$LOG_FILE" && \
                        log "AUTO-MERGE ENABLED: will merge when checks pass" || \
                        log "AUTO-MERGE DEFERRED: could not enable auto-merge"
                else
                    # All checks passed — merge now
                    if gh pr merge "$PR_URL" --squash 2>>"$LOG_FILE"; then
                        log "AUTO-MERGED: $PR_URL"
                    else
                        log "AUTO-MERGE FAILED: $PR_URL"
                        FINAL_STATUS="failed"
                    fi

                    # Auto-deploy: pull latest main and rsync to remote nodes
                    cd "$PROJECT_DIR"
                    if git pull origin main 2>>"$LOG_FILE"; then
                        for NODE_IP in ${BRAVO_IP:-127.0.0.1} ${CHARLIE_IP:-127.0.0.1} ${DELTA_IP:-127.0.0.1}; do
                            rsync -az --delete \
                                --exclude '.env' --exclude 'node_modules' --exclude 'data/' \
                                --exclude 'logs/' --exclude '.next/' --exclude '__pycache__/' \
                                --exclude 'venv/' --exclude 'browser_layer2/node_modules' \
                                ./ "${REMOTE_SSH_USER:-user}@${NODE_IP}:~/syutain_beta/" 2>/dev/null && \
                                log "DEPLOYED: rsync to $NODE_IP" || \
                                log "DEPLOY WARN: rsync failed for $NODE_IP"
                        done
                    else
                        log "DEPLOY ABORTED: git pull origin main failed"
                        FINAL_STATUS="failed"
                    fi

                    # Cleanup merged branch
                    git branch -D "$BRANCH_NAME" 2>/dev/null || true

                    # Discord notification — auto-merge + deploy
                    cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.discord_notify import notify_discord
async def notify():
    await notify_discord(
        '\U0001f680 [PDL] 自動マージ+デプロイ完了\n'
        'Task: #$TASK_ID\n'
        'PR: $PR_URL\n'
        '変更: $CHANGED_FILES\n'
        '※ファイル同期のみ。サービス再起動は手動で行ってください。'
    )
asyncio.run(notify())
" 2>/dev/null || log "WARN: Discord notification failed"
                fi
            else
                # Tier 1 (critical) — require manual review
                log "MANUAL REVIEW REQUIRED: Task is Tier 1 (critical). PR created but not auto-merged."

                cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.discord_notify import notify_discord
async def notify():
    await notify_discord(
        '\U0001f440 [PDL] 手動レビュー必要\n'
        'Task: #$TASK_ID - $(echo "$TASK_DESC" | head -c 80)\n'
        'PR: $PR_URL\n'
        'Tier 1タスクのため自動マージ不可。レビューしてください。'
    )
asyncio.run(notify())
" 2>/dev/null || log "WARN: Discord notification failed"
            fi
        else
            log "WARN: PR creation failed, commit stays on branch $BRANCH_NAME"

            # Fallback notification — commit succeeded but PR failed
            cd "$PROJECT_DIR" && python3 -c "
import asyncio
from tools.discord_notify import notify_discord
async def notify():
    await notify_discord(
        '\U0001f527 [PDL] 自動修正完了 (PR作成失敗)\n'
        'Task: #$TASK_ID - $(echo "$TASK_DESC" | head -c 100)\n'
        '変更: $CHANGED_FILES\n'
        'テスト: 全通過\n'
        'ブランチ: $BRANCH_NAME (手動でPR作成してください)'
    )
asyncio.run(notify())
" 2>/dev/null || log "WARN: Discord notification failed"
        fi

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

# Cleanup worktree (branch cleanup only if not pushed/merged)
cd "$PROJECT_DIR"
git worktree remove "$WORKTREE_DIR" --force 2>/dev/null || true
# Only delete branch if no PR was created (branch still needed for open PRs)
if [ -z "$PR_URL" ]; then
    git branch -D "$BRANCH_NAME" 2>/dev/null || true
fi
rm -f "$FORBIDDEN_FILE"

log "COMPLETE: id=$TASK_ID status=$FINAL_STATUS"
