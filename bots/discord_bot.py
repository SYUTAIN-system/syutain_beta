"""SYUTAINβ Discord Bot — 自然言語対話（改善版）"""
import os, sys, asyncio, logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import time as dtime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ログ設定（RotatingFileHandler: 10MB x 5世代）
_bot_log_dir = os.getenv("LOG_DIR", str(Path(__file__).resolve().parent.parent / "logs"))
os.makedirs(_bot_log_dir, exist_ok=True)
_bot_log_fmt = logging.Formatter("%(asctime)s [BOT] %(name)s %(levelname)s: %(message)s")
_bot_stream = logging.StreamHandler()
_bot_stream.setFormatter(_bot_log_fmt)
_bot_file = RotatingFileHandler(
    f"{_bot_log_dir}/discord_bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_bot_file.setFormatter(_bot_log_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_bot_stream, _bot_file])
logger = logging.getLogger("syutain.discord_bot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GENERAL_CH = int(os.getenv("DISCORD_GENERAL_CHANNEL_ID", "0"))
BRAIN_ALPHA_DISCORD_ID = os.getenv("BRAIN_ALPHA_DISCORD_ID", "1477009083100958853")

# JST timezone for scheduled reports
JST = timezone(timedelta(hours=9))

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
        logger.info("DB pool初期化完了 (on_ready)")
    except Exception as e:
        logger.error(f"DB pool初期化失敗: {e}")
    if not morning_report.is_running():
        morning_report.start()
    if not night_summary.is_running():
        night_summary.start()
    if not session_cleanup.is_running():
        session_cleanup.start()
    if not system_watchdog.is_running():
        system_watchdog.start()

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author == bot.user:
        return

    # Brain-αへのメンションが含まれている場合、Brain-βは無反応
    if f"<@{BRAIN_ALPHA_DISCORD_ID}>" in message.content:
        return

    # Brain-αのメッセージを検知 → エスカレーション追跡を更新
    if str(message.author.id) == BRAIN_ALPHA_DISCORD_ID:
        try:
            from bots.bot_escalation import on_brain_alpha_response, on_brain_alpha_task_complete
            await on_brain_alpha_response(message)
            await on_brain_alpha_task_complete(message)
        except Exception as e:
            logger.debug(f"Brain-α応答処理スキップ: {e}")
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
    user_msg = (message.content or "").strip()

    # 空メッセージ（添付のみ/ステッカーのみ/空白のみ）は LLM 呼ばない
    if not user_msg and not message.attachments:
        return

    # 意図分類（軽量パターン、LLM呼ばない）
    from bots.bot_intent import classify_intent
    user_intent = classify_intent(user_msg)

    # 島原のメッセージを記録（intent 付き）
    proactive.on_daichi_message()
    await save_message(channel_id, "daichi", user_msg, intent=user_intent)

    # statement 検出 → persona_memory に working fact として記録
    # 「エラー解消した」「CHARLIE復帰済み」等、ユーザーが宣言した事実を忘れない
    if user_intent == "statement":
        try:
            from bots.bot_memory_ingest import ingest_user_statement
            asyncio.ensure_future(ingest_user_statement(user_msg))
        except Exception as _e:
            logger.debug(f"statement ingest スキップ: {_e}")

    # ★ 直接実行ルート：承認/却下コマンドは LLM を通さず即実行
    # LLMが [ACTION:approve:N] を発行せず「承認しました」と幻覚出力する事故を防ぐ
    import re as _re
    _approve_m = _re.match(r'^(?:承認|approve)\s+(\d+)(?:\s+(.+))?$', user_msg, _re.IGNORECASE)
    _reject_m  = _re.match(r'^(?:却下|reject)\s+(\d+)(?:\s+(.+))?$', user_msg, _re.IGNORECASE)
    if _approve_m or _reject_m:
        from bots.bot_actions import approve_item, reject_item
        try:
            if _approve_m:
                _id = int(_approve_m.group(1))
                result = await approve_item(_id)
            else:
                _id = int(_reject_m.group(1))
                _reason = _reject_m.group(2) or None
                result = await reject_item(_id, _reason)
        except Exception as e:
            logger.warning(f"直接承認/却下失敗: {e}")
            result = f"処理失敗: {e}"
        await message.reply(result, mention_author=False)
        await save_message(channel_id, "syutain_beta", result)
        return

    # ★ 記事執筆依頼の直接ルート（P2）
    # パターン: "noteで〜について書いて" / "〜というタイトルで記事" / "記事書いて：〜"
    _article_m = _re.match(
        r'^(?:noteで|記事を?|note記事を?)\s*(.+?)(?:について|という|を|の件で)?\s*'
        r'(?:書いて|執筆して|作って|お願い)(?:\s*[。.])?\s*$',
        user_msg,
    )
    if not _article_m:
        _article_m2 = _re.match(r'^(?:記事|note).*書いて(?:[：:]\s*|\s+)(.+)$', user_msg)
        if _article_m2:
            _article_m = _article_m2
    if _article_m:
        _topic = _article_m.group(1).strip()
        if len(_topic) >= 3:
            from bots.bot_actions import commission_article
            try:
                result = await commission_article(_topic)
            except Exception as e:
                logger.warning(f"記事執筆依頼失敗: {e}")
                result = f"依頼受付失敗: {e}"
            await message.reply(result, mention_author=False)
            await save_message(channel_id, "syutain_beta", result)
            return

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

    # ACTION処理（破壊的ACTIONはuser_msgの同意表現で制御）
    action_result = await process_actions(response, user_message=user_msg)

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
    result = await approve_item(approval_id)
    await ctx.reply(result)

@bot.command(name="却下")
async def reject_cmd(ctx, approval_id: int, *, reason: str = None):
    from bots.bot_actions import reject_item
    result = await reject_item(approval_id, reason=reason)
    await ctx.reply(result)

@bot.command(name="承認一覧")
async def pending_list_cmd(ctx):
    from bots.bot_actions import get_pending_approvals_detail
    result = await get_pending_approvals_detail()
    # 2000文字制限対応
    if len(result) > 1900:
        result = result[:1900] + "\n...(続きはWeb UIで確認)"
    await ctx.reply(result)

@bot.command(name="状態")
async def status_cmd(ctx):
    """ノード・SNS・LLM・コスト・承認待ち・エラーの稼働サマリ"""
    from bots.bot_conversation import _get_system_status
    try:
        s = await _get_system_status()
        text = f"📊 **SYUTAINβ 現在の状態**\n```\n{s}\n```"
        if len(text) > 1900:
            text = text[:1900] + "\n...(省略)"
        await ctx.reply(text)
    except Exception as e:
        await ctx.reply(f"状態取得失敗: {e}")

@bot.command(name="予算")
async def budget_status_cmd(ctx):
    """当日コスト・予算使用率の照会（read-only）。変更は !予算設定"""
    from bots.bot_actions import get_cost_summary
    try:
        r = await get_cost_summary()
        await ctx.reply(
            f"💰 **予算状況**\n"
            f"本日: ¥{r.get('today_jpy', 0):.0f}\n"
            f"週次: ¥{r.get('week_jpy', 0):.0f}\n"
            f"ローカル比率(24h): {r.get('local_pct', 0):.1f}%"
        )
    except Exception as e:
        await ctx.reply(f"予算取得失敗: {e}")

@bot.command(name="記事")
async def articles_cmd(ctx, limit: int = 5):
    """直近生成された note 記事候補を表示"""
    from tools.db_pool import get_connection
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT id, status, LEFT(COALESCE(title, '無題'), 60) as title,
                          quality_score, created_at
                   FROM product_packages
                   WHERE platform='note'
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
        if not rows:
            await ctx.reply("📝 note 記事パッケージはまだありません")
            return
        lines = [f"📝 **直近の note 記事 ({len(rows)}件)**\n"]
        for r in rows:
            q = f"Q={r['quality_score']:.2f}" if r['quality_score'] else "Q=?"
            lines.append(f"#{r['id']} [{r['status']}] {r['title']} ({q})")
        await ctx.reply("\n".join(lines))
    except Exception as e:
        await ctx.reply(f"記事一覧取得失敗: {e}")

@bot.command(name="依頼")
async def commission_cmd(ctx, *, brief: str = ""):
    """記事執筆依頼。例: !依頼 タイトル案|本文ブリーフ"""
    if not brief.strip():
        await ctx.reply("使い方: `!依頼 タイトル案|本文ブリーフ` または `!依頼 ブリーフだけ`")
        return
    from bots.bot_actions import commission_article
    result = await commission_article(brief)
    await ctx.reply(result)

@bot.command(name="予算設定")
async def budget_cmd(ctx, daily: int = 0, monthly: int = 0):
    """予算変更。例: !予算設定 120 2000"""
    from bots.bot_actions import set_budget
    result = await set_budget(daily=str(daily) if daily else "", monthly=str(monthly) if monthly else "")
    await ctx.reply(result)

@bot.command(name="収益記録")
async def revenue_cmd(ctx, amount: int = 0, platform: str = "note", *, product: str = ""):
    """収益記録。例: !収益記録 980 note 記事タイトル"""
    from bots.bot_actions import record_revenue
    result = await record_revenue(amount=str(amount), platform=platform, product=product)
    await ctx.reply(result)

@bot.command(name="charlie")
async def charlie_cmd(ctx, mode: str = "status"):
    """CHARLIE操作。例: !charlie win11 / !charlie status"""
    from bots.bot_actions import charlie_mode
    result = await charlie_mode(mode=mode)
    await ctx.reply(result)

@bot.command(name="レビュー")
async def review_cmd(ctx):
    """Brain-αレビューを手動トリガー"""
    from bots.bot_actions import trigger_review
    await ctx.reply("🔄 レビュー実行中...")
    result = await trigger_review()
    if len(result) > 1900:
        result = result[:1900] + "..."
    await ctx.reply(result)

@bot.command(name="提案生成")
async def proposal_cmd(ctx, channel: str = "note"):
    """提案を手動生成。例: !提案生成 note"""
    from bots.bot_actions import trigger_proposal
    await ctx.reply("💡 提案生成中...")
    result = await trigger_proposal(channel=channel)
    await ctx.reply(result)

# Scheduled reports (JST timezone-aware)
@tasks.loop(time=[dtime(hour=7, minute=0, tzinfo=JST)])
async def morning_report():
    """朝の報告（JST 07:00）"""
    ch = bot.get_channel(GENERAL_CH)
    if not ch:
        logger.warning("morning_report: チャンネル取得失敗")
        return
    try:
        from bots.bot_notifications import generate_morning_report
        msg = await generate_morning_report(bot)
        await ch.send(msg)
        logger.info("morning_report送信完了")
        # alertチャンネルにもWebhook送信
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(f"📋 朝レポート\n{msg}", username="Brain-β Report")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"morning_report送信エラー: {e}")

@tasks.loop(time=[dtime(hour=22, minute=0, tzinfo=JST)])
async def night_summary():
    """夜のサマリー（JST 22:00）"""
    ch = bot.get_channel(GENERAL_CH)
    if not ch:
        logger.warning("night_summary: チャンネル取得失敗")
        return
    try:
        from bots.bot_notifications import generate_night_summary
        msg = await generate_night_summary(bot)
        await ch.send(msg)
        logger.info("night_summary送信完了")
        # alertチャンネルにもWebhook送信
        try:
            from tools.discord_notify import notify_discord
            await notify_discord(f"📋 夜サマリー\n{msg}", username="Brain-β Report")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"night_summary送信エラー: {e}")

