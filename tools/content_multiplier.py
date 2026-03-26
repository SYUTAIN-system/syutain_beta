"""
SYUTAINβ V25 1素材→多フォーマット自動展開パイプライン

入力: 1本のMarkdown記事（note記事 or 成果物）
出力:
  - Bluesky投稿 5本
  - X投稿案 3本（島原アカウント）
  - X投稿案 2本（SYUTAINβアカウント）
  - Booth商品説明ドラフト（商品化可能な場合のみ）
  - 次回note記事ネタ3案
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.content_multiplier")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


async def multiply_content(
    source_text: str,
    source_title: str = "",
    source_type: str = "note_article",
    submit_to_approval: bool = True,
) -> dict:
    """
    1本の記事から多フォーマット派生コンテンツを生成

    Args:
        source_text: 元記事のMarkdownテキスト
        source_title: 元記事のタイトル
        source_type: ソースの種類（note_article, artifact, etc.）
        submit_to_approval: 承認キューに投入するか

    Returns:
        {
            "bluesky": [5本],
            "x_shimahara": [3本],
            "x_syutain": [2本],
            "booth_desc": str or None,
            "note_ideas": [3本],
            "total_count": int,
        }
    """
    from tools.llm_router import call_llm, choose_best_model_v6

    # 戦略ファイル読み込み
    strategy_id = ""
    channel_strategy = ""
    anti_ai = ""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base_dir, "prompts", "strategy_identity.md"), "r") as f:
            strategy_id = f.read()
        with open(os.path.join(base_dir, "strategy", "CHANNEL_STRATEGY.md"), "r") as f:
            channel_strategy = f.read()
        with open(os.path.join(base_dir, "prompts", "anti_ai_writing.md"), "r") as f:
            anti_ai = f.read()
    except Exception:
        pass

    # intel_itemsから直近トレンドを取得（Q8/Q9修正: SNS投稿に市場動向を反映）
    intel_context = ""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as _conn_cm:
            intel_rows = await _conn_cm.fetch(
                """SELECT source, title, summary FROM intel_items
                WHERE importance_score >= 0.5
                AND created_at > NOW() - INTERVAL '48 hours'
                ORDER BY importance_score DESC LIMIT 3"""
            )
            if intel_rows:
                intel_context = "\n\n【直近の市場動向（投稿に活かせる素材）】\n"
                for r in intel_rows:
                    intel_context += f"- [{r['source']}] {r['title']}: {(r['summary'] or '')[:60]}\n"
    except Exception as e:
        logger.warning(f"content_multiplier intel取得失敗: {e}")

    # persona_memoryからDAICHIの文体・価値観を取得（接続#18修正）
    persona_hint = ""
    try:
        from tools.db_pool import get_connection as _get_conn_pm
        async with _get_conn_pm() as _conn_pm:
            pm_rows = await _conn_pm.fetch(
                """SELECT content FROM persona_memory
                WHERE category IN ('value', 'preference', 'writing_style', 'approval_pattern')
                ORDER BY created_at DESC LIMIT 5"""
            )
            if pm_rows:
                persona_hint = "\n\n【島原大知の人格・判断傾向】\n"
                for r in pm_rows:
                    persona_hint += f"- {(r['content'] or '')[:100]}\n"
    except Exception as e:
        logger.warning(f"content_multiplier persona取得失敗: {e}")

    # 事実誤認防止ルール（全プラットフォーム共通）
    factual_rules = (
        "\n【絶対禁止: 事実誤認】\n"
        "- 楽曲制作・音楽制作を仕事として語るな。島原大知は音楽の仕事をしていない。\n"
        "- SunoAIでの作詞は完全に個人の趣味。仕事・案件・クライアントとして語るな。\n"
        "- 島原大知の本業: 映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）、VTuber業界支援、事業運営。\n"
    )
    anti_ai += factual_rules

    model_sel = choose_best_model_v6(
        task_type="content", quality="medium", budget_sensitive=True, needs_japanese=True
    )

    # ===== 1. Bluesky投稿 5本 =====
    bluesky_result = await call_llm(
        prompt=f"""以下の記事から、Blueskyに投稿する独立した投稿を5本作ってください。

