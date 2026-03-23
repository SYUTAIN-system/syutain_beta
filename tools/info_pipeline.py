"""
SYUTAINβ V25 情報収集パイプライン (Step 16)
設計書 第5章 5.3「自律調査」準拠

Gmail API (80+キーワード) → Tavily Search → Jina Reader → RSS → YouTube
結果をPostgreSQL intel_items テーブルに保存する。
"""

import os
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.info_pipeline")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# 情報収集キーワード（80+個、設計書準拠）
INTEL_KEYWORDS = [
    # AI/LLM
    "GPT-5", "GPT-5.4", "Claude", "Gemini", "DeepSeek", "DeepSeek V4",
    "Qwen", "Qwen3.5", "LLaMA", "Mistral", "Phi-4", "Gemma",
    "OpenAI", "Anthropic", "Google AI", "Meta AI", "Microsoft AI",
    "LLM", "大規模言語モデル", "生成AI", "AI agent", "AIエージェント",
    "MCP protocol", "Model Context Protocol", "A2A protocol",
    "vLLM", "Ollama", "MLX", "GGUF", "量子化", "LoRA", "ファインチューニング",
    "Computer Use", "Tool Use", "Function Calling",
    # 開発/インフラ
    "NATS messaging", "JetStream", "Tailscale",
    "FastAPI", "Next.js", "React", "TypeScript",
    "PostgreSQL", "pgvector", "SQLite", "Litestream",
    # ビジネス/マーケティング
    "Stripe API", "Booth", "note.com", "アフィリエイト",
    "Micro-SaaS", "SaaS", "個人開発", "indie hacker",
    "コンテンツマーケティング", "SEO", "SNSマーケティング",
    "X API", "Twitter API", "Bluesky", "AT Protocol",
    # テック/トレンド
    "ブラウザ自動化", "Playwright", "Puppeteer", "Stagehand",
    "Lightpanda", "CDP", "ヘッドレスブラウザ",
    "暗号通貨", "Bitcoin", "Ethereum", "DeFi",
    "Web3", "ブロックチェーン",
    # 日本市場
    "副業", "フリーランス", "リモートワーク",
    "日本 AI", "AI 規制", "AI 法律",
    "電子書籍", "デジタルコンテンツ",
    # 競合監視
    "AutoGPT", "CrewAI", "LangGraph", "Dify", "n8n",
    "Make", "Zapier", "自動化ツール",
    # セキュリティ
    "AI safety", "AI alignment", "プロンプトインジェクション",
    "API key leak", "データ漏洩",
]

# カテゴリ分類マッピング
CATEGORY_KEYWORDS = {
    "ai_model": ["GPT", "Claude", "Gemini", "DeepSeek", "Qwen", "LLaMA", "Mistral", "Phi", "Gemma", "LLM"],
    "ai_tool": ["MCP", "A2A", "Computer Use", "Tool Use", "Function Calling", "agent"],
    "infrastructure": ["NATS", "JetStream", "Tailscale", "FastAPI", "PostgreSQL", "Docker"],
    "business": ["Stripe", "Booth", "note.com", "SaaS", "アフィリエイト", "収益"],
    "social": ["X API", "Twitter", "Bluesky", "SNS"],
    "browser": ["Playwright", "Stagehand", "Lightpanda", "ブラウザ"],
    "crypto": ["Bitcoin", "Ethereum", "暗号通貨", "DeFi"],
    "security": ["safety", "alignment", "leak", "漏洩"],
    "market_jp": ["副業", "フリーランス", "日本 AI"],
    "competitor": ["AutoGPT", "CrewAI", "LangGraph", "Dify", "n8n"],
}


