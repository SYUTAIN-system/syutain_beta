# Codex Instructions for SYUTAINβ

## Project
SYUTAINβ is a 50K+ line distributed autonomous AI business OS running on 4 nodes.

## Rules
1. NEVER modify: agents/os_kernel.py, tools/emergency_kill.py, agents/approval_manager.py, .env, credentials.json, CLAUDE.md
2. Always run syntax check: `python3 -c "import ast; ast.parse(open('file').read())"` after any edit
3. Use try-except for all tool/API calls
4. Settings from .env or DB, never hardcode
5. Test before committing

## Key Files
- app.py: FastAPI server (3,654 lines, 70 endpoints)
- scheduler.py: Job scheduler (3,464 lines, 60+ jobs)
- CLAUDE.md: 26 absolute rules

## Don't
- Access .env or any credentials
- Modify core safety systems (loop_guard, emergency_kill, approval_manager)
- Make changes > 500 lines without review
- Fabricate test data or statistics
