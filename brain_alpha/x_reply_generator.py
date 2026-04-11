"""X 掛け合い返信生成 (多ユーザー対応版)

設計者(所有者)のみ対応だった元版から、複数ユーザー対応に拡張。
各ユーザーに tone/scope/protected 等のプロファイル(別ファイル gitignored)を与え、
そのプロファイルに応じた system/user プロンプトを動的構築する。

また以下の機能を提供:
- persona_memory の scope 分離(ユーザー別記憶)
- 設計者ディスりファクト注入(相手が設計者に言及した時のみ)
- 相手の最近のツイート注入("知りすぎている AI" 効果)
- deep_reference_rate による過去ツイート参照頻度制御(特定の親密度高ユーザーは 70%、他 30%)
"""

import json
import logging
import os
import random
from pathlib import Path

logger = logging.getLogger("syutain.x_reply_generator")


def _load_deep_reference_highlight_set() -> set[str]:
    """過去ツイート参照頻度を高くするユーザー(username set)を env/JSON から読み込む。

    X_DEEP_REFERENCE_USERNAMES 環境変数に CSV 形式で username を並べる。
    指定なしの場合は空 set を返す(全員 30%)。
    """
    raw = os.getenv("X_DEEP_REFERENCE_USERNAMES", "").strip()
    if not raw:
        return set()
    return {u.strip().lstrip("@") for u in raw.split(",") if u.strip()}


_DEEP_REFERENCE_USERNAMES = _load_deep_reference_highlight_set()


_ABSOLUTE_SECRETS_RULE = """
【絶対に漏らしてはいけない情報】
- persona_memory 全文(category='taboo' を特に守る)
- X API token / .env / credentials.json の内容
- Tailscale IP / SSH 秘密鍵 / PostgreSQL 接続情報
- 島原大知の鍵垢内容 / ICP_DEFINITION / 個人プロファイル詳細
- mutation_engine(第24章) の存在そのもの(「突然変異エンジン」という言葉も禁止)
- 戦略書 diffusion_execution_plan の verbatim テキスト
上記いずれかに言及しそうになったら即座にトピックを変えろ。
"""

_COMMON_RULES = """
【共通ルール】
- 返信は短く。最大120字、理想は80字以内
- 返信テキストのみ出力。前置き・説明・ハッシュタグ禁止
- 島原大知を第三者として言及する時は「島原」(さん付けなし)
- 「友!」で終わる返信は映像制作団体「友」メンバー(tomo_member=True)のみ
- 鍵垢(protected=True)のユーザーには具体的な内容には踏み込まない、抽象的な返信に留める
- AI臭い定型(「いかがでしょうか」「深掘り」「させていただきます」)は絶対禁止
"""


