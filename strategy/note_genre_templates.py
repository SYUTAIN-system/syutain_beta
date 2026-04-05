"""
note記事ジャンル別テンプレート — 「売れるnote量産」戦略

各ジャンルに対して:
- タイトルパターン (3+ types)
- 無料パート構成 (hook, intro, problem_statement)
- 有料パート構成 (main_content, steps, examples, summary)
- CTAパターン (3+ types)
- 刺さるキーワード (20+ per genre)
- 目標文字数範囲
- 価格帯 (文字数ベース)

3軸タイトル生成:
- Axis 1: ジャンルキーワード
- Axis 2: 切り口 (方法論/失敗談/比較/ランキング/体験談/裏技/最新トレンド)
- Axis 3: 感情トリガー (恐怖/好奇心/嫉妬/焦り/希望/怒り/共感)
"""

import logging
import random
from typing import Optional

logger = logging.getLogger("syutain.strategy.note_genre_templates")

# ===== 3軸タイトル生成: 切り口 × 感情トリガー =====

TITLE_ANGLES = [
    "方法論",
    "失敗談",
    "比較",
    "ランキング",
    "体験談",
    "裏技",
    "最新トレンド",
]

EMOTION_TRIGGERS = [
    "恐怖",
    "好奇心",
    "嫉妬",
    "焦り",
    "希望",
    "怒り",
    "共感",
]


# ===== ジャンル別テンプレート =====

