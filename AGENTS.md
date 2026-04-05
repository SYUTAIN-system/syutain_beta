# AGENTS.md - System Capability Map
> Auto-referenced by OS Kernel during perceive phase.
> Last manual update: 2026-04-06

## Nodes

### ALPHA (orchestrator)
- **IP:** (Tailscale VPN / local)
- **HW:** Mac mini M4 Pro 16GB
- **OS:** macOS / launchd
- **LLM:** なし（オーケストレーター専任、推論はBRAVO/CHARLIE/DELTAに委譲）
- **Agents:** os_kernel, approval_manager, proposal_engine, web_ui_server, chat_agent, Brain-β Discord bot, scheduler (66+ジョブ)
- **Services:** PostgreSQL + pgvector, NATS server, FastAPI(:8000), Next.js(:3000), Caddy(:8443), Discord bot
- **Codex:** `/opt/homebrew/bin/codex` (codex-cli 0.118.0, ChatGPT Plus auth, gpt-5.3-codex xhigh reasoning) — gstack_code_review (毎日09:00), gstack_security_audit (日曜02:00), gstack_retro (月曜08:00) で使用
- **CAN:** Orchestrate goals, approve/reject, serve UI, run scheduler, manage DB, Discord Brain-β対話
- **CANNOT:** Run LLM inference locally. No dedicated GPU. bash 3.2 (no `declare -A`).

### BRAVO (heavy inference)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$BRAVO_IP
- **HW:** Ryzen + RTX 5070 12GB
- **OS:** Ubuntu / systemd
- **LLM:** Ollama always-on (KEEP_ALIVE=-1, KV Cache Q8). Models: qwen3.5:9b, qwen3.5:27b (highest_local時のみ、5 tok/s), nemotron-jp (日本語最適), nemotron-mini
- **Services:** syutain-worker-bravo.service, ollama.service, syutain-nats.service
- **Agents:** computer_use_agent, content_worker, browser_agent
- **Browser:** 4-layer (LightPanda:9222 → Stagehand → Chromium:9223 → ComputerUse/gpt-5.4)
- **CAN:** Heavy LLM inference (27B対応), browser automation, content generation
- **CANNOT:** Access PostgreSQL directly (via NATS/API only)

### CHARLIE (inference + batch)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$CHARLIE_IP
- **HW:** Ryzen 9 + RTX 3080 10GB
- **OS:** Ubuntu / systemd (Win11とのdual bootだったが、2026-03後半にUbuntu単独運用に移行)
- **LLM:** Ollama always-on (KEEP_ALIVE=-1, KV Cache Q8). Models: qwen3.5:9b, nemotron-jp
- **Services:** syutain-worker-charlie.service, ollama.service, syutain-nats.service
- **Agents:** inference_worker, batch_processor
- **CAN:** Batch inference, two-stage refinement local drafts
- **CANNOT:** 27Bモデル非対応。並列推論時はBRAVOと負荷分担。

### DELTA (light inference + monitor)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$DELTA_IP
- **HW:** Xeon E5 + GTX 980Ti 6GB + 48GB RAM
- **OS:** Ubuntu / systemd
- **LLM:** Ollama qwen3.5:4b (KEEP_ALIVE=-1, KV Cache Q8)
- **Services:** syutain-worker-delta.service, ollama.service, syutain-nats.service
- **Agents:** monitor_agent, info_collector, health_checker
- **Mutation engine:** Runs here exclusively (encrypted SQLCipher DB)
- **CAN:** Monitor, patrol, info collection, lightweight inference (4B), mutation engine
- **CANNOT:** Heavy inference. Simple tasks only (summarization, classification, short chat)

## Agents

| Agent | Node | Role | Capabilities | Failure Mode | Recovery |
|-------|------|------|-------------|-------------|----------|
| CORTEX | ALPHA | CEO | Heartbeat(10min), pipeline orchestration | LaunchAgent crash | `kill` to restart (KeepAlive) |
| FANG | BRAVO | CSO | KPI report(21:00), strategy | systemd service down | `systemctl restart syutain-worker-fang` |
| NERVE | BRAVO | COO | Meeting management, operations | systemd service down | `systemctl restart syutain-worker-nerve` |
| FORGE | CHARLIE | CTO | Code review | Node offline (Win11 boot) | Wait or route to BRAVO |
| MEDULLA | DELTA | VP | Patrol(30min), CEO deputy | Low inference quality | Escalate to API |
| SCOUT | DELTA | Intel | Multi-source research | Rate limits on sources | Retry with backoff |

All agents have fallback Discord notification on failure.

## Task Routing Rules

1. **Inference tasks:** BRAVO (primary, 9B/27B) → CHARLIE (secondary, 9B) → DELTA (light, 4B) → OpenRouter Qwen3.6 Plus (無料枠180req/day) → Gemini Flash (fallback)
2. **Browser automation:** BRAVO only (4-layer browser stack)
3. **Content generation:** BRAVO/CHARLIE (ローカル) → OpenRouter Qwen3.6 Plus (proposal/strategy/content_final) → Anthropic Claude (premium quality) → Gemini Flash (fallback)
4. **Monitoring/patrol:** DELTA
5. **Info collection:** DELTA (SCOUT)
6. **Code review:** ALPHA Codex `/gstack-review` (gpt-5.3-codex xhigh) — 毎日09:00
7. **Simple text tasks (summary, classification):** DELTA qwen3.5:4b → BRAVO/CHARLIE if quality insufficient
8. **LLM model selection:** Always via `choose_best_model_v6()` (18分岐ルーティング). 2-stage refine: local draft → API polish.

