"""Codex 日次コンテンツ品質管理 — 前日の全成果物を精査・問題特定・自律改善

毎日 04:00 JST に Codex (gpt-5.3-codex) が以下を全て実施:

1. 記事公開の確認: product_packages で ready のまま公開されてない記事はないか
   → あれば原因調査して修正
2. SNS 投稿文の品質精査: ハレーション・内容偏り・バリエーション不足の検出
   → プロンプト改善を自動適用
3. 記事の内容精査: 公開された記事に事実誤認・品質問題がないか
   → 改善提案を event_log に記録
4. 投稿頻度の確認: 各プラットフォームの posted/failed/rejected 比率
   → 異常があれば根本原因を特定して修正
5. エンゲージメント分析: 何が受けて何が受けなかったか
   → strategy/ のプロンプトを自動改善

スケジュール: 毎日 04:00 JST (日次)
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("syutain.codex_content_optimizer")

CODEX_PATH = "/opt/homebrew/bin/codex"
PROJECT_DIR = os.path.expanduser("~/syutain_beta")


async def _collect_daily_data(conn) -> dict:
    """前日24hの全コンテンツ関連データを収集"""
    data = {}

    # 記事の公開状況
    data["articles"] = [dict(r) for r in await conn.fetch(
        """SELECT id, status, LEFT(title, 80) as title, created_at::text
           FROM product_packages WHERE platform='note'
           AND created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC"""
    )]

    # ready のまま公開されてない記事
    data["stuck_articles"] = [dict(r) for r in await conn.fetch(
        """SELECT id, status, LEFT(title, 80) as title, created_at::text
           FROM product_packages WHERE platform='note' AND status='ready'
           AND created_at < NOW() - INTERVAL '2 hours'"""
    )]

    # SNS 投稿の全体状況
    data["sns_summary"] = [dict(r) for r in await conn.fetch(
        """SELECT platform, status, COUNT(*) as cnt
           FROM posting_queue
           WHERE created_at > NOW() - INTERVAL '24 hours'
           GROUP BY platform, status ORDER BY platform, status"""
    )]

    # 投稿内容の冒頭（バリエーション確認）
    data["posted_previews"] = [dict(r) for r in await conn.fetch(
        """SELECT platform, account, LEFT(content, 100) as preview, quality_score
           FROM posting_queue
           WHERE status='posted' AND posted_at > NOW() - INTERVAL '24 hours'
           ORDER BY posted_at DESC LIMIT 30"""
    )]

    # 失敗/拒否の詳細
    data["failures"] = [dict(r) for r in await conn.fetch(
        """SELECT platform, status, LEFT(content, 100) as preview,
                  created_at::text
           FROM posting_queue
           WHERE status IN ('failed', 'rejected', 'rejected_poem')
           AND created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT 15"""
    )]

    # エンゲージメントデータ
    data["engagement_top"] = [dict(r) for r in await conn.fetch(
        """SELECT platform, LEFT(content, 100) as preview,
                  engagement_data->>'like_count' as likes,
                  engagement_data->>'impression_count' as impressions
           FROM posting_queue
           WHERE status='posted' AND engagement_data IS NOT NULL
           AND posted_at > NOW() - INTERVAL '48 hours'
           ORDER BY COALESCE((engagement_data->>'impression_count')::int, 0) DESC
           LIMIT 10"""
    )]

    # content_pipeline の Stage 3 失敗
    data["pipeline_errors"] = []
    try:
        import re
        with open(os.path.join(PROJECT_DIR, "logs", "scheduler.log")) as f:
            for line in f:
                if "Stage 3 失敗" in line and datetime.now().strftime("%Y-%m-%d") in line:
                    data["pipeline_errors"].append(line.strip()[-200:])
    except Exception:
        pass

    return data


async def _run_codex_audit(prompt: str, timeout: int = 420) -> dict:
    """Codex を実行して結果を返す"""
    output_file = f"/tmp/codex_audit_{datetime.now().strftime('%H%M%S')}.txt"
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
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"success": False, "output": f"Timeout {timeout}s", "duration_ms": timeout * 1000}

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            os.remove(output_file)

        # 変更されたファイルを検出
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", stdout=asyncio.subprocess.PIPE, cwd=PROJECT_DIR,
        )
        diff_out, _ = await diff_proc.communicate()
        files_changed = [f.strip() for f in diff_out.decode().strip().split("\n") if f.strip()]

        # 変更行数チェック（200行超過なら全revert — 大規模リファクタ防止）
        try:
            import re as _re_stat2
            stat_proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--stat", stdout=asyncio.subprocess.PIPE, cwd=PROJECT_DIR,
            )
            stat_out, _ = await stat_proc.communicate()
            total_lines = sum(int(m.group(1)) for m in _re_stat2.finditer(r'(\d+) (?:insertion|deletion)', stat_out.decode()))
            if total_lines > 200:
                # 2026-04-11 CRITICAL FIX: 全 checkout 禁止(消失事故対策)。個別 revert のみ。
                logger.error(
                    f"Codex audit: 変更が{total_lines}行（上限200行）。"
                    f"files={len(files_changed)} 個別 revert(全 checkout 禁止)"
                )
                for _f in files_changed:
                    try:
                        _revert = await asyncio.create_subprocess_exec(
                            "git", "checkout", "HEAD", "--", _f, cwd=PROJECT_DIR,
                        )
                        await _revert.wait()
                    except Exception:
                        pass
                return {"success": False, "output": f"変更行数超過 ({total_lines}>200)、個別revert", "files_changed": []}
        except Exception:
            pass

        # strategy/ と brain_alpha/sns_batch.py と brain_alpha/content_pipeline.py のみ許可
        allowed_prefixes = ("strategy/", "brain_alpha/sns_batch.py", "brain_alpha/content_pipeline.py")
        allowed = []
        for f in files_changed:
            if any(f.startswith(p) or f == p for p in allowed_prefixes):
                # 構文チェック
                check = await asyncio.create_subprocess_exec(
                    "python3", "-m", "py_compile", f,
                    stderr=asyncio.subprocess.PIPE, cwd=PROJECT_DIR,
                )
                _, err = await check.communicate()
                if check.returncode == 0:
                    allowed.append(f)
                else:
                    logger.warning(f"Codex audit: {f} 構文エラー→revert")
                    await (await asyncio.create_subprocess_exec("git", "checkout", "--", f, cwd=PROJECT_DIR)).wait()
            else:
                logger.warning(f"Codex audit: {f} は許可外→revert")
                await (await asyncio.create_subprocess_exec("git", "checkout", "--", f, cwd=PROJECT_DIR)).wait()

        return {
            "success": True,
            "output": output[:3000],
            "duration_ms": duration_ms,
            "files_changed": allowed,
        }

    except Exception as e:
        return {"success": False, "output": str(e)[:500], "duration_ms": 0}


async def run_daily_content_audit() -> dict:
    """日次コンテンツ品質管理の全工程を実行"""
    from tools.db_pool import get_connection

    results = {"checks_performed": 0, "issues_found": 0, "fixes_applied": 0, "details": []}

    try:
        async with get_connection() as conn:
            data = await _collect_daily_data(conn)

        # データサマリを作成
        posted_count = sum(r["cnt"] for r in data["sns_summary"] if r["status"] == "posted")
        failed_count = sum(r["cnt"] for r in data["sns_summary"] if r["status"] in ("failed", "rejected", "rejected_poem"))
        article_count = len(data["articles"])
        stuck_count = len(data["stuck_articles"])
        pipeline_errors = len(data["pipeline_errors"])

        # 投稿内容の偏り検出（冒頭40字が似てるものをグルーピング）
        previews = [r.get("preview", "")[:40] for r in data["posted_previews"]]
        from collections import Counter
        common = Counter(previews).most_common(3)
        variety_issue = any(c >= 3 for _, c in common)

        issues = []
        if stuck_count > 0:
            issues.append(f"記事{stuck_count}本がready状態で公開されていない")
        if pipeline_errors > 0:
            issues.append(f"content_pipeline Stage3が{pipeline_errors}回失敗")
        if variety_issue:
            issues.append(f"投稿内容に偏り: 上位パターン {common}")
        if failed_count > posted_count * 0.3 and posted_count > 0:
            issues.append(f"失敗率{failed_count}/{posted_count+failed_count}が高い")

        results["checks_performed"] = 5  # articles, stuck, sns, variety, failures
        results["issues_found"] = len(issues)

        if not issues:
            logger.info("codex_daily_audit: 問題なし。プロンプト改善のみ実施")

        # Codex に包括的な分析 + 修正を依頼
        audit_prompt = (
            "SYUTAINβの日次コンテンツ品質管理を実施してください。\n\n"
            f"## 前日24hのデータ\n"
            f"- SNS投稿: posted {posted_count}件, failed/rejected {failed_count}件\n"
            f"- 記事: {article_count}件生成, stuck(未公開) {stuck_count}件\n"
            f"- content_pipeline失敗: {pipeline_errors}件\n"
            f"- 検出された問題: {issues if issues else 'なし'}\n\n"
            f"## SNS投稿プレビュー (バリエーション確認用)\n"
            f"{json.dumps(data['posted_previews'][:15], ensure_ascii=False, indent=1, default=str)[:2000]}\n\n"
            f"## 失敗/拒否された投稿\n"
            f"{json.dumps(data['failures'][:10], ensure_ascii=False, indent=1, default=str)[:1500]}\n\n"
            f"## エンゲージメント上位\n"
            f"{json.dumps(data['engagement_top'][:5], ensure_ascii=False, indent=1, default=str)[:1000]}\n\n"
            f"## 未公開記事\n"
            f"{json.dumps(data['stuck_articles'], ensure_ascii=False, indent=1, default=str)[:500]}\n\n"
            f"## pipeline エラー\n"
            f"{json.dumps(data['pipeline_errors'][:5], ensure_ascii=False, default=str)[:800]}\n\n"
            "## やること\n"
            "1. **投稿文のバリエーション**: 偏りがあれば `strategy/sns_theme_engine.py` の "
            "テーマプールを改善（受けたテーマを増やし、受けなかったものを減らす）\n"
            "2. **投稿品質**: ハレーションや事実と異なる内容があれば `strategy/sns_platform_voices.py` "
            "の forbidden / voice_rules を更新\n"
            "3. **記事公開**: stuck記事があれば原因を調査（`tools/note_publisher.py` や "
            "`brain_alpha/product_packager.py` に問題がないか）\n"
            "4. **pipeline失敗**: Stage3失敗の原因を分析して `brain_alpha/content_pipeline.py` "
            "のプロンプトやパラメータを改善\n"
            "5. **エンゲージメント反映**: 高エンゲージメント投稿のパターンを example_styles に反映\n\n"
            "修正可能ファイル: strategy/*.py, brain_alpha/sns_batch.py, brain_alpha/content_pipeline.py\n"
            "それ以外のファイルは変更禁止。構文チェック必須。\n"
        )

        audit_result = await _run_codex_audit(audit_prompt, timeout=420)
        results["fixes_applied"] = len(audit_result.get("files_changed", []))
        results["details"].append({
            "success": audit_result.get("success"),
            "files_changed": audit_result.get("files_changed", []),
            "duration_ms": audit_result.get("duration_ms", 0),
            "output_preview": audit_result.get("output", "")[:500],
        })

        # event_log に記録
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                       VALUES ('codex.daily_content_audit', 'codex', $1, 'alpha', $2::jsonb, NOW())""",
                    "warning" if issues else "info",
                    json.dumps({
                        "posted": posted_count, "failed": failed_count,
                        "articles": article_count, "stuck": stuck_count,
                        "pipeline_errors": pipeline_errors,
                        "issues": issues,
                        "fixes_applied": results["fixes_applied"],
                        "files_changed": audit_result.get("files_changed", []),
                    }, ensure_ascii=False),
                )
        except Exception:
            pass

        # Discord 通知
        try:
            from tools.discord_notify import notify_discord
            status_emoji = "🟢" if not issues else "🟡"
            lines = [
                f"{status_emoji} **Codex 日次コンテンツ品質管理**",
                f"SNS: {posted_count} posted / {failed_count} failed",
                f"記事: {article_count}件 / 未公開{stuck_count}件 / pipeline失敗{pipeline_errors}件",
            ]
            if issues:
                lines.append(f"検出: {'; '.join(issues)}")
            if audit_result.get("files_changed"):
                lines.append(f"改善: {', '.join(audit_result['files_changed'])}")
            await notify_discord("\n".join(lines))
        except Exception:
            pass

    except Exception as e:
        logger.error(f"run_daily_content_audit 全体失敗: {e}")

    return results


# 旧互換
async def run_content_optimization():
    return await run_daily_content_audit()
