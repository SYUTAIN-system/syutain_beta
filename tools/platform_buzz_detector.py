"""
プラットフォーム別トレンド・バズ検出器

目的: 今話題になっている・バズっているトピックを検知し、
SYUTAINβのSNS投稿にリアルタイムのトレンド要素を織り込む。

収集ソース:
1. Hacker News (news.ycombinator.com) - テック系の国際的な話題
2. Reddit r/programming, r/LocalLLaMA, r/MachineLearning - 英語圏のテック議論
3. GitHub Trending - 急上昇リポジトリ
4. Yahoo Japan リアルタイム検索 - 日本のリアルタイム話題
5. Bluesky Popular (AT Protocol) - Blueskyで反応の多い投稿
6. Zenn/Qiita Trending - 日本の技術記事トレンド

使い方:
    buzz_list = await detect_platform_buzz()
    # buzz_list = [{"source": "hackernews", "title": "...", "score": 450, "url": "..."}, ...]

データ保存先: platform_buzz_trends テーブル（新規）
"""

import os
import json
import logging
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import httpx

logger = logging.getLogger("syutain.platform_buzz")


@dataclass
class BuzzItem:
    """1つのトレンド・バズアイテム"""
    source: str  # "hackernews" / "reddit" / "github" / "yahoo_jp" / "bluesky_popular" / "zenn"
    title: str
    url: str = ""
    score: int = 0  # いいね数/点数/コメント数
    comments: int = 0
    category: str = ""  # "tech" / "ai" / "general" / "japanese"
    language: str = "en"  # "en" / "ja"
    tags: list = field(default_factory=list)
    detected_at: Optional[datetime] = None
    raw_data: dict = field(default_factory=dict)


async def _fetch_hackernews_top(limit: int = 20) -> list[BuzzItem]:
    """Hacker News APIから上位記事を取得"""
    items = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            if resp.status_code != 200:
                return []
            story_ids = resp.json()[:limit]
            # 各ストーリーの詳細を並列取得
            tasks = [client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json") for sid in story_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    continue
                try:
                    data = r.json()
                    if not data or data.get("type") != "story":
                        continue
                    items.append(BuzzItem(
                        source="hackernews",
                        title=data.get("title", ""),
                        url=data.get("url", f"https://news.ycombinator.com/item?id={data.get('id')}"),
                        score=int(data.get("score", 0)),
                        comments=int(data.get("descendants", 0)),
                        category="tech",
                        language="en",
                        detected_at=datetime.now(timezone.utc),
                        raw_data={"hn_id": data.get("id")},
                    ))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"HackerNews取得失敗: {e}")
    return items


