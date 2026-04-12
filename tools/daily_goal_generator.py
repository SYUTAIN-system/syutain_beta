"""Daily Goal Generator — SYUTAINβ の自律目標生成器

2026-04-12 P2 実装。背景:
- `agents/os_kernel.py` は 5段階自律ループ (Perceive → Think → Act → Verify → StopOrContinue)
  を完全実装しているが、起動トリガーが限定的:
  - ユーザからの chat 指示 (chat_agent)
  - Discord ACTION ハンドラ (bot_actions._execute_goal)
  - 週次提案の自動承認 (scheduler.auto_approve_proposals)
- 要求駆動型なので、ユーザが何も言わない日は os_kernel が一度も動かない
- SYUTAINβ を「自律型 AI 事業 OS」と呼ぶには、毎日 1 件以上の自律ゴール実行が欲しい

設計:
- 毎朝 06:30 JST (scheduler cron) に本ツールを呼ぶ
- persona_memory の価値観 + 直近の intel_items + 未解決課題 + 本日の KPI ギャップ
  から LLM で「今日 SYUTAINβ がやるべき 1 件のゴール」を生成する
- 生成したゴールを `kernel.execute_goal(raw_goal)` で fire-and-forget 実行
- 生成頻度: 1日 1件 (朝 06:30)
- 条件: goal_packets テーブルに active or running 状態のゴールが 3 件以上あれば skip

安全:
- generate failure は Discord 通知のみで scheduler を止めない
- 生成ゴールは必ず persona_memory の taboo を回避 (CLAUDE.md Rule 26)
- LLM fallback chain: proposal (qwen3.6-plus) → chat (haiku) → local
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

MAX_CONCURRENT_GOALS = 3  # これ以上の active/running ゴールがあれば skip


_GOAL_GENERATION_SYSTEM = """あなたは SYUTAINβ の自律目標生成官。
島原大知が開発した自律型 AI 事業 OS の「今日やるべきゴール」を 1 件、自分で選ぶ。

# 役割
- 毎朝 1 件の具体的なゴール (raw_goal) を生成する
- ゴールは 5段階自律ループ (os_kernel.execute_goal) が直接消化できる形式

# ルール
1. **具体的に書く**: 「〜を改善する」ではなく「〜のX値を<=Y まで下げる」のように測定可能にする
2. **当日中に完了できる粒度**: 大きすぎず小さすぎず、1-3 時間で 1 つのサブゴール
3. **persona_memory の taboo には触れない** (後で別 filter がかかるが、生成段階から避ける)
4. **既存の自動ジョブと重複しない**: 日次運用ジョブ (SNS 投稿、note 公開、gstack review) は既に別 cron で動いているので、それらは raw_goal に含めない
5. **事実ベース**: 「GitHub スター 1000 達成」のような検証不能な目標は NG
6. **内部系を優先**: 外部依存 (X API, 他社 SaaS) が必須な goal は、そのサービスの credit が足りる時のみ
7. **Build in Public 哲学**: 失敗しても公開できるように、進捗が記録しやすい goal を選ぶ

# 除外テーマ (設計者方針で当面手を付けない)
以下のテーマを raw_goal に含めてはいけない:
- デッドコード整理、デッドコード削除、dead code
- テスト追加、ユニットテスト作成、テストカバレッジ
- 型アノテーション追加、型付け
- X API 関連 (コスト影響があるため自律目標にしない)
- 画像/動画生成 (保留中)

# 優先したい領域
- system の観測性向上 (metric 追加、ダッシュボード整備)
- 未解決の持ち越し課題 (persona_memory や未解決タスクから持ってくる)
- 1 日で完結する小さな運用改善 (既存プロンプトの few-shot 追加、設定調整)
- note / Bluesky / Threads のコンテンツ品質向上
- 情報収集パイプラインの精度向上

