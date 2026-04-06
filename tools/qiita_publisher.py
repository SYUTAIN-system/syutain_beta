"""Qiita 記事公開 — API 経由で記事を投稿・管理

Qiita API v2: https://qiita.com/api/v2/docs
認証: Bearer token (QIITA_ACCESS_TOKEN in .env)
"""

import os
import json
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("syutain.qiita_publisher")

QIITA_TOKEN = os.getenv("QIITA_ACCESS_TOKEN", "")
QIITA_API = "https://qiita.com/api/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {QIITA_TOKEN}",
        "Content-Type": "application/json",
    }


async def publish_article(
    title: str,
    body: str,
    tags: list[str] = None,
    private: bool = False,
    tweet: bool = False,
) -> dict:
    """Qiita に記事を公開する。

    Args:
        title: 記事タイトル
        body: Markdown 本文
        tags: タグ名リスト (例: ["Python", "AI", "Claude"])
        private: True で限定公開
        tweet: True で X 連携投稿

    Returns:
        {"ok": bool, "url": str, "id": str, "error": str}
    """
    if not QIITA_TOKEN:
        return {"ok": False, "error": "QIITA_ACCESS_TOKEN 未設定"}

    if not title or not body:
        return {"ok": False, "error": "title と body は必須"}

    if tags is None:
        tags = ["AI", "SYUTAINβ", "BuildInPublic", "個人開発", "非エンジニア"]

    tag_objects = [{"name": t, "versions": []} for t in tags[:5]]  # Qiita は最大 5 タグ

    payload = {
        "title": title[:100],
        "body": body,
        "tags": tag_objects,
        "private": private,
        "tweet": tweet,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{QIITA_API}/items",
                headers=_headers(),
                json=payload,
            )
            if r.status_code in (200, 201):
                data = r.json()
                url = data.get("url", "")
                item_id = data.get("id", "")
                logger.info(f"Qiita 記事公開成功: {url}")
                return {"ok": True, "url": url, "id": item_id, "error": None}
            else:
                err = r.text[:300]
                logger.warning(f"Qiita API {r.status_code}: {err}")
                return {"ok": False, "error": f"HTTP {r.status_code}: {err}"}
    except Exception as e:
        logger.error(f"Qiita 公開失敗: {e}")
        return {"ok": False, "error": str(e)}


async def update_article(item_id: str, title: str = None, body: str = None, tags: list[str] = None) -> dict:
    """既存記事を更新"""
    if not QIITA_TOKEN:
        return {"ok": False, "error": "QIITA_ACCESS_TOKEN 未設定"}

    payload = {}
    if title:
        payload["title"] = title[:100]
    if body:
        payload["body"] = body
    if tags:
        payload["tags"] = [{"name": t, "versions": []} for t in tags[:5]]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.patch(
                f"{QIITA_API}/items/{item_id}",
                headers=_headers(),
                json=payload,
            )
            if r.status_code == 200:
                return {"ok": True, "url": r.json().get("url", ""), "id": item_id}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_my_articles(page: int = 1, per_page: int = 20) -> list[dict]:
    """自分の記事一覧を取得"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{QIITA_API}/authenticated_user/items",
                headers=_headers(),
                params={"page": page, "per_page": per_page},
            )
            if r.status_code == 200:
                return [{"id": a["id"], "title": a["title"], "url": a["url"],
                         "likes": a.get("likes_count", 0), "created": a.get("created_at")}
                        for a in r.json()]
    except Exception as e:
        logger.warning(f"Qiita 一覧取得失敗: {e}")
    return []
