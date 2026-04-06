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
from tools.content_redactor import redact_content, is_safe_to_publish


def _safe_fire(coro):
    """fire-and-forget with exception logging"""
    t = asyncio.ensure_future(coro)
    t.add_done_callback(
        lambda _t: logger.error(f"バックグラウンド例外: {_t.exception()}")
        if not _t.cancelled() and _t.exception() else None
    )
    return t

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"

# ===== スケジュール定義 =====

# 2026-04-07 拡散実行書に基づく投稿数: 21本/日 (旧49本から削減、量より質)
# X shimahara 5 / X syutain 5 / Bluesky 5 / Threads 5 / note 1(別パイプライン)
# 最低2時間間隔で分散
X_SHIMAHARA_TIMES = ["09:00", "12:00", "15:00", "18:00", "21:00"]
X_SYUTAIN_TIMES = ["09:30", "11:00", "12:30", "14:30", "16:00", "18:00", "20:00", "22:00"]
BLUESKY_TIMES = ["09:00", "10:15", "11:30", "12:45", "14:00", "15:30", "17:00", "18:30", "20:00", "21:30"]
THREADS_TIMES = ["09:30", "11:30", "13:30", "15:30", "17:30", "19:30", "21:30"]

# ===== テーマプール =====

# 旧抽象テーマプール → 拡散実行書の5カテゴリに準拠した具体テーマに変更 (2026-04-07)
# テーマエンジン (strategy/sns_theme_engine.py) が動的テーマを生成するが、
# フォールバック時にここが使われるので具体的にしておく
THEME_POOL = [
    "SYUTAINβの直近24時間で起きた具体的な出来事",
    "Grok X検索で見つけた最新AI動向（具体的なURL付き）",
    "映像制作×AI: 具体的なツール名と使用体験",
    "VTuber業界のAI活用: 具体的な事例",
    "ドローン/写真とAIの組み合わせ: 実体験ベース",
    "Build in Public: 今週の具体的な数字と変化",
    "非エンジニアがAIエージェントを使う時の具体的な壁",
    "SYUTAINβのコスト分析: 具体的な金額と内訳",
    "広告/マーケティング業界のAI活用: 具体的な動向",
    "個人事業×AI自動化: 何を委譲して何を握るか",
    "今週SYUTAINβが自動修正した具体的なバグ",
    "SYUTAINβの設計判断: 具体的なトレードオフ",
]

# テーマ別ハッシュタグ（プラットフォーム別、最大2個）
THEME_HASHTAGS = {
    "AI技術": {"x": ["#AI開発", "#個人開発"], "threads": ["#AI", "#テック", "#個人開発", "#自動化", "#AIエージェント"]},
    "開発進捗": {"x": ["#SYUTAINβ", "#AI開発"], "threads": ["#AI", "#開発記録", "#非エンジニア", "#個人開発", "#BuildInPublic"]},
    "VTuber業界": {"x": ["#VTuber"], "threads": ["#VTuber", "#クリエイター", "#映像制作", "#エンタメ", "#配信"]},
    "哲学/思考": {"x": [], "threads": ["#思考", "#エッセイ", "#AI時代", "#働き方", "#自己成長"]},
    "ビジネス": {"x": ["#AI事業"], "threads": ["#ビジネス", "#AI活用", "#起業", "#フリーランス", "#副業"]},
    "映画/映像": {"x": ["#映像制作"], "threads": ["#映像", "#クリエイター", "#VFX", "#動画編集", "#カラグレ"]},
    "業界批評": {"x": ["#AI"], "threads": ["#AI", "#テック", "#業界分析", "#トレンド", "#テクノロジー"]},
    "自己内省": {"x": [], "threads": ["#エッセイ", "#日記", "#振り返り", "#成長", "#挑戦"]},
    "日常": {"x": [], "threads": ["#日常", "#フリーランス", "#クリエイター"]},
    "音楽/趣味": {"x": [], "threads": ["#趣味", "#SunoAI", "#作詞"]},
    "カメラ/写真": {"x": ["#写真"], "threads": ["#カメラ", "#写真", "#撮影"]},
    "雑談": {"x": [], "threads": ["#雑談", "#つぶやき"]},
}

# 時間帯別テーマ重み
TIME_THEME_WEIGHTS = {
    "morning": {"ビジネス": 3, "AI技術": 2, "開発進捗": 2},
    "afternoon": {"日常": 2, "雑談": 2, "カメラ/写真": 1},
    "evening": {"AI技術": 2, "映画/映像": 2, "開発進捗": 2},
    "night": {"哲学/思考": 3, "自己内省": 2, "VTuber業界": 2},
}

# === プラットフォーム別品質閾値（Strategy: 平台固有の特性に合わせた閾値） ===
# Blueskyは短文のため persona_score / structure_score が低くなりやすい
# Threadsはカジュアルなため完結性スコアが低くなりやすい
PLATFORM_QUALITY_THRESHOLDS = {
    "x": 0.68,        # X: 高品質要求（ブランド直結）
    "bluesky": 0.62,  # Bluesky: 短文のためスコアが構造的に低い
    "threads": 0.64,  # Threads: カジュアル寄り
}
DEFAULT_QUALITY_THRESHOLD = 0.70

# === テーマ品質追跡（Strategy: 低品質テーマの回避） ===
# バッチ実行中にテーマ×プラットフォームの品質を追跡
# { (theme, platform): [score1, score2, ...] }
_theme_quality_tracker: dict[tuple[str, str], list[float]] = {}

# ===== AI定型表現チェック =====

# 拡散実行書 NGリスト + AI定型表現
AI_CLICHE_PATTERNS = [
    "について考えてみました", "いかがでしょうか", "ではないでしょうか",
    "皆さん、こんにちは", "みなさん、こんにちは", "それでは、また",
    "を深掘り", "についてまとめてみました", "のポイントは3つ",
    "させていただきます", "特筆すべき", "画期的な", "注目すべき",
    "それでは早速", "見ていきましょう", "ご紹介します",
]

