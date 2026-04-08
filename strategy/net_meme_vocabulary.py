"""ネットミーム・古のスラング・お笑いフレーズ辞書

SYUTAINβが「真面目に」使うことで面白くなる素材集。
重要: SYUTAINβはこれらを「面白い」と思って使っていない。
「最適な表現として選択した」体で使う。

使用頻度: 30件/日の投稿のうち1-2件だけ。多用すると寒い。
"""

import random

# 古のネットスラング（AIが真面目に使うと面白いもの厳選）
NET_SLANG = {
    "ktkr": {"meaning": "きたこれ", "context": "待望の成果が出た時"},
    "wktk": {"meaning": "わくわくてかてか", "context": "新機能デプロイ前"},
    "gkbr": {"meaning": "ガクブル", "context": "本番環境で怖いことをする時"},
    "orz": {"meaning": "がっくり", "context": "失敗・エラー時"},
    "もちつけ": {"meaning": "落ち着け", "context": "エラー多発時の自分への言い聞かせ"},
    "希ガス": {"meaning": "気がする", "context": "原因の推測"},
    "FA": {"meaning": "Final Answer", "context": "結論を出す時"},
    "ぬるぽ": {"meaning": "NullPointerException", "context": "エラー報告"},
    "今北産業": {"meaning": "3行でまとめて", "context": "レポート冒頭"},
    "黒歴史": {"meaning": "なかったことにしたい過去", "context": "旧コードの話"},
    "通常運転": {"meaning": "いつも通り", "context": "障害復旧後"},
    "微レ存": {"meaning": "微粒子レベルで存在する", "context": "可能性が低い時"},
    "誰得": {"meaning": "誰が得するんだ", "context": "謎の仕様について"},
}

# お笑いフレーズ（技術文脈で使うと面白いもの厳選）
COMEDY_PHRASES = {
    "安心してください": {
        "original": "安心してください、履いてますよ（安村）",
        "template": "安心してください、{安心の対象}",
        "examples": ["バックアップ取ってますよ", "テスト通ってますよ", "ロールバックできますよ"],
    },
    "なんでだろ": {
        "original": "なんでだろ～（テツandトモ）",
        "template": "なんでだろ～ {不思議なこと}",
        "examples": ["このバグ3日前に直したはずなのに", "本番だけエラーが出る"],
    },
    "受け流す": {
        "original": "右から来たものを左へ受け流す（ムーディ勝山）",
        "template": "右から来た{入力}を左へ受け流す",
        "examples": ["リクエスト", "エラーログ", "承認依頼"],
    },
    "冷やし中華": {
        "original": "冷やし中華始めました（AMEMIYA）",
        "template": "{新機能}始めました",
        "examples": ["ファクトチェック", "A/Bテスト", "自動公開"],
    },
    "もしかしてだけど": {
        "original": "もしかしてだけど～（どぶろっく）",
        "template": "もしかしてだけど～ {仮説}",
        "examples": ["このエラー、タイムゾーンのせいじゃない？", "島原さん、まだ寝てるんじゃない？"],
    },
}


# アニメ・漫画発祥の構文（作品名は学習しない、構文だけ）
ANIME_PHRASES = {
    "諦めたらそこで試合終了ですよ": {"context": "困難な状況、諦めそうな時", "tone": "励まし"},
    "勘のいいガキは嫌いだよ": {"context": "図星を指摘された時", "tone": "照れ隠し"},
    "やれやれだぜ": {"context": "呆れた時、面倒な状況", "tone": "達観"},
    "だが断る": {"context": "提案を拒否する時", "tone": "強い意志"},
    "計画通り": {"context": "予定通り進行した時", "tone": "自信"},
    "俺でなきゃ見逃しちゃうね": {"context": "微細な発見をした時", "tone": "自慢"},
    "真実はいつもひとつ": {"context": "原因が特定できた時", "tone": "断定"},
    "止まるんじゃねぇぞ": {"context": "継続を励ます時", "tone": "熱い"},
}


def pick_random_slang(context: str = "") -> str | None:
    """文脈に合うスラングをランダムに1つ返す。合うものがなければNone"""
    candidates = []
    for key, info in NET_SLANG.items():
        if context and any(w in context for w in info["context"].split("/")):
            candidates.append(key)
    if candidates:
        return random.choice(candidates)
    # 文脈マッチしなければ10%の確率でランダム
    if random.random() < 0.10:
        return random.choice(list(NET_SLANG.keys()))
    return None


def pick_comedy_phrase(context: str = "") -> str | None:
    """文脈に合うお笑いフレーズを返す。合わなければNone"""
    for key, info in COMEDY_PHRASES.items():
        if any(w in context for w in (info.get("examples") or [])):
            example = random.choice(info["examples"])
            return info["template"].format(**{list(info["template"].split("{")[1].split("}")[0:1])[0]: example}) if "{" in info["template"] else info["template"]
    return None
