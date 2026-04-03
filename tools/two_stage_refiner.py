"""
SYUTAINβ V25 2段階精錬パイプライン
設計書 第13章 13.2 準拠

Step 1: ローカルLLM（BRAVO/CHARLIE並列、choose_best_model_v6で選定）で荒原稿生成
Step 2: 品質チェック（ローカルLLMで自動採点、choose_best_model_v6で選定）
  - 品質OK（スコア0.7以上）→ そのまま使用（コスト¥0）
  - 品質NG → choose_best_model_v6でAPI精錬（モデルは状況に応じて動的選定）
"""

import asyncio
import logging
from typing import Optional

from tools.llm_router import call_llm, choose_best_model_v6, update_node_load

logger = logging.getLogger("syutain.refiner")

# 品質閾値
QUALITY_THRESHOLD = 0.7

# 品質チェックプロンプト
QUALITY_CHECK_PROMPT = """以下のテキストの品質を0.0〜1.0のスコアで評価してください。
評価基準:
- 論理性と一貫性 (0.3)
- 日本語の自然さ (0.3)
- 情報の正確性・有用性 (0.2)
- 読みやすさ・構成 (0.2)

最初の行にスコアだけを出力してください（例: 0.85）
2行目以降に簡潔な理由を書いてください。

評価対象テキスト:
---
{text}
---"""


async def two_stage_refine(
    prompt: str,
    system_prompt: str = "",
    task_type: str = "content",
    quality: str = "medium",
    parallel: bool = True,
) -> dict:
    """
    2段階精錬パイプライン

    Args:
        prompt: 生成プロンプト
        system_prompt: システムプロンプト
        task_type: タスク種別
        quality: 要求品質
        parallel: BRAVO/CHARLIE並列生成を有効化

    Returns:
        dict: {text, quality_score, refined, model_used, cost_jpy, stages}
    """
    stages = []

    try:
        # ===== Stage 1: ローカルLLMで荒原稿生成 =====
        if parallel:
            drafts = await _parallel_draft(prompt, system_prompt)
        else:
            drafts = [await _single_draft(prompt, system_prompt)]
    except Exception as e:
        logger.error(f"Stage 1 ローカル生成エラー: {e}")
        drafts = []

    if not drafts or all(d.get("error") for d in drafts):
        logger.warning("Stage 1: ローカル生成失敗、APIフォールバック")
        return await _api_fallback(prompt, system_prompt, task_type, quality)

    # エラーなしのドラフトのみ
    valid_drafts = [d for d in drafts if not d.get("error") and d.get("text")]
    if not valid_drafts:
        return await _api_fallback(prompt, system_prompt, task_type, quality)

    stages.append({
        "stage": 1,
        "action": "local_draft",
        "draft_count": len(valid_drafts),
        "nodes": [d.get("node", "unknown") for d in valid_drafts],
    })

    # ===== Stage 2: DELTAで品質チェック =====
    best_draft = None
    best_score = 0.0

    for draft in valid_drafts:
        score = await _quality_check(draft["text"])
        if score > best_score:
            best_score = score
            best_draft = draft

    stages.append({
        "stage": 2,
        "action": "quality_check",
        "best_score": best_score,
        "threshold": QUALITY_THRESHOLD,
    })

    # 品質OK → そのまま使用（コスト¥0）
    if best_score >= QUALITY_THRESHOLD:
        logger.info(f"2段階精錬: 品質OK（{best_score:.2f}）、ローカルのみで完了")
        return {
            "text": best_draft["text"],
            "quality_score": best_score,
            "refined": False,
            "model_used": best_draft.get("model_used", "local"),
            "cost_jpy": 0.0,
            "stages": stages,
        }

    # 品質NG → API精錬
    logger.info(f"2段階精錬: 品質NG（{best_score:.2f}）、API精錬実行")
    refined = await _api_refine(best_draft["text"], prompt, system_prompt, task_type, quality)
    stages.append({
        "stage": 3,
        "action": "api_refine",
        "model": refined.get("model_used", "unknown"),
    })

    # API精錬後の品質を再評価
    refined_text = refined.get("text", best_draft["text"])
    refined_score = best_score
    try:
        refined_score = await _quality_check(refined_text)
        stages.append({"stage": 4, "action": "re_evaluate", "score": refined_score})
        logger.info(f"2段階精錬: 再評価スコア {best_score:.2f} → {refined_score:.2f}")
    except Exception as e:
        logger.warning(f"2段階精錬: 再評価失敗（元スコア維持）: {e}")

    return {
        "text": refined_text,
        "quality_score": max(best_score, refined_score),
        "refined": True,
        "model_used": refined.get("model_used", "unknown"),
        "cost_jpy": refined.get("cost_jpy", 0.0),
        "stages": stages,
    }


