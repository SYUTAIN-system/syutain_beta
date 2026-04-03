"""
SYUTAINβ アフィリエイトリンク自動挿入マネージャー

SNS投稿にアフィリエイトリンクを自然に挿入する。
- キーワードマッチで最適なリンクを選択
- プラットフォーム別フォーマット
- レートリミット（1日の投稿の最大30%にのみ挿入）
"""

import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("syutain.affiliate_manager")

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "affiliate_links.yaml"

# キャッシュ（プロセス内）
_config_cache: dict = {}
_config_loaded_at: float = 0.0
_CACHE_TTL = 300  # 5分


def _load_config() -> dict:
    """YAML設定を読み込み（キャッシュ付き）"""
    global _config_cache, _config_loaded_at
    import time

    now = time.time()
    if _config_cache and (now - _config_loaded_at) < _CACHE_TTL:
        return _config_cache

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
        _config_loaded_at = now
    except Exception as e:
        logger.error(f"アフィリエイト設定読み込み失敗: {e}")
        _config_cache = {}

    return _config_cache


def match_affiliate(post_content: str, platform: str) -> Optional[dict]:
    """投稿内容をスキャンし、最適なアフィリエイトリンクを返す。

    Args:
        post_content: 投稿テキスト
        platform: "x" / "bluesky" / "threads"

    Returns:
        マッチした場合: {"service_name": str, "url": str, "priority": int}
        マッチなしまたはスキップ: None
    """
    if not post_content:
        return None

    config = _load_config()
    programs = config.get("programs", [])
    if not programs:
        return None

    # キーワードマッチ → 候補収集
    matches = []
    for prog in programs:
        keywords = prog.get("keywords", [])
        url = prog.get("affiliate_url", "")
        if not url or "example.com" in url:
            continue  # プレースホルダーURLはスキップ

        for kw in keywords:
            if kw in post_content:
                matches.append({
                    "service_name": prog["service_name"],
                    "url": url,
                    "priority": prog.get("priority", 5),
                })
                break  # 同一プログラム内で複数キーワードヒットしても1回

    if not matches:
        return None

    # priority降順でソート、最高priorityの中からランダム選択（同率対応）
    matches.sort(key=lambda m: m["priority"], reverse=True)
    top_priority = matches[0]["priority"]
    top_matches = [m for m in matches if m["priority"] == top_priority]
    return random.choice(top_matches)


async def should_insert_today(conn) -> bool:
    """今日の挿入率がrate_limit_pctを超えていないか確認する。

    Args:
        conn: asyncpg connection

    Returns:
        挿入可能ならTrue
    """
    config = _load_config()
    rate_limit_pct = config.get("rate_limit_pct", 30)

    try:
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) FILTER (WHERE status IN ('pending', 'posted')) AS total,
                COUNT(*) FILTER (WHERE affiliate_url IS NOT NULL
                                 AND status IN ('pending', 'posted')) AS with_affiliate
            FROM posting_queue
            WHERE scheduled_at::date = CURRENT_DATE
               OR scheduled_at::date = (CURRENT_DATE + INTERVAL '1 day')::date"""
        )
        total = row["total"] if row else 0
        with_affiliate = row["with_affiliate"] if row else 0

        if total == 0:
            return True

        current_pct = (with_affiliate / total) * 100
        return current_pct < rate_limit_pct

    except Exception as e:
        logger.debug(f"アフィリエイト率チェック失敗（挿入許可）: {e}")
        return True  # DB確認できない場合は許可（安全側）


def format_affiliate_link(
    post_content: str,
    match: dict,
    platform: str,
) -> str:
    """投稿にアフィリエイトリンクを自然に付加する。

    Args:
        post_content: 元の投稿テキスト
        match: match_affiliate()の返り値
        platform: "x" / "bluesky" / "threads"

    Returns:
        リンク付きの投稿テキスト。文字数超過の場合は元テキストをそのまま返す。
    """
    service_name = match["service_name"]
    url = match["url"]

    if platform == "x":
        # X: 文字数制限が厳しい。付加分込みで150字以内に収まるか確認
        suffix = f"\n詳しくは→ {url}"
        combined = post_content + suffix
        if len(combined) <= 150:
            return combined
        # 収まらない場合は挿入しない
        return post_content

    else:
        # Bluesky / Threads: 改行して自然に追加
        suffix = f"\n{service_name}: {url}"
        char_limit = 300 if platform == "bluesky" else 500
        combined = post_content + suffix
        if len(combined) <= char_limit:
            return combined
        return post_content


async def log_affiliate_insertion(
    platform: str,
    account: str,
    service_name: str,
    url: str,
) -> None:
    """アフィリエイト挿入をevent_logに記録する。"""
    try:
        from tools.event_logger import log_event
        await log_event(
            event_type="sns.affiliate_inserted",
            category="sns",
            payload={
                "platform": platform,
                "account": account,
                "service_name": service_name,
                "affiliate_url": url,
            },
            severity="info",
        )
    except Exception as e:
        logger.debug(f"アフィリエイトログ記録失敗: {e}")
