"""note記事素材コレクター — 5層ローテーションに応じた素材を事前収集

毎日07:00に実行。当日の地層に応じた素材をintel_items + note_materialsテーブルに蓄積。
記事生成時にcontent_pipelineが取り出して注入する。
"""

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.note_material_collector")

JST = timezone(timedelta(hours=9))

# 曜日→地層マッピング
LAYER_MAP = {
    0: "record",     # 月=週報(記録層)
    1: "incident",   # 火=事件層
    2: "intel",      # 水=情報層
    3: "knowledge",  # 木=知見層
    4: "incident",   # 金=事件層
    5: "intel",      # 土=情報層
    6: "philosophy", # 日=思想層
}


async def collect_materials_for_today() -> dict:
    """当日の地層に応じた素材を収集"""
    weekday = datetime.now(tz=JST).weekday()
    layer = LAYER_MAP.get(weekday, "incident")

    results = {"layer": layer, "materials": 0, "errors": []}

    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            if layer == "record":
                results["materials"] = await _collect_weekly_metrics(conn)
            elif layer == "incident":
                results["materials"] = await _collect_incidents(conn)
            elif layer == "intel":
                results["materials"] = await _collect_intel_materials(conn)
            elif layer == "knowledge":
                results["materials"] = await _collect_knowledge(conn)
            elif layer == "philosophy":
                results["materials"] = await _collect_philosophy(conn)
    except Exception as e:
        logger.error(f"素材収集失敗: {e}")
        results["errors"].append(str(e))

    logger.info(f"note素材収集完了: layer={layer}, materials={results['materials']}")
    return results


async def _save_material(conn, layer: str, title: str, content: str, source: str):
    """素材をintel_itemsに保存（note_materialソースとして）"""
    try:
        existing = await conn.fetchval(
            "SELECT id FROM intel_items WHERE title = $1 AND source = 'note_material' AND created_at > NOW() - INTERVAL '24 hours'",
            title,
        )
        if existing:
            return 0
        await conn.execute(
            """INSERT INTO intel_items (title, summary, source, category, review_flag, importance_score, metadata)
               VALUES ($1, $2, 'note_material', $3, 'actionable', 8, $4)""",
            title, content, f"note_{layer}",
            json.dumps({"layer": layer, "for_date": datetime.now(tz=JST).strftime("%Y-%m-%d")}, ensure_ascii=False),
        )
        return 1
    except Exception as e:
        logger.warning(f"素材保存失敗: {e}")
        return 0


async def _collect_weekly_metrics(conn) -> int:
    """記録層: 週次メトリクスを収集"""
    count = 0
    try:
        # LLM使用統計
        row = await conn.fetchrow(
            """SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost,
               COUNT(DISTINCT model) AS models
            FROM llm_usage_log WHERE created_at > NOW() - INTERVAL '7 days'"""
        )
        if row:
            count += await _save_material(conn, "record",
                f"週次LLM統計: {row['calls']}回呼出, ${row['cost']:.2f}, {row['models']}モデル",
                f"直近7日間のLLM呼び出し: {row['calls']}回, コスト${row['cost']:.4f}, 使用モデル数{row['models']}",
                "note_material")

        # SNS統計
        sns = await conn.fetchrow(
            """SELECT COUNT(*) AS posted,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed
            FROM posting_queue WHERE created_at > NOW() - INTERVAL '7 days'"""
        )
        if sns:
            count += await _save_material(conn, "record",
                f"週次SNS統計: 投稿{sns['posted']}件, 失敗{sns['failed']}件",
                f"直近7日間SNS: 投稿{sns['posted']}件, 失敗{sns['failed']}件",
                "note_material")

        # 記事統計
        articles = await conn.fetchrow(
            """SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'published') AS published
            FROM product_packages WHERE platform = 'note' AND created_at > NOW() - INTERVAL '7 days'"""
        )
        if articles:
            count += await _save_material(conn, "record",
                f"週次記事統計: 生成{articles['total']}件, 公開{articles['published']}件",
                f"note記事: 生成{articles['total']}件, 公開{articles['published']}件",
                "note_material")

    except Exception as e:
        logger.warning(f"週次メトリクス収集失敗: {e}")
    return count


