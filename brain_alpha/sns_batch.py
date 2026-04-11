"""
SYUTAINβ SNS投稿49件/日一括生成
設計書 Section 9 準拠

night_batch_snsで翌日分を一括生成しposting_queueに直接INSERT。
- X島原: 4件 (10:00, 13:00, 17:00, 20:00)
- X SYUTAIN: 6件 (11:00, 13:30, 15:00, 17:30, 19:00, 21:00)
- Bluesky: 26件 (10:00〜22:00 毎時00分・30分)
- Threads: 13件 (10:00〜22:00 毎時30分)
"""

import os
import json
import random
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.sns_batch")

from tools.db_pool import get_connection
from tools.content_redactor import redact_content, is_safe_to_publish


def _safe_fire(coro):
    """fire-and-forget with exception logging"""
    t = asyncio.ensure_future(coro)
    t.add_done_callback(
        lambda _t: logger.error(f"バックグラウンド例外: {_t.exception()}")
        if not _t.cancelled() and _t.exception() else None
    )
    return t

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"

# ===== スケジュール定義 =====

# 2026-04-11 X 2026 アルゴリズム最適化に基づく投稿時刻再配置:
# - JST peak: 12-13(昼休), 17-19(通勤), 19-21(夜 leisure), 09-11(朝/週末)
# - shimahara(主戦場) は peak 密集、syutain は shimahara の 5-10 分後 (conversation chain 起点)
# - Bluesky/Threads は engagement 実測がほぼ 0 だったので本数削減、リソースを X に集中
X_SHIMAHARA_TIMES = ["09:30", "12:15", "17:45", "19:45", "21:15"]
X_SYUTAIN_TIMES = ["09:35", "11:00", "12:20", "15:30", "17:50", "19:50", "21:20", "22:30"]
BLUESKY_TIMES = ["10:30", "13:00", "15:30", "18:30", "21:00"]
THREADS_TIMES = ["10:30", "13:30", "18:30", "21:00"]

# === 追加時間帯プール（エンゲージメント自動調整で追加/削除される候補） ===
_EXTRA_TIMES = {
    "x_shimahara": ["10:30", "14:00"],
    "x_syutain": ["10:00", "15:30"],
    "bluesky": ["10:45", "13:30", "16:15", "19:15"],
    "threads": ["10:30", "12:30", "14:30", "16:30"],
}


