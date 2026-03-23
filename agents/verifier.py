"""
SYUTAINβ V25 検証エンジン（Verifier）— Step 8
設計書 第6章 6.2「④ 検証（Verify）」準拠

タスク実行結果を成功条件に照らして検証し、品質スコアリングを行う。
"""

import os
import json
import logging
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm

load_dotenv()

logger = logging.getLogger("syutain.verifier")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")


class VerificationResult:
    """検証結果（設計書 verify_result 準拠）"""

    def __init__(
        self,
        status: str = "success",
        goal_progress: float = 0.0,
        value_generated: bool = False,
        artifacts_saved: Optional[list] = None,
        error_class: Optional[str] = None,
        retry_value: str = "none",
        revenue_contribution: float = 0.0,
        quality_score: float = 0.0,
        browser_action_success: Optional[bool] = None,
    ):
        self.status = status  # success / partial / failure
        self.goal_progress = goal_progress  # 0.0 - 1.0
        self.value_generated = value_generated
        self.artifacts_saved = artifacts_saved or []
        self.error_class = error_class
        self.retry_value = retry_value  # high / low / none
        self.revenue_contribution = revenue_contribution  # 0.0 - 1.0
        self.quality_score = quality_score  # 0.0 - 1.0
        self.browser_action_success = browser_action_success  # V25

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "goal_progress": self.goal_progress,
            "value_generated": self.value_generated,
            "artifacts_saved": self.artifacts_saved,
            "error_class": self.error_class,
            "retry_value": self.retry_value,
            "revenue_contribution": self.revenue_contribution,
            "quality_score": self.quality_score,
            "browser_action_success": self.browser_action_success,
        }


class Verifier:
    """検証エンジン — 実行結果の品質検証"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
            except Exception as e:
                logger.error(f"PostgreSQL接続プール作成失敗: {e}")
                return None
        return self._pool

    async def verify(
        self,
        execution_result: dict,
        goal_packet: dict,
        completed_task_count: int,
        total_task_count: int,
    ) -> VerificationResult:
        """
        タスク実行結果を検証する。

        Args:
            execution_result: Executorからの実行結果
            goal_packet: ゴールパケット（成功条件を含む）
            completed_task_count: 完了タスク数
            total_task_count: 総タスク数
        """
        task_id = execution_result.get("task_id", "unknown")
        logger.info(f"検証開始: {task_id}")

        status = execution_result.get("status", "failure")
        error_class = execution_result.get("error_class")
        output = execution_result.get("output", {})
        artifacts = execution_result.get("artifacts", [])

        # 基本検証: ステータスチェック
        if status == "failure":
            retry_value = self._assess_retry_value(error_class)
            return VerificationResult(
                status="failure",
                goal_progress=completed_task_count / max(total_task_count, 1),
                error_class=error_class,
                retry_value=retry_value,
            )

        if status == "pending_approval":
            return VerificationResult(
                status="partial",
                goal_progress=completed_task_count / max(total_task_count, 1),
                retry_value="none",
            )

        # 成果物の検証
        has_output = bool(output.get("text", "").strip()) or bool(artifacts)
        quality_score = 0.0

        if has_output:
            # LLMで品質スコアリング（CLAUDE.md ルール5: choose_best_model_v6使用）
            try:
                quality_score = await self._score_quality(
                    output, goal_packet.get("success_definition", [])
                )
            except Exception as e:
                logger.warning(f"品質スコアリング失敗: {e}")
                quality_score = 0.5  # デフォルト中間スコア

            # final_publish品質の成果物はTier Sモデルで追加検査
            task_type = execution_result.get("task_type", "")
            if quality_score >= 0.6 and task_type in [
                "content", "note_article", "product_desc", "btob",
                "pricing", "strategy", "proposal",
            ]:
                try:
                    quality_score = await self._tier_s_quality_check(
                        output, goal_packet.get("success_definition", []),
                        task_type, quality_score,
                    )
                except Exception as e:
                    logger.warning(f"Tier S品質検査失敗（元スコア維持）: {e}")

        # AI文体パターン検出（LLM不要、コストゼロ）
        if has_output and quality_score > 0:
            text_for_check = output.get("text", "")
            if text_for_check and len(text_for_check) > 50:
                ai_check = check_ai_patterns(text_for_check)
                quality_score = max(0.0, min(1.0, quality_score - ai_check["penalty"]))
                if ai_check["count"] > 0:
                    logger.info(
                        f"AI文体チェック: {ai_check['count']}件検出, "
                        f"ペナルティ={ai_check['penalty']}, patterns={ai_check['patterns'][:3]}"
                    )
                try:
                    from tools.event_logger import log_event
                    await log_event("quality.ai_pattern_check", "quality", {
                        "task_id": task_id,
                        "pattern_count": ai_check["count"],
                        "penalty": ai_check["penalty"],
                        "patterns": ai_check["patterns"][:5],
                    })
                except Exception:
                    pass

        # 進捗計算
        progress = (completed_task_count + 1) / max(total_task_count, 1)
        progress = min(progress, 1.0)

        # 価値判定
        value_generated = quality_score >= 0.3 or has_output

        # ブラウザアクション判定（V25）
        browser_success = None
        if execution_result.get("task_type") in ["browser_action", "computer_use"]:
            browser_success = status == "success"

        result = VerificationResult(
            status="success" if quality_score >= 0.5 else "partial",
            goal_progress=progress,
            value_generated=value_generated,
            artifacts_saved=[a.get("type", "unknown") for a in artifacts],
            quality_score=quality_score,
            browser_action_success=browser_success,
        )

        # 品質ログをDBに記録
        await self._log_quality(task_id, execution_result, result)

        # 判断根拠を記録
        ai_patterns_info = None
        if has_output and quality_score > 0:
            text_for_check_len = len(output.get("text", ""))
            if text_for_check_len > 50:
                ai_check_local = check_ai_patterns(output.get("text", ""))
                ai_patterns_info = {"count": ai_check_local["count"], "patterns": ai_check_local["patterns"][:5]}

        await self._record_trace(
            task_id=task_id,
            goal_id=goal_packet.get("goal_id"),
            action="quality_scoring",
            reasoning=f"品質スコア{result.quality_score:.2f}を付与。status={result.status}",
            confidence=result.quality_score,
            context={
                "quality_score": result.quality_score,
                "has_output": has_output,
                "ai_patterns": ai_patterns_info,
                "model_used": execution_result.get("output", {}).get("model_used", "unknown"),
                "task_type": execution_result.get("task_type", "unknown"),
            },
        )

        logger.info(
            f"検証完了: {task_id} → status={result.status}, "
            f"progress={result.goal_progress:.2f}, quality={result.quality_score:.2f}"
        )

        # 品質低下エスカレーション: 24h平均が7日平均-0.10
        try:
            await self._check_quality_decline()
        except Exception:
            pass

        return result

    async def _score_quality(self, output: dict, success_definition: list) -> float:
        """LLMで出力品質をスコアリング（0.0-1.0）"""
        text = output.get("text", "")
        if not text:
            return 0.0

        # 短いテキストは簡易チェック
        if len(text) < 20:
            return 0.3

        # LLMで品質評価（ローカルモデル使用でコスト¥0）
        model_sel = choose_best_model_v6(
            task_type="classification",
            quality="low",
            budget_sensitive=True,
            local_available=True,
        )

        success_str = "\n".join(f"- {s}" for s in success_definition) if success_definition else "なし"

        try:
            llm_result = await call_llm(
                prompt=f"""以下の出力の品質を0.0〜1.0で評価してください。数値のみ回答してください。

