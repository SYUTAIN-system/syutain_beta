"""Codex コンテンツ最適化 — エンゲージメントデータに基づくプロンプト自律改善

Codex (gpt-5.3-codex) がエンゲージメントデータと投稿内容を分析して、
SNS投稿と記事生成のプロンプトを自動的に改善するトライアンドエラーループ。

サイクル:
  1. 直近7日の投稿 + エンゲージメントデータを収集
  2. 「何が受けたか」「何が受けなかったか」のパターンを Codex に分析させる
  3. 分析結果に基づいて具体的なプロンプト改善案を生成
  4. 改善案を strategy/ 配下のファイルに反映 (安全な範囲で)
  5. 次回バッチで改善プロンプトが使われ、結果がまたデータになる

スケジュール: 水曜 04:00 JST (週次、SNS品質自動改善の直後)
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("syutain.codex_content_optimizer")

CODEX_PATH = "/opt/homebrew/bin/codex"
PROJECT_DIR = os.path.expanduser("~/syutain_beta")


async def analyze_engagement_patterns(conn) -> dict:
    """直近7日の投稿とエンゲージメントを集計してパターンを返す"""
    # 高エンゲージメント投稿 TOP 10
    top_posts = await conn.fetch(
        """SELECT platform, account, LEFT(content, 200) as content,
                  quality_score, theme_category,
                  engagement_data->>'like_count' as likes,
                  engagement_data->>'repost_count' as reposts,
                  engagement_data->>'impression_count' as impressions
           FROM posting_queue
           WHERE status = 'posted' AND engagement_data IS NOT NULL
           AND posted_at > NOW() - INTERVAL '7 days'
           ORDER BY COALESCE((engagement_data->>'impression_count')::int, 0) DESC
           LIMIT 10"""
    )

    # 低エンゲージメント投稿 (impressions はあるが likes 0)
    low_posts = await conn.fetch(
        """SELECT platform, account, LEFT(content, 200) as content,
                  quality_score, theme_category,
                  engagement_data->>'like_count' as likes,
                  engagement_data->>'impression_count' as impressions
           FROM posting_queue
           WHERE status = 'posted' AND engagement_data IS NOT NULL
           AND posted_at > NOW() - INTERVAL '7 days'
           AND COALESCE((engagement_data->>'like_count')::int, 0) = 0
           AND COALESCE((engagement_data->>'impression_count')::int, 0) > 0
           ORDER BY posted_at DESC LIMIT 10"""
    )

    # rejected 投稿のパターン
    rejected = await conn.fetch(
        """SELECT platform, LEFT(content, 200) as content, status
           FROM posting_queue
           WHERE status IN ('rejected_poem', 'rejected', 'failed')
           AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY created_at DESC LIMIT 10"""
    )

    # 記事品質データ
    articles = await conn.fetch(
        """SELECT LEFT(title, 100) as title, status,
                  LEFT(body_preview, 200) as preview
           FROM product_packages
           WHERE platform = 'note' AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY created_at DESC LIMIT 10"""
    )

    return {
        "top_posts": [dict(r) for r in top_posts],
        "low_posts": [dict(r) for r in low_posts],
        "rejected": [dict(r) for r in rejected],
        "articles": [dict(r) for r in articles],
    }


async def run_content_optimization() -> dict:
    """Codex にエンゲージメントデータを分析させ、プロンプト改善を自動適用する"""
    from tools.db_pool import get_connection

    results = {"analysis_done": False, "improvements_applied": 0, "details": []}

    try:
        async with get_connection() as conn:
            data = await analyze_engagement_patterns(conn)

        if not data["top_posts"] and not data["rejected"]:
            logger.info("codex_content_optimizer: エンゲージメントデータ不足。スキップ")
            return results

        # Codex に分析 + 改善案生成を依頼
        analysis_prompt = (
            "SYUTAINβの SNS 投稿と記事生成のパフォーマンスを分析して、"
            "具体的なプロンプト改善案を出してください。\n\n"
            f"## 高エンゲージメント投稿 TOP 10\n"
            f"{json.dumps(data['top_posts'], ensure_ascii=False, indent=2, default=str)[:3000]}\n\n"
            f"## 低エンゲージメント投稿 (impressions あり、likes 0)\n"
            f"{json.dumps(data['low_posts'], ensure_ascii=False, indent=2, default=str)[:2000]}\n\n"
            f"## 拒否された投稿\n"
            f"{json.dumps(data['rejected'], ensure_ascii=False, indent=2, default=str)[:1500]}\n\n"
            f"## 記事の品質状況\n"
            f"{json.dumps(data['articles'], ensure_ascii=False, indent=2, default=str)[:1500]}\n\n"
            "## 出力形式\n"
            "以下の 2 つのファイルに対する具体的な改善を実装してください:\n\n"
            "1. `strategy/sns_platform_voices.py` の `PLATFORM_VOICES` dict 内の "
            "`example_styles` と `voice_rules` を、高エンゲージメント投稿のパターンに"
            "合わせて更新。低エンゲージメントのパターンは避ける例として `forbidden` に追加。\n\n"
            "2. `strategy/sns_theme_engine.py` の静的フォールバックテーマ "
            "(`_CREATOR_FALLBACK`, `_PHILOSOPHY_FALLBACK`, `_SHIMAHARA_FALLBACK`) を"
            "エンゲージメントデータに基づいて更新。受けたテーマに近いものを追加、"
            "受けなかったテーマを入れ替え。\n\n"
            "ルール:\n"
            "- Python の dict/list 構造を壊さない\n"
            "- 既存の構造を維持して中身だけ変える\n"
            "- 変更後に python3 -m py_compile で構文チェック\n"
            "- CLAUDE.md の forbidden files は触らない\n"
        )

        output_file = f"/tmp/codex_content_opt_{datetime.now().strftime('%H%M%S')}.txt"
        start = datetime.now()

        proc = await asyncio.create_subprocess_exec(
            CODEX_PATH, "exec", analysis_prompt,
            "--output-last-message", output_file,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=420)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("codex_content_optimizer: Timeout (420s)")
            return results

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)

        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            os.remove(output_file)

        results["analysis_done"] = True

        # 変更されたファイルを検出
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only",
            stdout=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        diff_out, _ = await diff_proc.communicate()
        files_changed = [f.strip() for f in diff_out.decode().strip().split("\n") if f.strip()]

        # strategy/ 配下のみ許可、他は revert
        allowed_changes = []
        for f in files_changed:
            if f.startswith("strategy/"):
                allowed_changes.append(f)
            else:
                logger.warning(f"codex_content_optimizer: 許可外のファイル変更を revert: {f}")
                await (await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", f, cwd=PROJECT_DIR,
                )).wait()

        # 構文チェック
        for f in allowed_changes:
            check = await asyncio.create_subprocess_exec(
                "python3", "-m", "py_compile", f,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_DIR,
            )
            _, check_err = await check.communicate()
            if check.returncode != 0:
                logger.error(f"codex_content_optimizer: {f} 構文エラー。revert")
                await (await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", f, cwd=PROJECT_DIR,
                )).wait()
                allowed_changes.remove(f)

        results["improvements_applied"] = len(allowed_changes)
        results["details"] = [{
            "files_changed": allowed_changes,
            "duration_ms": duration_ms,
            "output_preview": output[:500],
        }]

        # 結果を event_log に記録
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """INSERT INTO event_log (event_type, category, severity, source_node, payload, created_at)
                       VALUES ('codex.content_optimization', 'codex', 'info', 'alpha', $1::jsonb, NOW())""",
                    json.dumps({
                        "analysis_done": True,
                        "improvements_applied": len(allowed_changes),
                        "files": allowed_changes,
                        "duration_ms": duration_ms,
                        "top_post_count": len(data["top_posts"]),
                        "low_post_count": len(data["low_posts"]),
                    }, ensure_ascii=False),
                )
        except Exception:
            pass

        # Discord 通知
        if allowed_changes:
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"🎯 Codex コンテンツ最適化完了\n"
                    f"分析: 高エンゲージ {len(data['top_posts'])}件 / 低エンゲージ {len(data['low_posts'])}件\n"
                    f"改善: {', '.join(allowed_changes)}\n"
                    f"所要: {duration_ms}ms"
                )
            except Exception:
                pass

        logger.info(
            f"codex_content_optimizer: done. improvements={len(allowed_changes)} "
            f"duration={duration_ms}ms"
        )

    except Exception as e:
        logger.error(f"codex_content_optimizer 全体失敗: {e}")

    return results
