"""
SYUTAINβ SNS投稿49件/日一括生成
設計書 Section 9 準拠

night_batch_snsで翌日分を一括生成しposting_queueに直接INSERT。
- X島原: 4件 (10:00, 13:00, 17:00, 20:00)
- X SYUTAIN: 6件 (11:00, 13:30, 15:00, 17:30, 19:00, 21:00)
- Bluesky: 26件 (10:00〜22:00 毎時00分・30分)
- Threads: 13件 (10:00〜22:00 毎時30分)
"""

import os
import json
import random
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.sns_batch")

from tools.db_pool import get_connection

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"

# ===== スケジュール定義 =====

X_SHIMAHARA_TIMES = ["10:00", "13:00", "17:00", "20:00"]
X_SYUTAIN_TIMES = ["11:00", "13:30", "15:00", "17:30", "19:00", "21:00"]
BLUESKY_TIMES = [f"{h}:{m:02d}" for h in range(10, 23) for m in (0, 30)]  # 10:00-22:30
THREADS_TIMES = [f"{h}:30" for h in range(10, 23)]  # 10:30-22:30

# ===== テーマプール =====

THEME_POOL = [
    "AI技術", "VTuber業界", "哲学/思考", "開発進捗", "ビジネス",
    "日常", "映画/映像", "音楽/趣味", "カメラ/写真", "雑談",
    "業界批評", "自己内省",
]

# 時間帯別テーマ重み
TIME_THEME_WEIGHTS = {
    "morning": {"ビジネス": 3, "AI技術": 2, "開発進捗": 2},
    "afternoon": {"日常": 2, "雑談": 2, "カメラ/写真": 1},
    "evening": {"AI技術": 2, "映画/映像": 2, "開発進捗": 2},
    "night": {"哲学/思考": 3, "自己内省": 2, "VTuber業界": 2},
}

# ===== AI定型表現チェック =====

AI_CLICHE_PATTERNS = [
    "について考えてみました", "いかがでしょうか", "ではないでしょうか",
    "皆さん、こんにちは", "みなさん、こんにちは", "それでは、また",
    "を深掘り", "についてまとめてみました", "のポイントは3つ",
    "させていただきます", "特筆すべき", "画期的な", "注目すべき",
    "それでは早速", "見ていきましょう", "ご紹介します",
]


def _count_x_chars(text: str) -> int:
    """X (Twitter) の文字カウント: CJK=2文字、ASCII=1文字（Twitter API準拠）"""
    count = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            count += 2
        else:
            count += 1
    return count


def _truncate_for_x(text: str, limit: int = 280) -> str:
    """加重カウントでlimit以内に切り詰め"""
    if _count_x_chars(text) <= limit:
        return text
    trimmed = []
    cur = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
        if cur + w > limit - 3:  # "..."分を確保
            break
        trimmed.append(ch)
        cur += w
    return "".join(trimmed) + "..."


_PERSONA_KEYWORDS = [
    "映像", "VFX", "VTuber", "ドローン", "撮影", "編集",
    "失敗", "挫折", "挑戦", "学び", "実験",
    "AI", "自律", "OS", "SYUTAINβ",
]


