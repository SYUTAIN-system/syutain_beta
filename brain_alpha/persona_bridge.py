"""
SYUTAINβ Brain-α 人格保持ブリッジ
設計書 Section 7 準拠

人間の脳の記憶構造を模倣し、Daichiの人格を保持・成長させる。
島原大知のTwitterアーカイブ2,909件から抽出した深層プロファイルを
SYUTAINβの人格基盤として完全に組み込む。
"""

import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.persona_bridge")

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


# ======================================================================
# 1. build_persona_context — 意図に応じた人格コンテキスト構築
# ======================================================================

async def build_persona_context(intent_type: str) -> dict:
    """
    意図に応じた適切な量の人格コンテキストを返す。

    casual:    persona_memory上位5件 + 名前
    standard:  上位10件 + strategy_identity + 直近セッション
    strategic: 上位20件 + 全strategy + 直近3セッション + Daichi対話10件 + 深層プロファイル
    code_fix:  直近セッション + 関連トレース10件
    """
    async with get_connection() as conn:
        context = {"intent": intent_type}

        # 優先度階層ラベル（LLMに伝達）
        _TIER_LABELS = {
            1: "ABSOLUTE",   # 絶対遵守（taboo等）
            2: "HIGH",       # 高優先（philosophy, identity, correction）
            3: "MEDIUM",     # 中優先（judgment）
            4: "LOW",        # 低優先（emotion, preference）— トレードオフ可
            5: "OPTIONAL",   # 参考情報
        }

        try:
            if intent_type == "casual":
                rows = await conn.fetch(
                    """SELECT content, category, COALESCE(priority_tier, 3) as priority_tier
                       FROM persona_memory
                       ORDER BY COALESCE(priority_tier, 3) ASC, created_at DESC LIMIT 5"""
                )
                context["persona"] = [
                    {"content": r["content"], "category": r["category"],
                     "priority": _TIER_LABELS.get(r["priority_tier"], "MEDIUM")}
                    for r in rows
                ]
                context["identity"] = "島原大知のAI事業パートナー SYUTAIN"

            elif intent_type == "standard":
                rows = await conn.fetch(
                    """SELECT content, category, reasoning, COALESCE(priority_tier, 3) as priority_tier
                       FROM persona_memory
                       ORDER BY COALESCE(priority_tier, 3) ASC, created_at DESC LIMIT 10"""
                )
                context["persona"] = [
                    {"content": r["content"], "category": r["category"],
                     "reasoning": r["reasoning"],
                     "priority": _TIER_LABELS.get(r["priority_tier"], "MEDIUM")}
                    for r in rows
                ]

                strategy_id_path = PROMPTS_DIR / "strategy_identity.md"
                if strategy_id_path.exists():
                    context["strategy_identity"] = strategy_id_path.read_text(encoding="utf-8")[:3000]

                session = await conn.fetchrow(
                    """SELECT session_id, summary, unresolved_issues FROM brain_alpha_session
                       ORDER BY created_at DESC LIMIT 1"""
                )
                if session:
                    context["last_session"] = {
                        "session_id": session["session_id"],
                        "summary": session["summary"],
                        "unresolved": _parse_json(session["unresolved_issues"]),
                    }

            elif intent_type == "strategic":
                # 人格記憶: priority_tier優先で上位20件（tier 1=absoluteが最優先）
                rows = await conn.fetch(
                    """SELECT content, category, reasoning, emotion,
                              COALESCE(priority_tier, 3) as priority_tier
                       FROM persona_memory
                       ORDER BY COALESCE(priority_tier, 3) ASC, created_at DESC
                       LIMIT 20"""
                )
                context["persona"] = [
                    {**dict(r), "priority": _TIER_LABELS.get(r["priority_tier"], "MEDIUM")}
                    for r in rows
                ]
                # LLMへの指示: 優先度階層の意味
                context["priority_guide"] = (
                    "ABSOLUTE=絶対遵守(違反不可), HIGH=高優先(核心的価値観), "
                    "MEDIUM=中優先(判断基準), LOW=低優先(トレードオフ可)"
                )

                # 全strategy
                context["strategies"] = {}
                if STRATEGY_DIR.exists():
                    for f in STRATEGY_DIR.glob("*.md"):
                        context["strategies"][f.stem] = f.read_text(encoding="utf-8")[:2000]

                strategy_id_path = PROMPTS_DIR / "strategy_identity.md"
                if strategy_id_path.exists():
                    context["strategy_identity"] = strategy_id_path.read_text(encoding="utf-8")

                # 深層プロファイル
                deep_profile_path = STRATEGY_DIR / "daichi_deep_profile.md"
                if deep_profile_path.exists():
                    context["deep_profile"] = deep_profile_path.read_text(encoding="utf-8")[:5000]

                # 直近3セッション
                sessions = await conn.fetch(
                    """SELECT session_id, summary, key_decisions, unresolved_issues
                       FROM brain_alpha_session ORDER BY created_at DESC LIMIT 3"""
                )
                context["sessions"] = [
                    {"session_id": s["session_id"], "summary": s["summary"],
                     "decisions": _parse_json(s["key_decisions"]),
                     "issues": _parse_json(s["unresolved_issues"])}
                    for s in sessions
                ]

                # Daichi対話直近10件
                dialogues = await conn.fetch(
                    """SELECT channel, daichi_message, extracted_philosophy, created_at
                       FROM daichi_dialogue_log ORDER BY created_at DESC LIMIT 10"""
                )
                context["daichi_dialogues"] = [
                    {"channel": d["channel"], "message": (d["daichi_message"] or "")[:200],
                     "philosophy": _parse_json(d["extracted_philosophy"])}
                    for d in dialogues
                ]

            elif intent_type == "code_fix":
                session = await conn.fetchrow(
                    """SELECT session_id, summary, key_decisions, unresolved_issues, next_session_context
                       FROM brain_alpha_session ORDER BY created_at DESC LIMIT 1"""
                )
                if session:
                    context["last_session"] = {
                        "session_id": session["session_id"],
                        "summary": session["summary"],
                        "decisions": _parse_json(session["key_decisions"]),
                        "issues": _parse_json(session["unresolved_issues"]),
                        "files": _parse_json(session["next_session_context"]).get("files_modified", []),
                    }

                traces = await conn.fetch(
                    """SELECT agent_name, task_id, action, reasoning, confidence
                       FROM agent_reasoning_trace ORDER BY created_at DESC LIMIT 10"""
                )
                context["traces"] = [
                    {"agent": t["agent_name"], "task_id": t["task_id"], "action": t["action"],
                     "reasoning": (t["reasoning"] or "")[:200],
                     "confidence": float(t["confidence"]) if t["confidence"] else None}
                    for t in traces
                ]

            return context
        except Exception as e:
            logger.error(f"コンテキスト構築失敗 ({intent_type}): {e}")
            return {"intent": intent_type, "error": str(e)}