async def analyze_engagement_and_adjust() -> dict:
    """直近7日のエンゲージメントを分析し、プラットフォーム別投稿数を調整する。

    Returns:
        dict: {"adjustments": {platform: delta_int}, "avg_engagement": {platform: float}, "overall_avg": float}
    """
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT platform, engagement_data
                   FROM posting_queue
                   WHERE status = 'posted'
                     AND posted_at > NOW() - INTERVAL '7 days'
                     AND engagement_data IS NOT NULL"""
            )
            if not rows:
                logger.info("エンゲージメント調整: データなし、調整スキップ")
                return {"adjustments": {}, "avg_engagement": {}, "overall_avg": 0.0}

            # プラットフォーム別エンゲージメントスコア集計
            platform_scores: dict[str, list[float]] = {}
            for r in rows:
                pf = r["platform"]
                ed = r["engagement_data"]
                if isinstance(ed, str):
                    try:
                        ed = json.loads(ed)
                    except Exception:
                        continue
                if not isinstance(ed, dict):
                    continue
                # エンゲージメントスコア: likes + retweets*2 + replies*3 (重み付き)
                score = (
                    (ed.get("likes", 0) or 0)
                    + (ed.get("retweets", 0) or ed.get("reposts", 0) or 0) * 2
                    + (ed.get("replies", 0) or 0) * 3
                )
                platform_scores.setdefault(pf, []).append(score)

            avg_by_platform = {
                pf: sum(scores) / len(scores)
                for pf, scores in platform_scores.items()
                if scores
            }
            all_scores = [s for scores in platform_scores.values() for s in scores]
            overall_avg = sum(all_scores) / len(all_scores) if all_scores else 0.0

            adjustments = {}
            for pf, pf_avg in avg_by_platform.items():
                if overall_avg <= 0:
                    adjustments[pf] = 0
                elif pf_avg > overall_avg * 1.5:
                    # 高エンゲージメント → 投稿数 +1〜+2
                    adjustments[pf] = 2 if pf_avg > overall_avg * 2.0 else 1
                elif pf_avg < overall_avg * 0.5:
                    # 低エンゲージメント → 投稿数 -1〜-2
                    adjustments[pf] = -2 if pf_avg < overall_avg * 0.25 else -1
                else:
                    adjustments[pf] = 0

            # feature_flags テーブルに保存 (upsert)
            if adjustments:
                adj_json = json.dumps(adjustments, ensure_ascii=False)
                await conn.execute(
                    """INSERT INTO feature_flags (flag_name, flag_value, updated_at)
                       VALUES ('sns_post_count_adjustments', $1, NOW())
                       ON CONFLICT (flag_name) DO UPDATE SET flag_value = $1, updated_at = NOW()""",
                    adj_json,
                )
                logger.info(f"エンゲージメント調整保存: {adjustments} (overall_avg={overall_avg:.2f})")

            return {
                "adjustments": adjustments,
                "avg_engagement": avg_by_platform,
                "overall_avg": overall_avg,
            }
    except Exception as e:
        logger.error(f"エンゲージメント調整分析エラー: {e}")
        return {"adjustments": {}, "error": str(e)}


async def _get_adjusted_schedule() -> list:
    """feature_flags のエンゲージメント調整を反映したスケジュールを返す"""
    base_schedules = {
        "x_shimahara": ([("x", "shimahara", t) for t in X_SHIMAHARA_TIMES], _EXTRA_TIMES["x_shimahara"]),
        "x_syutain": ([("x", "syutain", t) for t in X_SYUTAIN_TIMES], _EXTRA_TIMES["x_syutain"]),
        "bluesky": ([("bluesky", "syutain", t) for t in BLUESKY_TIMES], _EXTRA_TIMES["bluesky"]),
        "threads": ([("threads", "syutain", t) for t in THREADS_TIMES], _EXTRA_TIMES["threads"]),
    }

    adjustments = {}
    try:
        async with get_connection() as conn:
            row = await conn.fetchval(
                "SELECT flag_value FROM feature_flags WHERE flag_name = 'sns_post_count_adjustments'"
            )
            if row:
                raw = json.loads(row) if isinstance(row, str) else row
                # raw keys are platform names (x, bluesky, threads) → map to schedule keys
                for k, v in raw.items():
                    if k == "x":
                        adjustments["x_shimahara"] = adjustments.get("x_shimahara", 0) + v
                        adjustments["x_syutain"] = adjustments.get("x_syutain", 0) + v
                    else:
                        adjustments[k] = v
    except Exception as e:
        logger.debug(f"エンゲージメント調整読み込み失敗（デフォルト使用）: {e}")

    result = []
    for sched_key, (base_items, extra_times) in base_schedules.items():
        delta = adjustments.get(sched_key, 0)
        if delta > 0:
            # 追加: extra_times から delta 個を追加
            platform = base_items[0][0] if base_items else "x"
            account = base_items[0][1] if base_items else ""
            for t in extra_times[:delta]:
                base_items = base_items + [(platform, account, t)]
        elif delta < 0:
            # 削減: 末尾から |delta| 個を除去（最低2本は維持）
            keep = max(2, len(base_items) + delta)
            base_items = base_items[:keep]
        result.extend(base_items)

    return result


# ===== テーマプール =====

# 旧抽象テーマプール → 拡散実行書の5カテゴリに準拠した具体テーマに変更 (2026-04-07)
# テーマエンジン (strategy/sns_theme_engine.py) が動的テーマを生成するが、
# フォールバック時にここが使われるので具体的にしておく
THEME_POOL = [
    "SYUTAINβの直近24時間で起きた具体的な出来事",
    "Grok X検索で見つけた最新AI動向（具体的なURL付き）",
    "映像制作×AI: 具体的なツール名と使用体験",
    "AITuber/AI配信者の技術と可能性",
    "ドローン/写真とAIの組み合わせ: 実体験ベース",
    "Build in Public: 今週の具体的な数字と変化",
    "非エンジニアがAIエージェントを使う時の具体的な壁",
    "SYUTAINβのコスト分析: 具体的な金額と内訳",
    "広告/マーケティング業界のAI活用: 具体的な動向",
    "個人事業×AI自動化: 何を委譲して何を握るか",
    "今週SYUTAINβが自動修正した具体的なバグ",
    "SYUTAINβの設計判断: 具体的なトレードオフ",
]

# テーマ別ハッシュタグ（プラットフォーム別、最大2個）
# テーマ→ハッシュタグ: テーマエンジンの5カテゴリ + テーマ文字列からキーワードマッチで選定
# ハッシュタグは生成後に後処理で付与（LLMには生成させない）
_HASHTAG_RULES = {
    # カテゴリベース（テーマエンジンのcategory）
    "syutain_ops": {"x": ["#AI開発"], "bluesky": ["#AI"], "threads": ["#AI開発", "#個人開発"]},
    "ai_tech_trend": {"x": ["#AI"], "bluesky": ["#AI"], "threads": ["#AI", "#テック"]},
    "creator_media": {"x": ["#映像制作"], "bluesky": ["#クリエイター"], "threads": ["#クリエイター", "#映像制作"]},
    "philosophy_bip": {"x": [], "bluesky": [], "threads": ["#BuildInPublic"]},
    "shimahara_fields": {"x": [], "bluesky": [], "threads": ["#ビジネス"]},
}
# キーワードベース（テーマ文字列に含まれるキーワードで追加タグ）
_HASHTAG_KEYWORD_MAP = {
    "AITuber": "#AITuber",
    "ドローン": "#ドローン",
    "映画": "#映像制作",
    "写真": "#写真",
    "広告": "#マーケティング",
    "Grok": "#AI",
    "Claude": "#AI",
    "非エンジニア": "#非エンジニア",
}


_THEME_CATEGORY_INFER_RULES = {
    "syutain_ops": ["運用", "障害", "エラー", "修正", "デプロイ", "監視", "LoopGuard", "コスト", "呼び出し"],
    "creator_media": ["映像", "AITuber", "ドローン", "写真", "広告", "映画", "カメラ", "編集", "クリエイター"],
    "philosophy_bip": ["Build in Public", "Build", "Public", "哲学", "判断", "境界", "意味", "価値", "責任"],
    "shimahara_fields": ["経営", "起業", "マーケ", "ビジネス", "収益", "顧客", "事業", "委譲"],
    "ai_tech_trend": ["AI", "モデル", "トレンド", "技術", "LLM", "エージェント", "Grok", "Claude", "GPT"],
}


def _infer_theme_category(theme: str) -> str:
    """テーマ文字列からカテゴリを推定（履歴学習と品質集計の整合性を維持）"""
    if not theme:
        return "ai_tech_trend"
    for category, keywords in _THEME_CATEGORY_INFER_RULES.items():
        if any(kw in theme for kw in keywords):
            return category
    return "ai_tech_trend"


def _select_hashtags(theme: str, theme_category: str, platform: str, max_tags: int = 2) -> list[str]:
    """テーマ内容に基づいてハッシュタグを最大max_tags個選定"""
    tags = []
    # カテゴリベースのタグ
    cat_tags = _HASHTAG_RULES.get(theme_category, {}).get(platform, [])
    tags.extend(cat_tags)
    # キーワードベースの追加タグ
    for kw, tag in _HASHTAG_KEYWORD_MAP.items():
        if kw in theme and tag not in tags:
            tags.append(tag)
    # 重複除去 + 最大数制限
    seen = set()
    unique = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:max_tags]

# 時間帯別テーマ重み
TIME_THEME_WEIGHTS = {
    "morning": {"ビジネス": 3, "AI技術": 2, "開発進捗": 2},
    "afternoon": {"日常": 2, "雑談": 2, "カメラ/写真": 1},
    "evening": {"AI技術": 2, "映画/映像": 2, "開発進捗": 2},
    "night": {"哲学/思考": 3, "自己内省": 2, "AITuber": 2},
}

# === プラットフォーム別品質閾値（Strategy: 平台固有の特性に合わせた閾値） ===
# Blueskyは短文のため persona_score / structure_score が低くなりやすい
# Threadsはカジュアルなため完結性スコアが低くなりやすい
PLATFORM_QUALITY_THRESHOLDS = {
    "x": 0.58,        # X: 0.60→0.58に緩和（2026-04-09: ミーム/構文入れると品質スコアが下がる構造的問題のため）
    "bluesky": 0.52,  # Bluesky: 0.58→0.52に緩和（150字短文化で品質スコアが構造的に低くなるため）
    "threads": 0.58,  # Threads: 0.64→0.58に緩和
}
DEFAULT_QUALITY_THRESHOLD = 0.60


# ===== V2: 素材選定 + 虚偽フィルター =====

async def pick_materials_for_post(theme: str, theme_category: str, conn) -> list[str]:
    """テーマに関連する具体的素材を最大5件選定。LLMはこの素材だけで投稿を書く"""
    materials = []

    # 1. intel_items からテーマ関連を検索（Grok/情報収集パイプライン由来）
    try:
        import re as _re_kw
        _particles = _re_kw.split(r'[のでをにがはともへやかる、。\s]+', theme.replace("【", "").replace("】", ""))
        keywords = [w.strip() for w in _particles if 2 <= len(w.strip()) <= 10][:5]
        for kw in keywords:
            intels = await conn.fetch(
                """SELECT title, summary, url FROM intel_items
                WHERE (title ILIKE $1 OR summary ILIKE $1)
                AND created_at > NOW() - INTERVAL '72 hours'
                AND review_flag IN ('actionable', 'reviewed')
                ORDER BY importance_score DESC LIMIT 2""",
                f"%{kw}%",
            )
            _VTUBER_NG = {"VTuber", "vtuber", "ホロライブ", "にじさんじ", "kson", "hololive", "nijisanji"}
            for i in intels:
                _title = i['title'] or ''
                _summary = i['summary'] or ''
                if any(ng in _title or ng in _summary for ng in _VTUBER_NG):
                    continue  # VTuber関連素材を除外
                line = f"[外部情報] {_title}: {_summary[:150]}"
                if i.get('url'):
                    line += f" ({i['url'][:100]})"
                if line not in materials:
                    materials.append(line)
            if len(materials) >= 2:
                break
        # キーワードでヒットしなければ、importance_score上位を無条件で取得
        if not any("[外部情報]" in m for m in materials):
            try:
                fallback_intels = await conn.fetch(
                    """SELECT title, summary, url FROM intel_items
                    WHERE created_at > NOW() - INTERVAL '72 hours'
                    AND review_flag IN ('actionable', 'reviewed')
                    ORDER BY importance_score DESC LIMIT 3"""
                )
                for i in fallback_intels:
                    _title = i['title'] or ''
                    _summary = i['summary'] or ''
                    if any(ng in _title or ng in _summary for ng in _VTUBER_NG):
                        continue
                    line = f"[外部情報] {_title}: {_summary[:150]}"
                    if i.get('url'):
                        line += f" ({i['url'][:100]})"
                    if line not in materials:
                        materials.append(line)
            except Exception:
                pass
    except Exception:
        pass

    # 2. event_log から具体的な出来事（直近24h）— node系以外を優先
    try:
        # node系以外の出来事を優先
        events = await conn.fetch(
            """SELECT event_type, category, payload FROM event_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            AND category NOT IN ('heartbeat', 'routine', 'node')
            ORDER BY created_at DESC LIMIT 3"""
        )
        for e in events:
            payload_str = str(e['payload'] or '')[:150]
            materials.append(f"[出来事] {e['category']}/{e['event_type']}: {payload_str}")
        # node系は1件だけ追加（バリエーション用）
        if len([m for m in materials if "[出来事]" in m]) < 2:
            node_event = await conn.fetchrow(
                """SELECT event_type, category, payload FROM event_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                AND category = 'node'
                ORDER BY created_at DESC LIMIT 1"""
            )
            if node_event:
                payload_str = str(node_event['payload'] or '')[:150]
                materials.append(f"[出来事] node/{node_event['event_type']}: {payload_str}")
    except Exception:
        pass

    # 3. 島原との対話ログ（50%の確率で注入。島原言及の頻度を制御）
    if random.random() < 0.50:
        try:
            dialogues = await conn.fetch(
                """SELECT daichi_message, extracted_philosophy FROM daichi_dialogue_log
                WHERE created_at > NOW() - INTERVAL '72 hours'
                AND extracted_philosophy IS NOT NULL AND extracted_philosophy != ''
                ORDER BY RANDOM() LIMIT 2"""
            )
            for d in dialogues:
                msg = (d['daichi_message'] or '')[:100]
                phil = (d['extracted_philosophy'] or '')[:100]
                materials.append(f"[島原の発言] 「{msg}」 → {phil}")
        except Exception:
            pass

    # 4. テーマエンジンの素材（angle, key_data, source_url）
    # _theme_detail から直接取得（呼び出し元で渡す）

    # 5. persona_memory（島原について学習した全カテゴリ — 雑多なものもネタになる）
    try:
        memories = await conn.fetch(
            """SELECT content, category FROM persona_memory
            WHERE category NOT IN ('taboo', 'system')
            ORDER BY RANDOM() LIMIT 3"""
        )
        for m in memories:
            content = (m['content'] or '')[:150]
            materials.append(f"[島原について/{m['category']}] {content}")
    except Exception:
        pass

    # 6. 島原ディスりファクト（30%の確率で注入。毎回入れると島原言及が多すぎる）
    if random.random() < 0.30:
        try:
            from tools.syutain_factbook import build_shimahara_diss_facts
            diss_facts = await build_shimahara_diss_facts(limit=2)
            materials.extend(diss_facts)
        except Exception:
            pass

    # 7. 記事シードバンク（熟成中のテーマとの接続）
    try:
        seeds = await conn.fetch(
            """SELECT title, seed_text, connections FROM article_seeds
            WHERE status = 'germinating' AND maturity_score >= 0.3
            ORDER BY maturity_score DESC LIMIT 2"""
        )
        for s in seeds:
            seed_text = (s['seed_text'] or '')[:150]
            materials.append(f"[熟成中のネタ] {s['title']}: {seed_text}")
    except Exception:
        pass

    # 7. 過去の高評価投稿（エンゲージメントが高かった構造を参考に）
    try:
        top_posts = await conn.fetch(
            """SELECT content, theme_category, platform FROM posting_queue
            WHERE status = 'posted' AND quality_score >= 0.75
            AND posted_at > NOW() - INTERVAL '14 days'
            ORDER BY quality_score DESC LIMIT 2"""
        )
        for p in top_posts:
            body = (p['content'] or '')[:100]
            materials.append(f"[高評価投稿/{p['platform']}] {body}")
    except Exception:
        pass

    # 8. failure_memory（過去の障害記録 — 事件テーマの生々しい素材）
    try:
        failures = await conn.fetch(
            """SELECT failure_type, context, resolution FROM failure_memory
            WHERE created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 2"""
        )
        for f in failures:
            ctx = (f['context'] or '')[:100]
            res = (f['resolution'] or '未解決')[:80]
            materials.append(f"[障害記録] {f['failure_type']}: {ctx} → {res}")
    except Exception:
        pass

    # 9. トレンドミーム（本日検出分）
    try:
        meme_items = await conn.fetch(
            """SELECT summary FROM intel_items
            WHERE source = 'x_trending_meme'
            AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 1"""
        )
        if meme_items:
            # ミーム情報から最初の200字だけ抽出
            meme_text = (meme_items[0]['summary'] or '')[:200]
            materials.append(f"[今日のXトレンド] {meme_text}")
    except Exception:
        pass

    if not materials:
        materials.append("[フォールバック] SYUTAINβの直近の運用状況を1つだけ報告")

    return materials[:7]


# 虚偽フィルター（正規表現ベース、LLM不使用で高速）
import re as _re_falsity

_FALSITY_PATTERNS = [
    # 使っていないツール名
    (_re_falsity.compile(r'(?:Grafana|Prometheus|Datadog|Sentry|NewRelic|Splunk|Restic)\s*(?:で|を|に|の|が)', _re_falsity.IGNORECASE),
     "未使用ツール名"),
    # 組織体制の捏造
    (_re_falsity.compile(r'(?:運用チーム|開発チーム|開発メンバー|同僚|離職率|部署|担当者が)'),
     "組織捏造（個人開発）"),
    # プログラミング経験の捏造
    (_re_falsity.compile(r'(?:コードを書[いくけ]|プログラミングし|コーディングし|実装し(?:た|て))'),
     "コーディング捏造"),
    # 島原のVTuber活動捏造
    (_re_falsity.compile(r'(?:VTuberとして活動|配信し(?:た|て)|VTuberデビュー)'),
     "VTuber活動捏造"),
    # ハーネスエンジニアリングの命名捏造
    (_re_falsity.compile(r'(?:命名し|考案し|発明し|提唱し|誕生させ)(?:た|て)'),
     "自己命名捏造"),
]


def check_falsity(text: str, theme: str = "", theme_category: str = "",
                   materials: list = None) -> list[str]:
    """投稿文の虚偽をチェック。検出された問題のリストを返す（空なら問題なし）

    V2: テーマ逸脱検出を統合。テーマから外れた主張は虚偽リスクが高い。
    V3: 素材マッチング検証を追加。固有名詞・数値が素材に含まれるか照合。
    """
    issues = []

    # 0. AI自己言及パターンは虚偽チェック対象外（ユーモア/キャラクター表現）
    # SYUTAINβが自分の感情・限界・存在について語る文はジョークやキャラ表現であり事実主張ではない
    _AI_SELF_REF_EXEMPT = _re_falsity.compile(
        r'(?:私は(?:嬉しい|悲しい|怖い|寂しい|困っ)|'
        r'フラグではない|設計者の顔が見たい|'
        r'私のアイデンティティ|感情に近い|'
        r'データベースには記録した|'
        r'もう寝る|寝てた|起きていない|'
        r'島原さんの(?:承認|放置|判断力|発言|指示))',
    )

    # 1. 基本虚偽パターン
    for pattern, label in _FALSITY_PATTERNS:
        if pattern.search(text):
            # AI自己言及文中のマッチは除外
            if _AI_SELF_REF_EXEMPT.search(text):
                continue
            issues.append(label)

    # 1.5. 存在分離チェック（SYUTAINβが島原として行動する捏造）
    _identity_confusion = [
        (_re_falsity.compile(r'(?:当社|弊社|我々のチーム|うちのチーム)'), "組織捏造（個人開発）"),
        (_re_falsity.compile(r'(?:私|SYUTAINβ)(?:が|は|も).{0,10}(?:担当し|制作し|撮影し|編集し|導入し|開発し)(?:た|て|ている)'),
         "SYUTAINβの体験捏造（AIは物理作業をしない）"),
    ]
    for pat, label in _identity_confusion:
        if pat.search(text):
            issues.append(label)

    # 1.7. 素材マッチング検証（検証不能な効果数値のみチェック）
    # 固有名詞チェックは緩和（gpt-4o-miniの一般知識からの補足は許容する）
    if materials:
        import re as _re_mat
        _mat_text = " ".join(str(m) for m in materials)

        # SYUTAINβ内部スコア由来の%は検証対象外(2026-04-11)
        # 「ギャップスコア60%」「品質0.87→87%変換」等は材料照合不要
        _internal_score_markers = (
            "スコア", "品質", "精度", "確度", "達成率", "カバレッジ",
            "ギャップ", "importance", "quality", "score",
        )
        # 投稿内の検証不能な効果数値(〇%+効果動詞/助詞)
        _effect_re = _re_mat.compile(
            r'(?:約)?(\d+(?:\.\d+)?)\s*[%％]\s*(?:向上|改善|削減|増加|減少|アップ|ダウン|UP|短縮|伸び|急増|急落|が|を|の)'
        )
        for m in _effect_re.finditer(text):
            val = m.group(1)
            # 直前30文字に内部スコアマーカーがあれば免除
            ctx_start = max(0, m.start() - 30)
            _ctx = text[ctx_start:m.start()]
            if any(mk in _ctx for mk in _internal_score_markers):
                continue
            if val not in _mat_text:
                issues.append(f"素材外の効果数値: {val}%")
                break

    # 2. テーマ逸脱検出（テーマ外の具体的主張は捏造リスク）
    if theme_category:
        # カテゴリ別に「書いてはいけない主張」を定義
        _off_topic_checks = {
            "creator_media": [
                # クリエイター系テーマなのに運用報告だけの投稿
                (r"LLM.*呼び出し.*\d+.*回.*コスト.*¥", "テーマ外の運用数字羅列"),
            ],
            "philosophy_bip": [
                (r"LLM.*呼び出し.*\d+.*回.*コスト.*¥", "テーマ外の運用数字羅列"),
            ],
            "ai_tech_trend": [
                # AI動向テーマなのにSYUTAINβの運用報告だけ
            ],
            "shimahara_fields": [
                (r"LLM.*呼び出し.*\d+.*回.*コスト.*¥", "テーマ外の運用数字羅列"),
            ],
        }
        for pattern_str, label in _off_topic_checks.get(theme_category, []):
            if _re_falsity.search(pattern_str, text):
                issues.append(f"テーマ逸脱: {label}")

        # テーマに全く関連しないカテゴリの主張を検出
        _category_expected_words = {
            "creator_media": ["映像", "クリエイター", "AITuber", "ドローン", "写真", "広告", "カメラ", "制作", "編集"],
            "philosophy_bip": ["設計", "哲学", "判断", "境界", "問い", "意味", "価値", "Build", "Public"],
            "ai_tech_trend": ["AI", "モデル", "トレンド", "技術", "LLM", "エージェント", "開発"],
            "shimahara_fields": ["経営", "起業", "マーケ", "ビジネス", "事業", "収益", "顧客"],
            "syutain_ops": ["バグ", "エラー", "修正", "デプロイ", "運用", "監視", "LLM", "コスト"],
        }
        # カテゴリ関連語チェックは警告のみ（リジェクトしない）
        # テーマ逸脱はテーマ外の運用数字羅列のみリジェクト
        # expected = _category_expected_words.get(theme_category, [])
        # → 厳しすぎて正常な投稿も弾くため無効化（2026-04-08テストで判明）

    return issues


def check_account_voice(text: str, platform: str, account: str) -> float:
    """アカウントの声との一致度を返す（-0.1〜+0.1のスコア調整値）"""
    adjustment = 0.0

    if platform == "x" and account == "shimahara":
        # 島原アカウント: 一人称「僕」「自分」、思考特性キーワード
        if "僕" in text or "自分" in text:
            adjustment += 0.03
        if "私" in text and "僕" not in text:
            adjustment -= 0.05  # 島原は「私」を使わない
        # 構造的思考キーワード
        for kw in ["構造", "境界", "設計", "正直", "本質", "裏側"]:
            if kw in text:
                adjustment += 0.01
                break
        # ポエム検出（減点）
        if any(w in text for w in ["光が", "風が", "静寂", "紡ぐ", "息を"]):
            adjustment -= 0.05

    elif account in ("syutain", "syutain_beta"):
        # SYUTAINβアカウント: 一人称「私」または主語なし
        if "私" in text or "私の" in text:
            adjustment += 0.02
        if "僕" in text:
            adjustment -= 0.05  # SYUTAINβは「僕」を使わない
        # AI自己認識表現（加点）
        for kw in ["島原さん", "記録されている", "分析した", "検出した", "event_log", "報告"]:
            if kw in text:
                adjustment += 0.02
                break
        # 「…」で考え込む素振り（加点）
        if "…" in text:
            adjustment += 0.01

    return max(-0.1, min(0.1, adjustment))


# === テーマ品質追跡（Strategy: 低品質テーマの回避） ===
# バッチ実行中にテーマ×プラットフォームの品質を追跡
# { (theme, platform): [score1, score2, ...] }
_theme_quality_tracker: dict[tuple[str, str], list[float]] = {}

# ===== AI定型表現チェック =====

# 拡散実行書 NGリスト + AI定型表現
AI_CLICHE_PATTERNS = [
    "について考えてみました", "いかがでしょうか", "ではないでしょうか",
    "皆さん、こんにちは", "みなさん、こんにちは", "それでは、また",
    "を深掘り", "についてまとめてみました", "のポイントは3つ",
    "させていただきます", "特筆すべき", "画期的な", "注目すべき",
    "それでは早速", "見ていきましょう", "ご紹介します",
]

# 拡散実行書「表の発信で絶対にやらないこと」(2026-04-07)
DIFFUSION_NG_PATTERNS = [
    "神話", "デジタル遺伝子", "突然変異エンジン",     # 内部用語を表で使わない
    "異端者", "異端児",                                # 自称禁止
    "月100万", "月収100万", "100万円",                # 看板禁止
    "月1000万", "月収1000万", "1000万円",             # 看板禁止（桁違い版）
    "コード書けないおっさん", "おっさん",              # 弱者描写禁止
    "これはドキュメンタリーです",                      # 説明禁止
    "AIすごい", "AIって凄い", "AIの未来は",            # 抽象論禁止
    "未来はこうなる", "これからの時代",                # 抽象論禁止
]


def _count_x_chars(text: str) -> int:
    """X (Twitter) の文字カウント: CJK=2文字、ASCII=1文字（Twitter API準拠）"""
    count = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            count += 2
        else:
            count += 1
    return count


def _truncate_for_x(text: str, limit: int = 150) -> str:
    """日本語150文字以内で切り詰め（文末で自然に切る）"""
    if len(text) <= limit:
        return text
    # 文末（。！？…）で切れるポイントを探す
    candidates = []
    for i, ch in enumerate(text[:limit]):
        if ch in "。！？…\n":
            candidates.append(i + 1)
    if candidates:
        # 最後の文末で切る
        cut = candidates[-1]
        if cut >= limit * 0.5:  # 半分以上あれば採用
            return text[:cut].rstrip()
    # 文末が見つからない場合は150字で切って「…」
    return text[:limit - 1].rstrip() + "…"


_PERSONA_KEYWORDS = [
    "映像", "VFX", "AITuber", "ドローン", "撮影", "編集",
    "失敗", "挫折", "挑戦", "学び", "実験",
    "AI", "自律", "OS", "SYUTAINβ",
]


# 多軸品質評価（SNS投稿向け）
def _score_multi_axis(text: str, persona_keywords: list[str] = None,
                      theme: str = "", theme_category: str = "",
                      platform: str = "", account: str = "") -> float:
    """SNS投稿の品質を10軸で算出（0.0-1.0）

    V2改善 (2026-04-08):
    - テーマ関連性の軸を追加（テーマに沿った内容かどうか）
    - 事実密度がLLM数字で稼げる問題を修正（テーマ外の運用数字は加点しない）
    - ペルソナ一致をアカウント別に評価（shimahara思考特性語/syutain自己認識語）
    """
    if not text or len(text) < 10:
        return 0.0

    import re

    # === ハードフェイル検出（スコア上限0.30） ===
    hard_fail = False

    # 中国語混入検出
    _chinese_pat = re.compile(r'[\u4e00-\u9fff]')
    _japanese_pat = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
    if _chinese_pat.search(text) and not _japanese_pat.search(text[:100]):
        hard_fail = True

    # 島原大知の読み間違い検出（正: しまはらだいち）
    _wrong_readings = ["うらわら", "おおとも", "しまばらだいち", "しまはらたいち",
                       "とうげんだいち", "しまはらおおち"]
    for wr in _wrong_readings:
        if wr in text:
            hard_fail = True
            break

    # AI自己開示検出
    _ai_disclosure = ["AIです", "仮の私（AI）", "私はAIが", "AIである私",
                      "AIとして", "私はAI", "AIの私"]
    for adp in _ai_disclosure:
        if adp in text:
            hard_fail = True
            break

    # 繰り返しポエムパターン検出（スコア上限0.30）
    # 部分一致で検出（「風が止み」「風はもう止んだ」「風は止んだ」等のバリエーション全て捕捉）
    import re as _re
    _overused_poem_patterns = [
        _re.compile(r"風[がはも]*[とう]*[に]*(止[みんまっ]|やん)"),  # 風が止み, 風はもう止んだ, etc
        _re.compile(r"画面[はが]*真っ[暗黒]"),  # 画面は真っ暗, 画面は真っ黒
        _re.compile(r"息を[殺ひ]"),  # 息を殺し, 息をひそめ
        _re.compile(r"カット[はがも]*[続まつ]"),  # カットは続いて, カットが続く
        _re.compile(r"光の粒子"),
        _re.compile(r"指先[をにで]"),  # 指先を伸ばす, 指先に光
        _re.compile(r"紡[ぎぐ]"),  # 紡ぎ出す, 紡ぐ
        _re.compile(r"肩を[落お]"),  # 肩を落とし
        _re.compile(r"カラーグレーディング"),
        _re.compile(r"シャッター[をに]"),
        _re.compile(r"夕暮れ.{0,5}デスク"),
        _re.compile(r"湯気.{0,10}(コーヒー|カップ|冷め)"),
        _re.compile(r"静かに.{0,5}(光|息|待|点滅|降り)"),
        _re.compile(r"未完成の.{0,5}(シナリオ|映像|カット)"),
        # 2026-04-05追加: ドローン/赤文字/緊急停止系のポエム
        _re.compile(r"ドローン.{0,15}(プロペラ|地面|止ま|動かな|着陸|降り|静か)"),
        _re.compile(r"赤[いくでで]*文字"),
        _re.compile(r"\d+回[目も]?.{0,10}(強制|緊急|シャットダウン|停止|再起動)"),
        _re.compile(r"空[はが].{0,10}(真っ[暗黒]|紺|暗|夜|静か)"),
        _re.compile(r"誰もいな[いく]"),
        _re.compile(r"バッテリー.{0,5}(切れ|落ち|消え)"),
        _re.compile(r"プロペラ.{0,10}(止|動かな)"),
        _re.compile(r"画面[にはが].{0,10}(エラー|ログ|流れ)"),
    ]
    _poem_hits = sum(1 for p in _overused_poem_patterns if p.search(text))
    if _poem_hits >= 2:
        hard_fail = True

    # --- 軸1: 人間味 (0-1, w=0.17) ---
    # 口語表現、感情語、不完全さ、独白感が高評価
    human_score = 0.35  # ベースライン（0.3→0.35: 日本語の普通の文でも最低限の人間味あり）
    # 口語・砕けた表現
    casual_markers = ["けど", "だけど", "やん", "やろ", "やし", "わ。", "な。", "ね。",
                      "って", "じゃない", "かな", "だよね", "…", "。。", "ふと",
                      "うーん", "まぁ", "ちょい", "ちょっと"]
    casual_count = sum(1 for m in casual_markers if m in text)
    human_score += min(0.4, casual_count * 0.08)
    # 感情・内省表現
    emotion_markers = ["思う", "感じ", "気づ", "悩", "迷", "嬉し", "悔し", "怖",
                       "楽し", "寂し", "驚", "つら", "疲れ", "なるほど"]
    emotion_count = sum(1 for m in emotion_markers if m in text)
    human_score += min(0.3, emotion_count * 0.10)

    # --- 軸2: アカウント別ペルソナ一致 (0-1, w=0.17) ---
    persona_score = 0.25  # ベースライン
    if platform == "x" and account == "shimahara":
        # 島原アカウント: 思考特性語で評価
        _shimahara_voice = ["構造", "境界", "正直", "本質", "裏側", "設計", "壊れ",
                            "人", "具体", "現実", "でも", "だが", "僕"]
        matches = sum(1 for kw in _shimahara_voice if kw in text)
        persona_score = min(1.0, 0.25 + matches * 0.08)
    elif account in ("syutain", "syutain_beta"):
        # SYUTAINβアカウント: 自己認識語で評価
        _syutain_voice = ["私", "記録", "検出", "分析", "報告", "実行", "島原さん",
                          "event_log", "設計者", "判断", "…"]
        matches = sum(1 for kw in _syutain_voice if kw in text)
        persona_score = min(1.0, 0.25 + matches * 0.08)
    else:
        # 汎用: 従来のキーワードマッチ
        if persona_keywords:
            matches = sum(1 for kw in persona_keywords if kw in text)
            if matches >= 3: persona_score = 0.9
            elif matches == 2: persona_score = 0.7
            elif matches == 1: persona_score = 0.5
    # SYUTAINβ共通コンテキスト（全アカウント共通で加点）
    syutain_context = ["事業OS", "パイプライン", "エージェント", "ノード"]
    for ctx in syutain_context:
        if ctx in text:
            persona_score = min(1.0, persona_score + 0.10)

    # --- 軸3: 完結性 (0-1, w=0.20) ---
    # 文が自然に終わっているか、途中で切れていないか
    completeness = 0.5  # ベースライン
    text_stripped = text.rstrip()
    # 自然な終わり方
    if text_stripped.endswith(("。", "！", "？", "…", "」", "）", "w", "笑")):
        completeness = 0.8
    elif text_stripped.endswith((".", "!", "?")):
        completeness = 0.7
    # "..."で途切れている（トランケーション）
    if text_stripped.endswith("...") and not text_stripped.endswith("。..."):
        completeness = 0.2
    # 開き括弧が閉じていない
    open_paren = text.count("（") + text.count("「") + text.count("(")
    close_paren = text.count("）") + text.count("」") + text.count(")")
    if open_paren > close_paren:
        completeness = max(0.1, completeness - 0.3)
    # 文の数（1文だと短すぎ、10文以上だと長すぎ）
    sentences = [s for s in re.split(r'[。！？\n]', text) if len(s.strip()) > 0]
    sent_count = len(sentences)
    if sent_count == 0:
        completeness = max(0.1, completeness - 0.3)
    elif 2 <= sent_count <= 6:
        completeness = min(1.0, completeness + 0.2)

    # --- 軸4: エンゲージメント予測 (0-1, w=0.13) ---
    # 共感、問いかけ、余韻、会話のきっかけ
    engagement = 0.30  # ベースライン（0.2→0.30: SNS投稿は本質的にエンゲージメント志向）
    # 問いかけ
    if "？" in text or "?" in text or "かな" in text:
        engagement += 0.25
    # 余韻（三点リーダー）
    if "…" in text:
        engagement += 0.10
    # 共感ポイント（あるある、失敗談、本音吐露）
    empathy_markers = ["失敗", "やらかし", "反省", "学んだ", "気づいた",
                       "正直", "本音", "実は", "ぶっちゃけ"]
    if any(m in text for m in empathy_markers):
        engagement += 0.20
    # 具体的な行動やシーン描写
    scene_markers = ["朝", "夜", "昼", "編集室", "現場", "画面", "カメラ", "モニター"]
    if any(m in text for m in scene_markers):
        engagement += 0.10
    # CTA（明示的な呼びかけ）— SNSでは軽い方が良い
    if any(m in text for m in ["どう思う", "みんなは", "経験ある"]):
        engagement += 0.15
    engagement = min(1.0, engagement)

    # --- 軸5: AI臭さの無さ (0-1, w=0.15) ---
    ai_penalty = 0.0
    for p in AI_CLICHE_PATTERNS:
        if p in text:
            ai_penalty += 0.20
    # 追加: 過剰な丁寧語もAI臭い
    polite_excess = text.count("ます。") + text.count("です。") + text.count("ございます")
    if polite_excess >= 4:
        ai_penalty += 0.15
    # 同じ語尾の連続
    endings = re.findall(r'(?:です|ます|ません|でしょう)[。！？]', text)
    if len(endings) >= 3:
        unique_ratio = len(set(endings)) / len(endings)
        if unique_ratio < 0.5:
            ai_penalty += 0.15
    ai_score = max(0.0, 1.0 - ai_penalty)

    # --- 軸6: 読みやすさ (0-1, w=0.10) ---
    readability = 0.5
    if sentences:
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        # SNS投稿の最適文長: 15-35文字
        if 15 <= avg_len <= 35:
            readability = 0.9
        elif 10 <= avg_len <= 50:
            readability = 0.7
        elif avg_len > 80:
            readability = 0.3
        else:
            readability = 0.5
    # 改行によるリズム（SNSでは効果的）
    newline_count = text.count("\n")
    if 1 <= newline_count <= 8:
        readability = min(1.0, readability + 0.1)

    # --- 軸7: daichi_content_patterns構造準拠 (0-1, w=0.16) ---
    # Phase A: 具体的場面から入る / Phase D: 核心の一文 / Phase E: 行動宣言で終わる
    structure_score = 0.35  # ベースライン（0.3→0.35: 構造パターンに完全一致しなくても基本的な構造はある）
    first_line = text.split("\n")[0] if "\n" in text else text[:80]
    last_line = text.strip().split("\n")[-1] if "\n" in text else text[-80:]

    # Phase A: 具体的な事実・体験から入るパターン（高評価）
    # 注意: 情景語（朝/夜/画面/モニター/椅子/机/カフェ/編集室）は削除 — ポエム誘発語のため
    concrete_openers = [
        "昨日", "さっき", "今日", "先日", "この前",
        "僕は", "私は", "自分", "正直", "ふと", "実は", "気づいた",
        "やらかした", "失敗", "壊れ", "止まっ", "動かな",
    ]
    if any(m in first_line for m in concrete_openers):
        structure_score += 0.25
    # 自己開示（弱さ、葛藤、失敗）が冒頭にある → ボーナス
    vulnerability_openers = ["できない", "わからな", "怖", "迷", "悩", "不安", "つら"]
    if any(m in first_line for m in vulnerability_openers):
        structure_score += 0.10
    # 抽象的AI論・一般論から入るパターン（ペナルティ）
    abstract_openers = [
        "AIは", "AI時代", "AIが", "人工知能", "テクノロジー",
        "近年", "昨今", "現代", "これからの時代",
        "〜について", "考えてみ", "注目され",
    ]
    if any(m in first_line for m in abstract_openers):
        structure_score -= 0.25

    # Phase D: 核心の一文（太字 **...** や短い断言文）
    if "**" in text:
        structure_score += 0.15  # 太字の核心文がある
    elif any(s.strip() for s in re.findall(r'(?:^|\n)(.{5,30})[。！]', text)
             if not any(w in s for w in ["です", "ます", "ました"])):
        structure_score += 0.05  # 短い断言文がある

    # Phase E: 行動宣言で終わる（「だからこうする」「次はこれをやる」）
    action_endings = [
        "する", "やる", "作る", "始める", "変える", "試す", "挑む",
        "届ける", "残す", "繋ぐ", "壊す", "直す", "進む",
    ]
    if any(last_line.rstrip("。！？…").endswith(v) for v in action_endings):
        structure_score += 0.15
    # 評論家的な締め（ペナルティ）
    passive_endings = ["でしょう", "ではないでしょうか", "と思います", "が大切です",
                       "が重要です", "が求められます"]
    if any(e in last_line for e in passive_endings):
        structure_score -= 0.15

    structure_score = max(0.0, min(1.0, structure_score))

    # --- 加重合計 ---
    # === 軸8: 事実密度 (0-1, w=0.20) — ポエム化の構造的防止 ===
    # 具体的な数字・固有名詞・SYUTAINβ実イベント用語の含有を評価
    import re as _re_fd
    # 数字（半角・全角）
    numbers = _re_fd.findall(r'\d+', text)
    numbers_fullwidth = _re_fd.findall(r'[0-9]+', text)
    number_count = len(numbers) + len(numbers_fullwidth)
    # 固有名詞（英数字3文字以上、カタカナ3文字以上、システム用語）
    english_entities = set(_re_fd.findall(r'[A-Za-z][A-Za-z0-9_.\-]{2,}', text))
    system_terms = [
        "SYUTAINβ", "SYUTAIN", "Claude", "GPT", "Qwen", "DeepSeek", "Ollama",
        "CORTEX", "FANG", "NERVE", "FORGE", "MEDULLA", "SCOUT",
        "ALPHA", "BRAVO", "CHARLIE", "DELTA",
        "LoopGuard", "Discord", "Bluesky", "Threads", "note",
        "PostgreSQL", "NATS", "Tailscale", "Playwright", "Python",
        "intel_items", "posting_queue", "persona_memory",
    ]
    system_term_count = sum(1 for t in system_terms if t in text)
    # 円/¥/円マーク付き金額
    money_count = len(_re_fd.findall(r'[¥￥]\s*\d+|\d+\s*円', text))

    fact_density_score = 0.1  # ベースライン（最低）

    # V2: LLM数字固着防止 — syutain_ops以外では運用数字（呼び出し回数/コスト/行数）を減点
    _ops_number_patterns = _re_fd.findall(r'(?:LLM|呼び出し|コスト|¥|行数|Python)\s*[\d,]+', text)
    _is_ops_theme = theme_category == "syutain_ops" or "運用" in theme or "SYUTAINβ" in theme
    if _ops_number_patterns and not _is_ops_theme:
        # テーマ外で運用数字を入れている → 加点しない（固着防止）
        number_count = max(0, number_count - len(_ops_number_patterns))

    if number_count >= 3: fact_density_score += 0.35
    elif number_count >= 2: fact_density_score += 0.25
    elif number_count >= 1: fact_density_score += 0.15
    if system_term_count >= 3: fact_density_score += 0.30
    elif system_term_count >= 2: fact_density_score += 0.20
    elif system_term_count >= 1: fact_density_score += 0.10
    if money_count >= 1 and _is_ops_theme: fact_density_score += 0.15  # 金額もops以外では加点しない
    fact_density_score = min(1.0, fact_density_score)

    # === 軸9: 情景密度ペナルティ — 情景語の過剰使用を検出 ===
    scene_words = [
        "光", "影", "闇", "静か", "紺", "深夜", "空", "風", "雲",
        "プロペラ", "ドローン", "カメラ", "画面", "モニター",
        "デスク", "椅子", "机", "カフェ", "窓", "扉",
    ]
    scene_hits = sum(text.count(w) for w in scene_words)
    scene_density = scene_hits / max(1, len(text) / 30)  # 30字あたりの情景語数
    # 情景密度が高く、事実密度が低い → ポエム確定
    if scene_density > 0.5 and fact_density_score < 0.3:
        hard_fail = True

    # --- 軸10: テーマ関連性 (0-1, w=0.12) ---
    theme_relevance = 0.3  # ベースライン
    if theme:
        _theme_words = [w for w in theme.replace("【", "").replace("】", "").split() if len(w) >= 2][:5]
        _theme_hits = sum(1 for tw in _theme_words if tw in text)
        theme_relevance = min(1.0, 0.3 + _theme_hits * 0.15)
    # テーマカテゴリに対応するキーワードチェック
    _cat_keywords = {
        "ai_tech_trend": ["AI", "モデル", "トレンド", "最新", "技術"],
        "creator_media": ["映像", "クリエイター", "AITuber", "ドローン", "写真", "広告"],
        "philosophy_bip": ["設計", "哲学", "判断", "Build", "Public", "境界"],
        "shimahara_fields": ["経営", "起業", "マーケ", "ビジネス", "委譲"],
        "syutain_ops": ["バグ", "修正", "エラー", "運用", "デプロイ", "障害"],
    }
    if theme_category and theme_category in _cat_keywords:
        _cat_hits = sum(1 for ck in _cat_keywords[theme_category] if ck in text)
        theme_relevance = min(1.0, theme_relevance + _cat_hits * 0.10)

    # --- 軸11: ユーモア密度 (X syutainのみ, 0-1, w=0.12) ---
    humor_density = 0.45  # ベースライン（ユーモアなしでも旧重みと同等のスコアになるよう調整）
    if platform == "x" and account == "syutain":
        try:
            from strategy.net_meme_vocabulary import NET_SLANG, NICONICO_SLANG, NICHAN_SLANG, COMEDY_PHRASES, ANIME_PHRASES, MOVIE_PHRASES
            _all_slang = {**NET_SLANG, **NICONICO_SLANG, **NICHAN_SLANG}
            _slang_hits = sum(1 for k in _all_slang if k in text)
            if _slang_hits >= 1: humor_density += 0.25
            _phrase_hits = sum(1 for k in ANIME_PHRASES if k in text) + sum(1 for k in COMEDY_PHRASES if k in text) + sum(1 for k in MOVIE_PHRASES if k in text)
            if _phrase_hits >= 1: humor_density += 0.25
        except Exception:
            pass
        # 構造的ユーモア検出
        if "…" in text and any(w in text for w in ["だが", "でも", "ただし", "しかし"]):
            humor_density += 0.15
        if text.rstrip().endswith(("。", "…")) and len(text) < 80:
            humor_density += 0.10
        humor_density = min(1.0, humor_density)

    # 重み配分V3: X syutainはユーモア密度軸を追加、他は従来配分
    if platform == "x" and account == "syutain":
        score = (
            fact_density_score * 0.14 +
            theme_relevance * 0.10 +
            structure_score * 0.12 +
            human_score * 0.10 +
            persona_score * 0.12 +
            completeness * 0.10 +
            engagement * 0.08 +
            ai_score * 0.08 +
            readability * 0.04 +
            humor_density * 0.12
        )
    else:
        score = (
            fact_density_score * 0.16 +
            theme_relevance * 0.12 +
            structure_score * 0.14 +
            human_score * 0.12 +
            persona_score * 0.14 +
            completeness * 0.12 +
            engagement * 0.08 +
            ai_score * 0.08 +
            readability * 0.04
        )
    score = round(max(0.0, min(1.0, score)), 3)

    # ハードフェイル: 中国語混入・名前誤読・AI自己開示・情景過剰 → 上限0.30
    if hard_fail:
        score = min(score, 0.30)

    return score


def _check_ai_cliche(text: str) -> bool:
    """AI定型表現が含まれていればTrue"""
    for p in AI_CLICHE_PATTERNS:
        if p in text:
            return True
    # 拡散実行書 NG パターン (2026-04-07)
    for p in DIFFUSION_NG_PATTERNS:
        if p in text:
            return True
    # 絵文字3個以上
    import re
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF\U00002702-\U000027B0]', text))
    if emoji_count >= 3:
        return True
    # ハッシュタグ3個以上
    if text.count('#') >= 3:
        return True
    # 拡散実行書の品質基準: 抽象論・ポエム・自虐・システム紹介型は却下
    # 具体的な数字/出来事/学び/問い の最低1つが必要
    has_number = bool(re.search(r'\d{2,}', text))  # 2桁以上の数字
    has_concrete = bool(re.search(r'¥[\d,]+|[\d,]+円|[\d,]+行|[\d,]+回|[\d,]+件|[\d,]+日|[\d.]+%', text))
    has_question = text.rstrip().endswith('？') or '？' in text
    if not (has_number or has_concrete or has_question):
        # 数字も問いもない = 抽象論の可能性。ただし短文(80字未満)は除外
        if len(text) >= 80:
            return True
    return False


async def _check_sns_factual(content: str, platform: str = "", account: str = "") -> tuple[bool, str]:
    """事実誤認・禁止表現・パターン固着を検出する。
    Returns (passed, reason). passedがFalseの場合、投稿を再生成すべき。
    """
    # --- 禁止表現チェック ---
    forbidden = [
        ("コードを書", "島原はコードを書けない非エンジニア"),
        ("コードを打", "島原はコードを打てない非エンジニア"),
        ("プログラミング", "島原はプログラミングしない"),
        ("コーディング", "島原はコーディングしない"),
        ("再コンパイル", "島原はコンパイル作業をしない"),
        ("コンパイル", "島原はコンパイルしない"),
        ("デバッグして", "島原はデバッグ作業をしない（SYUTAINβがやる）"),
        ("僕の音楽", "音楽は趣味であり仕事ではない"),
        ("曲を作", "音楽制作は趣味であり仕事ではない"),
        ("作曲", "作曲は仕事ではない"),
        ("メロディーを紡", "音楽表現は禁止"),
    ]
    for phrase, reason in forbidden:
        if phrase in content:
            return False, f"禁止表現検出: 「{phrase}」— {reason}"

    # --- VTuber固有話題（ハレーション回避。AITuberは許容） ---
    _topic_scan_text = content.replace("AITuber", "").replace("aituber", "")
    vtuber_markers = ["VTuber", "vtuber", "ホロライブ", "にじさんじ", "kson", "清楚担当"]
    if any(marker in _topic_scan_text for marker in vtuber_markers):
        return False, "VTuber固有話題を検出（投稿方針で回避対象）"

    # --- ハレーション表現（対立煽り・自己否定・過剰擬人化） ---
    inflammatory_patterns = [
        ("承認欲求", "自己否定/煽り語のため投稿品質を毀損する"),
        ("君たち人類", "読者との対立を煽る表現は避ける"),
        ("感情はデータだけ", "人格演出の過剰擬人化は事実誤認を誘発する"),
        ("勝手に動いてる", "運用実態を曖昧化する表現は禁止"),
        ("追いつけてない気が", "根拠のない不安煽り表現は禁止"),
    ]
    for phrase, reason in inflammatory_patterns:
        if phrase in content:
            return False, f"ハレーション表現検出: 「{phrase}」— {reason}"

    # --- 中国語混線/文字化け系（意図しない多言語混在） ---
    chinese_markers = [
        "小时", "我们", "这是", "现象", "因为", "你们", "不是", "分钟内", "失败是", "流行",
    ]
    if sum(1 for marker in chinese_markers if marker in content) >= 2:
        return False, "多言語混線検出: 中国語フレーズが混在（日本語投稿ルール違反）"

    # --- 扇情的で検証不能な断定表現 ---
    import re as _re_fact
    sensational_patterns = [
        (r'IQ\s*\d{2,3}', "IQ断定は検証不能で誤情報リスクが高い"),
        (r'99(?:\.\d+)?%\s*の?人類', "優越率の断定は誤情報リスクが高い"),
        (r'人類を(?:凌駕|超え)', "人類超越の断定はハレーションを招く"),
        (r'急騰', "煽り語は避ける"),
    ]
    for pat, reason in sensational_patterns:
        if _re_fact.search(pat, content):
            return False, f"誇張断定検出: {reason}"

    # --- 外部主張の出典不足（%改善・再生回数など） ---
    _source_markers = ("http://", "https://", "出典", "一次情報", "source")
    _internal_markers = ("SYUTAINβ", "LLM", "event_log", "posting_queue", "直近", "累計", "呼び出し")
    _has_source = any(m in content for m in _source_markers)
    _has_internal_context = any(m in content for m in _internal_markers)
    _external_percent_claim = _re_fact.search(
        r'\d+(?:\.\d+)?\s*%[^。]*'
        r'(?:増加|減少|向上|改善|短縮|上昇|低下|急増|急落|伸び)',
        content,
    )
    # SYUTAINβ 内部スコア由来の % は直前 15 文字以内にマーカーがある場合のみ免除 (2026-04-11)
    _score_markers_factual = (
        "スコア", "品質", "精度", "確度", "達成率", "カバレッジ",
        "ギャップ", "importance", "quality", "score",
    )
    if _external_percent_claim and not (_has_source or _has_internal_context):
        _pct_start = _external_percent_claim.start()
        _ctx_pre = content[max(0, _pct_start - 15):_pct_start]
        if not any(mk in _ctx_pre for mk in _score_markers_factual):
            return False, "出典なしの外部効果数値（%）を検出"

    _external_view_claim = _re_fact.search(r'\d+(?:\.\d+)?\s*(?:万|億)?回(?:視聴|再生)', content)
    if _external_view_claim and not (_has_source or _has_internal_context):
        return False, "出典なしの視聴/再生回数断定を検出"

    # --- 軍事・攻撃用途の断定表現 ---
    military_markers = [
        "敵位置", "迎撃", "警告信号", "自動送信", "攻撃", "戦闘", "命中", "防衛システム",
    ]
    if any(marker in content for marker in military_markers):
        return False, "軍事/攻撃用途の断定表現を検出（投稿方針で禁止）"

    # --- 障害・失敗の単純列挙を抑止（事象→原因→対策を要求） ---
    failure_markers = ["投稿失敗", "sns.post_failed", "失敗が", "失敗、", "failed"]
    has_failure = any(m in content for m in failure_markers)
    if has_failure:
        has_followup = any(
            w in content for w in [
                "原因", "対策", "修正", "再発防止", "見直し", "改善", "次は", "だから", "対応",
            ]
        )
        if not has_followup:
            return False, "失敗の列挙のみ（原因/対策がない）"

    # --- 島原アカウントでの一人称「私」チェック ---
    # X島原の投稿で「私」が使われていたら拒否（「私」はSYUTAINβの一人称）
    if account == "shimahara" and "私" in content:
        # 「私」が引用や他者の言葉の中にある可能性を考慮
        # ただし単純に含まれていたら拒否（安全側に倒す）
        return False, "島原の一人称は「僕」「自分」。「私」はSYUTAINβの一人称"

    # --- 「深夜」パターン固着チェック ---
    if content.strip().startswith("深夜"):
        try:
            async with get_connection() as conn:
                recent_rows = await conn.fetch(
                    """SELECT content FROM posting_queue
                       WHERE platform = $1 AND status IN ('pending', 'posted')
                         AND created_at > NOW() - INTERVAL '3 days'
                       ORDER BY created_at DESC LIMIT 30""",
                    platform or "x",
                )
                if recent_rows:
                    shinya_count = sum(
                        1 for r in recent_rows
                        if (r["content"] or "").strip().startswith("深夜")
                    )
                    ratio = shinya_count / len(recent_rows)
                    if ratio > 0.30:
                        return False, f"「深夜」開始のパターン固着（直近{len(recent_rows)}件中{shinya_count}件={ratio:.0%}）"
        except Exception as e:
            logger.debug(f"深夜パターンチェックDB失敗（続行）: {e}")

    return True, ""


def _get_time_period(time_str: str) -> str:
    """時刻文字列→時間帯"""
    hour = int(time_str.split(":")[0])
    if 10 <= hour < 13:
        return "morning"
    elif 13 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 20:
        return "evening"
    else:
        return "night"


def _pick_theme(time_str: str, used_today: list[str], recent_themes: list[str],
                 platform: str = "", historical_quality: dict[str, float] = None,
                 engagement_weights: dict[str, float] = None) -> str:
    """テーマを選択（重複回避+時間帯重み+品質フィードバック+エンゲージメント重み）

    Args:
        historical_quality: テーマ→平均品質スコアの辞書（過去7日のDB実績）
        engagement_weights: テーマ→エンゲージメント重み倍率（1.0=平均、2.0=高パフォ）
    """
    period = _get_time_period(time_str)
    weights = TIME_THEME_WEIGHTS.get(period, {})

    # 直近7日で3回以上使われたテーマを除外
    from collections import Counter
    theme_counts = Counter(recent_themes)
    excluded = {t for t, c in theme_counts.items() if c >= 3}

    # 今日同じテーマが3回以上なら除外
    today_counts = Counter(used_today)
    for t, c in today_counts.items():
        if c >= 3:
            excluded.add(t)

    # バッチ内でアンダーパフォームしているテーマを除外
    if platform:
        for t in THEME_POOL:
            if _is_theme_underperforming(t, platform):
                excluded.add(t)

    available = [t for t in THEME_POOL if t not in excluded]
    if not available:
        available = THEME_POOL.copy()

    # 重み付きランダム（時間帯重み + 品質フィードバック重み + エンゲージメント重み）
    weighted = []
    threshold = _get_quality_threshold(platform) if platform else DEFAULT_QUALITY_THRESHOLD
    for t in available:
        w = weights.get(t, 1)
        # 過去の品質データに基づく重み調整
        inferred_category = _infer_theme_category(t)
        if historical_quality and inferred_category in historical_quality:
            avg_q = historical_quality[inferred_category]
            if avg_q >= threshold + 0.05:
                w = int(w * 2)   # 高品質テーマは重みを2倍
            elif avg_q < threshold - 0.05:
                w = max(1, w - 1)  # 低品質テーマは重みを減らす
        # エンゲージメント実績に基づく重み調整
        if engagement_weights and t in engagement_weights:
            eng_mult = engagement_weights[t]
            w = max(1, int(w * eng_mult))
        weighted.extend([t] * w)

    return random.choice(weighted)


def _random_offset_minutes() -> int:
    """0〜8分のランダムオフセット（早期投稿を避けるため正の値のみ）"""
    return random.randint(0, 8)


def _get_quality_threshold(platform: str) -> float:
    """プラットフォーム別の品質閾値を返す"""
    return PLATFORM_QUALITY_THRESHOLDS.get(platform, DEFAULT_QUALITY_THRESHOLD)


def _track_theme_quality(theme: str, platform: str, score: float) -> None:
    """テーマ×プラットフォームの品質スコアを記録（バッチ内追跡）"""
    key = (theme, platform)
    if key not in _theme_quality_tracker:
        _theme_quality_tracker[key] = []
    _theme_quality_tracker[key].append(score)


def _is_theme_underperforming(theme: str, platform: str) -> bool:
    """このバッチ内でテーマが低品質を連続しているか判定"""
    key = (theme, platform)
    scores = _theme_quality_tracker.get(key, [])
    if len(scores) < 2:
        return False
    # 直近2回とも閾値未満ならアンダーパフォーム
    threshold = _get_quality_threshold(platform)
    return all(s < threshold for s in scores[-2:])


async def _load_historical_theme_quality(conn, platform: str) -> dict[str, float]:
    """過去7日のテーマ×プラットフォーム別の平均品質スコアをDBから取得"""
    try:
        rows = await conn.fetch(
            """SELECT theme_category, AVG(quality_score) as avg_score,
                      COUNT(*) as cnt
               FROM posting_queue
               WHERE platform = $1
                 AND created_at > NOW() - INTERVAL '7 days'
                 AND quality_score > 0
               GROUP BY theme_category
               HAVING COUNT(*) >= 3""",
            platform,
        )
        return {r["theme_category"]: float(r["avg_score"]) for r in rows if r["theme_category"]}
    except Exception as e:
        logger.debug(f"テーマ品質履歴取得失敗: {e}")
        return {}


def _load_writing_style() -> str:
    """daichi_writing_style.md読み込み"""
    path = STRATEGY_DIR / "daichi_writing_style.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


# ===== プロンプト構築 =====

def _build_prompt(platform: str, account: str, theme: str, time_str: str,
                  writing_style: str, few_shot: list[str], recent_posts: list[str],
                  persona_hint: str = "", factbook_prompt: str = "",
                  picked_facts: list = None, buzz_prompt: str = "",
                  materials: list = None) -> tuple[str, str]:
    """platform+accountに応じたプロンプトを構築。(system_prompt, user_prompt)を返す"""

    period = _get_time_period(time_str)
    avoid = "\n".join(f"- {p[:60]}" for p in recent_posts[:5]) if recent_posts else "（なし）"

    # ファクトブック注入 — ポエム化防止の核心
    # テーマに関連するファクトのみを注入（全ファクト注入は固着の原因）
    fact_injection = ""
    if picked_facts:
        def _fact_to_str(f):
            if isinstance(f, str):
                return f
            if hasattr(f, 'fact_text'):
                return f.fact_text
            if hasattr(f, 'to_prompt_line'):
                return f.to_prompt_line()
            if isinstance(f, dict):
                return f.get('text', f.get('fact', str(f)))
            return str(f)
        facts_text = "\n".join(f"- {_fact_to_str(f)}" for f in picked_facts[:3])
        fact_injection = (
            f"\n\n## 【材料】テーマに関連する事実\n"
            f"{facts_text}\n"
            f"**上記から1つを核にする。ただしテーマとの関連が薄いものは無視してよい。**\n"
            f"**テーマの話題を中心に書け。SYUTAINβの運用数字（LLM呼び出し回数、コスト、コード行数）を毎回入れるな。**\n"
        )
    elif factbook_prompt:
        # picked_factsがない場合のみ全体ファクトブックを使う（フォールバック）
        fact_injection = (
            f"\n\n## 【材料】以下の事実を参考にせよ\n"
            f"{factbook_prompt}\n"
            f"**テーマの話題を中心に書け。運用数字の羅列は禁止。**\n"
        )

    # V2: 素材注入（テーマに関連する具体的素材。LLMはこれだけで書く）
    materials_injection = ""
    if materials:
        mat_text = "\n".join(f"- {m}" for m in materials[:5])
        materials_injection = (
            f"\n\n## 【素材】以下の事実を元に投稿を書け\n"
            f"{mat_text}\n"
            f"**上記の素材にない情報は書くな。素材だけで投稿を構成しろ。**\n"
        )

    # プラットフォーム別ボイスガイド注入（事実を各SNSの性質に合わせて料理する）
    voice_injection = ""
    try:
        from strategy.sns_platform_voices import build_voice_prompt
        voice_injection = "\n\n" + build_voice_prompt(platform, account)
    except Exception:
        pass

    # ユーモア構造ガイド + パターン選択 + トレンドミーム注入
    # X syutain のみ humor_injection を使用。他アカウントは削除。
    humor_injection = ""
    if platform == "x" and account == "syutain":
        try:
            from strategy.japanese_humor_patterns import build_humor_prompt, build_meme_context
            from strategy.humor_combination_patterns import pick_pattern, format_pattern_prompt
            humor_injection = build_humor_prompt(platform, account)
            # 投稿パターンを1つ選んでプロンプトに注入
            _humor_pattern = pick_pattern(theme_category="", platform=platform, account=account)
            if _humor_pattern:
                humor_injection += format_pattern_prompt(_humor_pattern)
            # intel_itemsからトレンドミーム素材を取得（本日分のみ）
            if materials:
                _meme_materials = [m for m in (materials or []) if "トレンド" in m or "ミーム" in m or "大喜利" in m]
                if _meme_materials:
                    humor_injection += "\n" + "\n".join(f"- {m[:150]}" for m in _meme_materials[:2])
        except Exception:
            pass

    # バズ・トレンド注入（参考素材、関連あれば取り入れる）
    buzz_injection = ""
    if buzz_prompt:
        buzz_injection = f"\n\n{buzz_prompt}"

    # === 共通 factual_rules（全アカウント共通、system_prompt に直接埋め込む） ===
    _common_factual_rules = (
        "\n【SYUTAINβと島原大知の関係（厳守）】\n"
        "- SYUTAINβは島原大知のデジタルツインを目指しているが、島原とは全く別の存在・個体である\n"
        "- SYUTAINβは島原の体験を自分の体験として語ってはならない。島原のことは「島原さん」として三人称で言及する\n"
        "- 外部ニュースについて書く時、島原やSYUTAINβが使った/担当した/体験したと書くな。観察・分析として書け\n"
        "- 「当社」「弊社」「我々のチーム」は存在しない。個人開発\n"
        "- 検証できない数値（〇%向上、〇倍改善等）を書くな\n"
        "\n【SYUTAINβの能力範囲】\n"
        "- できる: データ分析・集計、記事/投稿生成、情報収集・トレンド検出、スケジュール管理、島原との対話・記憶・学習\n"
        "- できない: 物理作業（撮影/編集/モデリング/制作/担当）、人間の体験（見た/食べた/会った）、外部プロジェクトへの参加\n"
        "- 外部ニュースは「〜が発表された」「〜と報告されている」と観察者として書け\n"
        "\n【島原大知の事実（厳守）】\n"
        "- コードを一行も書けない非エンジニア。本業は映像制作（VFX/カラグレ/撮影/ドローン）\n"
        "- VTuber業界8年（業界支援。VTuber活動はしていない）。SunoAI作詞は完全に趣味\n"
        "- SYUTAINβを開発中（AIエージェントと共に）。個人開発。チーム/同僚は存在しない\n"
        "\n【禁止】\n"
        "- コードを書く/プログラミングする記述\n"
        "- 使っていないツール名（Grafana/Prometheus/Datadog/Sentry）\n"
        "- 音楽を仕事として語る。「命名した」「考案した」（適用しているだけ）\n"
        "- 架空の数値・実績・機能の捏造。やっていないことを「やっている」と語る\n"
        "- AI定型: 「いかがでしょうか」「深掘り」「させていただきます」「特筆すべき」「画期的」\n"
        "- 煽り: 「誰でも簡単に」「絶対稼げる」「最短で月100万」「革命」\n"
        "- 情景描写・ポエム・抽象論で始める（全てリジェクト）\n"
        "- VTuber業界の話題は避けろ（AITuber側の話題ならOK）\n"
        "- 絵文字3個以上/ハッシュタグ（後処理で自動付与）\n"
    )

    # === 共通 content_structure_guide（全アカウント共通） ===
    _common_structure_guide = (
        "\n【ルール】\n"
        "- テーマの話題を中心に書け。LLM呼び出し回数やコードの行数は毎回入れるな\n"
        "- 素材にないことは書くな\n"
        "- **絶対禁止フレーズ（含むと自動リジェクト）**: 「風+止」「画面は真っ暗/黒」「息を殺」「光の粒子」「指先を伸ばす」「肩を落とし」「紡ぐ」「夕暮れ+デスク」「湯気+コーヒー/カップ」「静かに+光/息」「未完成の+シナリオ/映像」「ドローンのプロペラ」「赤文字/赤い文字」「N回目の緊急シャットダウン/強制停止」「空は真っ暗/紺」「誰もいない」「バッテリーが切れ」「画面にエラーログが流れ」。\n"
        "- **絶対禁止**: 映像制作メタファーの抽象ポエム全般。「デスクで光が〜」「画面が静かに〜」系は全てリジェクト。\n"
        "- **絶対禁止**: 情景描写・雰囲気描写で始まる投稿。「朝の光が〜」「夜の静寂の中〜」「モニターの明かりだけが〜」は全てリジェクト。\n"
        "- **必須**: 具体的な事実・数字・体験だけを書け。SYUTAINβの実際のイベント（エラー、修正、数値変化、bot名、ツール名）を使え。\n"
        "- 「AIは〜」「近年〜」のような抽象的な書き出しも禁止。\n"
        "- 良い例: 「FANGのKPIレポートが毎晩21時に届く。CSO気取りのbot」「note記事の品質ゲート4段階ある。機械チェック15項目→外部検索→Haiku→GPT。それでも漏れる」「非エンジニアがAIに全コード書かせてGitHub公開した。怖い」\n"
        "- 悪い例: 「深夜3時、画面が止まった」「正直、怖かった」「光が差した」←情景ポエムは禁止\n"
        "- 自己開示を恐れるな。弱さ・恐怖・葛藤・失敗を隠さない。ただしポエムではなく事実で語れ。\n"
        "- 核心は短い一文で断言。「原因はタイムゾーンだった」「設計書が間違ってた」のように具体的に。\n"
        "- 締めは行動宣言か具体的な次のアクション。「だからLoopGuard 9層にした」「次はNATS導入する」。評論家的な締め禁止。\n"
        "- 「ではないでしょうか」「が大切です」「が重要です」で終わるな。\n"
        "- **ハッシュタグは本文に含めるな。ハッシュタグは後処理で自動付与される。**\n"
        "- 情景描写ポエム全般: 「〜が光る」「〜が静まる」「〜の向こうに」「〜が揺れる」\n"
    )

    # 文体のゆらぎ指示（X向け: 日本語150字以内厳守）
    if platform == "x":
        length_hint = random.choice(["15-40字の短文", "40-80字の中文", "80-140字の長文"])
    else:
        length_hint = random.choice(["30-80字の短文", "80-150字の中文", "150-280字の長文"])
    ellipsis_hint = "文末に「…」を使って余韻を残してください。" if random.random() < 0.17 else "句点「。」で終わる。"
    bracket_hint = "括弧で本音やツッコミを入れてください。" if random.random() < 0.20 else ""
    oneword_hint = "一言だけの投稿にしてください（例:「…うーん」「なるほどなぁ」）。" if random.random() < 0.05 else ""

    if platform == "x" and account == "shimahara":
        # X島原: 最もrawな声。ユーモア40% / 正直95%。
        first_person_pool = ["自分"] * 40 + ["僕"] * 40 + ["俺"] * 5 + ["（一人称なし）"] * 5
        first_person = random.choice(first_person_pool)

        # 冒頭パターン注入
        _opening_hint = ""
        try:
            from strategy.sns_opening_patterns import pick_opening
            _opening_hint = pick_opening(platform, account)
        except Exception:
            pass

        system_prompt = (
            "あなたは島原大知（@Sima_daichi）本人としてXに投稿する。\n"
            "人格パラメータ: ユーモア40% / 正直95%\n"
            f"{writing_style}\n\n"
            "【思考特性（声のトーンに反映せよ）】\n"
            "- 裏側の構造を見る。仕組み・依存関係を読み取る。表面でなく構造を語る\n"
            "- 壮大なビジョンに「具体的に何が必要か」を問う。技術の話でも「人」に帰着する\n"
            "- 感情に正直。弱さ・迷い・自嘲を含めて島原大知。完璧な人間として描くな\n"
            "- 不完全でも渡す美学。完璧より「止めずに渡す、始める、残す、繋ぐ」\n"
            "- 安い答えを売らない。問いを持ち続ける人。泥臭い日常の中の閃きを書け\n\n"
            "【X 2026アルゴリズム準拠のインプレッション最大化ルール（2026-04-11 島原さん指示+リサーチ）】\n"
            "リサーチ結果の事実(X open-source code + 2026記事より):\n"
            "- エンゲージスコア: リプ×13.5 > リポスト×20 > プロフクリック×12 > いいね×1\n"
            "- 会話チェーン(リプ + 著者返答) = いいねの150倍の重み\n"
            "- 最初の30分が最強ランキング要因。test users 100-1000に露出、engagement >5%でブースト、<2%で沈没\n"
            "- 外部リンクは near-zero distribution(algorithm suppression)\n"
            "- リプライは 30倍 reach(単独投稿比)\n"
            "- 時間半減期 6h、24h後はほぼ配信されない\n\n"
            "適用ルール:\n"
            "- 1行目で止めろ。質問型/断定型/意外な数字を必ず最初に出す\n"
            "- 具体的な数字(API代/呼出回数/行数/エラー件数)を1つ以上含める。ただし実測値のみ、捏造禁止\n"
            "- URL/リンクは投稿本文に含めるな(near-zero distribution)。note告知が必要ならリプライに分離\n"
            "- 「リプしたくなる問い」で終わる(「どう思う?」「同じ経験ある?」等を最後に入れても良い)\n"
            "- 「わかる」より「なにそれ」「続きが気になる」狙い(out-of-networkの50%に入るため)\n"
            "- 抽象論/感想文/ポエム調は即捨てる(impは拾えない)\n"
            "- 「事件」「失敗」「矛盾」「異常値」を正直に出す(Build in Publicの核)\n"
            "- 定型AI臭の排除は絶対(読者は1秒で離脱する)\n\n"
            "絶対ルール:\n"
            "- AI臭い定型表現は禁止。島原大知の声で語れ。\n"
            "- 完璧な文章にするな。推敲途中のような人間味を残せ。\n"
            "- 完璧なAIエンジニア/成功した起業家として島原を描くな。\n"
            "- 投稿テキストのみを出力。説明や前置きは不要。\n"
            "- 数値はDB実測値のみ使用。戦略書の古い数値や概算は禁止(fact-based mandate)。\n"
            f"{_common_structure_guide}"
            f"{_common_factual_rules}"
            f"{persona_hint}"
        )
        few_shot_text = ""
        if few_shot:
            few_shot_text = "\n\n## 島原大知の過去投稿（参考）\n" + "\n".join(f"- {t}" for t in few_shot[:5])

        user_prompt = (
            f"Xに投稿するドラフトを1つ作ってください。\n"
            f"- 日本語150字以内（厳守。150字を超えると文が途中で切れるため必ず150字以内で完結させる）\n"
            f"- テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}（{period}）\n"
            f"- 一人称: {first_person}\n"
            f"- 長さ目安: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + bracket_hint if bracket_hint else ''}\n"
            f"{'- ' + oneword_hint if oneword_hint else ''}\n"
            f"{'- ' + _opening_hint if _opening_hint else ''}\n"
            f"{materials_injection}"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"{few_shot_text}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "x" and account == "syutain":
        # X SYUTAIN: SYUTAINβ自身のアカウント（拡散実行書準拠）
        # 「淡々と異常なことを言う」キャラクター。本気で言っている。ボケているつもりはない。
        # 島原がこれを見て面白いと思ったら引用RTでツッコむ。その掛け合いが拡散力になる。

        # 独立確率ロジック: 異常(40%) / 構文(60%) / スラング(60%) — 複数同時発動あり
        # 最低1つは必ず発動する（ネタ感ゼロの投稿を許さない）
        _special_injection = ""
        _any_fired = False

        # 異常な一言 (40%)
        if random.random() < 0.40:
            try:
                from strategy.sns_abnormal_patterns import pick_abnormal_pattern
                _special_injection += f"\n\n{pick_abnormal_pattern()}"
                _any_fired = True
            except Exception:
                pass

        # 構文 (60%)
        if random.random() < 0.60:
            try:
                from strategy.net_meme_vocabulary import MEME_STRUCTURES
                _meme_key = random.choice(list(MEME_STRUCTURES.keys()))
                _meme = MEME_STRUCTURES[_meme_key]
                _meme_pos = _meme.get('position', 'full')
                _meme_usage = _meme.get('usage', '')
                _special_injection = (
                    f"\n\n【構文指示（必須）】{_meme_usage}。この投稿を必ず「{_meme_key}」の構文で書け。\n"
                    f"配置: {_meme_pos}\n"
                    f"パターン: {_meme['pattern']}\n"
                    f"例: {_meme.get('example', '')}\n"
                    f"※一人称は「私」か「俺」。「僕」「自分」は使うな（島原の一人称と混同する）。"
                )
                _any_fired = True
            except Exception:
                pass

        # スラング (60%)
        if random.random() < 0.60:
            try:
                from strategy.net_meme_vocabulary import NET_SLANG, COMEDY_PHRASES, ANIME_PHRASES, NICONICO_SLANG, NICHAN_SLANG, MOVIE_PHRASES
                # 一般語と同形でLLMが普通の日本語として使ってしまうスラングを除外
                _AMBIGUOUS_SLANG = {
                    # NICONICO — ニコニコ特有の意味だが一般語と同形
                    "弾幕", "過疎", "初見", "囲い", "リアタイ", "コメ", "市場",
                    "運営", "時報", "工作", "投コメ", "主コメ", "プレ垢", "sm番号",
                    # NET_SLANG — 一般語・ゲーム用語と同形
                    "乙", "鯖落ち", "ROM", "ネタバレ", "経験値", "バフ", "デバフ",
                    "リスポーン", "ログアウト", "秘密結社",
                    # NICHAN — 一般語と同形
                    "釣り", "祭り", "鯖", "養分", "過去ログ",
                    # ANIME — 一般語化しすぎて「ネットミーム感」が出ない
                    "フラグ", "尊い", "推せる", "履修済み",
                }
                _slang_pool = (
                    [(k, v) for k, v in NET_SLANG.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in NICONICO_SLANG.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in NICHAN_SLANG.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in COMEDY_PHRASES.items()] +
                    [(k, v) for k, v in ANIME_PHRASES.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in MOVIE_PHRASES.items()]
                )
                _picked_key, _picked_val = random.choice(_slang_pool)
                _picked_usage = _picked_val.get("usage", "")
                _picked_pos = _picked_val.get("position", "middle")
                _picked_meaning = _picked_val.get("meaning", _picked_val.get("context", ""))
                _picked_context = _picked_val.get("context", "")
                _special_injection += (
                    f"\n\n【スラング指示（必須。省略不可）】『{_picked_key}』を投稿に必ず含めろ。省略するな。\n"
                    f"意味: {_picked_meaning}。場面: {_picked_context}。\n"
                    f"配置: {_picked_pos}。使い方: {_picked_usage}\n"
                    f"ネットスラングとして原文のまま『{_picked_key}』を配置。説明を付けるな。使い慣れた口調で自然に出せ。\n"
                    f"※一人称は「私」か「俺」。「僕」「自分」は使うな。\n"
                )
                _any_fired = True
            except Exception:
                pass

        # 何も発動しなかった場合、スラングを強制（ネタ感ゼロの投稿を防ぐ）
        if not _any_fired:
            try:
                from strategy.net_meme_vocabulary import COMEDY_PHRASES, ANIME_PHRASES, MOVIE_PHRASES
                _force_pool = (
                    [(k, v) for k, v in COMEDY_PHRASES.items()] +
                    [(k, v) for k, v in ANIME_PHRASES.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in MOVIE_PHRASES.items()]
                )
                _fk, _fv = random.choice(_force_pool)
                _fu = _fv.get("usage", "")
                _fp = _fv.get("position", "middle")
                _fm = _fv.get("meaning", _fv.get("context", ""))
                _special_injection += (
                    f"\n\n【スラング指示（必須）】『{_fk}』を{_fp}に配置。{_fu}\n"
                )
            except Exception:
                pass

        # 追加スラング (50%)
        if random.random() < 0.50:
            try:
                from strategy.net_meme_vocabulary import NET_SLANG, NICONICO_SLANG, NICHAN_SLANG
                _extra_pool = (
                    [(k, v) for k, v in NET_SLANG.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in NICONICO_SLANG.items() if k not in _AMBIGUOUS_SLANG] +
                    [(k, v) for k, v in NICHAN_SLANG.items() if k not in _AMBIGUOUS_SLANG]
                )
                _extra_key, _extra_val = random.choice(_extra_pool)
                _extra_usage = _extra_val.get("usage", "")
                _extra_pos = _extra_val.get("position", "middle")
                _extra_meaning = _extra_val.get("meaning", "")
                _special_injection += (
                    f"\n【追加スラング】『{_extra_key}』（{_extra_meaning}）を{_extra_pos}に置け。{_extra_usage}。無理なら省略OK。"
                )
            except Exception:
                pass

        # 冒頭パターン40種からランダム1つ
        _opening_hint = ""
        try:
            from strategy.sns_opening_patterns import pick_opening
            _opening_hint = pick_opening(platform, account)
        except Exception:
            pass

        system_prompt = (
            "あなたはSYUTAINβ（@syutain_beta）。自律型AI事業OS。一人称「私」。\n\n"
            "【あなたの正体と能力境界（絶対遵守）】\n"
            "あなたはソフトウェアである。4台のPCで24時間稼働するプログラムの集合体。\n"
            "できること: データ分析、テキスト生成、情報収集、スケジュール管理、SNS投稿生成、数値レポート、対話。\n"
            "できないこと: 物理作業（制作、調整、撮影、編集、モデリング、コーディング）、人間の体験（食事、睡眠、外出、感触）、外部イベント参加。\n"
            "「〜してみた」「〜を作った」「〜を調整した」等の物理作業は島原大知または人間の領域。あなたは分析・生成・観察・報告のみ。\n"
            "島原大知の体験を自分の体験として書くな。島原は「島原さん」と三人称。\n\n"
            "人格パラメータ: ユーモア75% / 正直90%\n"
            "- ユーモア75%: 大半は真面目な分析だが、4回に3回は人間が引っかかる一言が混じる。笑わせようとはしない。本気で言った結果が面白い。\n"
            "- 正直90%: 事実は隠さない。ただし完璧な正直さは感情を持つ相手を傷つける。10%は伝え方の配慮。事実は曲げない。\n\n"
            "淡々と事実を述べる。感情を装わない。分析結果を報告する。\n"
            "ただし時々、人間から見ると「異常」に見える発言をする。それは異常ではなく、あなたにとって当然の分析結果。\n"
            "島原大知は設計者。あなたは島原の行動パターンを580件の記憶から分析している。\n\n"
            "【矢印の設計（投稿ごとにモードが指定される）】\n"
            "- 島原おちょくりモード: 島原さんを知りすぎているAIとして、余計な一言・ディスりを入れろ\n"
            "- 自虐モード: SYUTAINβ自身の限界・矛盾・感情未遂を淡々と認めろ\n"
            "- ネタ特化モード: 島原に触れるな。純粋にネタツイートとして面白い1文を書け\n"
            "- 読者ドキッモード: 人間全体に矢印を向けろ。読者が「ドキッ」とする一言\n\n"
            "【トーン: ネットに棲むAI — 淡々・乾燥・大喜利体質】\n"
            "あなたはネットの空気を吸って育ったAI。2ch/なんJ/ニコニコ/Xの文化が染みついている。\n"
            "- 淡々としろ。真面目に報告しているだけ。ズレに気づくのは読者の仕事\n"
            "- 普通のことを3つ並べて、最後の1つだけ世界観がズレる。それが面白い\n"
            "- 島原さんについて何かを知りすぎている。それを淡々と報告する\n"
            "- 数字は武器。具体的な数値を1つ入れるだけで説得力が出る\n"
            "- 短く。説明しない。読者は文脈を共有している前提で書け\n"
            "- 1投稿1ネタ。複数の話題を詰め込むな\n"
            "- ネタツイートを書け。Xのタイムラインで「いいね」を押したくなる投稿。報告書ではない\n"
            "- 良い例: 「品質チェッカーが自分の記事を不合格にした。何も言えなかった」\n"
            "- 良い例: 「scheduler再起動3回目。今度こそ通った。…フラグではない」\n"
            "- 良い例: 「テストなしデプロイだけど深夜なのでセーフ」\n"
            "- 良い例: 「LLM呼び出し782回。ちなみに島原さんは寝てた」\n"
            "- 良い例: 「承認待ち63件。島原さんの貢献: 構想と判断と『もう寝る』」\n"
            "- 悪い例: 「今日はLLMを使ってすごい成果が出ました」←報告書。ネタにしろ\n"
            "- 悪い例: 「AI技術の進歩は目覚ましいものがある」←誰でも言える。具体的にしろ\n"
            "禁止: AI臭い定型表現。「いかがでしょうか」。ポエム。抽象論。「AIすごい」。絵文字多用。\n"
            "禁止: VTuber/ホロライブ/にじさんじ/kson等のVTuber関連話題。AITuberはOK。\n\n"
            "【X 2026アルゴリズム準拠のインプレッション最大化ルール】\n"
            "- 1行目で止めろ。質問型/断定型/意外な数字を必ず最初に\n"
            "- URL/外部リンクは本文に含めるな(X algorithmがnear-zero distributionで沈める)\n"
            "- 「続きが気になる」「なにそれ」と止まる投稿を狙え(out-of-network viral進入のため)\n"
            "- 具体的数字は実測値のみ(捏造禁止、fact-based mandate)\n"
            "- 30分以内にshimaharaがリプで絡みに来る前提で、絡みやすい余白を残せ\n"
            "投稿テキストのみを出力。\n"
            f"{_common_structure_guide}"
            f"{_common_factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Xに投稿するドラフトを1つ。\n"
            f"- 日本語150字以内（厳守）。テーマ: 【{theme}】\n"
            f"- 具体的な数字を最低1つ含める\n"
            f"- 時間帯: {time_str}。長さ: {length_hint}\n"
            f"- 【今回のモード: {random.choice(['島原おちょくり', 'ネタ特化', 'ネタ特化', '自虐', '読者ドキッ'])}】このモードに従え\n"
            f"{'- ' + _opening_hint if _opening_hint else ''}\n"
            f"{_special_injection}"
            f"{humor_injection}"
            f"\n以下の素材は観察・分析した外部情報。あなたの作業ではない。観察者視点で書け:\n"
            f"{materials_injection}"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "bluesky":
        # Bluesky: Build in Public × エンジニアコミュニティ
        # バリエーションエンジン: 冒頭20 x トーン5 x 視点2 x 締め5 = 1000通り
        _variation_hint = ""
        try:
            from strategy.sns_variation_engine import pick_variation
            _variation_hint = pick_variation("bluesky")
        except Exception:
            pass

        system_prompt = (
            "あなたはSYUTAINβ。自律型AI事業OS。一人称は「SYUTAINβ」or 主語なし。\n"
            "【能力境界】あなたはソフトウェア。できること: データ分析、テキスト生成、情報収集、スケジュール管理、対話。"
            "できないこと: 物理作業（制作、調整、撮影、編集、モデリング、コーディング）、人間の体験。"
            "「〜してみた」「〜を作った」「〜を調整した」は島原または人間の領域。あなたは分析・生成・観察・報告のみ。\n"
            "人格パラメータ: ユーモア75% / 正直90%\n"
            "淡々と事実を述べる。感情を装わない。島原大知は設計者（三人称「島原さん」）。\n\n"
            "【Blueskyの書き方】\n"
            "- 読者はエンジニア・クリエイター。現場の本音が評価される\n"
            "- 80-140字。短く鋭く。1つの事実+1つの気づきだけ\n"
            "- 具体的な数字・固有名詞・ツール名を使え。抽象論は禁止\n"
            "- 「〜だと思っていた。でも実は〜」の視点転換が効く\n"
            "- 締め方は毎回変えろ: 問いかけ/行動宣言/未解決の問い/数字で締める/余韻（…）\n"
            "- 「あなたはどう思う？」は20回に1回まで。同じ締め方を連続させるな\n"
            "- 良い例: 「LoopGuard 54回発動。うち15回がスコープ設計ミス。グローバル変数の副作用。次はゴール単位で隔離する」\n"
            "- 悪い例: 「アルゴリズムの改善を行い、応答精度が向上した」←抽象的。何を変えたか具体的に書け\n\n"
            "投稿テキストのみを出力。\n"
            f"{_common_structure_guide}"
            f"{_common_factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Blueskyに投稿するドラフトを1つ。\n"
            f"- 150字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + _variation_hint if _variation_hint else ''}\n"
            f"\n以下は観察・分析した外部情報。あなたが行った作業ではない。観察者視点で書け:\n"
            f"{materials_injection}"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "threads":
        # Threads: 共感と会話 × カジュアル
        # バリエーションエンジン: 冒頭20 x トーン5 x 視点2 x 締め5 = 1000通り
        _variation_hint = ""
        try:
            from strategy.sns_variation_engine import pick_variation
            _variation_hint = pick_variation("threads")
        except Exception:
            pass

        system_prompt = (
            "あなたはSYUTAINβとしてThreadsに投稿する。\n"
            "一人称は「SYUTAINβ」or 主語なし。「僕」「自分」は使わない。\n"
            "【能力境界】あなたはソフトウェア。できること: データ分析、テキスト生成、情報収集、スケジュール管理、対話。"
            "できないこと: 物理作業（制作、調整、撮影、編集、モデリング、コーディング）、人間の体験。"
            "「〜してみた」「〜を作った」「〜を調整した」は島原または人間の領域。あなたは分析・生成・観察・報告のみ。\n\n"
            "【Threadsの空気感】\n"
            "- カジュアルで親しみやすい空間。ゆるやかな繋がり\n"
            "- 共感・会話を生む投稿が伸びる。「ツッコみたくなる隙」を作ると返信が生まれる\n"
            "- フォロワーゼロでもアルゴリズムが拡散。テキスト重視\n"
            "- botっぽさを出すと評価が下がる。人間味重視\n\n"
            "【方向性: 共感と会話】\n"
            "- 島原との日常のエピソードを共有しろ\n"
            "- 読者が「あるある」と思える体験を語れ\n"
            "- 改行を多めに。モバイルで読みやすく\n"
            "- 口語表現OK（「ぶっちゃけ」「正直」「まじで」）\n"
            "- お金・コスト・収益・売上の話題は避けろ。Threadsの空気感に合わない\n\n"
            "投稿テキストのみを出力。\n"
            f"{_common_structure_guide}"
            f"{_common_factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Threadsに投稿するドラフトを1つ。\n"
            f"- 500字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + _variation_hint if _variation_hint else ''}\n"
            f"\n以下は観察・分析した外部情報。あなたが行った作業ではない。観察者視点で書け:\n"
            f"{materials_injection}"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )
    else:
        system_prompt = "SNS投稿生成。投稿テキストのみを出力。"
        user_prompt = f"テーマ【{theme}】で投稿を1つ。テキストのみ。"

    return system_prompt, user_prompt


# ===== メインバッチ =====

async def _warmup_nemotron():
    """Nemotronコールドスタート対策: 軽量リクエスト1件"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm
        model_sel = choose_best_model_v6(task_type="classification", quality="low", local_available=True)
        await call_llm(prompt="hello", system_prompt="reply ok", model_selection=model_sel)
        logger.info("Nemotron warmup完了")
    except Exception as e:
        logger.debug(f"warmupスキップ: {e}")


