"""
SYUTAINβ V25 統合LLMルータ — choose_best_model_v6
設計書 第3章準拠
"""

import os
import json
import time
import asyncio
import logging
import sqlite3
from typing import Optional
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.llm_router")

# ===== 予算統合（設計書 第8章 / CLAUDE.md ルール16）=====
from tools.budget_guard import get_budget_guard
from tools.discord_notify import notify_discord, notify_error

# モデル別コスト概算（1Kトークンあたり、円）
# コストレート: model_registry.py の $/1M を ¥/1K に変換 (×152/1000)
_COST_RATES_JPY_PER_1K = {
    "gpt-5.4":              {"input": 0.375,  "output": 2.250},   # $2.50/$15.00 per 1M
    "gemini-3.1-pro-preview": {"input": 0.300, "output": 1.800},  # $2.00/$12.00 per 1M
    "claude-opus-4-6":      {"input": 0.750,  "output": 3.750},   # $5.00/$25.00 per 1M
    "claude-sonnet-4-6":    {"input": 0.450,  "output": 2.250},   # $3.00/$15.00 per 1M
    "deepseek-v3.2":        {"input": 0.042,  "output": 0.063},   # $0.28/$0.42 per 1M
    "gemini-2.5-pro":       {"input": 0.1875, "output": 1.500},   # $1.25/$10.00 per 1M
    "gpt-5-mini":           {"input": 0.0375, "output": 0.300},   # $0.25/$2.00 per 1M
    "gemini-2.5-flash":     {"input": 0.0225, "output": 0.090},   # $0.15/$0.60 per 1M
    "claude-haiku-4-5":     {"input": 0.150,  "output": 0.750},   # $1.00/$5.00 per 1M
    "gpt-5-nano":           {"input": 0.0075, "output": 0.060},   # $0.05/$0.40 per 1M
    "gemini-2.5-flash-lite": {"input": 0.01125, "output": 0.045}, # $0.075/$0.30 per 1M
    "gpt-4o-mini":          {"input": 0.0225, "output": 0.090},  # $0.15/$0.60 per 1M
    "qwen3.6-plus":         {"input": 0.0,    "output": 0.0},    # OpenRouter無料
    "nemotron-3-nano-30b":  {"input": 0.0,    "output": 0.0},    # OpenRouter無料
    "_default":             {"input": 0.15,   "output": 0.15},
}

# ===== OpenRouter 無料モデル設定 =====
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# 2026-04-08: Qwen 3.6 Plus:free 廃止。代替モデルチェーン（順にフォールバック）
# Qwen3 Next 80B > Nemotron 3 Super 120B > Step 3.5 Flash > Gemma 4 31B
OPENROUTER_CONTENT_MODELS = [
    "google/gemma-4-31b-it:free",                   # Gemma 4 31B: 最速1.8s、日本語良好
    "nvidia/nemotron-3-super-120b-a12b:free",       # Nemotron Super: 大型5.6s
    "qwen/qwen3-next-80b-a3b-instruct:free",       # Qwen3 Next: 429出やすいが日本語強い
    "stepfun/step-3.5-flash:free",                  # Step Flash: フォールバック
]
OPENROUTER_QWEN36_MODEL = OPENROUTER_CONTENT_MODELS[0]  # デフォルト
# Nemotron-3 Nano 30B: chat/chat_light用（184 tok/s、高速）
OPENROUTER_NEMOTRON30B_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
_openrouter_daily_count = 0
_openrouter_daily_date = ""
# 2026-04-07 更新: $10 credit 購入済みのため上限 1,000/日。安全マージン 80% で 800。
# 旧値 180 は「上限200」の古い情報に基づいていた。
# リセット: UTC 00:00 (JST 09:00)。分あたり制限: 20 req/min (:free モデル共通)。
_OPENROUTER_DAILY_LIMIT = 800


def _estimate_cost_jpy(model: str, prompt: str) -> float:
    """プロンプト長からAPI呼び出しの推定コスト(円)を算出"""
    rates = _COST_RATES_JPY_PER_1K.get(model, _COST_RATES_JPY_PER_1K["_default"])
    # 概算: 1トークン≒3文字(日本語), 出力はinputの0.5倍と仮定
    est_input_tokens = len(prompt) / 3
    est_output_tokens = est_input_tokens * 0.5
    cost = (est_input_tokens / 1000) * rates["input"] + (est_output_tokens / 1000) * rates["output"]
    return round(cost, 4)


