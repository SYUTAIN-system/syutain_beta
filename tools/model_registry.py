"""
SYUTAINβ V25 モデルレジストリ
全利用可能モデルの情報を一元管理
"""

# Tier S（最高精度）
TIER_S = {
    "gpt-5.4": {
        "provider": "openai", "via": "direct",
        "input_per_1m": 2.50, "output_per_1m": 15.00,
        "context": 1_000_000, "intelligence": 57,
        "features": ["computer_use", "tool_search", "multimodal"],
    },
    "gemini-3.1-pro-preview": {
        "provider": "google", "via": "direct",
        "input_per_1m": 2.00, "output_per_1m": 12.00,
        "context": 1_000_000, "intelligence": 57,
        "features": ["multimodal"],
    },
    "claude-opus-4-6": {
        "provider": "anthropic", "via": "direct",
        "input_per_1m": 5.00, "output_per_1m": 25.00,
        "context": 200_000, "intelligence": 53,
        "features": ["agentic", "mcp"],
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic", "via": "direct",
        "input_per_1m": 3.00, "output_per_1m": 15.00,
        "context": 200_000, "intelligence": 52,
        "features": ["agentic", "mcp"],
    },
}

# Tier A（高品質・主力帯）
TIER_A = {
    "deepseek-v3.2": {
        "provider": "deepseek", "via": "direct",
        "input_per_1m": 0.28, "output_per_1m": 0.42,
        "context": 128_000, "intelligence": 45,
        "features": ["cache_discount"],
    },
    "gemini-2.5-pro": {
        "provider": "google", "via": "openrouter",
        "input_per_1m": 1.25, "output_per_1m": 10.00,
        "context": 1_000_000, "intelligence": 46,
        "features": ["thinking", "multimodal"],
    },
    "gpt-5-mini": {
        "provider": "openai", "via": "openrouter",
        "input_per_1m": 0.25, "output_per_1m": 2.00,
        "context": 128_000, "intelligence": 40,
        "features": [],
    },
    "gemini-2.5-flash": {
        "provider": "google", "via": "openrouter",
        "input_per_1m": 0.15, "output_per_1m": 0.60,
        "context": 1_000_000, "intelligence": 38,
        "features": ["thinking"],
    },
    "claude-haiku-4-5": {
        "provider": "anthropic", "via": "direct",
        "input_per_1m": 1.00, "output_per_1m": 5.00,
        "context": 200_000, "intelligence": 35,
        "features": [],
    },
}

# Tier B（低コスト量産）
TIER_B = {
    "gpt-5-nano": {
        "provider": "openai", "via": "openrouter",
        "input_per_1m": 0.05, "output_per_1m": 0.40,
        "context": 128_000, "intelligence": 25,
        "features": [],
    },
    "gemini-2.5-flash-lite": {
        "provider": "google", "via": "openrouter",
        "input_per_1m": 0.075, "output_per_1m": 0.30,
        "context": 1_000_000, "intelligence": 22,
        "features": [],
        "deprecation": "2026-06-01",
    },
}

# Tier L（ローカル無料）
TIER_L = {
    "qwen3.5-9b": {
        "provider": "local", "via": "ollama",
        "nodes": ["bravo", "charlie", "alpha"],
        "vram_gb": 6.5, "speed_tok_s": {"bravo": 15, "charlie": 14, "alpha": 32},
        "context": 262_000, "intelligence": 30,
        "features": ["multimodal", "thinking", "tool_calling"],
    },
    "qwen3.5-4b": {
        "provider": "local", "via": "ollama",
        "nodes": ["delta"],
        "vram_gb": 5.0, "speed_tok_s": {"delta": 10},
        "context": 131_000, "intelligence": 22,
        "features": ["multimodal", "thinking"],
    },
}

# 全モデル統合辞書
ALL_MODELS = {**TIER_S, **TIER_A, **TIER_B, **TIER_L}


def get_model_info(model_name: str) -> dict:
    """モデル情報を取得"""
    return ALL_MODELS.get(model_name, {})


def get_tier(model_name: str) -> str:
    """モデルのTierを取得"""
    if model_name in TIER_S:
        return "S"
    if model_name in TIER_A:
        return "A"
    if model_name in TIER_B:
        return "B"
    if model_name in TIER_L:
        return "L"
    return "unknown"
