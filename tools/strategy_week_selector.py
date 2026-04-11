"""
Week N→Week N+1 自動選定ループ

拡散実行書 第8部「Week 2以降のガイドライン」を自動化する。

ループ:
1. 前週の全投稿(shimahara/syutain)のエンゲージメントを集計
2. トップ3投稿を選出
3. LLMでそれらが読者に与えた「感情軸」を特定
4. 同じ感情を起こす別の素材を intel_items / failure_memory / article_seeds から選定
5. 翌週7日分(Day N+1〜N+7)のX投稿スクリプトをLLMに生成させる
6. strategy_plan_items に Day N+1〜N+7 として登録(status=pending)
7. 翌朝以降 strategy_plan_execution が順次投下

島原さん方針(2026-04-11): 完全自動実行優先、承認不要。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tools.db_pool import get_connection
from tools.llm_router import call_llm, choose_best_model_v6

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _engagement_score(likes: int, reposts: int, replies: int, impressions: int) -> float:
    """投稿のエンゲージメントスコア"""
    return likes * 3 + reposts * 2 + replies * 5 + impressions * 0.01


async def _get_top_posts(days: int = 7, top_n: int = 3) -> list[dict]:
    """直近daysのshimahara/syutain投稿からエンゲージメント上位top_nを取得"""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT pq.id, pq.platform, pq.account, pq.content, pq.created_at,
                      COALESCE(pqe.likes, 0) AS likes,
                      COALESCE(pqe.reposts, 0) AS reposts,
                      COALESCE(pqe.replies, 0) AS replies,
                      COALESCE(pqe.impressions, 0) AS impressions
               FROM posting_queue pq
               LEFT JOIN posting_queue_engagement pqe ON pqe.posting_queue_id = pq.id
               WHERE pq.status = 'posted'
                 AND pq.account IN ('shimahara', 'syutain')
                 AND pq.created_at > NOW() - make_interval(days => $1)
               ORDER BY pq.created_at DESC""",
            days,
        )

    scored = []
    for r in rows:
        score = _engagement_score(r["likes"], r["reposts"], r["replies"], r["impressions"])
        scored.append({**dict(r), "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


async def _get_candidate_materials(limit: int = 20) -> dict[str, list[dict]]:
    """素材プール: intel_items / failure_memory / article_seeds から直近の候補を取得"""
    result: dict[str, list[dict]] = {"intel": [], "failure": [], "seeds": []}

    async with get_connection() as conn:
        try:
            intel = await conn.fetch(
                """SELECT id, source, title, summary, importance_score, created_at
                   FROM intel_items
                   WHERE created_at > NOW() - INTERVAL '14 days'
                     AND importance_score >= 0.5
                   ORDER BY importance_score DESC, created_at DESC
                   LIMIT $1""",
                limit,
            )
            result["intel"] = [dict(r) for r in intel]
        except Exception as e:
            logger.warning(f"intel_items取得失敗: {e}")

        try:
            failure = await conn.fetch(
                """SELECT id, failure_type, context, resolution, created_at
                   FROM failure_memory
                   WHERE created_at > NOW() - INTERVAL '14 days'
                   ORDER BY created_at DESC
                   LIMIT $1""",
                limit,
            )
            result["failure"] = [dict(r) for r in failure]
        except Exception as e:
            logger.warning(f"failure_memory取得失敗: {e}")

        try:
            seeds = await conn.fetch(
                """SELECT id, title, layer, seed_text, angle, maturity_score, status
                   FROM article_seeds
                   WHERE status = 'germinating' AND maturity_score >= 0.3
                   ORDER BY maturity_score DESC
                   LIMIT $1""",
                limit,
            )
            result["seeds"] = [dict(r) for r in seeds]
        except Exception as e:
            logger.warning(f"article_seeds取得失敗: {e}")

    return result


def _format_top_posts(posts: list[dict]) -> str:
    lines = []
    for i, p in enumerate(posts, 1):
        lines.append(
            f"[#{i}] ({p['account']}/{p['platform']}, "
            f"imp={p['impressions']}, likes={p['likes']}, reposts={p['reposts']}, replies={p['replies']})\n"
            f"{p['content'][:200]}"
        )
    return "\n\n".join(lines)


def _format_materials(materials: dict) -> str:
    lines = ["## intel_items (外部情報)"]
    for m in materials["intel"][:10]:
        lines.append(f"- [{m['source']}] {m.get('title', '')[:80]}: {(m.get('summary') or '')[:120]}")
    lines.append("\n## failure_memory (失敗記録)")
    for m in materials["failure"][:10]:
        lines.append(f"- [{m['failure_type']}] {(m.get('context') or '')[:100]} → {(m.get('resolution') or '未解決')[:60]}")
    lines.append("\n## article_seeds (記事ネタ)")
    for m in materials["seeds"][:10]:
        lines.append(f"- [{m['layer']}] {m.get('title', '')[:80]}: {(m.get('seed_text') or '')[:120]}")
    return "\n".join(lines)


_WEEK_SELECT_SYSTEM = """あなたはSYUTAINβ拡散戦略のエンゲージメント分析官兼コンテンツ企画担当です。
前週のトップ3投稿が読者に与えた「感情軸」を特定し、同じ感情を起こす別の素材を選び、
翌週7日分のX投稿スクリプトを作成してください。

原則:
- 型の再利用は禁止。同じ感情を起こす「別の角度」を探す
- 各投稿は150字以内(X制約)
- 抽象論・ポエム調・「AIすごい」は禁止
- 具体的な数字・事件・体験だけを使う
- shimaharaアカウント視点(島原大知=映像制作15年、VTuber 8年、非エンジニア、4台PC運用者)
- 各日の末尾に`[SYUTAINβ auto-generated]`タグを付けない(後工程で自動付与される)

出力: JSONのみ。説明文・前置きなし。
"""

_WEEK_SELECT_USER_TEMPLATE = """# 前週トップ3投稿
{top_posts}

# 選択可能な素材プール
{materials}

# タスク
1. 上記トップ3が読者に与えた「感情軸」を1文で特定せよ(例: AIが現実を勝手に補完する面白さと怖さ)
2. その感情を起こす別の素材を素材プールから5〜7件選定せよ
3. 選定した素材を使って翌週7日分のX投稿スクリプトを作成せよ

# 出力形式(JSONのみ)
{{
  "emotion_axis": "...",
  "selected_materials": ["...", "..."],
  "week_plan": [
    {{"day_offset": 1, "label": "...", "content": "..."}},
    {{"day_offset": 2, "label": "...", "content": "..."}},
    {{"day_offset": 3, "label": "...", "content": "..."}},
    {{"day_offset": 4, "label": "...", "content": "..."}},
    {{"day_offset": 5, "label": "...", "content": "..."}},
    {{"day_offset": 6, "label": "...", "content": "..."}},
    {{"day_offset": 7, "label": "...", "content": "..."}}
  ]
}}"""


async def _select_next_week_with_llm(
    top_posts: list[dict],
    materials: dict,
) -> dict | None:
    """LLM呼び出し: 感情軸特定 → 素材選定 → 翌週7日分生成"""
    if not top_posts:
        logger.warning("strategy_week_selector: トップ投稿ゼロ、LLM呼び出しスキップ")
        return None

    user_prompt = _WEEK_SELECT_USER_TEMPLATE.format(
        top_posts=_format_top_posts(top_posts),
        materials=_format_materials(materials),
    )

    sel = choose_best_model_v6(
        task_type="strategy",
        quality="high",
        needs_japanese=True,
        intelligence_required=7,
    )
    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=_WEEK_SELECT_SYSTEM,
            model_selection=sel,
            temperature=0.8,
            use_cache=False,
        )
    except Exception as e:
        logger.error(f"strategy_week_selector: LLM呼び出し失敗: {e}")
        return None

    raw = (result.get("text") or result.get("content") or "").strip()
    # JSON抽出: ```json ``` フェンスがあれば剥がす
    if "```" in raw:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
    try:
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"strategy_week_selector: LLM出力JSON解析失敗: {e} raw={raw[:500]}")
        return None

    if not isinstance(parsed, dict) or "week_plan" not in parsed:
        logger.error(f"strategy_week_selector: 不正なLLM出力構造: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
        return None

    return parsed


async def _insert_next_week_items(
    plan: dict,
    base_day_number: int,
    base_date: date,
) -> int:
    """LLM生成結果を strategy_plan_items に挿入。挿入件数を返す"""
    inserted = 0
    async with get_connection() as conn:
        for entry in plan.get("week_plan", []):
            try:
                offset = int(entry.get("day_offset") or 0)
                if offset < 1 or offset > 7:
                    continue
                day_num = base_day_number + offset
                day_date = base_date + timedelta(days=offset - 1)
                content = (entry.get("content") or "").strip()
                label = (entry.get("label") or f"Week{(day_num - 1) // 7 + 1} Day{offset}").strip()
                if not content or len(content) < 20:
                    continue

                meta = {
                    "dynamic_values": False,
                    "auto_generated_from": "strategy_week_selector",
                    "emotion_axis": plan.get("emotion_axis", ""),
                    "selected_materials_sample": (plan.get("selected_materials") or [])[:3],
                }

                # 重複チェック(同じdayに既にエントリがあればスキップ)
                exists = await conn.fetchval(
                    """SELECT id FROM strategy_plan_items
                       WHERE plan_source = 'diffusion_execution_plan'
                         AND day_number = $1 AND item_type = 'x_post'""",
                    day_num,
                )
                if exists:
                    logger.debug(
                        f"strategy_week_selector: Day{day_num} 既存のためスキップ id={exists}"
                    )
                    continue

                await conn.execute(
                    """INSERT INTO strategy_plan_items
                       (plan_source, day_number, day_date, day_label, item_type,
                        platform, account, title, content, metadata, status)
                       VALUES ('diffusion_execution_plan', $1, $2, $3, 'x_post',
                               'x', 'shimahara', NULL, $4, $5::jsonb, 'pending')""",
                    day_num, day_date, label, content,
                    json.dumps(meta, ensure_ascii=False),
                )
                inserted += 1
                logger.info(
                    f"strategy_week_selector: Day{day_num} ({day_date}) 挿入 label={label}"
                )
            except Exception as e:
                logger.warning(f"strategy_week_selector: entry挿入失敗: {e}")

    return inserted


async def select_next_week() -> dict:
    """次週の戦略アイテムを自動生成・登録するメインエントリ"""
    stats = {
        "top_posts_analyzed": 0,
        "materials_considered": 0,
        "llm_called": False,
        "items_inserted": 0,
        "emotion_axis": "",
    }

    # 現在の最大day_numberを取得(次の週の起点)
    async with get_connection() as conn:
        max_day = await conn.fetchval(
            "SELECT COALESCE(MAX(day_number), 0) FROM strategy_plan_items WHERE plan_source='diffusion_execution_plan'"
        )
    base_day_number = int(max_day or 0)
    if base_day_number < 7:
        logger.info(f"strategy_week_selector: Week 1未完了(max_day={base_day_number})、選定スキップ")
        return stats

    # 次週の起点日は max_day の翌日
    from tools.strategy_plan_parser import _day_date
    base_date = _day_date(base_day_number) + timedelta(days=1)

    # 1. トップ投稿取得
    top_posts = await _get_top_posts(days=7, top_n=3)
    stats["top_posts_analyzed"] = len(top_posts)

    # 2. 素材プール取得
    materials = await _get_candidate_materials(limit=20)
    stats["materials_considered"] = (
        len(materials["intel"]) + len(materials["failure"]) + len(materials["seeds"])
    )

    # 3. LLM 選定
    plan = await _select_next_week_with_llm(top_posts, materials)
    stats["llm_called"] = True
    if not plan:
        return stats

    stats["emotion_axis"] = plan.get("emotion_axis", "")

    # 4. 挿入
    inserted = await _insert_next_week_items(plan, base_day_number, base_date)
    stats["items_inserted"] = inserted

    logger.info(f"strategy_week_selector: 完了 {stats}")
    return stats
