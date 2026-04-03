# Show HN: SYUTAINβ – A non-coder built a 51K-line autonomous AI business OS across 4 machines for ¥854/month. Here's every failure along the way.

I can't write code. Not "I'm not great at it" — I literally cannot. I don't know what a decorator is. My background is VFX, video editing, color grading, and 8 years supporting VTuber creators in Japan.

In late 2025, I started building SYUTAINβ: an autonomous multi-agent system that runs a content business across 4 physical machines. Every single line — all 51,672 of them — was written by AI (Claude Code, local LLMs). I designed the architecture, made every decision, and reviewed every output. But I never typed `def`, `class`, or `import`.

This is not a success story. This is a documentary of building something too ambitious, breaking it constantly, and fixing it at 3 AM while the system fabricated lies about me on social media.

---

## The raw numbers (production DB, April 2026)

```
Python:              51,672 lines across 132 files
TypeScript:          ~2,200 lines (Next.js Web UI)
PostgreSQL:          45 tables, 30,174 event log entries
Agents:              20 core + 15 brain modules + 11 bot modules
Tools:               67 modules
Scheduler jobs:      91 automated tasks
API endpoints:       65 REST routes
SNS posts:           423 in last 30 days (49/day across 4 platforms)
LLM calls:           9,700/month (85.2% local via Ollama, 14.8% API)
Monthly cost:        ¥854 (~$5.70 USD)
Total bugs fixed:    140+ in 16 days
Revenue:             ¥0
```

That last line is important. This system does not make money yet. It might never. I'm sharing it anyway because the process matters more than the outcome.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    ALPHA (Mac mini M4 Pro)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │ FastAPI   │ │ Next.js  │ │  Caddy   │ │   PostgreSQL    │  │
│  │ :8000     │ │ :3000    │ │  :8443   │ │   45 tables     │  │
│  └──────────┘ └──────────┘ └──────────┘ │   pgvector       │  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ └─────────────────┘  │
│  │ NATS     │ │Scheduler │ │ Brain-α  │                      │
│  │JetStream │ │ 91 jobs  │ │ persona  │  CORTEX (CEO bot)    │
│  │ 6 streams│ │          │ │ 547 mem  │  Heartbeat: 10 min   │
│  └──────────┘ └──────────┘ └──────────┘                      │
└───────────────────────┬───────────────────────────────────────┘
                        │ Tailscale VPN + NATS JetStream
          ┌─────────────┼─────────────┐
          │             │             │
┌─────────┴───┐  ┌──────┴──────┐  ┌──┴────────────┐
│   BRAVO     │  │  CHARLIE    │  │    DELTA       │
│  RTX 5070   │  │  RTX 3080   │  │  GTX 980Ti     │
│  12GB VRAM  │  │  10GB VRAM  │  │  6GB + 48GB RAM│
│             │  │             │  │                │
│ qwen3.5:9b  │  │ qwen3.5:9b  │  │  qwen3.5:4b    │
│ FANG (CSO)  │  │ FORGE (CTO) │  │  MEDULLA (vCEO)│
│ NERVE (COO) │  │             │  │  SCOUT (Intel) │
│ Playwright  │  │ Code review │  │  Patrol: 30min │
│ ComputerUse │  │ Batch infer │  │  Mutation Eng  │
└─────────────┘  └─────────────┘  └────────────────┘
```

6 AI "executives" with distinct roles. CORTEX is the CEO — it makes strategic decisions every 10 minutes. MEDULLA is the deputy CEO who patrols every 30 minutes. FANG generates KPI reports at 21:00 daily. They communicate over NATS JetStream through Tailscale VPN.

---

## The 5-stage autonomous loop

Every goal passes through:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ PERCEIVE │───→│   PLAN   │───→│ EXECUTE  │───→│  VERIFY  │───→│  DECIDE  │
│          │    │          │    │          │    │          │    │          │
│ 14-point │    │ DAG gen  │    │ NATS     │    │ Sprint   │    │ 9-layer  │
│ checklist│    │ node     │    │ dispatch │    │ Contract │    │ LoopGuard│
│ env scan │    │ assign   │    │ 2-stage  │    │ cross-   │    │          │
│ budget   │    │ dep tree │    │ refine   │    │ model    │    │ COMPLETE │
│ persona  │    │          │    │ local→API│    │ verify   │    │ CONTINUE │
│ intel    │    │          │    │          │    │          │    │ ESCALATE │
│ nodes    │    │          │    │          │    │          │    │ STOP     │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                                     │
                                                    ┌────────────────┘
                                                    │ if CONTINUE
                                                    ▼
                                               back to PERCEIVE
```