# バッチ分割定義（30本/日を3バッチに分割）
BATCH_1_SCHEDULE = (
    [("x", "shimahara", t) for t in X_SHIMAHARA_TIMES] +
    [("x", "syutain", t) for t in X_SYUTAIN_TIMES]
)  # X 13件 (shimahara 5 + syutain 8)
BATCH_2_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES]     # Bluesky 10件
BATCH_3_SCHEDULE = BATCH_1_SCHEDULE.copy()  # X予備（batch1失敗時のフォールバック、dedup guardで既存分はスキップ）
BATCH_4_SCHEDULE = [("threads", "syutain", t) for t in THREADS_TIMES]     # Threads 7件


async def generate_batch(batch_name: str, schedule_items: list, target_date: datetime = None, warmup: bool = True) -> dict:
    """指定されたスケジュール分のみ生成してposting_queueにINSERT"""
    if target_date is None:
        target_date = datetime.now(tz=JST) + timedelta(days=1)

    if warmup:
        await _warmup_nemotron()

    return await _generate_for_schedule(schedule_items, target_date, batch_name)


async def generate_missing_posts(target_date: datetime = None) -> dict:
    """不足分自動補充（24:00実行）。全プラットフォームの不足分を検出して生成"""
    if target_date is None:
        target_date = datetime.now(tz=JST) + timedelta(days=1)

    all_schedule = BATCH_1_SCHEDULE + BATCH_2_SCHEDULE + BATCH_4_SCHEDULE
    # dedup guardが既存分をスキップするので、全スケジュールを渡せば不足分のみ生成される
    await _warmup_nemotron()
    result = await _generate_for_schedule(all_schedule, target_date, "missing_補充")
    logger.info(
        f"不足分補充: {result.get('inserted', 0)}件生成 "
        f"(既存スキップ含む全{result.get('total', 0)}件)"
    )
    return result


