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
- LLM routing: choose_best_model_v6() — gpt-4o-mini for SNS+articles, local for light tasks
- SNS + articles: gpt-4o-mini via OpenRouter (¥136/month). Fallback: qwen3-235b → Gemini Flash
- 4 account-specific prompts: shimahara X (humor 40%/honest 95%) / syutain X (75%/90% + memes) / Bluesky (150 char, Build in Public) / Threads (empathy, no money talk)
- Timezone: all scheduled_at must be JST-aware (timezone(timedelta(hours=9)))
- Destructive ACTIONs: never via LLM free-text, only regex direct route or ACTION tag

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
- **戻せ**: 変更は小さく。100行以内。問題があれば即リバート
- **記録しろ**: 何を変えたか、なぜ変えたかをevent_logに記録
