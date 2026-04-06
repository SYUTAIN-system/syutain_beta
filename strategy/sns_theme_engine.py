"""SNS テーマ多様化エンジン — 具体的な素材付きテーマをDBから動的生成

2026-04-07 設計原理:
    旧 THEME_POOL は ["AI技術", "ビジネス", ...] の抽象テーマ 12 個。LLM はどれを選んでも
    SYUTAINβ の運用数値（LLM 呼び出し回数、コスト、Python 行数）から拾って**全部同じ投稿**を
    生成していた。4/6 の 42 件中 39 件が同一パターン。

    新設計は「具体的な話題素材プール」をDBから動的に組み立てる。各テーマに：
    - 一次情報の URL (Grok X 検索 / intel_items のソース)
    - 引用すべき具体的な数字や固有名詞
    - SNS 投稿の角度 (note_angle / sns_angle)
    - テーマカテゴリ (5 カテゴリ均等配分)

    これを persona_hint ではなく **テーマ指示そのもの** に注入するので、LLM は無視できない。

カテゴリ:
    1. syutain_ops     — SYUTAINβ の運用 (max 2件/日、固着防止)
    2. ai_tech_trend   — AI/テック最新動向 (Grok X リサーチ, intel_items)
    3. creator_media   — 映像/VTuber/ドローン/写真/広告/メディア
    4. philosophy_bip   — Build in Public 哲学、設計判断、教訓
    5. shimahara_fields — 経営/起業/マーケ/文化 (島原さんの拡張関連分野)

プラットフォーム別の配分:
    X @shimahara (4件):  syutain_ops 0, ai_tech 1, creator 1, philosophy 1, shimahara 1
    X @syutain  (6件):   syutain_ops 1, ai_tech 2, creator 1, philosophy 1, shimahara 1
    Bluesky    (13件):   syutain_ops 2, ai_tech 3, creator 3, philosophy 3, shimahara 2
    Threads    (13件):   syutain_ops 1, ai_tech 2, creator 3, philosophy 3, shimahara 4
"""

import json
import logging
import random
from typing import Optional

logger = logging.getLogger("syutain.sns_theme_engine")

# カテゴリ別の配分（各プラットフォーム×アカウントごと）
CATEGORY_DISTRIBUTION = {
    "x_shimahara": {
        "syutain_ops": 0, "ai_tech_trend": 1, "creator_media": 1,
        "philosophy_bip": 1, "shimahara_fields": 1,
    },
    "x_syutain": {
        "syutain_ops": 1, "ai_tech_trend": 2, "creator_media": 1,
        "philosophy_bip": 1, "shimahara_fields": 1,
    },
    "bluesky": {
        "syutain_ops": 2, "ai_tech_trend": 3, "creator_media": 3,
        "philosophy_bip": 3, "shimahara_fields": 2,
    },
    "threads": {
        "syutain_ops": 1, "ai_tech_trend": 2, "creator_media": 3,
        "philosophy_bip": 3, "shimahara_fields": 4,
    },
}

# SYUTAINβ運用テーマのバリエーション（固着防止のため固定テンプレートではなく角度を変える）
_SYUTAIN_OPS_ANGLES = [
    "今日見つけたバグとその原因の構造",
    "予算管理で起きた予想外の出来事",
    "ローカルLLMとクラウドLLMの使い分けの判断",
    "Discord Brain-βとの最新の会話で気づいたこと",
    "品質ゲートが止めてくれた危ない投稿の話",
    "夜間モードと日中モードの切り替えで起きること",
    "4台のPCの役割分担の進化",
    "CLAUDE.md のルールが増えた理由",
]

# creator_media テーマの静的候補（intel がない場合のフォールバック）
_CREATOR_FALLBACK = [
    {"topic": "AI映像制作ツールの現在地", "angle": "Runway/Sora/Kling等の実体験ベース比較", "category": "creator_media"},
    {"topic": "VTuber業界のAI活用", "angle": "モデリング/配信/マネジメントのどこにAIが入るか", "category": "creator_media"},
    {"topic": "ドローン×AIの可能性", "angle": "空撮/検査/農業での実用例", "category": "creator_media"},
    {"topic": "写真のAI編集", "angle": "Lightroom AI/Topaz等の実体験", "category": "creator_media"},
    {"topic": "広告制作とAI", "angle": "コピー生成/ビジュアル生成の現場", "category": "creator_media"},
    {"topic": "映画制作のAI革命", "angle": "プリプロ/VFX/カラグレのどこが変わるか", "category": "creator_media"},
]