class InfoPipeline:
    """情報収集パイプライン"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
            except Exception as e:
                logger.error(f"PostgreSQL接続失敗: {e}")
                return None
        return self._pool

    async def close(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"DB接続プール終了エラー: {e}")

    # ===== パイプライン実行 =====

    async def run_full_pipeline(self, keywords: Optional[list] = None) -> dict:
        """全パイプラインを順次実行"""
        kw_list = keywords or INTEL_KEYWORDS[:20]  # デフォルトは上位20キーワード
        results = {"tavily": [], "jina": [], "rss": [], "gmail": [], "youtube": [], "total_saved": 0}

        # 1. Gmail（Google Alerts）
        gmail_results = await self._run_gmail()
        results["gmail"] = gmail_results

        # 2. Tavily検索
        tavily_results = await self._run_tavily(kw_list)
        results["tavily"] = tavily_results

        # 3. Jina Reader（Tavily結果のURLを読み込み）
        urls_to_read = [r.get("url") for r in tavily_results if r.get("url")][:10]
        jina_results = await self._run_jina(urls_to_read)
        results["jina"] = jina_results

        # 4. RSS フィード
        rss_results = await self._run_rss()
        results["rss"] = rss_results

        # 5. YouTube Data API v3
        youtube_results = await self._run_youtube(kw_list[:6])
        results["youtube"] = youtube_results

        # 6. 保存
        all_items = gmail_results + tavily_results + jina_results + rss_results + youtube_results
        saved = await self._save_items(all_items)
        results["total_saved"] = saved

        logger.info(f"情報収集パイプライン完了: {saved}件保存 (Gmail:{len(gmail_results)}, Tavily:{len(tavily_results)}, Jina:{len(jina_results)}, RSS:{len(rss_results)}, YouTube:{len(youtube_results)})")

        # 判断根拠を記録
        # 高スコア上位5件の理由を記録
        high_items = sorted(all_items, key=lambda x: x.get("importance_score", 0), reverse=True)[:5]
        await self._record_trace(
            action="info_scoring",
            reasoning=f"情報収集{saved}件保存。ソース内訳: Gmail={len(gmail_results)}, Tavily={len(tavily_results)}, Jina={len(jina_results)}, RSS={len(rss_results)}, YouTube={len(youtube_results)}",
            confidence=0.7,
            context={
                "total_saved": saved,
                "sources": {"gmail": len(gmail_results), "tavily": len(tavily_results), "jina": len(jina_results), "rss": len(rss_results), "youtube": len(youtube_results)},
                "top_items": [{"title": i.get("title", "")[:80], "score": i.get("importance_score", 0), "category": i.get("category", "")} for i in high_items],
                "scoring_method": "keyword_match: high_priority(+0.15), mid_priority(+0.05), base=0.3",
                "category_method": "keyword_count_max_match",
            },
        )

        return results

    async def _run_gmail(self) -> list:
        """Gmail API経由でGoogle Alertsメールを収集（設計書第11章準拠）"""
        items = []
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import re

            SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
            creds = None
            token_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'token.json')

            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, 'w') as f:
                        f.write(creds.to_json())
                    logger.info("Gmail token refreshed")
                else:
                    logger.warning("Gmail token無効（初回認証が必要）")
                    return items

            service = build('gmail', 'v1', credentials=creds)

            # Google Alertsのメールを検索（直近24時間）
            query = 'from:googlealerts-noreply@google.com newer_than:1d'
            results = service.users().messages().list(
                userId='me', q=query, maxResults=20
            ).execute()
            messages = results.get('messages', [])

            for msg_ref in messages:
                try:
                    msg = service.users().messages().get(
                        userId='me', id=msg_ref['id'], format='full'
                    ).execute()

                    headers = {h['name']: h['value']
                               for h in msg.get('payload', {}).get('headers', [])}
                    subject = headers.get('Subject', '')

                    # Google Alertsの件名からキーワードを抽出
                    # 形式: "Google アラート - キーワード"
                    keyword = subject.replace('Google アラート - ', '').replace('Google Alert - ', '').strip()

                    # メール本文を取得
                    body = ''
                    payload = msg.get('payload', {})
                    if payload.get('body', {}).get('data'):
                        import base64
                        body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
                    elif payload.get('parts'):
                        for part in payload['parts']:
                            if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                                import base64
                                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                                break
                            elif part.get('mimeType') == 'text/html' and part.get('body', {}).get('data'):
                                import base64
                                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')

                    # HTMLタグを除去
                    body_clean = re.sub(r'<[^>]+>', ' ', body)
                    body_clean = re.sub(r'\s+', ' ', body_clean).strip()

                    # URLを抽出
                    urls = re.findall(r'https?://[^\s<>"\']+', body)
                    # Google redirect URLからactual URLを抽出
                    actual_urls = []
                    for u in urls:
                        if 'google.com/url' in u:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
                            if 'url' in parsed:
                                actual_urls.append(parsed['url'][0])
                        elif 'google.com' not in u and 'gstatic' not in u:
                            actual_urls.append(u)

                    # 記事ごとにintel_itemを作成（最大3記事/メール）
                    if actual_urls:
                        for url in actual_urls[:3]:
                            # URLからタイトルを推測（body_cleanから該当部分を抽出）
                            title = keyword
                            items.append({
                                "source": "gmail",
                                "keyword": keyword,
                                "title": f"[Alert] {keyword}",
                                "summary": body_clean[:500],
                                "url": url,
                                "importance_score": self._score_importance({"title": keyword, "content": body_clean}),
                                "category": self._classify_category(keyword + " " + body_clean),
                            })
                    else:
                        items.append({
                            "source": "gmail",
                            "keyword": keyword,
                            "title": f"[Alert] {keyword}",
                            "summary": body_clean[:500],
                            "url": "",
                            "importance_score": self._score_importance({"title": keyword, "content": body_clean}),
                            "category": self._classify_category(keyword + " " + body_clean),
                        })

                except Exception as e:
                    logger.warning(f"Gmailメッセージ処理失敗: {e}")

            logger.info(f"Gmail収集完了: {len(items)}件")

        except ImportError:
            logger.warning("Google API クライアントライブラリ未インストール: Gmail収集スキップ")
        except Exception as e:
            logger.error(f"Gmail収集エラー: {e}")

        return items

    async def _run_tavily(self, keywords: list) -> list:
        """Tavily検索を実行"""
        items = []
        try:
            from tools.tavily_client import TavilyClient
            client = TavilyClient()

            # キーワードを5個ずつバッチ処理
            for i in range(0, len(keywords), 5):
                batch = keywords[i:i + 5]
                query = " OR ".join(batch)
                try:
                    result = await client.search(query, max_results=5)
                    for r in result.get("results", []):
                        items.append({
                            "source": "tavily",
                            "keyword": query,
                            "title": r.get("title", ""),
                            "summary": r.get("content", "")[:500],
                            "url": r.get("url", ""),
                            "importance_score": self._score_importance(r),
                            "category": self._classify_category(r.get("title", "") + r.get("content", "")),
                        })
                except Exception as e:
                    logger.warning(f"Tavily検索失敗 (batch {i}): {e}")

                await asyncio.sleep(1)  # レートリミット配慮
        except Exception as e:
            logger.error(f"Tavily検索パイプラインエラー: {e}")
        return items

    async def _run_jina(self, urls: list) -> list:
        """Jina Readerで記事全文取得"""
        items = []
        try:
            from tools.jina_client import JinaClient
            client = JinaClient()

            for url in urls:
                try:
                    result = await client.read_url(url)
                    if result.get("content"):
                        items.append({
                            "source": "jina",
                            "keyword": "",
                            "title": result.get("title", ""),
                            "summary": result.get("content", "")[:1000],
                            "url": url,
                            "importance_score": 0.5,
                            "category": self._classify_category(result.get("content", "")),
                        })
                except Exception as e:
                    logger.warning(f"Jina読み込み失敗 ({url}): {e}")
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Jinaパイプラインエラー: {e}")
        return items

    async def _run_rss(self) -> list:
        """RSSフィード監視"""
        items = []
        rss_feeds = [
            ("https://blog.openai.com/rss/", "openai_blog"),
            ("https://www.anthropic.com/feed", "anthropic_blog"),
            ("https://blog.google/technology/ai/rss/", "google_ai_blog"),
        ]

        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser未インストール: RSS収集スキップ")
            return items

        for feed_url, source_name in rss_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]:
                    items.append({
                        "source": f"rss:{source_name}",
                        "keyword": "",
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", "")[:500],
                        "url": entry.get("link", ""),
                        "importance_score": 0.6,
                        "category": "ai_model",
                    })
            except Exception as e:
                logger.warning(f"RSSフィード取得失敗 ({source_name}): {e}")
        return items

    async def _run_youtube(self, keywords: list) -> list:
        """YouTube Data API v3で関連動画を検索（設計書第11章準拠）"""
        items = []
        try:
            from googleapiclient.discovery import build

            api_key = os.getenv("YOUTUBE_API_KEY", "")
            if not api_key:
                logger.warning("YOUTUBE_API_KEY未設定: YouTube収集スキップ")
                return items

            youtube = build('youtube', 'v3', developerKey=api_key)

            # キーワードを2-3個ずつ組み合わせて検索（クォータ節約）
            search_queries = []
            for i in range(0, min(len(keywords), 6), 2):
                batch = keywords[i:i + 2]
                search_queries.append(" ".join(batch))

            for query in search_queries:
                try:
                    resp = youtube.search().list(
                        q=query,
                        part='snippet',
                        maxResults=3,
                        type='video',
                        order='date',
                        publishedAfter=(datetime.utcnow().replace(hour=0, minute=0, second=0)
                                       - __import__('datetime').timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    ).execute()

                    for v in resp.get('items', []):
                        snippet = v.get('snippet', {})
                        video_id = v.get('id', {}).get('videoId', '')
                        title = snippet.get('title', '')
                        description = snippet.get('description', '')
                        channel = snippet.get('channelTitle', '')

                        items.append({
                            "source": "youtube",
                            "keyword": query,
                            "title": f"[{channel}] {title}",
                            "summary": description[:500],
                            "url": f"https://youtube.com/watch?v={video_id}" if video_id else "",
                            "importance_score": self._score_importance({"title": title, "content": description}),
                            "category": self._classify_category(title + " " + description),
                        })
                except Exception as e:
                    logger.warning(f"YouTube検索失敗 ({query}): {e}")

                await asyncio.sleep(0.5)  # クォータ配慮

            logger.info(f"YouTube収集完了: {len(items)}件")

        except ImportError:
            logger.warning("Google APIクライアント未インストール: YouTube収集スキップ")
        except Exception as e:
            logger.error(f"YouTube収集エラー: {e}")

        return items

    async def _record_trace(self, action: str = "", reasoning: str = "",
                           confidence: float = None, context: dict = None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO agent_reasoning_trace
                           (agent_name, action, reasoning, confidence, context)
                           VALUES ($1, $2, $3, $4, $5)""",
                        "info_pipeline", action, reasoning,
                        confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                    )
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    # ===== 重要度スコアリング =====

    def _score_importance(self, item: dict) -> float:
        """記事の重要度スコア (0.0-1.0)"""
        score = 0.3  # ベースライン
        text = (item.get("title", "") + " " + item.get("content", "")).lower()

        # 高優先キーワード
        high_priority = ["gpt-5", "deepseek v4", "qwen3.5", "breaking", "release", "launch", "新モデル"]
        for kw in high_priority:
            if kw.lower() in text:
                score += 0.15

        # 中優先キーワード
        mid_priority = ["api", "pricing", "benchmark", "performance", "update"]
        for kw in mid_priority:
            if kw.lower() in text:
                score += 0.05

        return min(1.0, score)

    def _classify_category(self, text: str) -> str:
        """テキストからカテゴリを分類"""
        text_lower = text.lower()
        best_category = "other"
        best_count = 0

        for category, keywords in CATEGORY_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if count > best_count:
                best_count = count
                best_category = category

        return best_category

    # ===== DB保存 =====

    async def _save_items(self, items: list) -> int:
        """intel_itemsテーブルに保存"""
        pool = await self._get_pool()
        if not pool:
            logger.warning("DB接続不可: 情報収集結果を保存できません")
            return 0

        saved = 0
        for item in items:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO intel_items (source, keyword, title, summary, url, importance_score, category)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        item.get("source", ""),
                        item.get("keyword", ""),
                        item.get("title", ""),
                        item.get("summary", ""),
                        item.get("url", ""),
                        item.get("importance_score", 0.0),
                        item.get("category", "other"),
                    )
                    saved += 1
                    # 高重要度（0.7以上）はDiscord通知 + Brain-αハンドオフ
                    if item.get("importance_score", 0.0) >= 0.7:
                        try:
                            from tools.discord_notify import notify_discord
                            await notify_discord(
                                f"📡 重要情報検出\n"
                                f"ソース: {item.get('source', '?')}\n"
                                f"タイトル: {item.get('title', '?')}\n"
                                f"重要度: {item.get('importance_score', 0):.2f}\n"
                                f"カテゴリ: {item.get('category', '?')}\n"
                                f"概要: {(item.get('summary', '') or '')[:150]}"
                            )
                        except Exception:
                            pass
                        try:
                            from brain_alpha.escalation import handoff_to_alpha
                            await handoff_to_alpha(
                                category="info",
                                title=f"重要情報: {item.get('title', '?')[:80]}",
                                detail=f"重要度{item.get('importance_score', 0):.2f} / {item.get('category', '')} / {(item.get('summary', '') or '')[:200]}",
                                source_agent="info_pipeline",
                                context={"source": item.get("source"), "url": item.get("url", ""), "score": item.get("importance_score", 0)},
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"intel_item保存失敗: {e}")

        return saved

    async def get_recent_items(self, limit: int = 20, category: Optional[str] = None) -> list:
        """最近のintel_itemsを取得"""
        pool = await self._get_pool()
        if not pool:
            return []
        try:
            async with pool.acquire() as conn:
                if category:
                    rows = await conn.fetch(
                        "SELECT * FROM intel_items WHERE category = $1 ORDER BY created_at DESC LIMIT $2",
                        category, limit,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM intel_items ORDER BY created_at DESC LIMIT $1",
                        limit,
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"intel_items取得失敗: {e}")
            return []