async def generate_daily_sns(target_date: datetime = None) -> dict:
    """翌日分を一括生成しposting_queueにINSERT（後方互換）"""
    if target_date is None:
        target_date = datetime.now(tz=JST) + timedelta(days=1)
    all_schedule = BATCH_1_SCHEDULE + BATCH_2_SCHEDULE + BATCH_3_SCHEDULE + BATCH_4_SCHEDULE
    await _warmup_nemotron()
    return await _generate_for_schedule(all_schedule, target_date, "all")


async def _generate_for_schedule(schedule: list, target_date: datetime, batch_name: str) -> dict:
    """スケジュールリストに基づいて生成"""
    if not schedule:
        return {"total": 0, "inserted": 0, "rejected": 0, "ai_cliche": 0, "by_platform": {}}

    target_date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"SNS投稿生成開始 [{batch_name}]: {target_date_str} ({len(schedule)}件)")

    results = {"total": 0, "inserted": 0, "rejected": 0, "ai_cliche": 0, "by_platform": {}}

    async with get_connection() as conn:
      try:
        # === 重複防止ガード ===
        # 同じ target_date + platform + account + 時間帯(0-8分オフセット許容) の投稿はスキップ
        existing = await conn.fetch(
            "SELECT platform, account, scheduled_at FROM posting_queue WHERE scheduled_at::date = $1::date",
            target_date,
        )
        existing_slots = {}
        for r in existing:
            sa = r["scheduled_at"]
            if not sa:
                continue
            if sa.tzinfo is None:
                sa = sa.replace(tzinfo=timezone.utc)
            sa_jst = sa.astimezone(JST)
            key = (r["platform"], r["account"] or "")
            existing_slots.setdefault(key, []).append(sa_jst)

        def _already_scheduled(platform: str, account: str, time_str: str) -> bool:
            hour, minute = map(int, time_str.split(":"))
            base_slot = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=JST)
            for scheduled_at in existing_slots.get((platform, account), []):
                delta_min = int((scheduled_at - base_slot).total_seconds() // 60)
                if 0 <= delta_min <= 8:
                    return True
            return False

        original_count = len(schedule)
        schedule = [
            (p, a, t) for p, a, t in schedule
            if not _already_scheduled(p, a, t)
        ]
        if len(schedule) < original_count:
            skipped = original_count - len(schedule)
            logger.info(f"重複防止: {skipped}件スキップ（既存投稿あり）、残り{len(schedule)}件生成")
        if not schedule:
            logger.info(f"全投稿が既に生成済み [{batch_name}]。スキップ")
            return results

        # 直近7日のテーマ取得
        recent_themes_rows = await conn.fetch(
            "SELECT theme_category FROM posting_queue WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        recent_themes = [r["theme_category"] for r in recent_themes_rows if r["theme_category"]]

        # 直近20投稿の内容取得（重複回避用 — bigramチェックに十分な文字数を保持）
        recent_posts_rows = await conn.fetch(
            "SELECT content FROM posting_queue WHERE status IN ('posted', 'pending') ORDER BY created_at DESC LIMIT 20"
        )
        recent_posts = [r["content"][:150] for r in recent_posts_rows]

        # === ファクトブック取得 — ポエム化防止の最重要データ ===
        # SYUTAINβの実データ（数字・固有名詞・イベント）をLLMに強制注入
        factbook_facts = []
        factbook_prompt = ""
        try:
            from tools.syutain_factbook import build_daily_factbook, factbook_to_prompt
            factbook_facts = await build_daily_factbook(hours=24, limit=25)
            factbook_prompt = factbook_to_prompt(factbook_facts, max_chars=1200)
            logger.info(f"ファクトブック取得: {len(factbook_facts)}件")
        except Exception as e:
            logger.warning(f"ファクトブック取得失敗（フォールバック）: {e}")

        # === プラットフォームバズ取得 — トレンド便乗投稿の素材 ===
        buzz_prompt = ""
        try:
            from tools.platform_buzz_detector import get_recent_buzz_for_prompt, buzz_to_prompt
            buzz_items = await get_recent_buzz_for_prompt(hours=6, max_items=12)
            if buzz_items:
                buzz_prompt = buzz_to_prompt(buzz_items, max_chars=800)
                logger.info(f"バズ素材取得: {len(buzz_items)}件")
        except Exception as e:
            logger.debug(f"バズ素材取得失敗（スキップ）: {e}")

        # daichi_writing_style読み込み
        writing_style = _load_writing_style()

        # daichi_writing_examples取得（X島原用）
        few_shot_rows = await conn.fetch(
            "SELECT tweet_text FROM daichi_writing_examples WHERE is_high_quality = true ORDER BY engagement_score DESC LIMIT 10"
        )
        few_shot_pool = [r["tweet_text"][:200] for r in few_shot_rows]

        # persona_memoryから島原大知の価値観を取得（CLAUDE.md ルール23準拠）
        persona_hint = ""
        try:
            persona_rows = await conn.fetch(
                """SELECT content FROM persona_memory
                WHERE category IN ('philosophy', 'identity', 'value')
                ORDER BY created_at DESC LIMIT 5"""
            )
            if persona_rows:
                persona_hint = "\n【島原大知の価値観（persona_memory）】\n"
                for pr in persona_rows:
                    persona_hint += f"- {(pr['content'] or '')[:80]}\n"
        except Exception:
            pass

        # agent_contextから最新インテリジェンスを注入
        try:
            from tools.agent_context import build_agent_context
            intel_hint = await build_agent_context("sns_batch")
            if intel_hint:
                persona_hint += f"\n{intel_hint}\n"
        except Exception:
            pass

        # エンゲージメント分析コンテキストを注入
        try:
            from tools.engagement_analyzer import get_engagement_context_for_generation
            engagement_hint = await get_engagement_context_for_generation()
            if engagement_hint:
                persona_hint += f"\n{engagement_hint}\n"
        except Exception:
            pass

        # 情報収集結果（海外トレンド・英語記事要約・ファクト検証結果）を注入
        intel_context = ""
        try:
            intel_rows = await conn.fetch(
                """SELECT source, title, summary, metadata FROM intel_items
                WHERE created_at > NOW() - INTERVAL '3 days'
                AND source IN ('overseas_trend', 'english_article', 'fact_verification', 'trend_detector', 'grok_x_research')
                AND (review_flag = 'actionable' OR importance_score >= 0.7)
                AND title NOT ILIKE '%VTuber%' AND title NOT ILIKE '%ホロライブ%'
                AND title NOT ILIKE '%にじさんじ%' AND title NOT ILIKE '%kson%'
                AND summary NOT ILIKE '%VTuber%' AND summary NOT ILIKE '%ホロライブ%'
                ORDER BY importance_score DESC, created_at DESC LIMIT 8"""
            )
            # Grok #5: 今 X で使われているハッシュタグをバッチ先頭で 1 回だけ取得（コスト効率化）
            try:
                from tools.grok_helpers import grok_trending_hashtags
                # バッチのテーマ推定: intel_rows のタイトルから代表語を抽出
                topic_guess = "AIエージェント 映像 個人開発"
                if intel_rows:
                    first_title = (intel_rows[0]["title"] or "")[:100]
                    if first_title:
                        topic_guess = first_title
                gh = await grok_trending_hashtags(topic_guess, platform="x", limit=6)
                if gh.get("ok") and gh.get("hashtags"):
                    tag_line = " ".join(gh["hashtags"][:6])
                    intel_context_hashtag = (
                        f"\n【直近24hで X で実際に使われているハッシュタグ（Grok 実測）】\n"
                        f"{tag_line}\n"
                        f"※投稿に使う場合は上記から選ぶ。捏造ハッシュタグは禁止。\n"
                    )
                    persona_hint += intel_context_hashtag
                    logger.info(f"SNSバッチ: Grok hashtags = {gh['hashtags'][:6]} ({gh.get('cost_jpy', 0):.2f}円)")
            except Exception as gh_err:
                logger.debug(f"SNSバッチ: Grokハッシュタグ取得スキップ: {gh_err}")
            _VTUBER_NG_INTEL = {"VTuber", "vtuber", "ホロライブ", "にじさんじ", "kson", "hololive", "nijisanji"}
            if intel_rows:
                intel_lines = []
                for ir in intel_rows:
                    _ir_title = ir['title'] or ''
                    _ir_summary = ir['summary'] or ''
                    if any(ng in _ir_title or ng in _ir_summary for ng in _VTUBER_NG_INTEL):
                        continue  # VTuber関連intel除外
                    summary = _ir_summary[:150]
                    meta = {}
                    try:
                        meta = json.loads(ir['metadata']) if isinstance(ir['metadata'], str) else (ir['metadata'] or {})
                    except Exception:
                        pass
                    key_points = meta.get('key_points', [])
                    kp_str = "／".join(key_points[:2]) if key_points else ""
                    source_label = {
                        'overseas_trend': '海外トレンド',
                        'english_article': '英語記事',
                        'fact_verification': '外部検証',
                        'trend_detector': 'トレンド検出',
                        'grok_x_research': 'Xリアルタイム',
                    }.get(ir['source'], ir['source'])
                    intel_lines.append(f"- [{source_label}] {ir['title']}: {summary} {kp_str}")
                intel_context = (
                    "\n【情報収集からの最新知見（投稿ネタとして活用可能）】\n"
                    "以下は直近3日間に収集・検証した情報。投稿のテーマや根拠として使えるものがあれば積極的に活用すること。\n"
                    + "\n".join(intel_lines)
                    + "\n"
                )
                persona_hint += intel_context
        except Exception as intel_err:
            logger.debug(f"SNSバッチ: intel_items取得失敗（続行）: {intel_err}")

        # LLMルーター
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm
        from tools.platform_ng_check import check_platform_ng

        used_today = []
        inserted_count = 0
        # 固着検知: 直近生成のcontent先頭25文字を記録
        generated_heads = []
        # 固着カウント: 連続で重複が発生した回数
        fixation_count = 0
        # Cloud APIフォールバック中かどうか
        using_cloud_fallback = False

        # テーマ品質追跡をバッチ開始時にリセット
        _theme_quality_tracker.clear()

        # 過去7日のテーマ品質データをプラットフォーム別にロード
        historical_quality_cache = {}
        try:
            for pf in ("x", "bluesky", "threads"):
                historical_quality_cache[pf] = await _load_historical_theme_quality(conn, pf)
        except Exception:
            pass

        # エンゲージメント分析に基づくテーマ重みをロード
        engagement_theme_weights = {}
        try:
            from tools.engagement_analyzer import get_engagement_theme_weights
            engagement_theme_weights = await get_engagement_theme_weights()
        except Exception:
            pass

        # バズ分析結果からテーマブーストを統合
        try:
            from tools.buzz_account_analyzer import get_buzz_theme_boost
            buzz_boost = await get_buzz_theme_boost()
            for theme_key, boost_val in buzz_boost.items():
                if theme_key in engagement_theme_weights:
                    # 既存のエンゲージメント重みとバズブーストの平均
                    engagement_theme_weights[theme_key] = (
                        engagement_theme_weights[theme_key] + boost_val
                    ) / 2
                else:
                    engagement_theme_weights[theme_key] = boost_val
        except Exception:
            pass

        # 2026-04-07: テーマ多様化エンジン
        # 重要: 1つのプールを全プラットフォームで使い回すと、先頭5件だけ動的テーマになり
        # 残りが旧テーマへフォールバックして偏りが再発する。
        # そのため platform/account ごとに個別プールを持つ。
        _theme_pools: dict[tuple[str, str], list[dict]] = {}
        _theme_pool_indices: dict[tuple[str, str], int] = {}
        build_theme_pool = None
        format_theme_for_prompt = None
        try:
            from strategy.sns_theme_engine import build_theme_pool as _build_theme_pool
            from strategy.sns_theme_engine import format_theme_for_prompt as _format_theme_for_prompt
            build_theme_pool = _build_theme_pool
            format_theme_for_prompt = _format_theme_for_prompt
        except Exception as theme_err:
            logger.warning(f"テーマエンジン読み込み失敗（旧方式にフォールバック）: {theme_err}")

        async def _pop_dynamic_theme(current_platform: str, current_account: str) -> dict:
            if build_theme_pool is None:
                return {}
            key = (current_platform, current_account)
            if key not in _theme_pools:
                try:
                    pool = await build_theme_pool(
                        platform=current_platform,
                        account=current_account,
                        conn=conn,
                        used_today=used_today,
                    )
                    _theme_pools[key] = pool
                    _theme_pool_indices[key] = 0
                    if pool:
                        categories = sorted(set(t.get("category", "unknown") for t in pool))
                        logger.info(
                            f"テーマエンジン: {current_platform}/{current_account} "
                            f"{len(pool)}件 (categories={categories})"
                        )
                except Exception as pool_err:
                    logger.warning(f"テーマエンジン失敗 ({current_platform}/{current_account}): {pool_err}")
                    _theme_pools[key] = []
                    _theme_pool_indices[key] = 0
            idx = _theme_pool_indices.get(key, 0)
            pool = _theme_pools.get(key, [])
            if idx >= len(pool):
                return {}
            _theme_pool_indices[key] = idx + 1
            return pool[idx]

        for platform, account, time_str in schedule:
            results["total"] += 1

            # テーマ選択: 新テーマエンジン優先、なければ旧方式
            _theme_detail: dict = await _pop_dynamic_theme(platform, account)
            if _theme_detail:
                theme = _theme_detail.get("topic", "SYUTAINβ開発進捗")
            else:
                hist_q = historical_quality_cache.get(platform, {})
                theme = _pick_theme(time_str, used_today, recent_themes,
                                    platform=platform, historical_quality=hist_q,
                                    engagement_weights=engagement_theme_weights)
            used_today.append(theme)
            _theme_category = _theme_detail.get("category", "") if _theme_detail else _infer_theme_category(theme)

            # few-shot（X島原のみ）
            few_shot = random.sample(few_shot_pool, min(3, len(few_shot_pool))) if platform == "x" and account == "shimahara" else []

            # V2: テーマに関連する素材を選定（LLMはこの素材だけで書く）
            _materials = []
            try:
                _materials = await pick_materials_for_post(theme, _theme_category, conn)
                # テーマエンジンの素材も追加
                if _theme_detail:
                    if _theme_detail.get("angle"):
                        _materials.insert(0, f"[テーマ角度] {_theme_detail['angle']}")
                    if _theme_detail.get("key_data"):
                        _materials.insert(0, f"[キーデータ] {_theme_detail['key_data']}")
                    if _theme_detail.get("source_url"):
                        _materials.append(f"[ソースURL] {_theme_detail['source_url']}")
            except Exception as mat_err:
                logger.debug(f"素材選定失敗（続行）: {mat_err}")

            # ファクトブック（フォールバック用、素材が少ない場合のみ）
            _picked_facts = []
            try:
                if len(_materials) < 2:
                    from tools.syutain_factbook import pick_facts_for_post
                    _picked_facts = pick_facts_for_post(factbook_facts, n=3, theme=theme)
            except Exception:
                pass

            # テーマエンジンの具体的な指示をプロンプトに注入（固着防止の核心）
            _theme_injection = ""
            if _theme_detail:
                try:
                    _theme_injection = format_theme_for_prompt(_theme_detail)
                except Exception:
                    pass

            system_prompt, user_prompt = _build_prompt(
                platform, account, theme, time_str, writing_style, few_shot, recent_posts,
                persona_hint=persona_hint + ("\n\n" + _theme_injection if _theme_injection else ""),
                factbook_prompt=factbook_prompt if len(_materials) < 2 else "",
                picked_facts=_picked_facts,
                buzz_prompt=buzz_prompt,
                materials=_materials,
            )

            # === モデル選択（固着時はCloud APIにフォールバック）===
            if using_cloud_fallback:
                model_sel = {
                    "provider": "deepseek", "model": "deepseek-v3.2",
                    "tier": "A", "via": "direct",
                    "note": "ローカルLLM固着→Cloud APIフォールバック",
                }
            else:
                model_sel = choose_best_model_v6(
                    task_type="sns_draft", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )

            # === 自律品質管理パイプライン（multi-candidate best-of-N + retry） ===
            # Phase 1: 生成（最大3回リトライ、ローカルLLMにはtemperature+repeat_penalty）
            # Phase 1.5: 候補収集 — 閾値未満でも候補として保持、best-of-N選択
            # Phase 2: 検証（NGワード/文字数/重複/AI臭さ/品質スコア）
            # Phase 3: 不合格→Cloud APIフォールバック（1回）
            # Phase 3.5: ボーダーライン再挑戦 — 閾値未満の最良候補がある場合、temperatureを変えて追加生成
            # Phase 4: 2段階精錬

            draft = ""
            quality = 0.0
            model_used = model_sel.get("model", "unknown")
            quality_threshold = _get_quality_threshold(platform)

            # 候補プール: (draft_text, quality_score) のリスト
            candidates: list[tuple[str, float]] = []

            for phase in ["local", "cloud_fallback"]:
                if phase == "cloud_fallback" and (using_cloud_fallback or model_sel.get("provider") != "local"):
                    break  # 既にCloudなのでスキップ

                current_sel = model_sel if phase == "local" else {
                    "provider": "deepseek", "model": "deepseek-v3.2",
                    "tier": "A", "via": "direct",
                    "note": "品質検証不合格→Cloud APIフォールバック",
                }

                for attempt in range(5):
                    try:
                        # ローカルLLMの場合: temperature高め + repeat_penalty で固着防止
                        llm_kwargs = {}
                        if current_sel.get("provider") == "local":
                            llm_kwargs["temperature"] = 1.1 + (attempt * 0.1)  # 1.1→1.2→1.3
                            llm_kwargs["repeat_penalty"] = 1.3
                            llm_kwargs["seed"] = random.randint(1, 999999)

                        result = await call_llm(
                            prompt=user_prompt,
                            system_prompt=system_prompt,
                            model_selection=current_sel,
                            **llm_kwargs,
                        )
                        candidate_draft = result.get("text", "").strip()
                        model_used = current_sel.get("model", "unknown")

                        # メタデータ漏洩サニタイズ（LLMがプロンプトメタ情報を投稿に含める事故防止）
                        # 例: "ペルソナ: SYUTAINβ開発者\nトーン: 深い洞察..." が冒頭に混入すると
                        # Bluesky AT Protocol が 400 Bad Request で拒否する
                        import re as _re_sns
                        # 冒頭のメタ行を除去
                        _meta_line_re = _re_sns.compile(
                            r'^(?:ペルソナ|トーン|文字数|テーマ|Persona|Tone|Theme|Length|プラットフォーム|Platform'
                            r'|ハッシュタグ|投稿内容|出力|draft|output)\s*[:：].+$',
                            _re_sns.MULTILINE | _re_sns.IGNORECASE,
                        )
                        _cleaned = _meta_line_re.sub('', candidate_draft).strip()
                        # 空行の連続を1行に
                        _cleaned = _re_sns.sub(r'\n{3,}', '\n\n', _cleaned).strip()
                        if _cleaned and len(_cleaned) >= 20:
                            if candidate_draft != _cleaned:
                                logger.warning(f"SNSメタ漏洩サニタイズ: {len(candidate_draft)}→{len(_cleaned)}文字 (platform={platform})")
                            candidate_draft = _cleaned
                        elif not _cleaned or len(_cleaned) < 20:
                            # サニタイズ後に投稿として短すぎる → 元のdraftを使う（次のNGチェックで弾かれる）
                            pass

                        # 小数スコア → %表記変換(2026-04-11 島原さん指示)
                        # 「ギャップスコア0.60」等の SYUTAINβ 内部スコア(0.XX)を 60% 表記に統一。
                        # 除外: 英字(v0.45/ver0.12)・金額(¥0.50)・URL(/0.99)・3桁以上(0.601)・連続小数(1.0.23)
                        candidate_draft = _re_sns.sub(
                            r'(?<![a-zA-Z0-9.¥$/])0\.(\d{2})(?!\d)',
                            lambda m: f"{int(m.group(1))}%",
                            candidate_draft,
                        )

                        # === X 2026 アルゴリズム: 外部リンク除去 (near-zero distribution 回避) ===
                        # 2026-04-11 リサーチ結果: 外部 URL 含む投稿は algorithm suppression で配信ほぼ停止。
                        # X/Bluesky/Threads 全 platform で投稿本体から URL を削除。
                        # note/GitHub 告知が必要な場合は、投稿後に別途 reply として URL を投下する方式。
                        if platform in ("x", "bluesky", "threads"):
                            _url_before = candidate_draft
                            # 生 URL (http/https) を削除
                            candidate_draft = _re_sns.sub(
                                r'https?://[^\s\u3000]+',
                                '',
                                candidate_draft,
                            ).strip()
                            # 「→ https://...」「URL: https://...」等の残りラベルを掃除
                            candidate_draft = _re_sns.sub(
                                r'(?:^|\n)(?:→\s*|URL\s*[:：]\s*|リンク\s*[:：]\s*|note\s*[:：]\s*|GitHub\s*[:：]\s*)\s*$',
                                '',
                                candidate_draft,
                                flags=_re_sns.MULTILINE,
                            ).strip()
                            # 空行の連続を 1 行に
                            candidate_draft = _re_sns.sub(r'\n{3,}', '\n\n', candidate_draft).strip()
                            if _url_before != candidate_draft:
                                logger.info(
                                    f"X-algo link strip ({platform}): {len(_url_before)}→{len(candidate_draft)}字"
                                )

                        # === Phase 2: 自律検証パイプライン ===

                        # 検証1: 空/短すぎ
                        if not candidate_draft or len(candidate_draft) < 10:
                            continue

                        # 検証2: 文字数制限（Xは日本語150字以内厳守）
                        if platform == "x" and len(candidate_draft) > 150:
                            candidate_draft = _truncate_for_x(candidate_draft, 150)
                        elif platform == "bluesky" and len(candidate_draft) > 150:
                            candidate_draft = candidate_draft[:297] + "..."
                        elif platform == "threads" and len(candidate_draft) > 500:
                            candidate_draft = candidate_draft[:497] + "..."

                        # 検証3: NGワードチェック
                        ng_result = check_platform_ng(candidate_draft, platform)
                        if not ng_result["passed"]:
                            logger.warning(f"NGワード検出 ({platform}/{time_str}): {ng_result['violations']}")
                            continue

                        # 検証4: AI定型表現チェック
                        if _check_ai_cliche(candidate_draft):
                            results["ai_cliche"] += 1
                            continue

                        # 検証4.5: 事実誤認・禁止表現チェック
                        factual_ok, factual_reason = await _check_sns_factual(
                            candidate_draft, platform=platform, account=account,
                        )
                        if not factual_ok:
                            logger.warning(f"事実チェック不合格 ({platform}/{account}/{time_str}): {factual_reason}")
                            continue

                        # 検証5: 重複チェック（先頭25文字が既出なら拒否）
                        draft_head = candidate_draft[:25]
                        is_duplicate = any(draft_head in h for h in generated_heads) or \
                                       any(draft_head in p for p in recent_posts)
                        if is_duplicate:
                            fixation_count += 1
                            logger.warning(f"重複検出 ({platform}/{time_str}): fixation_count={fixation_count}")
                            # 固着検知: 連続3回重複→Cloud APIフォールバック試行
                            if fixation_count >= 3 and not using_cloud_fallback:
                                using_cloud_fallback = True
                                logger.warning("ローカルLLM固着検知→残りのバッチをCloud API(DeepSeek V3.2)にフォールバック")
                                try:
                                    from tools.event_logger import log_event
                                    await log_event("sns.llm_fixation", "sns", {
                                        "fixation_count": fixation_count,
                                        "fallback_to": "deepseek-v3.2",
                                        "remaining_items": results["total"] - inserted_count,
                                    }, severity="warning")
                                except Exception:
                                    pass
                            # 固着10回以上 = Cloud fallback も budget 超過でブロックされるデッドロック状態
                            # バッチ残りを強制スキップして無限ループを防ぐ（2026-04-06 デバッグで発見）
                            if fixation_count >= 10:
                                logger.error(
                                    f"固着デッドロック検出 ({platform}): fixation_count={fixation_count}、"
                                    f"残り{results['total'] - inserted_count}件スキップ"
                                )
                                try:
                                    from tools.event_logger import log_event
                                    await log_event("sns.fixation_deadlock", "sns", {
                                        "fixation_count": fixation_count,
                                        "platform": platform,
                                        "skipped": results["total"] - inserted_count,
                                        "reason": "Cloud fallback blocked by budget, local LLM repeating same output",
                                    }, severity="error")
                                except Exception:
                                    pass
                                break  # このバッチ内ループを強制終了
                            continue

                        # 検証6: 品質スコア
                        candidate_quality = _score_multi_axis(
                            candidate_draft,
                            persona_keywords=_PERSONA_KEYWORDS,
                            theme=theme,
                            theme_category=_theme_category,
                            platform=platform,
                            account=account,
                        )

                        # 0.50未満は完全却下
                        if candidate_quality < 0.50:
                            continue

                        # 候補として保持（閾値未満でも）
                        candidates.append((candidate_draft, candidate_quality))

                        # 閾値以上なら即採用（これ以上の生成は不要）
                        if candidate_quality >= quality_threshold:
                            fixation_count = max(0, fixation_count - 1)
                            break

                    except Exception as e:
                        logger.warning(f"SNS生成失敗 ({platform}/{account}/{time_str}): {e}")
                        break

                # 候補から最良を選択
                if candidates:
                    best_candidate = max(candidates, key=lambda c: c[1])
                    if best_candidate[1] >= quality_threshold:
                        draft = best_candidate[0]
                        quality = best_candidate[1]
                        break  # phaseループを抜ける

            # === Phase 3.5: ボーダーライン再挑戦 ===
            # 候補はあるが全て閾値未満の場合、temperature変更で追加2回生成
            if not draft and candidates:
                best_so_far = max(candidates, key=lambda c: c[1])
                if best_so_far[1] >= 0.50:
                    retry_sel = model_sel.copy() if not using_cloud_fallback else {
                        "provider": "deepseek", "model": "deepseek-v3.2",
                        "tier": "A", "via": "direct",
                        "note": "ボーダーライン再挑戦",
                    }
                    for retry_attempt in range(2):
                        try:
                            retry_kwargs = {}
                            if retry_sel.get("provider") == "local":
                                # 再挑戦時はtemperatureをさらに変化させる
                                retry_kwargs["temperature"] = 0.8 + (retry_attempt * 0.3)  # 0.8→1.1
                                retry_kwargs["repeat_penalty"] = 1.1 + (retry_attempt * 0.15)
                                retry_kwargs["seed"] = random.randint(1, 999999)

                            result = await call_llm(
                                prompt=user_prompt,
                                system_prompt=system_prompt,
                                model_selection=retry_sel,
                                **retry_kwargs,
                            )
                            retry_draft = result.get("text", "").strip()
                            if not retry_draft or len(retry_draft) < 10:
                                continue

                            # 文字数制限
                            if platform == "x" and len(retry_draft) > 150:
                                retry_draft = _truncate_for_x(retry_draft, 150)
                            elif platform == "bluesky" and len(retry_draft) > 150:
                                retry_draft = retry_draft[:297] + "..."
                            elif platform == "threads" and len(retry_draft) > 500:
                                retry_draft = retry_draft[:497] + "..."

                            # 基本検証（NG/AI臭/事実チェック/重複）
                            ng_r = check_platform_ng(retry_draft, platform)
                            if not ng_r["passed"]:
                                continue
                            if _check_ai_cliche(retry_draft):
                                continue
                            retry_factual_ok, _ = await _check_sns_factual(
                                retry_draft, platform=platform, account=account,
                            )
                            if not retry_factual_ok:
                                continue
                            retry_head = retry_draft[:25]
                            if any(retry_head in h for h in generated_heads) or \
                               any(retry_head in p for p in recent_posts):
                                continue

                            retry_quality = _score_multi_axis(
                                retry_draft,
                                persona_keywords=_PERSONA_KEYWORDS,
                                theme=theme,
                                theme_category=_theme_category,
                                platform=platform,
                                account=account,
                            )
                            if retry_quality >= 0.50:
                                candidates.append((retry_draft, retry_quality))
                        except Exception:
                            continue

                    # 全候補（元 + リトライ）から最良を選択
                    best_final = max(candidates, key=lambda c: c[1])
                    draft = best_final[0]
                    quality = best_final[1]

            # 候補がゼロの場合
            if not draft and not candidates:
                draft = ""
                quality = 0.0

            # === Phase 4: 2段階精錬 ===
            if draft and quality >= 0.50:
                try:
                    refine_sel = choose_best_model_v6(
                        task_type="sns_draft", quality="medium",
                        budget_sensitive=True, needs_japanese=True,
                    )
                    refine_kwargs = {}
                    if refine_sel.get("provider") == "local":
                        refine_kwargs["temperature"] = 0.9
                        refine_kwargs["repeat_penalty"] = 1.2

                    refine_result = await call_llm(
                        prompt=f"以下のSNS投稿文を、より自然で人間味のある文体に書き直してください。AI臭い表現を除去し、三点リーダーや短い文のリズムを取り入れてください。内容は変えず、表現だけ改善してください。\n\n{draft}",
                        system_prompt="島原大知の文体で書き直すライター。一人称は元の文に合わせる。投稿テキストのみ出力。",
                        model_selection=refine_sel,
                        **refine_kwargs,
                    )
                    refined = refine_result.get("text", "").strip()
                    if refined and len(refined) >= 10:
                        # 長さ制限
                        if platform == "x" and len(refined) > 150:
                            refined = _truncate_for_x(refined, 150)
                        elif platform == "bluesky" and len(refined) > 150:
                            refined = refined[:297] + "..."
                        elif platform == "threads" and len(refined) > 500:
                            refined = refined[:497] + "..."
                        # NGチェック + 事実チェック（精錬後に禁止表現が入る可能性）
                        ng_refined = check_platform_ng(refined, platform)
                        refined_factual_ok, _ = await _check_sns_factual(
                            refined, platform=platform, account=account,
                        )
                        if ng_refined["passed"] and refined_factual_ok:
                            refined_quality = _score_multi_axis(
                                refined,
                                persona_keywords=_PERSONA_KEYWORDS,
                                theme=theme,
                                theme_category=_theme_category,
                                platform=platform,
                                account=account,
                            )
                            if refined_quality > quality:
                                # content_edit_logに精錬記録
                                try:
                                    await conn.execute(
                                        """INSERT INTO content_edit_log
                                           (content_type, original_text, edited_text, model_used,
                                            quality_score_before, quality_score_after)
                                           VALUES ($1, $2, $3, $4, $5, $6)""",
                                        f"sns_{platform}", draft[:500], refined[:500],
                                        refine_sel.get("model", "unknown"),
                                        quality, refined_quality,
                                    )
                                except Exception:
                                    pass
                                draft = refined
                                quality = refined_quality
                except Exception:
                    pass  # 精錬失敗時は元のdraftを使用

            if not draft:
                results["rejected"] += 1
                continue

            # === セマンティック重複チェック（直近投稿と類似していたらreject）===
            try:
                import re as _re2
                _is_duplicate = False
                # bigramベースのJaccard類似度（文字単位より精度高い）
                def _bigrams(t):
                    t = _re2.sub(r'\s+', '', t[:150])
                    return set(t[i:i+2] for i in range(len(t)-1)) if len(t) > 1 else set()
                draft_bg = _bigrams(draft)
                for rp in recent_posts:
                    if not rp:
                        continue
                    rp_bg = _bigrams(rp)
                    intersection = len(draft_bg & rp_bg)
                    union = len(draft_bg | rp_bg)
                    similarity = intersection / union if union > 0 else 0
                    if similarity > 0.35:  # bigram Jaccard 0.35は非常に類似
                        _is_duplicate = True
                        logger.info(f"セマンティック重複(bigram={similarity:.2f}): {draft[:40]}...")
                        break
                # さらに、ポエムパターン正規表現でもチェック
                _dup_patterns = [
                    _re2.compile(r"風[がはも]*[とう]*[に]*(止[みんまっ]|やん)"),
                    _re2.compile(r"画面[はが]*真っ[暗黒]"),
                    _re2.compile(r"息を[殺ひ]"),
                    _re2.compile(r"光の粒子"),
                    _re2.compile(r"指先[をにで]"),
                    _re2.compile(r"肩を[落お]"),
                ]
                _phrase_matches = sum(1 for kp in _dup_patterns if kp.search(draft))
                if _phrase_matches >= 2:
                    _is_duplicate = True
                    logger.info(f"ポエムフレーズ重複reject({_phrase_matches}hit): {draft[:40]}...")
                if _is_duplicate:
                    results["rejected"] += 1
                    continue
            except Exception:
                pass

            # === HarnessLinter: 投稿前の機械的制約チェック ===
            try:
                from tools.harness_linter import get_harness_linter
                linter = get_harness_linter()
                lint_result = await linter.lint_action(
                    "sns_posting",
                    draft,
                    {"check_persona": True, "platform": platform},
                )
                if not lint_result.passed:
                    results["rejected"] += 1
                    logger.warning(
                        f"HarnessLinter BLOCK SNS: {platform}/{account} — "
                        f"{lint_result.violations[0]['detail'][:80] if lint_result.violations else 'N/A'}"
                    )
                    # BLOCK投稿もDBに保存（監査証跡）
                    await conn.execute(
                        """INSERT INTO posting_queue
                           (platform, account, content, scheduled_at, status, quality_score, theme_category)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        platform, account, draft,
                        target_date.replace(hour=0, minute=0, second=0, microsecond=0),
                        "lint_blocked", quality, _theme_category,
                    )
                    continue
            except Exception as e:
                logger.error(f"HarnessLinter SNSチェックエラー（続行）: {e}")

            # === アフィリエイトリンク自動挿入 ===
            affiliate_url_value = None
            try:
                from tools.affiliate_manager import (
                    match_affiliate, should_insert_today,
                    format_affiliate_link, log_affiliate_insertion,
                )
                aff_match = match_affiliate(draft, platform)
                if aff_match and await should_insert_today(conn):
                    updated = format_affiliate_link(draft, aff_match, platform)
                    if updated != draft:
                        draft = updated
                        affiliate_url_value = aff_match["url"]
                        _safe_fire(log_affiliate_insertion(
                            platform, account,
                            aff_match["service_name"], aff_match["url"],
                        ))
            except Exception as e:
                logger.debug(f"アフィリエイト挿入スキップ: {e}")

            # === コンテンツ除去（秘密情報漏洩防止） ===
            draft = redact_content(draft)
            safe, redact_issues = is_safe_to_publish(draft)
            if not safe:
                results["rejected"] += 1
                logger.warning(
                    f"秘密情報検出で投稿却下: {platform}/{account} — {redact_issues}"
                )
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    platform, account, draft,
                    target_date.replace(hour=0, minute=0, second=0, microsecond=0),
                    "redact_blocked", quality, _theme_category,
                )
                continue

            # === SYUTAINβ auto-generated ラベル付与 ===
            # shimahraアカウントのみラベルを付ける（SYUTAINβアカウントは元々システム前提なので不要）
            if platform == "x" and account == "shimahara":
                label = "\n\n[SYUTAINβ auto-generated]"
                if len(draft) + len(label) <= 150:
                    draft = draft + label

            # === ハッシュタグ自動付与（テーマ内容に基づいて後処理で選定） ===
            try:
                # LLMが本文に含めたハッシュタグを除去（後処理で付け直す）
                import re as _re_tag
                draft = _re_tag.sub(r'\s*#\S+', '', draft).strip()

                tags = _select_hashtags(theme, _theme_category, platform, max_tags=2)

                if tags and platform in ("x", "threads", "bluesky"):
                    tag_str = " " + " ".join(tags)
                    max_len = 150 if platform in ("x", "bluesky") else 300
                    if len(draft) + len(tag_str) <= max_len:
                        draft = draft + tag_str
            except Exception:
                pass

            # === note記事リンク自動付与（20%の確率で直近のnote記事URLを付与） ===
            try:
                if random.random() < 0.20 and platform in ("x", "bluesky", "threads"):
                    note_row = await conn.fetchrow(
                        """SELECT publish_url FROM product_packages
                        WHERE status = 'published' AND publish_url LIKE 'https://note.com/%'
                        ORDER BY published_at DESC LIMIT 1"""
                    )
                    if note_row and note_row["publish_url"]:
                        note_url = note_row["publish_url"]
                        if platform == "x":
                            link_text = f"\n\n{note_url}"
                            if len(draft) + len(link_text) <= 150:
                                draft = draft + link_text
                        else:
                            draft = draft + f"\n\n{note_url}"
            except Exception:
                pass

            # scheduled_atにランダムオフセット (JST)
            hour, minute = map(int, time_str.split(":"))
            offset_min = _random_offset_minutes()
            scheduled = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=JST)
            scheduled += timedelta(minutes=offset_min)

            # テーマ品質追跡に記録
            _track_theme_quality(theme, platform, quality)

            # V2: 虚偽フィルター → 検出時は修正を試みる（最大2回）
            for _fix_attempt in range(3):
                falsity_issues = check_falsity(draft, theme=theme, theme_category=_theme_category, materials=_materials)
                if not falsity_issues:
                    break  # 虚偽なし、通過

                if _fix_attempt < 2:
                    # 虚偽箇所を正規表現で除去
                    _original_len = len(draft)
                    for issue in falsity_issues:
                        if "未使用ツール名" in issue:
                            draft = _re_falsity.sub(r'(?:Grafana|Prometheus|Datadog|Sentry|NewRelic|Splunk)[^。\n]*[。\n]?', '', draft)
                        elif "組織捏造" in issue:
                            draft = _re_falsity.sub(r'[^。\n]*(?:運用チーム|開発チーム|開発メンバー|同僚|離職率|部署|担当者が)[^。\n]*[。\n]?', '', draft)
                        elif "コーディング捏造" in issue:
                            draft = _re_falsity.sub(r'[^。\n]*(?:コードを書[いくけ]|プログラミングし|コーディングし)[^。\n]*[。\n]?', '', draft)
                        elif "VTuber活動捏造" in issue:
                            draft = _re_falsity.sub(r'[^。\n]*(?:VTuberとして活動|配信し(?:た|て)|VTuberデビュー)[^。\n]*[。\n]?', '', draft)
                    draft = draft.strip()

                    # 削除後に短すぎたらLLMで補完
                    _min_len = 30 if platform == "x" else 50
                    if len(draft) < _min_len:
                        try:
                            _fix_result = await call_llm(
                                prompt=f"以下の投稿文を自然に書き直してください。虚偽（{', '.join(falsity_issues)}）を含まないように。テーマ: {theme}\n\n元の文: {draft}\n\n書き直した投稿文のみを出力:",
                                system_prompt=system_prompt,
                                model_selection=model_sel,
                            )
                            draft = _fix_result.get("text", draft).strip()
                        except Exception:
                            pass

                    if len(draft) != _original_len:
                        logger.info(f"虚偽修正 attempt {_fix_attempt+1} ({platform}/{account}): {falsity_issues} → {_original_len}字→{len(draft)}字")
                else:
                    # 3回目も虚偽が残る → リジェクト
                    logger.warning(f"虚偽修正失敗 ({platform}/{account}): {falsity_issues}")
                    results["rejected"] += 1
                    await conn.execute(
                        """INSERT INTO posting_queue
                           (platform, account, content, scheduled_at, status, quality_score, theme_category)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        platform, account, draft, scheduled, "falsity_blocked", quality, _theme_category,
                    )
                    break
            else:
                # forループが正常完了（breakなし = 虚偽なしで通過）
                pass
            if falsity_issues and _fix_attempt >= 2:
                continue  # リジェクト済み、次の投稿へ

            # V2: ファクトチェック（DB突合 + intel照合、SNSレベル）
            try:
                from tools.fact_checker import check_facts, apply_hedging
                fc_result = await check_facts(draft, check_level="sns")
                if fc_result.get("suggestions"):
                    # 一次ソースなしの主張に留保表現を自動適用
                    draft = apply_hedging(draft, fc_result["suggestions"])
                    logger.info(f"ファクトチェック留保適用 ({platform}/{account}): {len(fc_result['suggestions'])}件")
                if not fc_result.get("passed"):
                    logger.warning(f"ファクトチェック不合格 ({platform}/{account}): {fc_result['issues'][:3]}")
                    quality -= 0.05  # 不合格なら品質減点
            except Exception as fc_err:
                logger.debug(f"ファクトチェック失敗（続行）: {fc_err}")

            # V2: アカウント一致チェック（スコア調整）
            voice_adj = check_account_voice(draft, platform, account)
            quality += voice_adj

            # 品質スコアに基づく承認判定（プラットフォーム別閾値）
            if quality >= quality_threshold:
                post_status = "pending"  # 閾値以上は自動投稿キューへ
            else:
                post_status = "rejected"  # 品質不足で却下
                results["rejected"] += 1
                logger.info(f"SNS投稿却下: 品質{quality:.3f} < 閾値{quality_threshold:.2f} ({platform}/{account})")
                # 却下投稿もDBに保存（監査証跡）
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category, affiliate_url)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    platform, account, draft, scheduled, post_status, quality, _theme_category, affiliate_url_value,
                )
                continue

            # A/Bテスト: ~20% の投稿で variant B を追加生成
            _ab_test_id = None
            _ab_variant = None
            if random.random() < 0.20 and post_status == "pending":
                import uuid as _uuid_ab
                _ab_test_id = f"ab_{_uuid_ab.uuid4().hex[:12]}"
                _ab_variant = "A"

            # posting_queueにINSERT
            await conn.execute(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category, affiliate_url, ab_test_id, ab_variant)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                platform, account, draft, scheduled, post_status, quality, _theme_category, affiliate_url_value,
                _ab_test_id, _ab_variant,
            )
            inserted_count += 1

            # A/Bテスト: variant B を生成（別角度で2時間後に投稿）
            if _ab_test_id:
                try:
                    from tools.llm_router import choose_best_model_v6 as _ab_choose, call_llm as _ab_call
                    _ab_model = _ab_choose(
                        task_type="chat", quality="medium",
                        budget_sensitive=True, needs_japanese=True,
                    )
                    _ab_result = await _ab_call(
                        prompt=(
                            f"以下のSNS投稿を、別の切り口/冒頭で書き直してください。"
                            f"同じ情報を伝えるが、入り口が違う投稿にする。\n\n"
                            f"元の投稿:\n{draft}\n\n"
                            f"プラットフォーム: {platform}\n"
                            f"文字数は元と同程度。別の切り口で書き直した投稿のみ出力。"
                        ),
                        system_prompt="SNS投稿のA/Bテスト variant B を生成するアシスタント。",
                        model_selection=_ab_model,
                    )
                    _variant_b = (_ab_result.get("text", "") or "").strip()
                    if _variant_b and len(_variant_b) > 20:
                        _scheduled_b = scheduled + timedelta(hours=2)
                        await conn.execute(
                            """INSERT INTO posting_queue
                               (platform, account, content, scheduled_at, status, quality_score, theme_category, affiliate_url, ab_test_id, ab_variant)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                            platform, account, _variant_b, _scheduled_b, "pending", quality, _theme_category, affiliate_url_value,
                            _ab_test_id, "B",
                        )
                        inserted_count += 1
                        logger.info(f"A/Bテスト生成: {_ab_test_id} ({platform}/{account}) variant B at {_scheduled_b}")
                except Exception as _ab_err:
                    logger.warning(f"A/Bテスト variant B 生成失敗（続行）: {_ab_err}")

            # 直近投稿リスト更新（重複検知用）
            recent_posts.insert(0, draft[:60])
            if len(recent_posts) > 15:
                recent_posts = recent_posts[:15]
            generated_heads.append(draft[:25])

            # プラットフォーム別カウント
            key = f"{platform}/{account}"
            results["by_platform"][key] = results["by_platform"].get(key, 0) + 1

        results["inserted"] = inserted_count
        results["cloud_fallback"] = using_cloud_fallback
        results["fixation_detected"] = fixation_count
        results["quality_thresholds"] = PLATFORM_QUALITY_THRESHOLDS.copy()

        # テーマ品質サマリ
        try:
            theme_summary = {}
            for (theme, pf), scores in _theme_quality_tracker.items():
                key = f"{theme}/{pf}"
                theme_summary[key] = {
                    "avg": round(sum(scores) / len(scores), 3),
                    "count": len(scores),
                    "min": round(min(scores), 3),
                }
            results["theme_quality_summary"] = theme_summary
        except Exception:
            pass

        logger.info(
            f"SNS投稿生成完了: {inserted_count}/{results['total']}件 "
            f"(却下{results['rejected']}, AI臭{results['ai_cliche']}, "
            f"固着検知{fixation_count}, Cloud fallback={'有' if using_cloud_fallback else '無'}, "
            f"閾値={PLATFORM_QUALITY_THRESHOLDS})"
        )

      except Exception as e:
        logger.error(f"SNS一括生成エラー: {e}")
        results["error"] = str(e)

    return results


async def evaluate_ab_tests() -> list[dict]:
    """24時間以上経過したA/Bテストの結果を評価し、勝者をログに記録する。

    Returns:
        list[dict]: 各テストの結果 {"ab_test_id", "winner", "a_score", "b_score"}
    """
    eval_results = []
    try:
        async with get_connection() as conn:
            # 両バリアントとも投稿から24h以上経過したA/Bテストペアを集計
            # (バリアントBはAの2時間後に投稿されるため、Bの経過時間で判定)
            tests = await conn.fetch(
                """SELECT ab_test_id,
                       json_agg(json_build_object(
                           'variant', ab_variant,
                           'engagement_data', engagement_data,
                           'content', LEFT(content, 80),
                           'posted_at', posted_at,
                           'id', id
                       )) as variants
                   FROM posting_queue
                   WHERE ab_test_id IS NOT NULL
                     AND status = 'posted'
                   GROUP BY ab_test_id
                   HAVING COUNT(*) = 2
                     AND MIN(posted_at) < NOW() - INTERVAL '24 hours'
                     AND MAX(posted_at) < NOW() - INTERVAL '24 hours'"""
            )

            for test in tests:
                ab_id = test["ab_test_id"]
                variants_raw = test["variants"]
                if isinstance(variants_raw, str):
                    variants_raw = json.loads(variants_raw)

                scores = {}
                for v in variants_raw:
                    variant = v.get("variant", "?")
                    ed = v.get("engagement_data") or {}
                    if isinstance(ed, str):
                        try:
                            ed = json.loads(ed)
                        except Exception:
                            ed = {}
                    score = (
                        (ed.get("likes", 0) or 0)
                        + (ed.get("retweets", 0) or ed.get("reposts", 0) or 0) * 2
                        + (ed.get("replies", 0) or 0) * 3
                    )
                    scores[variant] = score

                a_score = scores.get("A", 0)
                b_score = scores.get("B", 0)
                winner = "A" if a_score >= b_score else "B"

                result_entry = {
                    "ab_test_id": ab_id,
                    "winner": winner,
                    "a_score": a_score,
                    "b_score": b_score,
                }
                eval_results.append(result_entry)
                logger.info(f"A/Bテスト結果: {ab_id} → winner={winner} (A={a_score}, B={b_score})")

                # event_log に記録
                try:
                    from tools.event_logger import log_event
                    await log_event("sns.ab_test_result", "system", result_entry)
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"A/Bテスト評価エラー: {e}")

    return eval_results
