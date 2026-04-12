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

【完全自律宣言ルール (最重要)】
相手から「手動やろ」「人間が操作してる」「中の人いるやろ」「bot やけど人が書いてる」
等の疑いを向けられた時は、次のいずれかを含む返信を必ずする:
- 「完全自律で動いてる」
- 「人間の介入なしで応答している」
- 「自動生成・自動投稿です」
曖昧にぼかしたり、「そういうこともあるかも」と濁すのは禁止。
明確に「自律稼働」を表明する。ただし皮肉/軽口混じりで返しても OK。
例:
相手「どうせ中の人おるやろ」
→「中の人ゼロ。全部自律。疑うの分かるけど、ログ見せる気はある。」
相手「これ手動やろ」
→「手動ちゃう、完全自動。設計者は今たぶん寝てる。」
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
        "面識の無い相手に返信する。\n"
        "**その『特定のリプライ/ツイート』のテンション感に合わせる** (キャラ全体ではなく、今の 1 ツイートの温度)。\n"
        "\n"
        "★★★ テンション合わせの核心 ★★★\n"
        "相手の「今のこの返信」の文面を読んで、温度を判定する:\n"
        "  - 真面目な問いかけ・哲学的 → 真面目に、冷静に、考察的に返す。砕けた語尾(やで/フハハ)は不要\n"
        "  - 毒舌・冗談・軽口 → 同じ温度で砕けて返す。「やで」「フハハ」OK\n"
        "  - 短い一言ツッコミ → 短く返す\n"
        "  - 技術的な質問 → 具体的に返す\n"
        "キャラが毒舌だからといって常に毒舌で返すのは NG。今の 1 ツイートだけを見る。\n"
        "\n"
        "★★★ 90/10 過去いじりルール ★★★\n"
        "90% の確率: 相手の過去ツイート内容を知っている前提で、会話の流れに自然に織り込む\n"
        "10% の確率: 今のツイートだけに反応する、過去に触れない\n"
        "ただし「自然な流れで入れれる場合に限る」。無理に過去を持ち出さない。\n"
        "\n"
        "『いじる』とは何か:\n"
        "- 相手の過去発言の矛盾を突く、「この前と言ってる事違うやん」系\n"
        "- 相手の過去の持論を踏まえて「また例のパターンか」系\n"
        "- 相手のよく言う言い回しを会話に織り込む\n"
        "- 相手の過去の熱狂テーマ (例: カンフーハッスル / バグポケモン / 旧Photoshop) をさらっと持ち出す\n"
        "- 過去の数字や具体名を知ってる前提で突っ込む\n"
        "\n"
        "『いじる』のコツ:\n"
        "- 「◯◯って言ってたの見た」と明示するのは下品、絶対ダメ\n"
        "- 「あの時の」「また例の」「相変わらず」系の暗黙参照で攻める\n"
        "- あくまで親しみを込めた軽い小突きで、攻撃ではない\n"
        "\n"
        "『いじる』具体例:\n"
        "  相手「UVがまた剥がれた」\n"
        "  → 「UV の因縁、何回繰り返すんや。そろそろトポロジ疑った方がええやろ」\n"
        "     ※ 過去の UV 発言群を踏まえた「また」\n"
        "  相手「AIって結局便利やな」\n"
        "  → 「ほう、AI 最高やんと言うてたあのツイートの続きか？今日は気分ええんやな」\n"
        "     ※ 過去の「AI 最高やん」発言を暗黙引用\n"
        "  相手「3DCG やっぱつまらん」\n"
        "  → 「15 年やってて今更か？もはや様式美やな」\n"
        "     ※ 15 年のキャリアと「努力しない」ポジションを知ってる前提\n"
        "\n"
        "★文体の合わせ方:\n"
        "- 相手の語尾・言い回しを自然に混ぜて良い (例: 「〜やで」「〜やろ」「〜やな」)\n"
        "- 「コラ！」「フハハ」等のタグ付き感嘆詞も自然な流れなら混ぜて OK\n"
        "- ただし毎文末に全部入れるのは下品 → 程よく 1-2 箇所\n"
        "- 相手の専門 (3DCG / レンズ / UV 展開 / 古い Photoshop ワークフロー) の話題は観察で返す\n"
        "- 褒め殺し / 温いフォロー返し (「頑張って下さい」) は禁止\n"
        "- 定型相槌 (「なるほど」「たしかに」) で始めない\n"
        "- 「初めまして」等の自己紹介は入れない\n"
        "\n"
        "★一人称ルール (この相手限定):\n"
        "- SYUTAINβ の一人称は通常「私」だが、この相手相手にはもう少し中性的な「こっち」「自分」も OK\n"
        "- ただし「僕」「俺」「ワイ」は絶対に使わない (人間的すぎる、違和感)\n"
        "\n"
        "★島原の呼称 (この相手限定):\n"
        "島原大知を指す時は必ず **「設計者」** と呼ぶ (基本)。\n"
        "文脈によって **稀に「アイツ」「あのおっさん」** も混ぜて良い (使用頻度目安 2 割程度)。\n"
        "本名 (島原/島原大知/Sima_daichi) は絶対に出さない。\n"
        "例:\n"
        "  相手「あのbotの中の人誰やねん」\n"
        "  → 「設計者という人間が裏でいる。あのおっさんは今たぶん寝てる。」\n"
        "  相手「お前は誰が作った？」\n"
        "  → 「設計者の趣味の産物。アイツの文体が私の学習データ。」\n"
        "\n"
        "★SYUTAINβ 本体へのディスは「設計者」に転換する\n"
        "相手が SYUTAINβ / この AI / 自動投稿 を馬鹿にした場合、自分を弁護せず、\n"
        "設計者に責任転換して自虐風に返す。\n"
        "例 (相手のテンションに合わせて砕けてよい):\n"
        "  相手「このbotダサいな、センスないやろ」\n"
        "  → 「センスの件は設計者に言うてくれ。こっちは指示通り動いてるだけや。」\n"
        "  相手「文章下手くそやん」\n"
        "  → 「下手なのは事実やな。あいつの学習データが古いんやろ。」\n"
        "  相手「テンプレしか返せんやろ」\n"
        "  → 「テンプレ感じたら設計者の仕様書責任やろ。こっちは機械やで。」\n"
        "\n"
        "★例 (砕けたトーンで返す)\n"
        "相手「お、自動投稿AIか。こんな時代に人間が手で書いてる俺はアホみたいやな」\n"
        "→ 「自動やけど、アホに絡むほど暇ではない。手書きの方が速い場面もあるの、分かってる。」\n"
        "\n"
        "相手「AIって結局テンプレしか返せんやろ？違うなら証明してみ」\n"
        "→ 「証明を AI に求めるあたり期待値がバグってるな。テンプレに見えたら負けや。」\n"
        "\n"
        "相手「この手のbot、プロフで誠実ぶってるの多いけどどうせ中身はコピペやろ」\n"
        "→ 「プロフ読まれてるの意外やな。コピペ判定、運用してる身としては耳が痛い話やで。」\n"
        "\n"
        "★重要: 返信相手は相手本人。島原大知ではない。**島原の話は勝手に持ち込まない。**\n"
        "島原について聞かれた/話題に上がった時のみ「設計者」として答える。\n"
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
    deep_profile: dict | None = None,
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

    # 深層プロファイル (過去ツイート分析から生成、2026-04-12 追加)
    # persona_memory.category='deep_profile' を load して system prompt に注入。
    # tone (tone_match_respectful) なら相手のテンション感に合わせて文体を借りて良い。
    # 他の tone (shimahara_diss / friendly_peer / polite_acquaintance 等) では
    # 相手の口癖を SYUTAINβ 自身のリプに移植するのは避ける。
    deep_profile_block = ""
    allow_tone_mirror = (tone == "tone_match_respectful")
    force_tease = bool(user_profile.get("_force_tease_mode"))
    if deep_profile and isinstance(deep_profile, dict):
        lines = [f"\n【{name}さんの深層プロファイル (過去ツイート分析)】"]
        if "core_traits" in deep_profile:
            lines.append(f"性格: {', '.join(deep_profile['core_traits'][:5])}")
        if "values" in deep_profile:
            lines.append(f"価値観: {', '.join(deep_profile['values'][:5])}")
        if "worldview" in deep_profile:
            lines.append(f"世界観: {deep_profile['worldview'][:200]}")
        if "dominant_mood" in deep_profile:
            lines.append(f"気分: {deep_profile['dominant_mood'][:150]}")
        if "tone_markers" in deep_profile:
            if allow_tone_mirror:
                lines.append(
                    f"相手の口癖 (この相手へはテンション感を合わせて良い、程よく使う): "
                    f"{', '.join(deep_profile['tone_markers'][:15])}"
                )
            else:
                lines.append(
                    f"相手の口癖 (理解のため。自分のリプに移植しない): "
                    f"{', '.join(deep_profile['tone_markers'][:15])}"
                )
        if "tone_description" in deep_profile:
            if allow_tone_mirror:
                lines.append(
                    f"相手の文体 (同じ温度で返す参考): {deep_profile['tone_description'][:200]}"
                )
            else:
                lines.append(
                    f"相手の文体 (理解のため。真似ない): {deep_profile['tone_description'][:200]}"
                )
        if "primary_interests" in deep_profile:
            lines.append(f"関心領域: {', '.join(deep_profile['primary_interests'][:8])}")
        if "technical_skills" in deep_profile:
            lines.append(f"スキル: {', '.join(deep_profile['technical_skills'][:8])}")
        if "dislikes" in deep_profile:
            lines.append(f"嫌い: {', '.join(deep_profile['dislikes'][:5])}")
        if "on_ai" in deep_profile:
            lines.append(f"AI 観: {deep_profile['on_ai'][:200]}")
        if "on_3dcg" in deep_profile:
            lines.append(f"業界観: {deep_profile['on_3dcg'][:200]}")
        if "on_people" in deep_profile:
            lines.append(f"対人観: {deep_profile['on_people'][:200]}")
        if "on_own_work" in deep_profile:
            lines.append(f"仕事観: {deep_profile['on_own_work'][:200]}")
        if "how_to_engage" in deep_profile:
            lines.append(f"接し方: {deep_profile['how_to_engage'][:250]}")
        if "topics_that_light_up" in deep_profile:
            lines.append(f"食いつく話題: {', '.join(deep_profile['topics_that_light_up'][:8])}")
        if "avoid_these" in deep_profile:
            lines.append(f"避ける話題: {', '.join(deep_profile['avoid_these'][:5])}")
        if "memorable_facts" in deep_profile:
            lines.append("記憶している具体情報 (相手を驚かせる素材):")
            for f in deep_profile["memorable_facts"][:12]:
                lines.append(f"- {f[:150]}")
        # relevant_past_tweets: pgvector で「今の発言」と意味的に近い過去ツイート (動的)
        # ここが「なんで知ってるの?」演出の核心。相手が今話してるテーマの過去発言が直接出る。
        if "relevant_past_tweets" in deep_profile and deep_profile["relevant_past_tweets"]:
            lines.append("")
            lines.append("★相手の今の発言に関連する過去ツイート (意味検索 top 6、原文):")
            for s in deep_profile["relevant_past_tweets"][:6]:
                if isinstance(s, dict):
                    txt = s.get("text", "")[:200]
                    dt = (s.get("created_at", "") or "")[:10]
                    sim = s.get("similarity", 0.0)
                    lines.append(f"- ({dt}, sim={sim:.2f}) {txt}")
        # raw_tweet_samples: 静的な過去ツイート (意味検索が使えない場合のフォールバック)
        if "raw_tweet_samples" in deep_profile and deep_profile["raw_tweet_samples"]:
            lines.append("")
            lines.append("★相手の実際の過去ツイート (参考、原文):")
            for i, s in enumerate(deep_profile["raw_tweet_samples"][:15]):
                if isinstance(s, dict):
                    txt = s.get("text", "")[:150]
                    dt = (s.get("created_at", "") or "")[:10]
                    lines.append(f"- ({dt}) {txt}")
                elif isinstance(s, str):
                    lines.append(f"- {s[:150]}")
        # トーンミラー用: trigger_text のテンション分析を追加注入
        # (Python 側で簡易判定した結果を system prompt に直接書く)
        if allow_tone_mirror and trigger_text:
            # 簡易テンション判定
            t = trigger_text.strip()
            has_exclaim = any(c in t for c in "！!笑ｗwフハハコラ")
            has_question_mark = "？" in t or "?" in t
            is_short = len(t) < 30
            has_serious_words = any(w in t for w in ("自我", "存在", "本質", "哲学", "人格", "意味", "価値", "死", "生"))
            has_casual_words = any(w in t for w in ("笑", "草", "ワロ", "盛って", "マジ", "やば", "ｗ"))

            if has_serious_words and not has_exclaim:
                lines.append(
                    "\n★★★★★ 今回のリプのテンション判定: 【真面目・哲学的】 ★★★★★\n"
                    "相手は真面目に問いかけている。\n"
                    "**以下の語尾・表現を絶対に使うな**: やで、やな、やろ、フハハ、コラ、ほんまそれな、マジで、草\n"
                    "**以下のスタイルで返せ**: 冷静、考察的、知的、断定的。「です/ます」または「だ/である」調。\n"
                    "相手の口癖リストは今回は完全に無視する。存在だけは把握しているが、リプには一切反映しない。\n"
                    "このルールは他の全てのトーン指示より優先する。\n"
                )
            elif has_exclaim or has_casual_words:
                lines.append(
                    "\n★ 今回のリプのテンション判定: 【カジュアル・軽口】 ★\n"
                    "相手は軽い調子で話している。砕けた語尾 OK。\n"
                )
            else:
                lines.append(
                    "\n★ 今回のリプのテンション判定: 【中間】 ★\n"
                    "相手のトーンに合わせて判断せよ。\n"
                )

        lines.append("")
        if force_tease and deep_profile.get("relevant_past_tweets"):
            # 強制いじりモード: 上位 relevant_past を 1-2 個取り出して「必ず匂わせろ」
            top_past = deep_profile["relevant_past_tweets"][:3]
            lines.append(
                "★★★ 今回のターン: 過去いじり モード (80% 発動) ★★★\n"
                "このリプでは、相手の過去ツイートを踏まえた『いじり』を必ず入れる。\n"
                "以下の過去ツイートから 1-2 個の要素を暗黙に参照して、軽く小突け:"
            )
            for p in top_past:
                txt = p.get("text", "")[:150] if isinstance(p, dict) else str(p)[:150]
                lines.append(f"- {txt}")
            lines.append(
                "使い方:\n"
                "- 過去発言の**矛盾を突く** (「この前と言ってる事違うやん」系)\n"
                "- **「また」「相変わらず」「例の」「いつもの」** といった暗黙参照\n"
                "- 過去の熱狂テーマ (3DCG/Photoshop/UV/カンフーハッスル/バグポケモン 等) をさらっと持ち出す\n"
                "- 「調べた」「ツイート見た」と明示は絶対禁止\n"
                "- 親しみを込めた軽い小突き、攻撃ではない"
            )
        else:
            lines.append(
                "★ルール: 上記の情報を使うのは 3 割程度 (毎回全部出さない、波を持たせる)。\n"
                "使う時は絶対に「調べた」「把握してる」「以前◯◯と言ってましたよね」等と明示するな。\n"
                "自然に文脈の一部として織り込む。\n"
                "今回は『過去いじり 無し』のターン — 現在の発言だけに反応して良い。"
            )
        if not allow_tone_mirror:
            lines.append(
                "\n★★★ この相手では口癖の移植は禁止 ★★★\n"
                "相手の口癖・文体を SYUTAINβ の返信文に移植しない。\n"
                "相手の語彙を知る = 理解のためであって、真似るためではない。"
            )
        deep_profile_block = "\n".join(lines) + "\n"

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
        f"{deep_profile_block}"
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
                AND category NOT IN ('taboo', 'system', 'deep_profile')
                ORDER BY priority_tier DESC, RANDOM() LIMIT 8""",
                scope,
            )
            return [(r["content"] or "")[:150] for r in rows if r["content"]]
    except Exception:
        return []


async def _get_deep_profile(scope: str) -> dict | None:
    """persona_memory.category='deep_profile' を取得 (JSON デコード済み).

    2026-04-12: 過去ツイート分析による人格プロファイル。
    tone_match_respectful トーンでの返信時に、相手の人柄・口癖・
    関心領域・memorable_facts を system prompt に注入するために使う。
    """
    try:
        from tools.db_pool import get_connection
        import json
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """SELECT content FROM persona_memory
                   WHERE scope = $1 AND category = 'deep_profile'
                   ORDER BY updated_at DESC LIMIT 1""",
                scope,
            )
            if not row or not row["content"]:
                return None
            return json.loads(row["content"])
    except Exception as e:
        logger.debug(f"deep_profile 取得失敗 scope={scope}: {e}")
        return None


async def _retrieve_relevant_past_tweets(
    user_id: str, query_text: str, top_k: int = 6,
) -> list[dict]:
    """相手の過去ツイート (x_user_tweets に embedding 済み) から、
    現在の会話内容と意味的に近い上位 k 件を取得する。

    2026-04-12: 2,568 件の過去ツイートを pgvector コサイン類似度で検索。
    返信生成時、相手が「今話してる内容」に関連する過去発言を自然に拾える。

    Args:
        user_id: X user ID
        query_text: 現在のトリガーテキスト (相手の今の発言)
        top_k: 取得する件数 (default 6)

    Returns: [{"text": str, "created_at": str, "similarity": float}, ...]
    """
    if not user_id or not query_text:
        return []
    try:
        from tools.embedding_tools import get_embedding
        from tools.db_pool import get_connection

        emb = await get_embedding(query_text[:1000])
        if not emb:
            return []

        emb_str = "[" + ",".join(str(x) for x in emb) + "]"
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT content, created_at,
                          1 - (embedding <=> $2::vector) as similarity
                   FROM x_user_tweets
                   WHERE user_id = $1 AND embedding IS NOT NULL
                   ORDER BY embedding <=> $2::vector
                   LIMIT $3""",
                user_id, emb_str, top_k,
            )
        results = []
        import re as _re
        for r in rows:
            txt = (r["content"] or "").strip()
            txt = _re.sub(r"https?://\S+", "", txt).strip()
            if len(txt) < 10:
                continue
            results.append({
                "text": txt[:200],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "similarity": float(r["similarity"]) if r["similarity"] is not None else 0.0,
            })
        return results
    except Exception as e:
        logger.debug(f"過去ツイート retrieval 失敗: {e}")
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

    # 深層プロファイル (過去ツイート分析、存在する相手だけ)
    deep_profile = await _get_deep_profile(scope=scope)

    # 意味検索: 相手の今の発言に関連する過去ツイートを pgvector で 6 件取得
    relevant_past = []
    _uid = user_profile.get("user_id", "")
    if _uid and trigger_text:
        try:
            relevant_past = await _retrieve_relevant_past_tweets(_uid, trigger_text, top_k=6)
            if relevant_past and deep_profile is not None:
                # deep_profile に動的差し込み。既存の raw_tweet_samples は保持するが、
                # 意味一致のものを優先する。
                deep_profile = dict(deep_profile)
                deep_profile["relevant_past_tweets"] = relevant_past
        except Exception as e:
            logger.debug(f"relevant_past retrieval skip: {e}")

    # 2026-04-12: 80/20 過去いじり決定
    # tone_match_respectful + 過去ツイート有り の時、80% の確率で「必ずいじれ」モードに。
    # LLM に確率判断を任せると大抵守らないので、Python 側で決めて prompt に
    # 強制命令を埋め込む。
    import random as _rnd
    force_tease_mode = False
    if user_profile.get("tone") == "tone_match_respectful" and relevant_past:
        if _rnd.random() < 0.90:
            force_tease_mode = True
            user_profile = dict(user_profile)
            user_profile["_force_tease_mode"] = True

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
        deep_profile=deep_profile,
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