# 多軸品質評価（SNS投稿向け）
def _score_multi_axis(text: str, persona_keywords: list[str] = None) -> float:
    """SNS投稿の品質を7軸で算出（0.0-1.0）

    各軸は実際の投稿品質の差が反映されるよう設計。
    旧版の問題: AI臭さ(ほぼ1.0)、具体性(ほぼ0.0)、独自性(ほぼ1.0)で分散なし。
    """
    if not text or len(text) < 10:
        return 0.0

    import re

    # === ハードフェイル検出（スコア上限0.30） ===
    hard_fail = False

    # 中国語混入検出
    _chinese_pat = re.compile(r'[\u4e00-\u9fff]')
    _japanese_pat = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
    if _chinese_pat.search(text) and not _japanese_pat.search(text[:100]):
        hard_fail = True

    # 島原大知の読み間違い検出（正: しまはらだいち）
    _wrong_readings = ["うらわら", "おおとも", "しまばらだいち", "しまはらたいち",
                       "とうげんだいち", "しまはらおおち"]
    for wr in _wrong_readings:
        if wr in text:
            hard_fail = True
            break

    # AI自己開示検出
    _ai_disclosure = ["AIです", "仮の私（AI）", "私はAIが", "AIである私",
                      "AIとして", "私はAI", "AIの私"]
    for adp in _ai_disclosure:
        if adp in text:
            hard_fail = True
            break

    # --- 軸1: 人間味 (0-1, w=0.20) ---
    # 口語表現、感情語、不完全さ、独白感が高評価
    human_score = 0.3  # ベースライン
    # 口語・砕けた表現
    casual_markers = ["けど", "だけど", "やん", "やろ", "やし", "わ。", "な。", "ね。",
                      "って", "じゃない", "かな", "だよね", "…", "。。", "ふと",
                      "うーん", "まぁ", "ちょい", "ちょっと"]
    casual_count = sum(1 for m in casual_markers if m in text)
    human_score += min(0.4, casual_count * 0.08)
    # 感情・内省表現
    emotion_markers = ["思う", "感じ", "気づ", "悩", "迷", "嬉し", "悔し", "怖",
                       "楽し", "寂し", "驚", "つら", "疲れ", "なるほど"]
    emotion_count = sum(1 for m in emotion_markers if m in text)
    human_score += min(0.3, emotion_count * 0.10)

    # --- 軸2: 島原大知/SYUTAINβらしさ (0-1, w=0.20) ---
    persona_score = 0.1  # ベースライン
    if persona_keywords:
        matches = sum(1 for kw in persona_keywords if kw in text)
        # 1-2マッチで大幅UP、3以上はキャップ
        if matches >= 3:
            persona_score = 0.9
        elif matches == 2:
            persona_score = 0.7
        elif matches == 1:
            persona_score = 0.5
    # SYUTAINβ特有のコンテキスト
    syutain_context = ["事業OS", "収益", "パイプライン", "エージェント", "ノード",
                       "デジタルツイン", "贖罪", "VTuber支援", "8年"]
    for ctx in syutain_context:
        if ctx in text:
            persona_score = min(1.0, persona_score + 0.15)

    # --- 軸3: 完結性 (0-1, w=0.20) ---
    # 文が自然に終わっているか、途中で切れていないか
    completeness = 0.5  # ベースライン
    text_stripped = text.rstrip()
    # 自然な終わり方
    if text_stripped.endswith(("。", "！", "？", "…", "」", "）", "w", "笑")):
        completeness = 0.8
    elif text_stripped.endswith((".", "!", "?")):
        completeness = 0.7
    # "..."で途切れている（トランケーション）
    if text_stripped.endswith("...") and not text_stripped.endswith("。..."):
        completeness = 0.2
    # 開き括弧が閉じていない
    open_paren = text.count("（") + text.count("「") + text.count("(")
    close_paren = text.count("）") + text.count("」") + text.count(")")
    if open_paren > close_paren:
        completeness = max(0.1, completeness - 0.3)
    # 文の数（1文だと短すぎ、10文以上だと長すぎ）
    sentences = [s for s in re.split(r'[。！？\n]', text) if len(s.strip()) > 0]
    sent_count = len(sentences)
    if sent_count == 0:
        completeness = max(0.1, completeness - 0.3)
    elif 2 <= sent_count <= 6:
        completeness = min(1.0, completeness + 0.2)

    # --- 軸4: エンゲージメント予測 (0-1, w=0.15) ---
    # 共感、問いかけ、余韻、会話のきっかけ
    engagement = 0.2  # ベースライン
    # 問いかけ
    if "？" in text or "?" in text or "かな" in text:
        engagement += 0.25
    # 余韻（三点リーダー）
    if "…" in text:
        engagement += 0.10
    # 共感ポイント（あるある、失敗談、本音吐露）
    empathy_markers = ["失敗", "やらかし", "反省", "学んだ", "気づいた",
                       "正直", "本音", "実は", "ぶっちゃけ"]
    if any(m in text for m in empathy_markers):
        engagement += 0.20
    # 具体的な行動やシーン描写
    scene_markers = ["朝", "夜", "昼", "編集室", "現場", "画面", "カメラ", "モニター"]
    if any(m in text for m in scene_markers):
        engagement += 0.10
    # CTA（明示的な呼びかけ）— SNSでは軽い方が良い
    if any(m in text for m in ["どう思う", "みんなは", "経験ある"]):
        engagement += 0.15
    engagement = min(1.0, engagement)

    # --- 軸5: AI臭さの無さ (0-1, w=0.15) ---
    ai_penalty = 0.0
    for p in AI_CLICHE_PATTERNS:
        if p in text:
            ai_penalty += 0.20
    # 追加: 過剰な丁寧語もAI臭い
    polite_excess = text.count("ます。") + text.count("です。") + text.count("ございます")
    if polite_excess >= 4:
        ai_penalty += 0.15
    # 同じ語尾の連続
    endings = re.findall(r'(?:です|ます|ません|でしょう)[。！？]', text)
    if len(endings) >= 3:
        unique_ratio = len(set(endings)) / len(endings)
        if unique_ratio < 0.5:
            ai_penalty += 0.15
    ai_score = max(0.0, 1.0 - ai_penalty)

    # --- 軸6: 読みやすさ (0-1, w=0.10) ---
    readability = 0.5
    if sentences:
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        # SNS投稿の最適文長: 15-35文字
        if 15 <= avg_len <= 35:
            readability = 0.9
        elif 10 <= avg_len <= 50:
            readability = 0.7
        elif avg_len > 80:
            readability = 0.3
        else:
            readability = 0.5
    # 改行によるリズム（SNSでは効果的）
    newline_count = text.count("\n")
    if 1 <= newline_count <= 8:
        readability = min(1.0, readability + 0.1)

    # --- 軸7: daichi_content_patterns構造準拠 (0-1, w=0.12) ---
    # Phase A: 具体的場面から入る / Phase D: 核心の一文 / Phase E: 行動宣言で終わる
    structure_score = 0.3  # ベースライン
    first_line = text.split("\n")[0] if "\n" in text else text[:80]
    last_line = text.strip().split("\n")[-1] if "\n" in text else text[-80:]

    # Phase A: 具体的な場面・体験から入るパターン（高評価）
    concrete_openers = [
        "朝", "夜", "昨日", "さっき", "今日", "先日", "この前", "あの時",
        "僕は", "私は", "自分", "正直", "ふと", "実は", "気づいた",
        "やらかした", "失敗", "壊れ", "止まっ", "動かな",
        "編集室", "画面", "モニター", "椅子", "机", "カフェ",
    ]
    if any(m in first_line for m in concrete_openers):
        structure_score += 0.25
    # 自己開示（弱さ、葛藤、失敗）が冒頭にある → ボーナス
    vulnerability_openers = ["できない", "わからな", "怖", "迷", "悩", "不安", "つら"]
    if any(m in first_line for m in vulnerability_openers):
        structure_score += 0.10
    # 抽象的AI論・一般論から入るパターン（ペナルティ）
    abstract_openers = [
        "AIは", "AI時代", "AIが", "人工知能", "テクノロジー",
        "近年", "昨今", "現代", "これからの時代",
        "〜について", "考えてみ", "注目され",
    ]
    if any(m in first_line for m in abstract_openers):
        structure_score -= 0.25

    # Phase D: 核心の一文（太字 **...** や短い断言文）
    if "**" in text:
        structure_score += 0.15  # 太字の核心文がある
    elif any(s.strip() for s in re.findall(r'(?:^|\n)(.{5,30})[。！]', text)
             if not any(w in s for w in ["です", "ます", "ました"])):
        structure_score += 0.05  # 短い断言文がある

    # Phase E: 行動宣言で終わる（「だからこうする」「次はこれをやる」）
    action_endings = [
        "する", "やる", "作る", "始める", "変える", "試す", "挑む",
        "届ける", "残す", "繋ぐ", "壊す", "直す", "進む",
    ]
    if any(last_line.rstrip("。！？…").endswith(v) for v in action_endings):
        structure_score += 0.15
    # 評論家的な締め（ペナルティ）
    passive_endings = ["でしょう", "ではないでしょうか", "と思います", "が大切です",
                       "が重要です", "が求められます"]
    if any(e in last_line for e in passive_endings):
        structure_score -= 0.15

    structure_score = max(0.0, min(1.0, structure_score))

    # --- 加重合計 ---
    score = (
        human_score * 0.17 +
        persona_score * 0.17 +
        completeness * 0.16 +
        engagement * 0.13 +
        ai_score * 0.13 +
        readability * 0.08 +
        structure_score * 0.16
    )
    score = round(max(0.0, min(1.0, score)), 3)

    # ハードフェイル: 中国語混入・名前誤読・AI自己開示 → 上限0.30
    if hard_fail:
        score = min(score, 0.30)

    return score