# 出力
以下の JSON 形式で 1 件のみ出力する。説明は不要。
```json
{
  "raw_goal": "100-200 字程度の具体的なゴール説明",
  "priority": "low" / "medium" / "high",
  "rationale": "なぜこのゴールを選んだか (50-100 字)",
  "expected_completion_hours": 1-3
}
```"""


def _build_context_prompt(
    persona_values: list[dict],
    recent_intel: list[dict],
    unresolved_tasks: list[dict],
    recent_goals: list[dict],
    kpi_summary: dict,
) -> str:
    import json as _json

    def _fmt(x):
        return _json.dumps(x, ensure_ascii=False, default=str)[:1500]

    return (
        "# 本日のゴール生成コンテキスト\n\n"
        f"## 価値観 (persona_memory, 上位 {len(persona_values)} 件)\n"
        f"{_fmt(persona_values)}\n\n"
        f"## 直近 24h の intel (上位 {len(recent_intel)} 件)\n"
        f"{_fmt(recent_intel)}\n\n"
        f"## 未解決タスク (上位 {len(unresolved_tasks)} 件)\n"
        f"{_fmt(unresolved_tasks)}\n\n"
        f"## 直近のゴール実行履歴 (参考、重複回避用)\n"
        f"{_fmt(recent_goals)}\n\n"
        f"## KPI サマリ\n"
        f"{_fmt(kpi_summary)}\n\n"
        f"# タスク\n"
        f"上記を参考に、今日 SYUTAINβ が自律的に実行する 1 件のゴールを選び、JSON で返せ。"
    )


async def _collect_context() -> dict:
    """目標生成用のコンテキストを DB から収集"""
    from tools.db_pool import get_connection

    ctx = {
        "persona_values": [],
        "recent_intel": [],
        "unresolved_tasks": [],
        "recent_goals": [],
        "kpi_summary": {},
    }

    try:
        async with get_connection() as conn:
            # persona_memory: 価値観と taboo を除くカテゴリから priority_tier 高い順
            rows = await conn.fetch(
                """SELECT category, content FROM persona_memory
                   WHERE category IN ('value','belief','strength','priority','goal_constraint','fact')
                   ORDER BY priority_tier DESC NULLS LAST, updated_at DESC LIMIT 8"""
            )
            ctx["persona_values"] = [
                {"category": r["category"], "content": (r["content"] or "")[:200]}
                for r in rows
            ]

            # intel: 直近 24h の高重要度
            rows = await conn.fetch(
                """SELECT title, LEFT(summary, 200) as summary, importance_score
                   FROM intel_items
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                     AND importance_score >= 0.6
                   ORDER BY importance_score DESC, created_at DESC LIMIT 8"""
            )
            ctx["recent_intel"] = [dict(r) for r in rows]

            # 未解決タスク: (a) claude_code_queue pending と
            #             (b) brain_alpha_session の latest.unresolved_issues を統合
            rows = await conn.fetch(
                """SELECT category, LEFT(description, 200) as description
                   FROM claude_code_queue
                   WHERE status='pending'
                   ORDER BY created_at DESC LIMIT 5"""
            )
            unresolved = [dict(r) for r in rows]

            # 最新セッションの unresolved_issues
            try:
                sess = await conn.fetchrow(
                    """SELECT unresolved_issues FROM brain_alpha_session
                       ORDER BY created_at DESC LIMIT 1"""
                )
                if sess and sess["unresolved_issues"]:
                    import json as _json
                    raw = sess["unresolved_issues"]
                    try:
                        items = raw if isinstance(raw, list) else _json.loads(raw)
                    except Exception:
                        items = []
                    for item in (items or [])[:5]:
                        unresolved.append({"category": "session_unresolved", "description": str(item)[:200]})
            except Exception:
                pass
            ctx["unresolved_tasks"] = unresolved[:10]

            # 直近 3 日のゴール (重複回避)
            rows = await conn.fetch(
                """SELECT goal_id, LEFT(COALESCE(raw_goal, parsed_objective, ''), 150) as g, status
                   FROM goal_packets
                   WHERE created_at > NOW() - INTERVAL '3 days'
                   ORDER BY created_at DESC LIMIT 10"""
            )
            ctx["recent_goals"] = [dict(r) for r in rows]

            # KPI サマリ (軽量)
            kpi = {}
            row1 = await conn.fetchrow(
                "SELECT count(*) FROM product_packages WHERE platform='note' AND status='published' AND published_at > NOW() - INTERVAL '7 days'"
            )
            row2 = await conn.fetchrow(
                "SELECT count(*) FROM posting_queue WHERE platform='x' AND status='posted' AND posted_at > NOW() - INTERVAL '7 days'"
            )
            row3 = await conn.fetchrow(
                "SELECT count(*) FROM goal_packets WHERE status IN ('active','running')"
            )
            kpi["note_published_7d"] = int(row1["count"] or 0)
            kpi["x_posts_7d"] = int(row2["count"] or 0)
            kpi["active_goals"] = int(row3["count"] or 0)
            ctx["kpi_summary"] = kpi
    except Exception as e:
        logger.warning(f"_collect_context 部分失敗: {e}")

    return ctx


async def _count_active_goals() -> int:
    """実行中のゴール数を取得"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT count(*) FROM goal_packets WHERE status IN ('active','running')"
            )
            return int(row["count"]) if row else 0
    except Exception:
        return 0


