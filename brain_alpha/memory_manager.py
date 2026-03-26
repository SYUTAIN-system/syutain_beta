"""
SYUTAINβ Brain-α 記憶階層マネージャー
設計書 Section 6 準拠

人間の脳の記憶構造を模倣:
  感覚記憶     → channelイベント（数秒で消える）
  短期記憶     → Claude Codeコンテキストウィンドウ
  長期エピソード → brain_alpha_session（いつ何をして何が起きたか）
  長期意味     → persona_memory（Daichiの人格・哲学）
  長期手続き   → CLAUDE.md + コード自体

想起のコンテキスト量制御（OpenClaw教訓: 全記憶を注入しない）
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.brain_alpha.memory")


# ======================================================================
# 1. セッション記憶の保存
# ======================================================================

async def save_session_memory(
    session_id: str,
    summary: str,
    decisions: list[str] = None,
    files_modified: list[str] = None,
    open_issues: list[str] = None,
    daichi_interactions: int = 0,
) -> bool:
    """
    セッション終了時にbrain_alpha_sessionに保存。
    前回セッションのopen_issuesを自動引き継ぎする。
    """
    async with get_connection() as conn:
        try:
            # 前回セッションの未解決課題を引き継ぎ
            prev = await conn.fetchrow(
                """SELECT unresolved_issues FROM brain_alpha_session
                   ORDER BY created_at DESC LIMIT 1"""
            )
            inherited_issues = []
            if prev and prev["unresolved_issues"]:
                try:
                    inherited_issues = json.loads(prev["unresolved_issues"]) if isinstance(prev["unresolved_issues"], str) else prev["unresolved_issues"]
                except Exception:
                    pass

            # 今回の未解決課題と統合（重複除去）
            all_open = list(dict.fromkeys(inherited_issues + (open_issues or [])))

            await conn.execute(
                """INSERT INTO brain_alpha_session
                   (session_id, started_at, ended_at, summary, key_decisions,
                    unresolved_issues, next_session_context, daichi_interactions)
                   VALUES ($1, $2, NOW(), $3, $4, $5, $6, $7)
                   ON CONFLICT (session_id) DO UPDATE SET
                     ended_at = NOW(),
                     summary = EXCLUDED.summary,
                     key_decisions = EXCLUDED.key_decisions,
                     unresolved_issues = EXCLUDED.unresolved_issues,
                     next_session_context = EXCLUDED.next_session_context,
                     daichi_interactions = EXCLUDED.daichi_interactions""",
                session_id,
                datetime.now(timezone.utc),
                summary,
                json.dumps(decisions or [], ensure_ascii=False),
                json.dumps(all_open, ensure_ascii=False),
                json.dumps({
                    "files_modified": files_modified or [],
                    "inherited_issues_count": len(inherited_issues),
                }, ensure_ascii=False),
                daichi_interactions,
            )
            logger.info(f"セッション記憶保存: {session_id} (未解決{len(all_open)}件)")
            return True
        except Exception as e:
            logger.error(f"セッション記憶保存失敗: {e}")
            return False


# ======================================================================
# 2. セッション記憶の読み込み
# ======================================================================

async def load_session_memory(limit: int = 3) -> list[dict]:
    """
    最新1件はフル詳細、2-3件目は要約のみ。
    """
    async with get_connection() as conn:
        try:
            rows = await conn.fetch(
                """SELECT session_id, started_at, ended_at, summary,
                          key_decisions, unresolved_issues, next_session_context,
                          daichi_interactions
                   FROM brain_alpha_session
                   ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
            results = []
            for i, r in enumerate(rows):
                if i == 0:
                    # 最新: フル詳細
                    results.append({
                        "session_id": r["session_id"],
                        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                        "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                        "summary": r["summary"],
                        "key_decisions": _parse_json(r["key_decisions"]),
                        "unresolved_issues": _parse_json(r["unresolved_issues"]),
                        "next_session_context": _parse_json(r["next_session_context"]),
                        "daichi_interactions": r["daichi_interactions"] or 0,
                        "detail_level": "full",
                    })
                else:
                    # 2-3件目: 要約のみ
                    results.append({
                        "session_id": r["session_id"],
                        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                        "summary": r["summary"],
                        "detail_level": "summary",
                    })
            return results
        except Exception as e:
            logger.error(f"セッション記憶読み込み失敗: {e}")
            return []


