"""
SYUTAINβ V25 検証エンジン（Verifier）— Step 8
設計書 第6章 6.2「④ 検証（Verify）」準拠

タスク実行結果を成功条件に照らして検証し、品質スコアリングを行う。
"""

import os
import json
import logging
from typing import Optional

from tools.db_pool import get_connection
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm

load_dotenv()

logger = logging.getLogger("syutain.verifier")



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
        pass

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
        ai_check = None
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

        # 判断根拠を記録（ai_checkの結果を再利用）
        ai_patterns_info = None
        if ai_check is not None:
            ai_patterns_info = {"count": ai_check["count"], "patterns": ai_check["patterns"][:5]}

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
        """LLMで出力品質をスコアリング（0.0-1.0）— 詳細ルーブリック付き"""
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
                prompt=f"""以下の出力を5つの基準で各1-5点で評価し、合計点を25点満点で算出してください。

## 評価基準（各1-5点）

A. 完成度: 成功条件を満たしているか
   1=全く未達成 2=一部のみ 3=概ね達成 4=達成 5=条件を超える品質

B. 正確性: 事実誤認・論理矛盾がないか
   1=重大な誤り 2=複数の軽微な誤り 3=1つの誤り 4=ほぼ正確 5=完全に正確

C. 実用性: 読者が理解・行動できる内容か
   1=意味不明 2=理解困難 3=理解可能 4=行動可能 5=即座に活用可能

D. 独自性: テンプレ的でなく価値ある視点があるか
   1=完全にテンプレ 2=ほぼ定型 3=一部独自 4=独自の視点あり 5=深い洞察

E. 文体品質: 日本語として自然で読みやすいか
   1=不自然 2=AI臭い 3=普通 4=自然 5=島原大知の声が聞こえる

## 成功条件
{success_str}

## 出力（先頭500文字）
{text[:500]}

回答形式: A=X B=X C=X D=X E=X 合計=XX""",
                system_prompt="品質評価エージェント。指定された形式で回答する。",
                model_selection=model_sel,
            )

            score_text = llm_result.get("text", "").strip()
            import re

            # 合計点を抽出
            total_match = re.search(r"合計[=:：\s]*(\d+)", score_text)
            if total_match:
                total = int(total_match.group(1))
                return min(max(round(total / 25.0, 3), 0.0), 1.0)

            # 個別点を合算
            individual = re.findall(r"[A-E][=:：\s]*(\d)", score_text)
            if len(individual) >= 3:
                total = sum(int(x) for x in individual[:5])
                return min(max(round(total / 25.0, 3), 0.0), 1.0)

            # フォールバック: 従来の数値抽出
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
                prompt=f"""以下の成果物を6つの基準で各1-5点で検査してください。

## 検査基準（各1-5点）

A. 正確性: 事実誤認や論理矛盾がないか
   1=重大な誤り多数 2=誤りあり 3=概ね正確 4=ほぼ完璧 5=完全に正確

B. 文体一貫性: トーンや表現が統一されているか
   1=バラバラ 2=不統一 3=概ね統一 4=一貫 5=完全に統一

C. ICP適合性: ターゲット層（AI活用に関心がある28-39歳の非エンジニアクリエイター）に響くか
   1=全く響かない 2=やや的外れ 3=普通 4=響く 5=強く共感

D. 実用性: 読者が具体的に行動に移せるか
   1=行動不能 2=抽象的 3=一部実用的 4=実用的 5=即実践可能

E. 完成度: 必要な要素が揃っているか
   1=大幅欠落 2=欠落あり 3=最低限 4=十分 5=完璧

F. 独自価値: 他では得られない視点・情報があるか
   1=コモディティ 2=やや独自 3=普通 4=独自性あり 5=唯一無二

## 成功条件
{success_str}

## タスクタイプ: {task_type}

## 成果物（先頭1000文字）
{text[:1000]}

回答形式: A=X B=X C=X D=X E=X F=X 合計=XX""",
                system_prompt="品質検査エージェント。指定された形式で回答する。",
                model_selection=model_sel,
            )

            import re
            score_text = llm_result.get("text", "").strip()

            # 合計点を抽出（30点満点）
            total_match = re.search(r"合計[=:：\s]*(\d+)", score_text)
            tier_s_score = None
            if total_match:
                total = int(total_match.group(1))
                tier_s_score = min(max(round(total / 30.0, 3), 0.0), 1.0)
            else:
                # 個別点を合算
                individual = re.findall(r"[A-F][=:：\s]*(\d)", score_text)
                if len(individual) >= 3:
                    total = sum(int(x) for x in individual[:6])
                    tier_s_score = min(max(round(total / 30.0, 3), 0.0), 1.0)
                else:
                    match = re.search(r"(0?\.\d+|1\.0|0|1)", score_text)
                    if match:
                        tier_s_score = min(max(float(match.group(1)), 0.0), 1.0)

            if tier_s_score is not None:
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
        async with get_connection() as conn:
            r = await conn.fetchrow(
                """SELECT
                     AVG(quality_score) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as avg_24h,
                     AVG(quality_score) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as avg_7d
                   FROM model_quality_log
                   WHERE quality_score > 0"""
            )
            if r and r["avg_24h"] is not None and r["avg_7d"] is not None:
                delta = float(r["avg_24h"]) - float(r["avg_7d"])
                if delta < -0.05:
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
            async with get_connection() as conn:
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
        """品質ログをDBに記録（learning_managerに一元化、二重書き込み防止）"""
        # learning_managerにフィードバック（モデル品質学習ループ）
        try:
            from agents.learning_manager import get_learning_manager
            lm = get_learning_manager()
            await lm.track_model_quality(
                task_type=execution_result.get("task_type", "unknown"),
                model_used=execution_result.get("output", {}).get("model_used", "unknown"),
                tier=(execution_result.get("model_selection") or
                      execution_result.get("output", {}).get("model_selection") or
                      {}).get("tier", "unknown"),
                quality_score=verification.quality_score,
                total_cost_jpy=execution_result.get("cost_jpy", 0.0),
            )
        except Exception as e:
            logger.debug(f"learning_managerフィードバック失敗（無視）: {e}")

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
        pass


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

    # M. 中国語混入検出（簡体字の直接検出 + 仮名なしCJK検出）
    # 簡体字で日本語にない文字を直接検出
    simplified_chinese_chars = re.findall(r'[压热设买卖开关认识说话请问题变这那对个头发视频点击搜索输入确认选择删除编辑保存返回页面]', text)
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    japanese_pattern = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')  # hiragana + katakana
    penalty_extra_chinese = 0.0
    if simplified_chinese_chars:
        patterns_found.append(f"M.簡体字混入: 「{''.join(simplified_chinese_chars[:5])}」")
        penalty_extra_chinese = 0.40
    elif chinese_pattern.search(text) and not japanese_pattern.search(text[:100]):
        patterns_found.append("M.中国語混入: 仮名なしCJK検出")
        penalty_extra_chinese = 0.30

    # N. 島原大知の読み間違い検出
    wrong_readings = ["うらわら", "おおとも", "しまばらだいち", "しまはらたいち",
                      "とうげんだいち", "しまはらおおち"]
    penalty_extra_name = 0.0
    for wr in wrong_readings:
        if wr in text:
            patterns_found.append(f"N.名前誤読: 「{wr}」(正: しまはらだいち)")
            penalty_extra_name = 0.50
            break

    # N2. 企業名・固有名詞の読み間違い（ハルシネーション検出）
    penalty_extra_hallucination = 0.0
    hallucination_patterns = [
        (r'Nvidia[（(][^）)]*[英ア][^）)]*[）)]', "Nvidia読み間違い"),
        (r'Google[（(][^）)]*[^グーグル][^）)]*[）)]', "Google読み間違い"),
        (r'Apple[（(][^）)]*[^アップル][^）)]*[）)]', "Apple読み間違い"),
        (r'島原大知[（(][^しま][^）)]*[）)]', "島原大知読み間違い"),
    ]
    for hp, label in hallucination_patterns:
        if re.search(hp, text):
            patterns_found.append(f"N2.ハルシネーション: {label}")
            penalty_extra_hallucination = 0.40
            break

    # O. AI自己開示検出
    ai_disclosure_phrases = [
        "AIです", "仮の私（AI）", "私はAIが", "AIである私",
        "AIとして", "私はAI", "AIの私",
    ]
    penalty_extra_ai_disclosure = 0.0
    for adp in ai_disclosure_phrases:
        if adp in text:
            patterns_found.append(f"O.AI自己開示: 「{adp}」")
            penalty_extra_ai_disclosure = 0.40
            break

    # P. 太字+コロンパターン過多（anti_ai_writing rule G強化）
    penalty_extra_bold_colon = 0.0
    if len(bold_colon) >= 3:
        patterns_found.append(f"P.太字コロン過多: {len(bold_colon)}箇所(3+)")
        penalty_extra_bold_colon = 0.15

    # ペナルティ計算
    count = len(patterns_found)
    if count == 0:
        penalty = -0.05  # ボーナス（負のペナルティ＝加点）
    elif count <= 2:
        penalty = 0.0
    elif count <= 4:
        penalty = 0.10
    elif count <= 6:
        penalty = 0.20
    else:
        penalty = 0.30  # 7個以上のAIパターン → 強いペナルティ

    # 追加ペナルティ（重大品質問題）を加算
    penalty += penalty_extra_chinese + penalty_extra_name + penalty_extra_ai_disclosure + penalty_extra_bold_colon + penalty_extra_hallucination

    return {
        "count": count,
        "penalty": penalty,
        "patterns": patterns_found,
    }
