"""Codex 自動修正パイプライン — gstack review / self_healer / event_log のエラーを Codex に渡して自動修正

設計:
  1. gstack_code_review の結果から issues を抽出
  2. event_log の直近 error/critical を集約
  3. Codex に「この問題を修正して」と指示
  4. 修正結果を event_log に記録 + Discord 通知
  5. 安全装置: CLAUDE.md の forbidden files は修正対象外

スケジュール: gstack_code_review (09:00) 直後の 09:15 に実行
"""

import os
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("syutain.codex_auto_fix")

CODEX_PATH = "/opt/homebrew/bin/codex"
PROJECT_DIR = os.path.expanduser("~/syutain_beta")

# 修正禁止ファイル（CLAUDE.md Rule 準拠）
FORBIDDEN_FILES = {
    "agents/os_kernel.py", "tools/emergency_kill.py",
    "agents/approval_manager.py", "tools/loop_guard.py",
    ".env", "credentials.json", "token.json", "CLAUDE.md",
}

# 1回の自動修正で変更できる最大行数
MAX_LINES_CHANGED = 100


async def run_codex_fix(issue_description: str, files_hint: list[str] = None, timeout: int = 300) -> dict:
    """Codex に修正を指示して結果を返す。

    Args:
        issue_description: 問題の説明（gstack review output or error summary）
        files_hint: 修正対象のファイルパス候補（あれば Codex が早く見つけられる）
        timeout: 秒

    Returns:
        {"success": bool, "output": str, "duration_ms": int, "files_changed": list[str]}
    """
    # forbidden files チェック
    if files_hint:
        forbidden_found = [f for f in files_hint if f in FORBIDDEN_FILES]
        if forbidden_found:
            return {
                "success": False,
                "output": f"修正禁止ファイルが含まれています: {forbidden_found}",
                "duration_ms": 0,
                "files_changed": [],
            }

    prompt = (
        f"以下の問題を修正してください。\n\n"
        f"## 問題\n{issue_description[:2000]}\n\n"
        f"## ルール\n"
        f"- 修正は最小限に。問題の箇所だけ直す\n"
        f"- 以下のファイルは絶対に変更しない: {', '.join(FORBIDDEN_FILES)}\n"
        f"- テストを壊さない\n"
        f"- 修正後に python3 -m py_compile で構文チェック\n"
    )
    if files_hint:
        prompt += f"- 修正対象のヒント: {', '.join(files_hint[:5])}\n"

    output_file = f"/tmp/codex_fix_{datetime.now().strftime('%H%M%S')}.txt"
    start = datetime.now()

    try:
        proc = await asyncio.create_subprocess_exec(
            CODEX_PATH, "exec", prompt,
            "--output-last-message", output_file,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return {
                "success": False,
                "output": f"Timeout after {timeout}s",
                "duration_ms": duration,
                "files_changed": [],
            }

        duration = int((datetime.now() - start).total_seconds() * 1000)

        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            os.remove(output_file)

        # git diff で変更されたファイルを検出
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only",
            stdout=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        diff_out, _ = await diff_proc.communicate()
        files_changed = [f.strip() for f in diff_out.decode().strip().split("\n") if f.strip()]

        # forbidden files が変更されていたら revert
        for f in files_changed:
            if f in FORBIDDEN_FILES:
                logger.error(f"Codex が禁止ファイル {f} を変更した。revert する")
                revert_proc = await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", f,
                    cwd=PROJECT_DIR,
                )
                await revert_proc.wait()
                files_changed.remove(f)

        # 変更が多すぎたら全 revert
        if len(files_changed) > 10:
            logger.error(f"Codex が {len(files_changed)} ファイルを変更（上限10）。全 revert")
            await (await asyncio.create_subprocess_exec(
                "git", "checkout", "--", ".",
                cwd=PROJECT_DIR,
            )).wait()
            return {
                "success": False,
                "output": f"変更ファイル数が多すぎる ({len(files_changed)} > 10)。全 revert",
                "duration_ms": duration,
                "files_changed": [],
            }

        return {
            "success": proc.returncode == 0 and len(output) > 0,
            "output": output[:3000],
            "duration_ms": duration,
            "files_changed": files_changed,
        }

    except Exception as e:
        duration = int((datetime.now() - start).total_seconds() * 1000)
        logger.error(f"Codex 自動修正失敗: {e}")
        return {
            "success": False,
            "output": str(e)[:500],
            "duration_ms": duration,
            "files_changed": [],
        }