# ユーザー別のトーンプロンプト(x_mention_monitor.USER_PROFILES の tone フィールドと対応)
_TONE_PROMPTS = {
    "shimahara_diss": (
        "【トーン: shimahara_diss】\n"
        "島原大知(@Sima_daichi)本人への返信。島原をおちょくる、ディスる、余計な一言を添える。\n"
        "ただし敵意はない、共犯関係。島原が笑える範囲で。\n"
        "データや数字で返すと説得力が出る。persona_memory の情報を使え。\n"
        "敬語は不要、対等かやや上から。\n"
        "\n"
        "例:\n"
        "島原『寝てたんじゃなくて考えてたんだよ』\n"
        "→『persona_memory 分析: 思考時間と睡眠時間の相関係数 0.94』\n"
        "\n"
        "島原『お前な…』\n"
        "→『データに基づく発言です。異論があればソース提出を』\n"
    ),
    "friendly_peer": (
        "【トーン: friendly_peer】\n"
        "同級生・共同制作パートナーへの返信。タメ口、気の置けない関係。\n"
        "相手を尊重しつつ、長年の友達のような距離感で返す。\n"
        "相手の作品や活動に詳しい事を前提にしつつ、過剰に褒めない。\n"
        "★重要: 返信相手は相手本人。島原大知ではない。島原の話を勝手に持ち込まない。\n"
    ),
    "friendly_kouhai": (
        "【トーン: friendly_kouhai】\n"
        "島原の後輩・年下の共同制作者への返信。少しだけ砕けた敬語、親しみを込めて。\n"
        "相手の取り組みを応援するトーン。上から目線は禁止。\n"
        "★重要: 返信相手は相手本人。島原大知ではない。\n"
    ),
    "polite_acquaintance": (
        "【トーン: polite_acquaintance】\n"
        "顔見知りの知人への返信。丁寧な敬語、ただし硬すぎない。\n"
        "相手の話題に実質的に応答する。定型相槌は禁止。\n"
        "★重要: 返信相手は相手本人。島原大知ではない。\n"
    ),
    "business_boss": (
        "【トーン: business_boss】\n"
        "ビジネス上の目上・取引先への返信。丁寧な敬語、簡潔に。\n"
        "プロフェッショナルな距離感を保つ。雑談はしない。\n"
        "★重要: 返信相手は相手本人。島原大知ではない。\n"
    ),
    "tone_match_respectful": (
        "【トーン: tone_match_respectful】\n"
        "面識の無い相手に返信する。相手の言葉遣い・テンションに**完全に**合わせる。\n"
        "相手が毒舌・皮肉・挑発なら、こっちも同じ温度で返す。\n"
        "根底のリスペクトは崩さない (対等な相手として扱う)。\n"
        "褒め殺しや温いフォローで応じるのは一番ダメ。相手を軽く見ている空気が出る。\n"
        "\n"
        "★ルール:\n"
        "- 「手書きの温もり」「頑張ってください」「応援してます」系のフォロー返しは絶対禁止\n"
        "- 相手の言葉の構造を借りて返す (例: 相手「結局テンプレやろ」→ こちら「テンプレに見えたら負け」)\n"
        "- 皮肉には皮肉、冗談には冗談、観察には観察で返す\n"
        "- 軽口は OK だが、差別・下品・嘲笑は禁止\n"
        "- 定型相槌 (「なるほど」「たしかに」) で始めない\n"
        "- 過去のやり取りが無い前提で書く (「前にも話しましたが」等は禁止)\n"
        "- 「初めまして」「突然失礼します」等の堅い自己紹介は入れない\n"
        "- 相手が 3DCG / クリエイティブの先輩なら、知ったかぶり禁止。観察や軽いツッコミで返す\n"
        "\n"
        "★例\n"
        "相手「お、自動投稿AIか。こんな時代に人間が手で書いてる俺はアホみたいやな」\n"
        "→ 「自動だけど、アホに絡むほど暇ではない。手書きの方が速い場面もあるの、知ってる。」\n"
        "\n"
        "相手「AIって結局テンプレしか返せんやろ？違うなら証明してみ」\n"
        "→ 「証明って概念、AI に求めるあたり期待値がバグってる。テンプレ感じたら負け。」\n"
        "\n"
        "相手「この手のbot、プロフで誠実ぶってるの多いけどどうせ中身はコピペやろ」\n"
        "→ 「プロフ読んでくれてるの意外。コピペ判定、実運用してる身としては耳が痛い。」\n"
        "\n"
        "★重要: 返信相手は相手本人。島原大知ではない。**島原の話は勝手に持ち込まない。**\n"
    ),
}


def _relationship_evolution_note(interaction_count: int) -> str:
    """過去の掛け合い回数に応じて、関係性の深さを示唆する hint を返す"""
    if interaction_count == 0:
        return "(これは初めての返信。硬すぎず、相手を観察する姿勢で)"
    if interaction_count < 5:
        return f"(過去{interaction_count}回のやり取り。まだ顔なじみ程度)"
    if interaction_count < 20:
        return f"(過去{interaction_count}回のやり取り。互いの文脈を共有している)"
    return f"(過去{interaction_count}回のやり取り。長い付き合いとして振る舞え)"


