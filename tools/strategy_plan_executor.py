"""
戦略書実行エンジン — strategy_plan_items の今日のアイテムを自動実行する

島原さん方針(2026-04-11): 完全自動実行優先。人間介入前提を撤廃。

実行ルーティング:
- x_post → posting_queue に status='pending' で投入（SNSバッチが通常の承認フローで自動投稿）
- note_article → product_packages に status='ready' で投入（note_auto_publish が自動公開）
- weekly_report → product_packages に status='ready' で投入
- reply_day → auto_executable=False なのでスキップ（人間のリプ活動）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tools.db_pool import get_connection
from tools.strategy_plan_parser import (
    get_today_items,
    mark_item_executed,
    sync_strategy_plan,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _count_python_lines(root: str) -> int:
    """find + wc で Python 総行数を返す（失敗時は0）"""
    result = subprocess.run(
        ["bash", "-c",
         f"find '{root}' -name '*.py' -not -path '*/venv/*' -not -path '*/__pycache__/*' "
         "-exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}'"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return int(result.stdout.strip() or 0)


def _count_ts_lines(root: str) -> int:
    """find + wc で TS/TSX 総行数を返す（失敗時は0）"""
    result = subprocess.run(
        ["bash", "-c",
         f"find '{root}' \\( -name '*.ts' -o -name '*.tsx' \\) -not -path '*/node_modules/*' "
         "-exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}'"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return int(result.stdout.strip() or 0)


async def _resolve_dynamic_values() -> dict[str, Any]:
    """戦略書テンプレートに埋め込む動的値をDBから取得する"""
    vals: dict[str, Any] = {}

    # Python/TS 行数（ファイルシステムから）
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py_lines = await asyncio.to_thread(_count_python_lines, root)
        vals["python_lines"] = f"{py_lines:,}"
        vals["code_lines"] = vals["python_lines"]
    except Exception as e:
        logger.warning(f"python行数取得失敗: {e}")
        vals["python_lines"] = "69,000"
        vals["code_lines"] = "69,000"

    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ts_lines = await asyncio.to_thread(_count_ts_lines, root)
        vals["ts_lines"] = f"{ts_lines:,}"
    except Exception:
        vals["ts_lines"] = "57,000"

    async with get_connection() as conn:
        # LLM呼び出し累計・API代累計
        try:
            row = await conn.fetchrow(
                "SELECT count(*) AS calls, sum(amount_jpy)::numeric(10,2) AS total FROM llm_cost_log"
            )
            llm_calls = int(row["calls"] or 0)
            api_total = float(row["total"] or 0)
            vals["llm_calls"] = f"{llm_calls:,}"
            vals["llm_total"] = vals["llm_calls"]
            vals["api_total"] = f"{api_total:,.0f}"
            vals["api_per_call"] = f"{(api_total / llm_calls if llm_calls else 0):.1f}"
        except Exception as e:
            logger.warning(f"llm_cost_log取得失敗: {e}")
            vals.setdefault("llm_calls", "11,695")
            vals.setdefault("llm_total", "11,695")
            vals.setdefault("api_total", "1,236")
            vals.setdefault("api_per_call", "0.1")

        # intel_items 累計
        try:
            intel_total = await conn.fetchval("SELECT count(*) FROM intel_items")
            vals["intel_total"] = f"{int(intel_total or 0):,}"
        except Exception:
            vals["intel_total"] = "1,555"

        # スケジューラジョブ数（現在稼働中の概数 — 動的に取れないので既定値）
        vals["job_count"] = "68"

        # 収益
        try:
            rev = await conn.fetchval(
                "SELECT COALESCE(sum(amount_jpy), 0)::int FROM commerce_transactions "
                "WHERE status='completed'"
            )
            vals["revenue"] = f"{int(rev or 0):,}"
        except Exception:
            vals["revenue"] = "0"

        # 電気代（固定値。実測はしていない）
        vals["power_cost"] = "8,000"

        # posts posted
        try:
            posts_total = await conn.fetchval(
                "SELECT count(*) FROM posting_queue WHERE status='posted'"
            )
            vals["posts_total"] = f"{int(posts_total or 0):,}"
        except Exception:
            vals["posts_total"] = "552"

    # 週報用フィールドのデフォルト（Day 7で上書き）
    for field, default in {
        "follower_prev": "0", "follower_now": "0", "follower_delta": "0",
        "x_imp_shimahara": "0", "x_imp_syutain": "0",
        "bluesky_likes": "0", "bluesky_reposts": "0",
        "threads_views": "0", "threads_likes": "0",
        "note_pv": "0", "note_count": "0", "quality_pass_rate": "0",
        "api_week": "0", "llm_week": "0",
        "local_ratio": "87",
        "grok_count": "0", "overseas_count": "0", "intel_week": "0",
        "crypto_count": "0", "engagement_count": "0",
        "job_runs": "0", "codex_fix_count": "0",
        "best_progress": "（観測中）",
        "worst_incident": "（観測中）",
        "next_week_bet": "（来週決定）",
    }.items():
        vals.setdefault(field, default)

    return vals


def _substitute(template: str, values: dict[str, Any]) -> str:
    """テンプレート中の {field} を values で置換。KeyError は握りつぶす"""
    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(_SafeDict(values))


async def _execute_x_post(item: dict, values: dict) -> str | None:
    """X投稿アイテムを posting_queue に投入"""
    content = item["content"]
    if (item.get("metadata") or {}).get("dynamic_values"):
        content = _substitute(content, values)

    # [SYUTAINβ auto-generated] ラベルを付与（CLAUDE.md Rule 30対応: 島原の声でもラベル必須）
    if item.get("account") == "shimahara" and "[SYUTAINβ" not in content:
        content = content + "\n\n[SYUTAINβ auto-generated]"

    async with get_connection() as conn:
        # Dedupe: same first 30 chars already posted in last 48h
        head = content[:30]
        exists = await conn.fetchval(
            """SELECT id FROM posting_queue
               WHERE platform = $1 AND account = $2
                 AND substring(content, 1, 30) = $3
                 AND created_at > NOW() - INTERVAL '48 hours'
               LIMIT 1""",
            item["platform"], item["account"], head,
        )
        if exists:
            logger.info(
                f"strategy_exec: 重複検出スキップ Day{item['day_number']} "
                f"({item['platform']}/{item['account']}) existing={exists}"
            )
            return None

        # スケジュール時刻: 今日の09:00 JST（過去なら今から5分後）
        now = datetime.now(JST)
        scheduled = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if scheduled <= now:
            scheduled = now + timedelta(minutes=5)

        pid = await conn.fetchval(
            """INSERT INTO posting_queue
               (platform, account, content, scheduled_at, status, theme_category)
               VALUES ($1, $2, $3, $4, 'pending', 'strategy_plan')
               RETURNING id""",
            item["platform"], item["account"], content, scheduled,
        )
        logger.info(
            f"strategy_exec: posting_queue投入 Day{item['day_number']} "
            f"({item['platform']}/{item['account']}) id={pid} scheduled={scheduled.strftime('%H:%M')}"
        )
        return f"posting_queue:{pid}"


async def _execute_note_article(item: dict, values: dict) -> str | None:
    """note記事アイテムを product_packages に status='ready' で投入"""
    title = item.get("title") or "untitled"
    content = item["content"]
    if (item.get("metadata") or {}).get("dynamic_values"):
        content = _substitute(content, values)

    # auto_label を冒頭に追加
    auto_label = (
        "> この記事はSYUTAINβ（自律型AI事業OS）が自動生成・公開しました。\n"
        "> 島原大知が開発したシステムが、人間の介入なしに執筆しています。\n\n"
    )
    if not content.startswith(">"):
        content = auto_label + content

    async with get_connection() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM product_packages WHERE title = $1 AND platform = 'note'",
            title[:100],
        )
        if existing:
            logger.info(
                f"strategy_exec: 既存package Day{item['day_number']} "
                f"title={title[:40]} package_id={existing}"
            )
            return f"product_packages:{existing}"

        tags = json.dumps(
            ["SYUTAINβ", "BuildInPublic", "AI", "個人開発", "拡散実行書"],
            ensure_ascii=False,
        )
        pkg_id = await conn.fetchval(
            """INSERT INTO product_packages
               (platform, title, body_preview, body_full, price_jpy, status, tags, category)
               VALUES ('note', $1, $2, $3, 0, 'ready', $4, 'article')
               RETURNING id""",
            title[:100], content[:300], content, tags,
        )
        logger.info(
            f"strategy_exec: product_packages投入 Day{item['day_number']} "
            f"title={title[:40]} package_id={pkg_id}"
        )
        return f"product_packages:{pkg_id}"


async def _execute_weekly_report(item: dict, values: dict) -> str | None:
    """週報は note_article と同じフロー（テンプレート置換のみ別）"""
    return await _execute_note_article(item, values)


async def execute_today() -> dict[str, int]:
    """今日実行すべきアイテムを全て実行。戻り値は実行統計"""
    stats = {"executed": 0, "skipped": 0, "failed": 0, "total": 0}

    # 同期（冪等）
    try:
        await sync_strategy_plan()
    except Exception as e:
        logger.warning(f"strategy_exec: sync失敗（続行）: {e}")

    items = await get_today_items()
    stats["total"] = len(items)

    if not items:
        logger.info(f"strategy_exec: 今日({datetime.now(JST).date()})のアイテムなし")
        return stats

    values = await _resolve_dynamic_values()
    logger.info(
        f"strategy_exec: {len(items)}件実行開始 "
        f"(dynamic_values: llm_calls={values.get('llm_calls')}, "
        f"api_total=¥{values.get('api_total')})"
    )

    for item in items:
        try:
            meta = item.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            item["metadata"] = meta
            # reply_day 等は auto_executable=False で自動化不可
            if meta.get("auto_executable") is False:
                logger.info(
                    f"strategy_exec: Day{item['day_number']} {item['day_label']} は "
                    f"auto_executable=False のためスキップ"
                )
                await mark_item_executed(item["id"], "skipped:manual_only", status="skipped")
                stats["skipped"] += 1
                continue

            ref = None
            if item["item_type"] == "x_post":
                ref = await _execute_x_post(item, values)
            elif item["item_type"] == "note_article":
                ref = await _execute_note_article(item, values)
            elif item["item_type"] == "weekly_report":
                ref = await _execute_weekly_report(item, values)
            else:
                logger.warning(
                    f"strategy_exec: 未対応 item_type={item['item_type']} (Day{item['day_number']})"
                )
                stats["skipped"] += 1
                continue

            if ref:
                await mark_item_executed(item["id"], ref, status="executed")
                stats["executed"] += 1
            else:
                # 重複等でスキップ
                await mark_item_executed(item["id"], "skipped:dedupe", status="skipped")
                stats["skipped"] += 1

        except Exception as e:
            logger.error(
                f"strategy_exec: Day{item['day_number']} 実行失敗: {e}",
                exc_info=True,
            )
            stats["failed"] += 1

    logger.info(f"strategy_exec: 完了 {stats}")
    return stats
