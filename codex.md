# Codex Instructions for SYUTAINβ

## Project
SYUTAINβ is a 62K+ line distributed autonomous AI business OS running on 4 nodes (ALPHA macOS + BRAVO/CHARLIE/DELTA Ubuntu).
Designer: 島原大知 (non-engineer, 15yr video production, 8yr VTuber industry support).

## Rules
1. NEVER modify: agents/os_kernel.py, tools/emergency_kill.py, agents/approval_manager.py, tools/loop_guard.py, .env, credentials.json, token.json, CLAUDE.md
2. Always run syntax check: `python3 -c "import ast; ast.parse(open('file').read())"` after any edit
3. Use try-except for all tool/API calls
4. Settings from .env or DB, never hardcode
5. Test before committing (syntax + integration smoke)
6. event_log INSERT must include `category` column (NOT NULL constraint)

## Key Files
- app.py: FastAPI server (~3,685 lines, 64 endpoints, JWT auth)
- scheduler.py: Job scheduler (~5,400 lines, 66+ jobs)
- CLAUDE.md: 32 absolute rules
- Brain-β: bots/discord_bot.py + bot_conversation.py + bot_actions.py (破壊的ACTION直接ルート必須)

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
- LLM routing: choose_best_model_v6() — local LLM first, articles use free cloud
- SNS posts: local LLM only (nemotron-jp / qwen3.5:9b), NOT OpenRouter
- Articles: OpenRouter Qwen 3.6 Plus (free) → Gemini Flash fallback
- Timezone: all scheduled_at must be JST-aware (timezone(timedelta(hours=9)))
- Destructive ACTIONs: never via LLM free-text, only regex direct route or ACTION tag

## Recent Changes (2026-04-08)
- SNS V2: material-based generation (8 sources, max 7 per post)
- SNS V2: falsity filter → detect → fix → recheck loop (not just reject)
- SNS V2: account voice check (shimahara/syutain score adjustment)
- SNS V2: hashtags generated in post-processing, not by LLM
- Article: SYUTAINβ perspective (一人称「私」), shimahara narration rules
- Article: seed bank for "rumination" process, 5-layer rotation enforced
- Article: note_material_collector pre-collects materials at 07:00
- Article: fact checker relaxed (3+ critical to reject, number drift OK)
- LLM: Qwen 3.6 Plus:free deprecated → model chain (Gemma4 → Nemotron → Qwen3 → Step)
- LLM: chat task restored to Claude Haiku (not Nemotron Nano)
- Qiita/Zenn: independent tech article pipeline + auto-publish + SNS announce
- SNS batch5: 00:00 missing post auto-fill
- SNS batch3: X backup at 23:00 (dedup fills only missing posts)
