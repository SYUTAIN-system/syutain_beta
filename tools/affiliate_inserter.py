"""
SYUTAINβ V25 アフィリエイトリンク自動挿入
config/affiliate_links.yaml に基づいて SNS投稿にアフィリエイトリンクを自然挿入する。
"""

import os
import logging
from pathlib import Path
from typing import Optional

import yaml

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.affiliate")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "affiliate_links.yaml"

_config_cache: Optional[dict] = None


def load_affiliate_config() -> dict:
    global _config_cache
    if _config_cache:
        return _config_cache
    try:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f) or {}
        return _config_cache
    except Exception as e:
        logger.warning(f"affiliate config load failed: {e}")
        return {"rate_limit_pct": 30, "programs": []}


def find_matching_affiliate(text: str) -> Optional[dict]:
    """投稿テキストにマッチするアフィリエイトプログラムを返す（優先度順）"""
    config = load_affiliate_config()
    programs = sorted(config.get("programs", []), key=lambda p: p.get("priority", 0), reverse=True)
    for prog in programs:
        url = prog.get("affiliate_url", "")
        if "example.com" in url:
            continue  # プレースホルダーはスキップ
        for kw in prog.get("keywords", []):
            if kw in text:
                return prog
    return None


def insert_affiliate_link(text: str, affiliate: dict, platform: str) -> str:
    """テキストにアフィリエイトリンクを自然に追加"""
    url = affiliate.get("affiliate_url", "")
    name = affiliate.get("service_name", "")
    if not url or "example.com" in url:
        return text

    # プラットフォーム別の文字数制限
    limits = {"x": 280, "bluesky": 300, "threads": 500}
    max_len = limits.get(platform, 500)

    suffix = f"\n{url}"
    if len(text) + len(suffix) > max_len:
        # 収まらない場合は挿入しない
        return text

    return text + suffix


async def should_insert_affiliate(platform: str) -> bool:
    """本日のアフィリエイト挿入率が上限以内か"""
    config = load_affiliate_config()
    rate_limit = config.get("rate_limit_pct", 30) / 100.0
    try:
        async with get_connection() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE scheduled_at::date = CURRENT_DATE AND platform = $1",
                platform,
            ) or 1
            affiliate_count = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE scheduled_at::date = CURRENT_DATE AND platform = $1 AND theme_category LIKE '%%affiliate%%'",
                platform,
            ) or 0
            return affiliate_count / max(total, 1) < rate_limit
    except Exception as e:
        logger.warning(f"affiliate rate check failed: {e}")
        return True


async def process_post_for_affiliate(text: str, platform: str) -> tuple[str, Optional[str]]:
    """投稿テキストにアフィリエイトを適用。(修正テキスト, program名 or None)を返す"""
    if not await should_insert_affiliate(platform):
        return text, None

    match = find_matching_affiliate(text)
    if not match:
        return text, None

    new_text = insert_affiliate_link(text, match, platform)
    if new_text == text:
        return text, None

    return new_text, match.get("service_name")