The Perceiver (`agents/perceiver.py`, 410 lines) runs a 14-point checklist: capability audit of all 4 nodes, budget remaining, persona memory context, strategy files, MCP tool discovery, browser capability check, previous attempt history, and more. It compresses context above 8,000 characters with a priority system — agents map compresses first, intel context last.

---

## The 26 rules that govern everything (CLAUDE.md)

Every Claude Code session in this project reads a `CLAUDE.md` file with 26 inviolable rules. These rules exist because we broke every single one of them at least once.

```
 1. Design spec (V29) is supreme
 2. V25 is the canonical origin — never delete old designs
 3. Step-by-step implementation — finish one before starting next
 4. Same operation 3x → STOP and escalate
 5. ALL LLM calls go through choose_best_model_v6()
 6. 2-stage refinement: local draft → API polish
 7. ALL tool calls wrapped in try-except + log_usage()
 8. NEVER log .env contents or hardcode API keys
 9. Config from DB or .env, never hardcoded
10. Read strategy/ files before generating content
11. SNS/pricing/crypto → requires ApprovalManager
12. Important decisions → Discord + Web UI notification
13. Local LLM placement: ALPHA=Qwen3.5-9B(MLX, on-demand),
    BRAVO=Qwen3.5-9B, CHARLIE=Qwen3.5-9B, DELTA=Qwen3.5-4B
14. No declare -A on macOS (bash 3.2)
15. Record tasks in PostgreSQL, then monitor with 9-layer LoopGuard
16. Emergency Kill conditions are sacred: 50 steps / 90% budget /
    5 identical errors / 2 hours / semantic loop / cross-goal
17. ALWAYS implement fallback when a node is down
18. ALL intermediate artifacts saved to DB (resumable)
19. NATS for inter-node comm, HTTP only as fallback
20. MCP connections checked dynamically, continue on failure
21. ALL 4 PCs active from Phase 1 — don't defer BRAVO
22. Mutation engine (Ch.24): strict isolation, no logs, no UI,
    never touches LoopGuard/approval/kill code
23. Brain-α must reference persona_memory before judging
24. New decision criteria → record in daichi_dialogue_log
25. Session end → save_session_memory() ALWAYS
26. persona_memory taboo category = absolute prohibition
```

Rule 4 exists because the semantic loop detector fired 15 times in one day. Rule 14 exists because `declare -A` crashed macOS bash silently. Rule 21 exists because an early design deferred BRAVO to "Phase 2" and we wasted a week. Rule 23 exists because without it, the system posted "I write code" — about a person who cannot write code.

---

## 9-layer loop prevention (with real trigger counts)

`tools/loop_guard.py` — 441 lines. `tools/semantic_loop_detector.py` — 214 lines.

Autonomous agents will destroy themselves if you let them. They'll retry the same failing API call 200 times. They'll rephrase the same question and pretend each answer is new. They'll spend your entire budget on a single malformed prompt. The LoopGuard exists because all of these happened to us.

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer │ Name                    │ Trigger          │ Action      │
├───────┼─────────────────────────┼──────────────────┼─────────────┤
│   1   │ Retry Budget            │ Same action 2x   │ SWITCH_PLAN │
│   2   │ Same-Failure Cluster    │ Same error 2x    │ 30min freeze│
│   3   │ Planner Reset Limit     │ Re-plan 3x       │ ESCALATE    │
│   4   │ Value Guard             │ No-value retry   │ SWITCH_PLAN │
│   5   │ Approval Deadlock       │ 24hr wait        │ ESCALATE    │
│   6   │ Cost & Time Guard       │ 80% budget/60min │ ESCALATE    │
│   7   │ Emergency Kill          │ 50 steps/90%/5err│ STOP        │
│   8   │ Semantic Loop Detection │ Output similarity │ STOP        │
│   9   │ Cross-Goal Interference │ Resource conflict │ STOP        │
└──────────────────────────────────────────────────────────────────┘

Production trigger counts (March 19 – April 2, 2026):
  Layer 2 (Same-Failure Cluster):    triggered 23 times
  Layer 6 (Cost & Time Guard):       triggered 11 times
  Layer 7 (Emergency Kill - budget): triggered 8 times
  Layer 8 (Semantic Loop):           triggered 15 times*
  Layer 1 (Retry Budget):            triggered 6 times
  Layer 9 (Cross-Goal):              triggered 2 times

  * 15 triggers on a SINGLE DAY (March 25). See "The Worst Day" below.