GENRE_TEMPLATES = {
    "ai_tech": {
        "name": "AI技術・ツール系",
        "title_patterns": [
            "【{year}年最新】{keyword}を{angle}で徹底解説 — {emotion_hook}",
            "{keyword}で{benefit}する方法｜{persona}が実践した{number}つのステップ",
            "なぜ{keyword}を使わないと{loss}なのか？ — {experience}から学んだ真実",
            "「{keyword}は使えない」と思っていた{persona}が{result}を達成するまで",
        ],
        "free_part": {
            "hook": (
                "冒頭3行で「AIを使いこなせていない焦り」を刺激する。\n"
                "具体的な数字（○時間短縮、○円節約）で注意を引く。\n"
                "「あなたはまだ○○を使っていないんですか？」系の問いかけ。"
            ),
            "intro": (
                "AI技術の現状を簡潔に整理（3-5行）。\n"
                "「非エンジニアでも使える」ことを強調。\n"
                "島原大知がこのツールを使い始めた経緯。"
            ),
            "problem_statement": (
                "読者が抱える具体的な悩みを3つ列挙。\n"
                "「こんなことで困っていませんか？」形式。\n"
                "悩みの裏にある本質的な課題を指摘。"
            ),
        },
        "paid_part": {
            "main_content": (
                "ツールの具体的な使い方をステップバイステップで解説。\n"
                "スクリーンショットの代わりに、操作手順を詳細に文字で記述。\n"
                "「ここがポイント」「ここでハマりやすい」注意点を明記。\n"
                "各セクションに具体例を1つ以上含める。\n"
                "具体的なツール名・設定値・手順を明記する。\n"
                "読者の「で、具体的にどうすればいいの？」に答える。"
            ),
            "steps": (
                "実践ステップを5-7個に分解。\n"
                "各ステップに所要時間とコストを明記。\n"
                "初心者がつまずきやすいポイントに警告マークを付ける。"
            ),
            "examples": (
                "島原大知の実際の使用例を3つ以上。\n"
                "Before/Afterの具体的な数字を含める。\n"
                "失敗例も正直に共有。"
            ),
            "summary": (
                "記事の要点を箇条書き5つ。\n"
                "「今日から試せること」を1つ明確に提示。\n"
                "次のステップへの誘導。"
            ),
        },
        "cta_patterns": [
            "この記事で紹介した{keyword}の具体的な設定方法と、島原が実際に使っているプロンプトテンプレートは有料パートで公開しています。",
            "ここから先は、{number}時間かけて検証した{keyword}の「本当に使える設定」を全て公開します。この情報だけで元が取れるはずです。",
            "無料パートはここまで。有料パートでは、{keyword}を使って{result}を達成した具体的な手順と、失敗から学んだ{number}つの教訓を共有します。",
        ],
        "keywords": [
            "ChatGPT", "Claude", "GPT-4", "プロンプト", "AI自動化",
            "ノーコード", "API連携", "LLM", "画像生成", "Midjourney",
            "Stable Diffusion", "AIツール", "業務効率化", "AI副業",
            "プロンプトエンジニアリング", "RAG", "ファインチューニング",
            "AIエージェント", "自律AI", "ワークフロー自動化",
            "AI活用術", "非エンジニア", "コスト削減", "時短",
            "AIアシスタント", "生成AI", "AI時代", "DX",
        ],
        "word_count_range": (6000, 10000),
        "price_map": {6000: 480, 8000: 980, 12000: 1980},
    },

    "fukugyou": {
        "name": "副業・稼ぎ方系",
        "title_patterns": [
            "月{amount}円を{keyword}で稼いだ{persona}のリアルな{number}ヶ月",
            "【{year}年版】{keyword}で副業を始める完全ロードマップ — {emotion_hook}",
            "{keyword}は本当に稼げるのか？{number}ヶ月やってみた収支を全公開",
            "「{keyword}で稼ぐ」の嘘と本当 — {amount}円稼ぐまでにかかった本当のコスト",
        ],
        "free_part": {
            "hook": (
                "具体的な収益数字（月○円）で注意を引く。\n"
                "「副業で月5万円」の現実を突きつける。\n"
                "「楽して稼げる」という幻想を否定してから始める。"
            ),
            "intro": (
                "島原大知が副業を始めた背景。\n"
                "最初の収益が発生するまでの期間を正直に開示。\n"
                "この記事で学べることの箇条書き。"
            ),
            "problem_statement": (
                "「副業したいけど何から始めればいいかわからない」\n"
                "「情報が多すぎて選べない」\n"
                "「始めたけど全然稼げない」という3段階の悩み。"
            ),
        },
        "paid_part": {
            "main_content": (
                "実際の収益推移をグラフ的に文章で表現。\n"
                "初期投資額、ランニングコスト、損益分岐点を明記。\n"
                "「やめておいた方がいい人」の特徴も正直に記載。\n"
                "各セクションに具体例を1つ以上含める。\n"
                "具体的なツール名・設定値・手順を明記する。\n"
                "読者の「で、具体的にどうすればいいの？」に答える。"
            ),
            "steps": (
                "Day 1からの具体的アクションプランを時系列で。\n"
                "各ステップの所要時間と必要スキルレベルを明記。\n"
                "挫折しやすいポイントとその対処法。"
            ),
            "examples": (
                "実際の案件獲得までの流れ。\n"
                "失敗した副業とその理由。\n"
                "コスト計算の実例（税金含む）。"
            ),
            "summary": (
                "副業の選び方チェックリスト。\n"
                "最初の1ヶ月でやるべきことリスト。\n"
                "「これだけは避けろ」リスト。"
            ),
        },
        "cta_patterns": [
            "ここから先は、実際に{amount}円稼ぐまでの詳細な収支表と、島原が使っている{number}つのツール・テンプレートを公開します。",
            "無料パートはここまで。有料パートでは「初月で{amount}円」を達成するための具体的な手順と、9割の人が見落とす{keyword}のコツを解説します。",
            "この先には、{keyword}で失敗しないための{number}つのチェックリストと、島原が実際に使っている提案テンプレートがあります。",
        ],
        "keywords": [
            "副業", "月収", "不労所得", "在宅ワーク", "フリーランス",
            "スキル販売", "note販売", "コンテンツ販売", "アフィリエイト",
            "クラウドソーシング", "ココナラ", "ランサーズ", "動画編集",
            "Webライター", "ブログ収益", "SNSマネタイズ", "投資",
            "節税", "確定申告", "開業届", "収益化", "案件獲得",
            "ポートフォリオ", "単価交渉", "継続案件", "時給換算",
        ],
        "word_count_range": (6000, 10000),
        "price_map": {6000: 480, 8000: 980, 12000: 1980},
    },

    "business": {
        "name": "ビジネススキル系",
        "title_patterns": [
            "{keyword}ができない人が見落としている{number}つの本質",
            "なぜあなたの{keyword}は失敗するのか — {persona}が{number}回の失敗から掴んだ法則",
            "【永久保存版】{keyword}の教科書 — {emotion_hook}",
            "{keyword}を{period}で身につけた{persona}の{method}",
        ],
        "free_part": {
            "hook": (
                "「あなたの○○、間違っているかもしれない」系の問いかけ。\n"
                "業界の常識を覆す一言で始める。\n"
                "具体的な失敗エピソードのダイジェスト。"
            ),
            "intro": (
                "このスキルが今なぜ重要なのかの時代背景。\n"
                "島原大知がこのスキルを学んだきっかけ。\n"
                "記事の対象読者を明確に定義。"
            ),
            "problem_statement": (
                "スキルを持っていないことで起こる具体的な損失。\n"
                "「知らないことすら知らない」状態への気づきを促す。\n"
                "既存の学習法の限界を指摘。"
            ),
        },
        "paid_part": {
            "main_content": (
                "フレームワークを図解的に文章で説明。\n"
                "各ステップの理論的背景と実践方法。\n"
                "島原大知の実体験に基づく応用例。\n"
                "各セクションに具体例を1つ以上含める。\n"
                "具体的なツール名・設定値・手順を明記する。\n"
                "読者の「で、具体的にどうすればいいの？」に答える。"
            ),
            "steps": (
                "スキル習得の5ステップロードマップ。\n"
                "各ステップの習得目安期間。\n"
                "自己チェックリスト付き。"
            ),
            "examples": (
                "ビフォーアフターの具体的な変化。\n"
                "このスキルで解決した実際の問題3つ。\n"
                "失敗例と成功例の比較。"
            ),
            "summary": (
                "フレームワークの一覧図。\n"
                "明日から使える実践テンプレート。\n"
                "推奨書籍・リソース一覧。"
            ),
        },
        "cta_patterns": [
            "ここから先は、{keyword}を実践するための具体的なフレームワークと、島原が{number}年かけて作り上げたテンプレートを公開します。",
            "無料パートはここまで。有料パートでは{keyword}の{number}ステップ実践法と、「これをやるだけで変わる」最短ルートを解説します。",
            "この先には、{keyword}で結果を出すための実践ワークシートと、島原が実際に使っている判断基準が全て書かれています。",
        ],
        "keywords": [
            "交渉術", "プレゼン", "タイムマネジメント", "意思決定",
            "リーダーシップ", "マネジメント", "戦略思考", "問題解決",
            "コミュニケーション", "ファシリテーション", "ロジカルシンキング",
            "フレームワーク", "PDCA", "OKR", "KPI", "1on1",
            "フィードバック", "チームビルディング", "組織設計",
            "事業計画", "資金調達", "マーケティング戦略",
            "ブランディング", "顧客理解", "データ分析",
        ],
        "word_count_range": (6000, 10000),
        "price_map": {6000: 480, 8000: 980, 12000: 1980},
    },

    "creative": {
        "name": "クリエイティブ系",
        "title_patterns": [
            "{keyword}のプロが教える「{emotion_hook}」な{method} — {number}年の経験から",
            "なぜあなたの{keyword}は「それっぽい」で止まるのか？ — プロと素人の{number}の違い",
            "【{keyword}完全ガイド】{persona}が{number}年かけて辿り着いた制作フロー",
            "{keyword}で「選ばれる人」になるための{number}つの習慣",
        ],
        "free_part": {
            "hook": (
                "完成作品のビフォーアフターを言葉で描写。\n"
                "「プロと素人の差は○○にある」で引く。\n"
                "クリエイターの「あるある」悩みに共感。"
            ),
            "intro": (
                "島原大知のクリエイター歴（映像制作15年等）。\n"
                "このジャンルの現在のトレンド。\n"
                "記事で学べるスキルの一覧。"
            ),
            "problem_statement": (
                "「技術はあるのに仕事が来ない」問題。\n"
                "「何を作ればいいかわからない」問題。\n"
                "「クオリティの上げ方がわからない」問題。"
            ),
        },
        "paid_part": {
            "main_content": (
                "制作フローの全体像を図解的に説明。\n"
                "各工程のプロのこだわりポイント。\n"
                "使用ツール・設定値の具体的な数字。\n"
                "各セクションに具体例を1つ以上含める。\n"
                "具体的なツール名・設定値・手順を明記する。\n"
                "読者の「で、具体的にどうすればいいの？」に答える。"
            ),
            "steps": (
                "作品完成までのステップを詳細に分解。\n"
                "各ステップの所要時間と難易度。\n"
                "プロが無意識にやっている小技を言語化。"
            ),
            "examples": (
                "実際のプロジェクトの制作過程。\n"
                "クライアントとのやり取りの実例。\n"
                "失敗作品とそこからの学び。"
            ),
            "summary": (
                "制作チェックリスト。\n"
                "推奨ツール・素材サイト一覧。\n"
                "ポートフォリオの作り方。"
            ),
        },
        "cta_patterns": [
            "ここから先は、{keyword}のプロが実際に使っている制作テンプレートと、{number}年分のノウハウを凝縮した実践ガイドです。",
            "無料パートはここまで。有料パートでは、{keyword}で「選ばれる作品」を作るための具体的なテクニックと設定値を全公開します。",
            "この先には、島原が{number}年の{keyword}経験から抽出した「これだけ押さえれば変わる」{number}つの法則があります。",
        ],
        "keywords": [
            "映像制作", "動画編集", "カラーグレーディング", "VFX",
            "モーショングラフィックス", "サムネイル", "デザイン",
            "フォトグラフィー", "ライティング", "コンポジション",
            "ストーリーテリング", "演出", "撮影技法", "Live2D",
            "VTuber", "キャラクターデザイン", "UI/UX", "ロゴ",
            "ブランドデザイン", "ポートフォリオ", "作品制作",
            "クリエイティブ思考", "発想法", "制作フロー",
        ],
        "word_count_range": (6000, 10000),
        "price_map": {6000: 480, 8000: 980, 12000: 1980},
    },

    "engineering": {
        "name": "開発・エンジニアリング系",
        "title_patterns": [
            "非エンジニアが{keyword}を{period}で構築した全記録 — {emotion_hook}",
            "{keyword}入門｜{persona}が{number}回エラーを出して学んだ実践ガイド",
            "【{keyword}構築記】設計から運用まで — SYUTAINβの裏側を全公開",
            "エンジニアに頼らず{keyword}を実装する{number}つの方法",
        ],
        "free_part": {
            "hook": (
                "「非エンジニアが○○を作った」というギャップで引く。\n"
                "完成したシステムの具体的な成果数字。\n"
                "「プログラミングができなくても○○はできる」。"
            ),
            "intro": (
                "島原大知のエンジニアリング経験（非エンジニアの立場）。\n"
                "SYUTAINβ構築の背景と動機。\n"
                "この記事の対象読者と前提知識。"
            ),
            "problem_statement": (
                "「技術的なことはエンジニアに任せるしかない」という思い込み。\n"
                "「AIツールで何ができるかわからない」。\n"
                "「始めたいけどエラーが怖い」。"
            ),
        },
        "paid_part": {
            "main_content": (
                "システム構成図を文章で説明。\n"
                "技術選定の理由と代替案との比較。\n"
                "実際のコード断片（最小限）と解説。\n"
                "各セクションに具体例を1つ以上含める。\n"
                "具体的なツール名・設定値・手順を明記する。\n"
                "読者の「で、具体的にどうすればいいの？」に答える。"
            ),
            "steps": (
                "環境構築からデプロイまでのステップ。\n"
                "各ステップでハマりやすいポイントと解決策。\n"
                "コスト（サーバー代等）の内訳。"
            ),
            "examples": (
                "SYUTAINβの実際のアーキテクチャ。\n"
                "障害発生時の対応実例。\n"
                "コスト最適化の具体的な施策。"
            ),
            "summary": (
                "技術スタック一覧。\n"
                "初期構築チェックリスト。\n"
                "推奨学習リソース。"
            ),
        },
        "cta_patterns": [
            "ここから先は、{keyword}の具体的な構築手順と、島原が実際に使っている設定ファイル・コードテンプレートを全公開します。",
            "無料パートはここまで。有料パートでは、{keyword}を非エンジニアでも構築できる{number}ステップと、{number}回のエラーから学んだ解決策集を公開します。",
            "この先には、SYUTAINβ構築で得た{keyword}の実践知識と、同じものを作るための完全ガイドがあります。",
        ],
        "keywords": [
            "Python", "FastAPI", "PostgreSQL", "Docker", "API連携",
            "自動化", "Bot開発", "Discord Bot", "サーバー構築",
            "デプロイ", "CI/CD", "GitHub", "Linux", "SSH",
            "データベース", "クラウド", "VPS", "Tailscale",
            "NATS", "マイクロサービス", "監視", "ログ",
            "エラーハンドリング", "非エンジニア", "ローコード",
            "システム設計", "アーキテクチャ", "運用",
        ],
        "word_count_range": (6000, 10000),
        "price_map": {6000: 480, 8000: 980, 12000: 1980},
    },
}