# philosophy_bip テーマの静的候補
_PHILOSOPHY_FALLBACK = [
    {"topic": "Build in Publicの本当の意味", "angle": "恥ずかしい記録こそ価値がある理由", "category": "philosophy_bip"},
    {"topic": "AIに「出来ました」と言われた時", "angle": "信じるか検証するかの判断基準", "category": "philosophy_bip"},
    {"topic": "非エンジニアの武器", "angle": "コードは書けないけど壊れ方は想像できる", "category": "philosophy_bip"},
    {"topic": "設計書を25回書き直した話", "angle": "なぜドキュメントファーストが必須だったか", "category": "philosophy_bip"},
    {"topic": "AIエージェントの失敗パターン", "angle": "Gartner/McKinseyの予測と自分の実体験の交差", "category": "philosophy_bip"},
    {"topic": "完璧を待たずに公開する判断", "angle": "デッドコード207個あっても出す理由", "category": "philosophy_bip"},
]

# shimahara_fields テーマの静的候補
_SHIMAHARA_FALLBACK = [
    {"topic": "経営判断とAI", "angle": "提案エンジンが出した提案を人間がどう裁くか", "category": "shimahara_fields"},
    {"topic": "個人事業×AI自動化", "angle": "何を委譲して何を握り続けるか", "category": "shimahara_fields"},
    {"topic": "マーケティングのAI化", "angle": "SNS投稿49件/日を自動生成する実験結果", "category": "shimahara_fields"},
    {"topic": "メディアの未来", "angle": "AIがコンテンツを生成する時代の人間の役割", "category": "shimahara_fields"},
    {"topic": "文化産業とテクノロジー", "angle": "クリエイターがAIを使いこなす vs AIに置き換えられる", "category": "shimahara_fields"},
    {"topic": "起業の新しい形", "angle": "コードゼロで56000行のシステムを作る時代", "category": "shimahara_fields"},
]