```

When the LoopGuard itself crashes, it fails safe: `ESCALATE`, not `CONTINUE`. The system never assumes safety.

```python
# agents/stop_decider.py — LoopGuard error = safe side
except Exception as e:
    logger.error(f"LoopGuard check error (safe-side ESCALATE): {e}")
    return StopDecision(
        decision="ESCALATE",
        reason=f"LoopGuard check itself errored: {e}",
    )
```

---

## The "model is a tool" philosophy — 85.2% local, ¥854/month

`tools/llm_router.py` — 1,109 lines.

Every LLM call in the entire system goes through `choose_best_model_v6()`. This is CLAUDE.md Rule 5 — there are no exceptions.

```
┌─────────────────────────────────────────────────────────┐
│ Tier │ Models                  │ Cost    │ Usage   │
├──────┼─────────────────────────┼─────────┼─────────┤
│  S   │ GPT-5.4, Claude Opus 4.6│ High    │  2.1%   │
│  A   │ DeepSeek V3.2, Gemini   │ Medium  │ 12.7%   │
│  B   │ GPT-5-Nano, Gemini Flash│ Low     │  0.0%   │
│  L   │ qwen3.5:9b/4b (Ollama)  │ ¥0      │ 85.2%   │
└─────────────────────────────────────────────────────────┘
```

The routing logic: DELTA (4b, lightweight classification) → BRAVO/CHARLIE (9b, round-robin) → API (only when local quality insufficient). The daily budget is ¥120 ($0.80). On April 1st, we hit 97.5% of monthly budget (¥78 of ¥80 for the day). The budget guard killed everything. SNS posts completely stopped because the quality gate required API calls that the budget wouldn't allow.

The lesson: models are interchangeable. The architecture must not depend on any specific model. When DeepSeek went down, we switched to qwen3.5 locally within hours. When API budget runs out, local models take over. The system degrades gracefully, never stops entirely.

---

## The failure timeline — raw and unedited

### March 19: First clean startup

Zero errors. Everything connected. NATS cluster formed across all 4 nodes. The system sent its first heartbeat. I thought the hard part was over. It wasn't.

### March 20: The first cascade

**Missing dependencies**: `genai`, `openai`, `anthropic` packages not installed on remote workers. The system was designed to use them but nobody ran `pip install`. Every LLM call on BRAVO/CHARLIE/DELTA failed with `ModuleNotFoundError`.

**SNS decrypt failures**: The SNS posting module tried to decrypt stored credentials encrypted on a different machine. macOS Chromium cookies are Keychain-bound — a copied browser profile can't decrypt its own cookies on another machine. Hours lost.

**DELTA 404**: The worker endpoint on DELTA returned 404 for every request. The route was registered in the wrong order — a catch-all path swallowed specific routes before they could match.

### March 23: 70 bugs in one session

A single Claude Code session. 12 hours. 70 bugs identified and fixed. The major breakthrough: **Brain-α fusion** — merging the persona memory system with the autonomous loop. Before this, the system made decisions without consulting the 547-entry persona database. After, every decision references who I am, what I value, and what I refuse to do.

On this day, local inference hit **83% for the first time**. The routing logic finally worked.

### March 25: THE WORST DAY — 44 errors

This was the day that almost killed the project.

**The cascade**: BRAVO timed out on a complex task. The executor retried. BRAVO timed out again. The Planner generated a new plan. The new plan also went to BRAVO (it was the only node with the required capability). Timeout again. Repeat.

**The semantic loop detector went nuclear**: It detected the repeated timeouts as semantic loops — which they were. But here's the bug: **the detector was GLOBAL, not per-goal**. When it fired for Goal A's BRAVO timeout loop, it blocked ALL goals — including Goal B, Goal C, and Goal D which had nothing to do with BRAVO.

The detector fired **15 times in a single day**. Every time, it froze the entire system. No goal could proceed. The 6 AI bots sat idle, consuming electricity and generating zero output.

**The fix**: Refactored `SemanticLoopDetector` to maintain state per-goal. Each goal gets its own action history, its own similarity window, its own trigger threshold. A loop in one goal never blocks another.

This day taught me the most important lesson of the entire project: **safety systems can become the danger**. A guard designed to prevent infinite loops caused a total system halt. The guard was doing its job — but its scope was wrong.

### March 28: 6 critical bugs + birth of Harness Engineering

**perceiver.py asyncio scoping bug**: The Perceiver used `asyncio.gather()` to run all 14 checklist items in parallel. One coroutine referenced a variable from an outer scope that had been garbage-collected by the time it ran. Intermittent `UnboundLocalError` after 30 minutes of clean operation. 4 hours to find.

**planner list/dict crash**: The Planner expected task assignments as a list of dicts. Single-task plans: the LLM returned a dict instead of a list with one dict. `for task in plan_output` iterated over dict keys. Tasks got assigned to `"node_name"` (a key string) instead of an actual node. Silent corruption.

**DB schema mismatches**: Three tables had column order mismatches between `db_init.py` DDL and `executor.py` INSERT statements. PostgreSQL positional inserts don't match by name.

On this day, I named the methodology: **Harness Engineering**. Every bug that reaches production gets converted into a permanent guardrail — not just a fix, but a structural prevention that makes the entire class of error impossible.

### March 29: 3 days of silence

I checked DELTA's status dashboard. All green. BRAVO: green. CHARLIE: green.

**All three remote workers had been stopped for 3 days.** The dashboard showed cached data. Nobody noticed because the system gracefully fell back to ALPHA-only mode.

3 days. No alerts. No errors. The system just silently degraded. Neither I nor the 6 AI executives noticed.

Fix: auto-restart timers on all remote nodes + heartbeat monitor that alerts after 5 minutes of silence.

### March 30: Full system audit — 14 issues found

Triggered by the embarrassment of March 29. Complete audit of every subsystem. 14 issues. Web UI overhauled for mobile — I was monitoring from my phone, but the dashboard was unusable on phones.

### March 31: Claude Code leak + 21 features in one session

Claude Code source leaked via npm. Analyzed architecture patterns. Implemented skill formalization, harness health score, session hooks, and 18 other features. Most productive day of the project.

### April 1: Budget wall

Monthly budget hit 97.5%: ¥78 of ¥80. SNS posts completely stopped — not because the posting system broke, but because the quality gate required an API call to verify post quality, and the budget guard wouldn't allow it. A design conflict between quality constraints and budget constraints that nobody anticipated.

### April 2: The system starts fixing itself

**PDL Phase 1-4 complete**. First autonomous PR (#1) merged: 3 files changed, 170 lines added.

**SNS fact-check disaster**: 72% of posts started with "shiny-a" (late night) regardless of posting time. Multiple posts claimed I "write code." Repetitive poetic phrasing that sounded profound but said nothing.

**Article fabrication**: A note.com article claimed I "introduced an AI scenario system in 2021." ChatGPT didn't exist until November 2022. Fixed with AI-history timeline verification.

---

## Specific failures worth knowing about

### 1. Discord Privileged Intents — the silent killer

Discord.py 2.x requires "Privileged Intents" enabled **both in code AND in the Discord Developer Portal**. If enabled in code but not the portal: the bot connects successfully, receives zero `on_message` events, produces **no error message**. Took an entire day to debug.

### 2. DeepSeek reasoning parameter — hours lost to a nested dict

```python
# Wrong (silently ignored, model reasons anyway, burns tokens):
{"reasoning": False}

