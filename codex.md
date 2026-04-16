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

## Auto Changelog (last 7 days, updated 2026-04-16 09:41 JST)

We need to generate Auto Changelog section from the provided git log, following rules.

We must filter out:
- merge commits, typo fix, AUTO-STATS updates, WIP commits.
- Look for commits with messages like "Update codex.md auto-stats", "Update live stats", "chore(codex): auto-refresh codex.md changelog", etc. These should be excluded.

We need to group by functional categories (like SNS Pipeline, Monitoring) and produce bullet entries: "ファイル名: 何をどう変えたか" (File name: what changed). Each entry one line 80-140 characters (Japanese). No commit hash, no date. No numbers about LLM calls.

We must limit to <=60 lines total.

We need to parse commits from newest to oldest (already given in order: newest first). We'll pick meaningful commits.

Let's list commits with messages and changed files:

We'll go through each block.

Commit: 323abf9 - Update codex.md auto-stats (2026-04-16) -> codex.md -> exclude (auto-stats)

70f9992 - Update live stats (2026-04-16) -> README.md -> exclude (live stats)

9442f4a - chore(codex): auto-refresh codex.md changelog (2026-04-15) -> codex.md -> exclude (codex changelog refresh)

80d812a - Update codex.md auto-stats (2026-04-15) -> codex.md -> exclude

75a2d74 - Update live stats (2026-04-15) -> README.md -> exclude

11c579f - chore(codex): auto-refresh codex.md changelog (2026-04-14) -> codex.md -> exclude

af981eb - Update codex.md auto-stats (2026-04-14) -> codex.md -> exclude

cd743f4 - Update live stats (2026-04-14) -> README.md -> exclude

a6d63a5 - Zenn: AIエージェントの暴走防止: LoopGuard 9層の設計と「なぜ9層も必要だったか」 -> articles/5f42b256a059fc7b.md -> This is a documentation/article. Might be relevant to "Documentation" category. Should we include? It's not code but content. The instruction: Auto Changelog for Codex? Usually includes changes to code. But could include docs. Not explicitly excluded. We'll consider maybe include under "Documentation". However it's a Zenn article, not code. Might be okay but maybe they'd want only code changes. We'll see later.

0befc20 - chore(codex): auto-refresh codex.md changelog (2026-04-13) -> codex.md -> exclude

c713c39 - Update codex.md auto-stats (2026-04-13) -> codex.md -> exclude

43ea331 - Update live stats (2026-04-13) -> README.md -> exclude

8d1350c - feat(note): title generation patterns from engagement data + goal exclusions
- brain_alpha/content_pipeline.py: added effective title patterns and anti-patterns to the title generation system prompt. Based on actual engagement data (X/Bluesky/Threads announce post performance): Good: concrete numbers, failure stories, conversation quotes, cost figures; Bad: 日報 numbers, internal terms, abstract AI essays, poetic openers. note.com doesn't expose engagement API, so we use the SNS announce post engagement as a proxy for title effectiveness.
- Also note about tools/daily_goal_generator.py: exclusion list already committed separately. (But the commit only changed brain_alpha/content_pipeline.py? Actually only that file shown after ---. So we only have that file.)
We should include entry: brain_alpha/content_pipeline.py: タイトル生成プロンプトにエンゲージメントデータから導出した効果的パターンとアンチパターンを追加

7d4bda9 - chore(daily-goal): add exclusion list for user-deferred topics
- tools/daily_goal_generator.py: Added to _GOAL_GENERATION_SYSTEM prompt as "除外テーマ" block. Updated "優先したい領域" to focus on note/Bluesky/Threads quality, intel pipeline accuracy, and unresolved carry-over tasks.
We'll include: tools/daily_goal_generator.py: ユーザー延期トピックの除外リストを追加し、優先領域をnote/Bluesky/Threads品質等に絞り込み

bc1e58b - feat(x-reply): AGI official stance + expanded persona_facts to 300 chars + self-deep keyword trigger
- brain_alpha/x_reply_generator.py: added AGI policy to _COMMON_RULES, expanded persona_facts limit 150→300 chars, added self-deep keywords, saved designer's AGI view as persona_memory.
We'll need possibly split into multiple bullets if multiple aspects. But rule: same commit even if multiple points can be split if they are distinct. We could produce maybe two bullets: one for AGI stance, one for persona_facts expansion, one for self-deep trigger. However each bullet line length limited; we can combine but maybe separate.

964b9b4 - fix(x-reply): expand serious-tone keyword list (AGI, 論拠, ふざけず, etc)
- brain_alpha/x_reply_generator.py: added keywords: 論拠, ふざけず, 真面目に, 本気で, AGI, 可能性, 証明, 聞いていますか, 聞いてますか, 答えてください, 説明して
We'll include: brain_alpha/x_reply_generator.py: 真面目トリガー キーワードリストを拡張（論拠、ふざけず等）してシリアスな質問への応答を標準日本語に

e70898c - fix(x-reply): default to standard Japanese, use dialect only when recipient does
- brain_alpha/x_reply_generator.py: changed tone_match_respectful rule: default standard Japanese, Kansai only when recipient tweet uses it.
We'll include: brain_alpha/x_reply_generator.py: トーンマッチングを標準日本語デフォルトに変更、受信者のツイートが関西弁の時のみ方言使用

74ea189 - feat(x-reply): designer proxy voice + auto-load daichi persona on trigger
- brain_alpha/x_reply_generator.py: when asked about designer, auto-load daichi persona_memory and use proxy voice rule.
We'll include: brain_alpha/x_reply_generator.py: 設計者代理発言ルールを追加し、設計者に関する質問時にdaichi personaを自動ロード

1e63d5e - feat(x-reply): reply mechanism disclosure + deep knowledge signaling
- brain_alpha/x_reply_generator.py: added disclosure of selective reply mechanism and deep knowledge hint.
We'll include: brain_alpha/x_reply_generator.py: 返信メカニズムの開示と「知りすぎ」シグナリングルールを追加

aaee68d - fix(x-reply): per-tweet tone detection + 90% past-reference rate
- brain_alpha/x_reply_generator.py: inline tone detection, override for serious tweets, past-reference rate raised to 90%.
We'll include: brain_alpha/x_reply_generator.py: ツイート単位のトーン検出を実装し、真面目な質問ではカジュアルマーカーをブロック、過去参照率を90%に上昇

9ce8bc4 - fix(tavily): replace non-existent search_tavily with TavilyClient.search
- scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py: replaced import/call.
We'll need to group maybe under "Tavily integration fix" or "External API". Could create category "External Tools". For each file we could list but maybe combine: "Tavily関連モジュール: search_tavily を TavilyClient.search に置換し、ImportError を解消". That's one bullet covering multiple files.

cfca3cb - fix(mcp): extend OpenAI key pattern to match sk-proj- format
- tools/mcp_malware_verification.py: updated regex.
We'll include: tools/mcp_malware_verification.py: OpenAIキー検出正規表現をsk-proj-形式にも対応させる

8e0a6d7 - refactor(browser): P2-5 promote Playwright to Layer 1, demote Lightpanda
- agents/browser_agent.py: reordered layer priority.
We'll include: agents/browser_agent.py: ブラウザーエージェントでPlaywrightをレイヤー1に昇格、Lightpandaを3に降格

f618fbc - feat(mcp): P2-4 malware verification for MCP tool calls
- tools/mcp_malware_verification.py: new module scanning arguments before execution.
We'll include: tools/mcp_malware_verification.py: MCPツール引数にマルウェア検証を追加（コマンドインジェクション、SSRF等5つの脅威ベクトル）

Now also we have the Zenn article commit a6d63a5. Might be considered documentation. Could add under "Documentation": articles/5f42b256a059fc7b.md: Zenn記事「AIエージェントの暴走防止: LoopGuard 9層の設計」を追加

Now we need to group by categories.

Potential categories:
- SNS Pipeline (title generation, x-reply etc)
- Daily Goal Generator
- MCP / Malware verification
- Browser Agent
- Tavily / External API
- Documentation
- Maybe Monitoring? but we excluded live stats.

Let's list all meaningful commits with categorization.

We'll produce bullet lines.

We must ensure total lines <=60. We'll have maybe ~15-20 bullets.

Now craft bullet lines in Japanese, file name colon description.

Check length 80-140 characters. We'll aim ~100 chars.

Let's draft.

1. SNS Pipeline:
- brain_alpha/content_pipeline.py: タイトル生成プロンプトにエンゲージメントデータから導出した効果的パターンとアンチパターンを追加
Count characters? Let's approximate: "脳_alpha/content_pipeline.py:" (maybe 24) + rest... Should be okay.

- brain_alpha/x_reply_generator.py: AGIに関する公式スタンスを_COMMON_RULESに追加し、persona_facts上限を150→300文字に拡張
But we may split.

Better to produce multiple bullets for each facet.

Let's list all x-reply related commits and split.

From bc1e58b:
- brain_alpha/x_reply_generator.py: AGIに関する設計者の見解を persona_memory に保存し、_COMMON_RULES にAGI公式スタンスを追加
- brain_alpha/x_reply_generator.py: persona_facts の文字数上限を 150 → 300 に拡張し、AGI哲学記載が truncate されないように
- brain_alpha/x_reply_generator.py: 自己深掘りキーワード（AGI、汎用人工知能等）を追加し、該当質問時に daichi persona_facts を自動ロード

From 964b9b4:
- brain_alpha/x_reply_generator.py: 真面目トリガー キーワードリストに 「論拠」「ふざけず」「真面目に」等を追加し、シリアスな質問での方言混入を防止

From e70898c:
- brain_alpha/x_reply_generator.py: トーンマッチングを標準日本語デフォルトに変更、受信者ツイートが関西弁の時のみ方言を使用

From 74ea189:
- brain_alpha/x_reply_generator.py: 「設計者ならこう言うと思う」 Proxy Voice ルールを追加し、設計者に関する質問時に daichi persona を自動ロード