async def build_theme_pool(
    platform: str,
    account: str,
    conn,
    used_today: list[str] = None,
) -> list[dict]:
    """プラットフォーム×アカウント別の具体テーマプールをDBから動的生成。

    Returns:
        [{"topic": str, "angle": str, "source_url": str, "key_data": str,
          "category": str, "hashtags": list[str]}]
    """
    platform_key = f"{platform}_{account}" if platform == "x" else platform
    distribution = CATEGORY_DISTRIBUTION.get(platform_key, CATEGORY_DISTRIBUTION.get(platform, {}))
    if not distribution:
        distribution = {"syutain_ops": 1, "ai_tech_trend": 2, "creator_media": 2, "philosophy_bip": 2, "shimahara_fields": 2}

    pool: list[dict] = []
    used = set(used_today or [])

    # === 1. ai_tech_trend: Grok X リサーチ + intel_items から最新話題を取得 ===
    ai_tech_count = distribution.get("ai_tech_trend", 2)
    try:
        grok_items = await conn.fetch(
            """SELECT title, summary, url, metadata FROM intel_items
               WHERE source IN ('grok_x_research', 'trend_detector', 'overseas_trend')
               AND created_at > NOW() - INTERVAL '48 hours'
               AND review_flag = 'actionable'
               ORDER BY importance_score DESC, created_at DESC
               LIMIT $1""",
            ai_tech_count * 3,  # 候補を多めに取って重複回避
        )
        for r in grok_items:
            topic = (r["title"] or "")[:100]
            if topic in used or not topic:
                continue
            meta = {}
            try:
                meta = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            except Exception:
                pass
            pool.append({
                "topic": topic,
                "angle": (meta.get("note_angle") or meta.get("sns_angle") or r.get("summary", ""))[:200],
                "source_url": (r.get("url") or "")[:300],
                "key_data": (r.get("summary") or "")[:200],
                "category": "ai_tech_trend",
                "hashtags": ["#AI", "#テック"],
            })
            used.add(topic)
            if len([p for p in pool if p["category"] == "ai_tech_trend"]) >= ai_tech_count:
                break
    except Exception as e:
        logger.debug(f"ai_tech_trend DB取得失敗: {e}")

    # ai_tech が不足ならバズ検出から補充
    if len([p for p in pool if p["category"] == "ai_tech_trend"]) < ai_tech_count:
        try:
            buzz_items = await conn.fetch(
                """SELECT title, summary, url FROM intel_items
                   WHERE source = 'buzz_detector' AND category IN ('tech', 'ai')
                   AND created_at > NOW() - INTERVAL '72 hours'
                   ORDER BY importance_score DESC LIMIT 5"""
            )
            for r in buzz_items:
                topic = (r["title"] or "")[:100]
                if topic in used or not topic:
                    continue
                pool.append({
                    "topic": topic,
                    "angle": (r.get("summary") or "")[:200],
                    "source_url": (r.get("url") or "")[:300],
                    "key_data": "",
                    "category": "ai_tech_trend",
                    "hashtags": ["#AI", "#テック"],
                })
                used.add(topic)
                if len([p for p in pool if p["category"] == "ai_tech_trend"]) >= ai_tech_count:
                    break
        except Exception:
            pass

    # === 2. creator_media: intel_items のクリエイター系 + フォールバック ===
    creator_count = distribution.get("creator_media", 2)
    try:
        creator_items = await conn.fetch(
            """SELECT title, summary, url, metadata FROM intel_items
               WHERE (category IN ('creator', 'media', 'video', 'vtuber', 'drone', 'photo')
                      OR keyword ILIKE '%映像%' OR keyword ILIKE '%VTuber%'
                      OR keyword ILIKE '%ドローン%' OR keyword ILIKE '%写真%')
               AND created_at > NOW() - INTERVAL '72 hours'
               ORDER BY importance_score DESC LIMIT $1""",
            creator_count * 2,
        )
        for r in creator_items:
            topic = (r["title"] or "")[:100]
            if topic in used or not topic:
                continue
            pool.append({
                "topic": topic,
                "angle": (r.get("summary") or "")[:200],
                "source_url": (r.get("url") or "")[:300],
                "key_data": "",
                "category": "creator_media",
                "hashtags": ["#クリエイター", "#映像制作"],
            })
            used.add(topic)
            if len([p for p in pool if p["category"] == "creator_media"]) >= creator_count:
                break
    except Exception:
        pass
    # 不足分をフォールバックで補充
    while len([p for p in pool if p["category"] == "creator_media"]) < creator_count:
        candidates = [c for c in _CREATOR_FALLBACK if c["topic"] not in used]
        if not candidates:
            break
        chosen = random.choice(candidates)
        pool.append({**chosen, "source_url": "", "key_data": "", "hashtags": ["#クリエイター", "#映像制作"]})
        used.add(chosen["topic"])

    # === 3. syutain_ops: 運用テーマ（角度を変えて最大2件/日） ===
    ops_count = distribution.get("syutain_ops", 1)
    ops_angles_available = [a for a in _SYUTAIN_OPS_ANGLES if a not in used]
    for _ in range(min(ops_count, 2)):  # 絶対に 2 件以下
        if not ops_angles_available:
            break
        angle = random.choice(ops_angles_available)
        ops_angles_available.remove(angle)
        pool.append({
            "topic": f"SYUTAINβ運用: {angle}",
            "angle": angle,
            "source_url": "",
            "key_data": "SYUTAINβの最新実データを使う。ただし他テーマと同じ数字の繰り返しは禁止。",
            "category": "syutain_ops",
            "hashtags": ["#SYUTAINβ", "#AI開発"],
        })
        used.add(angle)

    # === 4. philosophy_bip: Build in Public 哲学 ===
    phil_count = distribution.get("philosophy_bip", 2)
    phil_items = [c for c in _PHILOSOPHY_FALLBACK if c["topic"] not in used]
    # daichi_dialogue_log から最新の哲学的発言を拾う
    try:
        dialogue_items = await conn.fetch(
            """SELECT daichi_message, extracted_philosophy FROM daichi_dialogue_log
               WHERE created_at > NOW() - INTERVAL '14 days'
               AND daichi_message IS NOT NULL AND length(daichi_message) > 30
               ORDER BY created_at DESC LIMIT 5"""
        )
        for d in dialogue_items:
            msg = (d["daichi_message"] or "")[:200]
            if msg in used or not msg:
                continue
            # エラーログやシステムメッセージが紛れ込んでいる場合を除外
            if any(kw in msg for kw in ["ERROR", "WARNING", "FAIL", "⚠️", "Traceback", "Exception"]):
                continue
            philosophy = {}
            try:
                philosophy = json.loads(d["extracted_philosophy"]) if isinstance(d["extracted_philosophy"], str) else (d["extracted_philosophy"] or {})
            except Exception:
                pass
            if philosophy:
                pool.append({
                    "topic": f"島原の思考: {msg[:60]}",
                    "angle": msg[:200],
                    "source_url": "",
                    "key_data": json.dumps(philosophy, ensure_ascii=False)[:300] if philosophy else "",
                    "category": "philosophy_bip",
                    "hashtags": ["#BuildInPublic", "#AI"],
                })
                used.add(msg)
                if len([p for p in pool if p["category"] == "philosophy_bip"]) >= phil_count:
                    break
    except Exception:
        pass
    while len([p for p in pool if p["category"] == "philosophy_bip"]) < phil_count:
        if not phil_items:
            break
        chosen = random.choice(phil_items)
        phil_items.remove(chosen)
        pool.append({**chosen, "source_url": "", "key_data": "", "hashtags": ["#BuildInPublic", "#非エンジニア"]})
        used.add(chosen["topic"])

    # === 5. shimahara_fields: 経営/起業/マーケ/文化 ===
    shima_count = distribution.get("shimahara_fields", 2)
    # Grok upcoming_events から翌週ネタ
    try:
        event_items = await conn.fetch(
            """SELECT title, summary, url, metadata FROM intel_items
               WHERE source = 'grok_upcoming_events'
               AND created_at > NOW() - INTERVAL '7 days'
               ORDER BY importance_score DESC LIMIT $1""",
            shima_count * 2,
        )
        for r in event_items:
            topic = (r["title"] or "")[:100]
            if topic in used or not topic:
                continue
            pool.append({
                "topic": topic,
                "angle": (r.get("summary") or "")[:200],
                "source_url": (r.get("url") or "")[:300],
                "key_data": "",
                "category": "shimahara_fields",
                "hashtags": ["#経営", "#起業"],
            })
            used.add(topic)
            if len([p for p in pool if p["category"] == "shimahara_fields"]) >= shima_count:
                break
    except Exception:
        pass
    while len([p for p in pool if p["category"] == "shimahara_fields"]) < shima_count:
        candidates = [c for c in _SHIMAHARA_FALLBACK if c["topic"] not in used]
        if not candidates:
            break
        chosen = random.choice(candidates)
        pool.append({**chosen, "source_url": "", "key_data": "", "hashtags": ["#経営", "#起業"]})
        used.add(chosen["topic"])

    # シャッフルして固定順序を避ける
    random.shuffle(pool)
    return pool


def format_theme_for_prompt(theme: dict) -> str:
    """テーマ dict を LLM に渡す 1 行の具体的な指示に変換。
    LLM がこれを無視して運用数値に戻るのを防ぐため、明示的に指示する。"""
    parts = [f"【テーマ】{theme['topic']}"]
    if theme.get("angle"):
        parts.append(f"【角度】{theme['angle']}")
    if theme.get("source_url"):
        parts.append(f"【情報源】{theme['source_url']}")
    if theme.get("key_data"):
        parts.append(f"【素材】{theme['key_data'][:150]}")
    parts.append("※上記のテーマと角度に沿って投稿を作成すること。SYUTAINβの運用数値（LLM呼び出し回数、コスト、Python行数等）に逃げないこと。")
    return "\n".join(parts)
