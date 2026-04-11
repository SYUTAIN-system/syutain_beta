"""Learning Feedback Loop — 実エンゲージメントをプロンプト改善に還元

2026-04-12 P2-3 実装。背景:
- learning_manager は週次レポートを生成するが、結果が次の生成プロンプトに
  反映されていない (学習→改善の閉ループが切れている)。
- model_quality_log のスコアはプロンプト品質の指標だが、実エンゲージメントとは
  別物。高 quality_score でも likes=0 のケースが多い。

本ツール:
- posting_queue から直近 7 日のエンゲージメント勝者 (likes + impressions 高)
  を抽出
- SYUTAINβ の広告/告知 (記事公開告知、定型テンプレ) は除外
- プラットフォーム別・アカウント別に top-5 を選出し、
  `strategy/learned_examples.json` (gitignored) にキャッシュ
- 次回 SNS 生成時、プロンプトに few-shot として混ぜる hook を追加
- 毎週月曜 03:30 JST に実行 (SNS 品質自動改善と同じ時間帯)

フィードバック精度:
- top_engagement_score = like_count * 5 + impression_count * 0.02 + reply_count * 3
- 各 (platform, account) キーで上位 5 件を記録
- 古い例 (>14 日) は自動的に退役
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"
LEARNED_EXAMPLES_PATH = STRATEGY_DIR / "learned_examples.json"

# 各 (platform, account) スロットに保持する例の上限
MAX_EXAMPLES_PER_SLOT = 5

# エンゲージメントスコアの重み
LIKE_WEIGHT = 5.0
IMP_WEIGHT = 0.02
REPLY_WEIGHT = 3.0
REPOST_WEIGHT = 2.0

# 除外パターン (定型テンプレ・告知系)
EXCLUDE_SUBSTRINGS = (
    "新しい記事を公開しました",
    "【新記事】",
    "新記事:",
    "[SYUTAINβ auto-generated]",
)


def _compute_engagement_score(engagement: dict) -> float:
    """エンゲージメント辞書からスコアを算出"""
    if not engagement or not isinstance(engagement, dict):
        return 0.0
    likes = int(engagement.get("like_count", 0) or 0)
    imp = int(engagement.get("impression_count", 0) or 0)
    replies = int(engagement.get("reply_count", 0) or 0)
    reposts = int(engagement.get("repost_count", 0) or 0)
    return (
        likes * LIKE_WEIGHT
        + imp * IMP_WEIGHT
        + replies * REPLY_WEIGHT
        + reposts * REPOST_WEIGHT
    )


def _is_template_post(content: str) -> bool:
    """定型テンプレ投稿か判定 (学習対象から除外)"""
    if not content:
        return True
    for s in EXCLUDE_SUBSTRINGS:
        if s in content:
            return True
    return False


async def collect_engagement_winners(days: int = 7, top_n: int = 5) -> dict:
    """posting_queue から engagement 上位を抽出.

    Returns: {
        "x_shimahara": [{"content": str, "score": float, "likes": int, ...}, ...],
        "x_syutain": [...],
        "bluesky": [...],
        "threads": [...],
    }
    """
    from tools.db_pool import get_connection
    result = {"x_shimahara": [], "x_syutain": [], "bluesky": [], "threads": []}

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT platform, account, content, engagement_data, posted_at, quality_score
                   FROM posting_queue
                   WHERE status='posted' AND engagement_data IS NOT NULL
                     AND posted_at > NOW() - make_interval(days => $1)""",
                days,
            )
    except Exception as e:
        logger.warning(f"engagement_winners collect 失敗: {e}")
        return result

    # プラットフォーム別 + アカウント別にバケットに入れる
    buckets: dict[str, list] = {
        "x_shimahara": [],
        "x_syutain": [],
        "bluesky": [],
        "threads": [],
    }

    for r in rows:
        content = r["content"] or ""
        if _is_template_post(content):
            continue
        engagement = r["engagement_data"]
        if isinstance(engagement, str):
            try:
                engagement = json.loads(engagement)
            except Exception:
                engagement = {}
        score = _compute_engagement_score(engagement or {})
        if score <= 0:
            continue

        item = {
            "content": content[:300],
            "score": round(score, 2),
            "likes": int((engagement or {}).get("like_count", 0) or 0),
            "imp": int((engagement or {}).get("impression_count", 0) or 0),
            "replies": int((engagement or {}).get("reply_count", 0) or 0),
            "posted_at": r["posted_at"].isoformat() if r["posted_at"] else None,
            "quality_score": float(r["quality_score"]) if r["quality_score"] is not None else None,
        }

        platform = r["platform"]
        account = (r["account"] or "").lower()
        if platform == "x":
            if account in ("shimahara", "sima_daichi"):
                buckets["x_shimahara"].append(item)
            else:
                buckets["x_syutain"].append(item)
        elif platform == "bluesky":
            buckets["bluesky"].append(item)
        elif platform == "threads":
            buckets["threads"].append(item)

    # Top-N 選出
    for key in buckets:
        buckets[key].sort(key=lambda x: x["score"], reverse=True)
        result[key] = buckets[key][:top_n]

    return result


async def update_learned_examples() -> dict:
    """エンゲージメント勝者を strategy/learned_examples.json に保存."""
    winners = await collect_engagement_winners(days=7, top_n=MAX_EXAMPLES_PER_SLOT)

    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)

    # 既存ファイル読み込み (履歴保持用)
    existing = {}
    if LEARNED_EXAMPLES_PATH.exists():
        try:
            with open(LEARNED_EXAMPLES_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    payload = {
        "updated_at": datetime.now(JST).isoformat(),
        "source": "engagement_winners_last_7d",
        "weights": {
            "like": LIKE_WEIGHT,
            "impression": IMP_WEIGHT,
            "reply": REPLY_WEIGHT,
            "repost": REPOST_WEIGHT,
        },
        "slots": winners,
    }

    with open(LEARNED_EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    summary = {k: len(v) for k, v in winners.items()}
    logger.info(f"learned_examples 更新完了: {summary}")
    return {"ok": True, "summary": summary, "path": str(LEARNED_EXAMPLES_PATH)}


def load_learned_examples(platform: str, account: str = "") -> list[dict]:
    """プロンプト生成側から呼ぶ。該当 (platform, account) スロットの例を返す."""
    if not LEARNED_EXAMPLES_PATH.exists():
        return []
    try:
        with open(LEARNED_EXAMPLES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    slots = data.get("slots", {})
    key = platform.lower()
    if platform == "x":
        account_lower = (account or "").lower()
        if account_lower in ("shimahara", "sima_daichi"):
            key = "x_shimahara"
        else:
            key = "x_syutain"
    return slots.get(key, [])


async def run_learning_feedback_cycle() -> dict:
    """週次 entrypoint. 毎週月曜 03:30 JST に scheduler から呼ぶ想定."""
    return await update_learned_examples()
