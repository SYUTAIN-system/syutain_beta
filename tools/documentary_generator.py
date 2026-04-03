"""
SYUTAINβ ドキュメンタリー記事自動生成
自システムの運用データ・成功・失敗から note 有料記事を生成する。

データソース:
- event_log: 重要イベント、エラー、復旧
- llm_cost_log: コスト推移、ローカル vs API比率
- tasks: 完了率、品質スコア
- posting_queue: SNS投稿統計
- failure_memory: 学んだ教訓
- brain_alpha_session: Brain-αの成果
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.event_logger import log_event

logger = logging.getLogger("syutain.documentary_generator")

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"

# 記事タイプのローテーション（週ごとに順番に回す）
ARTICLE_TYPES = [
    {
        "key": "sns_stats",
        "title_hint": "AIエージェントにSNS投稿を任せた結果",
        "focus": "SNS投稿の統計・品質・エンゲージメント",
        "primary_tables": ["posting_queue", "posting_queue_engagement"],
    },
    {
        "key": "cost_breakdown",
        "title_hint": "月XX円で動く自律AIシステムの内部",
        "focus": "LLMコスト・ローカル vs API比率・予算管理",
        "primary_tables": ["llm_cost_log", "model_quality_log"],
    },
    {
        "key": "failure_stories",
        "title_hint": "AIが自分で判断して失敗から学ぶ仕組み",
        "focus": "failure_memory の教訓・復旧ストーリー",
        "primary_tables": ["failure_memory", "event_log"],
    },
    {
        "key": "architecture",
        "title_hint": "コードゼロで作った分散AIシステムの全貌",
        "focus": "4台構成・ノード間通信・自律判断アーキテクチャ",
        "primary_tables": ["capability_snapshots", "event_log"],
    },
    {
        "key": "weekly_summary",
        "title_hint": "今週のSYUTAINβ: 成功と失敗の記録",
        "focus": "週次サマリー・タスク完了率・ハイライト",
        "primary_tables": ["tasks", "event_log", "brain_alpha_session"],
    },
]


def _load_text(filename: str) -> str:
    """strategy/ からテキストを読み込む"""
    path = STRATEGY_DIR / filename
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


async def _determine_article_type(conn) -> dict:
    """過去の生成履歴からローテーションで次の記事タイプを決定する"""
    try:
        row = await conn.fetchrow(
            """SELECT output_data->>'article_type' AS last_type
            FROM tasks
            WHERE type = 'documentary_article' AND status IN ('success', 'completed')
            ORDER BY created_at DESC LIMIT 1"""
        )
        last_key = row["last_type"] if row and row["last_type"] else None
    except Exception:
        last_key = None

    # 直前のタイプの次を選ぶ
    keys = [a["key"] for a in ARTICLE_TYPES]
    if last_key and last_key in keys:
        idx = (keys.index(last_key) + 1) % len(ARTICLE_TYPES)
    else:
        idx = 0
    return ARTICLE_TYPES[idx]


# ===== データ収集クエリ =====


async def _collect_sns_stats(conn) -> dict:
    """posting_queue から直近7日の SNS 統計を収集"""
    try:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'posted') AS posted,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                ROUND(AVG(quality_score)::numeric, 3) AS avg_quality,
                COUNT(DISTINCT platform) AS platforms,
                COUNT(DISTINCT theme_category) AS themes
            FROM posting_queue
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        engagement = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(likes), 0) AS total_likes,
                COALESCE(SUM(reposts), 0) AS total_reposts,
                COALESCE(SUM(impressions), 0) AS total_impressions
            FROM posting_queue_engagement
            WHERE checked_at > NOW() - INTERVAL '7 days'
        """)
        return {
            "total_posts": stats["total"] if stats else 0,
            "posted": stats["posted"] if stats else 0,
            "failed": stats["failed"] if stats else 0,
            "avg_quality": float(stats["avg_quality"]) if stats and stats["avg_quality"] else 0,
            "platforms": stats["platforms"] if stats else 0,
            "themes": stats["themes"] if stats else 0,
            "total_likes": engagement["total_likes"] if engagement else 0,
            "total_reposts": engagement["total_reposts"] if engagement else 0,
            "total_impressions": engagement["total_impressions"] if engagement else 0,
        }
    except Exception as e:
        logger.warning(f"SNS統計収集失敗: {e}")
        return {}