def _calc_actual_cost_jpy(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """実際のトークン数からコスト(円)を算出"""
    rates = _COST_RATES_JPY_PER_1K.get(model, _COST_RATES_JPY_PER_1K["_default"])
    cost = (prompt_tokens / 1000) * rates["input"] + (completion_tokens / 1000) * rates["output"]
    return round(cost, 4)


def _openrouter_available() -> bool:
    """OpenRouter Qwen 3.6 Plusが利用可能か（APIキー設定済み & 日次制限内）"""
    global _openrouter_daily_count, _openrouter_daily_date
    if not OPENROUTER_API_KEY:
        return False
    from datetime import date as _date
    today = _date.today().isoformat()
    if _openrouter_daily_date != today:
        _openrouter_daily_count = 0
        _openrouter_daily_date = today
    return _openrouter_daily_count < _OPENROUTER_DAILY_LIMIT


def _openrouter_record_use():
    """OpenRouter使用をカウント"""
    global _openrouter_daily_count
    _openrouter_daily_count += 1


# ===== ノード負荷状態（NATS経由で更新される）=====
_node_load = {
    "bravo": {"busy": False, "last_seen": 0, "call_count": 0},
    "charlie": {"busy": False, "last_seen": 0, "call_count": 0},
    "alpha": {"busy": False, "last_seen": 0, "call_count": 0},
}
_round_robin_idx = 0  # BRAVO/CHARLIEのラウンドロビン用

# 学習ループ: モデル品質フィードバックキャッシュ（非同期DB→同期choose_best_model_v6の橋渡し）
_model_quality_cache: dict = {}  # {task_type: {"model": "...", "avg_quality": 0.X, "updated": timestamp}}
_model_quality_cache_ttl = 3600  # 1時間キャッシュ


async def refresh_model_quality_cache():
    """model_quality_logから学習結果をキャッシュに読み込む（scheduler.pyから定期呼出）"""
    global _model_quality_cache
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch("""
                SELECT task_type, model_used, tier,
                    AVG(quality_score) as avg_quality, COUNT(*) as cnt
                FROM model_quality_log
                WHERE created_at >= NOW() - INTERVAL '14 days' AND quality_score > 0
                GROUP BY task_type, model_used, tier
                HAVING COUNT(*) >= 3
                ORDER BY task_type, avg_quality DESC
            """)
            cache = {}
            avoid = {}  # 品質が低いモデルを回避リストに
            for r in rows:
                tt = r["task_type"]
                avg_q = float(r["avg_quality"])
                # 品質0.4未満 & サンプル5件以上 → 回避リスト
                if avg_q < 0.4 and int(r["cnt"]) >= 5:
                    if tt not in avoid:
                        avoid[tt] = []
                    avoid[tt].append(r["model_used"])
                # 各task_typeで最高品質のモデルを記録
                if tt not in cache:
                    cache[tt] = {
                        "model": r["model_used"], "tier": r["tier"],
                        "avg_quality": avg_q,
                        "sample_count": int(r["cnt"]),
                        "updated": time.time(),
                        "avoid_models": avoid.get(tt, []),
                    }
                elif tt in avoid:
                    cache[tt]["avoid_models"] = avoid[tt]
            _model_quality_cache = cache
            logger.info(f"モデル品質キャッシュ更新: {len(cache)}タスクタイプ, {sum(len(v) for v in avoid.values())}モデル回避")
    except Exception as e:
        logger.warning(f"モデル品質キャッシュ更新失敗: {e}")


def update_node_load(node: str, busy: bool):
    """ノード負荷状態を更新（NATSハートビートから呼ばれる）"""
    if node in _node_load:
        _node_load[node]["busy"] = busy
        _node_load[node]["last_seen"] = time.time()


def _pick_local_node(prefer_delta: bool = False) -> str:
    """ローカルノードを選択。prefer_delta=Trueで軽量タスクをDELTAに振る"""
    global _round_robin_idx
    if prefer_delta:
        if not _node_load.get("delta", {}).get("busy"):
            _node_load.setdefault("delta", {})["call_count"] = _node_load.get("delta", {}).get("call_count", 0) + 1
            return "delta"
    # BRAVO/CHARLIEラウンドロビン
    candidates = ["bravo", "charlie"]
    for i in range(len(candidates)):
        idx = (_round_robin_idx + i) % len(candidates)
        node = candidates[idx]
        if not _node_load[node]["busy"]:
            _round_robin_idx = (idx + 1) % len(candidates)
            _node_load[node]["call_count"] = _node_load[node].get("call_count", 0) + 1
            return node
    # 全ビジー: DELTA → ALPHA
    if not _node_load.get("delta", {}).get("busy"):
        return "delta"
    return "alpha"


# ===== Nemotron-Nano-8B-v2-Japanese 設定 =====
NEMOTRON_JP_ENABLED = os.getenv("NEMOTRON_JP_ENABLED", "false").lower() == "true"
NEMOTRON_JP_NODES = [n.strip() for n in os.getenv("NEMOTRON_JP_NODES", "bravo,charlie").split(",")]
NEMOTRON_JP_MODEL = "nemotron-jp"  # ollama内のモデル名

# Nemotron優先タスク（日本語コンテンツ生成/チャット/Tool Calling）
# 2026-04-06 方針変更: content/sns_draft/drafting/note_article/note_draft/intel_summary は
# OpenRouter 無料モデル (Qwen 3.6 Plus) に移行。Nemotron-JP はローカル品質で十分なもののみ。
_NEMOTRON_PRIORITY_TASKS = {
    "persona_extraction",
    "quality_scoring", "tool_calling",
}

# Nemotron + /think 推奨タスク（品質検証・推論）
# strategy/proposal_generation/analysisは9Bの/thinkでは重すぎる
# analysisは_NEMOTRON_PRIORITY_TASKS経由で/thinkなしNemotronへ
_NEMOTRON_THINK_TASKS = {
    "quality_verification", "content_refinement",
}


def _pick_nemotron_node() -> Optional[str]:
    """Nemotronが利用可能なノードを返す。なければNone"""
    if not NEMOTRON_JP_ENABLED:
        return None
    for node in NEMOTRON_JP_NODES:
        if not _node_load.get(node, {}).get("busy"):
            return node
    return None


# ===== タスクタイプ→ノード/モデルのマッピング =====
# 実データに基づく品質実績でローカル/APIを振り分け

# DELTAで処理する軽量タスク（qwen3.5:4b、コスト¥0）
# → 推論力不要。分類・タグ付け・圧縮など
_DELTA_TASKS = {
    "log_formatting", "tagging", "classification", "compression",
    "health_check", "monitoring", "keyword_extraction",
    "sentiment_analysis", "translation_draft", "duplicate_check",
}

# BRAVO/CHARLIEで十分なタスク（qwen3.5-9b、コスト¥0）
# → 実データでAPI同等以上の品質が出ているタスクのみ
# 2026-04-06 方針転換: 「ローカル LLM のみでの動作」から「無料クラウドモデル優先」に変更。
# ローカル LLM (Qwen3.5-9B) は記事生成で 6000 字に届かない品質問題が判明（9 スロット中 6 失敗）。
# content/analysis/research/sns_draft は _QWEN36_TASKS に移動して OpenRouter 無料モデル優先に。
# ローカルは quality="low" + DELTA 軽量タスク + 以下の本当にローカルで十分なもののみ。
_LOCAL_OK_TASKS = {
    "variation_gen",      # 多様性生成、品質より量
    "quality_scoring",    # スコアリング用（低品質でOK）
    "persona_extraction", # キーワード抽出系
    "coding",             # ローカル0.50 = API 0.50（同等）
    "data_extraction",    # 構造化抽出、ローカルで十分
    "batch_process",      # 大量処理、コスト重視
    "bulk_draft",         # 大量ドラフト
    # sns_draft はOpenRouterのGemma 4 31B(無料)で生成（ローカル9Bではプロンプト消化不足）
}

# APIの方が品質が高いタスク → Gemini Flash（無料枠）優先
# V30: content/analysis/researchをローカルに移動。品質が重要なものだけAPI
_API_PREFERRED_TASKS = {
    "proposal",           # 3層提案、構造化思考が必要
    "note_article",       # 長文記事、品質重要
    "product_desc",       # 商品説明、購買に直結
    "booth_description",  # Booth商品説明
    "note_draft",         # note下書き
}

# Claude Haiku推奨タスク（¥0.003/回、高い推論力が必要）
_HAIKU_TASKS = {
    "quality_verification", "content_refinement",
    "proposal_generation", "persona_deep_analysis",
    "strategy", "competitive_analysis",
    "chat",                 # Discord Bot対話（事実回答・状態確認・相談）
}

# DeepSeek V3.2（最終品質+コスパ）
_DEEPSEEK_FINAL_TASKS = {
    "content_final", "note_article_final",
    "booth_description_final", "complex_analysis",
    "chat_light",           # Discord Bot軽度対話（挨拶・雑談・短文）
}


def choose_best_model_v6(
    task_type: str,
    quality: str = "medium",
    budget_sensitive: bool = True,
    needs_japanese: bool = False,
    final_publish: bool = False,
    local_available: bool = True,
    context_length_needed: int = 4000,
    is_agentic: bool = False,
    needs_multimodal: bool = False,
    needs_computer_use: bool = False,
    needs_tool_search: bool = False,
    intelligence_required: int = 0,
) -> dict:
    result = _choose_best_model_v6_impl(
        task_type=task_type, quality=quality, budget_sensitive=budget_sensitive,
        needs_japanese=needs_japanese, final_publish=final_publish,
        local_available=local_available, context_length_needed=context_length_needed,
        is_agentic=is_agentic, needs_multimodal=needs_multimodal,
        needs_computer_use=needs_computer_use, needs_tool_search=needs_tool_search,
        intelligence_required=intelligence_required,
    )
    result["task_type"] = task_type  # セマンティックキャッシュ用
    return result


def _choose_best_model_v6_impl(
    task_type: str,
    quality: str = "medium",
    budget_sensitive: bool = True,
    needs_japanese: bool = False,
    final_publish: bool = False,
    local_available: bool = True,
    context_length_needed: int = 4000,
    is_agentic: bool = False,
    needs_multimodal: bool = False,
    needs_computer_use: bool = False,
    needs_tool_search: bool = False,
    intelligence_required: int = 0,
) -> dict:
    """
    V25 モデル選択ロジック — 品質実データに基づく最適選定

    原則: モデルは手段。タスクに応じて最適なモデルを選ぶ。
    ローカルLLMの推論力を過大評価しない。

    判定順:
    1. Tier S 強制ルート（Computer Use/高知能/最終公開）
    2. quality="low" → ローカル強制（分類・タグ付け等）
    3. DELTA軽量タスク → ローカル
    4. ローカルで十分なタスク（実データで品質が出ているもの）→ ローカル
    5. APIの方が品質が高いタスク → Gemini Flash（無料枠）優先
    6. 高い推論力が必要 → Claude Haiku / DeepSeek
    7. デフォルト → Gemini Flash
    """
    anthropic_available = os.getenv("ANTHROPIC_CREDITS_AVAILABLE", "false").lower() == "true"

    # === Tier S 強制ルート ===

    if needs_computer_use:
        return {"provider": "openai", "model": "gpt-5.4", "tier": "S", "via": "direct",
                "note": "Computer Use必須"}

    if needs_tool_search:
        return {"provider": "openai", "model": "gpt-5.4", "tier": "S", "via": "direct",
                "note": "Tool Search必須"}

    if intelligence_required >= 50:
        return {"provider": "google", "model": "gemini-2.5-pro", "tier": "A", "via": "openrouter",
                "note": f"知能指数{intelligence_required}≥50"}

    # === final_publish時のTier S/Aルート（ただしQwen3.6対象は先に評価）===
    # 2026-04-05: Gemini 2.5 Pro(有料)より無料Qwen 3.6 Plusを優先するため、
    # Qwen3.6対象タスクならここをスキップして後段のOpenRouter無料ルートへ
    _QWEN36_TASKS_EARLY = {
        "proposal", "proposal_generation", "strategy", "competitive_analysis",
        "content_final", "note_article_final", "booth_description_final",
        "complex_analysis", "persona_deep_analysis",
        "note_article", "product_desc", "booth_description", "note_draft",
    }
    if final_publish and quality in ["high", "premium"] and task_type not in _QWEN36_TASKS_EARLY:
        if anthropic_available and task_type in ["strategy", "pricing", "btob"]:
            return {"provider": "anthropic", "model": "claude-sonnet-4-6", "tier": "S", "via": "direct",
                    "note": "最終公開+戦略タスク"}
        return {"provider": "google", "model": "gemini-2.5-pro", "tier": "A", "via": "openrouter",
                "note": "最終公開品質"}

    # === quality="highest_local" → BRAVO 27Bモデル（高品質ローカル推論） ===
    # 用途: 品質検証、最終チェック、重要記事の推敲、ファクトチェック
    # 注意: 5 tok/s（9bの18倍遅い）。短いタスク（<200トークン出力）に限定推奨

    if quality == "highest_local" and local_available:
        return {"provider": "local", "model": "qwen3.5-27b", "tier": "L+", "node": "bravo",
                "note": "highest_local→BRAVO 27B（高品質ローカル、低速）"}

    # === quality="low" → 強制ローカル ===

    if quality == "low" and local_available:
        if task_type in _DELTA_TASKS:
            node = _pick_local_node(prefer_delta=True)
        else:
            node = _pick_local_node(prefer_delta=False)
        model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
        return {"provider": "local", "model": model, "tier": "L", "node": node,
                "note": f"quality=low→ローカル強制({node})"}

    # === avoid_models: 品質実績で回避すべきモデル ===
    avoid_list = _model_quality_cache.get(task_type, {}).get("avoid_models", [])

    # === Nemotron-JP 優先ルート（日本語コンテンツ/チャット） ===

    if NEMOTRON_JP_ENABLED and local_available:
        if NEMOTRON_JP_MODEL not in avoid_list:
            nemotron_node = _pick_nemotron_node()
            if nemotron_node:
                if task_type in _NEMOTRON_PRIORITY_TASKS:
                    return {"provider": "local", "model": NEMOTRON_JP_MODEL, "tier": "L",
                            "node": nemotron_node, "note": f"Nemotron JP優先({task_type})→{nemotron_node}"}
                if task_type in _NEMOTRON_THINK_TASKS and quality in ("medium", "high"):
                    return {"provider": "local", "model": NEMOTRON_JP_MODEL, "tier": "L",
                            "node": nemotron_node, "think": True,
                            "note": f"Nemotron JP /think({task_type})→{nemotron_node}"}

    # === 学習ループキャッシュ ===

    if local_available and budget_sensitive and quality == "medium":
        cached = _model_quality_cache.get(task_type)
        if cached and cached.get("avg_quality", 0) >= 0.6:
            cached_model = cached["model"]
            cached_tier = cached.get("tier", "unknown")
            # ローカルモデルの場合のみ学習ループで推奨
            if cached_tier in ("L", "unknown") and cached_model in ("qwen3.5-9b", "qwen3.5-4b", "nemotron-jp"):
                if avoid_list and cached_model in avoid_list:
                    logger.warning(f"モデル {cached_model} はavoid_modelsリストに該当 (task_type={task_type})、学習ループ推奨スキップ")
                else:
                    node = _pick_local_node()
                    if cached_model == "qwen3.5-4b":
                        node = _pick_local_node(prefer_delta=True)
                    return {"provider": "local", "model": cached_model, "tier": "L", "node": node,
                            "note": f"学習ループ推奨(品質{cached['avg_quality']:.2f})"}

    # === Tier L: ローカルで十分なタスク ===

    # DELTA軽量タスク（推論力不要）
    if local_available and task_type in _DELTA_TASKS:
        node = _pick_local_node(prefer_delta=True)
        model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
        if model not in avoid_list:
            return {"provider": "local", "model": model, "tier": "L", "node": node,
                    "note": f"軽量タスク→{node}"}

    # 実データでローカル品質が十分なタスク
    if local_available and task_type in _LOCAL_OK_TASKS:
        node = _pick_local_node()
        model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
        if model not in avoid_list:
            return {"provider": "local", "model": model, "tier": "L", "node": node,
                    "note": f"ローカル十分({task_type})→{node}"}

    # === Tier A: APIの方が品質が高いタスク ===

    # OpenRouter Qwen 3.6 Plus（無料、1Mコンテキスト、高品質だが低速）
    # 「考える力」が必要で速度が許容されるタスクのみ。chat等の速度重要タスクは対象外
    _QWEN36_TASKS = {
        "proposal", "proposal_generation", "strategy", "competitive_analysis",  # 深い思考が必要
        "content_final", "note_article_final", "booth_description_final",       # 最終品質
        "complex_analysis", "persona_deep_analysis",                            # 深い分析
        "note_article", "product_desc", "booth_description", "note_draft",      # コンテンツ生成
        # 2026-04-06 追加: ローカル LLM から無料クラウドに移行したタスク
        "content", "analysis", "research",                                      # 記事生成/分析/リサーチ
        "sns_draft",                                                               # SNS投稿（Gemma4 31B無料で生成）
        "drafting",                                                                # ドラフト
        "intel_summary",                                                        # 情報要約
    }
    if task_type in _QWEN36_TASKS and _openrouter_available():
        return {"provider": "openrouter", "model": "qwen3.6-plus", "tier": "A", "via": "openrouter",
                "openrouter_model_id": OPENROUTER_QWEN36_MODEL,
                "note": f"Qwen 3.6 Plus(無料)→{task_type}"}

    # Gemini Flash フォールバック（API優先タスク）
    if task_type in _API_PREFERRED_TASKS:
        return {"provider": "google", "model": "gemini-2.5-flash", "tier": "A", "via": "direct",
                "note": f"API優先({task_type})→Gemini Flash"}

    # chat_light のみ Nemotron（挨拶・短文）。chat はHaikuで品質維持
    if task_type == "chat_light" and _openrouter_available():
        return {"provider": "openrouter", "model": "nemotron-3-nano-30b", "tier": "A", "via": "openrouter",
                "openrouter_model_id": OPENROUTER_NEMOTRON30B_MODEL,
                "note": f"Nemotron-3-Nano-30B(無料,184tok/s)→{task_type}"}

    # Claude Haiku推奨タスク（高い推論力が必要、chat/chat_light以外）
    if task_type in _HAIKU_TASKS:
        if anthropic_available:
            return {"provider": "anthropic", "model": "claude-haiku-4-5", "tier": "A", "via": "direct",
                    "note": f"高推論力({task_type})→Haiku"}
        return {"provider": "google", "model": "gemini-2.5-flash", "tier": "A", "via": "direct",
                "note": f"Haiku不可→Gemini Flash"}

    # DeepSeek最終品質（chat_light以外）
    if task_type in _DEEPSEEK_FINAL_TASKS:
        return {"provider": "deepseek", "model": "deepseek-v3.2", "tier": "A", "via": "direct",
                "note": f"最終品質({task_type})→DeepSeek"}

    # === quality="high" → API ===

    if quality == "high":
        if anthropic_available:
            return {"provider": "anthropic", "model": "claude-haiku-4-5", "tier": "A", "via": "direct",
                    "note": "quality=high→Haiku"}
        return {"provider": "google", "model": "gemini-2.5-flash", "tier": "A", "via": "direct",
                "note": "quality=high→Gemini Flash"}

    # === デフォルト ===
    # 2026-04-06 方針変更: ローカルより先に OpenRouter 無料モデルを試す

    # 未分類でも OpenRouter 無料が使えるならそちら優先
    if _openrouter_available():
        return {"provider": "openrouter", "model": "nemotron-3-nano-30b", "tier": "A", "via": "openrouter",
                "openrouter_model_id": OPENROUTER_NEMOTRON30B_MODEL,
                "note": f"未分類→Nemotron-3-Nano-30B(無料)"}

    # OpenRouter 上限超え → ローカルフォールバック
    if local_available:
        node = _pick_local_node()
        model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
        if avoid_list and model in avoid_list:
            logger.warning(f"モデル {model} はavoid_modelsリストに該当 (task_type={task_type})、フォールバック")
            return {"model": "gemini-2.5-flash", "tier": "A", "provider": "google",
                    "via": "direct", "note": f"avoid_modelsフォールバック({task_type})"}
        return {"provider": "local", "model": model, "tier": "L", "node": node,
                "note": f"OpenRouter上限超→ローカル({node})"}

    # 全部不可 → Gemini Flash
    return {"provider": "google", "model": "gemini-2.5-flash", "tier": "A", "via": "direct",
            "note": "全不可→Gemini Flash"}


async def call_llm(
    prompt: str,
    system_prompt: str = "",
    model_selection: Optional[dict] = None,
    goal_id: str = "",
    **kwargs,
) -> dict:
    """
    統合LLM呼び出し — プロバイダに応じて適切なAPIを呼ぶ
    model_selectionはchoose_best_model_v6()の戻り値

    セマンティックキャッシュ: task_typeがキャッシュ対象の場合、
    類似プロンプト(cosine>0.92)のキャッシュがあればLLM呼び出しをスキップ。
    """
    if model_selection is None:
        model_selection = choose_best_model_v6(task_type="drafting")

    # ===== セマンティックキャッシュ =====
    task_type = kwargs.pop("task_type", "") or (model_selection.get("task_type") if model_selection else "")
    use_cache = kwargs.pop("use_cache", True)  # 明示的にFalseでキャッシュ無効化可能
    if use_cache and task_type:
        try:
            from tools.semantic_cache import is_cacheable, get_semantic_cache
            if is_cacheable(task_type):
                cache = get_semantic_cache()
                return await cache.get_or_call(
                    prompt, system_prompt, model_selection,
                    _call_llm_internal, goal_id=goal_id,
                    task_type=task_type, **kwargs,
                )
        except Exception as e:
            logger.warning(f"セマンティックキャッシュ初期化失敗（直接呼び出し）: {e}")

    return await _call_llm_internal(
        prompt, system_prompt, model_selection, goal_id=goal_id, **kwargs,
    )


async def _call_llm_internal(
    prompt: str,
    system_prompt: str = "",
    model_selection: Optional[dict] = None,
    goal_id: str = "",
    **kwargs,
) -> dict:
    """実際のLLM呼び出し処理（セマンティックキャッシュから呼ばれる内部関数）"""
    if model_selection is None:
        model_selection = choose_best_model_v6(task_type="drafting")

    provider = model_selection["provider"]
    model = model_selection["model"]
    via = model_selection.get("via", "direct")
    node = model_selection.get("node")
    tier = model_selection.get("tier", "unknown")

    # ===== 予算チェック（API呼び出し前）=====
    # ローカルLLMはコスト0なのでチェック不要
    if provider != "local":
        try:
            budget_guard = get_budget_guard()
            estimated_cost = _estimate_cost_jpy(model, prompt)
            budget_check = await budget_guard.check_before_call(estimated_cost)

            if not budget_check["allowed"]:
                # 予算90%到達 → ローカルLLMフォールバック
                logger.warning(f"予算超過によりローカルLLMへフォールバック: {budget_check['reason']}")
                remaining = budget_check.get("remaining_jpy", "?")
                daily_limit = budget_check.get("daily_limit_jpy", "?")
                _task_type_hint = (model_selection or {}).get("task_type", "unknown")
                _quality_hint = (model_selection or {}).get("quality", "unknown")
                asyncio.create_task(notify_error(
                    "budget_90pct_fallback",
                    f"日次API予算90%到達（残¥{remaining}/日次上限¥{daily_limit}）。"
                    f"ローカルLLMのみで運転継続。元のリクエスト: {_task_type_hint}/{_quality_hint}",
                    severity="error",
                ))
                provider = "local"
                node = _pick_local_node()
                model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
                tier = "L"
        except Exception as e:
            # 予算チェック失敗でも本体処理は続行（CLAUDE.md ルール7）
            log_usage("budget_check", model, 0, 0, False, str(e))
            logger.error(f"予算チェック失敗（処理続行）: {e}")

    start_time = time.time()

    try:
        max_tokens = kwargs.get("max_tokens", 4096)
        if provider == "local":
            use_think = model_selection.get("think", False) if model_selection else False
            result = await _call_local_llm(
                prompt, system_prompt, model, node, think=use_think,
                temperature=kwargs.get("temperature"),
                repeat_penalty=kwargs.get("repeat_penalty"),
                seed=kwargs.get("seed"),
            )
        elif provider == "openai" and via == "direct":
            result = await _call_openai(prompt, system_prompt, model)
        elif provider == "anthropic":
            result = await _call_anthropic(prompt, system_prompt, model, max_tokens=max_tokens)
        elif provider == "deepseek":
            result = await _call_deepseek(prompt, system_prompt, model)
        elif provider == "google":
            result = await _call_google(prompt, system_prompt, model)
        elif provider == "openrouter" or via == "openrouter":
            # openrouter_model_idがあればそれを使う（例: qwen/qwen3.6-plus:free）
            or_model = model_selection.get("openrouter_model_id", model) if model_selection else model
            try:
                result = await _call_openrouter(prompt, system_prompt, or_model, max_tokens=max_tokens)
            except Exception as or_err:
                # OpenRouter :free 失敗 → 3段フォールバックチェーン
                # 2026-04-07: Qwen 3.6 Plus :free の upstream 429 対策
                err_str = str(or_err).lower()
                is_rate_limit = "429" in err_str or "rate" in err_str

                if is_rate_limit:
                    logger.warning(f"OpenRouter 429 ({or_model}) → DeepSeek V3.2 フォールバック")
                    try:
                        result = await _call_deepseek(prompt, system_prompt, "deepseek-v3.2")
                        model = "deepseek-v3.2"
                        provider = "deepseek"
                        tier = "A"
                    except Exception as ds_err:
                        logger.warning(f"DeepSeek も失敗: {ds_err} → Gemini Flash フォールバック")
                        result = await _call_google(prompt, system_prompt, "gemini-2.5-flash")
                        model = "gemini-2.5-flash"
                        provider = "google"
                        tier = "A"
                else:
                    # 429 以外のエラー → Gemini Flash
                    logger.warning(f"OpenRouter失敗({or_model}): {or_err} → Gemini Flashフォールバック")
                    result = await _call_google(prompt, system_prompt, "gemini-2.5-flash")
                    model = "gemini-2.5-flash"
                    provider = "google"
                    tier = "A"
        else:
            result = await _call_openrouter(prompt, system_prompt, model)

        # イベントログ記録（非同期、失敗してもアプリは止めない）
        try:
            from tools.event_logger import log_event
            actual_node = result.get("node", node or "api")
            # 意思決定トレース: なぜこのモデルが選ばれたか
            selection_reason = model_selection.get("note", "") if model_selection else ""
            await log_event("llm.call", "llm", {
                "model": model, "provider": provider, "tier": tier,
                "node": actual_node,
                "latency_ms": (time.time() - start_time) * 1000,
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
                "selection_reason": selection_reason,
            }, source_node=actual_node if provider == "local" else "alpha")
        except Exception:
            pass

        # agent_reasoning_trace: モデル選定根拠
        try:
            from tools.db_pool import get_connection
            async with get_connection() as _trace_conn:
                await _trace_conn.execute(
                    """INSERT INTO agent_reasoning_trace
                       (agent_name, action, reasoning, confidence, context)
                       VALUES ('LLMRouter', 'model_selected', $1, 1.0, $2)""",
                    model_selection.get("note", f"{model}@{node or provider}"),
                    json.dumps({"model": model, "provider": provider, "tier": tier,
                                "node": node, "task_type": kwargs.get("task_type", ""),
                                "nemotron_enabled": NEMOTRON_JP_ENABLED},
                               ensure_ascii=False),
                )
        except Exception:
            pass

        latency_ms = (time.time() - start_time) * 1000
        result["latency_ms"] = latency_ms
        result["model_used"] = model
        result["tier"] = tier

        # ローカルDBにログ記録
        _log_llm_call(model, tier, latency_ms, True)

        # ===== 予算記録 =====
        if provider == "local":
            # ローカルLLMもllm_cost_logに記録（cost=0）
            try:
                budget_guard = get_budget_guard()
                await budget_guard.record_spend(
                    amount_jpy=0.0, model=model, tier="L",
                    goal_id=goal_id,
                )
                result["cost_jpy"] = 0.0
            except Exception:
                pass

        if provider != "local":
            try:
                actual_cost = _calc_actual_cost_jpy(
                    model,
                    result.get("prompt_tokens", 0),
                    result.get("completion_tokens", 0),
                )
                budget_guard = get_budget_guard()
                spend_result = await budget_guard.record_spend(
                    amount_jpy=actual_cost,
                    model=model,
                    tier=tier,
                    goal_id=goal_id,
                )
                result["cost_jpy"] = actual_cost
                result["budget_alert"] = spend_result.get("alert_level", "ok")
                log_usage("llm_call", model, result.get("prompt_tokens", 0),
                          result.get("completion_tokens", 0), True)

                # 警告レベルに応じてDiscord通知（dedupはnotify_error内で処理）
                if spend_result.get("alert_level") in ("stop", "warn_budget_exceeded"):
                    # 予算超過通知は1日1回のみ（連続通知防止）
                    from datetime import date as _date
                    _budget_alert_key = f"budget_exceeded_{_date.today().isoformat()}"
                    if not hasattr(choose_best_model_v6, '_budget_alerted'):
                        choose_best_model_v6._budget_alerted = set()
                    if _budget_alert_key not in choose_best_model_v6._budget_alerted:
                        choose_best_model_v6._budget_alerted.add(_budget_alert_key)
                        asyncio.create_task(notify_error(
                            "budget_90pct_warn",
                            f"API予算90%超過（処理は継続中）: {spend_result.get('message', '')}",
                            severity="warning",
                        ))
            except Exception as e:
                log_usage("budget_record", model, 0, 0, False, str(e))
                logger.error(f"予算記録失敗（処理続行）: {e}")

        return result
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        error_msg = str(e) or f"{type(e).__name__}(no message)"
        _log_llm_call(model, tier, latency_ms, False, error_msg)
        log_usage("llm_call", model, 0, 0, False, error_msg)
        logger.error(f"LLM呼び出し失敗 ({model}@{node or provider}): {error_msg}")

        # イベントログ: LLMエラー
        try:
            from tools.event_logger import log_event
            await log_event("llm.error", "llm", {
                "model": model, "provider": provider, "node": node,
                "error": error_msg[:200], "exception_type": type(e).__name__,
            }, severity="error", source_node=node if provider == "local" else "alpha")
        except Exception:
            pass

        # CLAUDE.md ルール17: API失敗時はローカルLLMにフォールバック
        if provider != "local":
            try:
                fallback_node = _pick_local_node()
                fallback_model = "qwen3.5-4b" if fallback_node == "delta" else "qwen3.5-9b"
                logger.info(f"ローカルLLMフォールバック: {fallback_model}@{fallback_node}")
                # イベントログ: フォールバック
                try:
                    from tools.event_logger import log_event
                    await log_event("llm.fallback", "llm", {
                        "original_model": model, "fallback_model": fallback_model,
                        "fallback_node": fallback_node, "reason": str(e)[:100],
                    }, severity="warning", source_node=fallback_node)
                except Exception:
                    pass
                result = await _call_local_llm(prompt, system_prompt, fallback_model, fallback_node)
                result["fallback"] = True
                result["original_error"] = str(e)
                return result
            except Exception as fallback_err:
                logger.error(f"ローカルLLMフォールバックも失敗: {fallback_err}")

        return {"text": "", "error": str(e), "model_used": model}


async def _call_local_llm(prompt: str, system_prompt: str, model: str, node: str, think: bool = False,
                          temperature: float = None, repeat_penalty: float = None, seed: int = None) -> dict:
    """Ollama経由でローカルLLM呼び出し。think=TrueでNemotron推論モード有効"""
    url_map = {
        "bravo": os.getenv("BRAVO_OLLAMA_URL", "http://127.0.0.1:11434"),
        "charlie": os.getenv("CHARLIE_OLLAMA_URL", "http://127.0.0.1:11434"),
        "delta": os.getenv("DELTA_OLLAMA_URL", "http://127.0.0.1:11434"),
        "alpha": "http://localhost:11434",
    }
    # node="auto"またはurl_mapにない場合はラウンドロビンで自動選択
    if not node or node == "auto" or node not in url_map:
        node = _pick_local_node()
    base_url = url_map.get(node, url_map["bravo"])
    # 特殊モデル名の場合はOllamaタグに変換
    if model == NEMOTRON_JP_MODEL:
        ollama_model = NEMOTRON_JP_MODEL
    elif model == "qwen3.5-27b":
        ollama_model = "qwen3.5:27b"  # Ollamaタグ形式
        node = "bravo"  # 27BはBRAVO固定（他ノードには入らない）
        base_url = url_map.get("bravo", url_map.get("bravo"))
    else:
        ollama_model = os.getenv(f"{node.upper()}_LOCAL_MODEL", model)
    logger.info(f"ローカルLLM呼び出し: node={node}, model={ollama_model}")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # 推論制御: Nemotron JPはthink: true対応（Ollama 0.18.2+）
    # think=Trueの場合、thinkingフィールドに推論トレース、contentに最終回答が分離される
    think_mode = think

    # 27Bは約5 tok/sのため、長文改善タスクで300秒を超えやすい
    # 27Bのみread_timeoutを延長し、他モデルは現状値を維持
    read_timeout = 900.0 if model == "qwen3.5-27b" else 300.0
    timeout_config = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout_config) as client:
        try:
            payload = {
                "model": ollama_model,
                "messages": messages,
                "stream": False,
                "think": think_mode,
            }
            # Ollamaオプション（temperature, repeat_penalty等）
            options = {}
            if temperature is not None:
                options["temperature"] = temperature
            if repeat_penalty is not None:
                options["repeat_penalty"] = repeat_penalty
            if seed is not None:
                options["seed"] = seed
            if options:
                payload["options"] = options

            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})
            text = msg.get("content", "")
            thinking = msg.get("thinking", "")
            # think=true時: thinkingに推論トレース、contentに最終回答
            if not text and thinking:
                text = thinking  # フォールバック: contentが空ならthinkingを使用
            return {
                "text": text,
                "thinking": thinking,
                "node": node,
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # /api/chat が非対応の場合は /api/generate にフォールバック
                full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                resp2 = await client.post(
                    f"{base_url}/api/generate",
                    json={"model": ollama_model, "prompt": full_prompt, "stream": False},
                )
                resp2.raise_for_status()
                data2 = resp2.json()
                return {
                    "text": data2.get("response", ""),
                    "node": node,
                    "prompt_tokens": data2.get("prompt_eval_count", 0),
                    "completion_tokens": data2.get("eval_count", 0),
                }
            raise


async def _call_openai(prompt: str, system_prompt: str, model: str) -> dict:
    """OpenAI API直接呼び出し"""
    import openai

    client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    resp = await client.chat.completions.create(model=model, messages=messages)
    return {
        "text": resp.choices[0].message.content or "",
        "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
    }


async def _call_anthropic(prompt: str, system_prompt: str, model: str, max_tokens: int = 4096) -> dict:
    """Anthropic API直接呼び出し"""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text if resp.content else ""
    return {
        "text": text,
        "prompt_tokens": resp.usage.input_tokens,
        "completion_tokens": resp.usage.output_tokens,
    }


async def _call_deepseek(prompt: str, system_prompt: str, model: str) -> dict:
    """DeepSeek API直接呼び出し"""
    import openai

    client = openai.AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
    )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # DeepSeek APIのモデル名: deepseek-v3.2等 → deepseek-chat に変換
    api_model = "deepseek-chat"
    if "reasoner" in model:
        api_model = "deepseek-reasoner"
    resp = await client.chat.completions.create(model=api_model, messages=messages)
    return {
        "text": resp.choices[0].message.content or "",
        "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
    }