Fallback chain for LLM: local(BRAVO/CHARLIE/DELTA) → OpenRouter Qwen3.6 Plus (無料) → Anthropic/OpenAI/Gemini (有料、budget_guard監視下)

## Known Failure Patterns

| Pattern | Symptom | Fix |
|---------|---------|-----|
| CHARLIE health errors | Repeated `node.health [charlie]` in event_log | 2026-03後半にUbuntu単独化済み（旧dual boot）。ネットワーク/Ollama稼働確認。 |
| Hallucinated confirmation theater | Brain-βが「承認しました」等と返信するがDB更新なし | 2026-04-05修正済。on_message冒頭の正規表現で承認/却下/記事執筆依頼は直接ハンドラに流す。 |
| event_log INSERT silent fail | ジョブ成功するのにDBに記録されない | category NOT NULL制約を必ず書き込む (2026-04-06判明) |
| Discord intents failure | Bot connects but receives zero on_message | Enable Privileged Intents in Developer Portal (presences + members) |
| OpenRouter DeepSeek reasoning | Invalid param error | Use `{"reasoning": {"enabled": False}}` not `{"reasoning": False}` |
| X.com scraping blocked | Headless browser returns 403/empty | Use Jina Search API with `site:x.com` filter |
| macOS Chromium cookies | Cookie decryption fails on copied profile | Keychain-bound; cannot copy profiles between machines |
| Jina API blocked | urllib default UA rejected | Set custom User-Agent header |
| Remote systemd commands fail | Permission denied | Export `XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus` |
| LaunchAgent no log output | Logs appear empty despite bot running | Set `PYTHONUNBUFFERED=1` in plist |
| Semantic loop | Agent repeats same approach | SemanticLoopDetector triggers at threshold; switch plan or escalate |
| Budget 90% | Emergency Kill triggered | Halt all API calls; notify via Discord |

## Tool Availability

| Tool | Dependency | Rate Limit | Notes |
|------|-----------|-----------|-------|
| Tavily (search) | TAVILY_API_KEY | ~1000/month | Web search |
| Jina (reader/search) | JINA_API_KEY | Varies | URL extraction, search. Custom UA required. |
| DeepSeek API | DEEPSEEK_API_KEY | Budget-limited | Primary API LLM. Cheapest. |
| OpenRouter | OPENROUTER_API_KEY | Budget-limited | Multi-model fallback |
| Anthropic | ANTHROPIC_API_KEY | Budget-limited | Claude models |
| OpenAI | OPENAI_API_KEY | Budget-limited | GPT models, ComputerUse(gpt-5.4) |
| Gemini | GEMINI_API_KEY | Budget-limited | Google models |
| YouTube Data API | YOUTUBE_API_KEY | 10000 units/day | Video metadata only |
| Bluesky | BLUESKY_APP_PASSWORD | Platform limits | Social posting |
| LightPanda | BRAVO:9222 | Local | Fast headless browser |
| Stagehand | BRAVO local | Local | AI-driven browser |
| Playwright | BRAVO:9223 | Local | Full browser automation |
| ComputerUse | gpt-5.4 API | Budget-limited | Visual browser AI (Layer 4, expensive) |

## Budget Constraints (2026-04 現在)

- **Daily API budget:** ¥120 (DAILY_API_BUDGET_JPY in .env)
- **Monthly API budget:** ¥2,000 (MONTHLY_BUDGET_JPY)
- **Monthly info budget:** ¥15,000 (MONTHLY_INFO_BUDGET_JPY)
- **Alert at 80%**, Emergency Kill at 90% of daily budget
- **Cost priority (low→high):** ローカル(BRAVO/CHARLIE/DELTA、無料) → OpenRouter Qwen3.6 Plus (無料) → Nemotron-3-Nano-30B (OpenRouter無料) → Gemini Flash → DeepSeek V3.2 → Claude Haiku → Claude Sonnet/Opus → GPT-5.4
- **OpenRouter Qwen 3.6 Plus 日次上限:** 180 req/day、超過時はGemini Flashへ自動fallback
- **現状の月次コスト:** ¥518 / ¥2,000 (26% 使用、2026-04-06 時点)

## Communication Channels

### NATS JetStream Subjects
| Stream | Subjects | Retention | Purpose |
|--------|----------|-----------|---------|
| TASKS | `task.>` | 7 days | Task dispatch, status, results |
| AGENTS | `agent.>` | 1 day | Inter-agent messages, heartbeats |
| PROPOSALS | `proposal.>`, `approval.>` | 30 days | Proposals, approval flow |
| MONITOR | `monitor.>`, `log.>` | 3 days | Health, metrics, alerts |
| BROWSER | `browser.>`, `computer.>` | 7 days | Browser automation commands |
| INTEL | `intel.>` | 30 days | Info collection pipeline |

### Discord
- Webhook: DISCORD_WEBHOOK_URL (notifications, approvals, alerts)
- Bot channels: Each agent sends fallback notifications on failure

### HTTP Fallback
- FastAPI: localhost:8000 (when NATS unavailable)
- Direct node HTTP only as fallback (CLAUDE.md rule 19)
