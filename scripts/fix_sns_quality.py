"""
SNSコンテンツ品質修正スクリプト（一回限り実行）
1. persona_memoryにtabooエントリを追加
2. 全tabooエントリのpriority_tierを1に更新
3. posting_queueの問題投稿をrejectする
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from tools.db_pool import get_connection


TABOOS_TO_ADD = [
    "島原大知がコードを書いている/書けると語ること。島原はコードを一行も書けない非エンジニア。「コードを書く」「プログラミングする」「コーディングする」は全て事実と矛盾する。",
    "島原大知が音楽家/作曲家として語ること。SunoAIでの作詞は完全に個人の趣味であり、音楽制作を仕事や専門として語ってはならない。「僕の音楽」「曲を作った」等は禁止。",
    "島原大知の一人称として「私」を使うこと。島原の一人称は「僕」または「自分」。SYUTAINβとしての発信では「私」はSYUTAINβを指す。",
]


async def main():
    async with get_connection() as conn:
        # === Task 1: tabooエントリ追加 ===
        print("=== Task 1: persona_memoryにtabooエントリを追加 ===")
        for taboo in TABOOS_TO_ADD:
            # 重複チェック
            existing = await conn.fetchval(
                "SELECT id FROM persona_memory WHERE category = 'taboo' AND content = $1",
                taboo,
            )
            if existing:
                print(f"  [SKIP] 既存エントリ (id={existing}): {taboo[:50]}...")
                continue

            new_id = await conn.fetchval(
                """INSERT INTO persona_memory (category, content, reasoning, source, priority_tier)
                   VALUES ('taboo', $1, 'SNS品質改善: 事実誤認防止', 'fix_sns_quality.py', 1)
                   RETURNING id""",
                taboo,
            )
            print(f"  [ADD] id={new_id}: {taboo[:60]}...")

        # === Task 1b: 全tabooのpriority_tierを1に更新 ===
        print("\n=== Task 1b: 全tabooエントリのpriority_tier=1に更新 ===")
        updated = await conn.execute(
            "UPDATE persona_memory SET priority_tier = 1 WHERE category = 'taboo' AND priority_tier != 1",
        )
        print(f"  [UPDATE] {updated}")

        # 確認
        taboo_rows = await conn.fetch(
            "SELECT id, content, priority_tier FROM persona_memory WHERE category = 'taboo' ORDER BY id",
        )
        print(f"\n  現在のtabooエントリ数: {len(taboo_rows)}")
        for r in taboo_rows:
            print(f"    id={r['id']} tier={r['priority_tier']}: {(r['content'] or '')[:70]}...")

        # === Task 4: 問題投稿をreject ===
        print("\n=== Task 4: 問題のあるpending投稿をreject ===")

        # まず対象を確認
        problem_rows = await conn.fetch(
            """SELECT id, platform, account, content, scheduled_at
               FROM posting_queue
               WHERE status = 'pending' AND (
                   content LIKE '%コードを書%'
                   OR content LIKE '%プログラミングする%'
                   OR content LIKE '%僕の音楽%'
                   OR content LIKE '%曲を作%'
               )
               ORDER BY id"""
        )
        print(f"  対象投稿数: {len(problem_rows)}")
        for r in problem_rows:
            print(f"    id={r['id']} {r['platform']}/{r['account']} scheduled={r['scheduled_at']}: {(r['content'] or '')[:60]}...")

        if problem_rows:
            result = await conn.execute(
                """UPDATE posting_queue SET status = 'rejected'
                   WHERE status = 'pending' AND (
                       content LIKE '%コードを書%'
                       OR content LIKE '%プログラミングする%'
                       OR content LIKE '%僕の音楽%'
                       OR content LIKE '%曲を作%'
                   )"""
            )
            print(f"  [REJECT] {result}")
        else:
            print("  対象なし（問題投稿はありません）")

        print("\n完了")


if __name__ == "__main__":
    asyncio.run(main())
