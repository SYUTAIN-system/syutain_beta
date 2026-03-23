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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.sns_batch")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"

# ===== スケジュール定義 =====

X_SHIMAHARA_TIMES = ["10:00", "13:00", "17:00", "20:00"]
X_SYUTAIN_TIMES = ["11:00", "13:30", "15:00", "17:30", "19:00", "21:00"]
BLUESKY_TIMES = [f"{h}:{m:02d}" for h in range(10, 23) for m in (0, 30)]  # 10:00-22:30
THREADS_TIMES = [f"{h}:30" for h in range(10, 23)]  # 10:30-22:30

# ===== テーマプール =====

THEME_POOL = [
    "AI技術", "VTuber業界", "哲学/思考", "開発進捗", "ビジネス",
    "日常", "映画/映像", "音楽/作詞", "カメラ/写真", "雑談",
    "業界批評", "自己内省",
]

# 時間帯別テーマ重み
TIME_THEME_WEIGHTS = {
    "morning": {"ビジネス": 3, "AI技術": 2, "開発進捗": 2},
    "afternoon": {"日常": 2, "雑談": 2, "カメラ/写真": 1},
    "evening": {"AI技術": 2, "映画/映像": 2, "開発進捗": 2},
    "night": {"哲学/思考": 3, "自己内省": 2, "VTuber業界": 2},
}

# ===== AI定型表現チェック =====

AI_CLICHE_PATTERNS = [
    "について考えてみました", "いかがでしょうか", "ではないでしょうか",
    "皆さん、こんにちは", "みなさん、こんにちは", "それでは、また",
    "を深掘り", "についてまとめてみました", "のポイントは3つ",
    "させていただきます", "特筆すべき", "画期的な", "注目すべき",
    "それでは早速", "見ていきましょう", "ご紹介します",
]


def _check_ai_cliche(text: str) -> bool:
    """AI定型表現が含まれていればTrue"""
    for p in AI_CLICHE_PATTERNS:
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
    return False


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


def _pick_theme(time_str: str, used_today: list[str], recent_themes: list[str]) -> str:
    """テーマを選択（重複回避+時間帯重み）"""
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

    available = [t for t in THEME_POOL if t not in excluded]
    if not available:
        available = THEME_POOL.copy()

    # 重み付きランダム
    weighted = []
    for t in available:
        w = weights.get(t, 1)
        weighted.extend([t] * w)

    return random.choice(weighted)


def _random_offset_minutes() -> int:
    """±0〜8分のランダムオフセット"""
    return random.randint(0, 8)


def _load_writing_style() -> str:
    """daichi_writing_style.md読み込み"""
    path = STRATEGY_DIR / "daichi_writing_style.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


# ===== プロンプト構築 =====

