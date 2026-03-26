"""SYUTAINβ Discord Bot — 自然言語対話（改善版）"""
import os, sys, asyncio, logging
from pathlib import Path
from datetime import time as dtime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BOT] %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("syutain.discord_bot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GENERAL_CH = int(os.getenv("DISCORD_GENERAL_CHANNEL_ID", "0"))
BRAIN_ALPHA_DISCORD_ID = os.getenv("BRAIN_ALPHA_DISCORD_ID", "1477009083100958853")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=False),
)

@bot.event
async def on_ready():
    logger.info(f"Bot起動: {bot.user} (servers: {len(bot.guilds)})")
    try:
        from tools.db_pool import init_pool
        await init_pool(min_size=1, max_size=5)
    except Exception as e:
        logger.error(f"DB pool初期化失敗: {e}")
    if not morning_report.is_running():
        morning_report.start()
    if not night_summary.is_running():
        night_summary.start()
    if not session_cleanup.is_running():
        session_cleanup.start()

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author == bot.user:
        return

    # Brain-αへのメンションが含まれている場合、Brain-βは無反応
    if f"<@{BRAIN_ALPHA_DISCORD_ID}>" in message.content:
        return

    # Brain-αのメッセージにも反応しない（ループ防止）
    if str(message.author.id) == BRAIN_ALPHA_DISCORD_ID:
        return

    # Brain-αへのリプライの場合、Brain-βは無反応（Brain-αとの会話に割り込まない）
    if message.reference and message.reference.resolved:
        if str(message.reference.resolved.author.id) == BRAIN_ALPHA_DISCORD_ID:
            return

    # 指定チャンネル or DM のみ
    if message.guild and message.channel.id != GENERAL_CH:
        return

    from bots.bot_memory import save_message, get_recent_history
    from bots.bot_conversation import generate_response, generate_followup
    from bots.bot_actions import process_actions
    from bots.bot_context import session_manager, detect_context_request, get_previous_session_context
    from bots.bot_proactive import proactive, detect_silence_request
    from bots.bot_self_monitor import quality_monitor
    from bots.bot_escalation import (
        detect_brain_alpha_request, escalate_to_brain_alpha, handle_file_attachment,
    )
    from bots.bot_learning import detect_immediate_instruction, save_learnings_to_persona_memory

    channel_id = str(message.channel.id)
    user_msg = message.content

    # 島原のメッセージを記録
    proactive.on_daichi_message()
    await save_message(channel_id, "daichi", user_msg)

    # セッションコンテキスト取得
    ctx = session_manager.get_or_create(channel_id)
    ctx.touch()

    # サイレンスリクエスト検出
    if detect_silence_request(user_msg):
        proactive.on_silence_request()
        await message.reply("了解です。また話しかけてください。", mention_author=False)
        await save_message(channel_id, "syutain_beta", "了解です。また話しかけてください。")
        return

    # 否定シグナル検出（自己モニタリング）
    neg = quality_monitor.detect_negative_signal(user_msg)
    if neg:
        quality_monitor.record_signal("negative", user_msg[:80])

    # 肯定シグナル検出
    pos = quality_monitor.detect_positive_signal(user_msg)
    if pos:
        quality_monitor.record_signal("positive", user_msg[:80])

    # 即時学習指示の検出
    immediate = detect_immediate_instruction(user_msg)
    if immediate:
        asyncio.ensure_future(save_learnings_to_persona_memory([immediate]))

    # ファイル添付処理
    if message.attachments:
        file_response = await handle_file_attachment(message)
        if file_response:
            # ファイルについてのコメント + 通常応答も生成
            extra_context = f"\n【添付ファイル】{file_response}"
        else:
            extra_context = ""
    else:
        extra_context = ""

    # Brain-αエスカレーション判定
    if detect_brain_alpha_request(user_msg):
        await message.reply("これはBrain-αの管轄ですね。呼びます。", mention_author=False)
        await escalate_to_brain_alpha(message.channel, "", user_msg)
        await save_message(channel_id, "syutain_beta", "Brain-αにエスカレーションしました。")
        return

    # 日跨ぎ参照が必要か
    if detect_context_request(user_msg):
        prev_context = await get_previous_session_context(channel_id)
        if prev_context:
            extra_context += f"\n{prev_context}"

    # 参照解決
    ref = ctx.resolve_reference(user_msg)
    if ref:
        extra_context += f"\n【参照先】{str(ref)[:200]}"

    # 対話履歴取得
    history = await get_recent_history(channel_id, limit=20)

    # 応答生成
    async with message.channel.typing():
        response = await generate_response(user_msg, history, extra_context)

    # ACTION処理
    action_result = await process_actions(response)

    if action_result["actions"]:
        # ACTIONの結果をコンテキストに保存
        if "artifacts" in action_result.get("results", {}):
            ctx.update_references(action_result["results"]["artifacts"])
        elif "errors" in action_result.get("results", {}):
            ctx.update_references(action_result["results"]["errors"])

        followup = await generate_followup(
            action_result["clean_text"], action_result["results"], user_msg
        )
        reply_text = followup[:2000]
    else:
        reply_text = action_result["clean_text"][:2000]

    # スクリーンショットファイルの送信チェック
    if action_result.get("results"):
        for key, val in action_result["results"].items():
            if isinstance(val, str) and val.startswith("__SCREENSHOT__:"):
                filepath = val.replace("__SCREENSHOT__:", "")
                try:
                    import os
                    if os.path.exists(filepath):
                        await message.reply(
                            "スクリーンショット:",
                            file=discord.File(filepath),
                            mention_author=False,
                        )
                        os.remove(filepath)
                except Exception as e:
                    await message.reply(f"画像送信失敗: {e}", mention_author=False)

    if reply_text:
        await message.reply(reply_text, mention_author=False)
        await save_message(channel_id, "syutain_beta", reply_text)

        # daichi_dialogue_logに記録（CLAUDE.mdルール24準拠）
        try:
            from brain_alpha.persona_bridge import log_dialogue
            await log_dialogue(
                session_id=f"discord-{channel_id}",
                channel="discord_dm",
                daichi_msg=user_msg,
                alpha_response=reply_text,
            )
        except Exception:
            pass  # 記録失敗でも対話を止めない

    await bot.process_commands(message)