async def _fetch_reddit_top(subreddits: list = None, limit: int = 10) -> list[BuzzItem]:
    """Reddit の人気投稿を取得（認証不要のpublic endpoint）"""
    if subreddits is None:
        subreddits = ["programming", "LocalLLaMA", "MachineLearning", "ArtificialInteligence"]
    items = []
    headers = {"User-Agent": "SyutainBot/1.0"}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            for sub in subreddits:
                try:
                    resp = await client.get(f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for child in data.get("data", {}).get("children", []):
                        post = child.get("data", {})
                        items.append(BuzzItem(
                            source=f"reddit_{sub}",
                            title=post.get("title", ""),
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            score=int(post.get("score", 0)),
                            comments=int(post.get("num_comments", 0)),
                            category="tech",
                            language="en",
                            tags=[post.get("link_flair_text", "")] if post.get("link_flair_text") else [],
                            detected_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug(f"Reddit {sub}取得失敗: {e}")
    except Exception as e:
        logger.warning(f"Reddit全体失敗: {e}")
    return items


async def _fetch_github_trending(language: str = "python", since: str = "daily") -> list[BuzzItem]:
    """GitHub Trending を Jina Reader経由で取得"""
    items = []
    try:
        url = f"https://r.jina.ai/https://github.com/trending/{language}?since={since}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers={"User-Agent": "SyutainBot/1.0", "Accept": "text/markdown"})
            if resp.status_code != 200:
                return []
            text = resp.text
            # Markdown内のリポジトリリンクを抽出
            import re
            # パターン: [owner / repo](https://github.com/owner/repo)
            pattern = r'\[\s*([^/\]]+)\s*/\s*([^\]]+?)\s*\]\(https://github\.com/([^/\s)]+/[^/\s)]+?)\)'
            matches = re.findall(pattern, text)
            seen = set()
            for owner, repo, full in matches[:30]:
                repo_name = f"{owner.strip()}/{repo.strip()}"
                if repo_name in seen:
                    continue
                seen.add(repo_name)
                items.append(BuzzItem(
                    source="github_trending",
                    title=repo_name,
                    url=f"https://github.com/{full}",
                    score=0,  # トレンドページには正確なstar数が出ないことが多い
                    category="tech",
                    language="en",
                    tags=[language],
                    detected_at=datetime.now(timezone.utc),
                ))
            return items[:15]
    except Exception as e:
        logger.warning(f"GitHub Trending取得失敗: {e}")
    return items


async def _fetch_hatena_hotentry() -> list[BuzzItem]:
    """はてなブックマーク Hot Entry（RSS、日本の日常的話題）"""
    items = []
    try:
        import html as _html
        import re
        categories = {
            "total": "general",
            "entertainment": "entertainment",
            "game": "game",
            "life": "life",
        }
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "SyutainBot/1.0"}) as client:
            for cat_path, cat_name in categories.items():
                try:
                    url = f"https://b.hatena.ne.jp/hotentry/{cat_path}.rss" if cat_path != "total" else "https://b.hatena.ne.jp/hotentry.rss"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    text = resp.text
                    item_pattern = re.compile(
                        r'<item[^>]*>.*?<title[^>]*>(.*?)</title>.*?<link[^>]*>(.*?)</link>'
                        r'(?:.*?<hatena:bookmarkcount[^>]*>(\d+)</hatena:bookmarkcount>)?',
                        re.DOTALL,
                    )
                    matches = item_pattern.findall(text)
                    for title, link, bookmark_count in matches[:5]:
                        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title).strip()
                        # HTMLエンティティをデコード（&#x6B74; → 歴）
                        title = _html.unescape(title)
                        if not title:
                            continue
                        items.append(BuzzItem(
                            source=f"hatena_{cat_name}",
                            title=title,
                            url=link.strip(),
                            score=int(bookmark_count) if bookmark_count else 0,
                            category=cat_name,
                            language="ja",
                            detected_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug(f"はてな{cat_path}失敗: {e}")
    except Exception as e:
        logger.warning(f"はてなブックマーク取得失敗: {e}")
    return items[:20]


async def _fetch_yahoo_realtime() -> list[BuzzItem]:
    """Yahoo! Japan リアルタイム検索（Jina Reader経由、日本のエンタメ系トレンドに強い）"""
    items = []
    try:
        import re
        url = "https://r.jina.ai/https://search.yahoo.co.jp/realtime/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/markdown",
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            text = resp.text
            seen = set()

            # パターン1: トレンドランキング「N.   [N # キーワード](url)」形式
            trend_pattern = re.compile(r'^\s*\d+\.\s+\[\d+\s*#?\s*([^\]]+?)\]\(https://search\.yahoo\.co\.jp/realtime/search\?p=', re.MULTILINE)
            for m in trend_pattern.finditer(text):
                kw = m.group(1).strip()
                kw = re.sub(r'#\s*', '', kw).strip()
                if len(kw) < 2 or len(kw) > 40 or kw in seen:
                    continue
                if any(skip in kw for skip in ["ログイン", "検索", "ヘルプ", "Yahoo", "もっと見る"]):
                    continue
                seen.add(kw)
                items.append(BuzzItem(
                    source="yahoo_jp_realtime",
                    title=kw,
                    category="entertainment",
                    language="ja",
                    detected_at=datetime.now(timezone.utc),
                ))

            # パターン2: 急上昇ワード「*   [キーワード](url)」形式（realtime内のリンク）
            rising_pattern = re.compile(r'\*\s+\[([^\]]+?)\]\(https://search\.yahoo\.co\.jp/realtime/search\?p=')
            for m in rising_pattern.finditer(text):
                kw = m.group(1).strip()
                kw = re.sub(r'Image\s*\d+:?', '', kw).strip()
                kw = re.sub(r'急上昇', '', kw).strip()
                if len(kw) < 2 or len(kw) > 40 or kw in seen:
                    continue
                if any(skip in kw for skip in ["ログイン", "検索", "ヘルプ", "Yahoo", "もっと見る"]):
                    continue
                seen.add(kw)
                items.append(BuzzItem(
                    source="yahoo_jp_realtime",
                    title=kw,
                    category="entertainment",
                    language="ja",
                    detected_at=datetime.now(timezone.utc),
                ))
                if len(items) >= 25:
                    break
    except Exception as e:
        logger.warning(f"Yahoo Japan realtime失敗: {e}")
    return items[:25]


async def _fetch_togetter_trending() -> list[BuzzItem]:
    """Togetter 人気まとめ（Twitter話題の深掘り、エンタメ・バズ案件に強い）"""
    items = []
    try:
        import re
        import html as _html
        url = "https://r.jina.ai/https://togetter.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/markdown",
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            text = resp.text
            # Togetterの実際のパターン:
            # [### タイトル](https://togetter.com/li/XXX "title") pv数 (数字 数字 数字)
            # または [![Image](url)](togetter_url)[### タイトル](togetter_url "title")
            pattern = re.compile(
                r'\[###\s+([^\]]{10,200}?)\]\(https://togetter\.com/li/(\d+)(?:[^)]*)\)(?:[^\[]*?(\d+)\s*pv)?',
            )
            matches = pattern.findall(text)
            seen = set()
            for title, li_id, pv_str in matches[:25]:
                if li_id in seen:
                    continue
                seen.add(li_id)
                title_clean = _html.unescape(title.strip())
                if len(title_clean) < 10:
                    continue
                pv = 0
                try:
                    pv = int(pv_str) if pv_str else 0
                except Exception:
                    pv = 0
                items.append(BuzzItem(
                    source="togetter_popular",
                    title=title_clean,
                    url=f"https://togetter.com/li/{li_id}",
                    score=pv,  # PV数をスコアとして使用
                    category="entertainment",
                    language="ja",
                    detected_at=datetime.now(timezone.utc),
                ))
    except Exception as e:
        logger.warning(f"Togetter取得失敗: {e}")
    return items[:20]


async def _fetch_hatena_extended() -> list[BuzzItem]:
    """はてなブックマークの追加カテゴリ（政治/社会・IT・知的好奇心・文化芸能）"""
    items = []
    try:
        import html as _html
        import re
        extra_categories = {
            "social": "social",           # 政治と経済
            "it": "it",                    # テクノロジー
            "knowledge": "knowledge",      # 学び
            "fun": "fun",                  # おもしろ
        }
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "SyutainBot/1.0"}) as client:
            for cat_path, cat_name in extra_categories.items():
                try:
                    url = f"https://b.hatena.ne.jp/hotentry/{cat_path}.rss"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    text = resp.text
                    item_pattern = re.compile(
                        r'<item[^>]*>.*?<title[^>]*>(.*?)</title>.*?<link[^>]*>(.*?)</link>'
                        r'(?:.*?<hatena:bookmarkcount[^>]*>(\d+)</hatena:bookmarkcount>)?',
                        re.DOTALL,
                    )
                    matches = item_pattern.findall(text)
                    for title, link, bookmark_count in matches[:4]:
                        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title).strip()
                        title = _html.unescape(title)
                        if not title:
                            continue
                        items.append(BuzzItem(
                            source=f"hatena_{cat_name}",
                            title=title,
                            url=link.strip(),
                            score=int(bookmark_count) if bookmark_count else 0,
                            category=cat_name,
                            language="ja",
                            detected_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug(f"はてな{cat_path}失敗: {e}")
    except Exception as e:
        logger.warning(f"はてな拡張取得失敗: {e}")
    return items[:16]


async def _fetch_reddit_lifestyle(limit: int = 5) -> list[BuzzItem]:
    """島原の親和分野のReddit（映像/VTuber/ドローン/写真/広告/マーケ/メディア/映画/経営/文化/起業）"""
    subreddits = {
        # 映像・撮影系
        "videography": "videography",       # 映像制作
        "VideoEditing": "video_editing",    # 動画編集
        "Filmmakers": "cinema",              # 映画制作
        # VTuber
        "vtubers": "vtuber",                 # VTuber業界
        # 撮影機材系
        "drone": "drone",                    # ドローン
        "photography": "photography",        # 写真
        # 広告・マーケティング
        "advertising": "advertising",        # 広告
        "marketing": "marketing",            # マーケティング
        # メディア・ジャーナリズム
        "Journalism": "media",               # メディア
        # 経営・起業
        "Entrepreneur": "entrepreneur",      # 起業
        "startups": "startup",               # スタートアップ
        "smallbusiness": "business",         # 中小経営
    }
    items = []
    headers = {"User-Agent": "SyutainBot/1.0"}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            for sub, cat in subreddits.items():
                try:
                    resp = await client.get(f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for child in data.get("data", {}).get("children", []):
                        post = child.get("data", {})
                        items.append(BuzzItem(
                            source=f"reddit_{sub}",
                            title=post.get("title", ""),
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            score=int(post.get("score", 0)),
                            comments=int(post.get("num_comments", 0)),
                            category=cat,
                            language="en",
                            detected_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug(f"Reddit {sub}失敗: {e}")
    except Exception as e:
        logger.warning(f"Reddit lifestyle失敗: {e}")
    return items


async def _fetch_zenn_trending() -> list[BuzzItem]:
    """Zenn Trending記事を取得"""
    items = []
    try:
        url = "https://r.jina.ai/https://zenn.dev"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": "SyutainBot/1.0", "Accept": "text/markdown"})
            if resp.status_code != 200:
                return []
            text = resp.text
            # Zennの記事リンクパターン
            import re
            pattern = r'\[([^\]]{5,80})\]\(https://zenn\.dev/([^/\s)]+)/articles/([^\s)]+?)\)'
            matches = re.findall(pattern, text)
            seen = set()
            for title, author, slug in matches[:20]:
                if slug in seen:
                    continue
                seen.add(slug)
                items.append(BuzzItem(
                    source="zenn_trending",
                    title=title.strip(),
                    url=f"https://zenn.dev/{author}/articles/{slug}",
                    category="tech",
                    language="ja",
                    detected_at=datetime.now(timezone.utc),
                    raw_data={"author": author, "slug": slug},
                ))
    except Exception as e:
        logger.warning(f"Zenn取得失敗: {e}")
    return items[:10]


async def _fetch_bluesky_popular() -> list[BuzzItem]:
    """Blueskyの人気投稿（What's Hot feed）を取得"""
    items = []
    try:
        # Bluesky AT Protocol: app.bsky.feed.getFeed (What's Hot)
        handle = os.getenv("BLUESKY_HANDLE", "")
        password = os.getenv("BLUESKY_APP_PASSWORD", "")
        if not handle or not password:
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 認証
            auth_resp = await client.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": password},
            )
            if auth_resp.status_code != 200:
                return []
            access_jwt = auth_resp.json().get("accessJwt", "")
            headers = {"Authorization": f"Bearer {access_jwt}"}

            # What's Hot (discover) feed
            feed_uri = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
            feed_resp = await client.get(
                f"https://bsky.social/xrpc/app.bsky.feed.getFeed?feed={feed_uri}&limit=20",
                headers=headers,
            )
            if feed_resp.status_code != 200:
                return []
            data = feed_resp.json()
            for post_wrap in data.get("feed", []):
                post = post_wrap.get("post", {})
                record = post.get("record", {})
                text = record.get("text", "")[:200]
                if not text:
                    continue
                items.append(BuzzItem(
                    source="bluesky_popular",
                    title=text,
                    url=f"https://bsky.app/profile/{post.get('author', {}).get('handle', '')}/post/{post.get('uri', '').split('/')[-1]}",
                    score=int(post.get("likeCount", 0)),
                    comments=int(post.get("replyCount", 0)),
                    category="general",
                    language="ja" if any(ord(c) > 127 for c in text[:50]) else "en",
                    detected_at=datetime.now(timezone.utc),
                ))
    except Exception as e:
        logger.warning(f"Bluesky Popular取得失敗: {e}")
    return items[:15]


async def detect_platform_buzz() -> list[BuzzItem]:
    """全ソースから現在のトレンド・バズを検出（バランス配分）

    配分方針:
    - テック系: 40% (HN, Reddit LocalLLaMA/ML/programming, GitHub, Zenn)
    - 日本の日常・話題: 30% (はてな, Google Trends JP)
    - 島原の親和分野: 20% (Reddit videography/vtubers/drone/photography/music)
    - その他SNS: 10% (Bluesky Popular)
    """
    logger.info("platform_buzz_detector: 全ソース取得開始（バランス配分）")

    results = await asyncio.gather(
        # テック系（40%）
        _fetch_hackernews_top(limit=12),
        _fetch_reddit_top(limit=6),               # LocalLLaMA/ML/programming/AI
        _fetch_github_trending("python", "daily"),
        _fetch_zenn_trending(),
        # 日本の日常・話題（30%）
        _fetch_hatena_hotentry(),                  # 総合/エンタメ/ゲーム/暮らし
        _fetch_hatena_extended(),                  # 社会/IT/知的好奇心/おもしろ
        _fetch_yahoo_realtime(),                   # Yahoo!リアルタイム（エンタメ・芸能・バズワード）
        _fetch_togetter_trending(),                # Togetter（Twitter話題まとめ）
        # 島原の親和分野（20%）
        _fetch_reddit_lifestyle(limit=5),         # 映像/VTuber/ドローン/写真/音楽
        # その他SNS（10%）
        _fetch_bluesky_popular(),
        return_exceptions=True,
    )

    all_items: list[BuzzItem] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)

    logger.info(f"platform_buzz_detector: 取得完了 合計{len(all_items)}件")

    # カテゴリ別ラベル付け（tech/daily_jp/affinity/sns）
    _affinity_subs = (
        "reddit_videography", "reddit_VideoEditing", "reddit_Filmmakers",
        "reddit_vtubers", "reddit_drone", "reddit_photography",
        "reddit_advertising", "reddit_marketing", "reddit_Journalism",
        "reddit_Entrepreneur", "reddit_startups", "reddit_smallbusiness",
    )
    for item in all_items:
        if item.source in _affinity_subs:
            item.tags = item.tags + ["affinity"]
        elif item.source in ("hackernews", "github_trending", "zenn_trending") or (
            item.source.startswith("reddit_") and item.category == "tech"
        ):
            item.tags = item.tags + ["tech"]
        elif item.source.startswith("hatena_") or item.source == "google_trends_jp":
            item.tags = item.tags + ["daily_jp"]
        elif item.source == "bluesky_popular":
            item.tags = item.tags + ["sns"]

    # スコア順でソート
    all_items.sort(key=lambda x: x.score, reverse=True)
    return all_items


async def save_buzz_to_db(items: list[BuzzItem]) -> int:
    """バズアイテムをDBに保存"""
    from tools.db_pool import get_connection

    saved = 0
    async with get_connection() as conn:
        # テーブルがなければ作成
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS platform_buzz_trends (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                score INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                category TEXT,
                language TEXT,
                tags JSONB,
                raw_data JSONB,
                detected_at TIMESTAMPTZ DEFAULT NOW(),
                used_in_post BOOLEAN DEFAULT FALSE,
                UNIQUE(source, title)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_buzz_detected ON platform_buzz_trends(detected_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_buzz_source ON platform_buzz_trends(source)")

        for item in items:
            try:
                await conn.execute(
                    """INSERT INTO platform_buzz_trends
                    (source, title, url, score, comments, category, language, tags, raw_data, detected_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (source, title) DO UPDATE SET
                        score = EXCLUDED.score,
                        comments = EXCLUDED.comments,
                        detected_at = EXCLUDED.detected_at""",
                    item.source, item.title[:500], item.url, item.score, item.comments,
                    item.category, item.language, json.dumps(item.tags), json.dumps(item.raw_data),
                    item.detected_at or datetime.now(timezone.utc),
                )
                saved += 1
            except Exception as e:
                logger.debug(f"buzz保存失敗: {e}")

    return saved


async def get_recent_buzz_for_prompt(
    hours: int = 6,
    max_items: int = 12,
    language_filter: str = None,
) -> list[dict]:
    """プロンプト注入用に直近のバズを取得（カテゴリバランス配分）

    配分: tech 4件 / daily_jp 4件 / affinity 3件 / sns 1件 = 計12件
    """
    from tools.db_pool import get_connection

    # カテゴリ別ソースリスト
    tech_sources = ("hackernews", "github_trending", "zenn_trending",
                    "reddit_programming", "reddit_LocalLLaMA", "reddit_MachineLearning", "reddit_ArtificialInteligence")
    daily_jp_sources = ("hatena_general", "hatena_entertainment", "hatena_game", "hatena_life",
                        "hatena_social", "hatena_it", "hatena_knowledge", "hatena_fun",
                        "yahoo_jp_realtime", "togetter_top", "togetter_popular")
    affinity_sources = (
        "reddit_videography", "reddit_VideoEditing", "reddit_Filmmakers",
        "reddit_vtubers", "reddit_drone", "reddit_photography",
        "reddit_advertising", "reddit_marketing", "reddit_Journalism",
        "reddit_Entrepreneur", "reddit_startups", "reddit_smallbusiness",
    )

    async with get_connection() as conn:
        async def _fetch_cat(sources: tuple, limit: int) -> list[dict]:
            if not sources:
                return []
            rows = await conn.fetch(
                f"""SELECT source, title, url, score, category, language, detected_at
                FROM platform_buzz_trends
                WHERE source = ANY($1::text[])
                AND detected_at > NOW() - INTERVAL '{hours} hours'
                AND used_in_post = false
                ORDER BY score DESC NULLS LAST, detected_at DESC
                LIMIT $2""",
                list(sources), limit,
            )
            return [dict(r) for r in rows]

        # バランス配分で取得
        tech = await _fetch_cat(tech_sources, 4)
        daily_jp = await _fetch_cat(daily_jp_sources, 4)
        affinity = await _fetch_cat(affinity_sources, 3)
        sns = await _fetch_cat(("bluesky_popular",), 1)

        all_items = tech + daily_jp + affinity + sns
        return all_items[:max_items]


def buzz_to_prompt(buzz_items: list[dict], max_chars: int = 1000) -> str:
    """バズリストをLLMプロンプト用に整形"""
    if not buzz_items:
        return ""

    lines = ["## 今ネット上で話題のトピック（参考素材）"]
    total = len(lines[0])
    for item in buzz_items:
        line = f"- [{item.get('source', '?')}] {item.get('title', '')[:100]}"
        if item.get("score"):
            line += f" (score={item['score']})"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line) + 1

    lines.append("")
    lines.append("**注意**: 上記は参考。無理に使う必要はない。関連性があり、SYUTAINβの視点で語れるものがあれば取り入れてよい。")
    return "\n".join(lines)


async def run_buzz_detection_job():
    """スケジューラから呼ばれる定期実行関数"""
    try:
        items = await detect_platform_buzz()
        saved = await save_buzz_to_db(items)
        logger.info(f"platform_buzz_detector: {len(items)}件取得、{saved}件DB保存")
        return {"total": len(items), "saved": saved}
    except Exception as e:
        logger.error(f"platform_buzz_detector エラー: {e}")
        return {"error": str(e)}