def _build_prompt(platform: str, account: str, theme: str, time_str: str,
                  writing_style: str, few_shot: list[str], recent_posts: list[str]) -> tuple[str, str]:
    """platform+accountに応じたプロンプトを構築。(system_prompt, user_prompt)を返す"""

    period = _get_time_period(time_str)
    avoid = "\n".join(f"- {p[:60]}" for p in recent_posts[:5]) if recent_posts else "（なし）"

    # 文体のゆらぎ指示
    length_hint = random.choice(["30-80字の短文", "80-150字の中文", "150-280字の長文"])
    ellipsis_hint = "文末に「…」を使って余韻を残してください。" if random.random() < 0.17 else "句点「。」で終わる。"
    bracket_hint = "括弧で本音やツッコミを入れてください。" if random.random() < 0.20 else ""
    oneword_hint = "一言だけの投稿にしてください（例:「…うーん」「なるほどなぁ」）。" if random.random() < 0.05 else ""

    if platform == "x" and account == "shimahara":
        # X島原: 最もrawな声
        first_person_pool = ["自分"] * 40 + ["僕"] * 35 + ["私"] * 15 + ["俺"] * 5 + ["（一人称なし）"] * 5
        first_person = random.choice(first_person_pool)

        system_prompt = (
            "あなたは島原大知（@Sima_daichi）本人としてXに投稿する。\n"
            f"{writing_style}\n\n"
            "絶対ルール:\n"
            "- AI臭い定型表現は禁止。島原大知の声で語れ。\n"
            "- 完璧な文章にするな。推敲途中のような人間味を残せ。\n"
            "- 投稿テキストのみを出力。説明や前置きは不要。\n"
        )
        few_shot_text = ""
        if few_shot:
            few_shot_text = "\n\n## 島原大知の過去投稿（参考）\n" + "\n".join(f"- {t}" for t in few_shot[:5])

        user_prompt = (
            f"Xに投稿するドラフトを1つ作ってください。\n"
            f"- 280字以内\n"
            f"- テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}（{period}）\n"
            f"- 一人称: {first_person}\n"
            f"- 長さ目安: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + bracket_hint if bracket_hint else ''}\n"
            f"{'- ' + oneword_hint if oneword_hint else ''}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"{few_shot_text}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "x" and account == "syutain":
        # X SYUTAIN: プロジェクトの声
        system_prompt = (
            "あなたはSYUTAINβ公式Xアカウント（@syutain_beta）として投稿する。\n"
            "論理・設計・分析。結論→根拠→示唆。一人称「私」。\n"
            "AI臭い定型表現は禁止。SYUTAINβとしての独自の声で語れ。\n"
            "投稿テキストのみを出力。\n"
        )
        user_prompt = (
            f"Xに投稿するドラフトを1つ。\n"
            f"- 280字以内。テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}。長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "bluesky":
        # Bluesky: SYUTAINβの設計思想
        system_prompt = (
            "あなたはSYUTAINβとしてBlueskyに投稿する。\n"
            "SYUTAINβの設計思想として島原大知の哲学がDNAとして反映される。\n"
            "一人称は「SYUTAINβ」or 主語なし。「僕」「自分」は使わない。\n"
            "AI臭い定型表現は禁止。投稿テキストのみを出力。\n"
        )
        user_prompt = (
            f"Blueskyに投稿するドラフトを1つ。\n"
            f"- 300字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "threads":
        # Threads: SYUTAINβのカジュアルな声
        system_prompt = (
            "あなたはSYUTAINβとしてThreadsに投稿する。\n"
            "カジュアルで親しみやすいトーン。開発裏話、気づき、ゆるめの技術トピック。\n"
            "一人称は「SYUTAINβ」or 主語なし。「僕」「自分」は使わない。\n"
            "AI臭い定型表現は禁止。投稿テキストのみを出力。\n"
        )
        user_prompt = (
            f"Threadsに投稿するドラフトを1つ。\n"
            f"- 500字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
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


# バッチ分割定義
BATCH_1_SCHEDULE = (
    [("x", "shimahara", t) for t in X_SHIMAHARA_TIMES] +
    [("x", "syutain", t) for t in X_SYUTAIN_TIMES]
)  # 10件
BATCH_2_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES[:13]]  # 前半13件
BATCH_3_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES[13:]]  # 後半13件
BATCH_4_SCHEDULE = [("threads", "syutain", t) for t in THREADS_TIMES]       # 13件


async def generate_batch(batch_name: str, schedule_items: list, target_date: datetime = None, warmup: bool = True) -> dict:
    """指定されたスケジュール分のみ生成してposting_queueにINSERT"""
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)

    if warmup:
        await _warmup_nemotron()

    return await _generate_for_schedule(schedule_items, target_date, batch_name)


async def generate_daily_sns(target_date: datetime = None) -> dict:
    """翌日分49件を一括生成しposting_queueにINSERT（後方互換）"""
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)
    all_schedule = BATCH_1_SCHEDULE + BATCH_2_SCHEDULE + BATCH_3_SCHEDULE + BATCH_4_SCHEDULE
    await _warmup_nemotron()
    return await _generate_for_schedule(all_schedule, target_date, "all")


