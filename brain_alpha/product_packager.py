"""
SYUTAINβ 商品パッケージング — publish_ready記事をnote有料記事として整形

LLM不使用（コスト¥0）。キーワードマッチでタグ・カテゴリ自動抽出。
"""

import json
import logging
import re
from datetime import datetime, timezone

from tools.db_pool import get_connection
from tools.discord_notify import notify_discord

logger = logging.getLogger("syutain.product_packager")

# タグ抽出用キーワードマッピング
TAG_KEYWORDS = {
    "AI": ["AI", "人工知能", "LLM", "ChatGPT", "Claude", "GPT", "機械学習", "自動化"],
    "VTuber": ["VTuber", "Vtuber", "バーチャル", "配信", "Live2D"],
    "映像制作": ["映像", "動画", "編集", "VFX", "カラーグレーディング", "撮影", "ドローン"],
    "事業運営": ["事業", "経営", "ビジネス", "マネタイズ", "収益", "売上"],
    "プログラミング": ["Python", "JavaScript", "コード", "プログラミング", "開発", "API"],
    "マーケティング": ["マーケティング", "SNS", "集客", "フォロワー", "ブランディング"],
    "失敗談": ["失敗", "挫折", "やらかし", "反省", "学び"],
    "ツール紹介": ["ツール", "アプリ", "サービス", "おすすめ", "レビュー"],
    "働き方": ["フリーランス", "副業", "働き方", "リモート", "効率化"],
    "クリエイター": ["クリエイター", "制作", "作品", "ポートフォリオ"],
}

CATEGORY_KEYWORDS = {
    "テクノロジー": ["AI", "LLM", "API", "Python", "プログラミング", "自動化", "技術"],
    "ビジネス": ["事業", "経営", "収益", "マネタイズ", "ビジネス", "売上"],
    "クリエイティブ": ["映像", "VTuber", "制作", "クリエイター", "デザイン"],
    "ライフスタイル": ["働き方", "フリーランス", "日常", "暮らし"],
    "エンタメ": ["VTuber", "配信", "ゲーム", "エンタメ"],
}

FREE_PREVIEW_LENGTH = 500  # 無料公開部分の文字数


def _extract_tags(text: str) -> list[str]:
    """テキストからキーワードマッチでタグ抽出"""
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                tags.append(tag)
                break
    return tags[:5]


def _extract_category(text: str) -> str:
    """テキストからカテゴリを推定"""
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text.lower())
        if score > 0:
            scores[cat] = score
    if scores:
        return max(scores, key=scores.get)
    return "テクノロジー"


def _split_content(body: str) -> tuple[str, str]:
    """記事を無料プレビュー部分と有料部分に分割"""
    if len(body) <= FREE_PREVIEW_LENGTH:
        return body, ""

    # 文の区切りで分割（500文字付近）
    split_pos = FREE_PREVIEW_LENGTH
    for sep in ["。\n", "。", "\n\n", "\n"]:
        pos = body.rfind(sep, 0, FREE_PREVIEW_LENGTH + 100)
        if pos > FREE_PREVIEW_LENGTH * 0.6:
            split_pos = pos + len(sep)
            break

    preview = body[:split_pos].rstrip()
    full = body[split_pos:].lstrip()

    # プレビュー末尾に有料誘導
    preview += "\n\n---\n\n**ここから先は有料です。** 全文を読むには購入してください。"

    return preview, full


