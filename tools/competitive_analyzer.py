"""
SYUTAINβ V25 競合商品自動分析パイプライン

BRAVOのPlaywrightでBooth/noteの競合商品を定期スクレイピングし、
intel_itemsに保存してProposalEngineの提案精度を向上させる。
"""

import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.competitive_analyzer")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# スクレイピング対象キーワード
BOOTH_KEYWORDS = ["AI", "非エンジニア", "テンプレート", "自動化"]
NOTE_KEYWORDS = ["AI活用", "個人開発", "非エンジニア", "自動化"]


async def analyze_booth(limit: int = 20) -> list:
    """Booth売れ筋商品の分析（Jina経由 — headless blocked対策）"""
    results = []

    try:
        from tools.jina_client import JinaClient
        jina = JinaClient()

        for keyword in BOOTH_KEYWORDS[:2]:
            try:
                url = f"https://booth.pm/ja/search/{keyword}?sort=wish_list"
                content = await jina.extract(url)
                if not content:
                    continue

                # LLMで構造化
                from tools.llm_router import call_llm, choose_best_model_v6
                model_sel = choose_best_model_v6(
                    task_type="data_extraction", quality="low", budget_sensitive=True
                )
                result = await call_llm(
                    prompt=f"""以下のBooth検索結果から商品情報を抽出してJSON配列で出力してください。
最大5件。

{content[:3000]}

出力形式:
[{{"title": "商品名", "price": 価格, "category": "カテゴリ", "summary": "説明要約（50文字）"}}]""",
                    system_prompt="データ抽出エンジン。JSONのみ出力。",
                    model_selection=model_sel,
                )
                text = result.get("text", "").strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                try:
                    items = json.loads(text)
                    if isinstance(items, list):
                        for item in items[:5]:
                            results.append({
                                "source": "booth",
                                "keyword": keyword,
                                "title": item.get("title", ""),
                                "price": item.get("price"),
                                "category": item.get("category", ""),
                                "summary": item.get("summary", ""),
                            })
                except json.JSONDecodeError:
                    pass
            except Exception as e:
                logger.warning(f"Booth分析エラー ({keyword}): {e}")

    except Exception as e:
        logger.error(f"Booth分析全体エラー: {e}")

    return results


async def analyze_note(limit: int = 20) -> list:
    """note人気記事の分析（Jina経由）"""
    results = []

    try:
        from tools.jina_client import JinaClient
        jina = JinaClient()

        for keyword in NOTE_KEYWORDS[:2]:
            try:
                url = f"https://note.com/search?q={keyword}&sort=like"
                content = await jina.extract(url)
                if not content:
                    continue

                from tools.llm_router import call_llm, choose_best_model_v6
                model_sel = choose_best_model_v6(
                    task_type="data_extraction", quality="low", budget_sensitive=True
                )
                result = await call_llm(
                    prompt=f"""以下のnote検索結果から記事情報を抽出してJSON配列で出力してください。
最大5件。

{content[:3000]}

出力形式:
[{{"title": "記事タイトル", "author": "著者", "likes": スキ数, "summary": "内容要約（50文字）"}}]""",
                    system_prompt="データ抽出エンジン。JSONのみ出力。",
                    model_selection=model_sel,
                )
                text = result.get("text", "").strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                try:
                    items = json.loads(text)
                    if isinstance(items, list):
                        for item in items[:5]:
                            results.append({
                                "source": "note",
                                "keyword": keyword,
                                "title": item.get("title", ""),
                                "author": item.get("author", ""),
                                "likes": item.get("likes"),
                                "summary": item.get("summary", ""),
                            })
                except json.JSONDecodeError:
                    pass
            except Exception as e:
                logger.warning(f"note分析エラー ({keyword}): {e}")

    except Exception as e:
        logger.error(f"note分析全体エラー: {e}")

    return results


async def run_competitive_analysis() -> dict:
    """競合分析を実行し、intel_itemsに保存"""
    logger.info("競合分析開始")

    booth_results = await analyze_booth()
    note_results = await analyze_note()

    all_results = booth_results + note_results
    saved = 0

    if all_results:
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                for item in all_results:
                    await conn.execute(
                        """INSERT INTO intel_items (source, keyword, title, summary, metadata)
                        VALUES ($1, $2, $3, $4, $5)""",
                        f"competitive_analysis_{item['source']}",
                        item.get("keyword", ""),
                        item.get("title", "")[:200],
                        item.get("summary", "")[:500],
                        json.dumps(item, ensure_ascii=False),
                    )
                    saved += 1
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"競合分析DB保存エラー: {e}")

    # イベント記録
    try:
        from tools.event_logger import log_event
        await log_event("competitive.analysis_completed", "intel", {
            "booth_count": len(booth_results),
            "note_count": len(note_results),
            "saved_count": saved,
        })
    except Exception:
        pass

    logger.info(f"競合分析完了: Booth {len(booth_results)}件, note {len(note_results)}件, 保存 {saved}件")
    return {
        "booth": booth_results,
        "note": note_results,
        "total": len(all_results),
        "saved": saved,
    }
