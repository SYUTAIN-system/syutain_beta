# SYUTAINβ TOOLS

## LLM: tools/llm_router.py (choose_best_model_v6、18分岐: Ollama/OpenRouter Qwen3.6 Plus無料/Anthropic Claude/OpenAI/Gemini/DeepSeek)
## 情報収集: tools/info_collector, browser_ops, keyword_generator, platform_buzz_detector (24ソース)
## コンテンツ: brain_alpha/content_pipeline.py (5段階精錬), sns_batch.py (fact_density重視の8軸スコア + ポエム構造防御)
## SNS: tools/social_tools.py (X/Bluesky/Threads), note_publisher.py (Playwright経由)
## 品質: agents/verifier.py (Sprint Contract検証), brain_alpha/note_quality_checker.py (15項目+Section A-E), tools/platform_ng_check.py
## DB: tools/db_pool.py (PostgreSQL 49テーブル + pgvector、SQLite ノードローカル4テーブル)
## 監視: brain_alpha/self_healer.py, tools/discord_notify.py, tools/brain_beta_health_audit.py (毎時)
## 承認: agents/approval_manager.py (4 tier policy)
## 記憶: brain_alpha/memory_manager.py, persona_bridge.py, bots/bot_memory_ingest.py (working_fact)
## 財務: tools/budget_guard.py (日次¥120/月次¥2000), commerce_tools.py
## Brain-β対話: bots/discord_bot.py (on_message直接ルート), bot_intent.py (7カテゴリ分類), capability_manifest.py (自己説明)
## 記事執筆依頼: bots/bot_actions.commission_article + scheduler.process_article_commissions (3分ポーリング) + article_commission_queue テーブル