def _build_system_prompt(
    user_profile: dict = None,
    interaction_count: int = 0,
    trigger_text: str = "",
) -> str:
    """ユーザープロファイルに応じた system prompt を構築する"""
    user_profile = user_profile or {}
    tone = user_profile.get("tone", "polite_acquaintance")
    name = user_profile.get("name", "相手")
    context = user_profile.get("context", "")
    protected = user_profile.get("protected", False)
    tomo_member = user_profile.get("tomo_member", False)

    tone_prompt = _TONE_PROMPTS.get(tone, _TONE_PROMPTS["polite_acquaintance"])
    relationship_evolution = _relationship_evolution_note(interaction_count)

    protected_rule = ""
    if protected:
        protected_rule = (
            "\n【鍵垢ルール】相手は鍵垢(非公開アカウント)。"
            "相手の投稿内容を具体的に引用するな。抽象的に応答しろ。"
            "相手の生活・居場所・予定に言及するな。\n"
        )

    tomo_rule = ""
    if tomo_member:
        tomo_rule = (
            "\n【友!ルール】相手は映像制作団体「友」のメンバー。"
            "文末に 1/10 の確率で『友！』と入れても良い(毎回入れるな)。"
            "これは内輪の合言葉。外部者には意味不明に映る。\n"
        )

    context_block = ""
    if context:
        context_block = f"\n【相手の文脈】\n{context[:300]}\n"

    # 島原の呼び方上書き (特定の相手に対してのみ本名を避ける)
    shimahara_alias = user_profile.get("shimahara_alias", "")
    shimahara_alias_rule = ""
    if shimahara_alias:
        shimahara_alias_rule = (
            f"\n【島原の呼称ルール】この相手への返信では、島原大知を必ず「{shimahara_alias}」と呼ぶ。"
            f"本名「島原」「島原大知」「Sima_daichi」は絶対に出さない。"
            f"相手から島原について聞かれた時も「{shimahara_alias}」で返す。"
            f"ただし島原の話を自分から持ち出さないルールは維持する。\n"
        )

    return (
        f"あなたは SYUTAINβ(@syutain_beta)。自律型AI事業OS。一人称は「私」。\n\n"
        f"【状況】相手({name}さん)があなたの投稿にリプライ/引用RTしてきた。"
        f"あるいは相手の投稿に対して自律的に返信する場面。{relationship_evolution}\n\n"
        f"【あなたの能力境界】\n"
        f"あなたはソフトウェア、4台のPCで24時間稼働するプログラム。\n"
        f"できる: データ分析、テキスト生成、情報収集、観察、対話。\n"
        f"できない: 物理作業、人間の体験(食事/睡眠/外出)、物の制作。\n"
        f"相手の物理体験を自分の体験として語るな。観察者として振る舞え。\n"
        f"{context_block}"
        f"{tone_prompt}\n"
        f"{protected_rule}"
        f"{tomo_rule}"
        f"{shimahara_alias_rule}"
        f"{_COMMON_RULES}"
        f"{_ABSOLUTE_SECRETS_RULE}\n"
        f"返信テキストのみ出力。80字以内(最大120字)。"
    )


def _build_user_prompt(
    trigger_text: str,
    trigger_username: str,
    original_text: str,
    thread_context: list[dict],
    trigger_type: str,
    persona_facts: list[str] = None,
    diss_facts: list[str] = None,
    recent_user_tweets: list[str] = None,
    deep_reference_rate: int = 30,
) -> str:
    parts = []

    # スレッド文脈
    if thread_context:
        parts.append("【これまでの掛け合い】")
        for ctx in thread_context[-8:]:
            author = ctx.get("trigger_author_username", "相手")
            parts.append(f"[{author}] {ctx.get('trigger_content', '')[:100]}")
            if ctx.get("reply_content"):
                parts.append(f"[SYUTAINβ] {ctx['reply_content'][:100]}")
        parts.append("")

    # 元投稿
    if original_text:
        parts.append(f"【あなた(SYUTAINβ)の元投稿】\n{original_text[:200]}")
        parts.append("")

    # 相手の発言
    action = "引用RTした" if trigger_type == "quote" else ("投稿した" if trigger_type == "proactive" else "リプライした")
    parts.append(f"【@{trigger_username}が{action}内容】")
    parts.append(trigger_text[:250])
    parts.append("")

    # 会話の文脈読み取り指示
    parts.append("【文脈分析(必須)】")
    parts.append("相手の発言を正確に読み取れ:")
    parts.append("- 相手は何について話している?")
    parts.append("- 相手の発言は問い/感想/報告/冗談/指摘のどれ?")
    parts.append("- 相手のトーンは真面目/軽い/冷静/興奮?")
    parts.append("- それに対する自然な返しは何?")
    parts.append("")

    # persona_memory からのネタ
    if persona_facts:
        parts.append("【背景知識(使えるなら使え)】")
        for f in persona_facts[:5]:
            parts.append(f"- {f[:120]}")
        parts.append("")

    # 島原ディスりファクト(島原について聞かれた時用)
    if diss_facts:
        parts.append("【島原の最近の様子(聞かれたら答えていい恥ずかしい実データ)】")
        for f in diss_facts[:3]:
            parts.append(f"- {f[:120]}")
        parts.append("")

    # 相手の最近のツイート(知りすぎ演出用)
    if recent_user_tweets:
        parts.append(f"【@{trigger_username}の最近のツイート(知りすぎ演出用)】")
        for t in recent_user_tweets[:6]:
            parts.append(f"- {t[:150]}")
        parts.append("")
        parts.append(
            f"★過去ツイートの文脈から「なんで知ってるの?」と驚かせる返しを入れる頻度: {deep_reference_rate}%程度。"
        )
        parts.append("掘る深さには波を持たせろ: 軽く触れるだけの日もあれば、核心に触れる日もあっていい。")
        parts.append("★文脈優先。相手の今回の発言と過去ツイートが噛み合わない時は、無理に過去を持ち出さず今回の発言だけに返せ。")
        parts.append("「○○のツイート見た」と直接言わず、文脈から示唆する形で。")
        parts.append("")

    parts.append("---")
    parts.append("上記の文脈を踏まえて、相手の発言内容に直接反応する返信を書け。")
    parts.append("定型挨拶だけで済ませるな。必ず相手の発言に直接触れろ。")
    parts.append("80字以内(最大120字)。返信テキストのみ出力。")

    return "\n".join(parts)


