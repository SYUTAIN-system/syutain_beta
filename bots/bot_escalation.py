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

# エスカレーション追跡（メッセージID → 状態）
_pending_escalations: dict[str, dict] = {}


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
        sent = await channel.send(
            msg,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        logger.info(f"Brain-αエスカレーション送信: {original_message[:50]}")

        # エスカレーション追跡に登録
        _pending_escalations[str(sent.id)] = {
            "channel_id": channel.id,
            "original_message": original_message[:200],
            "sent_at": datetime.now(timezone.utc),
            "escalation_msg_id": sent.id,
            "status": "waiting",
        }

        # 段階的チェック（10秒×6回 = 最大60秒）
        for i in range(6):
            await asyncio.sleep(10)
            recent = [m async for m in channel.history(limit=10, after=sent)]
            brain_alpha_replied = any(
                str(m.author.id) == BRAIN_ALPHA_DISCORD_ID for m in recent
            )
            if brain_alpha_replied:
                logger.info("Brain-α応答を検出")
                _pending_escalations.pop(str(sent.id), None)
                return

        # 60秒経過しても応答なし
        await channel.send(
            "Brain-αがまだ応答していません。常駐セッションの状態を確認します。\n"
            "（Brain-αは常時起動設定のため、使用量制限の可能性があります）"
        )
    except Exception as e:
        logger.error(f"Brain-αエスカレーション失敗: {e}")
        try:
            await channel.send(f"Brain-αの呼び出しに失敗しました: {e}")
        except Exception:
            pass


async def on_brain_alpha_response(message):
    """Brain-αがこのチャンネルに返信した時の処理。
    discord_bot.pyのon_messageから呼ばれる。

    - 保留中のエスカレーションを完了にする
    - claude_code_queueのステータスを更新
    - Brain-βがフォローアップ通知を送る
    """
    channel_id = message.channel.id

    # 保留中のエスカレーションをチェック
    completed = []
    for esc_id, esc in _pending_escalations.items():
        if esc["channel_id"] == channel_id and esc["status"] == "waiting":
            esc["status"] = "responded"
            completed.append(esc_id)
            logger.info(f"Brain-αエスカレーション完了: {esc['original_message'][:50]}")

    for esc_id in completed:
        _pending_escalations.pop(esc_id, None)

    # claude_code_queueの最新pendingをprocessingに更新
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """UPDATE claude_code_queue
                   SET status = 'processing', updated_at = NOW()
                   WHERE status = 'pending'
                   AND source_agent = 'brain_beta'
                   ORDER BY created_at DESC
                   LIMIT 1"""
            )
    except Exception as e:
        logger.debug(f"キューステータス更新スキップ: {e}")


async def on_brain_alpha_task_complete(message):
    """Brain-αのタスク完了を検知してキューを更新する。
    Brain-αの返信内容から完了を推定。"""
    content = message.content.lower()
    completion_signals = [
        "完了", "done", "実装完了", "修正完了", "対応完了",
        "デプロイ", "再起動", "コミット",
    ]
    if any(sig in content for sig in completion_signals):
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                await conn.execute(
                    """UPDATE claude_code_queue
                       SET status = 'completed', updated_at = NOW()
                       WHERE status = 'processing'
                       AND source_agent = 'brain_beta'
                       ORDER BY updated_at DESC
                       LIMIT 1"""
                )
            logger.info("Brain-αタスク完了をキューに反映")
        except Exception as e:
            logger.debug(f"完了ステータス更新スキップ: {e}")


async def send_instruction_to_brain_alpha(instruction: str, context: dict = None, priority: str = "normal"):
    """Brain-βからBrain-α(Claude Code)に指示を送る（二重経路）。

    経路1: claude_code_queueテーブルにINSERT → Brain-αがポーリングで取得
    経路2: Discord Webhook → Brain-αのDiscordチャネルに通知
    経路3: Discord Bot → Brain-α(ID:1477009083100958853)にメンション付きメッセージ

    自動修復、エスカレーション、定期指示に使用。
    """
    import json as _json

    # 経路1: claude_code_queueにINSERT（最も確実）
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO claude_code_queue
                   (category, description, priority, source_agent, context_files, status)
                   VALUES ($1, $2, $3, $4, $5, 'pending')""",
                "brain_beta_instruction",
                instruction[:1000],
                priority,
                "brain_beta",
                _json.dumps(context or {}, ensure_ascii=False, default=str),
            )
        logger.info(f"Brain-α指示キュー登録: {instruction[:80]}")
    except Exception as e:
        logger.error(f"Brain-α指示キュー登録失敗: {e}")

    # 経路2: Discord Webhook通知
    try:
        from tools.discord_notify import notify_brain_only
        msg = f"\U0001f916 **Brain-\u03b2 \u2192 Brain-\u03b1 指示** [{priority}]\n"
        msg += f"内容: {instruction[:500]}\n"
        if context:
            msg += f"コンテキスト: ```json\n{_json.dumps(context, ensure_ascii=False, default=str)[:300]}\n```"
        await notify_brain_only(msg, username="Brain-\u03b2 \u2192 Brain-\u03b1")
    except Exception as e:
        logger.warning(f"Brain-α Webhook通知失敗: {e}")

    # 経路3: Discord Bot経由でBrain-αにメンション（Botが起動している場合のみ）
    try:
        from bots.discord_bot import bot, GENERAL_CH
        ch = bot.get_channel(GENERAL_CH)
        if ch:
            import discord
            mention = f"<@{BRAIN_ALPHA_DISCORD_ID}>"
            dm_msg = f"{mention} **Brain-\u03b2\u304b\u3089\u306e\u6307\u793a** [{priority}]\n{instruction[:300]}"
            await ch.send(dm_msg, allowed_mentions=discord.AllowedMentions(users=True))
    except Exception as e:
        logger.debug(f"Discord Bot経由送信スキップ: {e}")


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