# ===== ジャンル判定 =====

def detect_genre(theme: str) -> str:
    """テーマ文字列からジャンルを推定する。マッチしない場合は 'ai_tech' をデフォルトにする"""
    try:
        theme_lower = theme.lower()
        scores = {}
        for genre_id, tmpl in GENRE_TEMPLATES.items():
            score = 0
            for kw in tmpl["keywords"]:
                if kw.lower() in theme_lower:
                    score += 1
            scores[genre_id] = score

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
        return "ai_tech"
    except Exception as e:
        logger.warning(f"ジャンル判定失敗: {e}")
        return "ai_tech"


def get_template(genre: str) -> dict:
    """指定ジャンルのテンプレートを取得。存在しなければai_techにフォールバック"""
    return GENRE_TEMPLATES.get(genre, GENRE_TEMPLATES["ai_tech"])


# ===== 3軸タイトル生成プロンプト構築 =====

def build_title_generation_prompt(theme: str, genre: str) -> tuple[str, dict]:
    """
    3軸（ジャンルKW × 切り口 × 感情トリガー）でタイトル生成用プロンプトを構築する。

    Returns:
        (prompt_text, axes_metadata)
        axes_metadata は tracking 用: {"genre_keyword": ..., "angle": ..., "emotion": ...}
    """
    try:
        tmpl = get_template(genre)
        keywords = tmpl["keywords"]

        # 各軸からランダムに選択
        genre_keyword = random.choice(keywords)
        angle = random.choice(TITLE_ANGLES)
        emotion = random.choice(EMOTION_TRIGGERS)

        axes_metadata = {
            "genre": genre,
            "genre_keyword": genre_keyword,
            "angle": angle,
            "emotion": emotion,
        }

        title_patterns_text = "\n".join(f"  - {p}" for p in tmpl["title_patterns"])
        all_keywords_sample = ", ".join(random.sample(keywords, min(10, len(keywords))))

        prompt = (
            f"テーマ「{theme}」のnote記事タイトルを5つ提案してください。\n\n"
            f"## 最重要: Build in Publicドキュメンタリー方針\n"
            f"テーマは「SYUTAINβで実際に何が起きたか」に基づくこと。\n"
            f"外部AIニュース解説（「GPTの使い方」等）は禁止。\n\n"
            f"## 3軸タイトル生成ルール\n"
            f"以下の3つの軸を全て組み合わせたタイトルにすること:\n\n"
            f"### Axis 1: ジャンルキーワード（必ず含める）\n"
            f"  メインKW: {genre_keyword}\n"
            f"  関連KW候補: {all_keywords_sample}\n\n"
            f"### Axis 2: 切り口\n"
            f"  今回の切り口: **{angle}**\n"
            f"  ({angle}の視点でテーマを料理すること)\n\n"
            f"### Axis 3: 感情トリガー\n"
            f"  今回の感情: **{emotion}**\n"
            f"  (読者の{emotion}を刺激する表現を入れること)\n\n"
            f"## 参考タイトルパターン\n{title_patterns_text}\n\n"
            f"## SEO・拡散力最適化\n"
            f"- 検索されやすい具体的なキーワードを含める（「AI」「自動化」「非エンジニア」「分散システム」「月○円」等）\n"
            f"- 数字を含める（行数、コスト、日数、エラー回数など実データ）\n"
            f"- 「○○した話」「○○の記録」「○○で学んだこと」形式は検索+SNS両方に強い\n"
            f"- 対象読者を絞り込むワードを入れる（「非エンジニア」「一人で」「個人開発」等）\n\n"
            f"## 制約\n"
            f"- 各タイトルは15-25文字（端的に。長いタイトルは即却下される）\n"
            f"- 具体的な数字を含める\n"
            f"- 「いかがでしょうか」系の弱い表現は禁止\n"
            f"- 5つのタイトルのみを改行区切りで出力。番号・説明不要。\n"
        )

        return prompt, axes_metadata

    except Exception as e:
        logger.warning(f"タイトル生成プロンプト構築失敗: {e}")
        fallback_prompt = (
            f"テーマ「{theme}」のnote有料記事タイトルを5つ提案してください。\n"
            "各タイトルは40文字以内、具体的な数字を含め、改行区切りで出力。"
        )
        return fallback_prompt, {"genre": genre, "genre_keyword": "", "angle": "", "emotion": ""}


