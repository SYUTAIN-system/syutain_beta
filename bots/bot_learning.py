"""
対話から学んだことをpersona_memoryに蓄積する。

蓄積タイミング: 1時間おきに直近の対話を分析
蓄積する情報: 応答スタイルの好み、判断基準、哲学、禁止事項
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("syutain.bot_learning")


async def extract_learnings_from_recent_chat(hours: int = 1) -> list[dict]:
    """直近N時間の対話から島原の好み・指摘・判断を抽出する"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            messages = await conn.fetch(
                """SELECT author, content, created_at FROM discord_chat_history
                   WHERE created_at > NOW() - $1 * INTERVAL '1 hour'
                   ORDER BY created_at ASC""",
                hours,
            )
        if len(messages) < 2:
            return []  # 対話が少なすぎる

        # 島原のメッセージだけ抽出
        daichi_msgs = [m for m in messages if m["author"] == "daichi"]
        if not daichi_msgs:
            return []

        # Nemotronで分析（コスト0）
        from tools.llm_router import choose_best_model_v6, call_llm

        chat_text = "\n".join(
            f"{'大知さん' if m['author']=='daichi' else 'SYUTAINβ'}: {m['content']}"
            for m in messages[-20:]
        )

        sel = choose_best_model_v6(task_type="analysis", quality="low", budget_sensitive=True)
        result = await call_llm(
            prompt=f"""以下の対話から、島原大知について学べることを抽出してください。
2種類の情報を探してください:

A. 島原大知がどんな人間か（人物理解）:
  - 性格、価値観、考え方、感情、経験、好き嫌い
  - 仕事の進め方、こだわり、悩み
  - 人間関係、対人スタイル
  → category: "daichi_trait"

B. SYUTAINβへの指示・好み:
  - 応答スタイルの好み → category: "conversation"
  - 判断基準（承認/却下の基準など） → category: "approval_pattern"
  - 禁止事項（「〜するな」） → category: "taboo"
  - 哲学・価値観の表明 → category: "philosophy"

抽象的な解釈ではなく、大知さんが実際に言った具体的な内容のみ。
何もなければ空のJSONリスト[]を返してください。

対話:
{chat_text}

JSON形式で出力: [{{"category": "...", "content": "具体的な内容"}}]
JSONのみ出力。説明不要。""",
            system_prompt="島原大知の人物像と指示を抽出するアナリスト。具体的な内容のみ抽出。",
            model_selection=sel,
        )

        text = result.get("text", "[]").strip()
        # JSONパース
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            learnings = json.loads(match.group())
            return [l for l in learnings if isinstance(l, dict) and "content" in l]
        return []

    except Exception as e:
        logger.warning(f"対話分析失敗: {e}")
        return []


async def save_learnings_to_persona_memory(learnings: list[dict]) -> int:
    """抽出した学びをpersona_memoryに保存（重複チェック付き）"""
    if not learnings:
        return 0

    saved = 0
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            for learning in learnings:
                content = learning.get("content", "")
                category = learning.get("category", "conversation")
                if not content or len(content) < 5:
                    continue

                # 重複チェック（テキスト完全一致）
                exists = await conn.fetchval(
                    "SELECT COUNT(*) FROM persona_memory WHERE content = $1",
                    content,
                )
                if exists > 0:
                    continue

                new_id = await conn.fetchval(
                    "INSERT INTO persona_memory (category, content, reasoning) VALUES ($1, $2, $3) RETURNING id",
                    category, content, "Discord対話から自動抽出",
                )
                saved += 1
                logger.info(f"対話学習: [{category}] {content[:50]}")
                # embedding生成
                if new_id:
                    try:
                        from tools.embedding_tools import embed_and_store_persona
                        import asyncio
                        asyncio.create_task(embed_and_store_persona(new_id, content))
                    except Exception:
                        pass

    except Exception as e:
        logger.error(f"対話学習保存失敗: {e}")

    return saved


def detect_immediate_instruction(message: str) -> dict | None:
    """ルールベースで即時反映すべき指示を検出（LLM不要、高速）。
    Returns: {"category": str, "content": str} or None
    """
    import re

    # 禁止指示: 「〜するな」「〜しないで」「〜やめて」
    taboo_patterns = [
        (r"(.{2,30}?)(?:するな|しないで|やめて|やめろ|禁止)", "taboo"),
        (r"(.{2,30}?)(?:は嫌|は嫌い|はダメ|はNG)", "taboo"),
    ]
    for pattern, category in taboo_patterns:
        match = re.search(pattern, message)
        if match:
            return {"category": category, "content": match.group(0).strip()}

    # 好み指示: 「〜して」「〜がいい」「〜にして」
    pref_patterns = [
        (r"(.{2,30}?)(?:して$|してくれ|してほしい|にして)", "conversation"),
        (r"(.{2,30}?)(?:がいい|の方がいい|が好き)", "conversation"),
    ]
    for pattern, category in pref_patterns:
        match = re.search(pattern, message)
        if match:
            return {"category": category, "content": match.group(0).strip()}

    return None


async def run_chat_learning(hours: int = 1) -> dict:
    """対話学習の実行（スケジューラーから呼ばれる）"""
    learnings = await extract_learnings_from_recent_chat(hours)
    if not learnings:
        return {"extracted": 0, "saved": 0}

    saved = await save_learnings_to_persona_memory(learnings)

    if saved > 0:
        try:
            from tools.discord_notify import notify_discord
            summaries = [l["content"][:40] for l in learnings[:3]]
            await notify_discord(f"📚 対話から{saved}件学びました: {', '.join(summaries)}")
        except Exception:
            pass

    return {"extracted": len(learnings), "saved": saved}
