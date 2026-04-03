#!/usr/bin/env python3
"""
SYUTAINβ 過去資産一括 persona_memory 投入スクリプト

ソース:
a. chat_messages の島原の発言 → persona_memory
b. proposal_history の採用/却下パターン → persona_memory(category='judgment')
c. strategy/*.md の内容 → persona_memory(category='philosophy')
d. CONTENT_STRATEGY.md の Brand Voice → persona_memory(category='preference')

usage: python3 scripts/import_persona_assets.py
"""

import asyncio
import json
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import_persona")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

BATCH_SOURCE = "batch_import"


async def get_conn():
    return await asyncpg.connect(DATABASE_URL)


async def import_chat_messages(conn):
    """a. chat_messages の島原の発言を抽出 → persona_memory"""
    logger.info("=== chat_messages からの抽出開始 ===")

    rows = await conn.fetch(
        "SELECT content, metadata, session_id, created_at FROM chat_messages WHERE role = 'user' ORDER BY created_at"
    )
    logger.info(f"  対象メッセージ: {len(rows)}件")

    imported = 0
    for row in rows:
        content = row["content"]
        if not content or len(content) < 10:
            continue

        # カテゴリ判定
        lower = content.lower()
        if any(kw in lower for kw in ["嫌い", "好き", "好む", "こだわ", "大事", "信じ", "思う", "考え", "哲学"]):
            category = "philosophy"
        elif any(kw in lower for kw in ["承認", "却下", "ダメ", "いいよ", "判断", "決め"]):
            category = "judgment"
        elif any(kw in lower for kw in ["書き方", "スタイル", "表現", "トーン", "雰囲気"]):
            category = "preference"
        else:
            category = "conversation"

        # 重複チェック
        exists = await conn.fetchval(
            "SELECT 1 FROM persona_memory WHERE content = $1 AND source = $2 LIMIT 1",
            content[:500], BATCH_SOURCE,
        )
        if exists:
            continue

        await conn.execute(
            """INSERT INTO persona_memory (category, content, context, source, session_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)""",
            category,
            content[:500],
            f"chat:{row['session_id']}",
            BATCH_SOURCE,
            row["session_id"],
            row["created_at"],
        )
        imported += 1

    logger.info(f"  chat_messages → persona_memory: {imported}件投入")
    return imported


async def import_proposal_patterns(conn):
    """b. proposal_history の採用/却下パターン → persona_memory(category='judgment')"""
    logger.info("=== proposal_history からの抽出開始 ===")

    rows = await conn.fetch(
        """SELECT proposal_id, title, target_icp, primary_channel, adopted,
                  proposal_data, created_at
        FROM proposal_history ORDER BY created_at"""
    )
    logger.info(f"  対象提案: {len(rows)}件")

    imported = 0
    for row in rows:
        if row["adopted"] is None:
            continue  # 未判断

        action = "承認" if row["adopted"] else "却下"
        content = f"提案「{row['title']}」を{action}。ICP: {row['target_icp']}, チャネル: {row['primary_channel']}"

        exists = await conn.fetchval(
            "SELECT 1 FROM persona_memory WHERE content = $1 AND source = $2 LIMIT 1",
            content, BATCH_SOURCE,
        )
        if exists:
            continue

        await conn.execute(
            """INSERT INTO persona_memory (category, content, context, reasoning, source, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)""",
            "judgment",
            content,
            f"proposal:{row['proposal_id']}",
            f"{action}判断",
            BATCH_SOURCE,
            row["created_at"],
        )
        imported += 1

    logger.info(f"  proposal_history → persona_memory: {imported}件投入")
    return imported


