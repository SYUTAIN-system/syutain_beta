"""xAI Grok API クライアント — X (Twitter) リアルタイム検索 + Responses API

Endpoint: https://api.x.ai/v1/responses (OpenAI Responses API 互換)
Built-in tools: x_search (x_keyword_search + x_semantic_search 自動切替),
                web_search, code_execution 等

旧 Live Search API (/v1/chat/completions + search_parameters) は deprecated。
SYUTAINβ は新しい Agent Tools API (Responses API) を使う。

Models:
  - grok-4-fast-reasoning: 高速 + 推論ツール使用 (本命、SYUTAINβ のデフォルト)
  - grok-4-fast-non-reasoning: 非推論、さらに高速
  - grok-4-0709: フルモデル、深い分析用
  - grok-3 / grok-3-mini: 旧世代

SYUTAINβでの主な用途:
  - X リアルタイムトレンド取得 (参考記事の手法に準拠)
  - 記事執筆時のファクト収集
  - 海外/国内の空気感を拾う深掘り調査
  - 競合分析・言及モニタリング

コスト目安: 1 call あたり ~¥15-50 (x_search + tool 実行コスト込み)
予算ガード連動: budget_guard.record_spend() を必ず経由
CLAUDE.md Rule 8 準拠: API キーは .env から読み込み、ログ出力しない
"""

import os
import json
import logging
from typing import Optional, Any

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("syutain.grok")

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = "https://api.x.ai/v1"

# xAI は usage.cost_in_usd_ticks に **実コスト** を返してくれる。
# 検証: "Hi" 1語送信 → 1005000 ticks → ~$0.0001 → ~¥0.015 (cached_tokens 156/157 割引込み)。
# 変換: 1 USD = 10^10 ticks (tick = 10^-10 USD)。
TICKS_PER_USD = 1e10

# フォールバック用の token 単価表 (cost_in_usd_ticks が欠落時のみ使用)
MODEL_COSTS = {
    "grok-4-fast-reasoning": {"input_per_1m": 0.20, "output_per_1m": 0.50},
    "grok-4-fast-non-reasoning": {"input_per_1m": 0.20, "output_per_1m": 0.50},
    "grok-4-fast": {"input_per_1m": 0.20, "output_per_1m": 0.50},
    "grok-4-0709": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "grok-4": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "grok-3": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "grok-3-mini": {"input_per_1m": 0.30, "output_per_1m": 0.50},
}
DEFAULT_MODEL = "grok-4-fast-reasoning"
USD_TO_JPY = 152.0


def _is_available() -> bool:
    return bool(XAI_API_KEY) and XAI_API_KEY.startswith("xai-")


async def call_grok_responses(
    user_input: str,
    system_instructions: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    tools: Optional[list[dict]] = None,
    max_output_tokens: Optional[int] = None,
    goal_id: str = "grok_responses",
) -> dict:
    """xAI Responses API (/v1/responses) を呼び出す。

    Args:
        user_input: ユーザー入力テキスト
        system_instructions: システムレベルの指示 (Responses API の instructions フィールド)
        model: grok-4-fast-reasoning / grok-4-fast-non-reasoning / grok-4-0709 等
        tools: Agent Tools API のツール仕様。例: [{"type": "x_search"}, {"type": "web_search"}]
               None の場合、x_search と web_search を自動付与
        max_output_tokens: 応答の最大トークン数
        goal_id: budget_guard / event_log 用のラベル

    Returns:
        {
            "ok": bool,
            "text": str,              # 最終的な応答テキスト
            "model": str,
            "cost_jpy": float,
            "usage": dict,
            "citations": list[dict],  # URL 引用 (url/title/start_index/end_index)
            "tool_calls": list[dict], # モデルが実行したツール呼び出し
            "raw": dict,              # レスポンス全体
            "error": Optional[str],
        }
    """
    if not _is_available():
        return {"ok": False, "text": "", "error": "XAI_API_KEY未設定", "cost_jpy": 0.0}

    # 予算事前チェック
    try:
        from tools.budget_guard import get_budget_guard
        guard = get_budget_guard()
        await guard._load_from_db()
        precheck = await guard.check_before_call(30.0)
        if precheck and not precheck.get("allowed", True):
            return {
                "ok": False,
                "text": "",
                "error": f"予算上限超過: {precheck.get('message', '')}",
                "cost_jpy": 0.0,
            }
    except Exception as e:
        logger.debug(f"budget_guard precheck skip: {e}")

    if tools is None:
        tools = [{"type": "x_search"}, {"type": "web_search"}]

    body: dict[str, Any] = {
        "model": model,
        "input": user_input,
        "tools": tools,
    }
    if system_instructions:
        body["instructions"] = system_instructions
    if max_output_tokens:
        body["max_output_tokens"] = max_output_tokens

    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{XAI_BASE_URL}/responses",
                headers=headers,
                json=body,
            )
            if resp.status_code != 200:
                err = resp.text[:500]
                logger.warning(f"Grok Responses API HTTP {resp.status_code}: {err}")
                return {
                    "ok": False, "text": "", "error": f"HTTP {resp.status_code}: {err}",
                    "cost_jpy": 0.0,
                }
            data = resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "text": "", "error": "Grok API timeout (180s)", "cost_jpy": 0.0}
    except Exception as e:
        logger.error(f"Grok Responses API call failed: {e}")
        return {"ok": False, "text": "", "error": str(e), "cost_jpy": 0.0}

    # 応答の解析
    text = ""
    citations: list[dict] = []
    tool_calls: list[dict] = []
    try:
        for item in data.get("output", []) or []:
            itype = item.get("type", "")
            if itype == "message":
                for content in item.get("content", []) or []:
                    if content.get("type") == "output_text":
                        text += content.get("text", "") or ""
                        # 引用 annotations
                        for ann in content.get("annotations", []) or []:
                            if ann.get("type") == "url_citation":
                                citations.append({
                                    "url": ann.get("url", ""),
                                    "title": ann.get("title", ""),
                                    "start": ann.get("start_index", 0),
                                    "end": ann.get("end_index", 0),
                                })
            elif itype == "custom_tool_call":
                tool_calls.append({
                    "name": item.get("name", ""),
                    "input": item.get("input", ""),
                    "call_id": item.get("call_id", ""),
                    "status": item.get("status", ""),
                })
    except Exception as e:
        logger.warning(f"Grok response parse failed: {e}")

    # コスト計算: xAI が返す cost_in_usd_ticks を優先 (ツール実行コスト含む、cache割引反映済み)
    usage = data.get("usage", {}) or {}
    input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
    output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
    cost_ticks = usage.get("cost_in_usd_ticks", 0) or 0

    if cost_ticks > 0:
        cost_usd = cost_ticks / TICKS_PER_USD
        cost_jpy = cost_usd * USD_TO_JPY
    else:
        # フォールバック: トークン単価での推定 (ツールコスト無視、誤差あり)
        cost_info = MODEL_COSTS.get(model, MODEL_COSTS[DEFAULT_MODEL])
        token_cost_usd = (
            (input_tokens / 1_000_000) * cost_info["input_per_1m"]
            + (output_tokens / 1_000_000) * cost_info["output_per_1m"]
        )
        cost_jpy = token_cost_usd * USD_TO_JPY

    # 予算ガード記録
    try:
        from tools.budget_guard import get_budget_guard
        guard = get_budget_guard()
        await guard.record_spend(
            amount_jpy=cost_jpy,
            model=model,
            tier="grok",
            is_info_collection=True,
            goal_id=goal_id,
        )
    except Exception as e:
        logger.debug(f"budget_guard record skip: {e}")

    logger.info(
        f"grok responses: model={model} in={input_tokens} out={output_tokens} "
        f"tool_calls={len(tool_calls)} citations={len(citations)} cost=¥{cost_jpy:.2f}"
    )

    return {
        "ok": True,
        "text": text,
        "model": data.get("model", model),
        "cost_jpy": round(cost_jpy, 2),
        "usage": usage,
        "citations": citations,
        "tool_calls": tool_calls,
        "raw": data,
        "error": None,
    }


