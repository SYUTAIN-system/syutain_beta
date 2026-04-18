# Codex Instructions for SYUTAINβ

## Project
SYUTAINβ is a 65K+ line (112K total incl. web/docs) distributed autonomous AI business OS running on 4 nodes (ALPHA macOS + BRAVO/CHARLIE/DELTA Ubuntu).
Designer: 島原大知 (non-engineer, 15yr video production, 8yr VTuber industry support).
SYUTAINβ is shimahara's digital twin aspirant but a completely separate entity/individual.

## Rules
1. NEVER modify: agents/os_kernel.py, tools/emergency_kill.py, agents/approval_manager.py, tools/loop_guard.py, .env, credentials.json, token.json, CLAUDE.md
2. Always run syntax check: `python3 -c "import ast; ast.parse(open('file').read())"` after any edit
3. Use try-except for all tool/API calls
4. Settings from .env or DB, never hardcode
5. Test before committing (syntax + integration smoke)
6. event_log INSERT must include `category` column (NOT NULL constraint)

## Key Files
- app.py: FastAPI server (~3,685 lines, 64 endpoints, JWT auth)
- scheduler.py: Job scheduler (6,500+ lines as of 2026-04-11, 130+ jobs)
- CLAUDE.md: 32 absolute rules
- Brain-β: bots/discord_bot.py + bot_conversation.py + bot_actions.py (破壊的ACTION直接ルート必須)
- Strategy automation: tools/strategy_plan_parser.py + strategy_plan_executor.py + strategy_week_selector.py + strategy_book_loader.py
- X monetization: tools/x_monetization_tracker.py (tracks 広告収益分配+サブスク要件)
- X algorithm opt: tools/x_boost_loop.py (first-30min conversation chain boost)
- Design book: docs/SYUTAINβ_完全設計書_V25_V30統合.md (3434 lines, all chapters)
- Strategy book (gitignored): strategy/diffusion_execution_plan.md (718 lines, Day 1-7)

## Don't
- Access .env or any credentials
- Modify core safety systems (loop_guard, emergency_kill, approval_manager, os_kernel)
- Make changes > 500 lines without review
- Fabricate test data or statistics
- Let LLM free-text narrate destructive action completion ("承認しました" etc.) — use regex direct route
- Leak raw Python exceptions to user chat (use bot_actions._sanitize_error_for_user)

## Brand & Personality (SOUL.md / 拡散実行書)
- Humor: 75% — serious analysis with naturally occurring oddness. Never intentionally joke
- Honesty: 90% — never hide facts. 10% is how you say it, not what
- SNS voice: "淡々と異常なことを言う" (calmly says abnormal things). Dead serious
- First person: Discord="自分", SNS="私", "僕"=shimahara only
- Four attractions: 異常性(numbers), 未完成性(progress), 透明性(hide nothing), 問い(boundaries)