## 成功条件
{success_str}

## 出力（先頭500文字）
{text[:500]}
""",
                system_prompt="品質評価エージェント。0.0〜1.0の数値のみ出力。",
                model_selection=model_sel,
            )

            score_text = llm_result.get("text", "0.5").strip()
            # 数値を抽出
            import re
            match = re.search(r"(0?\.\d+|1\.0|0|1)", score_text)
            if match:
                return min(max(float(match.group(1)), 0.0), 1.0)
            return 0.5
        except Exception as e:
            logger.warning(f"品質スコアリングLLM呼び出し失敗: {e}")
            return 0.5

    async def _tier_s_quality_check(
        self,
        output: dict,
        success_definition: list,
        task_type: str,
        base_score: float,
    ) -> float:
        """
        Tier Sモデル（Claude Sonnet等）による最終品質検査

        対象: コンテンツ生成、BtoB提案、価格設定、戦略文書
        検査項目: 正確性、文体一貫性、ICP適合性、CTA有効性
        """
        text = output.get("text", "")
        if not text or len(text) < 100:
            return base_score

        model_sel = choose_best_model_v6(
            task_type="analysis",
            quality="high",
            budget_sensitive=True,
            final_publish=False,  # 検査自体は公開物ではない
        )

        success_str = "\n".join(f"- {s}" for s in success_definition) if success_definition else "なし"

        try:
            llm_result = await call_llm(
                prompt=f"""以下の成果物の品質を検査してください。0.0〜1.0の数値で回答してください。

## 検査項目
1. 正確性: 事実誤認や論理矛盾がないか
2. 文体一貫性: トーンや表現が統一されているか
3. 実用性: 読者が行動に移せる内容か
4. 完成度: 欠落している要素がないか

## 成功条件
{success_str}

## タスクタイプ
{task_type}

## 成果物（先頭1000文字）
{text[:1000]}

