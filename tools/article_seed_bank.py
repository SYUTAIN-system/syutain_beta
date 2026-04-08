"""記事シードバンク — 人間の「反芻」プロセスをシステム化

人間の記事執筆フロー:
  遭遇 → 反芻（数時間〜数日） → 着火 → 調査 → 角度決定 → 構成 → 初稿 → 寝かせ → 推敲 → 公開

現システムの最大の欠落は「反芻」フェーズ。
シードバンクは「気になったこと」を蓄積し、熟成させ、
十分な素材が集まったものから記事化する仕組み。

テーブル: article_seeds
- id, title, layer (record/incident/intel/knowledge/philosophy)
- seed_text (最初の気づき)
- connections (関連する他のシード・データとの接続)
- angle (「自分ならではの切り口」— 島原/SYUTAINβの視点)
- maturity_score (0.0-1.0: 素材の充実度)
- source_events (根拠となるevent_log/intel_items のID群)
- created_at, updated_at
"""

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.article_seed_bank")

JST = timezone(timedelta(hours=9))


async def ensure_table(conn):
    """article_seedsテーブルが存在しなければ作成"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS article_seeds (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            layer TEXT NOT NULL DEFAULT 'incident',
            seed_text TEXT NOT NULL,
            connections TEXT DEFAULT '[]',
            angle TEXT DEFAULT '',
            maturity_score FLOAT DEFAULT 0.0,
            source_events TEXT DEFAULT '[]',
            status TEXT DEFAULT 'germinating',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


async def plant_seed(conn, title: str, seed_text: str, layer: str,
                     source_event_ids: list = None, angle: str = "") -> int:
    """Phase 1 (遭遇): 気になった出来事をシードとして植える"""
    await ensure_table(conn)

    # 重複チェック（同じタイトルが24h以内にあればスキップ）
    existing = await conn.fetchval(
        "SELECT id FROM article_seeds WHERE title = $1 AND created_at > NOW() - INTERVAL '24 hours'",
        title,
    )
    if existing:
        return existing

    seed_id = await conn.fetchval(
        """INSERT INTO article_seeds (title, layer, seed_text, source_events, angle)
           VALUES ($1, $2, $3, $4, $5) RETURNING id""",
        title, layer, seed_text,
        json.dumps(source_event_ids or []),
        angle,
    )
    logger.info(f"シード植付: #{seed_id} [{layer}] {title[:50]}")
    return seed_id


async def nurture_seeds(conn) -> int:
    """Phase 2 (反芻): 既存シードに関連情報を接続し、熟成度を更新する

    毎日複数回呼ばれる。新しいevent_log/intel_itemsが入るたびに
    既存シードとの関連性をチェックし、接続を増やす。
    """
    await ensure_table(conn)

    updated = 0
    seeds = await conn.fetch(
        "SELECT id, title, seed_text, connections, source_events, layer "
        "FROM article_seeds WHERE status = 'germinating' ORDER BY created_at DESC LIMIT 20"
    )

    for seed in seeds:
        try:
            connections = json.loads(seed['connections'] or '[]')
            source_events = json.loads(seed['source_events'] or '[]')

            # 関連するevent_logを検索（キーワードマッチ）
            keywords = seed['title'].split()[:3]
            for kw in keywords:
                if len(kw) < 3:
                    continue
                related_events = await conn.fetch(
                    """SELECT id, event_type, payload::text as detail FROM event_log
                    WHERE payload::text ILIKE $1
                    AND created_at > NOW() - INTERVAL '48 hours'
                    AND id != ALL($2::int[])
                    LIMIT 3""",
                    f"%{kw}%", source_events or [0],
                )
                for ev in related_events:
                    connections.append({
                        "type": "event",
                        "id": ev['id'],
                        "summary": f"{ev['event_type']}: {(ev['detail'] or '')[:100]}",
                        "found_at": datetime.now(tz=JST).isoformat(),
                    })
                    source_events.append(ev['id'])

            # 関連するintel_itemsを検索
            related_intel = await conn.fetch(
                """SELECT id, title, summary FROM intel_items
                WHERE (title ILIKE $1 OR summary ILIKE $1)
                AND created_at > NOW() - INTERVAL '72 hours'
                LIMIT 3""",
                f"%{keywords[0] if keywords else seed['layer']}%",
            )
            for intel in related_intel:
                if not any(c.get('id') == intel['id'] and c.get('type') == 'intel' for c in connections):
                    connections.append({
                        "type": "intel",
                        "id": intel['id'],
                        "summary": f"{intel['title']}: {(intel['summary'] or '')[:100]}",
                        "found_at": datetime.now(tz=JST).isoformat(),
                    })

            # 熟成度スコア計算
            maturity = min(1.0, (
                0.2  # シード存在だけで0.2
                + min(0.3, len(connections) * 0.05)  # 接続数（最大0.3）
                + min(0.2, len(source_events) * 0.04)  # ソースイベント数（最大0.2）
                + (0.15 if seed.get('angle') else 0.0)  # 角度が決まっている
                + (0.15 if len(seed['seed_text']) > 200 else 0.05)  # 素材の厚み
            ))

            await conn.execute(
                """UPDATE article_seeds
                   SET connections = $1, source_events = $2, maturity_score = $3, updated_at = NOW()
                   WHERE id = $4""",
                json.dumps(connections, ensure_ascii=False, default=str),
                json.dumps(source_events),
                maturity,
                seed['id'],
            )
            updated += 1
        except Exception as e:
            logger.warning(f"シード育成失敗 #{seed['id']}: {e}")

    logger.info(f"シード育成: {updated}件更新")
    return updated


async def harvest_best_seed(conn, layer: str) -> dict | None:
    """Phase 3 (着火): 最も熟成したシードを収穫して記事テーマにする

    熟成度0.5以上のシードから、指定レイヤーに合うものを選ぶ。
    """
    await ensure_table(conn)

    seed = await conn.fetchrow(
        """SELECT id, title, seed_text, connections, angle, maturity_score
        FROM article_seeds
        WHERE status = 'germinating' AND layer = $1 AND maturity_score >= 0.4
        ORDER BY maturity_score DESC, created_at ASC
        LIMIT 1""",
        layer,
    )
    if not seed:
        # レイヤー指定なしでフォールバック
        seed = await conn.fetchrow(
            """SELECT id, title, seed_text, connections, angle, maturity_score
            FROM article_seeds
            WHERE status = 'germinating' AND maturity_score >= 0.4
            ORDER BY maturity_score DESC, created_at ASC
            LIMIT 1""",
        )
    if not seed:
        return None

    connections = json.loads(seed['connections'] or '[]')

    # 収穫済みにマーク
    await conn.execute(
        "UPDATE article_seeds SET status = 'harvested', updated_at = NOW() WHERE id = $1",
        seed['id'],
    )

    logger.info(f"シード収穫: #{seed['id']} [{layer}] {seed['title'][:50]} (maturity={seed['maturity_score']:.2f})")

    return {
        "seed_id": seed['id'],
        "title": seed['title'],
        "seed_text": seed['seed_text'],
        "connections": connections,
        "angle": seed['angle'] or "",
        "maturity_score": seed['maturity_score'],
    }


async def auto_plant_from_events(conn) -> int:
    """event_logとintel_itemsから自動的にシードを植える（定期実行用）"""
    await ensure_table(conn)

    planted = 0

    # 直近24hの注目イベントからシードを植える
    events = await conn.fetch(
        """SELECT id, event_type, category, payload::text as detail FROM event_log
        WHERE created_at > NOW() - INTERVAL '24 hours'
        AND category NOT IN ('heartbeat', 'routine')
        AND (event_type LIKE '%error%' OR event_type LIKE '%fail%'
             OR event_type LIKE '%fix%' OR event_type LIKE '%deploy%'
             OR event_type LIKE '%publish%' OR event_type LIKE '%milestone%')
        ORDER BY created_at DESC LIMIT 5"""
    )
    for ev in events:
        detail = (ev['detail'] or '')[:300]
        if len(detail) < 20:
            continue
        layer = "incident"
        sid = await plant_seed(
            conn,
            title=f"{ev['category']}/{ev['event_type']}: {detail[:60]}",
            seed_text=f"[{ev['category']}] {ev['event_type']}: {detail}",
            layer=layer,
            source_event_ids=[ev['id']],
        )
        if sid:
            planted += 1

    # 直近48hの高重要度intel_itemsからシードを植える
    intels = await conn.fetch(
        """SELECT id, title, summary, source FROM intel_items
        WHERE created_at > NOW() - INTERVAL '48 hours'
        AND importance_score >= 7
        AND review_flag IN ('actionable', 'reviewed')
        ORDER BY importance_score DESC LIMIT 5"""
    )
    for intel in intels:
        layer = "intel"
        sid = await plant_seed(
            conn,
            title=intel['title'],
            seed_text=f"[{intel['source']}] {intel['title']}: {(intel['summary'] or '')[:300]}",
            layer=layer,
        )
        if sid:
            planted += 1

    logger.info(f"自動シード植付: {planted}件")
    return planted
