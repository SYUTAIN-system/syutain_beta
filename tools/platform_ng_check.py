"""
SYUTAINβ V25 プラットフォームNGワードチェック

AT Protocol (Bluesky) / X利用規約に基づくNGワードリスト。
戦略的NG（CONTENT_STRATEGY.md）とは別レイヤー。
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("syutain.platform_ng_check")

# AT Protocol / Bluesky Community Guidelines ベースのNGワード
# 暴力、ヘイト、違法行為、スパム関連
BLUESKY_NG_PATTERNS = [
    # 暴力・脅迫
    r"殺す|殺してやる|死ね|死ねばいい|ぶっ殺す|爆破する|テロ",
    # ヘイトスピーチ
    r"劣等|人種差別|民族浄化|ゴキブリ(?:ども|ら)|害虫(?:ども|ら)",
    # 詐欺・違法
    r"詐欺(?:師)?で稼|マネーロンダリング|不正送金|違法薬物|脱税(?:方法|のやり方)",
    # スパム的表現
    r"(?:今すぐ|急いで)(?:クリック|登録|購入)|(?:限定|特別)(?:オファー|チャンス)(?:！|!){2,}",
    # 個人情報流出誘導
    r"パスワードを教え|クレカ番号|社会保障番号|マイナンバーを",
]

# CONTENT_STRATEGY.md の禁止語句（戦略的NG — 別レイヤーだが同時にチェック）
STRATEGY_NG_WORDS = [
    "誰でも簡単に",
    "絶対稼げる",
    "完全自動で放置",
    "AIに任せればOK",
    "最短で月100万",
    "革命",
    "覇権",
    "無双",
]


def check_platform_ng(text: str, platform: str = "bluesky") -> dict:
    """
    投稿テキストのNGワードチェック

    Returns:
        {
            "passed": bool,
            "violations": [{"type": "platform"|"strategy", "matched": str, "pattern": str}],
        }
    """
    violations = []

    # プラットフォームNGチェック
    for pattern in BLUESKY_NG_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            violations.append({
                "type": "platform",
                "matched": match.group(),
                "pattern": pattern[:30],
            })

    # 戦略NGワードチェック
    for ng in STRATEGY_NG_WORDS:
        if ng in text:
            violations.append({
                "type": "strategy",
                "matched": ng,
                "pattern": "CONTENT_STRATEGY禁止語句",
            })

    return {
        "passed": len(violations) == 0,
        "violations": violations,
    }


async def check_and_log(text: str, platform: str = "bluesky") -> dict:
    """NGワードチェック + event_log記録"""
    result = check_platform_ng(text, platform)

    if not result["passed"]:
        try:
            from tools.event_logger import log_event
            await log_event(
                "sns.ng_word_detected", "sns",
                {
                    "platform": platform,
                    "violations": result["violations"],
                    "text_preview": text[:80],
                },
                severity="warning",
            )
        except Exception:
            pass

    return result