# 旧 API 互換ラッパー (x_trend_research から呼ばれる)
async def call_grok(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    live_search: bool = False,
    search_sources: Optional[list[dict]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_search_results: int = 20,
    return_citations: bool = True,
    goal_id: str = "grok_chat",
) -> dict:
    """旧 live_search=True 向けの互換ラッパー。
    内部で Responses API + x_search / web_search ツールに変換する。"""
    tools = None
    if live_search:
        tools = []
        # sources から tool type を推定
        if search_sources:
            for src in search_sources:
                t = src.get("type", "")
                if t == "x":
                    tools.append({"type": "x_search"})
                elif t == "web":
                    tools.append({"type": "web_search"})
                elif t == "news":
                    tools.append({"type": "web_search"})  # xAI 側で web_search が news も拾う
        if not tools:
            tools = [{"type": "x_search"}, {"type": "web_search"}]

    # 期間制約を prompt に自然言語で付与
    period_hint = ""
    if from_date and to_date:
        period_hint = f"\n\n検索対象期間: {from_date} 〜 {to_date}"

    full_input = f"{prompt}{period_hint}"
    if return_citations:
        full_input += "\n\n必ず URL 引用を付けてください。"

    result = await call_grok_responses(
        user_input=full_input,
        system_instructions=system_prompt or None,
        model=model,
        tools=tools,
        max_output_tokens=max_tokens,
        goal_id=goal_id,
    )

    # 旧 API 形式に正規化
    return {
        "text": result.get("text", ""),
        "model": result.get("model", model),
        "cost_jpy": result.get("cost_jpy", 0.0),
        "usage": result.get("usage", {}),
        "citations": [c.get("url", "") for c in result.get("citations", []) if c.get("url")],
        "error": result.get("error"),
        "tool_calls": result.get("tool_calls", []),
    }


async def search_x(
    query: str,
    hours: int = 24,
    max_results: int = 20,
    min_faves: Optional[int] = None,
    lang: Optional[str] = None,
) -> dict:
    """X 検索を Grok Responses API + x_search ツールで実行 (軽量版)"""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(hours=hours)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    full_query = query
    if min_faves:
        full_query += f" min_faves:{min_faves}"
    if lang:
        full_query += f" lang:{lang}"

    prompt = (
        f"X (Twitter) で「{full_query}」について{from_date}〜{to_date}の期間で検索し、"
        f"関連投稿を最大{max_results}件ピックアップしてください。\n"
        f"各投稿について:\n"
        f"- URL (x.com/...)\n"
        f"- 投稿者ハンドル (@username)\n"
        f"- 要約 (1-2行)\n"
        f"- エンゲージメント指標 (likes/retweets/views、わかる範囲)\n"
        f"- 投稿時刻\n"
    )

    return await call_grok_responses(
        user_input=prompt,
        system_instructions="あなたは X (Twitter) のリアルタイム情報リサーチャー。正確な引用とURLを重視してください。",
        model=DEFAULT_MODEL,
        tools=[{"type": "x_search"}],
        max_output_tokens=3000,
        goal_id="grok_x_search",
    )