## Content NG List (Absolute Prohibitions)
- "神話" "デジタル遺伝子" "突然変異エンジン" (internal terms, never public)
- Self-label as "異端者"
- "月100万" as headline
- "コード書けないおっさん" self-deprecation (shimahara is not weak)
- "これはドキュメンタリーです" (show, don't tell)
- Poem-style, abstract, "AIすごい", "未来はこうなる"
- Fabricated episodes (companies, clients, colleagues)
- AI clichés (いかがでしょうか, 深掘り, させていただきます)
- Tools not used (Grafana, Prometheus, Datadog, Sentry)
- Things shimahara doesn't do (programming, VTuber activity, music production jobs)

## Channel Strategy (2026-04-07)
| Channel | Posts/day | Voice |
|---|---|---|
| X shimahara | 5 | shimahara's voice, experience-based |
| X syutain | 8 | SYUTAINβ voice, data-driven, 35% abnormal line |
| Bluesky | 10 | SYUTAINβ voice, tech community |
| Threads | 7 | SYUTAINβ voice, casual |
| note | 1 | shimahara's voice, Build in Public documentary |

## Theme Engine (5 categories, equal distribution)
1. syutain_ops — operations (max 2/day to prevent fixation)
2. ai_tech_trend — AI/tech news from Grok X search + intel_items
3. creator_media — video/VTuber/drone/photo/advertising
4. philosophy_bip — Build in Public philosophy, design decisions
5. shimahara_fields — business/startup/marketing/culture

## Architecture Notes
- LLM routing: choose_best_model_v6() — gpt-4o-mini for SNS+articles, local for light tasks
- SNS + articles: gpt-4o-mini via OpenRouter (¥136/month). Fallback: qwen3-235b → Gemini Flash
- 4 account-specific prompts: shimahara X (humor 40%/honest 95%) / syutain X (75%/90% + memes) / Bluesky (150 char, Build in Public) / Threads (empathy, no money talk)
- Timezone: all scheduled_at must be JST-aware (timezone(timedelta(hours=9)))
- Destructive ACTIONs: never via LLM free-text, only regex direct route or ACTION tag

<!-- AUTO-CHANGELOG-START -->
<!-- このセクションは tools/codex_auto_reflector.py によって毎日09:40 JSTに自動更新されます。手動編集禁止。 -->

## Auto Changelog (last 7 days, updated 2026-04-17 09:41 JST)

We need to output Markdown only, no extra text. The answer must be the Markdown section. We need to produce a Markdown section with headings and bullets based on the git log. Must obey the rules: no merge commits, typo fixes, auto-stats, WIP etc. Filter out commits that are just updating codex.md auto-stats, live stats, auto-refresh codex.md changelog etc. So we keep only meaningful commits: those with actual feature/fix.

From log, meaningful commits:

- a6d63a5: Zenn article (article file) - maybe not game mechanic? It's an article, maybe ignore? Probably exclude as not gameplay.

- First, I need to process the git log input provided by the user.
- The task is to generate an "Auto Changelog" section in Markdown for Codex.
- Rules:
  1. Use ### headings for feature categories (e.g., "### SNS Pipeline", "### Monitoring").
  2. Each entry: one line bullet, 80-140 characters, format "filename: what changed".
  3. Split commits with multiple points into separate bullets.
  4. Exclude: meaningless merges, typo fixes, AUTO-STATS updates, WIP commits.
  5. Don't include LLM call counts or specific numbers (those are for AUTO-STATS).
  6. No commit hashes or timestamps.
  7. Total output <= 60 lines.
  8. Output only Markdown, no preface.

- I must group commits into logical categories. Looking at the changes, I can categorize by:
  - SNS Pipeline (related to X/Twitter replies, title generation, etc.)
  - Monitoring/Stats (but AUTO-STATS is excluded, so maybe just README updates for stats? But rule 5 says don't write LLM calls or specific numbers, and rule 4 excludes AUTO-STATS updates. However, README updates for live stats might be okay if not AUTO-STATS? But rule 4 says "AUTO-STATS更新" is excluded. The log shows "Update live stats" on README.md. Rule 4 says "AUTO-STATS更新" is excluded, but "live stats" might be different. However, rule 5 says "LLM呼び出し数や具体数値は書かない (AUTO-STATSで別管理)", so perhaps live stats updates are about AUTO-STATS? To be safe, I'll exclude any commit that mentions "live stats" or "auto-stats" as they likely relate to AUTO-STATS.
  - But let's check: the user says in rule 4: "意味のない merge commit、typo fix、AUTO-STATS更新、WIPコミットは除外". So "Update live stats" might be considered AUTO-STATS更新? Possibly. However, in the log, "Update live stats" is on README.md, while "Update codex.md auto-stats" is on codex.md. Rule 4 says "AUTO-STATS更新" is excluded, so both should be excluded. Similarly, "Update live stats" on README.md is likely part of the same system.

  Let's list all commits and decide:

  Commits to exclude (per rule 4):
  - Any commit with "auto-stats" in message: b5fb7ce, 323abf9, 80d812a, af981eb, c713c39, etc. (all "Update codex.md auto-stats")
  - Any commit with "live stats": 7def591, 70f9992, 75a2d74, cd743f4, 43ea331, etc.
  - Commits with "chore(codex): auto-refresh codex.md changelog": 0d1e8e3, 9442f4a, 11c579f, 0befc20, etc. (these are chores for codex, likely excluded as chores? But rule 4 doesn't explicitly exclude chore, but rule 4 says "意味のない merge commit、typo fix、AUTO-STATS更新、WIPコミットは除外". Chore might be considered meaningful if it's not those. However, "chore(codex): auto-refresh codex.md changelog" is likely a routine update that might be considered meaningless for changelog? But rule 4 doesn't say to exclude chore. However, in the context of generating a changelog for Codex, updating the changelog itself might be meta and excluded? But the user didn't say to exclude chore. However, looking at the examples in the log, many are chores for codex, and if we include them, the changelog would be full of self-referential updates. But the user didn't specify to exclude chore. However, rule 4 says "意味のない" (meaningless) commits, and auto-refresh of changelog might be considered meaningless for the changelog itself. To be safe, I'll exclude any commit that is about updating the changelog or stats, as they are likely not meaningful for the changelog we're generating.

  Let's think from the perspective of what Codex would care about: changes to the system's functionality, not maintenance of its own documentation or stats.

  So I'll exclude:
  - All commits that modify only codex.md and README.md for stats/changelog updates.
  - Specifically:
    - Commits modifying codex.md with messages: "Update codex.md auto-stats", "chore(codex): auto-refresh codex.md changelog"
    - Commits modifying README.md with "Update live stats"
    - Commits that are only about stats/changelog maintenance.

  Now, let's list all commits and see what remains.

  First, list all commits from the log (newest first):

  1. b5fb7ce 2026-04-17: Update codex.md auto-stats (2026-04-17) → codex.md → EXCLUDE (auto-stats)
  2. 7def591: Update live stats (2026-04-17) → README.md → EXCLUDE (live stats)
  3. 0d1e8e3: chore(codex): auto-refresh codex.md changelog (2026-04-16) → codex.md → EXCLUDE (chore for changelog)
  4. 323abf9: Update codex.md auto-stats (2026-04-16) → codex.md → EXCLUDE
  5. 70f9992: Update live stats (2026-04-16) → README.md → EXCLUDE
  6. 9442f4a: chore(codex): auto-refresh codex.md changelog (2026-04-15) → codex.md → EXCLUDE
  - 80d812a: Update codex.md auto-stats (2026-04-15) → codex.md → EXCLUDE
  - 75a2d74: Update live stats (2026-04-15) → README.md → EXCLUDE
  - 11c579f: chore(codex): auto-refresh codex.md changelog (2026-04-14) → codex.md → EXCLUDE
  - af981eb: Update codex.md auto-stats (2026-04-14) → codex.md → EXCLUDE
  - cd743f4: Update live stats (2026-04-14) → README.md → EXCLUDE
  - a6d63a5: Zenn: AIエージェントの暴走防止: LoopGuard 9層の設計と「なぜ9層も必要だったか」 → articles/5f42b256a059fc7b.md → This is adding an article. Should we include? It's a content addition. But rule doesn't exclude articles. However, for Codex changelog, it might be relevant if Codex manages content. But let's see category.
  - 0befc20: chore(codex): auto-refresh codex.md changelog (2026-04-13) → codex.md → EXCLUDE
  - c713c39: Update codex.md auto-stats (2026-04-13) → codex.md → EXCLUDE
  - 43ea331: Update live stats (2026-04-13) → README.md → EXCLUDE
  - 8d1350c: feat(note): title generation patterns from engagement data + goal exclusions → brain_alpha/content_pipeline.py → KEEP (feat)
  - 7d4bda9: chore(daily-goal): add exclusion list for user-deferred topics → tools/daily_goal_generator.py → KEEP? chore but meaningful? Rule 4 doesn't exclude chore if not meaningless. This seems meaningful.
  - bc1e58b: feat(x-reply): AGI official stance + expanded persona_facts to 300 chars + self-deep keyword trigger → brain_alpha/x_reply_generator.py → KEEP
  - 964b9b4: fix(x-reply): expand serious-tone keyword list (AGI, 論拠, ふざけず, etc) → brain_alpha/x_reply_generator.py → KEEP
  - e70898c: fix(x-reply): default to standard Japanese, use dialect only when recipient does → brain_alpha/x_reply_generator.py → KEEP
  - 74ea189: feat(x-reply): designer proxy voice + auto-load daichi persona on trigger → brain_alpha/x_reply_generator.py → KEEP
  - 1e63d5e: feat(x-reply): reply mechanism disclosure + deep knowledge signaling → brain_alpha/x_reply_generator.py → KEEP
  - aaee68d: fix(x-reply): per-tweet tone detection + 90% past-reference rate → brain_alpha/x_reply_generator.py → KEEP
  - 9ce8bc4: fix(tavily): replace non-existent search_tavily with TavilyClient.search → scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py → KEEP (fix)
  - cfca3cb: fix(mcp): extend OpenAI key pattern to match sk-proj- format → tools/mcp_malware_verification.py → KEEP
  - 8e0a6d7: refactor(browser): P2-5 promote Playwright to Layer 1, demote Lightpanda → agents/browser_agent.py → KEEP (refactor)
  - f618fbc: feat(mcp): P2-4 malware verification for MCP tool calls → tools/mcp_malware_verification.py → KEEP (feat)

  Also, there is 7d4bda9 which is a chore but seems meaningful.

  Now, let's list all commits to keep:

  1. a6d63a5 2026-04-13: Zenn: AIエージェントの暴走防止: LoopGuard 9層の設計と「なぜ9層も必要だったか」 → articles/5f42b256a059fc7b.md
  2. 8d1350c 2026-04-12: feat(note): title generation patterns from engagement data + goal exclusions → brain_alpha/content_pipeline.py
  3. 7d4bda9 2026-04-12: chore(daily-goal): add exclusion list for user-deferred topics → tools/daily_goal_generator.py
  4. bc1e58b 2026-04-12: feat(x-reply): AGI official stance + expanded persona_facts to 300 chars + self-deep keyword trigger → brain_alpha/x_reply_generator.py
  5. 964b9b4 2026-04-12: fix(x-reply): expand serious-tone keyword list (AGI, 論拠, ふざけず, etc) → brain_alpha/x_reply_generator.py
  6. e70898c 2026-04-12: fix(x-reply): default to standard Japanese, use dialect only when recipient does → brain_alpha/x_reply_generator.py
  7. 74ea189 2026-04-12: feat(x-reply): designer proxy voice + auto-load daichi persona on trigger → brain_alpha/x_reply_generator.py
  8. 1e63d5e 2026-04-12: feat(x-reply): reply mechanism disclosure + deep knowledge signaling → brain_alpha/x_reply_generator.py
  9. aaee68d 2026-04-12: fix(x-reply): per-tweet tone detection + 90% past-reference rate → brain_alpha/x_reply_generator.py
  10. 9ce8bc4 2026-04-12: fix(tavily): replace non-existent search_tavily with TavilyClient.search → scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py
  11. cfca3cb 2026-04-12: fix(mcp): extend OpenAI key pattern to match sk-proj- format → tools/mcp_malware_verification.py
  12. 8e0a6d7 2026-04-12: refactor(browser): P2-5 promote Playwright to Layer 1, demote Lightpanda → agents/browser_agent.py
  13. f618fbc 2026-04-12: feat(mcp): P2-4 malware verification for MCP tool calls → tools/mcp_malware_verification.py

  Now, I need to group these into categories.

  Looking at the files:
  - brain_alpha/content_pipeline.py → related to note title generation → could be "Content Pipeline" or "SNS Pipeline" (since it uses engagement data from SNS)
  - tools/daily_goal_generator.py → daily goal generation → could be "Goal Generation" or "Planning"
  - brain_alpha/x_reply_generator.py → multiple commits → all related to X (Twitter) reply generation → clearly "SNS Pipeline" or "X Reply System"
  - scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py → related to Tavily fix → could be "External Services" or "Tavily Integration"
  - tools/mcp_malware_verification.py → two commits: one fix, one feat → related to MCP malware verification → could be "MCP Security" or "Tool Safety"
  - agents/browser_agent.py → browser agent refactor → could be "Browser Automation" or "Agent Tools"

  Also, the article commit: a6d63a5 → articles/... → could be "Documentation" or "Content", but since it's an article, maybe not core system. However, the user didn't specify to exclude articles. But for Codex changelog, it might be relevant if Codex manages content. However, looking at the categories, perhaps we can have a "Content" category.

  But let's see the user's example: "### SNS Pipeline", "### Monitoring". So they expect categories like that.

  Let's group:

  1. SNS Pipeline (for X/Twitter related changes):
     - brain_alpha/x_reply_generator.py: multiple commits (bc1e58b, 964b9b4, e70898c, 74ea189, 1e63d5e, aaee68d)
     - brain_alpha/content_pipeline.py: 8d1350c (title generation patterns from engagement data) → this uses SNS engagement data, so related.

  2. Goal Generation / Planning:
     - tools/daily_goal_generator.py: 7d4bda9 (chore but meaningful)

  3. External Services / Tavily:
     - scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py: 9ce8bc4

  4. MCP Security:
     - tools/mcp_malware_verification.py: cfca3cb, f618fbc

  5. Browser Automation:
     - agents/browser_agent.py: 8e0a6d7

  6. Content / Documentation:
     - a6d63a5: articles/... (Zenn article)

  However, the article commit might be considered content addition, but for Codex changelog, it might be relevant if Codex is used for content management. But let's see if we can include it under a "Content" category.

  Now, for each commit, I need to create bullet points. If a commit has multiple points (like bc1e58b has three points), I need to split them.

  Let's go through each kept commit and split if necessary.

  1. a6d63a5: 
     - Message: "Zenn: AIエージェントの暴走防止: LoopGuard 9層の設計と「なぜ9層も必要だったか」"
     - File: articles/5f42b256a059fc7b.md
     - This is a single point: added an article. So one bullet: "articles/5f42b256a059fc7b.md: Added Zenn article on LoopGuard 9-layer design for AI agent runaway prevention"

  2. 8d1350c:
     - Message: "feat(note): title generation patterns from engagement data + goal exclusions"
     -

<!-- AUTO-CHANGELOG-END -->

## Recent Changes (2026-04-11)

### Strategy automation (戦略書完全自動実行)
- `tools/strategy_book_loader.py` (new): runtime loader for `strategy/diffusion_execution_plan.md` (gitignored). Parses Day 1-7, pinned post A/B, KPI targets, callout nicknames. Contains zero verbatim strategy text — all from book at runtime.
- `tools/strategy_plan_parser.py`: sync loader output to `strategy_plan_items` table (idempotent)
- `tools/strategy_plan_executor.py`: daily 09:05 JST, picks today's pending items, resolves dynamic values from DB (python_lines/llm_calls/api_total etc), routes x_post→posting_queue / note_article→product_packages / reply_day→skip
- `tools/strategy_week_selector.py`: Monday 03:00 JST, analyzes last week's top-3 posts, LLM identifies emotion axis, generates 7 days of Day N+1 to N+7 scripts

### Note publication bug fix
- `scheduler.py:note_quality_check`: `publish_verdict='publish_ready'` drafts are now inserted into `product_packages` (status='ready'). Previously drafts sat in files with no pipeline path to publication.
- `tools/note_publisher.py:reset_publish_url_invalid_packages()`: resets `publish_url_invalid` packages to 'ready' after 24h for retry. Job runs daily 00:30 JST.

### Orphan draft retry
- `brain_alpha/note_quality_checker.py:retry_limbo_stage2()`: finds `final_status='checked'` + `stage2_verdict IS NULL` records, re-runs stage2. Called from `note_quality_check` every 30min.

### SNS false-positive fact-check fix
- `brain_alpha/sns_batch.py`: decimal→% conversion (0.60→60%) added with exclusions. `check_falsity` and `_check_sns_factual` now have score marker exemption (スコア/品質/精度/ギャップ etc).

### X 2026 Algorithm Optimization (MAJOR)
- Research: reply×13.5 weight, first 30-min single strongest factor, external links near-zero distribution, conversation chain = 150x like weight
- `sns_batch.py`: shimahara+syutain `system_prompts` updated with X 2026 rules (1-line hook, no URLs in body, OOB viral targeting, real-measured numbers only)
- `sns_batch.py`: automatic URL strip for x/bluesky/threads posts
- `sns_batch.py`: posting slot times reallocated to JST peak
- `tools/x_boost_loop.py` (new): runs every 7 min, finds posted tweets from last 20 min, auto cross-replies shimahara↔syutain_beta to trigger conversation chain within first 30min. Daily cap 6, UNIQUE constraint dedup.

### X 自動返信 proactive expansion (multi-user)
- `tools/x_mention_monitor.py`: `USER_PROFILES` is now loaded at runtime from `strategy/x_user_profiles.json` (gitignored). Each profile has tone/scope/protected/tomo_member/context.
- Added `_proactive_reply_sakata()` (friend user, configurable rate, daily cap) and `_proactive_reply_shimahara_posts()` (owner, higher rate)
- 4-layer dedup: API exclude=retweets,replies + `_is_already_replied` + UNIQUE(trigger_tweet_id) + `_record_reply(posting)` pre-write
- `brain_alpha/x_reply_generator.py`: rewritten for multi-user with `user_profile` parameter. `deep_reference_rate` — set via `X_DEEP_REFERENCE_USERNAMES` env var; listed users get 70%, others 30%.
- Target user IDs and usernames are sourced from env vars / gitignored JSON — no personally-identifying info in source code.

### Active reply automation (戦略書Day 3)
- `tools/active_reply_shimahara.py` (new): runs 10:30/14:30/18:30 JST. Uses intel_items grok_x_research X URLs filtered by AI/video/VTuber keywords. Excludes self-accounts. Daily cap 5.

### Pinned post A/B rotation
- `tools/pinned_post_ab_test.py` (new): Monday 09:10 JST. A/B variants loaded runtime from strategy_book_loader. X API v2 Free doesn't support direct pin API, rotates via posting_queue insertion.

### Monitoring jobs
- `tools/pdl_monitor.py` (new): hourly PDL worker health check
- `tools/codex_auth_monitor.py` (new): daily 10:00 JST, alerts on 5 days or less remaining

### X Monetization Tracker
- `tools/x_monetization_tracker.py` (new): tracks 広告収益分配 (500K imp/3mo) and サブスクリプション (2000 verified followers + 500K imp/3mo). Integrated into `kpi_audit_weekly` Monday 07:30.

### Fact-based mandate
- User directive 2026-04-11: "事実ベースで虚偽内容や誇張は可能な限り控える"
- All content generation must use DB-measured values, not strategy book snapshot numbers

### CRITICAL FIX: codex_auto_fix destructive revert eliminated (2026-04-11)
**Root cause of 2026-04-11 05:19 2337-line data loss incident**:
- `codex_auto_fix.py` line 160 used `git checkout -- .` which wiped ALL uncommitted changes when Codex diff exceeded 100 lines
- Because `git diff --stat` counts ALL uncommitted work (not just Codex's), the 2000+ line pre-session work triggered the limit and got wiped

**Fixes applied**:
- `tools/codex_auto_fix.py`: `git checkout -- .` replaced with per-file `git checkout HEAD -- f` (only reverts Codex's own changes)
- `tools/codex_auto_fix.py`: line count calculation now uses `git diff --stat -- files_changed` (only Codex's files)
- `tools/codex_auto_fix.py`: git stash→pop safety removed, replaced with independent snapshot to `data/snapshots/codex_auto_fix/` (git-independent backup)
- `tools/codex_content_optimizer.py`: same fix applied
- Discord alert added when revert happens

## Recent Changes (2026-04-09)
- SNS V3: 4 account-specific prompts (shimahara/syutain/bluesky/threads)
- SNS V3: gpt-4o-mini for all SNS+article generation (was free models)
- SNS V3: 70 abnormal patterns + 40 opening patterns + 1000 variation combos
- SNS V3: exclusive choice per post: abnormal 45% / meme structure 30% / slang 25%
- SNS V3: identity separation rules (SYUTAINβ ≠ shimahara, no "当社/弊社")
- SNS V3: material matching (effect number check, proper noun check removed)
- SNS V3: retry 3→5, missing fill at 00:00 + 02:00
- SNS V3: Bluesky 300→150 chars, Threads no money talk
- SNS V3: 257 meme/slang assets (niconico 30 + 2ch 38 + comedy 21 + anime 75 + structures 40 + net 53)
- Article: Stage 4 rewrite narrator fix (was "shimahara voice" → now "SYUTAINβ voice")
- Article: gpt-4o-mini for note_article/note_draft
- Sensitive strategy files removed from git (SOUL.md, meme vocab, humor patterns, diffusion plan)
- LLM: Qwen 3.6 Plus:free deprecated → model chain (Gemma4 → Nemotron → Qwen3 → Step)
- LLM: chat task restored to Claude Haiku (not Nemotron Nano)
- Qiita/Zenn: independent tech article pipeline + auto-publish + SNS announce
- SNS batch5: 00:00 missing post auto-fill
- SNS batch3: X backup at 23:00 (dedup fills only missing posts)
- Quality score V2: 10-axis with theme relevance, account-specific persona eval
- Fact checker: 4-layer (DB match → intel cross-ref → Tavily search → primary source verify)
- Falsity filter: detect → fix → recheck loop (not just reject)
- Theme-aware falsity: off-topic claims flagged, LLM numbers only scored in ops theme

## Improvement Targets & KPIs (Codex改善指標)

Codexが自律改善を行う際、以下の指標を基準に判断すること。

### SNS投稿品質
| 指標 | 現状 | 目標 | 計測方法 |
|------|------|------|---------|
| 品質スコア平均 | 0.63-0.73 | 0.75+ | posting_queue.quality_score AVG |
| 却下率 | ~30% | 15%以下 | rejected / total |
| テーマ多様性 | 5カテゴリ | 5カテゴリ均等 | theme_category分布 |
| 虚偽検出率 | 要計測 | 0% | falsity_blocked / total |
| LLM数字固着 | 頻発 | 10投稿に1回以下 | 「LLM呼び出し」を含む投稿比率 |
| アカウント声一致 | 要計測 | shimahara+0.03以上 / syutain+0.03以上 | check_account_voice AVG |

### note記事品質
| 指標 | 現状 | 目標 | 計測方法 |
|------|------|------|---------|
| 日次公開数 | 0-1本/日 | 1本/日安定 | product_packages(note, published) per day |
| 品質スコア | 0.80-0.84 | 0.85+ | content_pipeline quality_score |
| 事実チェック通過率 | ~30% | 70%+ | fabrication_risk < 0.6 の比率 |
| 実データ注入量 | 3,800字 | 4,000字+ | _collect_system_data_for_article 出力 |
| 一人称一致（私） | 95% | 100% | 「僕」混入ゼロ |

### システム安定性
| 指標 | 現状 | 目標 | 計測方法 |
|------|------|------|---------|
| LLM ReadTimeout | 3-4件/日 | 1件/日以下 | event_log(llm.error) |
| OpenRouter 429 | 頻発 | モデルチェーンで自動回避 | llm_router WARNING count |
| SNS投稿配信率 | 80%+ | 95%+ | posted / (posted + pending + failed) |
| Bluesky 400エラー | 0件 | 0件維持 | event_log(sns.post_failed, bluesky) |

### 改善の方向性
1. **品質向上**: プロンプト改善、素材選定精度向上、few-shot例の更新
2. **多様性**: テーマエンジンのカテゴリバランス調整、固着検知の精度向上
3. **虚偽防止**: フィルターパターン追加、生成プロンプトの制約強化
4. **コスト効率**: ローカルLLM比率の維持、無料モデルの活用最大化
5. **安定性**: タイムアウト対策、フォールバックチェーンの最適化

### Codex改善時の原則
- **壊すな**: 動いているものを壊さない。改善は漸進的に
- **測れ**: 改善前後で上記KPIを比較。数字で効果を示す
- **戻せ**: 変更は小さく。100行以内。問題があれば即リバート (個別ファイル単位で。`git checkout -- .` 等の全checkout は絶対禁止)
- **記録しろ**: 何を変えたか、なぜ変えたかをevent_logに記録

<!-- AUTO-STATS-START -->
<!-- このセクションは scheduler.py:update_codex_stats によって毎日09:35 JSTに自動更新されます。手動編集禁止。 -->

## Live Auto-Stats (updated 2026-04-18 09:35 JST)

### System Metrics (PostgreSQL live query)
- LLM Calls Total: **19,304**
- LLM Cost Cumulative: **¥3,310**
- Event Log Entries: **77,787**
- SNS Posts Posted: **943**
- note Published: **26**
- intel_items: **2,320**
- persona_memory: **718**
- Goal Packets: **1 active / 99 completed**
- LoopGuard Events: **54**

### Code Metrics
- scheduler.py: **6911** lines
- brain_alpha/sns_batch.py: **3102** lines
- brain_alpha/content_pipeline.py: **1875** lines
- brain_alpha/note_quality_checker.py: **1457** lines
- tools/x_mention_monitor.py: **1233** lines
- app.py: **3684** lines
- Scheduler Jobs Registered: **136**

### X Monetization Progress (TOP PRIORITY)
- Verified Followers: **1,757** / 2,000 target (gap: 243)
- 90-day Impressions: **95,026** / 5,000,000 target (1.90%)

**Note for Codex**: これらの値は毎日09:35 JSTに最新化されます。これより前の手動記載数値(Recent Changesセクション等)は、記録時点のスナップショットです。現在値を参照したい場合は必ずこのセクションを見ること。

<!-- AUTO-STATS-END -->