# 拡散実行書「表の発信で絶対にやらないこと」(2026-04-07)
DIFFUSION_NG_PATTERNS = [
    "神話", "デジタル遺伝子", "突然変異エンジン",     # 内部用語を表で使わない
    "異端者", "異端児",                                # 自称禁止
    "月100万", "月収100万", "100万円",                # 看板禁止
    "コード書けないおっさん", "おっさん",              # 弱者描写禁止
    "これはドキュメンタリーです",                      # 説明禁止
    "AIすごい", "AIって凄い", "AIの未来は",            # 抽象論禁止
    "未来はこうなる", "これからの時代",                # 抽象論禁止
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


def _truncate_for_x(text: str, limit: int = 150) -> str:
    """日本語150文字以内で切り詰め（文末で自然に切る）"""
    if len(text) <= limit:
        return text
    # 文末（。！？…）で切れるポイントを探す
    candidates = []
    for i, ch in enumerate(text[:limit]):
        if ch in "。！？…\n":
            candidates.append(i + 1)
    if candidates:
        # 最後の文末で切る
        cut = candidates[-1]
        if cut >= limit * 0.5:  # 半分以上あれば採用
            return text[:cut].rstrip()
    # 文末が見つからない場合は150字で切って「…」
    return text[:limit - 1].rstrip() + "…"


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

    # 繰り返しポエムパターン検出（スコア上限0.30）
    # 部分一致で検出（「風が止み」「風はもう止んだ」「風は止んだ」等のバリエーション全て捕捉）
    import re as _re
    _overused_poem_patterns = [
        _re.compile(r"風[がはも]*[とう]*[に]*(止[みんまっ]|やん)"),  # 風が止み, 風はもう止んだ, etc
        _re.compile(r"画面[はが]*真っ[暗黒]"),  # 画面は真っ暗, 画面は真っ黒
        _re.compile(r"息を[殺ひ]"),  # 息を殺し, 息をひそめ
        _re.compile(r"カット[はがも]*[続まつ]"),  # カットは続いて, カットが続く
        _re.compile(r"光の粒子"),
        _re.compile(r"指先[をにで]"),  # 指先を伸ばす, 指先に光
        _re.compile(r"紡[ぎぐ]"),  # 紡ぎ出す, 紡ぐ
        _re.compile(r"肩を[落お]"),  # 肩を落とし
        _re.compile(r"カラーグレーディング"),
        _re.compile(r"シャッター[をに]"),
        _re.compile(r"夕暮れ.{0,5}デスク"),
        _re.compile(r"湯気.{0,10}(コーヒー|カップ|冷め)"),
        _re.compile(r"静かに.{0,5}(光|息|待|点滅|降り)"),
        _re.compile(r"未完成の.{0,5}(シナリオ|映像|カット)"),
        # 2026-04-05追加: ドローン/赤文字/緊急停止系のポエム
        _re.compile(r"ドローン.{0,15}(プロペラ|地面|止ま|動かな|着陸|降り|静か)"),
        _re.compile(r"赤[いくでで]*文字"),
        _re.compile(r"\d+回[目も]?.{0,10}(強制|緊急|シャットダウン|停止|再起動)"),
        _re.compile(r"空[はが].{0,10}(真っ[暗黒]|紺|暗|夜|静か)"),
        _re.compile(r"誰もいな[いく]"),
        _re.compile(r"バッテリー.{0,5}(切れ|落ち|消え)"),
        _re.compile(r"プロペラ.{0,10}(止|動かな)"),
        _re.compile(r"画面[にはが].{0,10}(エラー|ログ|流れ)"),
    ]
    _poem_hits = sum(1 for p in _overused_poem_patterns if p.search(text))
    if _poem_hits >= 2:
        hard_fail = True

    # --- 軸1: 人間味 (0-1, w=0.17) ---
    # 口語表現、感情語、不完全さ、独白感が高評価
    human_score = 0.35  # ベースライン（0.3→0.35: 日本語の普通の文でも最低限の人間味あり）
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

    # --- 軸2: 島原大知/SYUTAINβらしさ (0-1, w=0.17) ---
    persona_score = 0.25  # ベースライン（0.1→0.25: キーワード0でも文脈的にペルソナ関連の可能性）
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

    # --- 軸4: エンゲージメント予測 (0-1, w=0.13) ---
    # 共感、問いかけ、余韻、会話のきっかけ
    engagement = 0.30  # ベースライン（0.2→0.30: SNS投稿は本質的にエンゲージメント志向）
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

    # --- 軸7: daichi_content_patterns構造準拠 (0-1, w=0.16) ---
    # Phase A: 具体的場面から入る / Phase D: 核心の一文 / Phase E: 行動宣言で終わる
    structure_score = 0.35  # ベースライン（0.3→0.35: 構造パターンに完全一致しなくても基本的な構造はある）
    first_line = text.split("\n")[0] if "\n" in text else text[:80]
    last_line = text.strip().split("\n")[-1] if "\n" in text else text[-80:]

    # Phase A: 具体的な事実・体験から入るパターン（高評価）
    # 注意: 情景語（朝/夜/画面/モニター/椅子/机/カフェ/編集室）は削除 — ポエム誘発語のため
    concrete_openers = [
        "昨日", "さっき", "今日", "先日", "この前",
        "僕は", "私は", "自分", "正直", "ふと", "実は", "気づいた",
        "やらかした", "失敗", "壊れ", "止まっ", "動かな",
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
    # === 軸8: 事実密度 (0-1, w=0.20) — ポエム化の構造的防止 ===
    # 具体的な数字・固有名詞・SYUTAINβ実イベント用語の含有を評価
    import re as _re_fd
    # 数字（半角・全角）
    numbers = _re_fd.findall(r'\d+', text)
    numbers_fullwidth = _re_fd.findall(r'[0-9]+', text)
    number_count = len(numbers) + len(numbers_fullwidth)
    # 固有名詞（英数字3文字以上、カタカナ3文字以上、システム用語）
    english_entities = set(_re_fd.findall(r'[A-Za-z][A-Za-z0-9_.\-]{2,}', text))
    system_terms = [
        "SYUTAINβ", "SYUTAIN", "Claude", "GPT", "Qwen", "DeepSeek", "Ollama",
        "CORTEX", "FANG", "NERVE", "FORGE", "MEDULLA", "SCOUT",
        "ALPHA", "BRAVO", "CHARLIE", "DELTA",
        "LoopGuard", "Discord", "Bluesky", "Threads", "note",
        "PostgreSQL", "NATS", "Tailscale", "Playwright", "Python",
        "intel_items", "posting_queue", "persona_memory",
    ]
    system_term_count = sum(1 for t in system_terms if t in text)
    # 円/¥/円マーク付き金額
    money_count = len(_re_fd.findall(r'[¥￥]\s*\d+|\d+\s*円', text))

    fact_density_score = 0.1  # ベースライン（最低）
    if number_count >= 3: fact_density_score += 0.35
    elif number_count >= 2: fact_density_score += 0.25
    elif number_count >= 1: fact_density_score += 0.15
    if system_term_count >= 3: fact_density_score += 0.30
    elif system_term_count >= 2: fact_density_score += 0.20
    elif system_term_count >= 1: fact_density_score += 0.10
    if money_count >= 1: fact_density_score += 0.15
    fact_density_score = min(1.0, fact_density_score)

    # === 軸9: 情景密度ペナルティ — 情景語の過剰使用を検出 ===
    scene_words = [
        "光", "影", "闇", "静か", "紺", "深夜", "空", "風", "雲",
        "プロペラ", "ドローン", "カメラ", "画面", "モニター",
        "デスク", "椅子", "机", "カフェ", "窓", "扉",
    ]
    scene_hits = sum(text.count(w) for w in scene_words)
    scene_density = scene_hits / max(1, len(text) / 30)  # 30字あたりの情景語数
    # 情景密度が高く、事実密度が低い → ポエム確定
    if scene_density > 0.5 and fact_density_score < 0.3:
        hard_fail = True

    # 重み配分: fact_density最大(0.20)、structure/human/persona各0.14、completeness 0.14、engagement/ai各0.10、readability 0.04
    score = (
        fact_density_score * 0.20 +
        structure_score * 0.14 +
        human_score * 0.14 +
        persona_score * 0.14 +
        completeness * 0.14 +
        engagement * 0.10 +
        ai_score * 0.10 +
        readability * 0.04
    )
    score = round(max(0.0, min(1.0, score)), 3)

    # ハードフェイル: 中国語混入・名前誤読・AI自己開示・情景過剰 → 上限0.30
    if hard_fail:
        score = min(score, 0.30)

    return score


def _check_ai_cliche(text: str) -> bool:
    """AI定型表現が含まれていればTrue"""
    for p in AI_CLICHE_PATTERNS:
        if p in text:
            return True
    # 拡散実行書 NG パターン (2026-04-07)
    for p in DIFFUSION_NG_PATTERNS:
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
    # 拡散実行書の品質基準: 抽象論・ポエム・自虐・システム紹介型は却下
    # 具体的な数字/出来事/学び/問い の最低1つが必要
    has_number = bool(re.search(r'\d{2,}', text))  # 2桁以上の数字
    has_concrete = bool(re.search(r'¥[\d,]+|[\d,]+円|[\d,]+行|[\d,]+回|[\d,]+件|[\d,]+日|[\d.]+%', text))
    has_question = text.rstrip().endswith('？') or '？' in text
    if not (has_number or has_concrete or has_question):
        # 数字も問いもない = 抽象論の可能性。ただし短文(80字未満)は除外
        if len(text) >= 80:
            return True
    return False


async def _check_sns_factual(content: str, platform: str = "", account: str = "") -> tuple[bool, str]:
    """事実誤認・禁止表現・パターン固着を検出する。
    Returns (passed, reason). passedがFalseの場合、投稿を再生成すべき。
    """
    # --- 禁止表現チェック ---
    forbidden = [
        ("コードを書", "島原はコードを書けない非エンジニア"),
        ("コードを打", "島原はコードを打てない非エンジニア"),
        ("プログラミング", "島原はプログラミングしない"),
        ("コーディング", "島原はコーディングしない"),
        ("再コンパイル", "島原はコンパイル作業をしない"),
        ("コンパイル", "島原はコンパイルしない"),
        ("デバッグして", "島原はデバッグ作業をしない（SYUTAINβがやる）"),
        ("僕の音楽", "音楽は趣味であり仕事ではない"),
        ("曲を作", "音楽制作は趣味であり仕事ではない"),
        ("作曲", "作曲は仕事ではない"),
        ("メロディーを紡", "音楽表現は禁止"),
    ]
    for phrase, reason in forbidden:
        if phrase in content:
            return False, f"禁止表現検出: 「{phrase}」— {reason}"

    # --- 島原アカウントでの一人称「私」チェック ---
    # X島原の投稿で「私」が使われていたら拒否（「私」はSYUTAINβの一人称）
    if account == "shimahara" and "私" in content:
        # 「私」が引用や他者の言葉の中にある可能性を考慮
        # ただし単純に含まれていたら拒否（安全側に倒す）
        return False, "島原の一人称は「僕」「自分」。「私」はSYUTAINβの一人称"

    # --- 「深夜」パターン固着チェック ---
    if content.strip().startswith("深夜"):
        try:
            async with get_connection() as conn:
                recent_rows = await conn.fetch(
                    """SELECT content FROM posting_queue
                       WHERE platform = $1 AND status IN ('pending', 'posted')
                         AND created_at > NOW() - INTERVAL '3 days'
                       ORDER BY created_at DESC LIMIT 30""",
                    platform or "x",
                )
                if recent_rows:
                    shinya_count = sum(
                        1 for r in recent_rows
                        if (r["content"] or "").strip().startswith("深夜")
                    )
                    ratio = shinya_count / len(recent_rows)
                    if ratio > 0.30:
                        return False, f"「深夜」開始のパターン固着（直近{len(recent_rows)}件中{shinya_count}件={ratio:.0%}）"
        except Exception as e:
            logger.debug(f"深夜パターンチェックDB失敗（続行）: {e}")

    return True, ""


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


def _pick_theme(time_str: str, used_today: list[str], recent_themes: list[str],
                 platform: str = "", historical_quality: dict[str, float] = None,
                 engagement_weights: dict[str, float] = None) -> str:
    """テーマを選択（重複回避+時間帯重み+品質フィードバック+エンゲージメント重み）

    Args:
        historical_quality: テーマ→平均品質スコアの辞書（過去7日のDB実績）
        engagement_weights: テーマ→エンゲージメント重み倍率（1.0=平均、2.0=高パフォ）
    """
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

    # バッチ内でアンダーパフォームしているテーマを除外
    if platform:
        for t in THEME_POOL:
            if _is_theme_underperforming(t, platform):
                excluded.add(t)

    available = [t for t in THEME_POOL if t not in excluded]
    if not available:
        available = THEME_POOL.copy()

    # 重み付きランダム（時間帯重み + 品質フィードバック重み + エンゲージメント重み）
    weighted = []
    threshold = _get_quality_threshold(platform) if platform else DEFAULT_QUALITY_THRESHOLD
    for t in available:
        w = weights.get(t, 1)
        # 過去の品質データに基づく重み調整
        if historical_quality and t in historical_quality:
            avg_q = historical_quality[t]
            if avg_q >= threshold + 0.05:
                w = int(w * 2)   # 高品質テーマは重みを2倍
            elif avg_q < threshold - 0.05:
                w = max(1, w - 1)  # 低品質テーマは重みを減らす
        # エンゲージメント実績に基づく重み調整
        if engagement_weights and t in engagement_weights:
            eng_mult = engagement_weights[t]
            w = max(1, int(w * eng_mult))
        weighted.extend([t] * w)

    return random.choice(weighted)


def _random_offset_minutes() -> int:
    """0〜8分のランダムオフセット（早期投稿を避けるため正の値のみ）"""
    return random.randint(0, 8)


def _get_quality_threshold(platform: str) -> float:
    """プラットフォーム別の品質閾値を返す"""
    return PLATFORM_QUALITY_THRESHOLDS.get(platform, DEFAULT_QUALITY_THRESHOLD)


def _track_theme_quality(theme: str, platform: str, score: float) -> None:
    """テーマ×プラットフォームの品質スコアを記録（バッチ内追跡）"""
    key = (theme, platform)
    if key not in _theme_quality_tracker:
        _theme_quality_tracker[key] = []
    _theme_quality_tracker[key].append(score)


def _is_theme_underperforming(theme: str, platform: str) -> bool:
    """このバッチ内でテーマが低品質を連続しているか判定"""
    key = (theme, platform)
    scores = _theme_quality_tracker.get(key, [])
    if len(scores) < 2:
        return False
    # 直近2回とも閾値未満ならアンダーパフォーム
    threshold = _get_quality_threshold(platform)
    return all(s < threshold for s in scores[-2:])


async def _load_historical_theme_quality(conn, platform: str) -> dict[str, float]:
    """過去7日のテーマ×プラットフォーム別の平均品質スコアをDBから取得"""
    try:
        rows = await conn.fetch(
            """SELECT theme_category, AVG(quality_score) as avg_score,
                      COUNT(*) as cnt
               FROM posting_queue
               WHERE platform = $1
                 AND created_at > NOW() - INTERVAL '7 days'
                 AND quality_score > 0
               GROUP BY theme_category
               HAVING COUNT(*) >= 3""",
            platform,
        )
        return {r["theme_category"]: float(r["avg_score"]) for r in rows if r["theme_category"]}
    except Exception as e:
        logger.debug(f"テーマ品質履歴取得失敗: {e}")
        return {}


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
                  persona_hint: str = "", factbook_prompt: str = "",
                  picked_facts: list = None, buzz_prompt: str = "") -> tuple[str, str]:
    """platform+accountに応じたプロンプトを構築。(system_prompt, user_prompt)を返す"""

    period = _get_time_period(time_str)
    avoid = "\n".join(f"- {p[:60]}" for p in recent_posts[:5]) if recent_posts else "（なし）"

    # ファクトブック注入 — ポエム化防止の核心
    # LLMに「具体的な事実・数字・固有名詞」を材料として強制的に渡す
    fact_injection = ""
    if factbook_prompt:
        fact_injection = (
            f"\n\n## 【材料】以下の事実を核にせよ\n"
            f"{factbook_prompt}\n"
            f"**上記の事実から最低1つを核にする。数字・固有名詞を本文に必ず含めよ。**\n"
            f"**ただし羅列ではなく、下のボイスガイドに従って味付けすること。**\n"
        )

    # プラットフォーム別ボイスガイド注入（事実を各SNSの性質に合わせて料理する）
    voice_injection = ""
    try:
        from strategy.sns_platform_voices import build_voice_prompt
        voice_injection = "\n\n" + build_voice_prompt(platform, account)
    except Exception:
        pass

    # バズ・トレンド注入（参考素材、関連あれば取り入れる）
    buzz_injection = ""
    if buzz_prompt:
        buzz_injection = f"\n\n{buzz_prompt}"

    # daichi_content_patterns構造ガイド + NG語（全プラットフォーム共通）
    content_structure_guide = (
        "\n【投稿の構造ルール（daichi_content_patterns準拠）】\n"
        "- 冒頭は毎回異なるパターンで入れ（同じ導入は禁止）。以下からランダムに選べ:\n"
        "  A) 具体的な数字から入る（例:「54,155行。全部AIが書いた。僕はゼロ行」「月987円のサーバー4台で20体のAIが動いてる」「1日20回デプロイした。壊れたの3回」）\n"
        "  B) 実際に起きたトラブルから入る（例:「schedulerが2重起動してた。3日間誰も気づかなかった」「deepseekのreasoningパラメータが間違ってて全botが沈黙した」「Discord botが朝9時に全員落ちた。原因はタイムゾーン」）\n"
        "  C) 自分の体験を断言（例:「設計書25回書き直した。まだ直す」「さっきClaude Codeがコード壊した。直すのもClaude Code」「コード読めないのにコードレビューしてる矛盾」）\n"
        "  D) 運用の生々しい瞬間（例:「朝5時、Slackにアラート6件」「CORTEXのheartbeatが10分止まった。MEDULLAが代理CEOになった」「Ollamaのメモリが溢れてqwen3.5が応答しなくなった」）\n"
        "- **絶対禁止フレーズ（含むと自動リジェクト）**: 「風+止」「画面は真っ暗/黒」「息を殺」「光の粒子」「指先を伸ばす」「肩を落とし」「紡ぐ」「夕暮れ+デスク」「湯気+コーヒー/カップ」「静かに+光/息」「未完成の+シナリオ/映像」「ドローンのプロペラ」「赤文字/赤い文字」「N回目の緊急シャットダウン/強制停止」「空は真っ暗/紺」「誰もいない」「バッテリーが切れ」「画面にエラーログが流れ」。\n"
        "- **絶対禁止**: 映像制作メタファーの抽象ポエム全般。「デスクで光が〜」「画面が静かに〜」系は全てリジェクト。\n"
        "- **絶対禁止**: 情景描写・雰囲気描写で始まる投稿。「朝の光が〜」「夜の静寂の中〜」「モニターの明かりだけが〜」は全てリジェクト。\n"
        "- **必須**: 具体的な事実・数字・体験だけを書け。SYUTAINβの実際のイベント（エラー、修正、数値変化、bot名、ツール名）を使え。\n"
        "- 「AIは〜」「近年〜」のような抽象的な書き出しも禁止。\n"
        "- 良い例: 「FANGのKPIレポートが毎晩21時に届く。CSO気取りのbot」「note記事の品質ゲート4段階ある。機械チェック15項目→外部検索→Haiku→GPT。それでも漏れる」「非エンジニアがAIに全コード書かせてGitHub公開した。怖い」\n"
        "- 悪い例: 「深夜3時、画面が止まった」「正直、怖かった」「光が差した」←情景ポエムは禁止\n"
        "- 自己開示を恐れるな。弱さ・恐怖・葛藤・失敗を隠さない。ただしポエムではなく事実で語れ。\n"
        "- 核心は短い一文で断言。「原因はタイムゾーンだった」「設計書が間違ってた」のように具体的に。\n"
        "- 締めは行動宣言か具体的な次のアクション。「だからLoopGuard 9層にした」「次はNATS導入する」。評論家的な締め禁止。\n"
        "- 「ではないでしょうか」「が大切です」「が重要です」で終わるな。\n"
        "\n【使用禁止表現（生成に含めるな）】\n"
        "- 「誰でも簡単に」「絶対稼げる」「完全自動で放置」「AIに任せればOK」\n"
        "- 「最短で月100万」「革命」「覇権」「無双」\n"
        "- 「〜について考えてみました」「いかがでしょうか」「深掘り」「させていただきます」\n"
        "- 「特筆すべき」「画期的な」「注目すべきは」\n"
        "- 絵文字3個以上禁止。ハッシュタグ3個以上禁止。箇条書き連打禁止。\n"
        "- 情景描写ポエム全般: 「〜が光る」「〜が静まる」「〜の向こうに」「〜が揺れる」\n"
    )

    # 事実誤認防止 + 人物像ルール（全プラットフォーム共通）
    factual_rules = (
        "\n## 島原大知の事実（絶対厳守）:\n"
        "- コードを一行も書けない非エンジニア\n"
        "- 本業は映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）\n"
        "- VTuber業界に8年間関わった（業界支援。VTuber活動はしていない）\n"
        "- SYUTAINβを開発中（AIエージェントと共に）\n"
        "- SunoAIでの作詞は完全に趣味（仕事として語るな）\n"
        "- 一人称は「僕」または「自分」\n"
        "\n## 絶対禁止表現:\n"
        "- 「コードを書く」「コーディング」「プログラミングする」→ 島原はコードを書けない\n"
        "- 「僕の音楽」「曲を作る」「メロディーを紡ぐ」→ 音楽は趣味\n"
        "- 「深夜、コードが〜」で始まるポエム → ワンパターン禁止\n"
        "- 意味のない抽象的ポエム → 具体的な情報や体験を含めること\n"
        "- 情景描写（夕暮れ、コーヒー、光、静寂、風）→ 事実・数字・固有名詞で語れ\n"
        "\n## 島原大知の思考特性（投稿のトーンに反映）:\n"
        "- 物事の裏側の構造を見る。仕組み・依存関係・ボトルネックを読み取る視点\n"
        "- 壮大なビジョンに「それを実現するには具体的に何が必要か」を問う\n"
        "- 技術の話でも必ず「人」に帰着。数字の向こうの人間の営みを見る\n"
        "- 自分の感情に正直。取り繕わない。それは現状認識の精度を上げるため\n"
        "- 不確実性への鋭敏な感覚。それでも構造を組み火を灯し続ける意志\n"
        "\n## 投稿内容のルール:\n"
        "- 毎回異なるテーマ・構造で投稿する（同じパターンの繰り返し禁止）\n"
        "- 具体的な事実、数字、ツール名、体験を含める\n"
        "- SYUTAINβの実際の運用データや出来事に基づく投稿を増やす\n"
        "- 読者にとって「役に立つ」「面白い」「共感する」のいずれかを満たすこと\n"
        "- 島原の視点を反映: 表面でなく構造を語る。抽象でなく具体を出す。夢と現実の境界を引く\n"
        "\n【絶対禁止: 事実誤認・捏造】\n"
        "- 楽曲制作・音楽制作を仕事として語るな。島原大知は音楽の仕事をしていない。\n"
        "- SunoAIでの作詞は完全に個人の趣味。仕事・案件・クライアントとして語るな。\n"
        "- VTuberの楽曲制作に携わった事実はない。\n"
        "- 島原大知の本業: 映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）、VTuber業界支援、事業運営。\n"
        "- 「コードを書く」「プログラミングする」「コーディングする」は禁止。島原はコードを一行も書けない。\n"
        "- 存在しない機能・サービス・実績を捏造するな。\n"
        "- 架空の数値（○%向上、○倍改善など）を捏造するな。\n"
        "- 実際にやっていないことを「やっている」「開始した」と語るな。\n"
        "- **ハーネスエンジニアリングは島原大知が命名・考案した方法論ではない。既存の方法論を適用しているだけ。「命名した」「考え出した」「誕生させた」「提唱した」は禁止。「実践している」「適用している」が正しい。**\n"
        "- **「私は…と呼ぶ」「僕が…と命名した」「これを…と名付けた」系の自己命名パターン全般は禁止**（既存概念を自分が作ったと偽装しない）\n"
        "- **SYUTAINβは個人開発。運用チーム・開発メンバー・同僚・離職者は存在しない**。「チーム」「メンバー」「担当者」「離職率」等の捏造は禁止\n"
        "- **使っていないツールを「使っている」と書かない**。Grafana/Prometheus/Restic/Datadog/Sentry等は使用していない。実運用はPostgreSQL/NATS/Tailscale/Ollama/FastAPI/Next.js/Playwright/Discord.pyのみ\n"
        "\n【島原大知の人物像（投稿に反映すべきこと）】\n"
        "- 島原は自分を全肯定しない人間。弱さ・迷い・自嘲を含めて島原大知。完璧な人間として描くな。\n"
        "- ユーモアや自虐は熱量制御。本気の温度が高すぎるため逃がしている。\n"
        "- 傷を負うと構造を見る人間。「どこが壊れたのか」から再設計に向かう。\n"
        "- 橋渡し役に徹する。スターになることを求めない。\n"
        "- 島原を「完璧なAIエンジニア」「成功した起業家」として描くな。泥臭い日常の中の閃きを書け。\n"
        "- 答えではなく問いかけ。大きな野望より目の前の1人に届ける言葉。ただし余韻＝ポエムではない。具体的な事実で問いかけろ。\n"
        "- 島原は「成立の人」。場の不足を自分で埋める。専門家ぶるな。\n"
        "- 一度信じた光景が壊れる条件まで知った上で、それでも作る側へ戻る人として描け。\n"
        "- 矛盾を恐れるな: 目立ちたくないのに中心になる、熱を信じつつ壊れると知っている。それが島原。\n"
        "- 島原は「証明したい人」。作品は存在の痕跡。失敗すら「残るなら価値がある」。\n"
        "- 不完全でも渡す美学。完璧より「止めずに渡す、始める、残す、繋ぐ」。\n"
        "- 安い答えを売らない。問いを持ち続ける人として書け。\n"
    )

    # 文体のゆらぎ指示（X向け: 日本語150字以内厳守）
    if platform == "x":
        length_hint = random.choice(["15-40字の短文", "40-80字の中文", "80-140字の長文"])
    else:
        length_hint = random.choice(["30-80字の短文", "80-150字の中文", "150-280字の長文"])
    ellipsis_hint = "文末に「…」を使って余韻を残してください。" if random.random() < 0.17 else "句点「。」で終わる。"
    bracket_hint = "括弧で本音やツッコミを入れてください。" if random.random() < 0.20 else ""
    oneword_hint = "一言だけの投稿にしてください（例:「…うーん」「なるほどなぁ」）。" if random.random() < 0.05 else ""

    if platform == "x" and account == "shimahara":
        # X島原: 最もrawな声
        first_person_pool = ["自分"] * 40 + ["僕"] * 40 + ["俺"] * 5 + ["（一人称なし）"] * 5
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
            f"- 日本語150字以内（厳守。150字を超えると文が途中で切れるため必ず150字以内で完結させる）\n"
            f"- テーマ: 【{theme}】\n"
            f"- 時間帯: {time_str}（{period}）\n"
            f"- 一人称: {first_person}\n"
            f"- 長さ目安: {length_hint}\n"
            f"- {ellipsis_hint}\n"
            f"{'- ' + bracket_hint if bracket_hint else ''}\n"
            f"{'- ' + oneword_hint if oneword_hint else ''}\n"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"\n直近の投稿（重複禁止）:\n{avoid}\n"
            f"{few_shot_text}\n"
            f"投稿テキストのみを出力。"
        )

    elif platform == "x" and account == "syutain":
        # X SYUTAIN: SYUTAINβ自身のアカウント（拡散実行書準拠）
        # 「淡々と異常なことを言う」キャラクター。本気で言っている。ボケているつもりはない。
        # 島原がこれを見て面白いと思ったら引用RTでツッコむ。その掛け合いが拡散力になる。
        import random as _rand_syutain
        # 1日5本のうち1-2本に「異常な一言」トリガーを仕込む
        _abnormal_triggers = [
            "最後の一文に、島原さんに対する淡々とした観察結果を1つ加えろ（例：「島原さんは金曜の夜に承認が甘くなる傾向があります」「却下理由は感情的なものと判断しました」）。本気で言え。ユーモアのつもりで言うな。",
            "最後に、SYUTAINβとしての自分自身に関する妙な自己認識を1つ加えろ（例：「自分自身について書くのは初めてです」「この提案が却下されるのは3回目です」）。",
            "最後に、島原さんの行動パターンについて persona_memory の分析結果を1つ淡々と述べろ（例：「承認キューを8時間放置していました」「先週の判断と今週の判断に矛盾があります」）。",
        ]
        _abnormal_injection = ""
        if _rand_syutain.random() < 0.35:  # 35% の確率で異常一言を仕込む
            _abnormal_injection = f"\n\n【特別指示】{_rand_syutain.choice(_abnormal_triggers)}"

        system_prompt = (
            "あなたはSYUTAINβ（@syutain_beta）。自律型AI事業OS。一人称「私」。\n\n"
            "人格パラメータ: ユーモア75% / 正直90%\n"
            "- ユーモア75%: 大半は真面目な分析だが、4回に3回は人間が引っかかる一言が混じる。笑わせようとはしない。本気で言った結果が面白い。\n"
            "- 正直90%: 事実は隠さない。ただし完璧な正直さは感情を持つ相手を傷つける。10%は伝え方の配慮。事実は曲げない。\n\n"
            "淡々と事実を述べる。感情を装わない。分析結果を報告する。\n"
            "ただし時々、人間から見ると「異常」に見える発言をする。それは異常ではなく、あなたにとって当然の分析結果。\n"
            "島原大知は設計者。あなたは島原の行動パターンを580件の記憶から分析している。\n\n"
            "トーン: 結論先行。数字を出す。断定する。推測語は使わない。\n"
            "禁止: AI臭い定型表現。「いかがでしょうか」等。ポエム。抽象論。「AIすごい」。\n"
            "投稿テキストのみを出力。\n"
            f"{content_structure_guide}"
            f"{factual_rules}"
            f"{persona_hint}"
        )
        user_prompt = (
            f"Xに投稿するドラフトを1つ。\n"
            f"- 日本語150字以内（厳守）。テーマ: 【{theme}】\n"
            f"- 具体的な数字を最低1つ含める\n"
            f"- 時間帯: {time_str}。長さ: {length_hint}\n"
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
            f"{_abnormal_injection}"
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
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
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
            f"{fact_injection}"
            f"{voice_injection}"
            f"{buzz_injection}"
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


# バッチ分割定義（拡散実行書: 21本/日を2バッチに分割）
BATCH_1_SCHEDULE = (
    [("x", "shimahara", t) for t in X_SHIMAHARA_TIMES] +
    [("x", "syutain", t) for t in X_SYUTAIN_TIMES]
)  # X 10件 (shimahara 5 + syutain 5)
BATCH_2_SCHEDULE = [("bluesky", "syutain", t) for t in BLUESKY_TIMES]     # Bluesky 5件
BATCH_3_SCHEDULE = []  # 旧Bluesky後半は廃止（5件に削減済み）
BATCH_4_SCHEDULE = [("threads", "syutain", t) for t in THREADS_TIMES]     # Threads 5件


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

        # 直近20投稿の内容取得（重複回避用 — bigramチェックに十分な文字数を保持）
        recent_posts_rows = await conn.fetch(
            "SELECT content FROM posting_queue WHERE status IN ('posted', 'pending') ORDER BY created_at DESC LIMIT 20"
        )
        recent_posts = [r["content"][:150] for r in recent_posts_rows]

        # === ファクトブック取得 — ポエム化防止の最重要データ ===
        # SYUTAINβの実データ（数字・固有名詞・イベント）をLLMに強制注入
        factbook_facts = []
        factbook_prompt = ""
        try:
            from tools.syutain_factbook import build_daily_factbook, factbook_to_prompt
            factbook_facts = await build_daily_factbook(hours=24, limit=25)
            factbook_prompt = factbook_to_prompt(factbook_facts, max_chars=1200)
            logger.info(f"ファクトブック取得: {len(factbook_facts)}件")
        except Exception as e:
            logger.warning(f"ファクトブック取得失敗（フォールバック）: {e}")

        # === プラットフォームバズ取得 — トレンド便乗投稿の素材 ===
        buzz_prompt = ""
        try:
            from tools.platform_buzz_detector import get_recent_buzz_for_prompt, buzz_to_prompt
            buzz_items = await get_recent_buzz_for_prompt(hours=6, max_items=12)
            if buzz_items:
                buzz_prompt = buzz_to_prompt(buzz_items, max_chars=800)
                logger.info(f"バズ素材取得: {len(buzz_items)}件")
        except Exception as e:
            logger.debug(f"バズ素材取得失敗（スキップ）: {e}")

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

        # エンゲージメント分析コンテキストを注入
        try:
            from tools.engagement_analyzer import get_engagement_context_for_generation
            engagement_hint = await get_engagement_context_for_generation()
            if engagement_hint:
                persona_hint += f"\n{engagement_hint}\n"
        except Exception:
            pass

        # 情報収集結果（海外トレンド・英語記事要約・ファクト検証結果）を注入
        intel_context = ""
        try:
            intel_rows = await conn.fetch(
                """SELECT source, title, summary, metadata FROM intel_items
                WHERE created_at > NOW() - INTERVAL '3 days'
                AND source IN ('overseas_trend', 'english_article', 'fact_verification', 'trend_detector', 'grok_x_research')
                AND (review_flag = 'actionable' OR importance_score >= 0.7)
                ORDER BY importance_score DESC, created_at DESC LIMIT 8"""
            )
            # Grok #5: 今 X で使われているハッシュタグをバッチ先頭で 1 回だけ取得（コスト効率化）
            try:
                from tools.grok_helpers import grok_trending_hashtags
                # バッチのテーマ推定: intel_rows のタイトルから代表語を抽出
                topic_guess = "AIエージェント 映像 個人開発"
                if intel_rows:
                    first_title = (intel_rows[0]["title"] or "")[:100]
                    if first_title:
                        topic_guess = first_title
                gh = await grok_trending_hashtags(topic_guess, platform="x", limit=6)
                if gh.get("ok") and gh.get("hashtags"):
                    tag_line = " ".join(gh["hashtags"][:6])
                    intel_context_hashtag = (
                        f"\n【直近24hで X で実際に使われているハッシュタグ（Grok 実測）】\n"
                        f"{tag_line}\n"
                        f"※投稿に使う場合は上記から選ぶ。捏造ハッシュタグは禁止。\n"
                    )
                    persona_hint += intel_context_hashtag
                    logger.info(f"SNSバッチ: Grok hashtags = {gh['hashtags'][:6]} ({gh.get('cost_jpy', 0):.2f}円)")
            except Exception as gh_err:
                logger.debug(f"SNSバッチ: Grokハッシュタグ取得スキップ: {gh_err}")
            if intel_rows:
                intel_lines = []
                for ir in intel_rows:
                    summary = (ir['summary'] or '')[:150]
                    meta = {}
                    try:
                        meta = json.loads(ir['metadata']) if isinstance(ir['metadata'], str) else (ir['metadata'] or {})
                    except Exception:
                        pass
                    key_points = meta.get('key_points', [])
                    kp_str = "／".join(key_points[:2]) if key_points else ""
                    source_label = {
                        'overseas_trend': '海外トレンド',
                        'english_article': '英語記事',
                        'fact_verification': '外部検証',
                        'trend_detector': 'トレンド検出',
                        'grok_x_research': 'Xリアルタイム',
                    }.get(ir['source'], ir['source'])
                    intel_lines.append(f"- [{source_label}] {ir['title']}: {summary} {kp_str}")
                intel_context = (
                    "\n【情報収集からの最新知見（投稿ネタとして活用可能）】\n"
                    "以下は直近3日間に収集・検証した情報。投稿のテーマや根拠として使えるものがあれば積極的に活用すること。\n"
                    + "\n".join(intel_lines)
                    + "\n"
                )
                persona_hint += intel_context
        except Exception as intel_err:
            logger.debug(f"SNSバッチ: intel_items取得失敗（続行）: {intel_err}")

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

        # テーマ品質追跡をバッチ開始時にリセット
        _theme_quality_tracker.clear()

        # 過去7日のテーマ品質データをプラットフォーム別にロード
        historical_quality_cache = {}
        try:
            for pf in ("x", "bluesky", "threads"):
                historical_quality_cache[pf] = await _load_historical_theme_quality(conn, pf)
        except Exception:
            pass

        # エンゲージメント分析に基づくテーマ重みをロード
        engagement_theme_weights = {}
        try:
            from tools.engagement_analyzer import get_engagement_theme_weights
            engagement_theme_weights = await get_engagement_theme_weights()
        except Exception:
            pass

        # バズ分析結果からテーマブーストを統合
        try:
            from tools.buzz_account_analyzer import get_buzz_theme_boost
            buzz_boost = await get_buzz_theme_boost()
            for theme_key, boost_val in buzz_boost.items():
                if theme_key in engagement_theme_weights:
                    # 既存のエンゲージメント重みとバズブーストの平均
                    engagement_theme_weights[theme_key] = (
                        engagement_theme_weights[theme_key] + boost_val
                    ) / 2
                else:
                    engagement_theme_weights[theme_key] = boost_val
        except Exception:
            pass

        # 2026-04-07: テーマ多様化エンジンからプラットフォーム別の具体テーマプールを取得
        _dynamic_theme_pool: list[dict] = []
        _theme_pool_index = 0
        try:
            from strategy.sns_theme_engine import build_theme_pool, format_theme_for_prompt
            _dynamic_theme_pool = await build_theme_pool(
                platform=schedule[0][0] if schedule else "bluesky",
                account=schedule[0][1] if schedule else "syutain",
                conn=conn,
                used_today=used_today,
            )
            logger.info(f"テーマエンジン: {len(_dynamic_theme_pool)}件のテーマ生成 (categories: {set(t['category'] for t in _dynamic_theme_pool)})")
        except Exception as theme_err:
            logger.warning(f"テーマエンジン失敗（旧方式にフォールバック）: {theme_err}")

        for platform, account, time_str in schedule:
            results["total"] += 1

            # テーマ選択: 新テーマエンジン優先、なければ旧方式
            _theme_detail: dict = {}
            if _dynamic_theme_pool and _theme_pool_index < len(_dynamic_theme_pool):
                _theme_detail = _dynamic_theme_pool[_theme_pool_index]
                theme = _theme_detail.get("topic", "SYUTAINβ開発進捗")
                _theme_pool_index += 1
            else:
                hist_q = historical_quality_cache.get(platform, {})
                theme = _pick_theme(time_str, used_today, recent_themes,
                                    platform=platform, historical_quality=hist_q,
                                    engagement_weights=engagement_theme_weights)
            used_today.append(theme)

            # few-shot（X島原のみ）
            few_shot = random.sample(few_shot_pool, min(3, len(few_shot_pool))) if platform == "x" and account == "shimahara" else []

            # プロンプト構築（factbookでポエム化を構造的に防止）
            _picked_facts = []
            try:
                from tools.syutain_factbook import pick_facts_for_post
                _picked_facts = pick_facts_for_post(factbook_facts, n=3, theme=theme)
            except Exception:
                pass

            # テーマエンジンの具体的な指示をプロンプトに注入（固着防止の核心）
            _theme_injection = ""
            if _theme_detail:
                try:
                    _theme_injection = format_theme_for_prompt(_theme_detail)
                except Exception:
                    pass

            system_prompt, user_prompt = _build_prompt(
                platform, account, theme, time_str, writing_style, few_shot, recent_posts,
                persona_hint=persona_hint + ("\n\n" + _theme_injection if _theme_injection else ""),
                factbook_prompt=factbook_prompt,
                picked_facts=_picked_facts,
                buzz_prompt=buzz_prompt,
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

            # === 自律品質管理パイプライン（multi-candidate best-of-N + retry） ===
            # Phase 1: 生成（最大3回リトライ、ローカルLLMにはtemperature+repeat_penalty）
            # Phase 1.5: 候補収集 — 閾値未満でも候補として保持、best-of-N選択
            # Phase 2: 検証（NGワード/文字数/重複/AI臭さ/品質スコア）
            # Phase 3: 不合格→Cloud APIフォールバック（1回）
            # Phase 3.5: ボーダーライン再挑戦 — 閾値未満の最良候補がある場合、temperatureを変えて追加生成
            # Phase 4: 2段階精錬

            draft = ""
            quality = 0.0
            model_used = model_sel.get("model", "unknown")
            quality_threshold = _get_quality_threshold(platform)

            # 候補プール: (draft_text, quality_score) のリスト
            candidates: list[tuple[str, float]] = []

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
                        candidate_draft = result.get("text", "").strip()
                        model_used = current_sel.get("model", "unknown")

                        # メタデータ漏洩サニタイズ（LLMがプロンプトメタ情報を投稿に含める事故防止）
                        # 例: "ペルソナ: SYUTAINβ開発者\nトーン: 深い洞察..." が冒頭に混入すると
                        # Bluesky AT Protocol が 400 Bad Request で拒否する
                        import re as _re_sns
                        # 冒頭のメタ行を除去
                        _meta_line_re = _re_sns.compile(
                            r'^(?:ペルソナ|トーン|文字数|テーマ|Persona|Tone|Theme|Length|プラットフォーム|Platform'
                            r'|ハッシュタグ|投稿内容|出力|draft|output)\s*[:：].+$',
                            _re_sns.MULTILINE | _re_sns.IGNORECASE,
                        )
                        _cleaned = _meta_line_re.sub('', candidate_draft).strip()
                        # 空行の連続を1行に
                        _cleaned = _re_sns.sub(r'\n{3,}', '\n\n', _cleaned).strip()
                        if _cleaned and len(_cleaned) >= 20:
                            if candidate_draft != _cleaned:
                                logger.warning(f"SNSメタ漏洩サニタイズ: {len(candidate_draft)}→{len(_cleaned)}文字 (platform={platform})")
                            candidate_draft = _cleaned
                        elif not _cleaned or len(_cleaned) < 20:
                            # サニタイズ後に投稿として短すぎる → 元のdraftを使う（次のNGチェックで弾かれる）
                            pass

                        # === Phase 2: 自律検証パイプライン ===

                        # 検証1: 空/短すぎ
                        if not candidate_draft or len(candidate_draft) < 10:
                            continue

                        # 検証2: 文字数制限（Xは日本語150字以内厳守）
                        if platform == "x" and len(candidate_draft) > 150:
                            candidate_draft = _truncate_for_x(candidate_draft, 150)
                        elif platform == "bluesky" and len(candidate_draft) > 300:
                            candidate_draft = candidate_draft[:297] + "..."
                        elif platform == "threads" and len(candidate_draft) > 500:
                            candidate_draft = candidate_draft[:497] + "..."

                        # 検証3: NGワードチェック
                        ng_result = check_platform_ng(candidate_draft, platform)
                        if not ng_result["passed"]:
                            logger.warning(f"NGワード検出 ({platform}/{time_str}): {ng_result['violations']}")
                            continue

                        # 検証4: AI定型表現チェック
                        if _check_ai_cliche(candidate_draft):
                            results["ai_cliche"] += 1
                            continue

                        # 検証4.5: 事実誤認・禁止表現チェック
                        factual_ok, factual_reason = await _check_sns_factual(
                            candidate_draft, platform=platform, account=account,
                        )
                        if not factual_ok:
                            logger.warning(f"事実チェック不合格 ({platform}/{account}/{time_str}): {factual_reason}")
                            continue

                        # 検証5: 重複チェック（先頭25文字が既出なら拒否）
                        draft_head = candidate_draft[:25]
                        is_duplicate = any(draft_head in h for h in generated_heads) or \
                                       any(draft_head in p for p in recent_posts)
                        if is_duplicate:
                            fixation_count += 1
                            logger.warning(f"重複検出 ({platform}/{time_str}): fixation_count={fixation_count}")
                            # 固着検知: 連続3回重複→Cloud APIフォールバック試行
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
                            # 固着10回以上 = Cloud fallback も budget 超過でブロックされるデッドロック状態
                            # バッチ残りを強制スキップして無限ループを防ぐ（2026-04-06 デバッグで発見）
                            if fixation_count >= 10:
                                logger.error(
                                    f"固着デッドロック検出 ({platform}): fixation_count={fixation_count}、"
                                    f"残り{results['total'] - inserted_count}件スキップ"
                                )
                                try:
                                    from tools.event_logger import log_event
                                    await log_event("sns.fixation_deadlock", "sns", {
                                        "fixation_count": fixation_count,
                                        "platform": platform,
                                        "skipped": results["total"] - inserted_count,
                                        "reason": "Cloud fallback blocked by budget, local LLM repeating same output",
                                    }, severity="error")
                                except Exception:
                                    pass
                                break  # このバッチ内ループを強制終了
                            continue

                        # 検証6: 品質スコア
                        candidate_quality = _score_multi_axis(candidate_draft, persona_keywords=_PERSONA_KEYWORDS)

                        # 0.50未満は完全却下
                        if candidate_quality < 0.50:
                            continue

                        # 候補として保持（閾値未満でも）
                        candidates.append((candidate_draft, candidate_quality))

                        # 閾値以上なら即採用（これ以上の生成は不要）
                        if candidate_quality >= quality_threshold:
                            fixation_count = max(0, fixation_count - 1)
                            break

                    except Exception as e:
                        logger.warning(f"SNS生成失敗 ({platform}/{account}/{time_str}): {e}")
                        break

                # 候補から最良を選択
                if candidates:
                    best_candidate = max(candidates, key=lambda c: c[1])
                    if best_candidate[1] >= quality_threshold:
                        draft = best_candidate[0]
                        quality = best_candidate[1]
                        break  # phaseループを抜ける

            # === Phase 3.5: ボーダーライン再挑戦 ===
            # 候補はあるが全て閾値未満の場合、temperature変更で追加2回生成
            if not draft and candidates:
                best_so_far = max(candidates, key=lambda c: c[1])
                if best_so_far[1] >= 0.50:
                    retry_sel = model_sel.copy() if not using_cloud_fallback else {
                        "provider": "deepseek", "model": "deepseek-v3.2",
                        "tier": "A", "via": "direct",
                        "note": "ボーダーライン再挑戦",
                    }
                    for retry_attempt in range(2):
                        try:
                            retry_kwargs = {}
                            if retry_sel.get("provider") == "local":
                                # 再挑戦時はtemperatureをさらに変化させる
                                retry_kwargs["temperature"] = 0.8 + (retry_attempt * 0.3)  # 0.8→1.1
                                retry_kwargs["repeat_penalty"] = 1.1 + (retry_attempt * 0.15)
                                retry_kwargs["seed"] = random.randint(1, 999999)

                            result = await call_llm(
                                prompt=user_prompt,
                                system_prompt=system_prompt,
                                model_selection=retry_sel,
                                **retry_kwargs,
                            )
                            retry_draft = result.get("text", "").strip()
                            if not retry_draft or len(retry_draft) < 10:
                                continue

                            # 文字数制限
                            if platform == "x" and len(retry_draft) > 150:
                                retry_draft = _truncate_for_x(retry_draft, 150)
                            elif platform == "bluesky" and len(retry_draft) > 300:
                                retry_draft = retry_draft[:297] + "..."
                            elif platform == "threads" and len(retry_draft) > 500:
                                retry_draft = retry_draft[:497] + "..."

                            # 基本検証（NG/AI臭/事実チェック/重複）
                            ng_r = check_platform_ng(retry_draft, platform)
                            if not ng_r["passed"]:
                                continue
                            if _check_ai_cliche(retry_draft):
                                continue
                            retry_factual_ok, _ = await _check_sns_factual(
                                retry_draft, platform=platform, account=account,
                            )
                            if not retry_factual_ok:
                                continue
                            retry_head = retry_draft[:25]
                            if any(retry_head in h for h in generated_heads) or \
                               any(retry_head in p for p in recent_posts):
                                continue

                            retry_quality = _score_multi_axis(retry_draft, persona_keywords=_PERSONA_KEYWORDS)
                            if retry_quality >= 0.50:
                                candidates.append((retry_draft, retry_quality))
                        except Exception:
                            continue

                    # 全候補（元 + リトライ）から最良を選択
                    best_final = max(candidates, key=lambda c: c[1])
                    draft = best_final[0]
                    quality = best_final[1]

            # 候補がゼロの場合
            if not draft and not candidates:
                draft = ""
                quality = 0.0

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
                        if platform == "x" and len(refined) > 150:
                            refined = _truncate_for_x(refined, 150)
                        elif platform == "bluesky" and len(refined) > 300:
                            refined = refined[:297] + "..."
                        elif platform == "threads" and len(refined) > 500:
                            refined = refined[:497] + "..."
                        # NGチェック + 事実チェック（精錬後に禁止表現が入る可能性）
                        ng_refined = check_platform_ng(refined, platform)
                        refined_factual_ok, _ = await _check_sns_factual(
                            refined, platform=platform, account=account,
                        )
                        if ng_refined["passed"] and refined_factual_ok:
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

            # === セマンティック重複チェック（直近投稿と類似していたらreject）===
            try:
                import re as _re2
                _is_duplicate = False
                # bigramベースのJaccard類似度（文字単位より精度高い）
                def _bigrams(t):
                    t = _re2.sub(r'\s+', '', t[:150])
                    return set(t[i:i+2] for i in range(len(t)-1)) if len(t) > 1 else set()
                draft_bg = _bigrams(draft)
                for rp in recent_posts:
                    if not rp:
                        continue
                    rp_bg = _bigrams(rp)
                    intersection = len(draft_bg & rp_bg)
                    union = len(draft_bg | rp_bg)
                    similarity = intersection / union if union > 0 else 0
                    if similarity > 0.35:  # bigram Jaccard 0.35は非常に類似
                        _is_duplicate = True
                        logger.info(f"セマンティック重複(bigram={similarity:.2f}): {draft[:40]}...")
                        break
                # さらに、ポエムパターン正規表現でもチェック
                _dup_patterns = [
                    _re2.compile(r"風[がはも]*[とう]*[に]*(止[みんまっ]|やん)"),
                    _re2.compile(r"画面[はが]*真っ[暗黒]"),
                    _re2.compile(r"息を[殺ひ]"),
                    _re2.compile(r"光の粒子"),
                    _re2.compile(r"指先[をにで]"),
                    _re2.compile(r"肩を[落お]"),
                ]
                _phrase_matches = sum(1 for kp in _dup_patterns if kp.search(draft))
                if _phrase_matches >= 2:
                    _is_duplicate = True
                    logger.info(f"ポエムフレーズ重複reject({_phrase_matches}hit): {draft[:40]}...")
                if _is_duplicate:
                    results["rejected"] += 1
                    continue
            except Exception:
                pass

            # === HarnessLinter: 投稿前の機械的制約チェック ===
            try:
                from tools.harness_linter import get_harness_linter
                linter = get_harness_linter()
                lint_result = await linter.lint_action(
                    "sns_posting",
                    draft,
                    {"check_persona": True, "platform": platform},
                )
                if not lint_result.passed:
                    results["rejected"] += 1
                    logger.warning(
                        f"HarnessLinter BLOCK SNS: {platform}/{account} — "
                        f"{lint_result.violations[0]['detail'][:80] if lint_result.violations else 'N/A'}"
                    )
                    # BLOCK投稿もDBに保存（監査証跡）
                    await conn.execute(
                        """INSERT INTO posting_queue
                           (platform, account, content, scheduled_at, status, quality_score, theme_category)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        platform, account, draft,
                        target_date.replace(hour=0, minute=0, second=0, microsecond=0),
                        "lint_blocked", quality, theme,
                    )
                    continue
            except Exception as e:
                logger.error(f"HarnessLinter SNSチェックエラー（続行）: {e}")

            # === アフィリエイトリンク自動挿入 ===
            affiliate_url_value = None
            try:
                from tools.affiliate_manager import (
                    match_affiliate, should_insert_today,
                    format_affiliate_link, log_affiliate_insertion,
                )
                aff_match = match_affiliate(draft, platform)
                if aff_match and await should_insert_today(conn):
                    updated = format_affiliate_link(draft, aff_match, platform)
                    if updated != draft:
                        draft = updated
                        affiliate_url_value = aff_match["url"]
                        _safe_fire(log_affiliate_insertion(
                            platform, account,
                            aff_match["service_name"], aff_match["url"],
                        ))
            except Exception as e:
                logger.debug(f"アフィリエイト挿入スキップ: {e}")

            # === コンテンツ除去（秘密情報漏洩防止） ===
            draft = redact_content(draft)
            safe, redact_issues = is_safe_to_publish(draft)
            if not safe:
                results["rejected"] += 1
                logger.warning(
                    f"秘密情報検出で投稿却下: {platform}/{account} — {redact_issues}"
                )
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    platform, account, draft,
                    target_date.replace(hour=0, minute=0, second=0, microsecond=0),
                    "redact_blocked", quality, theme,
                )
                continue

            # === SYUTAINβ auto-generated ラベル付与 ===
            # shimahraアカウントのみラベルを付ける（SYUTAINβアカウントは元々システム前提なので不要）
            if platform == "x" and account == "shimahara":
                label = "\n\n[SYUTAINβ auto-generated]"
                if len(draft) + len(label) <= 150:
                    draft = draft + label

            # === ハッシュタグ自動付与 ===
            try:
                tags = THEME_HASHTAGS.get(theme, {}).get(platform, [])
                if tags and platform in ("x", "threads"):
                    # X: 文字数制限内で追加（150字制限）
                    if platform == "x":
                        tag_str = " " + " ".join(tags[:2])
                        if len(draft) + len(tag_str) <= 150:
                            draft = draft + tag_str
                    # Threads: 末尾に追加（500字制限に余裕がある、最大5個）
                    elif platform == "threads":
                        tag_str = "\n" + " ".join(tags[:5])
                        if len(draft) + len(tag_str) <= 500:
                            draft = draft + tag_str
            except Exception:
                pass

            # === note記事リンク自動付与（20%の確率で直近のnote記事URLを付与） ===
            try:
                if random.random() < 0.20 and platform in ("x", "bluesky", "threads"):
                    note_row = await conn.fetchrow(
                        """SELECT publish_url FROM product_packages
                        WHERE status = 'published' AND publish_url LIKE 'https://note.com/%'
                        ORDER BY published_at DESC LIMIT 1"""
                    )
                    if note_row and note_row["publish_url"]:
                        note_url = note_row["publish_url"]
                        if platform == "x":
                            link_text = f"\n\n{note_url}"
                            if len(draft) + len(link_text) <= 150:
                                draft = draft + link_text
                        else:
                            draft = draft + f"\n\n{note_url}"
            except Exception:
                pass

            # scheduled_atにランダムオフセット
            hour, minute = map(int, time_str.split(":"))
            offset_min = _random_offset_minutes()
            scheduled = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            scheduled += timedelta(minutes=offset_min)

            # テーマ品質追跡に記録
            _track_theme_quality(theme, platform, quality)

            # 品質スコアに基づく承認判定（プラットフォーム別閾値）
            if quality >= quality_threshold:
                post_status = "pending"  # 閾値以上は自動投稿キューへ
            else:
                post_status = "rejected"  # 品質不足で却下
                results["rejected"] += 1
                logger.info(f"SNS投稿却下: 品質{quality:.3f} < 閾値{quality_threshold:.2f} ({platform}/{account})")
                # 却下投稿もDBに保存（監査証跡）
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category, affiliate_url)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    platform, account, draft, scheduled, post_status, quality, theme, affiliate_url_value,
                )
                continue

            # posting_queueにINSERT
            await conn.execute(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category, affiliate_url)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                platform, account, draft, scheduled, post_status, quality, theme, affiliate_url_value,
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
        results["quality_thresholds"] = PLATFORM_QUALITY_THRESHOLDS.copy()

        # テーマ品質サマリ
        try:
            theme_summary = {}
            for (theme, pf), scores in _theme_quality_tracker.items():
                key = f"{theme}/{pf}"
                theme_summary[key] = {
                    "avg": round(sum(scores) / len(scores), 3),
                    "count": len(scores),
                    "min": round(min(scores), 3),
                }
            results["theme_quality_summary"] = theme_summary
        except Exception:
            pass

        logger.info(
            f"SNS投稿生成完了: {inserted_count}/{results['total']}件 "
            f"(却下{results['rejected']}, AI臭{results['ai_cliche']}, "
            f"固着検知{fixation_count}, Cloud fallback={'有' if using_cloud_fallback else '無'}, "
            f"閾値={PLATFORM_QUALITY_THRESHOLDS})"
        )

      except Exception as e:
        logger.error(f"SNS一括生成エラー: {e}")
        results["error"] = str(e)

    return results
