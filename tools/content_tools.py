"""
SYUTAINβ V25 コンテンツツール (Step 18)
設計書準拠

note.com下書き生成、Booth商品説明生成。
2段階精錬パイプライン使用（CLAUDE.mdルール6）。
"""

import os
import logging
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.content_tools")


# ===== note.com 記事生成 =====

async def generate_note_draft(
    topic: str,
    target_audience: str = "",
    tone: str = "informative",
    length: str = "medium",
    strategy_context: Optional[dict] = None,
) -> dict:
    """
    note.com記事の下書きを2段階精錬で生成

    Args:
        topic: 記事テーマ
        target_audience: ターゲット読者（ICP準拠）
        tone: トーン (informative / casual / professional / storytelling)
        length: 記事長 (short=1000字 / medium=2000字 / long=4000字)
        strategy_context: 戦略ファイルからのコンテキスト

    Returns:
        {"title": str, "body": str, "tags": [...], "quality_score": float, ...}
    """
    # 戦略ファイル参照（CLAUDE.mdルール10）
    if strategy_context is None:
        try:
            from tools.analytics_tools import load_strategy_context
            strategy_context = load_strategy_context()
        except Exception as e:
            logger.warning(f"戦略コンテキスト読み込み失敗: {e}")
            strategy_context = {}

    length_chars = {"short": 1000, "medium": 2000, "long": 4000}.get(length, 2000)

    icp_info = strategy_context.get("icp", "")
    channel_info = strategy_context.get("channel", "")

    system_prompt = f"""あなたはSYUTAINβのコンテンツライターです。
note.comに投稿する質の高い日本語記事を執筆してください。

ターゲット読者: {target_audience or icp_info or '個人開発者・AI活用に興味がある人'}
トーン: {tone}
文字数目安: {length_chars}文字

記事構成:
1. タイトル（30文字以内、興味を引く）
2. リード文（3行以内で要点を伝える）
3. 本文（見出し付き、具体例を含む）
4. まとめ
5. タグ候補（5個）

出力形式:
TITLE: (タイトル)
TAGS: (タグ1, タグ2, ...)
---
(本文)"""

    prompt = f"テーマ: {topic}"

    # 2段階精錬パイプライン使用（CLAUDE.mdルール6）
    try:
        from tools.two_stage_refiner import two_stage_refine
        result = await two_stage_refine(
            prompt=prompt,
            system_prompt=system_prompt,
            task_type="note_article",
            quality="medium",
        )
        text = result.get("text", "")
    except Exception as e:
        logger.error(f"2段階精錬失敗: {e}")
        # フォールバック: 直接LLM呼び出し
        try:
            from tools.llm_router import call_llm, choose_best_model_v6
            selection = choose_best_model_v6(task_type="content", needs_japanese=True)
            llm_result = await call_llm(prompt, system_prompt, model_selection=selection)
            text = llm_result.get("text", "")
            result = {"text": text, "quality_score": 0.0, "refined": False, "stages": []}
        except Exception as e2:
            logger.error(f"LLMフォールバックも失敗: {e2}")
            return {"title": "", "body": "", "tags": [], "error": str(e2)}

    # テキストからタイトル・タグ・本文を分離
    parsed = _parse_note_output(text)

    return {
        "title": parsed["title"],
        "body": parsed["body"],
        "tags": parsed["tags"],
        "quality_score": result.get("quality_score", 0.0),
        "refined": result.get("refined", False),
        "model_used": result.get("model_used", "unknown"),
        "stages": result.get("stages", []),
    }


def _parse_note_output(text: str) -> dict:
    """LLM出力からnote記事の構成要素を分離"""
    title = ""
    tags = []
    body = text

    lines = text.split("\n")
    body_start = 0

    for i, line in enumerate(lines):
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
            body_start = i + 1
        elif line.startswith("TAGS:"):
            tags_str = line.replace("TAGS:", "").strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()]
            body_start = i + 1
        elif line.strip() == "---":
            body_start = i + 1
            break

    body = "\n".join(lines[body_start:]).strip()
    return {"title": title, "body": body, "tags": tags}


# ===== Booth 商品説明生成 =====

async def generate_booth_description(
    product_name: str,
    product_type: str = "digital",
    features: Optional[list] = None,
    price_jpy: int = 0,
    strategy_context: Optional[dict] = None,
) -> dict:
    """
    Booth商品説明を2段階精錬で生成

    Args:
        product_name: 商品名
        product_type: 商品種別 (digital / physical / service)
        features: 特徴リスト
        price_jpy: 価格（参考）
        strategy_context: 戦略コンテキスト

    Returns:
        {"description": str, "short_description": str, "quality_score": float, ...}
    """
    if strategy_context is None:
        try:
            from tools.analytics_tools import load_strategy_context
            strategy_context = load_strategy_context()
        except Exception:
            strategy_context = {}

    features_text = "\n".join(f"- {f}" for f in (features or []))

    system_prompt = f"""あなたはSYUTAINβの商品コピーライターです。
Boothで販売するデジタル商品の魅力的な説明文を作成してください。

ターゲット: {strategy_context.get('icp', '個人開発者・クリエイター')}

出力形式:
SHORT: (一行説明・50文字以内)
---
(詳細説明・500-1000文字)"""

    prompt = f"""商品名: {product_name}
種別: {product_type}
{f'特徴:{chr(10)}{features_text}' if features_text else ''}
{f'参考価格: {price_jpy}円' if price_jpy else ''}"""

    try:
        from tools.two_stage_refiner import two_stage_refine
        result = await two_stage_refine(
            prompt=prompt,
            system_prompt=system_prompt,
            task_type="product_desc",
            quality="medium",
        )
        text = result.get("text", "")
    except Exception as e:
        logger.error(f"Booth説明生成失敗: {e}")
        return {"description": "", "short_description": "", "error": str(e)}

    # 出力パース
    short_desc = ""
    full_desc = text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("SHORT:"):
            short_desc = line.replace("SHORT:", "").strip()
        elif line.strip() == "---":
            full_desc = "\n".join(lines[i + 1:]).strip()
            break

    return {
        "description": full_desc,
        "short_description": short_desc,
        "quality_score": result.get("quality_score", 0.0),
        "refined": result.get("refined", False),
        "model_used": result.get("model_used", "unknown"),
    }


# ===== 汎用コンテンツ生成 =====

async def generate_content(
    content_type: str,
    prompt: str,
    quality: str = "medium",
    **kwargs,
) -> dict:
    """汎用コンテンツ生成（2段階精錬）"""
    try:
        from tools.two_stage_refiner import two_stage_refine
        return await two_stage_refine(
            prompt=prompt,
            task_type=content_type,
            quality=quality,
        )
    except Exception as e:
        logger.error(f"コンテンツ生成失敗 ({content_type}): {e}")
        return {"text": "", "error": str(e)}