async def _call_google(prompt: str, system_prompt: str, model: str) -> dict:
    """Google Gemini API直接呼び出し"""
    from google import genai

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

    response = await client.aio.models.generate_content(
        model=model, contents=full_prompt,
    )
    return {
        "text": response.text or "",
        "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
        "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
    }


async def _call_openrouter(prompt: str, system_prompt: str, model: str, max_tokens: int = 4096) -> dict:
    """OpenRouter API経由呼び出し（100+モデル統合アクセス）
    429 Rate Limit 対策: 最大3回リトライ(5秒間隔)、それでもダメなら例外を上位に伝播。
    上位の call_llm で DeepSeek/Gemini Flash フォールバックが発動する。"""
    import openai

    client = openai.AsyncOpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # モデルチェーン: 指定モデルが404/廃止なら代替モデルを順に試す
    models_to_try = [model]
    if model in OPENROUTER_CONTENT_MODELS:
        models_to_try = OPENROUTER_CONTENT_MODELS.copy()
    elif model == OPENROUTER_QWEN36_MODEL:
        models_to_try = OPENROUTER_CONTENT_MODELS.copy()

    last_error = None
    for current_model in models_to_try:
        for attempt in range(3):
            try:
                resp = await client.chat.completions.create(model=current_model, messages=messages, max_tokens=max_tokens)
                _openrouter_record_use()
                if not resp or not resp.choices:
                    raise ValueError("OpenRouter returned empty choices")
                return {
                    "text": resp.choices[0].message.content or "",
                    "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                }
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if "404" in err_str or "deprecated" in err_str:
                    logger.warning(f"OpenRouter モデル廃止/404 ({current_model}): {str(e)[:80]}. 次のモデルへ")
                    break  # 次のモデルへ
                if "429" in err_str or "rate" in err_str:
                    if attempt < 2:
                        logger.warning(f"OpenRouter 429 (attempt {attempt+1}/3, model={current_model}): {str(e)[:100]}. 5秒後リトライ")
                        await asyncio.sleep(5)
                        continue
            raise  # 429 以外のエラー、または 3 回リトライ失敗は即 raise

    raise last_error or RuntimeError("OpenRouter 3回リトライ後も失敗")


async def call_llm_stream(
    prompt: str,
    system_prompt: str = "",
    model_selection: Optional[dict] = None,
    **kwargs,
):
    """
    ストリーミングLLM呼び出し — トークンを非同期に生成する
    各yieldは {"token": "...", "done": False} または {"token": "", "done": True, ...}
    """
    if model_selection is None:
        model_selection = choose_best_model_v6(task_type="drafting")

    provider = model_selection["provider"]
    model = model_selection["model"]
    via = model_selection.get("via", "direct")
    node = model_selection.get("node")
    tier = model_selection.get("tier", "unknown")

    # 予算チェック（API呼び出し前）
    if provider != "local":
        try:
            budget_guard = get_budget_guard()
            estimated_cost = _estimate_cost_jpy(model, prompt)
            budget_check = await budget_guard.check_before_call(estimated_cost)
            if not budget_check["allowed"]:
                logger.warning(f"予算超過によりローカルLLMへフォールバック: {budget_check['reason']}")
                provider = "local"
                node = _pick_local_node()
                model = "qwen3.5-4b" if node == "delta" else "qwen3.5-9b"
                tier = "L"
        except Exception as e:
            logger.error(f"予算チェック失敗（処理続行）: {e}")

    start_time = time.time()
    full_text = ""

    try:
        if provider == "local":
            async for chunk in _stream_local_llm(prompt, system_prompt, model, node):
                full_text += chunk
                yield {"token": chunk, "done": False}
        elif provider == "deepseek":
            ds_model = "deepseek-reasoner" if "reasoner" in model else "deepseek-chat"
            async for chunk in _stream_openai_compatible(
                prompt, system_prompt, ds_model,
                os.getenv("DEEPSEEK_API_KEY"), "https://api.deepseek.com/v1"
            ):
                full_text += chunk
                yield {"token": chunk, "done": False}
        elif provider == "google":
            async for chunk in _stream_google(prompt, system_prompt, model):
                full_text += chunk
                yield {"token": chunk, "done": False}
        elif provider == "openai" and via == "direct":
            async for chunk in _stream_openai_compatible(
                prompt, system_prompt, model,
                os.getenv("OPENAI_API_KEY"), "https://api.openai.com/v1"
            ):
                full_text += chunk
                yield {"token": chunk, "done": False}
        elif via == "openrouter":
            async for chunk in _stream_openai_compatible(
                prompt, system_prompt, model,
                os.getenv("OPENROUTER_API_KEY"), "https://openrouter.ai/api/v1"
            ):
                full_text += chunk
                yield {"token": chunk, "done": False}
        elif provider == "anthropic":
            async for chunk in _stream_anthropic(prompt, system_prompt, model):
                full_text += chunk
                yield {"token": chunk, "done": False}
        else:
            # フォールバック: 非ストリーミング
            result = await call_llm(prompt, system_prompt, model_selection)
            yield {"token": result.get("text", ""), "done": False}
            full_text = result.get("text", "")

        latency_ms = (time.time() - start_time) * 1000
        yield {
            "token": "", "done": True,
            "model_used": model, "tier": tier,
            "latency_ms": latency_ms, "full_text": full_text,
        }
    except Exception as e:
        logger.error(f"ストリーミングLLM呼び出し失敗 ({model}): {e}")
        # ローカルLLMフォールバック（非ストリーミング）
        if provider != "local":
            try:
                fallback_node = _pick_local_node()
                fallback_model = "qwen3.5-4b" if fallback_node == "delta" else "qwen3.5-9b"
                async for chunk in _stream_local_llm(prompt, system_prompt, fallback_model, fallback_node):
                    full_text += chunk
                    yield {"token": chunk, "done": False}
                yield {"token": "", "done": True, "model_used": fallback_model, "tier": "L", "fallback": True}
                return
            except Exception:
                pass
        yield {"token": "", "done": True, "error": str(e), "model_used": model}


async def _stream_local_llm(prompt: str, system_prompt: str, model: str, node: str):
    """Ollamaストリーミング"""
    url_map = {
        "bravo": os.getenv("BRAVO_OLLAMA_URL", "http://127.0.0.1:11434"),
        "charlie": os.getenv("CHARLIE_OLLAMA_URL", "http://127.0.0.1:11434"),
        "delta": os.getenv("DELTA_OLLAMA_URL", "http://127.0.0.1:11434"),
        "alpha": "http://localhost:11434",
    }
    if not node or node == "auto" or node not in url_map:
        node = _pick_local_node()
    base_url = url_map.get(node, url_map["bravo"])
    ollama_model = os.getenv(f"{node.upper()}_LOCAL_MODEL", model)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json={"model": ollama_model, "messages": messages, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


async def _stream_openai_compatible(
    prompt: str, system_prompt: str, model: str, api_key: str, base_url: str
):
    """OpenAI互換API（DeepSeek/OpenRouter/OpenAI）ストリーミング"""
    import openai
    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def _stream_anthropic(prompt: str, system_prompt: str, model: str):
    """Anthropic APIストリーミング"""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    async with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system_prompt or "You are a helpful assistant.",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_google(prompt: str, system_prompt: str, model: str):
    """Google Gemini APIストリーミング"""
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    async for chunk in client.aio.models.generate_content_stream(
        model=model, contents=full_prompt,
    ):
        if chunk.text:
            yield chunk.text


def log_usage(
    operation: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    success: bool = True,
    error_message: str = "",
):
    """
    model_quality_logテーブルに記録（CLAUDE.md ルール7準拠）
    全ツール呼び出しはtry-exceptで囲みlog_usage()でエラーを記録する。
    """
    try:
        node_name = os.getenv("THIS_NODE", "alpha")
        db_path = Path(f"data/local_{node_name}.db")
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO model_quality_log
               (operation, model, prompt_tokens, completion_tokens, success, error_message, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (operation, model, prompt_tokens, completion_tokens, success, error_message or None),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # ログ記録失敗は無視（本体処理を妨げない）


def _log_llm_call(model: str, tier: str, latency_ms: float, success: bool, error: str = ""):
    """LLM呼び出しをローカルSQLiteに記録"""
    try:
        node_name = os.getenv("THIS_NODE", "alpha")
        db_path = Path(f"data/local_{node_name}.db")
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO llm_call_log (model, tier, latency_ms, success, error_message) VALUES (?, ?, ?, ?, ?)",
            (model, tier or "unknown", latency_ms, success, error or None),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # ログ記録失敗は無視（本体処理を妨げない）


async def call_llm_parallel(
    prompt: str,
    system_prompt: str = "",
    nodes: list = None,
) -> dict:
    """
    Best-of-N並列生成: 複数ノードに同時にリクエストを送り、最良の結果を返す。
    夜間モードのコンテンツ生成で使用。
    """
    nodes = nodes or ["bravo", "charlie"]
    tasks_list = []
    for nd in nodes:
        m = "qwen3.5-4b" if nd == "delta" else "qwen3.5-9b"
        tasks_list.append(_call_local_llm(prompt, system_prompt, m, nd))

    results = await asyncio.gather(*tasks_list, return_exceptions=True)

    valid_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"並列生成 node={nodes[i]} 失敗: {r}")
            continue
        if isinstance(r, dict) and r.get("text"):
            r["source_node"] = nodes[i]
            valid_results.append(r)

    if not valid_results:
        return {"text": "", "error": "全ノードで生成失敗", "alternatives": []}

    # 簡易品質評価: テキスト長 + 日本語率
    def _quick_score(result):
        text = result.get("text", "")
        jp_chars = sum(1 for c in text if '\u3000' <= c <= '\u9fff' or '\u30a0' <= c <= '\u30ff')
        jp_ratio = jp_chars / max(len(text), 1)
        length_score = min(len(text) / 500, 1.0)
        return jp_ratio * 0.6 + length_score * 0.4

    valid_results.sort(key=_quick_score, reverse=True)
    best = valid_results[0]
    best["alternatives"] = valid_results[1:]
    best["parallel_count"] = len(nodes)
    return best