async def _generate_for_schedule(schedule: list, target_date: datetime, batch_name: str) -> dict:
    """スケジュールリストに基づいて生成"""
    target_date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"SNS投稿生成開始 [{batch_name}]: {target_date_str} ({len(schedule)}件)")

    conn = await asyncpg.connect(DATABASE_URL)
    results = {"total": 0, "inserted": 0, "rejected": 0, "ai_cliche": 0, "by_platform": {}}

    try:
        # 直近7日のテーマ取得
        recent_themes_rows = await conn.fetch(
            "SELECT theme_category FROM posting_queue WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        recent_themes = [r["theme_category"] for r in recent_themes_rows if r["theme_category"]]

        # 直近5投稿の内容取得（重複回避用）
        recent_posts_rows = await conn.fetch(
            "SELECT content FROM posting_queue ORDER BY created_at DESC LIMIT 5"
        )
        recent_posts = [r["content"][:60] for r in recent_posts_rows]

        # daichi_writing_style読み込み
        writing_style = _load_writing_style()

        # daichi_writing_examples取得（X島原用）
        few_shot_rows = await conn.fetch(
            "SELECT tweet_text FROM daichi_writing_examples WHERE is_high_quality = true ORDER BY engagement_score DESC LIMIT 10"
        )
        few_shot_pool = [r["tweet_text"][:200] for r in few_shot_rows]

        # LLMルーター
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm
        from agents.verifier import check_ai_patterns

        # スケジュール組み立て
        schedule = []
        for t in X_SHIMAHARA_TIMES:
            schedule.append(("x", "shimahara", t))
        for t in X_SYUTAIN_TIMES:
            schedule.append(("x", "syutain", t))
        for t in BLUESKY_TIMES:
            schedule.append(("bluesky", "syutain", t))
        for t in THREADS_TIMES:
            schedule.append(("threads", "syutain", t))

        used_today = []
        inserted_count = 0

        for platform, account, time_str in schedule:
            results["total"] += 1

            # テーマ選択
            theme = _pick_theme(time_str, used_today, recent_themes)
            used_today.append(theme)

            # few-shot（X島原のみ）
            few_shot = random.sample(few_shot_pool, min(3, len(few_shot_pool))) if platform == "x" and account == "shimahara" else []

            # プロンプト構築
            system_prompt, user_prompt = _build_prompt(
                platform, account, theme, time_str, writing_style, few_shot, recent_posts,
            )

            # LLM生成（Nemotron優先）
            model_sel = choose_best_model_v6(
                task_type="sns_draft", quality="medium",
                budget_sensitive=True, needs_japanese=True,
            )

            max_retries = 2
            draft = ""
            for attempt in range(max_retries + 1):
                try:
                    result = await call_llm(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        model_selection=model_sel,
                    )
                    draft = result.get("text", "").strip()

                    # 長さ制限
                    if platform == "x" and len(draft) > 280:
                        draft = draft[:277] + "..."
                    elif platform == "bluesky" and len(draft) > 300:
                        draft = draft[:297] + "..."
                    elif platform == "threads" and len(draft) > 500:
                        draft = draft[:497] + "..."

                    if not draft or len(draft) < 10:
                        continue

                    # AI定型表現チェック
                    if _check_ai_cliche(draft):
                        results["ai_cliche"] += 1
                        if attempt < max_retries:
                            continue
                        # 最終試行でもAI臭いなら却下
                        draft = ""
                        break

                    # 品質チェック（check_ai_patterns）
                    ai_check = check_ai_patterns(draft)
                    quality = max(0.0, min(1.0, 0.7 - ai_check["penalty"]))
                    if quality < 0.50:
                        if attempt < max_retries:
                            continue
                        draft = ""
                    break

                except Exception as e:
                    logger.warning(f"SNS生成失敗 ({platform}/{account}/{time_str}): {e}")
                    draft = ""
                    break

            if not draft:
                results["rejected"] += 1
                continue

            # scheduled_atにランダムオフセット
            hour, minute = map(int, time_str.split(":"))
            offset_min = _random_offset_minutes()
            scheduled = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            scheduled += timedelta(minutes=offset_min)

            # posting_queueにINSERT
            await conn.execute(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category)
                   VALUES ($1, $2, $3, $4, 'pending', $5, $6)""",
                platform, account, draft, scheduled, quality, theme,
            )
            inserted_count += 1

            # 直近投稿リスト更新
            recent_posts.insert(0, draft[:60])
            if len(recent_posts) > 10:
                recent_posts = recent_posts[:10]

            # プラットフォーム別カウント
            key = f"{platform}/{account}"
            results["by_platform"][key] = results["by_platform"].get(key, 0) + 1

        results["inserted"] = inserted_count
        logger.info(f"SNS投稿生成完了: {inserted_count}/{results['total']}件 (却下{results['rejected']}, AI臭{results['ai_cliche']})")

    except Exception as e:
        logger.error(f"SNS一括生成エラー: {e}")
        results["error"] = str(e)
    finally:
        await conn.close()

    return results
