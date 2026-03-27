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
3. persona_match: 島原大知の経歴との整合性
4. quality_axes: AI臭さの無さ / 具体性 / 独自性 / 読みやすさ / ペルソナマッチ（各0-1）
5. fatal_issues: 事実誤認・経歴詐称・法的リスクがあればtrue

## 回答形式（このJSON構造のみ。説明文禁止）
{{"fact_check":{{"issues":[],"score":0.0}},"consistency":{{"issues":[],"score":0.0}},"persona_match":{{"issues":[],"score":0.0}},"quality_axes":{{"no_ai_smell":0.0,"specificity":0.0,"originality":0.0,"readability":0.0,"persona_match":0.0}},"overall_score":0.0,"fatal_issues":false,"summary":"...","improvement_suggestions":["..."]}}"""

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

    # ===== Stage 2: GPT-5.4 =====

    async def _stage2_gpt5_check(self, content: str, haiku_result: dict) -> tuple[dict, float, int, int, str]:
        """GPT-5.4最終確認。戻り値: (result_dict, cost_jpy, in_tok, out_tok, model_used)"""
        import openai

        profile = _load_strategy_file("島原大知_詳細プロファイリング超完全版.md", max_chars=6000)
        haiku_json = json.dumps(haiku_result, ensure_ascii=False, indent=2)

        system_prompt = f"""あなたはnote有料記事の最終品質チェッカーです。Stage 1（Haiku）の評価を参考に、より高次の品質評価を行います。必ずJSON形式のみで回答してください。

## 著者詳細プロファイル
{profile}

## チェック項目
1. haiku_review: Haikuの指摘の妥当性検証（同意/見落とし/誤検出）
2. quality_assessment: 読者への価値 / 島原の声 / 構成スコア（各0-1）
3. pricing_recommendation: ¥0 / ¥300 / ¥500 / ¥980 / ¥1980
4. publish_verdict: publish_ready / needs_edit / reject

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