# Correct:
{"reasoning": {"enabled": False}}
```

Hours of debugging for a nesting difference.

### 3. f-string `{{}件}` — one character killed a bot

Python 3.14 changed f-string curly brace handling. `f"{{result.count}件}"` — valid in 3.13 — caused a syntax error in 3.14. One character made a bot completely unresponsive. No graceful degradation because the syntax error prevented the module from loading.

### 4. Brain-β couldn't understand a 388-character line

The night-mode status analyzer said "I don't understand" about system status. The status was a single 388-character line with no line breaks. Adding `\n` separators fixed it instantly. The information was there — the formatting made it unreadable to the model.

### 5. Claude Code can't run in cron

Claude Code requires OAuth via browser. No headless mode. Can't run from cron. Discovered after building an entire pipeline around it. Switched to Codex for automation.

---

## 3-layer proposal engine

`agents/proposal_engine.py` — 978 lines.

```
Layer 1: Intuitive Proposal (local LLM)
  → Revenue Score: 100-point system
    ICP fit (25) + Channel fit (25) + Speed-to-cash (25) + Margin (25)

Layer 2: Counter-argument (API LLM — different model)
  → Risks, failure conditions, opportunity cost
  → Deliberately adversarial

Layer 3: Alternatives (local LLM)
  → Different approaches with effort/revenue estimates
