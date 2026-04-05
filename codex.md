# Codex Instructions for SYUTAINβ

## Project
SYUTAINβ is a 58K+ line distributed autonomous AI business OS running on 4 nodes (ALPHA macOS + BRAVO/CHARLIE/DELTA Ubuntu).

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
