"""Grok 活用の共通ヘルパー (9 機能)

SYUTAINβ の既存パイプライン（content_pipeline / sns_batch / proposal_engine /
self_healer / scheduler）から呼び出される小さな専用関数群。

各関数は Grok の Responses API + Agent Tools API を使い、必ず JSON を返す。
コストは 1 call ~¥0.02-0.5 (cost_in_usd_ticks 実測)。予算 guard は
grok_client 内で自動連動。

2026-04-06 実装（V25 rev.5）:
  1. grok_fact_check         — note記事の事実主張検証
  2. grok_topic_traction     — SNS投稿前の話題性スコア (0-1)
  3. grok_monitor_mentions   — 競合・自己言及モニタリング
  5. grok_trending_hashtags  — 今使われているハッシュタグ取得
  6. grok_topicality_score   — 記事テーマの時事性評価 (0-1)
  7. grok_similar_incidents  — 類似障害事例を X/Web で検索
  8. grok_persona_verify     — 発言内容を公開情報と照合
  9. grok_market_sentiment   — 提案の市場反応シミュレーション
 10. grok_upcoming_events    — 今後N日間のイベント・話題予測

(#4 リプライ下書きアシストは島原さん判断で対象外)
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger("syutain.grok_helpers")


async def _call_grok_json(
    prompt: str,
    system: str,
    tools: Optional[list[dict]] = None,
    max_tokens: int = 2500,
    goal_id: str = "grok_helper",
) -> dict:
    """Grok を呼んで JSON を返させる共通ラッパー。
    デフォルトで x_search + web_search ツールを有効化。パース失敗時は raw テキストを返す。"""
    from tools.grok_client import call_grok_responses
    if tools is None:
        tools = [{"type": "x_search"}, {"type": "web_search"}]

    instructions = system + "\n\n必ず有効な JSON オブジェクトのみを返してください。説明文や markdown code fence は付けないでください。"

    result = await call_grok_responses(
        user_input=prompt,
        system_instructions=instructions,
        tools=tools,
        max_output_tokens=max_tokens,
        goal_id=goal_id,
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "cost_jpy": result.get("cost_jpy", 0.0)}

    text = (result.get("text") or "").strip()
    # code fence 除去
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed: dict = {}
    try:
        parsed = json.loads(text)
    except Exception:
        # 部分的にJSONが含まれている場合を救出
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = {"raw": text[:1500]}
        else:
            parsed = {"raw": text[:1500]}

    return {
        "ok": True,
        "parsed": parsed,
        "cost_jpy": result.get("cost_jpy", 0.0),
        "citations": result.get("citations", []),
        "tool_calls": len(result.get("tool_calls", [])),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #1 note 記事ファクト強化
# ═══════════════════════════════════════════════════════════════════════════

async def grok_fact_check(claims: list[str], topic_hint: str = "") -> dict:
    """note 記事中の事実主張リストを Grok で検証する。

    Args:
        claims: 検証したい事実主張の文リスト
        topic_hint: 記事全体のテーマ (精度向上)

    Returns:
        {
            "ok": bool,
            "verified": [{"claim": str, "verdict": "true"/"false"/"unverified", "reason": str, "sources": [url]}],
            "critical_issues": ["虚偽が確認された claim 要約"],
            "cost_jpy": float
        }
    """
    if not claims:
        return {"ok": True, "verified": [], "critical_issues": [], "cost_jpy": 0.0}

    claim_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims[:10]))
    prompt = (
        f"以下の事実主張を X (Twitter) と Web で検証してください。\n"
        f"{'テーマ: ' + topic_hint if topic_hint else ''}\n\n"
        f"主張リスト:\n{claim_lines}\n\n"
        f"各主張について、verdict を 'true' (実在/裏付けあり) / 'false' (虚偽) / "
        f"'unverified' (裏が取れない) のいずれかで返してください。\n\n"
        f'JSON スキーマ: {{"verified": [{{"claim": "...", "verdict": "true|false|unverified", "reason": "...", "sources": ["url"]}}]}}'
    )
    system = (
        "あなたは厳密なファクトチェッカー。一次情報・公式発表・本人発言を優先し、"
        "裏が取れない主張は必ず 'unverified' とする。確信がないものを 'true' にしない。"
    )
    r = await _call_grok_json(prompt, system, goal_id="grok_fact_check")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    verified = parsed.get("verified", []) if isinstance(parsed, dict) else []
    critical = []
    for v in verified:
        if isinstance(v, dict) and v.get("verdict") == "false":
            critical.append(f"[Grok虚偽検出] {v.get('claim', '')[:100]}: {v.get('reason', '')[:100]}")
    return {
        "ok": True,
        "verified": verified,
        "critical_issues": critical,
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #2 SNS 投稿の話題接続検証
# ═══════════════════════════════════════════════════════════════════════════

async def grok_topic_traction(content: str, platform: str = "x") -> dict:
    """SNS 投稿候補の話題性を Grok で評価 (0-1 スコア)。
    0.5 未満なら静かな話題、0.7 以上ならバズ文脈と接続している"""
    snippet = content[:500]
    prompt = (
        f"以下の {platform.upper()} 投稿候補が、現在 (直近24時間) の {platform.upper()} で話題になっている文脈と"
        f"接続しているかを評価してください。\n\n投稿候補:\n```\n{snippet}\n```\n\n"
        f"関連キーワードで X 検索し、以下を JSON で返してください:\n"
        f'{{"traction_score": 0.0-1.0, "reasoning": "...", "related_posts": ["url"], "recommendation": "post_now|adjust|skip"}}'
    )
    system = "あなたはSNSマーケティング分析AI。投稿タイミングとトレンド接続を評価する。"
    r = await _call_grok_json(prompt, system, tools=[{"type": "x_search"}], max_tokens=1500, goal_id="grok_topic_traction")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "traction_score": 0.5, "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "traction_score": float(parsed.get("traction_score", 0.5) or 0.5),
        "reasoning": parsed.get("reasoning", ""),
        "recommendation": parsed.get("recommendation", "post_now"),
        "related_posts": parsed.get("related_posts", []),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #3 競合・自己言及モニタリング
# ═══════════════════════════════════════════════════════════════════════════

async def grok_monitor_mentions(keywords: list[str], hours: int = 24) -> dict:
    """指定キーワード群を X で追跡し、言及・競合動向を返す。"""
    if not keywords:
        return {"ok": True, "mentions": [], "cost_jpy": 0.0}
    kw = ", ".join(keywords[:8])
    prompt = (
        f"直近{hours}時間の X で以下のキーワードへの言及を追跡してください: {kw}\n\n"
        f"各言及について: 投稿者, URL, 要約, 言及の性質 (肯定/中立/批判/競合アナウンス)、"
        f"SYUTAINβ 運用者 (島原大知) にとっての重要度 (high/medium/low) を判定。\n\n"
        f'JSON: {{"mentions": [{{"url": "...", "author": "@...", "summary": "...", "sentiment": "...", "importance": "..."}}], '
        f'"competitor_updates": ["..."], "key_insights": ["..."]}}'
    )
    system = (
        "あなたは競合インテリジェンス担当。SYUTAINβ は非エンジニアの島原大知が Claude Code と組んで "
        "AI エージェントを作る Build in Public プロジェクト。類似プロジェクト・言及・業界動向を拾う。"
    )
    r = await _call_grok_json(prompt, system, goal_id="grok_mention_monitor")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "mentions": parsed.get("mentions", []),
        "competitor_updates": parsed.get("competitor_updates", []),
        "key_insights": parsed.get("key_insights", []),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #5 ハッシュタグ最適化
# ═══════════════════════════════════════════════════════════════════════════

async def grok_trending_hashtags(topic: str, platform: str = "x", limit: int = 5) -> dict:
    """指定トピックで現在使われているハッシュタグを X から取得"""
    prompt = (
        f"{platform.upper()} で「{topic}」に関連して現在 (直近24時間) 実際に使われている"
        f"ハッシュタグを最大{limit}個、使用頻度順で返してください。\n\n"
        f'JSON: {{"hashtags": [{{"tag": "#...", "frequency_level": "high|medium|low", "context": "..."}}]}}'
    )
    system = "あなたはSNSハッシュタグ分析AI。実際に使われているものだけを返す。捏造禁止。"
    r = await _call_grok_json(prompt, system, tools=[{"type": "x_search"}], max_tokens=1000, goal_id="grok_hashtag")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "hashtags": [], "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    hashtags = parsed.get("hashtags", []) if isinstance(parsed, dict) else []
    tags = []
    for h in hashtags:
        if isinstance(h, dict):
            t = h.get("tag", "").strip()
            if t and not t.startswith("#"):
                t = "#" + t
            if t:
                tags.append(t)
        elif isinstance(h, str):
            tags.append(h if h.startswith("#") else "#" + h)
    return {"ok": True, "hashtags": tags[:limit], "cost_jpy": r.get("cost_jpy", 0.0)}


# ═══════════════════════════════════════════════════════════════════════════
# #6 記事の時事性スコア
# ═══════════════════════════════════════════════════════════════════════════

async def grok_topicality_score(title: str, summary: str = "") -> dict:
    """記事のテーマが現在進行形の話題かを Grok で評価 (0-1)。
    0.8 以上なら即時公開推奨、0.4 未満なら夜間バッチで OK"""
    prompt = (
        f"以下の note 記事のテーマが、現在 (直近72時間) X/Web で話題になっている"
        f"現在進行形のトピックかどうかを評価してください。\n\n"
        f"タイトル: {title[:200]}\n要約: {summary[:500]}\n\n"
        f'JSON: {{"topicality_score": 0.0-1.0, "current_buzz_level": "high|medium|low|static", '
        f'"publish_urgency": "immediate|today|this_week|anytime", "reasoning": "..."}}'
    )
    system = "あなたはコンテンツタイミング分析AI。今書くべきか後でいいかを判定する。"
    r = await _call_grok_json(prompt, system, max_tokens=800, goal_id="grok_topicality")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "topicality_score": 0.5, "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "topicality_score": float(parsed.get("topicality_score", 0.5) or 0.5),
        "current_buzz_level": parsed.get("current_buzz_level", "medium"),
        "publish_urgency": parsed.get("publish_urgency", "this_week"),
        "reasoning": parsed.get("reasoning", ""),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #7 障害事例リサーチ
# ═══════════════════════════════════════════════════════════════════════════

async def grok_similar_incidents(error_summary: str, tech_stack: str = "Python + PostgreSQL + NATS + Ollama + Claude Code") -> dict:
    """類似障害・解決例を X/Web で検索、self_healer の参考情報を返す"""
    prompt = (
        f"以下のエラー・障害について、他の個人開発者や OSS 界隈で類似事例・解決方法を"
        f"X / Web で検索してください。\n\n"
        f"技術スタック: {tech_stack}\n"
        f"エラー概要: {error_summary[:800]}\n\n"
        f'JSON: {{"similar_cases": [{{"source": "url", "description": "...", "resolution": "...", "relevance": "high|medium|low"}}], '
        f'"suggested_fix": "...", "known_bug": "true|false|unknown"}}'
    )
    system = "あなたは障害対応アシスタント。実在する事例のみ返す。架空の解決策を捏造しない。"
    r = await _call_grok_json(prompt, system, max_tokens=2500, goal_id="grok_incident_research")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "similar_cases": parsed.get("similar_cases", []),
        "suggested_fix": parsed.get("suggested_fix", ""),
        "known_bug": parsed.get("known_bug", "unknown"),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #8 ペルソナ検証ループ
# ═══════════════════════════════════════════════════════════════════════════

async def grok_persona_verify(statement: str, context: str = "") -> dict:
    """島原さんの発言・判断基準を公開情報 (X, Web, 過去の投稿) と照合して矛盾を検出"""
    prompt = (
        f"以下は島原大知 (@Sima_daichi / @syutain_beta) の発言または SYUTAINβ の判断基準です。\n"
        f"公開されている島原さんの過去発言・プロフィール情報と矛盾していないかチェックしてください。\n\n"
        f"発言: {statement[:600]}\n"
        f"{'コンテキスト: ' + context[:400] if context else ''}\n\n"
        f'JSON: {{"consistent": true|false, "confidence": 0.0-1.0, "supporting_evidence": ["url"], '
        f'"conflicts": ["..."], "persona_refinement": "..."}}'
    )
    system = (
        "あなたはペルソナ一貫性検証AI。島原大知の公開情報 (X, note, Build in Public 投稿) を"
        "重視し、発言の一貫性を検証する。"
    )
    r = await _call_grok_json(prompt, system, max_tokens=1500, goal_id="grok_persona_verify")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "consistent": bool(parsed.get("consistent", True)),
        "confidence": float(parsed.get("confidence", 0.5) or 0.5),
        "conflicts": parsed.get("conflicts", []),
        "persona_refinement": parsed.get("persona_refinement", ""),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #9 意思決定前リアルタイム検索
# ═══════════════════════════════════════════════════════════════════════════

async def grok_market_sentiment(proposal_text: str) -> dict:
    """提案内容の市場反応をリアルタイム検索で予測 (proposal_engine 統合用)"""
    prompt = (
        f"以下の事業提案について、同様のアイデアや競合商品への現在の市場反応 (X, Web) を"
        f"調査してください。\n\n提案:\n```\n{proposal_text[:1500]}\n```\n\n"
        f'JSON: {{"market_sentiment": "positive|neutral|negative|mixed", "confidence": 0.0-1.0, '
        f'"similar_products": ["..."], "differentiation_opportunities": ["..."], '
        f'"red_flags": ["..."], "go_no_go": "go|conditional|no_go", "reasoning": "..."}}'
    )
    system = (
        "あなたは市場分析アシスタント。個人開発者の事業提案を、実際の市場動向・類似事例・"
        "競合商品と照らして評価する。投資助言ではなく、戦略判断材料として返す。"
    )
    r = await _call_grok_json(prompt, system, max_tokens=2500, goal_id="grok_market_sentiment")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "sentiment": parsed.get("market_sentiment", "neutral"),
        "confidence": float(parsed.get("confidence", 0.5) or 0.5),
        "similar_products": parsed.get("similar_products", []),
        "differentiation_opportunities": parsed.get("differentiation_opportunities", []),
        "red_flags": parsed.get("red_flags", []),
        "go_no_go": parsed.get("go_no_go", "conditional"),
        "reasoning": parsed.get("reasoning", ""),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #10 コンテンツカレンダー自動生成
# ═══════════════════════════════════════════════════════════════════════════

async def grok_upcoming_events(days: int = 7, domains: Optional[list[str]] = None) -> dict:
    """今後N日間の話題・イベント・製品発表を予測してコンテンツカレンダーに使う"""
    if domains is None:
        domains = [
            "AI エージェント / Claude Code / Codex", "映像制作 × AI",
            "VTuber / ドローン / 写真", "個人開発 / Build in Public",
            "広告 / マーケ / メディア", "起業 / 経営判断",
        ]
    domain_list = ", ".join(domains[:8])
    prompt = (
        f"今後{days}日間に予定されている、または確度が高いイベント・製品発表・話題ピークを "
        f"X / Web で調査してください。対象分野: {domain_list}\n\n"
        f"各イベントについて: 予定日, タイトル, 一次情報URL, SYUTAINβ にとって活用可能な "
        f"note 記事のネタ案 / SNS 投稿のタイミング案を提示。\n\n"
        f'JSON: {{"events": [{{"date": "YYYY-MM-DD", "title": "...", "source_url": "...", '
        f'"note_angle": "...", "sns_timing": "...", "relevance": "high|medium|low"}}]}}'
    )
    system = "あなたはコンテンツカレンダー プランナー。既知の確度が高いイベントのみ返す。"
    r = await _call_grok_json(prompt, system, max_tokens=3500, goal_id="grok_upcoming_events")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cost_jpy": r.get("cost_jpy", 0.0)}
    parsed = r.get("parsed", {})
    return {
        "ok": True,
        "events": parsed.get("events", []),
        "cost_jpy": r.get("cost_jpy", 0.0),
    }
