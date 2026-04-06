"""Zenn 記事公開 — GitHub 連携経由（git push で自動デプロイ）

Zenn は公式 API がないため、GitHub リポジトリ連携を使う:
  1. articles/{slug}.md に frontmatter 付き Markdown を書く
  2. git add + commit + push
  3. Zenn が自動検出してデプロイ

slug: 12-50 文字の英数字+ハイフン（ファイル名 = 記事の永続 ID）
"""

import os
import re
import secrets
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("syutain.zenn_publisher")

ARTICLES_DIR = Path(__file__).resolve().parent.parent / "articles"


def generate_slug() -> str:
    """Zenn 用のランダム slug を生成（16文字 hex）"""
    return secrets.token_hex(8)


def create_article(
    title: str,
    body: str,
    emoji: str = "🧠",
    article_type: str = "tech",
    topics: list[str] = None,
    published: bool = True,
    slug: str = None,
) -> dict:
    """Zenn 記事を articles/ に作成する。git push は別途行う。

    Args:
        title: 記事タイトル（60字以内推奨）
        body: Markdown 本文
        emoji: アイキャッチ絵文字
        article_type: "tech" or "idea"
        topics: トピック名（最大5個、英小文字）
        published: True で公開、False で下書き
        slug: 記事 slug（省略時自動生成）

    Returns:
        {"ok": bool, "path": str, "slug": str, "error": str}
    """
    if not title or not body:
        return {"ok": False, "error": "title と body は必須"}

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    slug = slug or generate_slug()
    # slug のバリデーション
    slug = re.sub(r'[^a-z0-9-]', '', slug.lower())[:50]
    if len(slug) < 12:
        slug = slug + secrets.token_hex(6)

    if topics is None:
        topics = ["ai", "claude", "python", "buildinpublic", "個人開発"]
    topics = [t.lower() for t in topics[:5]]

    # frontmatter
    frontmatter = (
        f'---\n'
        f'title: "{title[:100]}"\n'
        f'emoji: "{emoji}"\n'
        f'type: "{article_type}"\n'
        f'topics: {topics}\n'
        f'published: {"true" if published else "false"}\n'
        f'---\n\n'
    )

    filepath = ARTICLES_DIR / f"{slug}.md"
    filepath.write_text(frontmatter + body, encoding="utf-8")

    logger.info(f"Zenn 記事作成: {filepath} (published={published})")

    return {
        "ok": True,
        "path": str(filepath),
        "slug": slug,
        "error": None,
    }


async def publish_and_push(
    title: str,
    body: str,
    emoji: str = "🧠",
    topics: list[str] = None,
    published: bool = True,
) -> dict:
    """記事を作成して git add + commit + push まで一気にやる。
    push 後に Zenn が自動デプロイする。"""
    import asyncio

    result = create_article(title, body, emoji=emoji, topics=topics, published=published)
    if not result["ok"]:
        return result

    filepath = result["path"]
    slug = result["slug"]

    try:
        # git add
        proc = await asyncio.create_subprocess_exec(
            "git", "add", filepath,
            cwd=str(ARTICLES_DIR.parent),
        )
        await proc.wait()

        # git commit
        commit_msg = f"Zenn: {title[:60]}"
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", commit_msg,
            cwd=str(ARTICLES_DIR.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        # git push
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "origin", "main",
            cwd=str(ARTICLES_DIR.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            url = f"https://zenn.dev/syutain/articles/{slug}"
            logger.info(f"Zenn 記事公開: {url}")
            return {
                "ok": True,
                "path": filepath,
                "slug": slug,
                "url": url,
                "error": None,
            }
        else:
            err = stderr.decode()[:300]
            logger.warning(f"Zenn git push 失敗: {err}")
            return {"ok": False, "error": f"git push failed: {err}", "path": filepath, "slug": slug}

    except Exception as e:
        logger.error(f"Zenn publish_and_push 失敗: {e}")
        return {"ok": False, "error": str(e), "path": filepath, "slug": slug}


def list_articles() -> list[dict]:
    """articles/ 内の記事一覧を返す"""
    if not ARTICLES_DIR.exists():
        return []
    results = []
    for f in sorted(ARTICLES_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        title = ""
        published = False
        for line in content.split("\n"):
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')
            if line.startswith("published:"):
                published = "true" in line.lower()
        results.append({
            "slug": f.stem,
            "title": title,
            "published": published,
            "path": str(f),
        })
    return results