# ======================================================================
# 3. 関連記憶の想起（pgvectorベクトル検索）
# ======================================================================

async def recall_relevant_memory(query: str, limit: int = 10) -> list[dict]:
    """
    persona_memoryからpgvectorコサイン類似度検索。
    tools/embedding_tools.pyのパターンを使用。
    """
    try:
        from tools.embedding_tools import get_embedding
        embedding = await get_embedding(query)
        if not embedding:
            # フォールバック: テキスト部分一致検索
            return await _fallback_text_search(query, limit)

        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT id, category, content, reasoning, emotion,
                          1 - (embedding <=> $1::vector) as similarity
                   FROM persona_memory
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                json.dumps(embedding), limit,
            )
            return [
                {
                    "id": r["id"],
                    "category": r["category"],
                    "content": r["content"],
                    "reasoning": r["reasoning"],
                    "emotion": r["emotion"],
                    "similarity": round(float(r["similarity"]), 4),
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"関連記憶想起失敗: {e}")
        return await _fallback_text_search(query, limit)


async def _fallback_text_search(query: str, limit: int) -> list[dict]:
    """ベクトル検索不可時のフォールバック: テキスト部分一致"""
    async with get_connection() as conn:
        try:
            # クエリの最初の3単語で検索（パラメータ化クエリでSQLインジェクション防止）
            keywords = [kw for kw in query.split()[:3] if len(kw) > 1]
            if not keywords:
                rows = await conn.fetch(
                    """SELECT id, category, content, reasoning, emotion
                        FROM persona_memory
                        ORDER BY created_at DESC LIMIT $1""",
                    limit,
                )
            else:
                # $1=limit, $2〜=keywords
                conditions = " OR ".join(
                    f"content ILIKE '%' || ${i+2} || '%'" for i in range(len(keywords))
                )
                rows = await conn.fetch(
                    f"""SELECT id, category, content, reasoning, emotion
                        FROM persona_memory
                        WHERE {conditions}
                        ORDER BY created_at DESC LIMIT $1""",
                    limit, *keywords,
                )
            return [
                {"id": r["id"], "category": r["category"], "content": r["content"],
                 "reasoning": r["reasoning"], "emotion": r["emotion"], "similarity": None}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"テキスト検索フォールバック失敗: {e}")
            return []


# ======================================================================
# 4. 記憶の統合・忘却（7日以上前のセッションを圧縮）
# ======================================================================

async def consolidate_memories(days: int = 7) -> dict:
    """
    7日以上前のbrain_alpha_sessionを要約・圧縮（忘却メカニズム）。
    重要な判断だけ残し、ルーティンは圧縮する。
    LLM不使用: key_decisions非空=重要、空=ルーティンと判定。
    """
    async with get_connection() as conn:
        try:
            # 対象セッション取得
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows = await conn.fetch(
                """SELECT id, session_id, summary, key_decisions, unresolved_issues
                   FROM brain_alpha_session
                   WHERE created_at < $1
                     AND summary IS NOT NULL
                     AND summary NOT LIKE '%%[compressed]%%'
                   ORDER BY created_at ASC""",
                cutoff,
            )

            if not rows:
                return {"status": "nothing_to_consolidate", "count": 0}

            compressed = 0
            preserved = 0

            for r in rows:
                decisions = _parse_json(r["key_decisions"])
                has_important = bool(decisions and len(decisions) > 0)
                issues = _parse_json(r["unresolved_issues"])
                has_issues = bool(issues and len(issues) > 0)

                if has_important or has_issues:
                    # 重要: 要約を短縮して保持
                    short_summary = (r["summary"] or "")[:200]
                    await conn.execute(
                        """UPDATE brain_alpha_session
                           SET summary = $1
                           WHERE id = $2""",
                        f"[compressed] {short_summary}",
                        r["id"],
                    )
                    preserved += 1
                else:
                    # ルーティン: 大幅圧縮
                    await conn.execute(
                        """UPDATE brain_alpha_session
                           SET summary = $1,
                               key_decisions = '[]'::jsonb,
                               next_session_context = '{}'::jsonb
                           WHERE id = $2""",
                        f"[compressed] {(r['summary'] or '')[:80]}",
                        r["id"],
                    )
                    compressed += 1

            result = {
                "status": "ok",
                "total": len(rows),
                "preserved": preserved,
                "compressed": compressed,
                "cutoff_days": days,
            }
            logger.info(f"記憶統合完了: {result}")
            return result
        except Exception as e:
            logger.error(f"記憶統合失敗: {e}")
            return {"status": "error", "error": str(e)}


# ======================================================================
# 5. Daichiの哲学抽出・保存
# ======================================================================

async def extract_and_store_philosophy(
    daichi_message: str,
    brain_response: str,
    channel: str = "channels",
    session_id: str = None,
) -> dict:
    """
    Daichiの発言から価値観・判断基準を自動抽出。
    重要度が高いものはpersona_memoryに追加。
    daichi_dialogue_logにも記録。

    抽出にはローカルLLM使用（コスト¥0）。
    """
    async with get_connection() as conn:
        try:
            # daichi_dialogue_logに記録
            philosophy_json = None
            try:
                philosophy_json = await _extract_philosophy_via_llm(daichi_message)
            except Exception as e:
                logger.warning(f"哲学抽出LLM失敗（スキップ）: {e}")

            await conn.execute(
                """INSERT INTO daichi_dialogue_log
                   (channel, daichi_message, system_response, extracted_philosophy,
                    context_level, session_id)
                   VALUES ($1, $2, $3, $4, 'standard', $5)""",
                channel,
                daichi_message[:2000],
                brain_response[:2000],
                json.dumps(philosophy_json, ensure_ascii=False) if philosophy_json else None,
                session_id,
            )

            # 重要な哲学をpersona_memoryに保存
            stored_persona = False
            if philosophy_json and philosophy_json.get("importance", 0) >= 0.7:
                persona_id = await conn.fetchval(
                    """INSERT INTO persona_memory
                       (category, context, content, reasoning, emotion, source, session_id)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       RETURNING id""",
                    philosophy_json.get("category", "philosophy"),
                    f"Daichi対話 ({channel})",
                    philosophy_json.get("content", daichi_message[:300]),
                    philosophy_json.get("reasoning", ""),
                    philosophy_json.get("emotion", ""),
                    "brain_alpha_extract",
                    session_id,
                )
                stored_persona = True

                # ベクトル化（バックグラウンド）
                try:
                    from tools.embedding_tools import embed_and_store_persona
                    await embed_and_store_persona(persona_id, philosophy_json.get("content", daichi_message[:300]))
                except Exception:
                    pass

            return {
                "status": "ok",
                "philosophy_extracted": philosophy_json is not None,
                "stored_to_persona": stored_persona,
                "importance": philosophy_json.get("importance", 0) if philosophy_json else 0,
            }
        except Exception as e:
            logger.error(f"哲学抽出・保存失敗: {e}")
            return {"status": "error", "error": str(e)}


async def _extract_philosophy_via_llm(message: str) -> Optional[dict]:
    """ローカルLLMで哲学を抽出（コスト¥0）"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.llm_router import choose_best_model_v6, call_llm

    model_sel = choose_best_model_v6(
        task_type="classification",
        quality="low",
        budget_sensitive=True,
        local_available=True,
    )

    result = await call_llm(
        prompt=f"""以下のDaichiの発言から、価値観・判断基準・哲学を抽出してJSON出力してください。
発言にそのような要素がない場合は{{"importance": 0}}のみ返してください。

発言: {message[:500]}

JSON形式:
{{"category": "philosophy|preference|judgment|approval_pattern", "content": "抽出した価値観(1文)", "reasoning": "なぜこの発言からそう判断したか", "emotion": "感情トーン", "importance": 0.0-1.0}}""",
        system_prompt="Daichiの価値観抽出エージェント。有効なJSONのみ出力。",
        model_selection=model_sel,
    )

    text = result.get("text", "").strip()
    # JSON抽出
    import re
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ======================================================================
# 6. 想起のコンテキスト量制御
# ======================================================================

async def get_context_for_intent(intent_type: str) -> dict:
    """
    意図に応じた適切な量のコンテキストを返す。
    OpenClaw教訓: 全記憶を注入しない。

    intent_type:
      casual:    persona_memory上位5件 + 名前
      standard:  上位10件 + strategy_identity + 直近セッション
      strategic: 上位20件 + 全strategy + 直近3セッション + Daichi対話10件
      code_fix:  直近セッション + 関連トレース10件
    """
    async with get_connection() as conn:
        context = {"intent": intent_type}

        try:
            if intent_type == "casual":
                rows = await conn.fetch(
                    """SELECT content, category FROM persona_memory
                       ORDER BY created_at DESC LIMIT 5"""
                )
                context["persona"] = [{"content": r["content"], "category": r["category"]} for r in rows]
                context["identity"] = "島原大知のAI事業パートナー SYUTAIN"

            elif intent_type == "standard":
                rows = await conn.fetch(
                    """SELECT content, category, reasoning FROM persona_memory
                       ORDER BY created_at DESC LIMIT 10"""
                )
                context["persona"] = [{"content": r["content"], "category": r["category"], "reasoning": r["reasoning"]} for r in rows]

                # strategy_identity
                strategy_path = Path(__file__).resolve().parent.parent / "prompts" / "strategy_identity.md"
                if strategy_path.exists():
                    context["strategy_identity"] = strategy_path.read_text(encoding="utf-8")[:3000]

                # 直近セッション
                sessions = await conn.fetch(
                    """SELECT session_id, summary, unresolved_issues FROM brain_alpha_session
                       ORDER BY created_at DESC LIMIT 1"""
                )
                if sessions:
                    s = sessions[0]
                    context["last_session"] = {
                        "session_id": s["session_id"],
                        "summary": s["summary"],
                        "unresolved_issues": _parse_json(s["unresolved_issues"]),
                    }

            elif intent_type == "strategic":
                rows = await conn.fetch(
                    """SELECT content, category, reasoning, emotion FROM persona_memory
                       ORDER BY created_at DESC LIMIT 20"""
                )
                context["persona"] = [dict(r) for r in rows]

                # 全strategy
                strategy_dir = Path(__file__).resolve().parent.parent / "strategy"
                context["strategies"] = {}
                if strategy_dir.exists():
                    for f in strategy_dir.glob("*.md"):
                        context["strategies"][f.stem] = f.read_text(encoding="utf-8")[:2000]

                strategy_path = Path(__file__).resolve().parent.parent / "prompts" / "strategy_identity.md"
                if strategy_path.exists():
                    context["strategy_identity"] = strategy_path.read_text(encoding="utf-8")

                # 直近3セッション
                sessions = await conn.fetch(
                    """SELECT session_id, summary, key_decisions, unresolved_issues
                       FROM brain_alpha_session
                       ORDER BY created_at DESC LIMIT 3"""
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
                       FROM daichi_dialogue_log
                       ORDER BY created_at DESC LIMIT 10"""
                )
                context["daichi_dialogues"] = [
                    {"channel": d["channel"], "message": d["daichi_message"][:200],
                     "philosophy": _parse_json(d["extracted_philosophy"])}
                    for d in dialogues
                ]

            elif intent_type == "code_fix":
                # 直近セッション
                sessions = await conn.fetch(
                    """SELECT session_id, summary, key_decisions, unresolved_issues,
                              next_session_context
                       FROM brain_alpha_session
                       ORDER BY created_at DESC LIMIT 1"""
                )
                if sessions:
                    s = sessions[0]
                    context["last_session"] = {
                        "session_id": s["session_id"],
                        "summary": s["summary"],
                        "decisions": _parse_json(s["key_decisions"]),
                        "issues": _parse_json(s["unresolved_issues"]),
                        "files": _parse_json(s["next_session_context"]).get("files_modified", []),
                    }

                # 関連トレース直近10件
                traces = await conn.fetch(
                    """SELECT agent_name, task_id, action, reasoning, confidence, context
                       FROM agent_reasoning_trace
                       ORDER BY created_at DESC LIMIT 10"""
                )
                context["traces"] = [
                    {"agent": t["agent_name"], "task_id": t["task_id"], "action": t["action"],
                     "reasoning": t["reasoning"][:200], "confidence": float(t["confidence"]) if t["confidence"] else None}
                    for t in traces
                ]

            return context
        except Exception as e:
            logger.error(f"コンテキスト取得失敗 ({intent_type}): {e}")
            return {"intent": intent_type, "error": str(e)}


# ======================================================================
# ユーティリティ
# ======================================================================

def _parse_json(val) -> list | dict:
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []
