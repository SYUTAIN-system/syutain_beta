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

## Auto Changelog (last 7 days, updated 2026-04-12 09:41 JST)

### SNS Reply Engine (x-reply)
- brain_alpha/x_reply_generator.py: kusositsureiに対して tone_match_respectful かつ関連過去ツイート存在時に80%確率で過去いじりモードを発動し、過去ツイートを言い回しに取り込む実装
- brain_alpha/x_reply_generator.py: 受信者の Kansai 弁や語尾を理解には使うが SYUTAINβ の生成文体には絶対に反映させないようトーンマーカー漏洩を防止
- brain_alpha/x_reply_generator.py: kusositsurei 限定で語調ミラーリングを許可し、設計者／アイツ／あのおっさん の呼び分けルールを実装
- brain_alpha/x_reply_generator.py: kusositsurei の全ツイート2,568件に対する pgvector ベース意味類似検索を組み込み、返信ごとに上位6件を深層プロファイルに注入
- brain_alpha/x_reply_generator.py: deep_profile に raw_tweet_samples（過去ツイート抜粋）を埋め込み、引用禁止・語彙継承のみで過去知識を自然に織り込むルールを追加
- brain_alpha/x_reply_generator.py: X API から取得した kusositsurei のツイートを LLM で分析し、深層プロファイル JSON を persona_memory に保存してシステムプロンプトに反映

### Scheduler & Monitoring
- scheduler.py: オフピーク時間帯に時間単位スロット（0‑10,20‑23時）を追加し、深夜を含む 24 時間 1 時間以内のメンション検知カバレッジを達成
- tools/x_mention_monitor.py, scheduler.py: メンション最大経過時間を 60 分から 6 時間に緩和し、オフピークに 23 時スロットを追加して見逃し防止

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

## Live Auto-Stats (updated 2026-04-13 09:35 JST)

### System Metrics (PostgreSQL live query)
- LLM Calls Total: **16,178**
- LLM Cost Cumulative: **¥2,139**
- Event Log Entries: **63,609**
- SNS Posts Posted: **783**
- note Published: **18**
- intel_items: **1,835**
- persona_memory: **718**
- Goal Packets: **2 active / 73 completed**
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