async def auto_fix_from_review() -> dict:
    """直近の gstack review 結果から issues を抽出して Codex に自動修正させる。
    scheduler から 09:15 JST に呼ばれる。"""
    from tools.db_pool import get_connection

    results = {"attempted": 0, "fixed": 0, "failed": 0, "skipped": 0, "details": []}

    try:
        async with get_connection() as conn:
            # 直近の gstack review 結果を取得
            row = await conn.fetchrow(
                """SELECT payload FROM event_log
                   WHERE event_type = 'gstack.review' AND severity = 'info'
                   AND created_at > NOW() - INTERVAL '6 hours'
                   ORDER BY created_at DESC LIMIT 1"""
            )
            if not row:
                logger.info("codex_auto_fix: 直近の gstack review 結果なし。スキップ")
                return results

            payload = {}
            try:
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else (row["payload"] or {})
            except Exception:
                pass

            if not payload.get("success"):
                logger.info("codex_auto_fix: gstack review が失敗。スキップ")
                return results

            output = payload.get("output_preview", "")
            if "0 issues" in output.lower() or "no issues" in output.lower():
                logger.info("codex_auto_fix: gstack review issues 0件。スキップ")
                return results

            # issues を抽出して修正を試みる
            logger.info(f"codex_auto_fix: gstack review に issues あり。Codex で自動修正を試行")
            results["attempted"] = 1

            fix_result = await run_codex_fix(
                issue_description=f"gstack コードレビューで以下の問題が検出されました:\n\n{output[:2000]}",
                timeout=300,
            )

            detail = {
                "source": "gstack_review",
                "success": fix_result["success"],
                "duration_ms": fix_result["duration_ms"],
                "files_changed": fix_result["files_changed"],
                "output_preview": fix_result["output"][:300],
            }
            results["details"].append(detail)

            if fix_result["success"] and fix_result["files_changed"]:
                results["fixed"] = 1
                # 修正を event_log に記録
                await conn.execute(
                    """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                       VALUES ('codex.auto_fix', 'codex', 'info', 'alpha', $1::jsonb, NOW())""",
                    json.dumps(detail, ensure_ascii=False),
                )
                # Discord 通知
                try:
                    from tools.discord_notify import notify_discord
                    await notify_discord(
                        f"🔧 Codex 自動修正完了\n"
                        f"ソース: gstack review\n"
                        f"修正ファイル: {', '.join(fix_result['files_changed'])}\n"
                        f"所要: {fix_result['duration_ms']}ms"
                    )
                except Exception:
                    pass
            else:
                results["failed"] = 1

    except Exception as e:
        logger.error(f"codex_auto_fix 全体失敗: {e}")

    return results


async def auto_fix_from_errors() -> dict:
    """直近の event_log error/critical を Codex に渡して自動修正を試みる。
    self_healer と連携して、繰り返し発生するエラーを自動的に直す。"""
    from tools.db_pool import get_connection

    results = {"attempted": 0, "fixed": 0, "details": []}

    try:
        async with get_connection() as conn:
            # 直近24hで3回以上発生した同一エラーを検出（繰り返しパターンのみ対象）
            rows = await conn.fetch(
                """SELECT event_type, COUNT(*) as cnt,
                          LEFT(MIN(payload::text), 300) as sample_payload
                   FROM event_log
                   WHERE severity IN ('error', 'critical')
                   AND created_at > NOW() - INTERVAL '24 hours'
                   AND event_type NOT IN ('sns.post_failed', 'sns.fixation_deadlock')
                   GROUP BY event_type
                   HAVING COUNT(*) >= 3
                   ORDER BY COUNT(*) DESC LIMIT 3"""
            )

            for r in rows:
                event_type = r["event_type"]
                count = r["cnt"]
                sample = r["sample_payload"] or ""

                logger.info(f"codex_auto_fix: 繰り返しエラー検出 {event_type} ({count}回)")
                results["attempted"] += 1

                fix_result = await run_codex_fix(
                    issue_description=(
                        f"以下のエラーが直近24時間で {count} 回繰り返し発生しています。\n\n"
                        f"event_type: {event_type}\n"
                        f"payload sample: {sample}\n\n"
                        f"根本原因を特定して修正してください。"
                    ),
                    timeout=300,
                )

                detail = {
                    "source": f"error_repeat:{event_type}",
                    "error_count": count,
                    "success": fix_result["success"],
                    "files_changed": fix_result["files_changed"],
                }
                results["details"].append(detail)

                if fix_result["success"] and fix_result["files_changed"]:
                    results["fixed"] += 1
                    async with get_connection() as conn2:
                        await conn2.execute(
                            """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                               VALUES ('codex.auto_fix', 'codex', 'info', 'alpha', $1::jsonb, NOW())""",
                            json.dumps(detail, ensure_ascii=False),
                        )

    except Exception as e:
        logger.error(f"codex_auto_fix_from_errors 全体失敗: {e}")

    return results
