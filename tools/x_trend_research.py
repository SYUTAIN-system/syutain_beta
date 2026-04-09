"""X トレンド・空気感リサーチ (SYUTAINβ 向け最適化版)

参考記事 (x-research-skills by HayattiQ) のプロンプト設計を
SYUTAINβ 専用に再構築したリサーチパイプライン。

元設計との違い:
  - 想定読者を「投資家+エンジニア」ではなく**「非エンジニア起業家・
    映像クリエイター・AIと共に道を引こうとする人」**に変更
  - 領域を島原大知の関連分野に拡張: 映像制作 / VTuber / ドローン /
    写真 / 広告 / マーケティング / メディア / 映画 / 経営 / 文化 /
    起業、加えて AI / テック / 自律エージェント / Build in Public
  - intel_items テーブルに自動保存して SYUTAINβ 全体から参照可能に
  - 既存の intel 4 施策 (X速報、週次ダイジェスト、システム改善提案、
    Discord経営日報) に供給するアップストリームとして機能
  - ドキュメンタリー記事のネタ出しソースとしても利用
  - 予算ガード連動 (1 call ~¥15-30 程度)

使用例:
    from tools.x_trend_research import research_x_trends
    result = await research_x_trends(
        topic="AIエージェント開発トレンド",
        hours=24,
        count=5,
    )
"""

import os
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("syutain.x_research")

# 島原大知の関連領域 (これらに親和性が高い話題を優先)
SHIMAHARA_DOMAINS = [
    "映像制作", "AI映像", "Runway", "Sora", "Veo",
    "AITuber", "2D/3D モデル",
    "ドローン", "空撮", "FPV",
    "写真", "撮影", "ライティング",
    "広告", "マーケティング", "ブランディング",
    "メディア", "映画", "演出",
    "経営", "起業", "個人事業",
    "文化", "コンテンツ産業",
    # AI / テック
    "Claude Code", "Claude", "Anthropic",
    "GPT", "OpenAI", "Codex",
    "Gemini", "Google AI",
    "AI Agent", "自律エージェント",
    "Build in Public", "個人開発",
    "Ollama", "ローカルLLM",
]


def _default_system_prompt() -> str:
    return (
        "あなたは X (Twitter) 上のトレンドと空気感を正確に読み取るリサーチャーです。"
        "SYUTAINβ という自律型AIビジネスOSのための情報収集を担当しています。"
        "SYUTAINβ の運用者は島原大知 (@Sima_daichi) という映像クリエイター・VTuber業界支援者で、"
        "コードを一行も書かずに Claude Code と組んで AI エージェントを作り続けている人物です。"
        "読者層は「非エンジニアの起業家・クリエイター・映像/VTuber/広告/メディア/映画/経営/文化/起業に関わる人」"
        "と「AIと共に道を引こうとする技術者」です。\n\n"
        "ルール:\n"
        "- 投資助言に見える表現は禁止 (買い/売り/倍化/目標株価など)\n"
        "- 不確かなゴシップは避け、一次情報・公式発表・本人発言を優先する\n"
        "- 引用URLは必ず実在するもの、捏造禁止\n"
        "- 投稿者ハンドル・URL・要約は正確に\n"
        "- 日本語中心だが、海外の一次情報も積極的に拾う\n"
        "- 繰り返し出てくる「機能名」「短いフレーズ」「言い回し」をクラスタ化して抽出する"
    )


