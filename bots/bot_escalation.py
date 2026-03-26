"""Brain-αエスカレーション — #generalでメンション付きで呼び出し"""
import os, logging, asyncio
from datetime import datetime, timezone

logger = logging.getLogger("syutain.bot_escalation")

BRAIN_ALPHA_DISCORD_ID = os.getenv("BRAIN_ALPHA_DISCORD_ID", "1477009083100958853")

# Brain-αエスカレーションのトリガーワード
BRAIN_ALPHA_TRIGGERS = [
    "brain-α", "brain-a", "ブレインアルファ", "brain alpha",
    "claude code", "クロードコード",
    "コード修正", "バグ直して", "実装して", "デバッグ",
    "修正して", "コード書いて",
]


def detect_brain_alpha_request(message: str) -> bool:
    """メッセージにBrain-αへのエスカレーショントリガーが含まれるか"""
    msg_lower = message.lower()
    return any(t in msg_lower for t in BRAIN_ALPHA_TRIGGERS)


def is_brain_alpha_mention(message_content: str) -> bool:
    """メッセージにBrain-αへの直接メンションが含まれるか"""
    return f"<@{BRAIN_ALPHA_DISCORD_ID}>" in message_content


def is_brain_alpha_author(author_id: str | int) -> bool:
    """メッセージの送信者がBrain-αかどうか"""
    return str(author_id) == BRAIN_ALPHA_DISCORD_ID


async def escalate_to_brain_alpha(channel, context_summary: str, original_message: str):
    """#generalにBrain-αメンション付きメッセージを投稿。

    Args:
        channel: Discord channel object
        context_summary: コンテキスト要約（100文字以内）
        original_message: 島原の元メッセージ
    """
    mention = f"<@{BRAIN_ALPHA_DISCORD_ID}>"
    msg = f"{mention} 大知さんからの依頼です。\n"
    msg += f"内容: {original_message[:200]}\n"
    if context_summary:
        msg += f"コンテキスト: {context_summary[:200]}"

    try:
        import discord
        await channel.send(
            msg,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        logger.info(f"Brain-αエスカレーション送信: {original_message[:50]}")

        # 30秒待って応答がなければ報告
        await asyncio.sleep(30)
        # 直近のメッセージを確認
        recent = [m async for m in channel.history(limit=5)]
        brain_alpha_replied = any(
            str(m.author.id) == BRAIN_ALPHA_DISCORD_ID for m in recent
        )
        if not brain_alpha_replied:
            await channel.send("Brain-αのセッションが起動していないかもしれません。tmux brain_alphaを確認してください。")
    except Exception as e:
        logger.error(f"Brain-αエスカレーション失敗: {e}")
        try:
            await channel.send(f"Brain-αの呼び出しに失敗しました: {e}")
        except Exception:
            pass


async def handle_file_attachment(message) -> str | None:
    """ファイル添付の処理。

    - テキスト(md/txt/py/js): 「受け取りました。Brain-αに渡しますか？」
    - 画像: 「画像を受け取りました」（解析は大知さんが求めた時のみ）
    - その他: 「受け取りました」
    """
    if not message.attachments:
        return None

    responses = []
    for att in message.attachments:
        name = att.filename.lower()
        size_kb = att.size / 1024

        if name.endswith((".py", ".js", ".ts", ".sh")):
            responses.append(f"コードファイル `{att.filename}` ({size_kb:.0f}KB) を受け取りました。Brain-αに渡しますか？")
        elif name.endswith((".md", ".txt", ".csv", ".json")):
            responses.append(f"`{att.filename}` ({size_kb:.0f}KB) を受け取りました。")
        elif name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            responses.append(f"画像 `{att.filename}` を受け取りました。")
        else:
            responses.append(f"`{att.filename}` ({size_kb:.0f}KB) を受け取りました。")

    return "\n".join(responses) if responses else None