【記事タイトル】{source_title}
【記事本文（抜粋）】
{source_text[:2000]}
{intel_context}

各投稿の要件:
- 300文字以内
- 記事の異なる要点を1つずつ取り上げる
- 仮説共有スタイル、結論を固めすぎない
- 島原大知の人格が見える内容（VTuber8年×非エンジニア×AI事業OS）
- 問いかけを含める

JSONリスト形式で出力: ["投稿1", "投稿2", ...]""",
        system_prompt=f"SYUTAINβのBluesky投稿生成。\n{anti_ai}\n\n{strategy_id[:1000]}{persona_hint}",
        model_selection=model_sel,
    )
    bluesky_posts = _parse_list(bluesky_result.get("text", ""), 5)

    # ===== 2. X投稿 島原アカウント 3本 =====
    x_shimahara_result = await call_llm(
        prompt=f"""以下の記事から、島原大知のXアカウント（@Sima_daichi）用の投稿を3本作ってください。

【記事】{source_title}: {source_text[:1500]}
{intel_context}
要件:
- 140文字以内
- 一人称「僕」
- 感情・失敗・数字のいずれかのフックを入れる
- 共感を誘う内容
- 直近の市場動向があれば、自然に絡める

JSONリスト形式で出力: ["投稿1", "投稿2", "投稿3"]""",
        system_prompt=f"島原大知個人アカウントのX投稿生成。共感・人格・物語。\n{anti_ai[:1500]}{persona_hint}",
        model_selection=model_sel,
    )
    x_shimahara = _parse_list(x_shimahara_result.get("text", ""), 3)

    # ===== 3. X投稿 SYUTAINβアカウント 2本 =====
    x_syutain_result = await call_llm(
        prompt=f"""以下の記事から、SYUTAINβのXアカウント（@syutain_beta）用の投稿を2本作ってください。

【記事】{source_title}: {source_text[:1500]}
{intel_context}

要件:
- 140文字以内
- 一人称「私」
- 結論→根拠→示唆の構造
- 分析・構造のフック

JSONリスト形式で出力: ["投稿1", "投稿2"]""",
        system_prompt=f"SYUTAINβ公式X投稿生成。論理・設計・分析。\n{anti_ai[:1500]}",
        model_selection=model_sel,
    )
    x_syutain = _parse_list(x_syutain_result.get("text", ""), 2)

    # ===== 4. Threads投稿 3本 =====
    threads_result = await call_llm(
        prompt=f"""以下の記事から、Threadsに投稿する独立した投稿を3本作ってください。

【記事タイトル】{source_title}
【記事本文（抜粋）】
{source_text[:2000]}
{intel_context}
各投稿の要件:
- 500文字以内
- X(280文字)より詳しく。体験談ベースで深掘りする
- 記事の異なる要点を1つずつ取り上げる
- 問いかけを含めて対話を誘発する
- 島原大知の人格が見える内容

JSONリスト形式で出力: ["投稿1", "投稿2", "投稿3"]""",
        system_prompt=f"SYUTAINβのThreads投稿生成。体験談ベース、問いかけ多め。\n{anti_ai[:1500]}",
        model_selection=model_sel,
    )
    threads_posts = _parse_list(threads_result.get("text", ""), 3)

    # ===== 5. Booth商品説明（商品化可能な場合のみ） =====
    booth_result = await call_llm(
        prompt=f"""以下の記事を読んで、Booth入口商品（¥980）として商品化できるか判定してください。

【記事】{source_title}: {source_text[:1500]}

商品化可能な場合のみ、以下のJSON形式で出力:
{{"is_productizable": true, "product_title": "商品名", "description": "商品説明（200文字）", "price": 980, "target": "対象者"}}

