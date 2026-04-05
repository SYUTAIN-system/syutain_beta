"""Brain-β チャット改善施策の実運用観測スクリプト

2026-04-05 の徹底改善（幻覚確認劇撲滅／working_fact ingest／定型接頭辞撲滅／
commission_article 新設）が実運用で想定通り動いているかを定期監査する。

スケジューラから 1 時間毎に呼ばれ、結果は event_log と Discord（異常時のみ）に出す。
朝 08:00 に人間向けサマリを出力する想定。

観測項目:
  A. 幻覚確認劇再発: Brain-β が「承認しました」「投稿しました」等を発言しつつ
     対応する DB 操作が同時刻に存在しない事案
  B. 定型接頭辞再発: syutain_beta 発言の冒頭 30 文字に
     「自分が取得したデータ」「取得したデータによると」「報告します」が含まれる率
  C. 生Python例外露出: syutain_beta 発言に
     "name 'X' is not defined" / "KeyError" / "AttributeError" 等が含まれる件数
  D. working_fact 注入実績: persona_memory.working_fact の直近 24h カウント
  E. commission パイプライン実績: article_commission_queue の status 分布
  F. !コマンド発動ログ: 承認一覧/状態/予算/記事/依頼 の発動回数
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.brain_beta_audit")

# 定型接頭辞の検出パターン
_PREAMBLE_PATTERNS = [
    r"自分が取得したデータ",
    r"取得したデータによると",
    r"取得データ(?:から|には|は)",
    r"^報告します",
    r"^自分は.{0,20}報告します",
]
_PREAMBLE_RE = re.compile("|".join(_PREAMBLE_PATTERNS))

# 生Python例外の検出パターン
_RAW_EXC_PATTERNS = [
    r"name '[^']+' is not defined",
    r"\bKeyError\b[:\s]",
    r"\bAttributeError\b",
    r"'NoneType' object has",
    r"Traceback \(most recent call",
    r"TypeError: .+ object",
]
_RAW_EXC_RE = re.compile("|".join(_RAW_EXC_PATTERNS))

# 幻覚確認劇の検出: Brain-β が「承認/却下しました」「投稿しました」「変更しました」等を言った時
_FABRICATION_CLAIM_RE = re.compile(
    r"(?:承認|却下|投稿|公開|削除|変更|設定|記録|保存)(?:しました|完了)"
)


async def audit() -> dict[str, Any]:
    result: dict[str, Any] = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": 24,
        "alerts": [],
    }
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with get_connection() as conn:
        # A. Brain-β 発言を全取得
        rows = await conn.fetch(
            """SELECT id, content, created_at FROM discord_chat_history
               WHERE author = 'syutain_beta' AND created_at > $1
               ORDER BY created_at DESC""",
            since,
        )

        total = len(rows)
        preamble_hits = 0
        raw_exc_hits = 0
        fabrication_suspects = []

        for r in rows:
            content = r["content"] or ""
            if _PREAMBLE_RE.search(content[:80]):
                preamble_hits += 1
            if _RAW_EXC_RE.search(content):
                raw_exc_hits += 1
            if _FABRICATION_CLAIM_RE.search(content):
                fabrication_suspects.append({
                    "id": r["id"],
                    "content": content[:200],
                    "at": r["created_at"].isoformat(),
                })

        result["B_stilted_preamble"] = {
            "total_syutain_messages": total,
            "preamble_hits": preamble_hits,
            "rate": round(preamble_hits / max(total, 1), 3),
        }
        result["C_raw_exception_leak"] = {
            "count": raw_exc_hits,
        }

        # A. 幻覚確認劇詳細: 疑わしい発言の前後 60 秒以内に対応する DB 操作があるか
        hallucination_cases = []
        for suspect in fabrication_suspects[:20]:  # 最大 20 件まで調査
            suspect_time = datetime.fromisoformat(suspect["at"])
            content = suspect["content"]
            # 承認/却下ケース: approval_queue に responded_at ±60s で該当あるか
            if "承認" in content or "却下" in content:
                m = re.search(r"(?:ID|#)\s*(\d+)", content)
                if m:
                    approval_id = int(m.group(1))
                    hit = await conn.fetchval(
                        """SELECT 1 FROM approval_queue
                           WHERE id = $1 AND responded_at IS NOT NULL
                           AND responded_at BETWEEN $2 AND $3 LIMIT 1""",
                        approval_id,
                        suspect_time - timedelta(seconds=60),
                        suspect_time + timedelta(seconds=60),
                    )
                    if not hit:
                        hallucination_cases.append({
                            **suspect,
                            "reason": f"approval_id={approval_id} に対応するDB更新なし",
                        })

        result["A_hallucinated_confirmations"] = {
            "suspect_messages": len(fabrication_suspects),
            "confirmed_hallucinations": len(hallucination_cases),
            "cases": hallucination_cases[:10],
        }

        # D. working_fact 注入実績
        wf_24h = await conn.fetchval(
            """SELECT COUNT(*) FROM persona_memory
               WHERE category = 'working_fact' AND created_at > $1""",
            since,
        )
        wf_active_tier8 = await conn.fetchval(
            """SELECT COUNT(*) FROM persona_memory
               WHERE category = 'working_fact' AND priority_tier >= 8"""
        )
        wf_total = await conn.fetchval(
            "SELECT COUNT(*) FROM persona_memory WHERE category = 'working_fact'"
        )
        result["D_working_fact_ingest"] = {
            "ingested_last_24h": wf_24h,
            "active_tier8": wf_active_tier8,
            "total": wf_total,
        }

        # E. commission パイプライン
        commission_rows = await conn.fetch(
            """SELECT status, COUNT(*) as n FROM article_commission_queue
               GROUP BY status"""
        )
        result["E_commission_queue"] = {
            r["status"]: r["n"] for r in commission_rows
        }

        # F. !コマンド発動回数（ユーザー側メッセージから）
        cmd_rows = await conn.fetch(
            """SELECT content FROM discord_chat_history
               WHERE author = 'daichi' AND content LIKE '!%'
               AND created_at > $1""",
            since,
        )
        cmd_counts: dict[str, int] = {}
        for r in cmd_rows:
            first = (r["content"] or "").strip().split()[0] if r["content"] else ""
            if first:
                cmd_counts[first] = cmd_counts.get(first, 0) + 1
        result["F_command_invocations"] = cmd_counts

    # 異常判定
    if result["A_hallucinated_confirmations"]["confirmed_hallucinations"] > 0:
        result["alerts"].append({
            "severity": "critical",
            "topic": "hallucinated_confirmation",
            "detail": f"{result['A_hallucinated_confirmations']['confirmed_hallucinations']}件の幻覚確認劇を検出",
        })
    if result["B_stilted_preamble"]["rate"] > 0.15:
        result["alerts"].append({
            "severity": "high",
            "topic": "stilted_preamble_regression",
            "detail": f"定型接頭辞再発率 {result['B_stilted_preamble']['rate']*100:.1f}% (>15%)",
        })
    if result["C_raw_exception_leak"]["count"] > 0:
        result["alerts"].append({
            "severity": "high",
            "topic": "raw_exception_leaked",
            "detail": f"生Python例外露出 {result['C_raw_exception_leak']['count']}件",
        })

    return result


async def persist_and_alert(result: dict[str, Any]) -> None:
    """結果を event_log に記録。アラートがあれば Discord 通知"""
    try:
        async with get_connection() as conn:
            # event_log スキーマ: event_type, category (NOT NULL), severity, source_node, payload, created_at
            await conn.execute(
                """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                   VALUES ('brain_beta_audit', 'audit', $1, 'alpha', $2::jsonb, NOW())""",
                "warning" if result["alerts"] else "info",
                json.dumps(result, ensure_ascii=False, default=str),
            )
    except Exception as e:
        logger.warning(f"event_log 保存失敗: {e}")

    if result["alerts"]:
        try:
            from tools.discord_notify import notify_discord
            msg_lines = ["🔍 **Brain-β 健全性監査アラート**"]
            for a in result["alerts"]:
                msg_lines.append(f"[{a['severity'].upper()}] {a['topic']}: {a['detail']}")
            msg_lines.append("")
            msg_lines.append(
                f"定型接頭辞率: {result['B_stilted_preamble']['rate']*100:.1f}%"
                f"（{result['B_stilted_preamble']['preamble_hits']}/{result['B_stilted_preamble']['total_syutain_messages']}）"
            )
            msg_lines.append(
                f"working_fact ingested(24h): {result['D_working_fact_ingest']['ingested_last_24h']}件"
            )
            msg_lines.append(f"commission queue: {result['E_commission_queue']}")
            await notify_discord("\n".join(msg_lines))
        except Exception as e:
            logger.warning(f"Brain-β 監査通知失敗: {e}")


async def run_audit() -> None:
    """scheduler から呼ばれるエントリポイント"""
    try:
        result = await audit()
        await persist_and_alert(result)
        logger.info(
            f"brain_beta_audit: alerts={len(result['alerts'])} "
            f"preamble={result['B_stilted_preamble']['rate']*100:.1f}% "
            f"raw_exc={result['C_raw_exception_leak']['count']} "
            f"wf24h={result['D_working_fact_ingest']['ingested_last_24h']} "
            f"commission={result['E_commission_queue']}"
        )
    except Exception as e:
        logger.error(f"brain_beta_audit 失敗: {e}")


if __name__ == "__main__":
    # 手動実行時は結果を stdout に吐く
    async def _main():
        r = await audit()
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    asyncio.run(_main())