# Reaction shortcuts
@bot.event
async def on_reaction_add(reaction, user):
    if user == bot.user:
        return
    if reaction.message.author != bot.user:
        return

    emoji = str(reaction.emoji)

    # 自己モニタリング
    from bots.bot_self_monitor import quality_monitor
    signal = quality_monitor.on_reaction(emoji)
    if signal != "neutral":
        quality_monitor.record_signal(signal, reaction.message.content[:80])

    # 承認/却下処理
    if emoji in ("\U0001f44d", "\U0001f44e"):
        import re
        match = re.search(r'承認ID[:\s]*(\d+)', reaction.message.content)
        if match:
            approval_id = int(match.group(1))
            from bots.bot_actions import approve_item, reject_item
            if emoji == "\U0001f44d":
                await approve_item(approval_id)
                await reaction.message.channel.send(f"承認しました。(ID: {approval_id})")
            else:
                await reject_item(approval_id)
                await reaction.message.channel.send(f"却下しました。(ID: {approval_id})")

# Legacy commands
@bot.command(name="承認")
async def approve_cmd(ctx, approval_id: int):
    from bots.bot_actions import approve_item
    await approve_item(approval_id)
    await ctx.reply(f"承認しました。(ID: {approval_id})")

@bot.command(name="却下")
async def reject_cmd(ctx, approval_id: int):
    from bots.bot_actions import reject_item
    await reject_item(approval_id)
    await ctx.reply(f"却下しました。(ID: {approval_id})")

# Scheduled reports
@tasks.loop(time=[dtime(hour=7, minute=0)])
async def morning_report():
    ch = bot.get_channel(GENERAL_CH)
    if ch:
        from bots.bot_notifications import generate_morning_report
        msg = await generate_morning_report(bot)
        await ch.send(msg)

@tasks.loop(time=[dtime(hour=22, minute=0)])
async def night_summary():
    ch = bot.get_channel(GENERAL_CH)
    if ch:
        from bots.bot_notifications import generate_night_summary
        msg = await generate_night_summary(bot)
        await ch.send(msg)

@tasks.loop(minutes=5)
async def session_cleanup():
    """期限切れセッションのクリーンアップ + プロアクティブ報告チェック"""
    from bots.bot_context import session_manager
    session_manager.cleanup_expired()

    # プロアクティブ報告チェック
    ch = bot.get_channel(GENERAL_CH)
    if ch:
        from bots.bot_proactive import check_proactive_triggers
        report = await check_proactive_triggers(ch)
        if report:
            await ch.send(report)

if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN未設定")
        sys.exit(1)
    bot.run(TOKEN)