def _build_research_prompt(
    topic: str,
    hours: int,
    count: int,
    seeds: Optional[list[str]] = None,
    mode: str = "balanced",
) -> str:
    """参考記事のプロンプト構造を SYUTAINβ 用に再構築"""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    seed_block = ""
    if seeds:
        seed_block = f"\n- シード（出発点となるキーワード）: {', '.join(seeds)}\n"

    domains_hint = ", ".join(SHIMAHARA_DOMAINS[:15]) + "..."

    mode_block = ""
    if mode == "tech":
        mode_block = "\n- モード: テック偏重 (AI/開発/自律エージェント/Claude/Codex 中心)"
    elif mode == "creator":
        mode_block = "\n- モード: クリエイター偏重 (映像/VTuber/ドローン/写真/広告/メディア 中心)"
    elif mode == "business":
        mode_block = "\n- モード: 経営・起業偏重 (個人事業/SaaS/Build in Public/経営判断 中心)"

    return f"""目的: SYUTAINβ の運用と情報発信に役立つ X 上のトレンド・空気感を抽出する。

前提:
- 想定読者: 非エンジニアの起業家・クリエイター + AIと共に道を引こうとする技術者
- 運用者: 島原大知 (@Sima_daichi) — 映像クリエイター、VTuber業界支援者、非エンジニア
- 領域: {topic}
- 関連分野 (親和性が高いと判断するもの): {domains_hint}
- 期間: 「昨日と今日」= {yesterday} と {today} (直近 {hours} 時間){seed_block}{mode_block}
- 文体: 常体、ストーリー薄め、結論先出し

やること (重要: 空気を拾うための探索手順):

1) まず「広く薄く」探索してタイムラインの空気を抽出する
   - seed が無い場合: 上記関連分野に対して広めのクエリを12個以上自分で作って X 検索
   - 収集した投稿から「繰り返し出てくる固有名詞・機能名・言い回し」を抽出
   - 3-5 クラスターにまとめる (単発の話題はクラスターにしない)
   - 抽出した「繰り返し出てくる機能名・短いフレーズ」を2-5個選んで追加検索して補強
   - 可能なら X の検索オペレータを使ってバズを拾う (例: min_faves:500, since:{yesterday})

2) クラスターごとに代表ポストを2つずつ選ぶ (長文の直接引用はしない)

3) 合計 {count} 件の「素材」を出す (各分野に偏らせない)

4) 各素材について以下を必ず出す:
   - url (X の投稿URL、無ければ一次情報URL)
   - 要約 (1-2行、自分の言葉で)
   - エンゲージ指標 (観測できたものだけ: likes/retweets/replies/views)
   - なぜ伸びたか (仮説を3つまで)
   - SYUTAINβ から作れる投稿ネタ案 (note記事1つ、SNS投稿1つ)
   - フック案 (1行を3つ)
   - 注意 (断定/投資助言に見えないよう調整すべき点があれば1行)

追加の要求 (空気感を出す):
- 最初に「タイムラインの空気 (論点のクラスター)」を3-5個、各クラスターに代表ポストURLを2つずつ
- その上で「投稿者が使っている言い回し・キーフレーズ」を各クラスターにつき2-3個 (そのまま引用せず、短い言い換えで)
- 不確かなゴシップは避け、一次情報・公式発表・本人発言を優先。裏が取れないものは「未確認」と明記

出力形式 (JSON):
{{
  "clusters": [
    {{
      "name": "クラスタ名 (短く)",
      "representative_posts": ["https://x.com/...", "https://x.com/..."],
      "key_phrases": ["言い回し1", "言い回し2"]
    }}
  ],
  "today_conclusions": ["狙うべきテーマ1", "狙うべきテーマ2", "狙うべきテーマ3"],
  "materials": [
    {{
      "url": "https://x.com/...",
      "author": "@username",
      "summary": "要約",
      "engagement": {{"likes": 100, "retweets": 20, "replies": 5, "views": 5000}},
      "why_viral": ["理由1", "理由2"],
      "note_angle": "note記事のネタ案",
      "sns_angle": "SNS投稿のネタ案",
      "hooks": ["フック1", "フック2", "フック3"],
      "caveat": "調整点"
    }}
  ],
  "all_urls": ["https://x.com/...", "..."]
}}

必ず有効な JSON のみを返してください。本文や解説は付けないでください。
"""