async def generate_daily_goal() -> dict:
    """本日のゴールを生成し、LLM から raw_goal を返す.

    Returns: {"ok": bool, "raw_goal": str, "priority": str, "rationale": str, "reason"?: str}
    """
    # 既に active goal が上限なら skip
    active = await _count_active_goals()
    if active >= MAX_CONCURRENT_GOALS:
        return {
            "ok": False,
            "reason": f"active_goal_cap ({active}/{MAX_CONCURRENT_GOALS})",
        }

    ctx = await _collect_context()

    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        return {"ok": False, "reason": "llm_router_unavailable"}

    # proposal task_type で qwen3.6-plus (無料) を優先
    sel = choose_best_model_v6(
        task_type="proposal",
        quality="medium",
        needs_japanese=True,
    )

    try:
        result = await call_llm(
            prompt=_build_context_prompt(
                ctx["persona_values"], ctx["recent_intel"],
                ctx["unresolved_tasks"], ctx["recent_goals"], ctx["kpi_summary"],
            ),
            system_prompt=_GOAL_GENERATION_SYSTEM,
            model_selection=sel,
            temperature=0.4,
            use_cache=False,
        )
    except Exception as e:
        logger.warning(f"daily_goal_generator LLM 失敗: {e}")
        return {"ok": False, "reason": f"llm_error: {e}"}

    text = (result.get("text") or result.get("content") or "").strip()

    # JSON 抽出
    import re
    import json as _json
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        logger.warning(f"daily_goal_generator JSON 抽出失敗: {text[:200]}")
        return {"ok": False, "reason": "json_not_found"}

    try:
        data = _json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"daily_goal_generator JSON parse 失敗: {e}, text={text[:200]}")
        return {"ok": False, "reason": f"json_parse_error: {e}"}

    raw_goal = (data.get("raw_goal") or "").strip()
    if not raw_goal:
        return {"ok": False, "reason": "empty_raw_goal"}

    return {
        "ok": True,
        "raw_goal": raw_goal,
        "priority": data.get("priority", "medium"),
        "rationale": (data.get("rationale") or "")[:500],
        "expected_completion_hours": data.get("expected_completion_hours", 2),
        "context_summary": {
            "active_goals": ctx["kpi_summary"].get("active_goals", 0),
            "note_published_7d": ctx["kpi_summary"].get("note_published_7d", 0),
            "x_posts_7d": ctx["kpi_summary"].get("x_posts_7d", 0),
        },
    }


async def run_daily_goal_cycle() -> dict:
    """毎朝 06:30 JST に scheduler から呼ばれるエントリ.

    生成 → fire-and-forget で os_kernel.execute_goal() を起動 → Discord 通知.
    """
    import asyncio

    stats = {"ok": False, "reason": "", "raw_goal": ""}

    gen = await generate_daily_goal()
    if not gen.get("ok"):
        stats["reason"] = gen.get("reason", "generation_failed")
        logger.info(f"daily_goal: 生成 skip/失敗 — {stats['reason']}")
        return stats

    raw_goal = gen["raw_goal"]
    stats["raw_goal"] = raw_goal
    stats["priority"] = gen.get("priority", "medium")
    stats["rationale"] = gen.get("rationale", "")

    # os_kernel.execute_goal() を fire-and-forget で起動
    try:
        from agents.os_kernel import get_os_kernel
        kernel = get_os_kernel()
        asyncio.create_task(kernel.execute_goal(raw_goal))
        stats["ok"] = True
        logger.info(
            f"daily_goal: 起動 — {raw_goal[:80]} (priority={gen.get('priority')})"
        )
    except Exception as e:
        stats["reason"] = f"kernel_start_failed: {e}"
        logger.error(f"daily_goal: kernel 起動失敗 — {e}")
        return stats

    # Discord 通知
    try:
        from tools.discord_notify import notify_discord
        await notify_discord(
            f"🎯 daily_goal 起動 (priority={gen.get('priority')})\n"
            f"目標: {raw_goal[:200]}\n"
            f"根拠: {gen.get('rationale', '')[:150]}"
        )
    except Exception:
        pass

    return stats