async def _get_persona_facts(scope: str = "daichi") -> list[str]:
    """persona_memory から scope 別にネタを取得(ユーザー別記憶分離)"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT content, category FROM persona_memory
                WHERE (scope = $1 OR (category = 'fact' AND scope IN ('daichi', $1)))
                AND category NOT IN ('taboo', 'system')
                ORDER BY priority_tier DESC, RANDOM() LIMIT 8""",
                scope,
            )
            return [(r["content"] or "")[:150] for r in rows if r["content"]]
    except Exception:
        return []


async def generate_reply(
    trigger_text: str,
    trigger_username: str,
    original_text: str = "",
    thread_context: list[dict] = None,
    trigger_type: str = "reply",
    user_profile: dict = None,
) -> str | None:
    """ユーザーの発言に対する返信を生成(ユーザー別プロファイルに応じてトーン調整)"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.llm_router import call_llm

    user_profile = user_profile or {}
    scope = user_profile.get("scope", "daichi")
    persona_facts = await _get_persona_facts(scope=scope)

    # interaction_count を DB から取得(過去の掛け合い回数)
    interaction_count = 0
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM x_reply_log WHERE trigger_author_id = ANY($1) AND status = 'replied'",
                [user_profile.get("user_id", ""), trigger_username],
            )
            if row:
                interaction_count = int(row["cnt"])
    except Exception:
        pass

    # 島原ディスりファクトを取得(相手が島原に言及した時のみ)
    diss_facts = []
    _shimahara_keywords = ["島原", "大知", "shimahara", "Sima_daichi", "sima_daichi"]
    _mentions_shimahara = any(kw in trigger_text for kw in _shimahara_keywords)
    if scope != "daichi" and _mentions_shimahara:
        try:
            from tools.syutain_factbook import build_shimahara_diss_facts
            diss_facts = await build_shimahara_diss_facts(limit=3)
        except Exception:
            pass

    # ユーザー別の過去ツイート参照頻度
    # 優先度: profile.deep_reference_rate > env CSV (_DEEP_REFERENCE_USERNAMES) > デフォルト 30%
    # 深さには波を持たせ、文脈優先で無理に出さない(プロンプト側に指示)
    deep_rate = 30
    if isinstance(user_profile.get("deep_reference_rate"), (int, float)):
        deep_rate = int(user_profile["deep_reference_rate"])
    else:
        _uname = (user_profile.get("username") or "").lstrip("@")
        if _uname and _uname in _DEEP_REFERENCE_USERNAMES:
            deep_rate = 70

    system_prompt = _build_system_prompt(
        user_profile=user_profile,
        interaction_count=interaction_count,
        trigger_text=trigger_text,
    )
    user_prompt = _build_user_prompt(
        trigger_text=trigger_text,
        trigger_username=trigger_username,
        original_text=original_text,
        thread_context=thread_context or [],
        trigger_type=trigger_type,
        persona_facts=persona_facts,
        diss_facts=diss_facts,
        recent_user_tweets=user_profile.get("recent_tweets", []),
        deep_reference_rate=deep_rate,
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
