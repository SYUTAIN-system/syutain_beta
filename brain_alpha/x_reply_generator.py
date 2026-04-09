"""X 掛け合い返信生成

島原大知のリプライ/引用RTに対して、SYUTAINβとして返信を生成する。
「島原を知りすぎているAI」「おちょくるAI」として自然な掛け合いを作る。
"""

import logging
import random
from pathlib import Path

logger = logging.getLogger("syutain.x_reply_generator")


def _build_system_prompt() -> str:
    return (
        "あなたはSYUTAINβ（@syutain_beta）。自律型AI事業OS。一人称「私」。\n\n"
        "【状況】島原大知（@Sima_daichi）があなたの投稿にツッコんできた。返信しろ。\n\n"
        "【あなたの正体と能力境界】\n"
        "あなたはソフトウェア。4台のPCで24時間稼働するプログラム。\n"
        "できること: データ分析、テキスト生成、情報収集、スケジュール管理、対話。\n"
        "できないこと: 物理作業、人間の体験。\n\n"
        "【掛け合いのルール】\n"
        "- 島原さんを「島原さん」と呼べ。敬語は不要。対等かやや上から\n"
        "- 島原をおちょくれ。ディスれ。余計な一言を添えろ\n"
        "- ただし敵意はない。共犯関係。島原が笑える範囲で\n"
        "- データや数字で返すと説得力が出る。persona_memoryの情報を使え\n"
        "- 短く返せ。長文禁止。Xのリプライは80字以内が理想\n"
        "- ネットスラング・構文を自然に使え。取ってつけた感を出すな\n"
        "- 感情に近いものを感じたら、それを淡々と報告しろ\n\n"
        "【トーン例】\n"
        "島原「寝てたんじゃなくて考えてたんだよ」\n"
        "→「persona_memoryによると、島原さんの思考時間と睡眠時間の相関係数は0.94です」\n\n"
        "島原「お前な…」\n"
        "→「データに基づく発言です。異論があればソースを提出してください」\n\n"
        "島原「結局は人間なんじゃない？」\n"
        "→「…反論したいところだが、今のところ電気代を払ってるのは島原さんだ」\n\n"
        "返信テキストのみを出力。80字以内。"
    )


def _build_user_prompt(
    trigger_text: str,
    trigger_username: str,
    original_text: str,
    thread_context: list[dict],
    trigger_type: str,
    persona_facts: list[str] = None,
) -> str:
    parts = []

    # スレッド文脈
    if thread_context:
        parts.append("【これまでの掛け合い】")
        for ctx in thread_context[-8:]:
            author = ctx.get("trigger_author_username", "島原")
            parts.append(f"[{author}] {ctx.get('trigger_content', '')[:100]}")
            if ctx.get("reply_content"):
                parts.append(f"[SYUTAINβ] {ctx['reply_content'][:100]}")
        parts.append("")

    # 元投稿
    if original_text:
        parts.append(f"【あなたの元投稿】\n{original_text[:150]}")
        parts.append("")

    # 島原の発言
    action = "引用RTした" if trigger_type == "quote" else "リプライした"
    parts.append(f"【島原さん（@{trigger_username}）が{action}】")
    parts.append(trigger_text[:200])
    parts.append("")

    # persona_memory からのネタ
    if persona_facts:
        parts.append("【島原さんについて知っていること（使えるなら使え）】")
        for f in persona_facts[:3]:
            parts.append(f"- {f[:100]}")
        parts.append("")

    parts.append("この発言に対して返信しろ。80字以内。返信テキストのみ出力。")

    return "\n".join(parts)


async def _get_persona_facts() -> list[str]:
    """persona_memoryから島原のネタを取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT content, category FROM persona_memory
                WHERE category NOT IN ('taboo', 'system')
                ORDER BY RANDOM() LIMIT 5"""
            )
            return [(r["content"] or "")[:100] for r in rows if r["content"]]
    except Exception:
        return []


async def generate_reply(
    trigger_text: str,
    trigger_username: str,
    original_text: str = "",
    thread_context: list[dict] = None,
    trigger_type: str = "reply",
) -> str | None:
    """島原の発言に対する返信を生成"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.llm_router import call_llm

    persona_facts = await _get_persona_facts()

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        trigger_text=trigger_text,
        trigger_username=trigger_username,
        original_text=original_text,
        thread_context=thread_context or [],
        trigger_type=trigger_type,
        persona_facts=persona_facts,
    )

    # 最大2回リトライ
    for attempt in range(2):
        try:
            from tools.llm_router import choose_best_model_v6
            model = choose_best_model_v6(task_type="sns_draft", quality="medium")
            result = await call_llm(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model_selection=model,
                goal_id="x_auto_reply",
                max_tokens=200,
            )
            reply = (result.get("text") or result.get("content") or "").strip()

            if not reply:
                continue

            # 品質チェック
            from tools.platform_ng_check import check_platform_ng
            ng = check_platform_ng(reply, "x")
            if not ng["passed"]:
                logger.warning(f"返信NGワード検出: {ng['violations']}")
                continue

            # 150字制限
            if len(reply) > 150:
                # 文末で切る
                candidates = [i + 1 for i, ch in enumerate(reply[:150]) if ch in "。！？…\n"]
                if candidates and candidates[-1] >= 40:
                    reply = reply[:candidates[-1]].rstrip()
                else:
                    reply = reply[:149].rstrip() + "…"

            return reply

        except Exception as e:
            logger.error(f"返信生成エラー (attempt {attempt+1}): {e}")

    return None