async def _collect_cost_data(conn) -> dict:
    """llm_cost_log から直近30日のコストデータを収集"""
    try:
        monthly = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(amount_jpy), 0) AS total_jpy,
                COUNT(*) AS call_count,
                COUNT(DISTINCT model) AS model_count
            FROM llm_cost_log
            WHERE recorded_at > NOW() - INTERVAL '30 days'
        """)
        weekly = await conn.fetchrow("""
            SELECT COALESCE(SUM(amount_jpy), 0) AS weekly_jpy
            FROM llm_cost_log
            WHERE recorded_at > NOW() - INTERVAL '7 days'
        """)
        by_tier = await conn.fetch("""
            SELECT tier, COALESCE(SUM(amount_jpy), 0) AS tier_jpy, COUNT(*) AS tier_count
            FROM llm_cost_log
            WHERE recorded_at > NOW() - INTERVAL '30 days'
            GROUP BY tier ORDER BY tier_jpy DESC
        """)
        top_models = await conn.fetch("""
            SELECT model, COALESCE(SUM(amount_jpy), 0) AS model_jpy, COUNT(*) AS calls
            FROM llm_cost_log
            WHERE recorded_at > NOW() - INTERVAL '30 days'
            GROUP BY model ORDER BY model_jpy DESC LIMIT 5
        """)
        return {
            "monthly_total_jpy": float(monthly["total_jpy"]) if monthly else 0,
            "monthly_calls": monthly["call_count"] if monthly else 0,
            "model_count": monthly["model_count"] if monthly else 0,
            "weekly_jpy": float(weekly["weekly_jpy"]) if weekly else 0,
            "by_tier": [
                {"tier": r["tier"], "jpy": float(r["tier_jpy"]), "count": r["tier_count"]}
                for r in by_tier
            ] if by_tier else [],
            "top_models": [
                {"model": r["model"], "jpy": float(r["model_jpy"]), "calls": r["calls"]}
                for r in top_models
            ] if top_models else [],
        }
    except Exception as e:
        logger.warning(f"コストデータ収集失敗: {e}")
        return {}


async def _collect_task_stats(conn) -> dict:
    """tasks テーブルから直近7日のタスク統計を収集"""
    try:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'success') AS success,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                ROUND(AVG(quality_score)::numeric, 3) AS avg_quality,
                COUNT(DISTINCT type) AS task_types,
                COUNT(DISTINCT assigned_node) AS nodes_used
            FROM tasks
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        return {
            "total": stats["total"] if stats else 0,
            "success": stats["success"] if stats else 0,
            "failed": stats["failed"] if stats else 0,
            "pending": stats["pending"] if stats else 0,
            "avg_quality": float(stats["avg_quality"]) if stats and stats["avg_quality"] else 0,
            "task_types": stats["task_types"] if stats else 0,
            "nodes_used": stats["nodes_used"] if stats else 0,
        }
    except Exception as e:
        logger.warning(f"タスク統計収集失敗: {e}")
        return {}


async def _collect_failure_stories(conn) -> list:
    """failure_memory から教訓になるストーリーを収集"""
    try:
        rows = await conn.fetch("""
            SELECT failure_type, task_type, error_message, root_cause,
                   prevention_rule, occurrence_count, first_seen, last_seen, resolved
            FROM failure_memory
            WHERE last_seen > NOW() - INTERVAL '30 days'
            ORDER BY occurrence_count DESC, last_seen DESC
            LIMIT 10
        """)
        return [
            {
                "failure_type": r["failure_type"],
                "task_type": r["task_type"],
                "error": (r["error_message"] or "")[:200],
                "root_cause": r["root_cause"],
                "prevention_rule": r["prevention_rule"],
                "occurrences": r["occurrence_count"],
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "resolved": r["resolved"],
            }
            for r in rows
        ] if rows else []
    except Exception as e:
        logger.warning(f"failure_memory収集失敗: {e}")
        return []


async def _collect_event_highlights(conn) -> list:
    """event_log から直近7日の重要イベントを収集"""
    try:
        rows = await conn.fetch("""
            SELECT event_type, category, severity, source_node, payload, created_at
            FROM event_log
            WHERE created_at > NOW() - INTERVAL '7 days'
              AND severity IN ('warning', 'error', 'critical')
            ORDER BY created_at DESC
            LIMIT 20
        """)
        return [
            {
                "type": r["event_type"],
                "category": r["category"],
                "severity": r["severity"],
                "node": r["source_node"],
                "payload_summary": (r["payload"] or "{}")[:200],
                "when": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ] if rows else []
    except Exception as e:
        logger.warning(f"イベントハイライト収集失敗: {e}")
        return []


async def _collect_brain_sessions(conn) -> list:
    """brain_alpha_session から直近の成果を収集"""
    try:
        rows = await conn.fetch("""
            SELECT session_id, started_at, ended_at, summary,
                   key_decisions, daichi_interactions
            FROM brain_alpha_session
            WHERE started_at > NOW() - INTERVAL '7 days'
            ORDER BY started_at DESC
            LIMIT 5
        """)
        return [
            {
                "session_id": r["session_id"],
                "started": r["started_at"].isoformat() if r["started_at"] else None,
                "summary": (r["summary"] or "")[:300],
                "key_decisions": r["key_decisions"],
                "daichi_interactions": r["daichi_interactions"],
            }
            for r in rows
        ] if rows else []
    except Exception as e:
        logger.warning(f"brain_alpha_session収集失敗: {e}")
        return []


async def _load_persona(conn) -> str:
    """persona_memory から価値観を取得"""
    try:
        rows = await conn.fetch(
            """SELECT content FROM persona_memory
            WHERE category IN ('philosophy', 'identity')
            ORDER BY created_at DESC LIMIT 10"""
        )
        if not rows:
            return ""
        lines = [f"- {(r['content'] or '')[:120]}" for r in rows]
        return "【島原大知の価値観】\n" + "\n".join(lines)
    except Exception:
        return ""


# ===== メイン生成関数 =====


async def generate_documentary_article() -> dict:
    """
    SYUTAINβ の運用データからドキュメンタリー記事を生成する。

    Returns:
        dict: {title, content, theme, article_type, quality_score, data_sources_used, stages, metadata}
    """
    task_id = str(uuid4())
    stages = []
    data_sources_used = []
    writing_style = _load_text("daichi_writing_style.md")
    content_patterns = _load_text("daichi_content_patterns.md")

    async with get_connection() as conn:
        # ===== Phase 0: 記事タイプ決定 =====
        article_type = await _determine_article_type(conn)
        type_key = article_type["key"]
        stages.append({
            "stage": 0, "name": "記事タイプ決定",
            "status": "success", "detail": f"{type_key}: {article_type['title_hint']}",
        })

        # ===== Phase 1: データ収集 =====
        all_data = {}
        try:
            # 全タイプ共通で基本統計は取得（記事の厚みのため）
            all_data["sns"] = await _collect_sns_stats(conn)
            if all_data["sns"]:
                data_sources_used.append("posting_queue")

            all_data["cost"] = await _collect_cost_data(conn)
            if all_data["cost"]:
                data_sources_used.append("llm_cost_log")

            all_data["tasks"] = await _collect_task_stats(conn)
            if all_data["tasks"]:
                data_sources_used.append("tasks")

            all_data["failures"] = await _collect_failure_stories(conn)
            if all_data["failures"]:
                data_sources_used.append("failure_memory")

            all_data["events"] = await _collect_event_highlights(conn)
            if all_data["events"]:
                data_sources_used.append("event_log")

            all_data["brain_sessions"] = await _collect_brain_sessions(conn)
            if all_data["brain_sessions"]:
                data_sources_used.append("brain_alpha_session")

            stages.append({
                "stage": 1, "name": "データ収集",
                "status": "success",
                "detail": f"sources={data_sources_used}",
            })
        except Exception as e:
            logger.error(f"データ収集失敗: {e}")
            stages.append({"stage": 1, "name": "データ収集", "status": "error", "detail": str(e)})

        # データが全く取れなかった場合は中止
        if not any(all_data.values()):
            return {
                "title": "", "content": "", "theme": type_key,
                "article_type": type_key, "quality_score": 0.0,
                "data_sources_used": [], "stages": stages,
                "metadata": {"task_id": task_id, "error": "データ収集結果が空"},
            }

        # ===== Phase 2: データサマリー構築 =====
        data_summary = _build_data_summary(all_data, type_key)
        persona_text = await _load_persona(conn)

        # ===== Phase 3: タイトル + 構成案生成 =====
        try:
            model_sel_outline = choose_best_model_v6(
                task_type="analysis", quality="medium",
                budget_sensitive=True, needs_japanese=True,
            )
            outline_prompt = (
                f"SYUTAINβ（自律AI事業OS）の実際の運用データをもとに、"
                f"note有料記事（500円）のタイトルと構成案を作成してください。\n\n"
                f"## 記事テーマ\n{article_type['title_hint']}\n"
                f"フォーカス: {article_type['focus']}\n\n"
                f"## 実データ\n{data_summary}\n\n"
                f"## 記事構造\n"
                f"1. タイトル案を3つ（実データの数値を含めること）\n"
                f"2. 無料パート（1000-1500字）の構成\n"
                f"   - フック: 実データの衝撃的な数字から入る\n"
                f"   - 概要: SYUTAINβとは何か（初見読者向け）\n"
                f"   - データのハイライト（一部だけ見せる）\n"
                f"   - クリフハンガー: 有料パートへの期待\n"
                f"3. 有料パート（4500-6500字）の構成\n"
                f"   - 詳細なデータ分析\n"
                f"   - 失敗から学んだ教訓\n"
                f"   - 技術的な舞台裏\n"
                f"   - 島原大知の所感と次のアクション\n\n"
                f"タイトル案3つ + 構成案を出力してください。\n"
                f"\n{persona_text}"
            )
            result_outline = await call_llm(
                prompt=outline_prompt,
                system_prompt=(
                    "島原大知のnote有料記事の構成アシスタント。\n"
                    "SYUTAINβの運用データをそのまま使い、数値を捏造しないこと。\n"
                    "「AIシステムの運用リアル」を読者に伝える構成を設計する。\n"
                    f"{content_patterns[:2000]}"
                ),
                model_selection=model_sel_outline,
            )
            outline = result_outline.get("text", "").strip()
            if not outline:
                raise ValueError("構成案が空")
            stages.append({
                "stage": 3, "name": "タイトル+構成案",
                "status": "success",
                "model": model_sel_outline.get("model", "unknown"),
                "detail": outline[:300],
            })
        except Exception as e:
            logger.error(f"構成案生成失敗: {e}")
            return {
                "title": article_type["title_hint"], "content": "",
                "theme": type_key, "article_type": type_key,
                "quality_score": 0.0, "data_sources_used": data_sources_used,
                "stages": stages + [{"stage": 3, "name": "構成案", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"構成案生成失敗: {e}"},
            }

        # ===== Phase 4: 本文生成 =====
        try:
            model_sel_draft = choose_best_model_v6(
                task_type="content_final", quality="high",
                budget_sensitive=False, needs_japanese=True,
                final_publish=True,
            )
            draft_prompt = (
                f"以下の構成案と実データに基づき、6000字以上のnote有料記事を執筆してください。\n"
                f"この記事はSYUTAINβの「ドキュメンタリー記事」です。\n"
                f"自分たちのAIシステムが実際に動いている生のデータを、読者に見せる記事です。\n\n"
                f"## 構成案\n{outline}\n\n"
                f"## 実データ（この数値をそのまま使うこと。絶対に変えない）\n{data_summary}\n\n"
                f"## noteフォーマット（厳守）\n\n"
                f"### 無料パート（冒頭〜「---ここから有料---」まで、1000-1500字）\n"
                f"- 衝撃的な冒頭: 実データの数字で始める（例: 「この1週間で、AIが自動生成したSNS投稿は{all_data.get('sns', {}).get('total_posts', 'XX')}件。」）\n"
                f"- SYUTAINβの概要: 4台のPC、6体のAIエージェント、月XX円で動く自律システム\n"
                f"- 「こういう情報、普通は出てこない」という独自性の強調\n"
                f"- データの一部をチラ見せ\n"
                f"- クリフハンガー: 有料パートへの引き\n\n"
                f"### 本文中に必ず以下のマーカーを入れる:\n"
                f"```\n---ここから有料---\n```\n\n"
                f"### 有料パート（「---ここから有料---」以降、4500-6500字）\n"
                f"- データの詳細分析（表やリスト形式で見やすく）\n"
                f"- 失敗のストーリー（failure_memoryから具体的に）\n"
                f"- 技術的な舞台裏（ノード構成、モデル選定、コスト最適化）\n"
                f"- 「やってみて分かったこと」（教科書に載っていない知見）\n"
                f"- 島原大知の所感（このシステムを動かしていて何を感じるか）\n"
                f"- 次週の計画・実験予定\n\n"
                f"## 絶対禁止\n"
                f"- 実データと異なる数値を書くこと\n"
                f"- 架空のエピソード\n"
                f"- AI定型句（「いかがでしょうか」「深掘り」「特筆すべき」）\n"
                f"- 抽象的な一般論だけの段落\n\n"
                f"記事本文のみを出力。メタ情報や説明は不要。"
            )
            result_draft = await call_llm(
                prompt=draft_prompt,
                system_prompt=(
                    "あなたは島原大知として、SYUTAINβのドキュメンタリー記事を執筆する。\n"
                    "この記事の最大の価値は「リアルなデータ」。\n"
                    "AIシステムを実際に動かしている人間にしか書けない内容を提供する。\n"
                    "数値は実データをそのまま使う。丸めても良いが、捏造は絶対にしない。\n\n"
                    f"{writing_style[:2000]}\n\n"
                    f"{persona_text}"
                ),
                model_selection=model_sel_draft,
            )
            draft = result_draft.get("text", "").strip()
            if not draft or len(draft) < 2000:
                raise ValueError(f"初稿が短すぎる（{len(draft)}字）")
            stages.append({
                "stage": 4, "name": "本文生成",
                "status": "success",
                "model": model_sel_draft.get("model", "unknown"),
                "detail": f"{len(draft)}字",
            })
        except Exception as e:
            logger.error(f"本文生成失敗: {e}")
            return {
                "title": article_type["title_hint"], "content": "",
                "theme": type_key, "article_type": type_key,
                "quality_score": 0.0, "data_sources_used": data_sources_used,
                "stages": stages + [{"stage": 4, "name": "本文生成", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"本文生成失敗: {e}"},
            }

        # ===== Phase 5: リライト（島原の声） =====
        try:
            model_sel_rewrite = choose_best_model_v6(
                task_type="quality_verification", quality="high",
                budget_sensitive=True, needs_japanese=True,
            )
            min_length = len(draft)
            rewrite_prompt = (
                f"以下のドキュメンタリー記事を島原大知の声でリライトしてください。\n"
                f"500円の有料note記事です。\n\n"
                f"【最重要】元原稿は{min_length}字です。最低{min_length}字以上を維持。"
                f"短縮・要約は絶対に行わないでください。\n\n"
                f"リライトの指針:\n"
                f"- 一人称は「自分」「僕」「私」を場面に応じて使い分ける\n"
                f"- 三点リーダー（…）で余韻を残す\n"
                f"- 段落は短く（1-3文で改行）\n"
                f"- 「正直」「だが」「でも」で逆接を多用\n"
                f"- 核心部分は**太字**で強調\n"
                f"- AI臭い定型表現は一切使わない\n"
                f"- データの数値は変えない\n"
                f"- 記事本文のみを出力\n\n"
                f"## 元原稿\n{draft}"
            )
            result_rewrite = await call_llm(
                prompt=rewrite_prompt,
                system_prompt=(
                    "島原大知の文体でリライトするエディター。\n"
                    "ドキュメンタリー記事のため、データの正確性を最優先する。\n"
                    "数値を変えてはいけない。文体だけを島原大知に寄せる。\n\n"
                    f"{writing_style[:2000]}\n\n"
                    f"{persona_text}"
                ),
                model_selection=model_sel_rewrite,
            )
            rewritten = result_rewrite.get("text", "").strip()
            if not rewritten or len(rewritten) < 2000:
                logger.warning(f"リライト結果が短い（{len(rewritten)}字）、初稿を使用")
                rewritten = draft
                stages.append({
                    "stage": 5, "name": "リライト",
                    "status": "fallback", "detail": "リライト結果が短すぎ、初稿を使用",
                })
            else:
                stages.append({
                    "stage": 5, "name": "リライト",
                    "status": "success",
                    "model": model_sel_rewrite.get("model", "unknown"),
                    "detail": f"{len(rewritten)}字",
                })
        except Exception as e:
            logger.warning(f"リライト失敗（初稿で続行）: {e}")
            rewritten = draft
            stages.append({"stage": 5, "name": "リライト", "status": "error", "detail": str(e)})

        # ===== Phase 6: 品質検証 =====
        try:
            from brain_alpha.sns_batch import _score_multi_axis, _PERSONA_KEYWORDS
            quality_score = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)
        except Exception:
            quality_score = 0.5  # 品質検証失敗時はデフォルト

        # データ検証: 実データの数値が本文に含まれているか
        data_accuracy = _verify_data_in_text(rewritten, all_data)
        stages.append({
            "stage": 6, "name": "品質検証",
            "status": "accepted" if quality_score >= 0.50 else "marginal",
            "detail": f"score={quality_score:.3f}, data_accuracy={data_accuracy:.1%}",
        })

        # タイトル抽出（本文の1行目から）
        lines = rewritten.strip().split("\n")
        raw_title = lines[0].strip().lstrip("#").strip() if lines else article_type["title_hint"]
        if not raw_title or len(raw_title) < 5:
            raw_title = article_type["title_hint"]
        # 100文字制限
        title = raw_title[:97] + "..." if len(raw_title) > 100 else raw_title

        status = "success" if quality_score >= 0.50 else "failed"

        # tasksテーブルに保存
        output_data = {
            "title": title,
            "content": rewritten,
            "theme": type_key,
            "article_type": type_key,
            "quality_score": quality_score,
            "data_accuracy": data_accuracy,
            "data_sources_used": data_sources_used,
            "stages": stages,
            "actual_length": len(rewritten),
            "raw_data": {k: v for k, v in all_data.items() if v},
        }
        try:
            last_model = "unknown"
            for s in reversed(stages):
                if "model" in s:
                    last_model = s["model"]
                    break

            await conn.execute(
                """INSERT INTO tasks (id, goal_id, type, status, assigned_node, model_used, quality_score, output_data, created_at)
                VALUES ($1, 'documentary_pipeline', $2, $3, 'alpha', $4, $5, $6, NOW())""",
                task_id,
                "documentary_article",
                status,
                last_model,
                quality_score,
                json.dumps(output_data, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.error(f"tasks保存失敗: {e}")

        # イベントログ
        try:
            await log_event(
                event_type="documentary.generated",
                category="content",
                payload={
                    "task_id": task_id,
                    "article_type": type_key,
                    "title": title,
                    "quality_score": quality_score,
                    "length": len(rewritten),
                    "data_sources": data_sources_used,
                },
                severity="info",
            )
        except Exception:
            pass

    logger.info(
        f"ドキュメンタリー記事生成完了: task_id={task_id}, type={type_key}, "
        f"score={quality_score:.3f}, length={len(rewritten)}字"
    )

    return {
        "title": title,
        "content": rewritten,
        "theme": type_key,
        "article_type": type_key,
        "quality_score": quality_score,
        "data_sources_used": data_sources_used,
        "stages": stages,
        "metadata": {
            "task_id": task_id,
            "status": status,
            "actual_length": len(rewritten),
            "data_accuracy": data_accuracy,
        },
    }


def _build_data_summary(all_data: dict, type_key: str) -> str:
    """収集データを LLM に渡すテキストサマリーに整形する"""
    parts = []

    sns = all_data.get("sns", {})
    if sns:
        parts.append(
            f"### SNS投稿（直近7日）\n"
            f"- 総投稿数: {sns.get('total_posts', 0)}件\n"
            f"- 投稿成功: {sns.get('posted', 0)}件 / 失敗: {sns.get('failed', 0)}件\n"
            f"- 平均品質スコア: {sns.get('avg_quality', 0)}\n"
            f"- プラットフォーム数: {sns.get('platforms', 0)}\n"
            f"- テーマカテゴリ数: {sns.get('themes', 0)}\n"
            f"- 合計いいね: {sns.get('total_likes', 0)} / リポスト: {sns.get('total_reposts', 0)}\n"
            f"- 合計インプレッション: {sns.get('total_impressions', 0)}"
        )

    cost = all_data.get("cost", {})
    if cost:
        tier_lines = "\n".join(
            f"  - {t['tier']}: {t['jpy']:.1f}円 ({t['count']}回)"
            for t in cost.get("by_tier", [])
        )
        model_lines = "\n".join(
            f"  - {m['model']}: {m['jpy']:.1f}円 ({m['calls']}回)"
            for m in cost.get("top_models", [])
        )
        parts.append(
            f"### LLMコスト（直近30日）\n"
            f"- 月間合計: {cost.get('monthly_total_jpy', 0):.1f}円\n"
            f"- 週間コスト: {cost.get('weekly_jpy', 0):.1f}円\n"
            f"- API呼び出し回数: {cost.get('monthly_calls', 0)}回\n"
            f"- 使用モデル数: {cost.get('model_count', 0)}\n"
            f"- ティア別:\n{tier_lines}\n"
            f"- モデル別TOP5:\n{model_lines}"
        )

    tasks = all_data.get("tasks", {})
    if tasks:
        total = tasks.get("total", 0)
        success = tasks.get("success", 0)
        rate = (success / total * 100) if total > 0 else 0
        parts.append(
            f"### タスク統計（直近7日）\n"
            f"- 総タスク数: {total}件\n"
            f"- 成功: {success}件 / 失敗: {tasks.get('failed', 0)}件 / 保留: {tasks.get('pending', 0)}件\n"
            f"- 完了率: {rate:.1f}%\n"
            f"- 平均品質スコア: {tasks.get('avg_quality', 0)}\n"
            f"- タスク種別数: {tasks.get('task_types', 0)}\n"
            f"- 稼働ノード数: {tasks.get('nodes_used', 0)}"
        )

    failures = all_data.get("failures", [])
    if failures:
        failure_lines = "\n".join(
            f"  - [{f['failure_type']}] {f.get('root_cause', '原因不明')}"
            f" (発生{f['occurrences']}回, 解決={'済' if f['resolved'] else '未'})"
            for f in failures[:5]
        )
        parts.append(
            f"### 失敗記録（直近30日、上位{len(failures)}件）\n{failure_lines}"
        )

    events = all_data.get("events", [])
    if events:
        event_lines = "\n".join(
            f"  - [{e['severity']}] {e['type']} @ {e['node']} ({e['when'][:10] if e.get('when') else '?'})"
            for e in events[:10]
        )
        parts.append(
            f"### 重要イベント（直近7日、{len(events)}件）\n{event_lines}"
        )

    sessions = all_data.get("brain_sessions", [])
    if sessions:
        session_lines = "\n".join(
            f"  - {s.get('summary', '(サマリーなし)')[:100]}"
            for s in sessions[:3]
        )
        parts.append(
            f"### Brain-αセッション（直近7日、{len(sessions)}件）\n{session_lines}"
        )

    return "\n\n".join(parts) if parts else "（データ収集結果なし）"


def _verify_data_in_text(text: str, all_data: dict) -> float:
    """本文中に実データの数値が含まれているかを検証する（0.0-1.0）"""
    checks = []

    sns = all_data.get("sns", {})
    if sns.get("total_posts"):
        checks.append(str(sns["total_posts"]) in text)
    if sns.get("posted"):
        checks.append(str(sns["posted"]) in text)

    cost = all_data.get("cost", {})
    if cost.get("monthly_total_jpy"):
        # 小数点以下を含む可能性があるため、整数部分で確認
        int_cost = str(int(cost["monthly_total_jpy"]))
        checks.append(int_cost in text)

    tasks = all_data.get("tasks", {})
    if tasks.get("total"):
        checks.append(str(tasks["total"]) in text)

    if not checks:
        return 1.0  # チェック項目がない場合は満点扱い
    return sum(checks) / len(checks)
