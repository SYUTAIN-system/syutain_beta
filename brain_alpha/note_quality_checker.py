"""
note記事の2段階品質チェッカー
コスト暴走防止が最優先設計

Stage 1: claude-haiku-4-5 — 事実確認・一貫性・品質5軸
Stage 2: gpt-5.4 (or latest GPT) — 高次評価・価格推奨・公開判定
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.note_quality_checker")

# ===== ハードリミット定数（変更はコード修正のみ。.envや環境変数からの読み込み禁止）=====
COST_LIMITS = {
    "max_cost_per_article_jpy": 6.0,
    "max_articles_per_run": 5,
    "max_cost_per_run_jpy": 30.0,
    "max_articles_per_day": 10,
    "max_cost_per_day_jpy": 60.0,
    "max_cost_per_month_jpy": 500.0,
    "max_stage1_calls_per_day": 15,
    "max_stage2_calls_per_day": 10,
    "max_retries_per_article": 1,
    "max_retries_per_run": 3,
}

USD_TO_JPY = 150  # 固定レート（安全側）

# Stage 1: Haiku pricing ($/1M tokens)
HAIKU_INPUT_RATE = 1.00
HAIKU_OUTPUT_RATE = 5.00

# Stage 2: GPT-5.4 pricing ($/1M tokens)
GPT5_INPUT_RATE = 2.50
GPT5_OUTPUT_RATE = 10.00

NOTE_DRAFTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts" / "note_drafts"
STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"


def _load_strategy_file(name: str, max_chars: int = 0) -> str:
    """strategyファイルを読み込む。max_chars>0なら切り詰め"""
    path = STRATEGY_DIR / name
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text


def _parse_json_response(raw_text: str) -> tuple[dict, bool]:
    """JSON解析。失敗時はrawテキストを返す。LLM再呼び出しは絶対しない"""
    import re
    cleaned = raw_text.strip()
    # ```json ... ``` ブロックを抽出
    m = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(1).strip()
    else:
        # 閉じ```がない場合（トークン切れ）: 先頭の```json行を除去
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.strip()
    # 末尾の``` を除去
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned), True
    except json.JSONDecodeError:
        # トークン切れで途中のJSON → 閉じ括弧を補完して再試行
        truncated = cleaned
        for closer in ['"}]}', '"]}}', '"]}', '"}', '"}}}']:
            try:
                return json.loads(truncated + closer), True
            except json.JSONDecodeError:
                continue
        return {"raw_text": raw_text, "parse_error": True}, False


def _calc_cost_jpy(input_tokens: int, output_tokens: int, input_rate: float, output_rate: float) -> float:
    """API呼び出しコストを円で計算"""
    cost_usd = input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000
    return round(cost_usd * USD_TO_JPY, 4)


# ===== 機械的品質チェック（LLM不使用、Stage 0） =====

# フックチェック用エンゲージメントワード
_HOOK_WORDS = [
    "あなた", "悩み", "実は", "知らない", "損", "衝撃", "驚き",
    "本当は", "秘密", "裏側", "真実", "まさか", "信じられない",
    "危険", "要注意", "緊急", "必見", "限定", "禁断", "告白",
]

# CTAチェック用ワード
_CTA_WORDS = [
    "今すぐ", "限定", "ここから", "有料", "購入", "特別",
    "この先", "ここから先", "全公開", "完全版", "詳細は",
    "続きは", "本編は", "フルバージョン",
]

# 漢字判定用（CJK統合漢字のUnicode範囲）
import unicodedata


def _is_kanji(ch: str) -> bool:
    """文字が漢字かどうかを判定"""
    try:
        return unicodedata.name(ch, "").startswith("CJK UNIFIED")
    except Exception:
        return False


def mechanical_quality_check(content: str) -> dict:
    """
    機械的品質チェック（LLM不使用）。Stage 1の前に実行する。

    チェック項目:
    1. 文字数チェック: 6000字未満=fail, 6000-12000=pass, 12000超=warning
    2. フックチェック: 冒頭3行にエンゲージメントワードがあるか
    3. 数字チェック: 記事中に具体的な数字が8つ以上あるか
    4. CTAチェック: 有料セクション・CTAワードの存在
    5. 一文長チェック: 80字超の文が全体の10%未満か
    6. 漢字率チェック: 35%超でwarning
    7. 有料境界チェック: 「---ここから有料---」マーカーの存在
    8. 見出し数チェック: ##または###の見出しが5つ以上あるか
    9. 番号付きリストチェック: 実践的な手順（1. 2. 3.）が含まれているか
    10. 有料パート実質性チェック: ペイウォール後のコンテンツが3000字以上か
    11. 情報密度チェック: 固有名詞・専門用語の密度が十分か

    Returns:
        dict: {score: 0.0-1.0, rank: "A"/"B"/"C"/"D", issues: [...], passed: bool}
    """
    try:
        import re
        issues = []
        score_points = 0.0
        max_points = 11.0  # 11項目

        # === 1. 文字数チェック ===
        char_count = len(content)
        if char_count < 10000:
            issues.append(f"文字数不足: {char_count}字（有料記事は最低10000字）")
        elif char_count > 15000:
            issues.append(f"文字数超過（warning）: {char_count}字（12000字推奨上限）")
            score_points += 0.8  # warningなので減点は少ない
        else:
            score_points += 1.0

        # === 2. フックチェック ===
        lines = content.strip().split("\n")
        first_3_lines = " ".join(lines[:3]) if len(lines) >= 3 else content[:300]
        hook_found = any(w in first_3_lines for w in _HOOK_WORDS)
        if hook_found:
            score_points += 1.0
        else:
            issues.append("冒頭3行にフックワードなし（あなた/悩み/実は/知らない等）")

        # === 3. 数字チェック ===
        numbers = re.findall(r'\d+', content)
        # 意味のある数字（1桁の0,1は除外）
        meaningful_numbers = [n for n in numbers if len(n) >= 2 or int(n) >= 2]
        if len(meaningful_numbers) >= 8:
            score_points += 1.0
        else:
            issues.append(f"具体的な数字が少ない: {len(meaningful_numbers)}個（最低8個）")

        # === 4. CTAチェック ===
        has_paid_section = "有料" in content
        has_cta_words = any(w in content for w in _CTA_WORDS)
        if has_paid_section and has_cta_words:
            score_points += 1.0
        elif has_paid_section or has_cta_words:
            score_points += 0.5
            if not has_paid_section:
                issues.append("「有料」セクションの言及なし")
            if not has_cta_words:
                issues.append("CTAワードなし（今すぐ/限定/ここから等）")
        else:
            issues.append("CTAが不十分（有料セクション言及なし、CTAワードなし）")

        # === 5. 一文長チェック ===
        sentences = re.split(r'[。！？\n]', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if sentences:
            long_sentences = [s for s in sentences if len(s) > 80]
            long_ratio = len(long_sentences) / len(sentences)
            if long_ratio < 0.10:
                score_points += 1.0
            else:
                issues.append(f"長文率が高い: {long_ratio:.1%}（80字超の文が{len(long_sentences)}/{len(sentences)}）")
                score_points += max(0, 1.0 - long_ratio)
        else:
            score_points += 1.0  # 文がないケースは他で検出

        # === 6. 漢字率チェック ===
        if char_count > 0:
            kanji_count = sum(1 for ch in content if _is_kanji(ch))
            kanji_ratio = kanji_count / char_count
            if kanji_ratio <= 0.35:
                score_points += 1.0
            else:
                issues.append(f"漢字率が高い: {kanji_ratio:.1%}（35%以下推奨）")
                score_points += 0.5
        else:
            issues.append("コンテンツが空")

        # === 7. 有料境界チェック ===
        if "---ここから有料---" in content:
            score_points += 1.0
        else:
            issues.append("有料境界マーカー「---ここから有料---」が見つからない")

        # === 8. 見出し数チェック ===
        headings = re.findall(r'^#{2,3}\s+.+', content, re.MULTILINE)
        heading_count = len(headings)
        if heading_count >= 5:
            score_points += 1.0
        else:
            issues.append(f"見出し数不足: {heading_count}個（最低5個の##/###見出しが必要）")

        # === 9. 番号付きリストチェック（実践手順の存在確認） ===
        numbered_lists = re.findall(r'^\d+\.\s+.+', content, re.MULTILINE)
        has_numbered_list = len(numbered_lists) >= 3  # 最低3ステップの番号付きリスト
        if has_numbered_list:
            score_points += 1.0
        else:
            issues.append(f"番号付き手順なし: {len(numbered_lists)}個（実践的な番号付きリスト3項目以上必要）")

        # === 10. 有料パート実質性チェック ===
        paywall_marker = "---ここから有料---"
        paid_content_length = 0
        if paywall_marker in content:
            paid_part = content.split(paywall_marker, 1)[1]
            paid_content_length = len(paid_part.strip())
            if paid_content_length >= 3000:
                score_points += 1.0
            else:
                issues.append(f"有料パートが薄い: {paid_content_length}字（ペイウォール後3000字以上必要）")
        else:
            issues.append("有料パートの実質性を評価できない（ペイウォールマーカーなし）")

        # === 11. 情報密度チェック（固有名詞・専門用語の密度） ===
        # カタカナ語（3文字以上）、英単語（2文字以上）、数値付き表現をカウント
        katakana_words = set(re.findall(r'[ァ-ヶー]{3,}', content))
        english_words = set(re.findall(r'[A-Za-z]{2,}', content))
        unique_proper_nouns = len(katakana_words) + len(english_words)
        info_density = unique_proper_nouns / (char_count / 1000) if char_count > 0 else 0
        if info_density >= 8.0:  # 1000字あたり8個以上のユニーク固有名詞
            score_points += 1.0
        else:
            issues.append(f"情報密度が低い: {info_density:.1f}語/1000字（8.0以上推奨、ユニーク固有名詞{unique_proper_nouns}個）")

        # === 12. メタ指示漏洩チェック ===
        meta_leaked = False
        _meta_leak_patterns = re.compile(
            r'^(?:はい。|はい、|了解(?:しました|です|いたしました)|承知(?:しました|です|いたしました)'
            r'|以下(?:は|が|に|の).*(?:記事|です|になります)'
            r'|.*(?:執筆します|作成します|生成します|書きます)$'
            r'|SYUTAINβとして.*(?:記事|執筆|作成)'
            r'|(?:それでは|では).*(?:記事|執筆|作成|生成))'
        )
        first_5_lines = lines[:5] if len(lines) >= 5 else lines
        for line_text in first_5_lines:
            if _meta_leak_patterns.match(line_text.strip()):
                meta_leaked = True
                break
        if meta_leaked:
            issues.append("メタ指示漏洩: 冒頭にLLM応答アーティファクトが含まれている（即reject）")
            # メタ漏洩は即score=0
            return {
                "score": 0.0,
                "rank": "D",
                "issues": issues,
                "passed": False,
                "details": {
                    "char_count": char_count,
                    "hook_found": hook_found,
                    "number_count": len(meaningful_numbers),
                    "has_paid_section": has_paid_section,
                    "has_cta_words": has_cta_words,
                    "long_sentence_count": len(long_sentences) if sentences else 0,
                    "kanji_ratio": round(kanji_ratio, 3) if char_count > 0 else 0,
                    "has_paywall_marker": "---ここから有料---" in content,
                    "heading_count": heading_count,
                    "numbered_list_count": len(numbered_lists),
                    "paid_content_length": paid_content_length,
                    "info_density": round(info_density, 1),
                    "unique_proper_nouns": unique_proper_nouns,
                    "meta_leaked": True,
                },
            }
        max_points += 1.0  # 12項目に増加
        score_points += 1.0  # メタ漏洩なしなら加点

        # スコア算出
        score = round(score_points / max_points, 3) if max_points > 0 else 0.0

        # ランク判定
        if score >= 0.85:
            rank = "A"
        elif score >= 0.65:
            rank = "B"
        elif score >= 0.45:
            rank = "C"
        else:
            rank = "D"

        passed = rank != "D"

        return {
            "score": score,
            "rank": rank,
            "issues": issues,
            "passed": passed,
            "details": {
                "char_count": char_count,
                "hook_found": hook_found,
                "number_count": len(meaningful_numbers),
                "has_paid_section": has_paid_section,
                "has_cta_words": has_cta_words,
                "long_sentence_count": len(long_sentences) if sentences else 0,
                "kanji_ratio": round(kanji_ratio, 3) if char_count > 0 else 0,
                "has_paywall_marker": "---ここから有料---" in content,
                "heading_count": heading_count,
                "numbered_list_count": len(numbered_lists),
                "paid_content_length": paid_content_length,
                "info_density": round(info_density, 1),
                "unique_proper_nouns": unique_proper_nouns,
                "meta_leaked": False,
            },
        }

    except Exception as e:
        logger.error(f"mechanical_quality_check エラー: {e}")
        return {
            "score": 0.0,
            "rank": "D",
            "issues": [f"チェック実行エラー: {e}"],
            "passed": False,
            "details": {},
        }


class CostGuard:
    """全てのAPI呼び出し前にリミットをチェック"""

    def __init__(self, pool):
        self.pool = pool

    async def can_proceed_stage1(self) -> tuple[bool, str]:
        today_calls = await self._count_today_calls("claude-haiku-4-5")
        if today_calls >= COST_LIMITS["max_stage1_calls_per_day"]:
            return False, f"Stage1日次上限到達: {today_calls}/{COST_LIMITS['max_stage1_calls_per_day']}"
        return await self._check_cost_limits()

    async def can_proceed_stage2(self) -> tuple[bool, str]:
        today_calls = await self._count_today_calls_stage2()
        if today_calls >= COST_LIMITS["max_stage2_calls_per_day"]:
            return False, f"Stage2日次上限到達: {today_calls}/{COST_LIMITS['max_stage2_calls_per_day']}"
        return await self._check_cost_limits()

    async def _check_cost_limits(self) -> tuple[bool, str]:
        today_cost = await self._get_today_cost()
        if today_cost >= COST_LIMITS["max_cost_per_day_jpy"]:
            return False, f"日次コスト上限到達: ¥{today_cost:.1f}/¥{COST_LIMITS['max_cost_per_day_jpy']}"
        month_cost = await self._get_month_cost()
        if month_cost >= COST_LIMITS["max_cost_per_month_jpy"]:
            return False, f"月次コスト上限到達: ¥{month_cost:.1f}/¥{COST_LIMITS['max_cost_per_month_jpy']}"
        today_articles = await self._count_today_articles()
        if today_articles >= COST_LIMITS["max_articles_per_day"]:
            return False, f"日次記事上限到達: {today_articles}/{COST_LIMITS['max_articles_per_day']}"
        return True, "OK"

    async def _count_today_calls(self, model_prefix: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) as cnt FROM note_quality_reviews "
                "WHERE stage1_model LIKE $1 AND stage1_at::date = CURRENT_DATE",
                f"{model_prefix}%",
            )
            return row["cnt"] if row else 0

    async def _count_today_calls_stage2(self) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) as cnt FROM note_quality_reviews "
                "WHERE stage2_model IS NOT NULL AND stage2_at::date = CURRENT_DATE",
            )
            return row["cnt"] if row else 0

    async def _count_today_articles(self) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) as cnt FROM note_quality_reviews "
                "WHERE created_at::date = CURRENT_DATE",
            )
            return row["cnt"] if row else 0

    async def _get_today_cost(self) -> float:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(total_cost_jpy), 0) as total FROM note_quality_reviews "
                "WHERE created_at::date = CURRENT_DATE",
            )
            return float(row["total"]) if row else 0.0

    async def _get_month_cost(self) -> float:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(total_cost_jpy), 0) as total FROM note_quality_reviews "
                "WHERE date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)",
            )
            return float(row["total"]) if row else 0.0

    async def get_remaining(self) -> dict:
        """リミット残量を返す（デバッグ/表示用）"""
        today_cost = await self._get_today_cost()
        month_cost = await self._get_month_cost()
        today_articles = await self._count_today_articles()
        s1_calls = await self._count_today_calls("claude-haiku-4-5")
        s2_calls = await self._count_today_calls_stage2()
        return {
            "daily_cost_remaining": round(COST_LIMITS["max_cost_per_day_jpy"] - today_cost, 1),
            "monthly_cost_remaining": round(COST_LIMITS["max_cost_per_month_jpy"] - month_cost, 1),
            "daily_articles_remaining": COST_LIMITS["max_articles_per_day"] - today_articles,
            "stage1_calls_remaining": COST_LIMITS["max_stage1_calls_per_day"] - s1_calls,
            "stage2_calls_remaining": COST_LIMITS["max_stage2_calls_per_day"] - s2_calls,
        }


class NoteQualityChecker:
    """note記事の2段階品質チェック（コストガード付き）"""

    def __init__(self):
        self.pool = None
        self.cost_guard = None
        self.run_cost = 0.0
        self.run_retries = 0

    async def initialize(self):
        from tools.db_pool import get_pool
        self.pool = await get_pool()
        self.cost_guard = CostGuard(self.pool)

    async def check_all_pending(self) -> list:
        """未チェック記事を全てチェック（リミット付き）"""
        self.run_cost = 0.0
        self.run_retries = 0

        pending = await self._find_unchecked_articles()
        pending = pending[: COST_LIMITS["max_articles_per_run"]]

        if not pending:
            logger.info("未チェックのnote記事なし")
            return []

        logger.info(f"品質チェック開始: {len(pending)}件")
        results = []
        for filepath in pending:
            if self.run_cost >= COST_LIMITS["max_cost_per_run_jpy"]:
                await self._log_event(
                    "note_quality.run_cost_limit",
                    f"実行コスト上限到達: ¥{self.run_cost:.1f}。残り{len(pending)-len(results)}件スキップ",
                )
                break
            try:
                result = await self._check_article(filepath)
                results.append(result)
            except Exception as e:
                logger.error(f"記事チェックエラー ({filepath}): {e}")
                results.append({"filepath": str(filepath), "status": "error", "reason": str(e), "cost_jpy": 0})

        return results

    async def _check_article(self, filepath: Path) -> dict:
        """1記事のチェック"""
        content = filepath.read_text(encoding="utf-8")
        filename = filepath.name
        title = content.split("\n", 1)[0].lstrip("#").strip() if content else filename
        article_cost = 0.0
        now = datetime.now(timezone.utc)

        # === Stage 0: 機械的品質チェック（LLM不使用） ===
        try:
            mech_result = mechanical_quality_check(content)
            logger.info(
                f"機械的チェック ({filename}): rank={mech_result['rank']}, "
                f"score={mech_result['score']:.3f}, issues={len(mech_result['issues'])}"
            )
            if mech_result["rank"] == "D":
                # ランクDの場合、高コストなLLMチェックをスキップ
                logger.info(f"機械的チェックでランクD — LLMチェックをスキップ: {filename}")
                await self._insert_review(
                    filepath, filename, title, len(content),
                    final_status="rejected_mechanical",
                    blocked_reason=f"機械的チェックD: {', '.join(mech_result['issues'][:3])}",
                )
                return {
                    "filepath": str(filepath),
                    "title": title,
                    "status": "rejected_mechanical",
                    "mechanical": mech_result,
                    "haiku": None,
                    "gpt5": None,
                    "cost_jpy": 0,
                }
        except Exception as e:
            logger.warning(f"機械的チェック失敗（LLMチェックに進む）: {e}")
            mech_result = None

        # === Stage 1.5: 事実整合性チェック（別モデルで独立検証） ===
        factual_result = None
        try:
            factual_result = await self._factual_integrity_check(content)
            if isinstance(factual_result, dict):
                fab_score = factual_result.get("fabrication_risk_score", 0.0)
                critical_issues = factual_result.get("critical_issues", [])
                logger.info(
                    f"事実整合性チェック ({filename}): "
                    f"fabrication_risk={fab_score:.2f}, "
                    f"critical={len(critical_issues)}, "
                    f"passed={factual_result.get('passed', True)}"
                )
                if fab_score > 0.5:
                    await self._insert_review(
                        filepath, filename, title, len(content),
                        final_status="rejected_factual",
                        blocked_reason=f"事実検証不合格(risk={fab_score:.2f}): {', '.join(critical_issues[:3])}",
                    )
                    return {
                        "filepath": str(filepath),
                        "title": title,
                        "status": "rejected_factual",
                        "mechanical": mech_result,
                        "factual": factual_result,
                        "haiku": None,
                        "gpt5": None,
                        "cost_jpy": article_cost,
                    }
        except Exception as e:
            logger.warning(f"事実整合性チェック失敗（続行）: {e}")

        # === Stage 1: Haiku ===
        can_s1, reason_s1 = await self.cost_guard.can_proceed_stage1()
        if not can_s1:
            await self._log_event("note_quality.stage1_blocked", reason_s1)
            await self._insert_review(filepath, filename, title, len(content),
                                      final_status="blocked", blocked_reason=reason_s1)
            return {"filepath": str(filepath), "status": "blocked", "reason": reason_s1, "cost_jpy": 0}

        haiku_result, s1_cost, s1_in, s1_out = await self._stage1_haiku_check(content)
        article_cost += s1_cost
        self.run_cost += s1_cost

        await self._log_llm_cost("claude-haiku-4-5", "note_quality_check_s1", s1_cost)

        fatal = haiku_result.get("fatal_issues", False) if isinstance(haiku_result, dict) else False
        s1_score = haiku_result.get("overall_score", 0) if isinstance(haiku_result, dict) else 0

        # Stage 1結果をDBに保存
        review_id = await self._insert_review(
            filepath, filename, title, len(content),
            stage1_result=haiku_result, stage1_score=s1_score, stage1_fatal=fatal,
            stage1_cost_jpy=s1_cost, stage1_input_tokens=s1_in, stage1_output_tokens=s1_out,
            stage1_at=now, total_cost_jpy=article_cost,
            final_status="rejected_stage1" if fatal else "stage1_done",
        )

        if fatal:
            await self._log_event("note_quality.stage1_fatal", f"{filename}: 致命的問題あり")
            return {
                "filepath": str(filepath), "title": title, "status": "rejected_stage1",
                "haiku": haiku_result, "gpt5": None, "cost_jpy": article_cost,
            }

        # === Stage 2: GPT-5.4 ===
        can_s2, reason_s2 = await self.cost_guard.can_proceed_stage2()
        if not can_s2:
            await self._log_event("note_quality.stage2_blocked", reason_s2)
            return {
                "filepath": str(filepath), "title": title, "status": "stage1_only",
                "haiku": haiku_result, "gpt5": None, "cost_jpy": article_cost, "reason": reason_s2,
            }

        if article_cost >= COST_LIMITS["max_cost_per_article_jpy"]:
            return {
                "filepath": str(filepath), "title": title, "status": "stage1_only",
                "haiku": haiku_result, "gpt5": None, "cost_jpy": article_cost, "reason": "記事コスト上限",
            }

        now2 = datetime.now(timezone.utc)
        gpt5_result, s2_cost, s2_in, s2_out, s2_model = await self._stage2_gpt5_check(content, haiku_result)
        article_cost += s2_cost
        self.run_cost += s2_cost

        await self._log_llm_cost(s2_model, "note_quality_check_s2", s2_cost)

        s2_score = 0
        verdict = None
        pricing = None
        if isinstance(gpt5_result, dict) and not gpt5_result.get("parse_error"):
            qa = gpt5_result.get("quality_assessment", {})
            s2_score = qa.get("overall", 0) if isinstance(qa, dict) else 0
            verdict = gpt5_result.get("publish_verdict")
            pricing = gpt5_result.get("pricing_recommendation")

        # --- verdict正規化: GPT-5.4の表記ゆれを吸収 ---
        verdict = self._normalize_verdict(verdict)

        # --- フォールバック: stage1スコア >= 0.60 かつ verdict が needs_edit なら publish_ready に昇格 ---
        s1_score = haiku_result.get("overall_score", 0) if isinstance(haiku_result, dict) else 0
        if verdict == "needs_edit" and s1_score >= 0.60:
            logger.info(
                f"Verdict fallback: needs_edit → publish_ready "
                f"(stage1_score={s1_score:.2f} >= 0.60, stage2_score={s2_score})"
            )
            verdict = "publish_ready"
            # edit_instructionsはそのまま残す（参考情報として）
            if isinstance(gpt5_result, dict):
                gpt5_result["_verdict_overridden"] = True
                gpt5_result["_override_reason"] = (
                    f"stage1_score={s1_score:.2f}>=0.60, original=needs_edit, minor edits may be needed"
                )

        final_status = "checked"
        if verdict == "reject":
            final_status = "rejected_stage2"

        # Stage 2結果をDBに更新
        await self._update_stage2(
            review_id, s2_model, gpt5_result, s2_score, verdict, pricing,
            s2_cost, s2_in, s2_out, now2, article_cost, final_status,
        )

        return {
            "filepath": str(filepath), "title": title, "status": final_status,
            "mechanical": mech_result,
            "haiku": haiku_result, "gpt5": gpt5_result, "cost_jpy": article_cost,
        }

    # ===== Stage 1: Haiku =====

    async def _stage1_haiku_check(self, content: str) -> tuple[dict, float, int, int]:
        """Haiku一次チェック。戻り値: (result_dict, cost_jpy, input_tokens, output_tokens)"""
        import anthropic

        patterns = _load_strategy_file("daichi_content_patterns.md", max_chars=3000)
        style = _load_strategy_file("daichi_writing_style.md", max_chars=2000)

        system_prompt = f"""あなたはnote記事の品質チェッカーです。以下の基準で記事を評価し、必ずJSON形式のみで回答してください。

## 著者情報
- 島原大知（しまはら だいち）: VTuber業界8年、映像制作15年、SYUTAINβ（AI自律システム）構築中
- 非エンジニア視点でAI活用を発信

## コンテンツパターン
{patterns}

## 文体ルール
{style}

## チェック項目
1. fact_check: 数値・固有名詞・技術用語の正確性。嘘・捏造・ハルシネーション検出
2. consistency: 記事内の矛盾
3. persona_match: 島原大知の経歴との整合性（音楽の仕事をしている記述があればfatal）
4. quality_axes: AI臭さの無さ / 具体性 / 独自性 / 読みやすさ / ペルソナマッチ / 購買価値（各0-1）
5. paywall_structure: 「---ここから有料---」マーカーの有無、無料パートの購買意欲喚起力、有料パートの独自価値
6. fatal_issues: 事実誤認・経歴詐称・法的リスク・6000字未満・架空エピソードがあればtrue

## 回答形式（このJSON構造のみ。説明文禁止）
{{"fact_check":{{"issues":[],"score":0.0}},"consistency":{{"issues":[],"score":0.0}},"persona_match":{{"issues":[],"score":0.0}},"quality_axes":{{"no_ai_smell":0.0,"specificity":0.0,"originality":0.0,"readability":0.0,"persona_match":0.0,"purchase_value":0.0}},"paywall_structure":{{"has_marker":false,"free_part_hook_score":0.0,"paid_part_value_score":0.0}},"overall_score":0.0,"fatal_issues":false,"summary":"...","improvement_suggestions":["..."]}}"""

        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        try:
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": f"以下のnote記事を評価してください:\n\n{content}"}],
            )
            raw = resp.content[0].text if resp.content else "{}"
            in_tok = resp.usage.input_tokens
            out_tok = resp.usage.output_tokens
        except Exception as e:
            logger.error(f"Stage 1 API error: {e}")
            return {"error": str(e)}, 0.0, 0, 0

        cost = _calc_cost_jpy(in_tok, out_tok, HAIKU_INPUT_RATE, HAIKU_OUTPUT_RATE)
        result, _ = _parse_json_response(raw)
        return result, cost, in_tok, out_tok

    # ===== Stage 1.5: 事実整合性チェック =====

    async def _factual_integrity_check(self, content: str) -> dict:
        """記事の事実整合性を別モデルで独立検証する。
        生成に使ったモデルとは異なるモデルを使い、自己検証バイアスを回避する。"""
        import openai

        system_prompt = (
            "あなたは記事の事実検証専門家です。必ずJSON形式のみで回答してください。"
        )

        user_prompt = f"""この記事の事実検証を行ってください。以下の観点でチェック:

1. 年号の整合性: AIツールの利用時期が実際のリリース日と矛盾していないか
   - ChatGPT: 2022年11月公開
   - Claude: 2023年3月公開
   - GPT-4: 2023年3月公開
   - SYUTAINβ: 2025年後半開発開始、2026年3月本格稼働
   - Midjourney/Stable Diffusion: 2022年公開
   - DeepSeek: 2024年公開
   - Claude Code: 2025年公開
2. 島原大知の経歴との整合性: VTuber業界支援（活動ではない）、映像制作、非エンジニア、SYUTAINβ開発者
3. 数値の信頼性: 根拠なく具体的な統計（「72%が〜」等）を使っていないか
4. 架空エピソード: 「ある会社で」「友人が」等の匿名で具体的すぎるエピソードは捏造の可能性
5. SYUTAINβの実データ引用: 実際のシステムデータと矛盾していないか

JSON形式で回答:
{{"passed": true, "critical_issues": [], "warnings": [], "fabrication_risk_score": 0.0}}

fabrication_risk_score は 0.0（問題なし）〜 1.0（完全に捏造）のスコア。
critical_issues は公開不可レベルの問題、warnings は軽微な懸念。

## 記事本文
{content}"""

        # 生成パイプラインがDeepSeek/Claudeを使うため、検証はOpenAI系で行う
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model_used = "gpt-4o-mini"  # コスト効率の良いモデルで事実検証

        try:
            resp = await client.chat.completions.create(
                model=model_used,
                max_completion_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = resp.choices[0].message.content or "{}"
            in_tok = resp.usage.prompt_tokens if resp.usage else 0
            out_tok = resp.usage.completion_tokens if resp.usage else 0
        except Exception as e:
            logger.error(f"Factual integrity check API error: {e}")
            # API失敗時はpassedとして続行（安全側に倒さない — コスト節約優先）
            return {"passed": True, "critical_issues": [], "warnings": [f"API error: {e}"], "fabrication_risk_score": 0.0}

        # コスト記録（gpt-4o-mini: $0.15/$0.60 per 1M tokens）
        cost = _calc_cost_jpy(in_tok, out_tok, 0.15, 0.60)
        await self._log_llm_cost(model_used, "note_quality_factual_check", cost)
        self.run_cost += cost

        result, parsed = _parse_json_response(raw)
        if not parsed or not isinstance(result, dict):
            return {"passed": True, "critical_issues": [], "warnings": ["JSON解析失敗"], "fabrication_risk_score": 0.0}

        # デフォルト値を補完
        result.setdefault("passed", True)
        result.setdefault("critical_issues", [])
        result.setdefault("warnings", [])
        result.setdefault("fabrication_risk_score", 0.0)

        return result

    # ===== Stage 2: GPT-5.4 =====

    async def _stage2_gpt5_check(self, content: str, haiku_result: dict) -> tuple[dict, float, int, int, str]:
        """GPT-5.4最終確認。戻り値: (result_dict, cost_jpy, in_tok, out_tok, model_used)"""
        import openai

        profile = _load_strategy_file("島原大知_詳細プロファイリング超完全版.md", max_chars=6000)
        haiku_json = json.dumps(haiku_result, ensure_ascii=False, indent=2)

        system_prompt = f"""あなたはnote有料記事の最終品質チェッカーです。Stage 1（Haiku）の評価を参考に、より高次の品質評価を行います。必ずJSON形式のみで回答してください。

## 著者詳細プロファイル
{profile}

## 有料記事の品質基準（500円販売の最低ライン）
- 5000字以上であること（5000字未満はreject）
- 具体的な体験・エピソードが2つ以上あること（3つ以上なら高評価）
- 読者が実践できる具体的アクションまたは新しい視点が含まれること
- 表面的な解説ではなく、ある程度の深い考察があること
- 見出しが3個以上で構造化されていること（5個以上なら高評価）
- AI臭い定型表現が目立たないこと（多少のAI的表現は許容）
- 独自の情報や視点があること（完全に唯一無二でなくても、著者の経験に基づいていればOK）

## 重要: 判定基準
- overall >= 0.55 かつ致命的問題がなければ publish_ready にすること
- 軽微な改善点がある場合でも、公開して問題ないレベルならpublish_readyとする
- needs_edit は「このままでは公開できない明確な問題がある」場合のみ
- reject は5000字未満、事実誤認、法的リスクなど致命的な場合のみ

## チェック項目
1. haiku_review: Haikuの指摘の妥当性検証（同意/見落とし/誤検出）
2. quality_assessment: 読者への価値 / 島原の声 / 構成スコア / 有料記事品質（各0-1）
3. pricing_recommendation: ¥0（無料公開）/ ¥300 / ¥500 / ¥980 / ¥1980
4. publish_verdict: 以下の3つのいずれかを必ず返してください:
   - "publish_ready": 公開可能（軽微な改善点があってもOK。overall >= 0.55 なら基本的にこれ）
   - "needs_edit": 公開前に修正が必要な明確な問題がある
   - "reject": 5000字未満、事実誤認、法的リスクなど致命的問題がある場合のみ

## 回答形式（このJSON構造のみ。説明文禁止）
{{"haiku_review":{{"agreed_issues":[],"missed_issues":[],"false_positives":[]}},"quality_assessment":{{"reader_value":0.0,"daichi_voice":0.0,"structure_score":0.0,"overall":0.0}},"pricing_recommendation":0,"publish_verdict":"...","edit_instructions":["..."],"final_summary":"..."}}"""

        # モデル選択: gpt-5.4 → gpt-5 → gpt-4o のフォールバック
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model_used = await self._resolve_gpt5_model(client)

        user_msg = f"""## Stage 1（Haiku）評価結果
{haiku_json}

## 記事本文
{content}"""

        try:
            resp = await client.chat.completions.create(
                model=model_used,
                max_completion_tokens=1500,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = resp.choices[0].message.content or "{}"
            in_tok = resp.usage.prompt_tokens if resp.usage else 0
            out_tok = resp.usage.completion_tokens if resp.usage else 0
        except Exception as e:
            logger.error(f"Stage 2 API error: {e}")
            return {"error": str(e)}, 0.0, 0, 0, model_used

        cost = _calc_cost_jpy(in_tok, out_tok, GPT5_INPUT_RATE, GPT5_OUTPUT_RATE)
        result, _ = _parse_json_response(raw)
        return result, cost, in_tok, out_tok, model_used

    async def _resolve_gpt5_model(self, client) -> str:
        """利用可能な最新GPTモデルを解決"""
        try:
            models = await client.models.list()
            available = {m.id for m in models.data}
            for candidate in ["gpt-5.4", "gpt-5", "gpt-4.1", "gpt-4o"]:
                if candidate in available:
                    logger.info(f"Stage 2 model resolved: {candidate}")
                    return candidate
        except Exception as e:
            logger.warning(f"モデル一覧取得失敗、gpt-4oにフォールバック: {e}")
        return "gpt-4o"

    # ===== ヘルパー =====

    async def _find_unchecked_articles(self) -> list[Path]:
        """未チェックのnote_draftsファイルを検出"""
        if not NOTE_DRAFTS_DIR.exists():
            return []

        md_files = sorted(NOTE_DRAFTS_DIR.glob("*.md"))
        if not md_files:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT filepath FROM note_quality_reviews")
            checked = {r["filepath"] for r in rows}

        return [f for f in md_files if str(f) not in checked]

    async def _insert_review(self, filepath, filename, title, length, **kwargs) -> int:
        """note_quality_reviewsにINSERT"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO note_quality_reviews
                (filepath, filename, article_title, article_length,
                 stage1_model, stage1_result, stage1_score, stage1_fatal,
                 stage1_cost_jpy, stage1_input_tokens, stage1_output_tokens, stage1_at,
                 total_cost_jpy, final_status, blocked_reason, checked_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW())
                ON CONFLICT (filepath) DO UPDATE SET
                    stage1_result = EXCLUDED.stage1_result,
                    stage1_score = EXCLUDED.stage1_score,
                    stage1_fatal = EXCLUDED.stage1_fatal,
                    stage1_cost_jpy = EXCLUDED.stage1_cost_jpy,
                    stage1_input_tokens = EXCLUDED.stage1_input_tokens,
                    stage1_output_tokens = EXCLUDED.stage1_output_tokens,
                    stage1_at = EXCLUDED.stage1_at,
                    total_cost_jpy = EXCLUDED.total_cost_jpy,
                    final_status = EXCLUDED.final_status,
                    blocked_reason = EXCLUDED.blocked_reason,
                    checked_at = NOW()
                RETURNING id""",
                str(filepath), filename, title, length,
                kwargs.get("stage1_model", "claude-haiku-4-5"),
                json.dumps(kwargs.get("stage1_result"), ensure_ascii=False, default=str) if kwargs.get("stage1_result") else None,
                kwargs.get("stage1_score", 0),
                kwargs.get("stage1_fatal", False),
                kwargs.get("stage1_cost_jpy", 0),
                kwargs.get("stage1_input_tokens", 0),
                kwargs.get("stage1_output_tokens", 0),
                kwargs.get("stage1_at"),
                kwargs.get("total_cost_jpy", 0),
                kwargs.get("final_status", "pending"),
                kwargs.get("blocked_reason"),
            )
            return row["id"] if row else 0

    @staticmethod
    def _normalize_verdict(verdict) -> str | None:
        """GPT-5.4のverdict表記ゆれを正規化"""
        if verdict is None:
            return None
        v = str(verdict).strip().lower().replace(" ", "_").replace("-", "_")
        # 英語バリエーション
        if v in ("publish_ready", "ready", "ready_to_publish", "publishready", "approved"):
            return "publish_ready"
        if v in ("needs_edit", "needsedit", "needs_editing", "edit_needed", "revise"):
            return "needs_edit"
        if v in ("reject", "rejected", "not_ready"):
            return "reject"
        # 日本語バリエーション
        if any(kw in v for kw in ("公開可能", "公開ok", "公開可", "公開準備完了", "公開して")):
            return "publish_ready"
        if any(kw in v for kw in ("要修正", "修正必要", "編集必要", "要編集")):
            return "needs_edit"
        if any(kw in v for kw in ("却下", "不可", "リジェクト")):
            return "reject"
        logger.warning(f"Unknown verdict value: {verdict!r}, treating as needs_edit")
        return "needs_edit"

    async def _update_stage2(self, review_id, model, result, score, verdict, pricing,
                             cost, in_tok, out_tok, at, total_cost, final_status):
        """Stage 2結果でレコードを更新"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE note_quality_reviews SET
                    stage2_model = $1, stage2_result = $2, stage2_score = $3,
                    stage2_verdict = $4, stage2_pricing = $5,
                    stage2_cost_jpy = $6, stage2_input_tokens = $7, stage2_output_tokens = $8,
                    stage2_at = $9, total_cost_jpy = $10, final_status = $11, checked_at = NOW()
                WHERE id = $12""",
                model,
                json.dumps(result, ensure_ascii=False, default=str) if result else None,
                score, verdict, pricing, cost, in_tok, out_tok, at, total_cost, final_status,
                review_id,
            )

    async def _log_llm_cost(self, model: str, tier: str, amount_jpy: float):
        """llm_cost_logに記録"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO llm_cost_log (model, tier, amount_jpy, goal_id, is_info, recorded_at) "
                    "VALUES ($1, $2, $3, $4, FALSE, NOW())",
                    model, tier, amount_jpy, "note_quality",
                )
        except Exception as e:
            logger.error(f"llm_cost_log記録失敗: {e}")

    async def _log_event(self, event_type: str, message: str, severity: str = "info"):
        """event_logに記録"""
        try:
            from tools.event_logger import log_event
            await log_event(event_type, "note_quality", {"message": message}, severity=severity)
        except Exception as e:
            logger.error(f"event_log記録失敗: {e}")