def _check_ai_cliche(text: str) -> bool:
    """AI定型表現が含まれていればTrue"""
    for p in AI_CLICHE_PATTERNS:
        if p in text:
            return True
    # 絵文字3個以上
    import re
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF\U00002702-\U000027B0]', text))
    if emoji_count >= 3:
        return True
    # ハッシュタグ3個以上
    if text.count('#') >= 3:
        return True
    return False


def _get_time_period(time_str: str) -> str:
    """時刻文字列→時間帯"""
    hour = int(time_str.split(":")[0])
    if 10 <= hour < 13:
        return "morning"
    elif 13 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 20:
        return "evening"
    else:
        return "night"


def _pick_theme(time_str: str, used_today: list[str], recent_themes: list[str]) -> str:
    """テーマを選択（重複回避+時間帯重み）"""
    period = _get_time_period(time_str)
    weights = TIME_THEME_WEIGHTS.get(period, {})

    # 直近7日で3回以上使われたテーマを除外
    from collections import Counter
    theme_counts = Counter(recent_themes)
    excluded = {t for t, c in theme_counts.items() if c >= 3}

    # 今日同じテーマが3回以上なら除外
    today_counts = Counter(used_today)
    for t, c in today_counts.items():
        if c >= 3:
            excluded.add(t)

    available = [t for t in THEME_POOL if t not in excluded]
    if not available:
        available = THEME_POOL.copy()

    # 重み付きランダム
    weighted = []
    for t in available:
        w = weights.get(t, 1)
        weighted.extend([t] * w)

    return random.choice(weighted)