async def import_strategy_files(conn):
    """c. strategy/*.md → persona_memory(category='philosophy')"""
    logger.info("=== strategy/ からの抽出開始 ===")

    strategy_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategy")
    imported = 0

    for filename in os.listdir(strategy_dir):
        if not filename.endswith(".md"):
            continue

        filepath = os.path.join(strategy_dir, filename)
        with open(filepath, "r") as f:
            text = f.read()

        # セクション分割（## 見出しごと）
        sections = []
        current_section = ""
        current_title = filename
        for line in text.split("\n"):
            if line.startswith("## "):
                if current_section.strip():
                    sections.append((current_title, current_section.strip()))
                current_title = line[3:].strip()
                current_section = ""
            else:
                current_section += line + "\n"
        if current_section.strip():
            sections.append((current_title, current_section.strip()))

        for title, content in sections:
            if len(content) < 20:
                continue

            # カテゴリ判定
            lower_title = title.lower()
            if any(kw in lower_title for kw in ["禁止", "ng", "ルール"]):
                category = "preference"
            elif any(kw in lower_title for kw in ["icp", "ターゲット", "誰に"]):
                category = "philosophy"
            elif any(kw in lower_title for kw in ["voice", "トーン", "書き方"]):
                category = "preference"
            else:
                category = "philosophy"

            exists = await conn.fetchval(
                "SELECT 1 FROM persona_memory WHERE context = $1 AND source = $2 LIMIT 1",
                f"strategy:{filename}:{title}", BATCH_SOURCE,
            )
            if exists:
                continue

            await conn.execute(
                """INSERT INTO persona_memory (category, content, context, source)
                VALUES ($1, $2, $3, $4)""",
                category,
                content[:500],
                f"strategy:{filename}:{title}",
                BATCH_SOURCE,
            )
            imported += 1

    logger.info(f"  strategy/ → persona_memory: {imported}件投入")
    return imported


async def import_strategy_identity(conn):
    """d. strategy_identity.md → persona_memory(category='philosophy'/'preference')"""
    logger.info("=== strategy_identity.md からの抽出開始 ===")

    filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "prompts", "strategy_identity.md")
    if not os.path.exists(filepath):
        logger.warning("  strategy_identity.md が見つかりません")
        return 0

    with open(filepath, "r") as f:
        text = f.read()

    # セクション分割
    sections = []
    current_section = ""
    current_title = "概要"
    for line in text.split("\n"):
        if line.startswith("## "):
            if current_section.strip():
                sections.append((current_title, current_section.strip()))
            current_title = line[3:].strip()
            current_section = ""
        else:
            current_section += line + "\n"
    if current_section.strip():
        sections.append((current_title, current_section.strip()))

    imported = 0
    for title, content in sections:
        if len(content) < 20:
            continue

        lower = title.lower()
        if "禁止" in lower or "ng" in lower:
            category = "preference"
        elif "商品" in lower or "ポートフォリオ" in lower:
            category = "preference"
        else:
            category = "philosophy"

        exists = await conn.fetchval(
            "SELECT 1 FROM persona_memory WHERE context = $1 AND source = $2 LIMIT 1",
            f"identity:{title}", BATCH_SOURCE,
        )
        if exists:
            continue

        await conn.execute(
            """INSERT INTO persona_memory (category, content, context, source)
            VALUES ($1, $2, $3, $4)""",
            category,
            content[:500],
            f"identity:{title}",
            BATCH_SOURCE,
        )
        imported += 1

    logger.info(f"  strategy_identity.md → persona_memory: {imported}件投入")
    return imported


async def main():
    conn = await get_conn()

    try:
        # 投入前の件数
        before = await conn.fetchval("SELECT count(*) FROM persona_memory")
        logger.info(f"投入前 persona_memory: {before}件")

        total = 0
        total += await import_chat_messages(conn)
        total += await import_proposal_patterns(conn)
        total += await import_strategy_files(conn)
        total += await import_strategy_identity(conn)

        # 投入後の件数
        after = await conn.fetchval("SELECT count(*) FROM persona_memory")
        logger.info(f"\n=== 完了 ===")
        logger.info(f"  新規投入: {total}件")
        logger.info(f"  総件数: {before}件 → {after}件")

        # カテゴリ別内訳
        categories = await conn.fetch(
            "SELECT category, count(*), count(*) FILTER (WHERE source = $1) as batch "
            "FROM persona_memory GROUP BY category ORDER BY count DESC",
            BATCH_SOURCE,
        )
        for row in categories:
            logger.info(f"  {row['category']}: {row['count']}件 (batch: {row['batch']}件)")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