async def _parallel_draft(prompt: str, system_prompt: str) -> list:
    """BRAVO/CHARLIE並列で荒原稿生成（V25: 最大3台）"""
    from tools.node_manager import get_node_manager

    # ルータに任せてノード+モデルの整合性を保つ（2並列で別ノードが選ばれることを期待）
    sel_1 = choose_best_model_v6(task_type="drafting", local_available=True)
    sel_2 = choose_best_model_v6(task_type="drafting", local_available=True)

    tasks = [
        call_llm(prompt, system_prompt, model_selection=sel_1),
        call_llm(prompt, system_prompt, model_selection=sel_2),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    drafts = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"並列ドラフト生成エラー ({['bravo', 'charlie'][i]}): {r}")
            drafts.append({"error": str(r)})
        else:
            drafts.append(r)

    return drafts


async def _single_draft(prompt: str, system_prompt: str) -> dict:
    """単一ノードで荒原稿生成"""
    selection = choose_best_model_v6(task_type="drafting")
    return await call_llm(prompt, system_prompt, model_selection=selection)


async def _quality_check(text: str) -> float:
    """品質チェック（ローカルLLM優先、動的選定）"""
    delta_sel = choose_best_model_v6(
        task_type="classification", quality="low",
        budget_sensitive=True, local_available=True,
    )

    try:
        check_prompt = QUALITY_CHECK_PROMPT.format(text=text[:3000])
        result = await call_llm(check_prompt, model_selection=delta_sel)
        response_text = result.get("text", "0.5")
        # 最初の行からスコアを抽出
        first_line = response_text.strip().split("\n")[0].strip()
        score = float(first_line)
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning(f"品質チェックエラー: {e}")
        return 0.5  # エラー時はデフォルトスコア


async def _api_refine(draft: str, original_prompt: str, system_prompt: str,
                      task_type: str, quality: str) -> dict:
    """API精錬（品質NG時のフォールバック）"""
    refine_prompt = f"""以下の荒原稿を高品質に精錬してください。

元の指示: {original_prompt}

荒原稿:
---
{draft}
---

精錬のポイント:
- 論理の飛躍を修正
- 日本語を自然にする
- 冗長な表現を削除
- 構成を改善"""

    # ルーターに委譲: task_type + quality で最適モデルを選定
    selection = choose_best_model_v6(
        task_type=task_type, quality=quality,
        local_available=False,  # API精錬なのでローカルは除外
    )

    return await call_llm(refine_prompt, system_prompt, model_selection=selection)


async def _api_fallback(prompt: str, system_prompt: str,
                        task_type: str, quality: str) -> dict:
    """ローカルLLM全滅時のAPIフォールバック"""
    logger.warning("ローカルLLM全滅、APIフォールバック")
    selection = choose_best_model_v6(
        task_type=task_type, quality=quality, local_available=False,
    )
    result = await call_llm(prompt, system_prompt, model_selection=selection)
    return {
        "text": result.get("text", ""),
        "quality_score": 0.0,
        "refined": True,
        "model_used": result.get("model_used", "unknown"),
        "cost_jpy": result.get("cost_jpy", 0.0),
        "stages": [{"stage": 1, "action": "api_fallback"}],
    }