From 1e63d5e:
- brain_alpha/x_reply_generator.py: 選択的返信メカニズムの開示と「知りすぎ」シグナリングルールを追加し、返信理由を説明

From aaee68d:
- brain_alpha/x_reply_generator.py: ツイート単位のトーン検出をインライン実装し、真面目な質問ではカジュアルマーカーをブロック、過去参照率を 80% → 90% に上昇

Now also note: there may be overlapping; we might combine some to reduce lines.

But we need to keep lines <=60; splitting is okay.

Now other categories:

Daily Goal Generator:
- tools/daily_goal_generator.py: ユーザーが延期したトピック（死コード掃除、テスト追加等）を除外リストに追加し、優先領域を note/Bluesky/Threads 品質等に絞り込み

MCP Malware Verification:
- tools/mcp_malware_verification.py: OpenAI キー検出正規表現を sk-proj- 形式にも対応させる (cfca3cb)
- tools/mcp_malware_verification.py: MCPツール引数にマルウェア検証を追加（コマンドインジェクション、SSRF、パストラバーサル、秘密漏洩、 oversized 引数の5脅威ベクトル） (f618fbc)

Browser Agent:
- agents/browser_agent.py: ブラウザーエージェントで Playwright をレイヤー1に昇格、Lightpanda をレイヤー3に降格し、抽出処理の優先順位を変更

Tavily fix:
- scheduler.py, tools/budget_guard.py, tools/fact_checker.py, tools/overseas_trend_detector.py: Tavily 関連モジュールで 未定義の search_tavily 呼び出しを TavilyClient().search() に置換し、ImportError を解消

Documentation:
- articles/5f42b256a059fc7b.md: Zenn記事「AIエージェントの暴走防止: LoopGuard 9層の設計となぜ9層も必要だったか」を追加

Now we need to group under headings.

Potential headings:
### SNS Pipeline (タイトル生成・返信)
### Daily Goal Generator
### MCP / セキュリティ
### ブラウザーエージェント
### 外部API連携 (Tavily)
### ドキュメント

Now produce bullet list under each.

We need to ensure each bullet line 80-140 characters. Let's craft each line and count roughly.

We'll produce maybe around 20 bullets.

Let's draft each bullet.

I'll write them in Japanese.

1. SNS Pipeline:
- brain_alpha/content_pipeline.py: タイトル生成プロンプトにエンゲージメントデータから導出した効果的パターン（「具体的数値」「失敗談」）とアンチパターン（「日報番号」「抽象的AI論文」）を追加
Count: Let's approximate characters: "脳_alpha/content_pipeline.py:" (maybe 24) + rest... Should be >80. Let's trust.

But we need to ensure each bullet is one line.

We'll produce.

Let's enumerate:

Under ### SNS Pipeline
- brain_alpha/content_pipeline.py: タイトル生成プロンプトにエンゲージメントデータから導出した効果的パターン（「具体的数値」「失敗談」「会話引用」「コスト」）とアンチパターン（「日報番号」「内部用語」「抽象的AIエッセイ」「詩的オープナー」）を追加

- brain_alpha/x_reply_generator.py: AGIに関する設計者の見解を persona_memory に保存し、_COMMON_RULES に「現行では低い／目指している／到達時に設計者はいない」旨の公式スタンスを追加

- brain_alpha/x_reply_generator.py: persona_facts の文字数上限を 150 → 300 に拡張し、AGI哲学の重要文言が truncate されないように調整

- brain_alpha/x_reply_generator.py: 自己深掘りキーワード（AGI、汎用人工知能、シンギュラリティ、自我、意識、存在意義）を追加し、該当質問時に daichi persona_facts を自動ロード

- brain_alpha/x_reply_generator.py: 真面目トリガー キーワードリストに 「論拠」「ふざけず」「真面目に」「本気で」「AGI」「可能性」「証明」「聞いていますか」等を追加し、シリアスな質問では標準日本語を強制

- brain_alpha/x_reply_generator.py: トーンマッチングを標準日本語デフォルトに変更し、受信者ツイートが関西弁や「コラ」「フハハ」等を使う時のみ方言を使用、それ以外はです／ます調

- brain_alpha/x_reply_generator.py: 「設計者ならこう言うと思う」 Proxy Voice ルールを追加し、設計者に関する質問時に daichi persona を自動ロードし、島原の第一人称「僕」で回答

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

## Live Auto-Stats (updated 2026-04-16 09:35 JST)

### System Metrics (PostgreSQL live query)
- LLM Calls Total: **18,232**
- LLM Cost Cumulative: **¥2,863**
- Event Log Entries: **72,239**
- SNS Posts Posted: **886**
- note Published: **23**
- intel_items: **2,135**
- persona_memory: **718**
- Goal Packets: **1 active / 90 completed**
- LoopGuard Events: **54**

### Code Metrics
- scheduler.py: **6911** lines
- brain_alpha/sns_batch.py: **3200** lines
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