商品化不可能な場合:
{{"is_productizable": false}}""",
        system_prompt="SYUTAINβの商品化判定エンジン。",
        model_selection=model_sel,
    )
    booth_data = _parse_json(booth_result.get("text", ""))
    booth_desc = None
    if booth_data and booth_data.get("is_productizable"):
        booth_desc = json.dumps(booth_data, ensure_ascii=False)

    # ===== 5. 次回note記事ネタ3案 =====
    note_ideas_result = await call_llm(
        prompt=f"""以下の記事の続きとして書ける、次回note記事のネタを3案出してください。

【記事】{source_title}: {source_text[:1500]}
{intel_context}

各ネタの要件:
- 具体的なタイトル案
- 想定読者
- 有料/無料の推奨

JSONリスト形式で出力: [{{"title": "...", "reader": "...", "paid": true/false}}, ...]""",
        system_prompt="SYUTAINβのnote記事企画エンジン。",
        model_selection=model_sel,
    )
    note_ideas = _parse_list_or_json(note_ideas_result.get("text", ""), 3)

    # ===== DB保存 & 承認キュー投入 =====
    result = {
        "bluesky": bluesky_posts,
        "x_shimahara": x_shimahara,
        "x_syutain": x_syutain,
        "threads": threads_posts,
        "booth_desc": booth_desc,
        "note_ideas": note_ideas,
        "total_count": len(bluesky_posts) + len(x_shimahara) + len(x_syutain) + len(threads_posts) + (1 if booth_desc else 0) + len(note_ideas),
        "source_title": source_title,
    }

    if submit_to_approval:
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                # Bluesky投稿を承認キューに投入
                for post in bluesky_posts:
                    await conn.execute(
                        """INSERT INTO approval_queue (request_type, request_data, status)
                        VALUES ('bluesky_post', $1, 'pending')""",
                        json.dumps({
                            "content": post[:300],
                            "platform": "bluesky",
                            "auto_generated": True,
                            "source": f"multiplied:{source_title}",
                        }, ensure_ascii=False),
                    )
                # Threads投稿を承認キューに投入
                for post in threads_posts:
                    await conn.execute(
                        """INSERT INTO approval_queue (request_type, request_data, status)
                        VALUES ('threads_post', $1, 'pending')""",
                        json.dumps({
                            "content": post[:500],
                            "platform": "threads",
                            "auto_generated": True,
                            "source": f"multiplied:{source_title}",
                        }, ensure_ascii=False),
                    )
                logger.info(f"content_multiplier: {result['total_count']}件生成, {len(bluesky_posts)+len(threads_posts)}件を承認キューに投入")
        except Exception as e:
            logger.error(f"content_multiplier DB保存エラー: {e}")

    # イベント記録
    try:
        from tools.event_logger import log_event
        await log_event("content.multiplied", "content", {
            "source_title": source_title,
            "source_type": source_type,
            "bluesky_count": len(bluesky_posts),
            "x_shimahara_count": len(x_shimahara),
            "x_syutain_count": len(x_syutain),
            "threads_count": len(threads_posts),
            "booth_productizable": booth_desc is not None,
            "note_ideas_count": len(note_ideas),
            "total_count": result["total_count"],
        })
    except Exception:
        pass

    return result


def _parse_list(text: str, expected: int) -> list:
    """LLM出力からJSONリストをパース"""
    import re
    text = text.strip()
    # ```json ... ``` のフェンスを除去
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(item) for item in data[:expected]]
    except json.JSONDecodeError:
        pass

    # フォールバック: 改行区切りで分割
    lines = [l.strip().lstrip("- •").strip('"\'') for l in text.split("\n") if l.strip() and len(l.strip()) > 10]
    return lines[:expected]


def _parse_json(text: str) -> Optional[dict]:
    """LLM出力からJSONオブジェクトをパース"""
    import re
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _parse_list_or_json(text: str, expected: int) -> list:
    """LLM出力からリスト（文字列 or dict）をパース"""
    import re
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data[:expected]
    except json.JSONDecodeError:
        pass
    return _parse_list(text, expected)
