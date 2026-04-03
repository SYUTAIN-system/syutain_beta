# AGENTS.md - System Capability Map
> Auto-referenced by OS Kernel during perceive phase.
> Last manual update: 2026-03-28

## Nodes

### ALPHA (orchestrator)
- **IP:** (Tailscale VPN / local)
- **HW:** Mac mini M4 Pro 16GB
- **OS:** macOS / launchd
- **LLM:** MLX qwen3.5-9b (on-demand, max 6.6GB RAM). Load ONLY when BRAVO+CHARLIE both busy.
- **Agents:** os_kernel, approval_manager, proposal_engine, web_ui_server, chat_agent
- **Services:** PostgreSQL, NATS server, FastAPI(:8000), Next.js(:3000), Caddy(:8443)
- **CAN:** Orchestrate goals, approve/reject, serve UI, run scheduler, manage DB
- **CANNOT:** Run heavy inference continuously. No dedicated GPU. bash 3.2 (no `declare -A`).

### BRAVO (executor)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$BRAVO_IP
- **HW:** Ryzen + RTX 5070 12GB
- **OS:** Ubuntu / systemd
- **LLM:** Ollama always-on. Models: qwen3.5:9b, nemotron-jp, nemotron-mini
- **Agents:** computer_use_agent, content_worker, browser_agent
- **Browser:** 4-layer (LightPanda:9222 → Stagehand → Chromium:9223 → ComputerUse/gpt-5.4)
- **CAN:** Execute tasks, browser automation, content generation, heavy LLM inference
- **CANNOT:** Access PostgreSQL directly (via NATS/API only)

### CHARLIE (inference)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$CHARLIE_IP
- **HW:** Ryzen 9 + RTX 3080 10GB
- **OS:** Ubuntu / systemd (dual-boot with Win11)
- **LLM:** Ollama always-on. Models: qwen3.5:9b, nemotron-jp
- **Agents:** inference_worker, batch_processor
- **CAN:** Batch inference, two-stage refinement local drafts
- **CANNOT:** Available when Win11 is booted. Fallback: BRAVO+DELTA. Health errors are common — check before routing.

### DELTA (monitor)
- **IP:** (Tailscale VPN) / ssh $REMOTE_SSH_USER@$DELTA_IP
- **HW:** Xeon E5 + GTX 980Ti 6GB + 48GB RAM
- **OS:** Ubuntu / systemd
- **LLM:** Ollama qwen3.5:4b (GPU-first, CPU fallback via llama-cpp if <8 tok/s)
- **Agents:** monitor_agent, info_collector, health_checker
- **Mutation engine:** Runs here exclusively (encrypted SQLCipher DB)
- **CAN:** Monitor, patrol, info collection, lightweight inference, mutation engine
- **CANNOT:** Heavy inference (4b model only, old GPU). Use for simple tasks only.

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

1. **Inference tasks:** BRAVO (primary) → CHARLIE (secondary) → ALPHA MLX (last resort, on-demand only)
2. **Browser automation:** BRAVO only (4-layer browser stack)
3. **Content generation:** BRAVO → CHARLIE → API fallback (DeepSeek)
4. **Monitoring/patrol:** DELTA
5. **Info collection:** DELTA (SCOUT)
6. **Code review:** CHARLIE (FORGE) → BRAVO fallback
7. **Simple text tasks (summary, classification):** DELTA qwen3.5:4b → BRAVO/CHARLIE if quality insufficient
8. **LLM model selection:** Always via `choose_best_model_v6()`. 2-stage refine: local draft → API polish.

Fallback chain for LLM: local(BRAVO/CHARLIE) → local(DELTA) → local(ALPHA MLX) → DeepSeek API → OpenRouter

## Known Failure Patterns

| Pattern | Symptom | Fix |
|---------|---------|-----|
| CHARLIE health errors | Repeated `node.health [charlie]` in event_log | Check if Win11 is booted. If so, skip CHARLIE routing. |
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

## Budget Constraints

- **Daily API budget:** ¥80 (default, from .env DAILY_BUDGET_JPY)
- **Monthly API budget:** ¥1,500 (MONTHLY_BUDGET_JPY)
- **Monthly info budget:** ¥15,000 (MONTHLY_INFO_BUDGET_JPY)
- **Single call limit:** ¥500 max per API call
- **Alert at 80%**, Emergency Kill at 90% of daily budget
- **Current local ratio:** ~85% (target: maximize local inference)
- **Cost priority:** DeepSeek < Gemini Flash < GPT-5-nano < local (free)

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