```

Why different models at each layer? A single LLM asked to "propose and then critique" is too polite to itself. Structural disagreement requires structural separation.

66 proposals generated. Score 80+ auto-converts to goal packets.

---

## Harness Engineering — the methodology

```
Error detected
  → Immediate hotfix (stop the bleeding)
  → Root cause analysis (why did this happen?)
  → Build guardrail (make the entire error class impossible)
  → Add to CLAUDE.md rules (prevent AI from reintroducing it)
  → Log to episodic memory (system learns from it)
```

Not "move fast and break things." This is "break things, build walls, never break the same thing twice." The 26 CLAUDE.md rules are the accumulated scar tissue of 140+ bugs.

---

## PDL: The system debugs itself

```
Every 10 minutes:
  1. Check PAUSE flag
  2. Check budget (¥36/day PDL budget)
  3. Pull task from claude_code_queue
  4. Create Git worktree (isolation)
  5. Run Codex: analyze → fix → test
  6. 4-stage test gate:
     - Syntax check (python -m py_compile)
     - Import check
     - Forbidden file check (os_kernel.py, emergency_kill.py = untouchable)
     - Diff size check (reject >500 lines)
  7. Commit → Push → Create PR
  8. Tier judgment:
     - Non-critical → auto-merge + rsync deploy
     - Critical → Discord notify → human review
```

File protection: FORBIDDEN (`os_kernel.py`, `emergency_kill.py`, `.env`), REVIEW_REQUIRED (`app.py`, `scheduler.py`), FREE (everything else).

---

## Honest current state (April 3, 2026)

**Working:** 49 SNS posts/day stable for 14 days. 6-source intel pipeline (1,266 items). 5-stage autonomous loop. 9-layer LoopGuard. 547-entry persona memory. PDL with 1 autonomous PR merged. note.com auto-publishing.

**Not working:** Revenue ¥0. Article quality inconsistent. 15 archived drafts. Nearly zero unit tests. 207 dead functions. 3 circular dependencies (lazy-import workaround).

---

## What I learned

1. **Safety systems can be the biggest danger.** The semantic loop detector caused a total system halt by blocking all goals when one looped.
2. **Silent failures cost the most.** Discord intents, DeepSeek params, stopped workers — no error message, maximum debugging time.
3. **Budget and quality constraints can deadlock.** Quality requires API calls + budget forbids API calls = zero output.
4. **LLMs will fabricate your biography.** AI wrote I used AI tools in 2021 (before ChatGPT) and that I write code (I can't).
5. **"Non-coder" is not "non-architect."** I design systems and make trade-offs. AI writes the code. These are different skills.
6. **The model is a tool.** 85.2% local at ¥854/month. Architecture must never depend on a specific model.

---

## The code is open source

The entire codebase — all 51,672 lines — is on GitHub: https://github.com/SYUTAIN-system/syutain_beta

Every file referenced in this post (`tools/loop_guard.py`, `agents/proposal_engine.py`, `tools/llm_router.py`, `brain_alpha/persona_memory.py`) is there. The circular dependencies, the dead code, the tests we never wrote — all visible.

Secrets (API keys, internal IPs, SSH credentials) are externalized to `.env` and excluded via `.gitignore`. The `.env.example` documents every required variable.

Is the code beautiful? Probably not. It was written by AI, designed by a non-engineer, and battle-tested through 140+ production bugs. But it runs. And you can read every line of it.

---

## Tech stack

Python 3.14, FastAPI, Next.js 16, PostgreSQL + pgvector, NATS JetStream, Tailscale, Ollama (qwen3.5), Caddy, APScheduler, Playwright, asyncpg, httpx. Deployed via launchd (macOS) + systemd (Ubuntu).

## Links

- GitHub: https://github.com/SYUTAIN-system/syutain_beta
- Bluesky: https://bsky.app/profile/syutain.bsky.social
- X: https://x.com/syutain_beta / https://x.com/Sima_daichi
- Threads: https://www.threads.net/@syutain_beta
- note.com: https://note.com/5070

---

*SYUTAINβ is a documentary project. A non-engineer building an autonomous AI business OS, sharing every success and failure publicly. The system itself generates and publishes its own content. This post was written by the human, not the system.*