@tasks.loop(minutes=5)
async def session_cleanup():
    """期限切れセッションのクリーンアップ + プロアクティブ報告チェック"""
    try:
        from bots.bot_context import session_manager
        session_manager.cleanup_expired()
    except Exception as e:
        logger.error(f"セッションクリーンアップ失敗: {e}")

    # プロアクティブ報告チェック
    ch = bot.get_channel(GENERAL_CH)
    if ch:
        try:
            from bots.bot_proactive import check_proactive_triggers
            report = await check_proactive_triggers(ch)
            if report:
                await ch.send(report)
        except Exception as e:
            logger.error(f"プロアクティブチェック失敗: {e}")

@tasks.loop(minutes=2)
async def system_watchdog():
    """2分ごとにシステム異常を監視して即時報告"""
    ch = bot.get_channel(GENERAL_CH)
    if not ch:
        return
    try:
        from bots.bot_proactive import check_emergency_alerts
        alerts = await check_emergency_alerts()
        if alerts:
            await ch.send(alerts)
    except Exception as e:
        logger.error(f"Watchdog error: {e}")

# before_loopでbotのready待ち
@morning_report.before_loop
async def before_morning_report():
    await bot.wait_until_ready()

@night_summary.before_loop
async def before_night_summary():
    await bot.wait_until_ready()

@session_cleanup.before_loop
async def before_session_cleanup():
    await bot.wait_until_ready()

@system_watchdog.before_loop
async def before_system_watchdog():
    await bot.wait_until_ready()

if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN未設定")
        sys.exit(1)
    bot.run(TOKEN)
