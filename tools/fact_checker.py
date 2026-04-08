"""SNS投稿/記事のファクトチェック — 4層構造 + 一次ソース検証

Layer 1: DB実データ突合（コストゼロ）— SYUTAINβの数字を実DBと照合
Layer 2: intel_items照合（コストゼロ）— 既存の検証済み情報と突合
Layer 3: Tavily検索（¥0.1/回）— 外部事実の裏取り（外部主張がある場合のみ）
Layer 4: 一次ソース検証 — 検索結果に公式サイト/論文/プレスリリースがあるか

原則: 確認できたことだけ断定、それ以外は留保表現に修正
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("syutain.fact_checker")

# 一次ソースと認められるドメインパターン
PRIMARY_SOURCE_DOMAINS = [
    r"\.go\.jp",           # 政府機関
    r"\.ac\.jp",           # 大学
    r"arxiv\.org",         # 論文
    r"github\.com",        # OSS
    r"openai\.com",        # OpenAI公式
    r"anthropic\.com",     # Anthropic公式
    r"google\.com/blog",   # Google公式ブログ
    r"deepmind\.google",   # DeepMind公式
    r"meta\.com",          # Meta公式
    r"x\.ai",              # xAI公式
    r"huggingface\.co",    # HuggingFace
    r"nvidia\.com",        # NVIDIA公式
    r"note\.com/5070",     # 島原のnote
    r"prtimes\.jp",        # プレスリリース
    r"reuters\.",          # ロイター
    r"nikkei\.com",        # 日経
]


async def check_facts(text: str, check_level: str = "sns") -> dict:
    """投稿/記事のファクトチェック

    Args:
        text: チェック対象のテキスト
        check_level: "sns"（軽量、Layer 1-2のみ）or "article"（全層）

    Returns:
        {
            "passed": bool,
            "issues": [{"claim": str, "verdict": str, "source": str}],
            "suggestions": [{"original": str, "suggested": str}],
            "cost_jpy": float,
        }
    """
    result = {"passed": True, "issues": [], "suggestions": [], "cost_jpy": 0.0}

    # === Layer 1: DB実データ突合 ===
    try:
        db_issues = await _check_db_facts(text)
        result["issues"].extend(db_issues)
    except Exception as e:
        logger.debug(f"Layer 1 DB突合失敗: {e}")

    # === Layer 2: intel_items照合 ===
    try:
        intel_issues = await _check_intel_facts(text)
        result["issues"].extend(intel_issues)
    except Exception as e:
        logger.debug(f"Layer 2 intel照合失敗: {e}")

    # === Layer 3: Tavily検索（記事のみ、または外部事実を含むSNS） ===
    external_claims = _extract_external_claims(text)
    if external_claims and (check_level == "article" or len(external_claims) >= 2):
        try:
            tavily_issues, cost = await _check_tavily(external_claims)
            result["issues"].extend(tavily_issues)
            result["cost_jpy"] += cost
        except Exception as e:
            logger.debug(f"Layer 3 Tavily検索失敗: {e}")

    # === Layer 4: 一次ソース検証 ===
    for issue in result["issues"]:
        if issue.get("source_url"):
            is_primary = _is_primary_source(issue["source_url"])
            issue["primary_source"] = is_primary
            if not is_primary:
                # 一次ソースでない → 留保表現を提案
                claim = issue.get("claim", "")
                if claim:
                    result["suggestions"].append({
                        "original": claim,
                        "suggested": f"〜とされている（{claim}）",
                        "reason": "一次ソースが確認できないため留保表現を推奨",
                    })

    # 合否判定
    critical = [i for i in result["issues"] if i.get("verdict") == "false"]
    if len(critical) >= 2:
        result["passed"] = False

    return result


async def _check_db_facts(text: str) -> list[dict]:
    """Layer 1: SYUTAINβの実データとの突合"""
    issues = []
    from tools.db_pool import get_connection

    # テキストから数字を含む主張を抽出
    number_claims = re.findall(r'(?:Python|コード).{0,10}(\d[\d,]+)\s*行', text)
    cost_claims = re.findall(r'[¥￥]\s*([\d,]+(?:\.\d+)?)', text)
    llm_claims = re.findall(r'(?:LLM|呼び出し).{0,10}(\d[\d,]+)\s*回', text)

    async with get_connection() as conn:
        # コード行数チェック（実際の行数と比較）
        if number_claims:
            try:
                import subprocess
                actual = subprocess.run(
                    ["find", "/Users/daichi/syutain_beta", "-name", "*.py",
                     "-not", "-path", "*/venv/*", "-not", "-path", "*/__pycache__/*"],
                    capture_output=True, text=True,
                )
                files = [f for f in actual.stdout.strip().split("\n") if f]
                total_lines = 0
                for f in files:
                    try:
                        total_lines += sum(1 for _ in open(f))
                    except Exception:
                        pass
                for claim_num in number_claims:
                    claimed = int(claim_num.replace(",", ""))
                    if abs(claimed - total_lines) > total_lines * 0.3:  # 30%以上の乖離
                        issues.append({
                            "claim": f"コード{claimed}行",
                            "verdict": "inaccurate",
                            "detail": f"実際は{total_lines}行（{abs(claimed-total_lines)}行の差）",
                            "source": "db_check",
                        })
            except Exception:
                pass

        # LLM呼び出し回数チェック
        if llm_claims:
            try:
                actual_calls = await conn.fetchval(
                    "SELECT COUNT(*) FROM llm_usage_log"
                )
                for claim_num in llm_claims:
                    claimed = int(claim_num.replace(",", ""))
                    if actual_calls and abs(claimed - actual_calls) > actual_calls * 0.3:
                        issues.append({
                            "claim": f"LLM {claimed}回",
                            "verdict": "inaccurate",
                            "detail": f"実際は{actual_calls}回",
                            "source": "db_check",
                        })
            except Exception:
                pass

    return issues


async def _check_intel_facts(text: str) -> list[dict]:
    """Layer 2: intel_itemsの検証済み情報との照合"""
    issues = []
    from tools.db_pool import get_connection

    # テキストから外部の固有名詞・サービス名を抽出
    external_entities = re.findall(r'([A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)*)', text)
    # 既知のSYUTAINβ内部用語を除外
    internal_terms = {"SYUTAINβ", "SYUTAIN", "Claude", "Python", "ALPHA", "BRAVO",
                      "CHARLIE", "DELTA", "Discord", "Bluesky", "Threads", "PostgreSQL",
                      "NATS", "Ollama", "FastAPI", "Playwright", "CORTEX", "FANG",
                      "NERVE", "FORGE", "MEDULLA", "SCOUT", "Tailscale", "OpenRouter"}
    external_only = [e for e in external_entities if e not in internal_terms and len(e) > 2]

    if external_only:
        async with get_connection() as conn:
            for entity in external_only[:3]:  # 最大3件チェック
                try:
                    found = await conn.fetchval(
                        """SELECT COUNT(*) FROM intel_items
                        WHERE (title ILIKE $1 OR summary ILIKE $1)
                        AND created_at > NOW() - INTERVAL '30 days'""",
                        f"%{entity}%",
                    )
                    if found and found > 0:
                        pass  # intel_itemsに存在 → 検証済み
                    # 見つからなくてもissueにはしない（未知≠虚偽）
                except Exception:
                    pass

    return issues


def _extract_external_claims(text: str) -> list[str]:
    """テキストから外部事実の主張を抽出"""
    claims = []
    # 「○○が△△を発表/公開/リリース」パターン
    patterns = [
        r'([A-Za-z]+(?:\s[A-Za-z]+)*)\s*(?:が|は).{0,20}(?:発表|公開|リリース|導入|採用|開発)',
        r'(?:調査|レポート|報告).{0,10}(?:によると|では|によれば)',
        r'\d+%\s*(?:の|が).{5,30}(?:している|した|である)',
    ]
    for p in patterns:
        matches = re.findall(p, text)
        if matches:
            if isinstance(matches[0], str):
                claims.extend(matches)
            else:
                claims.extend([m[0] for m in matches])
    return claims[:5]


async def _check_tavily(claims: list[str]) -> tuple[list[dict], float]:
    """Layer 3: Tavily Search APIで外部事実を裏取り"""
    issues = []
    total_cost = 0.0

    try:
        from tools.tavily_client import search_tavily
    except ImportError:
        return issues, 0.0

    for claim in claims[:3]:  # 最大3件
        try:
            results = await search_tavily(claim, max_results=3)
            total_cost += 0.01  # Tavily 1検索 ≈ ¥0.01

            if results:
                # 検索結果からURLを取得
                urls = [r.get("url", "") for r in results if r.get("url")]
                has_primary = any(_is_primary_source(u) for u in urls)

                if not has_primary and urls:
                    issues.append({
                        "claim": claim,
                        "verdict": "unverified",
                        "detail": f"検索結果あり({len(results)}件)だが一次ソースなし",
                        "source": "tavily",
                        "source_url": urls[0] if urls else "",
                    })
            else:
                issues.append({
                    "claim": claim,
                    "verdict": "not_found",
                    "detail": "検索結果なし",
                    "source": "tavily",
                    "source_url": "",
                })
        except Exception as e:
            logger.debug(f"Tavily検索失敗 ({claim[:30]}): {e}")

    return issues, total_cost


def _is_primary_source(url: str) -> bool:
    """URLが一次ソースかどうか判定"""
    if not url:
        return False
    for pattern in PRIMARY_SOURCE_DOMAINS:
        if re.search(pattern, url):
            return True
    return False


def apply_hedging(text: str, suggestions: list[dict]) -> str:
    """留保表現を自動適用（断定→「〜とされている」に修正）"""
    for s in suggestions:
        original = s.get("original", "")
        suggested = s.get("suggested", "")
        if original and suggested and original in text:
            text = text.replace(original, suggested, 1)
    return text