async def research_x_trends(
    topic: str = "AIエージェント、Build in Public、個人開発者の動き",
    hours: int = 24,
    count: int = 5,
    seeds: Optional[list[str]] = None,
    mode: str = "balanced",
    save_to_intel: bool = True,
    model: Optional[str] = None,
) -> dict:
    """X トレンドリサーチを実行し、結果を JSON + intel_items 保存で返す。

    Args:
        topic: 調査したいメインテーマ
        hours: 直近何時間を対象にするか
        count: 最終的に出力する「素材」の件数
        seeds: 出発点となるキーワード候補 (None で自動選定)
        mode: "balanced" / "tech" / "creator" / "business"
        save_to_intel: True で intel_items テーブルに保存
        model: 上書きする Grok モデル

    Returns:
        {
            "ok": bool,
            "topic": str,
            "parsed": dict,  # JSON解析結果 (clusters/conclusions/materials/all_urls)
            "raw_text": str,
            "cost_jpy": float,
            "citations": list[str],
            "intel_saved": int,
            "error": Optional[str]
        }
    """
    from tools.grok_client import call_grok, DEFAULT_MODEL, _is_available

    if not _is_available():
        return {
            "ok": False,
            "error": "XAI_API_KEY 未設定。.env に XAI_API_KEY=xai-... を追加してください",
            "cost_jpy": 0.0,
        }

    prompt = _build_research_prompt(topic, hours, count, seeds, mode)
    system = _default_system_prompt()

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(hours=hours)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    result = await call_grok(
        prompt=prompt,
        system_prompt=system,
        model=model or DEFAULT_MODEL,
        max_tokens=8192,
        temperature=0.7,
        live_search=True,
        search_sources=[{"type": "x"}, {"type": "web"}, {"type": "news"}],
        from_date=from_date,
        to_date=to_date,
        max_search_results=30,
        return_citations=True,
        goal_id="x_trend_research",
    )

    if result.get("error"):
        return {
            "ok": False,
            "error": result["error"],
            "cost_jpy": result.get("cost_jpy", 0.0),
            "topic": topic,
        }

    raw_text = result.get("text", "")
    parsed: dict = {}
    try:
        # Grok が ```json ... ``` で囲むことがあるので除去
        text_to_parse = raw_text.strip()
        if text_to_parse.startswith("```"):
            text_to_parse = re.sub(r"^```(?:json)?\s*", "", text_to_parse)
            text_to_parse = re.sub(r"\s*```$", "", text_to_parse)
        parsed = json.loads(text_to_parse)
    except Exception as e:
        logger.warning(f"Grok応答のJSON解析失敗: {e}. 生テキストを保存します")
        parsed = {"raw": raw_text[:2000]}

    intel_saved = 0
    if save_to_intel and parsed.get("materials"):
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                for m in parsed.get("materials", [])[:count]:
                    if not isinstance(m, dict):
                        continue
                    url = (m.get("url") or "")[:500]
                    summary = (m.get("summary") or "")[:1500]
                    author = (m.get("author") or "")[:100]
                    engagement = m.get("engagement", {}) or {}
                    likes = engagement.get("likes", 0) if isinstance(engagement, dict) else 0
                    try:
                        importance = min(1.0, (int(likes or 0) / 1000.0))
                    except Exception:
                        importance = 0.5
                    title = (m.get("note_angle") or summary[:80] or "X trend item")[:200]
                    try:
                        await conn.execute(
                            """INSERT INTO intel_items
                               (source, keyword, title, summary, url, importance_score,
                                category, review_flag, metadata, created_at)
                               VALUES ('grok_x_research', $1, $2, $3, $4, $5,
                                       'x_trend', 'actionable', $6::jsonb, NOW())""",
                            topic[:200], title, summary, url, importance,
                            json.dumps({
                                "author": author,
                                "engagement": engagement,
                                "why_viral": m.get("why_viral", []),
                                "note_angle": m.get("note_angle", ""),
                                "sns_angle": m.get("sns_angle", ""),
                                "hooks": m.get("hooks", []),
                                "caveat": m.get("caveat", ""),
                                "mode": mode,
                                "researched_at": now.isoformat(),
                            }, ensure_ascii=False),
                        )
                        intel_saved += 1
                    except Exception as e:
                        logger.debug(f"intel保存スキップ: {e}")
        except Exception as e:
            logger.warning(f"intel保存の全体失敗: {e}")

    return {
        "ok": True,
        "topic": topic,
        "parsed": parsed,
        "raw_text": raw_text,
        "cost_jpy": result.get("cost_jpy", 0.0),
        "citations": result.get("citations", []),
        "intel_saved": intel_saved,
        "model": result.get("model", ""),
        "error": None,
    }


async def quick_x_search(query: str, hours: int = 24) -> dict:
    """軽量な X 検索: Grok Live Search でクエリを直接投げ、要約テキストを返す。
    Brain-β の直接ルート向け、コスト ~¥5-10。
    """
    from tools.grok_client import search_x

    result = await search_x(query=query, hours=hours, max_results=15)
    return result