async def package_publish_ready_articles() -> dict:
    """publish_readyの記事をproduct_packagesに変換"""
    results = {"packaged": 0, "skipped": 0, "errors": []}

    try:
        async with get_connection() as conn:
            # product_packagesテーブルがなければ作成
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS product_packages (
                    id SERIAL PRIMARY KEY,
                    platform VARCHAR(50) NOT NULL DEFAULT 'note',
                    source_review_id INTEGER,
                    title TEXT NOT NULL,
                    body_preview TEXT,
                    body_full TEXT,
                    price_jpy INTEGER NOT NULL DEFAULT 500,
                    tags JSONB DEFAULT '[]',
                    category VARCHAR(100),
                    status VARCHAR(50) DEFAULT 'ready',
                    approved_at TIMESTAMPTZ,
                    published_at TIMESTAMPTZ,
                    publish_url TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # publish_readyかつ未パッケージの記事を取得
            reviews = await conn.fetch("""
                SELECT r.id, r.article_title, r.filepath, r.stage2_pricing,
                       r.stage2_score, r.stage2_verdict
                FROM note_quality_reviews r
                WHERE r.stage2_verdict = 'publish_ready'
                AND NOT EXISTS (
                    SELECT 1 FROM product_packages p WHERE p.source_review_id = r.id
                )
                ORDER BY r.stage2_score DESC
                LIMIT 5
            """)

            if not reviews:
                logger.info("パッケージ対象のpublish_ready記事なし")
                return results

            for review in reviews:
                try:
                    # 記事本文を読み込み
                    filepath = review["filepath"]
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            body = f.read()
                    except FileNotFoundError:
                        logger.warning(f"記事ファイル未検出: {filepath}")
                        results["skipped"] += 1
                        continue

                    title = review["article_title"] or filepath.split("/")[-1].replace(".md", "")

                    # 価格設定（stage2_pricingを使用、なければ¥500）
                    pricing = review["stage2_pricing"]
                    price = 500
                    if pricing:
                        if isinstance(pricing, (int, float)):
                            price = int(pricing)
                        elif isinstance(pricing, str):
                            price_match = re.search(r"(\d+)", pricing)
                            if price_match:
                                price = int(price_match.group(1))

                    # タグ・カテゴリ抽出（LLM不使用）
                    tags = _extract_tags(title + " " + body[:2000])
                    category = _extract_category(title + " " + body[:2000])

                    # コンテンツ分割
                    preview, full_part = _split_content(body)

                    # DB保存
                    pkg_id = await conn.fetchval("""
                        INSERT INTO product_packages
                            (platform, source_review_id, title, body_preview, body_full,
                             price_jpy, tags, category, status)
                        VALUES ('note', $1, $2, $3, $4, $5, $6, $7, 'ready')
                        RETURNING id
                    """,
                        review["id"], title, preview, full_part,
                        price, json.dumps(tags, ensure_ascii=False), category,
                    )

                    # Discord通知
                    await notify_discord(
                        f"📦 記事『{title}』公開準備完了。推奨¥{price}。`!承認 pkg-{pkg_id}`で承認"
                    )

                    results["packaged"] += 1
                    logger.info(f"パッケージ完了: {title} (¥{price}, tags={tags})")

                except Exception as e:
                    logger.error(f"記事パッケージ失敗: {e}")
                    results["errors"].append(str(e))

    except Exception as e:
        logger.error(f"product_packager全体エラー: {e}")
        results["errors"].append(str(e))

    # イベント記録
    if results["packaged"] > 0:
        try:
            from tools.event_logger import log_event
            await log_event("product.packaged", "commerce", {
                "packaged": results["packaged"],
                "skipped": results["skipped"],
            })
        except Exception:
            pass

    return results


async def get_pending_packages() -> list[dict]:
    """承認待ちパッケージ一覧"""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, title, price_jpy, tags, category, status, created_at
                FROM product_packages
                WHERE status = 'ready'
                ORDER BY created_at DESC LIMIT 20
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"パッケージ一覧取得失敗: {e}")
        return []


async def approve_package(pkg_id: int) -> dict:
    """パッケージを承認"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "UPDATE product_packages SET status = 'approved', approved_at = NOW() WHERE id = $1 RETURNING id, title, price_jpy",
                pkg_id,
            )
            if row:
                await notify_discord(f"✅ 記事『{row['title']}』(¥{row['price_jpy']}) 承認済み。公開待ちキューに追加。")
                return {"status": "approved", "id": pkg_id, "title": row["title"]}
            return {"status": "not_found", "id": pkg_id}
    except Exception as e:
        logger.error(f"パッケージ承認失敗: {e}")
        return {"status": "error", "error": str(e)}


async def reject_package(pkg_id: int, reason: str = "") -> dict:
    """パッケージを却下"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "UPDATE product_packages SET status = 'rejected' WHERE id = $1 RETURNING id, title",
                pkg_id,
            )
            if row:
                await notify_discord(f"❌ 記事『{row['title']}』却下。理由: {reason or '不明'}")
                return {"status": "rejected", "id": pkg_id}
            return {"status": "not_found", "id": pkg_id}
    except Exception as e:
        logger.error(f"パッケージ却下失敗: {e}")
        return {"status": "error", "error": str(e)}


async def preview_package(pkg_id: int) -> dict:
    """パッケージプレビュー"""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM product_packages WHERE id = $1", pkg_id
            )
            if row:
                return dict(row)
            return {"error": "not_found"}
    except Exception as e:
        return {"error": str(e)}
