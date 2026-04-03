"""
persona_memoryの欠損embeddingをバッチ生成するスクリプト
Jina Embedding API v3を使用（無料枠: 1M tokens/月）

使い方: cd ~/syutain_beta && python3 scripts/backfill_embeddings.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def main():
    from tools.db_pool import get_connection, init_pool, close_pool
    from tools.embedding_tools import get_embedding

    await init_pool(min_size=1, max_size=3)

    # 欠損件数確認
    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM persona_memory WHERE embedding IS NULL ORDER BY id"
        )

    total = len(rows)
    print(f"対象: {total}件のembedding欠損")
    if total == 0:
        print("全件embedding済み。終了。")
        await close_pool()
        return

    success = 0
    failed = 0
    batch_size = 10

    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        print(f"\nバッチ {i // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({len(batch)}件)")

        for row in batch:
            pid = row["id"]
            content = row["content"] or ""
            if len(content) < 5:
                print(f"  ID={pid}: スキップ（content短すぎ: {len(content)}字）")
                failed += 1
                continue

            try:
                embedding = await get_embedding(content[:8000])
                if not embedding:
                    print(f"  ID={pid}: embedding取得失敗（API応答なし）")
                    failed += 1
                    continue

                embedding_str = str(embedding)
                async with get_connection() as conn:
                    await conn.execute(
                        "UPDATE persona_memory SET embedding = $1::vector WHERE id = $2",
                        embedding_str, pid,
                    )
                success += 1
                print(f"  ID={pid}: OK ({content[:30]}...)")
            except Exception as e:
                print(f"  ID={pid}: エラー ({e})")
                failed += 1

        # バッチ間スリープ（rate limit対策）
        if i + batch_size < total:
            await asyncio.sleep(1)

    print(f"\n=== 完了 ===")
    print(f"成功: {success}/{total}件")
    print(f"失敗: {failed}/{total}件")

    # 最終確認
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as total, COUNT(embedding) as has_emb FROM persona_memory"
        )
        print(f"embedding状態: {row['has_emb']}/{row['total']}件")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