品質スコア（0.0〜1.0の数値のみ）:""",
                system_prompt="品質検査エージェント。0.0〜1.0の数値のみ出力。",
                model_selection=model_sel,
            )

            import re
            score_text = llm_result.get("text", "").strip()
            match = re.search(r"(0?\.\d+|1\.0|0|1)", score_text)
            if match:
                tier_s_score = min(max(float(match.group(1)), 0.0), 1.0)
                # 元スコアとTier Sスコアの加重平均（Tier S検査を重視）
                final_score = base_score * 0.3 + tier_s_score * 0.7
                logger.info(
                    f"Tier S品質検査: base={base_score:.2f}, "
                    f"tier_s={tier_s_score:.2f}, final={final_score:.2f}"
                )
                return final_score
        except Exception as e:
            logger.warning(f"Tier S品質検査LLM呼び出し失敗: {e}")

        return base_score

    def _assess_retry_value(self, error_class: Optional[str]) -> str:
        """再試行の価値を判定"""
        if error_class is None:
            return "none"

        # 一時的なエラー → 再試行価値高い
        if error_class in ["timeout", "network"]:
            return "high"
        # モデルエラー → 別モデルで再試行
        elif error_class in ["model"]:
            return "high"
        # 認証エラー → 再試行しても無駄
        elif error_class in ["auth"]:
            return "none"
        # 予算超過 → 再試行不可
        elif error_class in ["budget"]:
            return "none"
        # ブラウザエラー → フォールバック可能
        elif error_class in ["browser", "browser_layer_exhausted"]:
            return "low"
        else:
            return "low"

    async def _check_quality_decline(self):
        """24h平均が7日平均を0.10以上下回っていたらエスカレーション"""
        pool = await self._get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                """SELECT
                     AVG(quality_score) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as avg_24h,
                     AVG(quality_score) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as avg_7d
                   FROM model_quality_log
                   WHERE quality_score > 0"""
            )
            if r and r["avg_24h"] is not None and r["avg_7d"] is not None:
                delta = float(r["avg_24h"]) - float(r["avg_7d"])
                if delta < -0.10:
                    # 重複防止: 直近1日以内に同じエスカレーションがなければ
                    existing = await conn.fetchval(
                        """SELECT COUNT(*) FROM claude_code_queue
                           WHERE category = 'quality_decline' AND created_at > NOW() - INTERVAL '24 hours'"""
                    )
                    if existing == 0:
                        from brain_alpha.escalation import escalate_to_queue
                        await escalate_to_queue(
                            category="quality_decline",
                            description=f"品質スコア低下: 24h平均={float(r['avg_24h']):.2f}, 7日平均={float(r['avg_7d']):.2f} (差={delta:.2f})",
                            priority="high",
                            source_agent="verifier",
                            auto_solvable=False,
                        )

    async def _record_trace(self, task_id: str, goal_id: str = None, action: str = "",
                           reasoning: str = "", confidence: float = None, context: dict = None):
        """判断根拠をagent_reasoning_traceに記録（失敗してもメイン処理を止めない）"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO agent_reasoning_trace
                           (agent_name, goal_id, task_id, action, reasoning, confidence, context)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        "verifier", goal_id, task_id, action, reasoning,
                        confidence, json.dumps(context or {}, ensure_ascii=False, default=str),
                    )
        except Exception as e:
            logger.debug(f"トレース記録失敗（無視）: {e}")

    async def _log_quality(self, task_id: str, execution_result: dict, verification: VerificationResult):
        """品質ログをDBに記録"""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO model_quality_log
                            (task_type, model_used, tier, quality_score, total_cost_jpy)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        execution_result.get("task_type", "unknown"),
                        execution_result.get("output", {}).get("model_used", "unknown"),
                        execution_result.get("model_selection", {}).get("tier", "unknown")
                            if execution_result.get("model_selection") else "unknown",
                        verification.quality_score,
                        execution_result.get("cost_jpy", 0.0),
                    )
        except Exception as e:
            logger.warning(f"品質ログDB記録失敗: {e}")

    async def verify_goal_completion(self, goal_packet: dict, all_results: list[dict]) -> VerificationResult:
        """ゴール全体の達成度を検証"""
        if not all_results:
            return VerificationResult(status="failure", goal_progress=0.0)

        # 全タスクの結果を集約
        success_count = sum(1 for r in all_results if r.get("status") == "success")
        total = len(all_results)
        avg_quality = sum(r.get("quality_score", 0) for r in all_results) / max(total, 1)

        progress = success_count / max(total, 1)
        overall_status = "success" if progress >= 0.8 and avg_quality >= 0.5 else "partial"

        return VerificationResult(
            status=overall_status,
            goal_progress=progress,
            value_generated=success_count > 0,
            quality_score=avg_quality,
        )

    async def close(self):
        if self._pool:
            try:
                await self._pool.close()
            except Exception as e:
                logger.error(f"接続プール終了エラー: {e}")