# ======================================================================
# 2. log_dialogue — 対話記録 + 価値観自動抽出
# ======================================================================

async def log_dialogue(
    session_id: str,
    channel: str,
    daichi_msg: str,
    alpha_response: str,
) -> dict:
    """
    daichi_dialogue_logに記録 + ローカルLLMで価値観自動抽出 + persona_memoryに追加。
    """
    async with get_connection() as conn:
        try:
            # LLMで哲学抽出（コスト¥0）
            philosophy = None
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from tools.llm_router import choose_best_model_v6, call_llm
                import re

                model_sel = choose_best_model_v6(
                    task_type="classification", quality="low",
                    budget_sensitive=True, local_available=True,
                )
                result = await call_llm(
                    prompt=f"""以下のDaichiの発言から、価値観・判断基準・哲学を抽出してJSON出力してください。
発言にそのような要素がない場合は{{"importance": 0}}のみ返してください。

発言: {daichi_msg[:500]}

JSON形式:
{{"category": "philosophy|judgment|identity|emotion|preference", "content": "抽出した価値観(1文)", "reasoning": "なぜそう判断したか", "emotion": "感情トーン", "importance": 0.0-1.0}}""",
                    system_prompt="Daichiの価値観抽出エージェント。有効なJSONのみ出力。",
                    model_selection=model_sel,
                )
                text = result.get("text", "").strip()
                match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
                if match:
                    philosophy = json.loads(match.group())
            except Exception as e:
                logger.debug(f"哲学抽出スキップ: {e}")

            # daichi_dialogue_logに記録
            await conn.execute(
                """INSERT INTO daichi_dialogue_log
                   (channel, daichi_message, system_response, extracted_philosophy, context_level, session_id)
                   VALUES ($1, $2, $3, $4, 'standard', $5)""",
                channel, daichi_msg[:2000], alpha_response[:2000],
                json.dumps(philosophy, ensure_ascii=False) if philosophy else None,
                session_id,
            )

            # 重要な哲学をpersona_memoryに保存
            stored = False
            if philosophy and philosophy.get("importance", 0) >= 0.7:
                persona_id = await conn.fetchval(
                    """INSERT INTO persona_memory
                       (category, context, content, reasoning, emotion, source, session_id)
                       VALUES ($1, $2, $3, $4, $5, 'brain_alpha_dialogue', $6) RETURNING id""",
                    philosophy.get("category", "philosophy"),
                    f"Daichi対話 ({channel})",
                    philosophy.get("content", daichi_msg[:300]),
                    philosophy.get("reasoning", ""),
                    philosophy.get("emotion", ""),
                    session_id,
                )
                stored = True

                # ベクトル化
                try:
                    from tools.embedding_tools import embed_and_store_persona
                    await embed_and_store_persona(persona_id, philosophy.get("content", daichi_msg[:300]))
                except Exception:
                    pass

            return {
                "status": "ok",
                "philosophy_extracted": philosophy is not None,
                "stored_to_persona": stored,
                "importance": philosophy.get("importance", 0) if philosophy else 0,
            }
        except Exception as e:
            logger.error(f"対話記録失敗: {e}")
            return {"status": "error", "error": str(e)}


# ======================================================================
# 3. get_personality_summary — 人格サマリー
# ======================================================================

async def get_personality_summary() -> dict:
    """persona_memoryの全カテゴリからサマリーを生成"""
    async with get_connection() as conn:
        try:
            # カテゴリ別統計
            stats = await conn.fetch(
                """SELECT category, COUNT(*) as cnt,
                          COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                   FROM persona_memory GROUP BY category ORDER BY cnt DESC"""
            )

            # カテゴリ別代表エントリ（各上位3件）
            highlights = {}
            for row in stats:
                cat = row["category"]
                top = await conn.fetch(
                    """SELECT content FROM persona_memory
                       WHERE category = $1 ORDER BY created_at DESC LIMIT 3""",
                    cat,
                )
                highlights[cat] = [r["content"][:100] for r in top]

            total = await conn.fetchval("SELECT COUNT(*) FROM persona_memory")

            return {
                "total": total or 0,
                "categories": [
                    {"category": r["category"], "count": r["cnt"], "embedded": r["embedded"],
                     "highlights": highlights.get(r["category"], [])}
                    for r in stats
                ],
            }
        except Exception as e:
            logger.error(f"人格サマリー取得失敗: {e}")
            return {"status": "error", "error": str(e)}


def _parse_json(val):
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []
