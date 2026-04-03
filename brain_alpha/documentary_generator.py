"""
SYUTAINβ V25 ドキュメンタリー記事自動生成
システムの稼働データから「AIと非エンジニアの挑戦」記事を自動生成する。
"""

import json
import logging
from datetime import datetime, timezone

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm

logger = logging.getLogger("syutain.documentary")


async def generate_documentary_article() -> dict:
    """システムデータからドキュメンタリー記事を生成"""
    try:
        async with get_connection() as conn:
            # データ収集
            data = {}

            # 直近7日のシステム統計
            data["llm_calls"] = await conn.fetchval(
                "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '7 days'"
            ) or 0
            data["llm_cost"] = float(await conn.fetchval(
                "SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '7 days'"
            ) or 0)
            data["sns_posted"] = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='posted' AND posted_at > NOW() - INTERVAL '7 days'"
            ) or 0
            data["tasks_completed"] = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('completed', 'success') AND created_at > NOW() - INTERVAL '7 days'"
            ) or 0
            data["errors"] = await conn.fetchval(
                "SELECT COUNT(*) FROM event_log WHERE severity='error' AND created_at > NOW() - INTERVAL '7 days'"
            ) or 0

            # 直近の判断・エピソード
            episodes = await conn.fetch("""
                SELECT category, reasoning, decision FROM brain_alpha_reasoning
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC LIMIT 3
            """)
            data["episodes"] = [
                {"category": e["category"], "reasoning": (e["reasoning"] or "")[:100]}
                for e in episodes
            ]

            # persona_memoryから価値観
            values = await conn.fetch("""
                SELECT content FROM persona_memory
                WHERE category IN ('philosophy', 'identity')
                ORDER BY created_at DESC LIMIT 5
            """)
            data["values"] = [v["content"][:100] for v in values]

        # LLMで記事生成
        model_info = choose_best_model_v6(task_type="drafting", quality="medium")
        prompt = f"""あなたは島原大知のゴーストライター。以下のシステムデータから、
「コードが書けない人間がAIと挑む事業OS構築」のドキュメンタリー記事を書いてください。

【データ】
- 今週のLLM呼び出し: {data['llm_calls']}回（コスト¥{data['llm_cost']:.0f}）
- SNS投稿: {data['sns_posted']}件
- 完了タスク: {data['tasks_completed']}件
- エラー: {data['errors']}件
- エピソード: {json.dumps(data['episodes'], ensure_ascii=False)[:300]}
- 価値観: {json.dumps(data['values'], ensure_ascii=False)[:200]}

【文体ルール】
- 一人称「僕」、読者に語りかけるトーン
- 具体的な数字を入れる
- 失敗も正直に書く
- AI臭を出さない、自然な日本語
- 3000-5000字

【構成】
1. 今週何が起きたか（具体的エピソード）
2. 何を学んだか
3. 次に何をするか
"""

        result = await call_llm(
            prompt=prompt,
            model=model_info.get("model", "qwen3.5-9b"),
            provider=model_info.get("provider", "local"),
            node=model_info.get("node", "charlie"),
            max_tokens=4000,
        )

        return {
            "status": "success",
            "title": f"SYUTAINβ週報 — {datetime.now().strftime('%m/%d')}",
            "content": result.get("text", ""),
            "data_used": data,
            "model": model_info.get("model"),
        }

    except Exception as e:
        logger.error(f"ドキュメンタリー生成失敗: {e}")
        return {"status": "error", "error": str(e)}