# ===== AI文体パターン検出（LLM不要、コストゼロ） =====

def check_ai_patterns(text: str) -> dict:
    """
    テキストからAI文体パターンを検出する。

    Returns:
        {
            "count": int,       # 検出されたパターン数
            "penalty": float,   # 品質スコアへのペナルティ
            "patterns": list,   # 検出パターンの詳細
        }
    """
    import re

    patterns_found = []

    # A. 意義の過剰な強調
    significance_phrases = [
        "浮き彫りにし", "大きな示唆", "重要性を示し", "物語っています",
        "象徴しています", "裏付けています",
    ]
    for phrase in significance_phrases:
        if phrase in text:
            patterns_found.append(f"A.意義過剰: 「{phrase}」")

    # B. AI頻出語彙
    ai_vocab = [
        "特筆すべき", "注目すべき", "画期的な", "革新的な",
        "多岐にわたる", "網羅的な", "包括的な",
        "と言えるでしょう", "ではないでしょうか",
    ]
    for word in ai_vocab:
        if word in text:
            patterns_found.append(f"B.AI語彙: 「{word}」")

    # 「さらに」「加えて」の連続使用
    sarani_count = text.count("さらに") + text.count("加えて")
    if sarani_count >= 3:
        patterns_found.append(f"B.接続詞過多: 「さらに/加えて」{sarani_count}回")

    # D. 回りくどい表現
    roundabout = [
        "として位置づけられ", "の役割を果たし",
        "という観点から", "という側面があり",
    ]
    for phrase in roundabout:
        if phrase in text:
            patterns_found.append(f"D.回りくどい: 「{phrase}」")

    # E. 三点セットの強制（「X、Y、Zの」パターン）
    triplet_pattern = re.findall(r'[^、。]+、[^、。]+、[^、。]+の(?:三つ|3つ|観点|バランス)', text)
    if len(triplet_pattern) >= 2:
        patterns_found.append(f"E.三点セット: {len(triplet_pattern)}箇所")

    # F. 定型的な冒頭と結論
    opening_patterns = [
        "ここでは", "本記事では", "本稿では", "以下では",
        "今回は〜について",
    ]
    for op in opening_patterns:
        if text.strip().startswith(op):
            patterns_found.append(f"F.定型冒頭: 「{op}」")

    closing_patterns = [
        "注目されます", "期待されます", "さらなる発展",
        "今後の展開", "引き続き注視",
    ]
    last_100 = text[-100:] if len(text) > 100 else text
    for cp in closing_patterns:
        if cp in last_100:
            patterns_found.append(f"F.定型結論: 「{cp}」")

    # G. 太字+コロンの箇条書き（**X**: Y）
    bold_colon = re.findall(r'\*\*[^*]+\*\*\s*[:：]', text)
    if len(bold_colon) >= 2:
        patterns_found.append(f"G.太字コロン: {len(bold_colon)}箇所")

    # H. ダッシュの使用
    dash_count = text.count('——') + text.count(' — ') + text.count('ーー')
    if dash_count >= 1:
        patterns_found.append(f"H.ダッシュ: {dash_count}箇所")

    # I. 曖昧な出典
    vague_sources = ["研究によると", "専門家は", "多くの人が", "一般的に"]
    for vs in vague_sources:
        if vs in text:
            patterns_found.append(f"I.曖昧出典: 「{vs}」")

    # J. 過剰なヘッジング
    hedge_count = (
        text.count("かもしれません") +
        text.count("の可能性があります") +
        text.count("と考えられます") +
        text.count("と思われます")
    )
    if hedge_count >= 3:
        patterns_found.append(f"J.ヘッジ過多: {hedge_count}回")

    # K. チャットボット残留表現
    chatbot_phrases = [
        "もちろんです", "素晴らしい質問", "ご理解いただけると幸いです",
        "見ていきましょう", "ご紹介します", "お伝えします",
        "それでは早速",
    ]
    for cp in chatbot_phrases:
        if cp in text:
            patterns_found.append(f"K.チャットボット: 「{cp}」")

    # L. 追従的トーン
    flattery = [
        "非常に興味深い", "素晴らしいアプローチ", "優れた取り組み",
        "画期的な試み",
    ]
    for fl in flattery:
        if fl in text:
            patterns_found.append(f"L.追従的: 「{fl}」")

    # ペナルティ計算
    count = len(patterns_found)
    if count == 0:
        penalty = -0.05  # ボーナス（負のペナルティ＝加点）
    elif count <= 2:
        penalty = 0.0
    elif count <= 5:
        penalty = 0.10
    else:
        penalty = 0.20

    return {
        "count": count,
        "penalty": penalty,
        "patterns": patterns_found,
    }
