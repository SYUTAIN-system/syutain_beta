"""
SYUTAINβ 多段コンテンツ生成パイプライン
5段階で商品化可能なコンテンツを生成する。

Stage 1: ネタ選定 (intel_items + persona_memory → テーマ)
Stage 2: 構成案 (テーマ → Phase A-E骨組み)
Stage 3: 初稿 (構成案 → 本文)
Stage 4: リライト (初稿 → 島原の声で書き直し)
Stage 5: 品質検証 (多軸評価)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from brain_alpha.sns_batch import _score_multi_axis, _PERSONA_KEYWORDS

logger = logging.getLogger("syutain.brain_alpha.content_pipeline")

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"


def _load_content_patterns() -> str:
    """strategy/daichi_content_patterns.md を読み込む"""
    path = STRATEGY_DIR / "daichi_content_patterns.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _load_writing_style() -> str:
    """strategy/daichi_writing_style.md を読み込む"""
    path = STRATEGY_DIR / "daichi_writing_style.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


async def _load_few_shot_examples(conn) -> list[str]:
    """daichi_writing_examples から long_article カテゴリの例を取得"""
    try:
        rows = await conn.fetch(
            """SELECT tweet_text FROM daichi_writing_examples
            WHERE theme_category = 'long_article'
            AND is_high_quality = true
            ORDER BY engagement_score DESC LIMIT 5"""
        )
        return [r["tweet_text"] for r in rows if r["tweet_text"]]
    except Exception as e:
        logger.warning(f"few-shot例取得失敗: {e}")
        return []


async def _load_persona(conn) -> str:
    """persona_memory から哲学・アイデンティティを取得（最大10件）"""
    try:
        rows = await conn.fetch(
            """SELECT content FROM persona_memory
            WHERE category IN ('philosophy', 'identity')
            ORDER BY created_at DESC LIMIT 10"""
        )
        if not rows:
            return ""
        lines = [f"- {(r['content'] or '')[:120]}" for r in rows]
        return "【島原大知の価値観（persona_memory）】\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"persona_memory取得失敗: {e}")
        return ""


async def _load_intel_themes(conn) -> list[str]:
    """intel_items から最近のテーマ候補を取得"""
    try:
        rows = await conn.fetch(
            """SELECT title, summary FROM intel_items
            WHERE created_at > NOW() - INTERVAL '3 days'
            AND status = 'reviewed'
            ORDER BY relevance_score DESC LIMIT 10"""
        )
        return [f"{r['title']}: {(r['summary'] or '')[:80]}" for r in rows if r["title"]]
    except Exception as e:
        logger.warning(f"intel_items取得失敗: {e}")
        return []


# ===== 5段パイプライン =====


async def generate_publishable_content(
    theme: str = None,
    content_type: str = "note_article",
    target_length: int = 3000,
) -> dict:
    """
    5段階パイプラインでコンテンツを生成する。

    Returns:
        dict: title, content, quality_score, stages, metadata
    """
    task_id = str(uuid4())
    stages = []
    content_patterns = _load_content_patterns()
    writing_style = _load_writing_style()

    async with get_connection() as conn:
        few_shot_examples = await _load_few_shot_examples(conn)
        persona_text = await _load_persona(conn)

        # ===== Stage 1: ネタ選定 =====
        if theme:
            selected_theme = theme
            stages.append({
                "stage": 1,
                "name": "ネタ選定",
                "status": "skipped",
                "detail": f"テーマ指定済み: {theme}",
            })
        else:
            try:
                intel_themes = await _load_intel_themes(conn)
                intel_context = "\n".join(f"- {t}" for t in intel_themes) if intel_themes else "（最近のインテル情報なし）"

                model_sel = choose_best_model_v6(
                    task_type="analysis", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )
                result = await call_llm(
                    prompt=(
                        "以下のインテル情報と島原大知のペルソナを踏まえ、"
                        "note記事として最も読者に刺さるテーマを1つだけ提案してください。\n"
                        "テーマ名のみを1行で出力。説明不要。\n\n"
                        f"## 最近のインテル情報\n{intel_context}\n\n"
                        f"## ペルソナ\n{persona_text}\n"
                    ),
                    system_prompt=(
                        "島原大知のコンテンツテーマ選定アシスタント。\n"
                        "テーマ軸: AI×クリエイター / 設計思想×実体験 / VTuber業界×未来予測 / "
                        "人間の価値×AI時代 / SYUTAINβ構築記録 / 不可能性の哲学\n"
                        "テーマ名のみを1行で出力。"
                    ),
                    model_selection=model_sel,
                )
                selected_theme = result.get("text", "").strip()
                if not selected_theme:
                    selected_theme = "AI時代における人間の価値"
                stages.append({
                    "stage": 1,
                    "name": "ネタ選定",
                    "status": "success",
                    "model": model_sel.get("model", "unknown"),
                    "detail": selected_theme,
                })
            except Exception as e:
                logger.error(f"Stage 1 失敗: {e}")
                selected_theme = "AI時代における人間の価値"
                stages.append({
                    "stage": 1,
                    "name": "ネタ選定",
                    "status": "fallback",
                    "detail": f"エラー({e})、デフォルトテーマ使用",
                })

        # ===== Stage 2: 構成案（Phase A-E） =====
        try:
            model_sel_outline = choose_best_model_v6(
                task_type="drafting", quality="medium",
                budget_sensitive=True, needs_japanese=True,
            )
            result_outline = await call_llm(
                prompt=(
                    f"テーマ「{selected_theme}」で{target_length}字程度のnote記事の構成案を作成してください。\n\n"
                    "以下の5フェーズ構成で骨組みを出力:\n"
                    "Phase A: 導入（個人の体験・感覚から入る。自己開示を含む）\n"
                    "Phase B: 転換（導入から本題への切り替え）\n"
                    "Phase C: 展開（体験→考察→哲学の往復を2-3回）\n"
                    "Phase D: 核心（太字で打ち込む一文）\n"
                    "Phase E: 結論（行動宣言で終わる）\n\n"
                    "各フェーズについて2-3行で具体的に何を書くか記述してください。\n"
                    f"\n{persona_text}"
                ),
                system_prompt=(
                    "島原大知のnote記事構成アシスタント。\n"
                    f"{content_patterns[:2000]}\n"
                ),
                model_selection=model_sel_outline,
            )
            outline = result_outline.get("text", "").strip()
            if not outline:
                raise ValueError("構成案が空")
            stages.append({
                "stage": 2,
                "name": "構成案",
                "status": "success",
                "model": model_sel_outline.get("model", "unknown"),
                "detail": outline[:300],
            })
        except Exception as e:
            logger.error(f"Stage 2 失敗: {e}")
            return {
                "title": selected_theme,
                "content": "",
                "quality_score": 0.0,
                "stages": stages + [{"stage": 2, "name": "構成案", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"Stage 2 失敗: {e}"},
            }

        # ===== Stage 3: 初稿 =====
        try:
            few_shot_text = ""
            if few_shot_examples:
                few_shot_text = "\n\n## 参考記事（島原大知の過去の文章）\n" + "\n---\n".join(
                    ex[:500] for ex in few_shot_examples[:3]
                )

            model_sel_draft = choose_best_model_v6(
                task_type="content_final", quality="high",
                budget_sensitive=True, needs_japanese=True,
            )
            result_draft = await call_llm(
                prompt=(
                    f"以下の構成案に基づき、{target_length}字程度のnote記事の初稿を書いてください。\n\n"
                    f"## テーマ\n{selected_theme}\n\n"
                    f"## 構成案\n{outline}\n\n"
                    "注意:\n"
                    "- 記事本文のみを出力。メタ情報や説明は不要。\n"
                    "- Phase A-Eの構成に忠実に従う。\n"
                    "- 島原大知の声で書く。AI臭い定型表現は禁止。\n"
                    f"{few_shot_text}"
                ),
                system_prompt=(
                    "あなたは島原大知としてnote記事を執筆する。\n\n"
                    f"{content_patterns[:3000]}\n\n"
                    f"{writing_style[:2000]}\n\n"
                    f"{persona_text}\n\n"
                    "記事本文のみを出力。タイトルも含めてよい。"
                ),
                model_selection=model_sel_draft,
            )
            first_draft = result_draft.get("text", "").strip()
            if not first_draft or len(first_draft) < 500:
                raise ValueError(f"初稿が短すぎる（{len(first_draft)}字）")
            stages.append({
                "stage": 3,
                "name": "初稿",
                "status": "success",
                "model": model_sel_draft.get("model", "unknown"),
                "detail": f"{len(first_draft)}字",
            })
        except Exception as e:
            logger.error(f"Stage 3 失敗: {e}")
            return {
                "title": selected_theme,
                "content": "",
                "quality_score": 0.0,
                "stages": stages + [{"stage": 3, "name": "初稿", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"Stage 3 失敗: {e}"},
            }

        # ===== Stage 4: リライト（島原の声で書き直し） =====
        rewrite_attempt = 0
        max_rewrite = 2
        rewritten = first_draft
        quality_score = 0.0

        while rewrite_attempt < max_rewrite:
            try:
                model_sel_rewrite = choose_best_model_v6(
                    task_type="quality_verification", quality="high",
                    budget_sensitive=True, needs_japanese=True,
                )
                rewrite_instruction = (
                    "以下の記事を島原大知の声でリライトしてください。\n\n"
                    "リライトの指針:\n"
                    "- 一人称は場面に応じて「私」「僕」「自分」を使い分ける\n"
                    "- 三点リーダー（…）で余韻を残す\n"
                    "- 段落は短く（1-3文で改行）\n"
                    "- 「正直」「だが」「でも」で逆接を多用\n"
                    "- 核心部分は**太字**で強調\n"
                    "- AI臭い定型表現は一切使わない\n"
                    "- 評論家的ではなく、行動宣言で終わる\n"
                    "- 記事本文のみを出力\n\n"
                    f"## 元原稿\n{rewritten}"
                )
                if rewrite_attempt > 0:
                    rewrite_instruction += (
                        "\n\n## 前回の品質スコア\n"
                        f"{quality_score:.3f}（0.75以上が目標）\n"
                        "より島原大知らしい文体に近づけてください。"
                    )

                result_rewrite = await call_llm(
                    prompt=rewrite_instruction,
                    system_prompt=(
                        "島原大知の文体でリライトするエディター。\n\n"
                        f"{writing_style[:2000]}\n\n"
                        f"{persona_text}\n\n"
                        "記事本文のみを出力。説明不要。"
                    ),
                    model_selection=model_sel_rewrite,
                )
                rewritten = result_rewrite.get("text", "").strip()
                if not rewritten or len(rewritten) < 500:
                    rewritten = first_draft
                    raise ValueError("リライト結果が短すぎる")

                # ===== Stage 5: 品質検証 =====
                quality_score = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)

                if quality_score >= 0.75:
                    stages.append({
                        "stage": 4,
                        "name": "リライト",
                        "status": "success",
                        "model": model_sel_rewrite.get("model", "unknown"),
                        "detail": f"attempt {rewrite_attempt + 1}, {len(rewritten)}字",
                    })
                    stages.append({
                        "stage": 5,
                        "name": "品質検証",
                        "status": "accepted",
                        "detail": f"score={quality_score:.3f} (>=0.75)",
                    })
                    break
                elif quality_score >= 0.50 and rewrite_attempt == 0:
                    # 0.50-0.74: Stage 4を1回リトライ
                    logger.info(f"品質スコア {quality_score:.3f} — リトライ")
                    rewrite_attempt += 1
                    continue
                else:
                    # < 0.50 または2回目の0.50-0.74
                    stages.append({
                        "stage": 4,
                        "name": "リライト",
                        "status": "completed",
                        "model": model_sel_rewrite.get("model", "unknown"),
                        "detail": f"attempt {rewrite_attempt + 1}, {len(rewritten)}字",
                    })
                    if quality_score < 0.50:
                        stages.append({
                            "stage": 5,
                            "name": "品質検証",
                            "status": "failed",
                            "detail": f"score={quality_score:.3f} (<0.50)",
                        })
                    else:
                        stages.append({
                            "stage": 5,
                            "name": "品質検証",
                            "status": "marginal",
                            "detail": f"score={quality_score:.3f} (0.50-0.74, リトライ済)",
                        })
                    break

            except Exception as e:
                logger.error(f"Stage 4 リライト失敗 (attempt {rewrite_attempt + 1}): {e}")
                stages.append({
                    "stage": 4,
                    "name": "リライト",
                    "status": "error",
                    "detail": str(e),
                })
                quality_score = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)
                stages.append({
                    "stage": 5,
                    "name": "品質検証",
                    "status": "fallback",
                    "detail": f"score={quality_score:.3f} (リライト失敗、初稿で評価)",
                })
                break

        # タイトル抽出（本文の最初の行を使用）
        lines = rewritten.strip().split("\n")
        title = lines[0].strip().lstrip("#").strip() if lines else selected_theme
        if len(title) > 100:
            title = title[:97] + "..."

        # 成功/失敗判定
        status = "success" if quality_score >= 0.50 else "failed"

        # tasksテーブルに保存
        output_data = {
            "title": title,
            "content": rewritten,
            "theme": selected_theme,
            "quality_score": quality_score,
            "stages": stages,
            "target_length": target_length,
            "actual_length": len(rewritten),
        }
        try:
            last_model = "unknown"
            for s in reversed(stages):
                if "model" in s:
                    last_model = s["model"]
                    break

            await conn.execute(
                """INSERT INTO tasks (id, goal_id, type, status, assigned_node, model_used, quality_score, output_data, created_at)
                VALUES ($1, 'content_pipeline', $2, $3, 'alpha', $4, $5, $6, NOW())""",
                task_id,
                content_type,
                status,
                last_model,
                quality_score,
                json.dumps(output_data, ensure_ascii=False, default=str),
            )
            logger.info(f"コンテンツ生成完了: task_id={task_id}, score={quality_score:.3f}, status={status}")
        except Exception as e:
            logger.error(f"tasks保存失敗: {e}")

    return {
        "title": title,
        "content": rewritten,
        "quality_score": quality_score,
        "stages": stages,
        "metadata": {
            "task_id": task_id,
            "content_type": content_type,
            "theme": selected_theme,
            "target_length": target_length,
            "actual_length": len(rewritten),
            "status": status,
        },
    }