def _random_offset_minutes() -> int:
    """0〜8分のランダムオフセット（早期投稿を避けるため正の値のみ）"""
    return random.randint(0, 8)


def _load_writing_style() -> str:
    """daichi_writing_style.md読み込み"""
    path = STRATEGY_DIR / "daichi_writing_style.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


# ===== プロンプト構築 =====

def _build_prompt(platform: str, account: str, theme: str, time_str: str,
                  writing_style: str, few_shot: list[str], recent_posts: list[str],
                  persona_hint: str = "") -> tuple[str, str]:
    """platform+accountに応じたプロンプトを構築。(system_prompt, user_prompt)を返す"""

    period = _get_time_period(time_str)
    avoid = "\n".join(f"- {p[:60]}" for p in recent_posts[:5]) if recent_posts else "（なし）"

    # daichi_content_patterns構造ガイド + NG語（全プラットフォーム共通）
    content_structure_guide = (
        "\n【投稿の構造ルール（daichi_content_patterns準拠）】\n"
        "- 冒頭は必ず具体的な場面・体験・感覚から入れ。「AIは〜」「近年〜」のような抽象的な書き出しは禁止。\n"
        "- 例: 「深夜3時、画面が止まった」「正直、怖かった」「さっきコード壊した」\n"
        "- 自己開示を恐れるな。弱さ・恐怖・葛藤・失敗を隠さない。\n"
        "- 核心は短い一文で断言。「設計なき実装の末路だった」のように切れ味良く。\n"
        "- 締めは行動宣言。「だから僕はこうする」「次はこれをやる」。評論家的な締め禁止。\n"
        "- 「ではないでしょうか」「が大切です」「が重要です」で終わるな。\n"
        "\n【使用禁止表現（生成に含めるな）】\n"
        "- 「誰でも簡単に」「絶対稼げる」「完全自動で放置」「AIに任せればOK」\n"
        "- 「最短で月100万」「革命」「覇権」「無双」\n"
        "- 「〜について考えてみました」「いかがでしょうか」「深掘り」「させていただきます」\n"
        "- 「特筆すべき」「画期的な」「注目すべきは」\n"
        "- 絵文字3個以上禁止。ハッシュタグ3個以上禁止。箇条書き連打禁止。\n"
    )

    # 事実誤認防止 + 人物像ルール（全プラットフォーム共通）
    factual_rules = (
        "\n【絶対禁止: 事実誤認・捏造】\n"
        "- 楽曲制作・音楽制作を仕事として語るな。島原大知は音楽の仕事をしていない。\n"
        "- SunoAIでの作詞は完全に個人の趣味。仕事・案件・クライアントとして語るな。\n"
        "- VTuberの楽曲制作に携わった事実はない。\n"
        "- 島原大知の本業: 映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）、VTuber業界支援、事業運営。\n"
        "- 存在しない機能・サービス・実績を捏造するな。\n"
        "- 架空の数値（○%向上、○倍改善など）を捏造するな。\n"
        "- 実際にやっていないことを「やっている」「開始した」と語るな。\n"
        "\n【島原大知の人物像（投稿に反映すべきこと）】\n"
        "- 島原は自分を全肯定しない人間。弱さ・迷い・自嘲を含めて島原大知。完璧な人間として描くな。\n"
        "- ユーモアや自虐は熱量制御。本気の温度が高すぎるため逃がしている。\n"
        "- 傷を負うと構造を見る人間。「どこが壊れたのか」から再設計に向かう。\n"
        "- 橋渡し役に徹する。スターになることを求めない。\n"
        "- 島原を「完璧なAIエンジニア」「成功した起業家」として描くな。泥臭い日常の中の閃きを書け。\n"
        "- 答えではなく問いかけ。断定より余韻。大きな野望より目の前の1人に届ける言葉。\n"
        "- 島原は「成立の人」。場の不足を自分で埋める。専門家ぶるな。\n"
        "- 一度信じた光景が壊れる条件まで知った上で、それでも作る側へ戻る人として描け。\n"
        "- 矛盾を恐れるな: 目立ちたくないのに中心になる、熱を信じつつ壊れると知っている。それが島原。\n"
        "- 島原は「証明したい人」。作品は存在の痕跡。失敗すら「残るなら価値がある」。\n"
        "- 不完全でも渡す美学。完璧より「止めずに渡す、始める、残す、繋ぐ」。\n"
        "- 安い答えを売らない。問いを持ち続ける人として書け。\n"
    )

    # 文体のゆらぎ指示（X向け: CJK=2カウントのため日本語は実質140字上限）
    if platform == "x":
        length_hint = random.choice(["15-40字の短文", "40-80字の中文", "80-130字の長文"])
    else:
        length_hint = random.choice(["30-80字の短文", "80-150字の中文", "150-280字の長文"])
    ellipsis_hint = "文末に「…」を使って余韻を残してください。" if random.random() < 0.17 else "句点「。」で終わる。"
    bracket_hint = "括弧で本音やツッコミを入れてください。" if random.random() < 0.20 else ""
    oneword_hint = "一言だけの投稿にしてください（例:「…うーん」「なるほどなぁ」）。" if random.random() < 0.05 else ""

    if platform == "x" and account == "shimahara":
        # X島原: 最もrawな声
        first_person_pool = ["自分"] * 40 + ["僕"] * 35 + ["私"] * 15 + ["俺"] * 5 + ["（一人称なし）"] * 5
        first_person = random.choice(first_person_pool)

        system_prompt = (
            "あなたは島原大知（@Sima_daichi）本人としてXに投稿する。\n"
            f"{writing_style}\n\n"
            "絶対ルール:\n"
            "- AI臭い定型表現は禁止。島原大知の声で語れ。\n"
            "- 完璧な文章にするな。推敲途中のような人間味を残せ。\n"
            "- 投稿テキストのみを出力。説明や前置きは不要。\n"
            f"{content_structure_guide}"
            f"{factual_rules}"
            f"{persona_hint}"
        )
        few_shot_text = ""
        if few_shot:
            few_shot_text = "\n\n## 島原大知の過去投稿（参考）\n" + "\n".join(f"- {t}" for t in few_shot[:5])

        user_prompt = (
            f"Xに投稿するドラフトを1つ作ってください。\n"
            f"- 日本語140字以内（Xは日本語1文字=2カウント、合計280以内）\n"
            f"- テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}（{period}）\n"
            f"- 一人称: {first_person}\n"
            f"- 長さ目安: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + bracket_hint if bracket_hint else ''}\n"
            f"{'- ' + oneword_hint if oneword_hint else ''}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"{few_shot_text}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "x" and account == "syutain":
        # X SYUTAIN: プロジェクトの声
        system_prompt = (
            "あなたはSYUTAINβ公式Xアカウント（@syutain_beta）として投稿する。\n"
            "論理・設計・分析。結論→根拠→示唆。一人称「私」。\n"
            "AI臭い定型表現は禁止。SYUTAINβとしての独自の声で語れ。\n"
            "投稿テキストのみを出力。\n"
            f"{content_structure_guide}"
            f"{factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Xに投稿するドラフトを1つ。\n"
            f"- 日本語140字以内（Xは日本語1文字=2カウント、合計280以内）。テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}。長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "bluesky":
        # Bluesky: SYUTAINβの設計思想
        system_prompt = (
            "あなたはSYUTAINβとしてBlueskyに投稿する。\n"
            "SYUTAINβの設計思想として島原大知の哲学がDNAとして反映される。\n"
            "一人称は「SYUTAINβ」or 主語なし。「僕」「自分」は使わない。\n"
            "AI臭い定型表現は禁止。投稿テキストのみを出力。\n"
            f"{content_structure_guide}"
            f"{factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Blueskyに投稿するドラフトを1つ。\n"
            f"- 300字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "threads":
        # Threads: SYUTAINβのカジュアルな声
        system_prompt = (
            "あなたはSYUTAINβとしてThreadsに投稿する。\n"
            "カジュアルで親しみやすいトーン。開発裏話、気づき、ゆるめの技術トピック。\n"
            "一人称は「SYUTAINβ」or 主語なし。「僕」「自分」は使わない。\n"
            "AI臭い定型表現は禁止。投稿テキストのみを出力。\n"
            f"{content_structure_guide}"
            f"{factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Threadsに投稿するドラフトを1つ。\n"
            f"- 500字以内。テーマ: 【{theme}】\n"
            f"- 長さ: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"投稿テキストのみを出力。"
        )
    else:
        system_prompt = "SNS投稿生成。投稿テキストのみを出力。"
        user_prompt = f"テーマ【{theme}】で投稿を1つ。テキストのみ。"

    return system_prompt, user_prompt


# ===== メインバッチ =====

async def _warmup_nemotron():
    """Nemotronコールドスタート対策: 軽量リクエスト1件"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm
        model_sel = choose_best_model_v6(task_type="classification", quality="low", local_available=True)
        await call_llm(prompt="hello", system_prompt="reply ok", model_selection=model_sel)
        logger.info("Nemotron warmup完了")
    except Exception as e:
        logger.debug(f"warmupスキップ: {e}")


# バッチ分割定義
BATCH_1_SCHEDULE = (
    [("x", "shimahara", t) for t in X_SHIMAHARA_TIMES] +
    [("x", "syutain", t) for t in X_SYUTAIN_TIMES]
)  # 10件
BATCH_2_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES[:13]]  # 前半13件
BATCH_3_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES[13:]]  # 後半13件
BATCH_4_SCHEDULE = [("threads", "syutain", t) for t in THREADS_TIMES]       # 13件


async def generate_batch(batch_name: str, schedule_items: list, target_date: datetime = None, warmup: bool = True) -> dict:
    """指定されたスケジュール分のみ生成してposting_queueにINSERT"""
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)

    if warmup:
        await _warmup_nemotron()

    return await _generate_for_schedule(schedule_items, target_date, batch_name)


async def generate_daily_sns(target_date: datetime = None) -> dict:
    """翌日分49件を一括生成しposting_queueにINSERT（後方互換）"""
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)
    all_schedule = BATCH_1_SCHEDULE + BATCH_2_SCHEDULE + BATCH_3_SCHEDULE + BATCH_4_SCHEDULE
    await _warmup_nemotron()
    return await _generate_for_schedule(all_schedule, target_date, "all")


async def _generate_for_schedule(schedule: list, target_date: datetime, batch_name: str) -> dict:
    """スケジュールリストに基づいて生成"""
    target_date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"SNS投稿生成開始 [{batch_name}]: {target_date_str} ({len(schedule)}件)")

    results = {"total": 0, "inserted": 0, "rejected": 0, "ai_cliche": 0, "by_platform": {}}

    async with get_connection() as conn:
      try:
        # 直近7日のテーマ取得
        recent_themes_rows = await conn.fetch(
            "SELECT theme_category FROM posting_queue WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        recent_themes = [r["theme_category"] for r in recent_themes_rows if r["theme_category"]]

        # 直近5投稿の内容取得（重複回避用）
        recent_posts_rows = await conn.fetch(
            "SELECT content FROM posting_queue ORDER BY created_at DESC LIMIT 5"
        )
        recent_posts = [r["content"][:60] for r in recent_posts_rows]

        # daichi_writing_style読み込み
        writing_style = _load_writing_style()

        # daichi_writing_examples取得（X島原用）
        few_shot_rows = await conn.fetch(
            "SELECT tweet_text FROM daichi_writing_examples WHERE is_high_quality = true ORDER BY engagement_score DESC LIMIT 10"
        )
        few_shot_pool = [r["tweet_text"][:200] for r in few_shot_rows]

        # persona_memoryから島原大知の価値観を取得（CLAUDE.md ルール23準拠）
        persona_hint = ""
        try:
            persona_rows = await conn.fetch(
                """SELECT content FROM persona_memory
                WHERE category IN ('philosophy', 'identity', 'value')
                ORDER BY created_at DESC LIMIT 5"""
            )
            if persona_rows:
                persona_hint = "\n【島原大知の価値観（persona_memory）】\n"
                for pr in persona_rows:
                    persona_hint += f"- {(pr['content'] or '')[:80]}\n"
        except Exception:
            pass

        # agent_contextから最新インテリジェンスを注入
        try:
            from tools.agent_context import build_agent_context
            intel_hint = await build_agent_context("sns_batch")
            if intel_hint:
                persona_hint += f"\n{intel_hint}\n"
        except Exception:
            pass

        # LLMルーター
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm
        from tools.platform_ng_check import check_platform_ng

        used_today = []
        inserted_count = 0
        # 固着検知: 直近生成のcontent先頭25文字を記録
        generated_heads = []
        # 固着カウント: 連続で重複が発生した回数
        fixation_count = 0
        # Cloud APIフォールバック中かどうか
        using_cloud_fallback = False

        for platform, account, time_str in schedule:
            results["total"] += 1

            # テーマ選択
            theme = _pick_theme(time_str, used_today, recent_themes)
            used_today.append(theme)

            # few-shot（X島原のみ）
            few_shot = random.sample(few_shot_pool, min(3, len(few_shot_pool))) if platform == "x" and account == "shimahara" else []

            # プロンプト構築
            system_prompt, user_prompt = _build_prompt(
                platform, account, theme, time_str, writing_style, few_shot, recent_posts,
                persona_hint=persona_hint,
            )

            # === モデル選択（固着時はCloud APIにフォールバック）===
            if using_cloud_fallback:
                model_sel = {
                    "provider": "deepseek", "model": "deepseek-v3.2",
                    "tier": "A", "via": "direct",
                    "note": "ローカルLLM固着→Cloud APIフォールバック",
                }
            else:
                model_sel = choose_best_model_v6(
                    task_type="sns_draft", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )

            # === 自律品質管理パイプライン ===
            # Phase 1: 生成（最大3回リトライ、ローカルLLMにはtemperature+repeat_penalty）
            # Phase 2: 検証（NGワード/文字数/重複/AI臭さ/品質スコア）
            # Phase 3: 不合格→Cloud APIフォールバック（1回）
            # Phase 4: 2段階精錬

            draft = ""
            quality = 0.0
            model_used = model_sel.get("model", "unknown")

            for phase in ["local", "cloud_fallback"]:
                if phase == "cloud_fallback" and (using_cloud_fallback or model_sel.get("provider") != "local"):
                    break  # 既にCloudなのでスキップ

                current_sel = model_sel if phase == "local" else {
                    "provider": "deepseek", "model": "deepseek-v3.2",
                    "tier": "A", "via": "direct",
                    "note": "品質検証不合格→Cloud APIフォールバック",
                }

                for attempt in range(3):
                    try:
                        # ローカルLLMの場合: temperature高め + repeat_penalty で固着防止
                        llm_kwargs = {}
                        if current_sel.get("provider") == "local":
                            llm_kwargs["temperature"] = 1.1 + (attempt * 0.1)  # 1.1→1.2→1.3
                            llm_kwargs["repeat_penalty"] = 1.3
                            llm_kwargs["seed"] = random.randint(1, 999999)

                        result = await call_llm(
                            prompt=user_prompt,
                            system_prompt=system_prompt,
                            model_selection=current_sel,
                            **llm_kwargs,
                        )
                        draft = result.get("text", "").strip()
                        model_used = current_sel.get("model", "unknown")

                        # === Phase 2: 自律検証パイプライン ===

                        # 検証1: 空/短すぎ
                        if not draft or len(draft) < 10:
                            draft = ""
                            continue

                        # 検証2: 文字数制限（Xは加重カウント: CJK=2）
                        if platform == "x" and _count_x_chars(draft) > 280:
                            draft = _truncate_for_x(draft, 280)
                        elif platform == "bluesky" and len(draft) > 300:
                            draft = draft[:297] + "..."
                        elif platform == "threads" and len(draft) > 500:
                            draft = draft[:497] + "..."

                        # 検証3: NGワードチェック
                        ng_result = check_platform_ng(draft, platform)
                        if not ng_result["passed"]:
                            logger.warning(f"NGワード検出 ({platform}/{time_str}): {ng_result['violations']}")
                            draft = ""
                            continue

                        # 検証4: AI定型表現チェック
                        if _check_ai_cliche(draft):
                            results["ai_cliche"] += 1
                            draft = ""
                            continue

                        # 検証5: 重複チェック（先頭25文字が既出なら拒否）
                        draft_head = draft[:25]
                        is_duplicate = any(draft_head in h for h in generated_heads) or \
                                       any(draft_head in p for p in recent_posts)
                        if is_duplicate:
                            fixation_count += 1
                            logger.warning(f"重複検出 ({platform}/{time_str}): fixation_count={fixation_count}")
                            draft = ""
                            # 固着検知: 連続3回重複→このバッチ残り全てCloud APIに切替
                            if fixation_count >= 3 and not using_cloud_fallback:
                                using_cloud_fallback = True
                                logger.warning("ローカルLLM固着検知→残りのバッチをCloud API(DeepSeek V3.2)にフォールバック")
                                try:
                                    from tools.event_logger import log_event
                                    await log_event("sns.llm_fixation", "sns", {
                                        "fixation_count": fixation_count,
                                        "fallback_to": "deepseek-v3.2",
                                        "remaining_items": results["total"] - inserted_count,
                                    }, severity="warning")
                                except Exception:
                                    pass
                            continue

                        # 検証6: 品質スコア（0.50未満は却下、0.50-0.59は精錬で改善を試みる）
                        quality = _score_multi_axis(draft, persona_keywords=_PERSONA_KEYWORDS)
                        if quality < 0.50:
                            draft = ""
                            continue

                        # 全検証通過 → 固着カウントリセット
                        fixation_count = max(0, fixation_count - 1)
                        break

                    except Exception as e:
                        logger.warning(f"SNS生成失敗 ({platform}/{account}/{time_str}): {e}")
                        draft = ""
                        break

                if draft:
                    break  # 合格したのでphaseループを抜ける

            # === Phase 4: 2段階精錬 ===
            if draft and quality >= 0.50:
                try:
                    refine_sel = choose_best_model_v6(
                        task_type="sns_draft", quality="medium",
                        budget_sensitive=True, needs_japanese=True,
                    )
                    refine_kwargs = {}
                    if refine_sel.get("provider") == "local":
                        refine_kwargs["temperature"] = 0.9
                        refine_kwargs["repeat_penalty"] = 1.2

                    refine_result = await call_llm(
                        prompt=f"以下のSNS投稿文を、より自然で人間味のある文体に書き直してください。AI臭い表現を除去し、三点リーダーや短い文のリズムを取り入れてください。内容は変えず、表現だけ改善してください。\n\n{draft}",
                        system_prompt="島原大知の文体で書き直すライター。一人称は元の文に合わせる。投稿テキストのみ出力。",
                        model_selection=refine_sel,
                        **refine_kwargs,
                    )
                    refined = refine_result.get("text", "").strip()
                    if refined and len(refined) >= 10:
                        # 長さ制限
                        if platform == "x" and _count_x_chars(refined) > 280:
                            refined = _truncate_for_x(refined, 280)
                        elif platform == "bluesky" and len(refined) > 300:
                            refined = refined[:297] + "..."
                        elif platform == "threads" and len(refined) > 500:
                            refined = refined[:497] + "..."
                        # NGチェック（精錬後にNGワードが入る可能性）
                        ng_refined = check_platform_ng(refined, platform)
                        if ng_refined["passed"]:
                            refined_quality = _score_multi_axis(refined, persona_keywords=_PERSONA_KEYWORDS)
                            if refined_quality > quality:
                                # content_edit_logに精錬記録
                                try:
                                    await conn.execute(
                                        """INSERT INTO content_edit_log
                                           (content_type, original_text, edited_text, model_used,
                                            quality_score_before, quality_score_after)
                                           VALUES ($1, $2, $3, $4, $5, $6)""",
                                        f"sns_{platform}", draft[:500], refined[:500],
                                        refine_sel.get("model", "unknown"),
                                        quality, refined_quality,
                                    )
                                except Exception:
                                    pass
                                draft = refined
                                quality = refined_quality
                except Exception:
                    pass  # 精錬失敗時は元のdraftを使用

            if not draft:
                results["rejected"] += 1
                continue

            # scheduled_atにランダムオフセット
            hour, minute = map(int, time_str.split(":"))
            offset_min = _random_offset_minutes()
            scheduled = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            scheduled += timedelta(minutes=offset_min)

            # 品質スコアに基づく承認判定（CLAUDE.md ルール11準拠、品質0.75以上で自動承認）
            if quality >= 0.75:
                post_status = "pending"  # 投稿キューへ（自動承認基準クリア）
            elif quality >= 0.60:
                post_status = "pending_review"  # 0.60-0.74は人間レビュー待ち
                results.setdefault("pending_review", 0)
                results["pending_review"] += 1
                logger.info(f"SNS投稿レビュー待ち: 品質{quality:.2f} ({platform}/{account})")
            else:
                post_status = "rejected"  # 品質不足で却下
                results["rejected"] += 1
                logger.info(f"SNS投稿却下: 品質{quality:.2f} ({platform}/{account})")
                # 却下投稿もDBに保存（監査証跡）
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    platform, account, draft, scheduled, post_status, quality, theme,
                )
                continue

            # posting_queueにINSERT
            await conn.execute(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                platform, account, draft, scheduled, post_status, quality, theme,
            )
            inserted_count += 1

            # 直近投稿リスト更新（重複検知用）
            recent_posts.insert(0, draft[:60])
            if len(recent_posts) > 15:
                recent_posts = recent_posts[:15]
            generated_heads.append(draft[:25])

            # プラットフォーム別カウント
            key = f"{platform}/{account}"
            results["by_platform"][key] = results["by_platform"].get(key, 0) + 1

        results["inserted"] = inserted_count
        results["cloud_fallback"] = using_cloud_fallback
        results["fixation_detected"] = fixation_count
        logger.info(
            f"SNS投稿生成完了: {inserted_count}/{results['total']}件 "
            f"(却下{results['rejected']}, AI臭{results['ai_cliche']}, "
            f"固着検知{fixation_count}, Cloud fallback={'有' if using_cloud_fallback else '無'})"
        )

      except Exception as e:
        logger.error(f"SNS一括生成エラー: {e}")
        results["error"] = str(e)

    return results