def build_structure_prompt_with_template(theme: str, genre: str, target_length: int) -> str:
    """ジャンルテンプレートを使った構成案プロンプトを構築する"""
    try:
        tmpl = get_template(genre)

        free_part = tmpl["free_part"]
        paid_part = tmpl["paid_part"]
        cta_sample = random.choice(tmpl["cta_patterns"])
        word_min, word_max = tmpl["word_count_range"]

        prompt = (
            f"テーマ「{theme}」で{target_length}字以上のnote有料記事（ジャンル: {tmpl['name']}）の構成案を作成してください。\n\n"
            f"## ジャンル別テンプレート\n\n"
            f"### 無料パート（冒頭1500-2000字）\n"
            f"**フック**: {free_part['hook']}\n"
            f"**導入**: {free_part['intro']}\n"
            f"**課題提示**: {free_part['problem_statement']}\n\n"
            f"### 有料パート（{word_min}-{word_max}字）\n"
            f"**メインコンテンツ**: {paid_part['main_content']}\n"
            f"**ステップ**: {paid_part['steps']}\n"
            f"**事例**: {paid_part['examples']}\n"
            f"**まとめ**: {paid_part['summary']}\n\n"
            f"### CTA例\n{cta_sample}\n\n"
            f"各フェーズについて2-3行で具体的に何を書くか記述してください。\n"
            f"【重要】構成は最低7セクション、各セクションに3つ以上のサブセクション（具体例・手順・データ）を含めること。\n"
            f"【重要】架空のエピソードを作らない。島原大知が実際に経験しうることだけ書く。\n"
        )
        return prompt

    except Exception as e:
        logger.warning(f"構成案プロンプト構築失敗: {e}")
        return f"テーマ「{theme}」で{target_length}字以上のnote有料記事の構成案を作成してください。"


def get_price_by_word_count(word_count: int) -> int | None:
    """文字数から価格を自動設定する。6000字未満はNone（パッケージ対象外）"""
    if word_count >= 12000:
        return 1980  # premium
    elif word_count >= 8000:
        return 980  # standard
    elif word_count >= 6000:
        return 480  # entry level
    else:
        return None  # パッケージ対象外