async def _collect_incidents(conn) -> int:
    """事件層: 直近のエラー・異常・修正イベントを収集"""
    count = 0
    try:
        events = await conn.fetch(
            """SELECT event_type, category, detail, created_at
            FROM event_log
            WHERE created_at > NOW() - INTERVAL '48 hours'
            AND category NOT IN ('heartbeat', 'routine', 'audit')
            AND (event_type LIKE '%error%' OR event_type LIKE '%fail%'
                 OR event_type LIKE '%fix%' OR event_type LIKE '%restart%'
                 OR event_type LIKE '%deploy%' OR event_type LIKE '%bug%')
            ORDER BY created_at DESC LIMIT 10"""
        )
        for ev in events:
            detail = (ev['detail'] or '')[:300]
            t = ev['created_at'].strftime('%m/%d %H:%M') if ev['created_at'] else '?'
            count += await _save_material(conn, "incident",
                f"[{t}] {ev['category']}/{ev['event_type']}",
                f"[{t}] {ev['category']}/{ev['event_type']}: {detail}",
                "note_material")

        # failure_memory も収集
        failures = await conn.fetch(
            """SELECT failure_type, context, resolution, created_at
            FROM failure_memory
            WHERE created_at > NOW() - INTERVAL '48 hours'
            ORDER BY created_at DESC LIMIT 5"""
        )
        for f in failures:
            context = (f['context'] or '')[:200]
            resolution = (f['resolution'] or '未解決')[:200]
            count += await _save_material(conn, "incident",
                f"障害: {f['failure_type']}",
                f"障害: {f['failure_type']}\n状況: {context}\n対処: {resolution}",
                "note_material")

    except Exception as e:
        logger.warning(f"事件収集失敗: {e}")
    return count


async def _collect_intel_materials(conn) -> int:
    """情報層: Grok X検索 + intel_itemsの最新素材"""
    count = 0
    try:
        items = await conn.fetch(
            """SELECT title, summary, url, source FROM intel_items
            WHERE source IN ('grok_x_research', 'trend_detector', 'overseas_trend', 'english_article')
            AND created_at > NOW() - INTERVAL '48 hours'
            AND review_flag IN ('actionable', 'reviewed')
            ORDER BY importance_score DESC LIMIT 10"""
        )
        for item in items:
            summary = (item['summary'] or '')[:300]
            url = (item['url'] or '')[:200]
            count += await _save_material(conn, "intel",
                f"[{item['source']}] {item['title']}",
                f"{item['title']}\n{summary}\nURL: {url}",
                "note_material")
    except Exception as e:
        logger.warning(f"情報素材収集失敗: {e}")
    return count


async def _collect_knowledge(conn) -> int:
    """知見層: 設計判断・ノウハウの素材"""
    count = 0
    try:
        # 最近の設計判断（persona_memoryから）
        decisions = await conn.fetch(
            """SELECT content, category FROM persona_memory
            WHERE category IN ('design_decision', 'lesson_learned', 'working_fact')
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY priority_tier DESC, created_at DESC LIMIT 5"""
        )
        for d in decisions:
            content = (d['content'] or '')[:300]
            count += await _save_material(conn, "knowledge",
                f"知見({d['category']}): {content[:50]}",
                content,
                "note_material")

        # 最近のgstack reviewで見つかった改善点
        reviews = await conn.fetch(
            """SELECT detail FROM event_log
            WHERE event_type LIKE '%review%' OR event_type LIKE '%audit%'
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 5"""
        )
        for r in reviews:
            detail = (r['detail'] or '')[:300]
            if detail:
                count += await _save_material(conn, "knowledge",
                    f"レビュー知見: {detail[:50]}",
                    detail,
                    "note_material")

    except Exception as e:
        logger.warning(f"知見収集失敗: {e}")
    return count


async def _collect_philosophy(conn) -> int:
    """思想層: 島原との対話ログから哲学的素材"""
    count = 0
    try:
        dialogue = await conn.fetch(
            """SELECT daichi_message, extracted_philosophy, created_at
            FROM daichi_dialogue_log
            WHERE extracted_philosophy IS NOT NULL AND extracted_philosophy != ''
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 8"""
        )
        for d in dialogue:
            msg = (d['daichi_message'] or '')[:200]
            phil = (d['extracted_philosophy'] or '')[:300]
            count += await _save_material(conn, "philosophy",
                f"島原の哲学: {phil[:50]}",
                f"島原の発言: 「{msg}」\n抽出された哲学: {phil}",
                "note_material")
    except Exception as e:
        logger.warning(f"哲学素材収集失敗: {e}")
    return count
