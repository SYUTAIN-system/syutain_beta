"""Codex Auto Reflector — codex.md AUTO-CHANGELOG セクションを git log から毎日再生成

2026-04-11 の事故後、島原さん指示:
    「Codexへの反映、全て自動化を行なって、本日の様な改修前の状態に戻される
    ということが構造的に起こり得ない様には再々徹底して欲しい」

従来:
    - AUTO-STATS (scheduler.py:update_codex_stats) が数値系のみ 09:35 JST 自動更新
    - Recent Changes セクションは人間が都度手書き → codex.md が陳腐化

本ツール:
    - git log --since=7日前 を取得
    - LLM で機能カテゴリ単位の変更点に要約
    - codex.md の AUTO-CHANGELOG マーカ間に書き込み
    - 変更があれば git commit + push

スケジュール: 毎日 09:40 JST (scheduler.py:update_codex_stats の 5分後)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.codex_auto_reflector")

JST = timezone(timedelta(hours=9))

PROJECT_DIR = os.path.expanduser("~/syutain_beta")
CODEX_MD = os.path.join(PROJECT_DIR, "codex.md")

CHANGELOG_START = "<!-- AUTO-CHANGELOG-START -->"
CHANGELOG_END = "<!-- AUTO-CHANGELOG-END -->"

GIT_LOG_DAYS = 7
MAX_COMMITS = 60

_SUMMARY_SYSTEM = """あなたは SYUTAINβ の Codex リファレンス整備官。

タスク:
 渡された git log (直近1週間) を読み、Codex が使える簡潔な
 「Auto Changelog」セクションを Markdown で生成する。

出力ルール:
1. ### 見出しで機能カテゴリごとにグルーピング (例: "### SNS Pipeline", "### Monitoring")
2. 各エントリは 1 行 (80〜140字) の bullet で「ファイル名: 何をどう変えたか」
3. 同じ commit でも論点が複数あれば分ける
4. 意味のない merge commit、typo fix、AUTO-STATS更新、WIPコミットは除外
5. LLM呼び出し数や具体数値は書かない (AUTO-STATSで別管理)
6. 変更日時や commit hash は書かない (Codex からは不要)
7. 全体で 60 行を超えない
8. 出力は Markdown のみ。前置きや説明は禁止
"""


def _build_summary_user_prompt(commits_text: str) -> str:
    return (
        "# 入力: 直近1週間の git log (新しい順)\n\n"
        "```\n"
        f"{commits_text[:12000]}\n"
        "```\n\n"
        "# 出力: Markdown セクション (### 見出し + bullet list)"
    )


async def _get_recent_commits(days: int = GIT_LOG_DAYS, max_commits: int = MAX_COMMITS) -> str:
    """git log で直近 N 日の変更を取得"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log",
            f"--since={days} days ago",
            f"--max-count={max_commits}",
            "--pretty=format:## %h %ad%n%s%n%b%n---",
            "--date=short",
            "--name-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"git log 取得失敗: {err.decode()[:200]}")
            return ""
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"git log 実行失敗: {e}")
        return ""


async def _summarize_with_llm(commits_text: str) -> str | None:
    """LLM で commit ログを整形済み Markdown に要約"""
    if not commits_text.strip():
        return None

    try:
        from tools.llm_router import call_llm, choose_best_model_v6
    except ImportError:
        logger.warning("llm_router 未利用可 — auto_reflector スキップ")
        return None

    # 2026-04-11: task_type='summary' は Nemotron Nano に routing されるが reasoning
    # トークンを使い切って text が空返却される問題があるため、OpenRouter Qwen3.6-Plus
    # (無料) に routing される 'proposal' を使う。実測で 4,000 字の構造化要約が得られる。
    sel = choose_best_model_v6(
        task_type="proposal",
        quality="medium",
        needs_japanese=True,
    )
    try:
        result = await call_llm(
            prompt=_build_summary_user_prompt(commits_text),
            system_prompt=_SUMMARY_SYSTEM,
            model_selection=sel,
            temperature=0.3,
            use_cache=False,
        )
        text = (result.get("text") or result.get("content") or "").strip()
        text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n```\s*$", "", text, flags=re.MULTILINE)
        return text.strip() or None
    except Exception as e:
        logger.warning(f"LLM 要約失敗: {e}")
        return None


def _update_codex_md(new_section: str) -> bool:
    """codex.md の changelog マーカ間を new_section で書き換える。
    マーカが無ければ Recent Changes セクションの直前に挿入する。
    """
    if not os.path.exists(CODEX_MD):
        logger.warning("codex.md 存在しない — スキップ")
        return False

    with open(CODEX_MD, "r", encoding="utf-8") as f:
        content = f.read()

    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    block = (
        f"{CHANGELOG_START}\n"
        f"<!-- このセクションは tools/codex_auto_reflector.py によって毎日09:40 JSTに自動更新されます。手動編集禁止。 -->\n"
        f"\n"
        f"## Auto Changelog (last 7 days, updated {now_jst})\n"
        f"\n"
        f"{new_section}\n"
        f"\n"
        f"{CHANGELOG_END}"
    )

    pat = re.compile(
        re.escape(CHANGELOG_START) + r".*?" + re.escape(CHANGELOG_END),
        re.DOTALL,
    )

    if pat.search(content):
        new_content = pat.sub(block, content)
    else:
        anchor = "## Recent Changes"
        idx = content.find(anchor)
        if idx >= 0:
            new_content = content[:idx] + block + "\n\n" + content[idx:]
        else:
            new_content = content.rstrip() + "\n\n" + block + "\n"

    if new_content == content:
        logger.debug("codex.md AUTO-CHANGELOG: 変更なし")
        return False

    with open(CODEX_MD, "w", encoding="utf-8") as f:
        f.write(new_content)
    logger.info("codex.md AUTO-CHANGELOG 更新完了")
    return True


async def _git_commit_and_push() -> bool:
    """codex.md のみを add して commit + push する"""
    try:
        add_proc = await asyncio.create_subprocess_exec(
            "git", "add", "codex.md",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        await add_proc.wait()

        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--cached", "--name-only",
            stdout=asyncio.subprocess.PIPE, cwd=PROJECT_DIR,
        )
        diff_out, _ = await diff_proc.communicate()
        if not diff_out.strip():
            logger.debug("codex.md に staged 変更なし — commit スキップ")
            return False

        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m",
            f"chore(codex): auto-refresh codex.md changelog ({datetime.now(JST).strftime('%Y-%m-%d')})",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        cr_code = await commit_proc.wait()
        if cr_code != 0:
            _, cerr = await commit_proc.communicate()
            logger.warning(f"codex.md commit 失敗: {cerr.decode()[:200]}")
            return False

        push_proc = await asyncio.create_subprocess_exec(
            "git", "push", "origin", "main",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=PROJECT_DIR,
        )
        pr_code = await push_proc.wait()
        if pr_code == 0:
            logger.info("codex.md git push 完了 (auto_reflector)")
            return True
        _, perr = await push_proc.communicate()
        logger.warning(f"codex.md git push 失敗: {perr.decode()[:200]}")
        return False
    except Exception as e:
        logger.warning(f"_git_commit_and_push 失敗: {e}")
        return False


async def run_codex_auto_reflector() -> dict:
    """daily entrypoint. 毎日 09:40 JST に scheduler から呼ばれる。"""
    stats = {"commits_read": 0, "summary_written": False, "committed": False, "error": ""}
    try:
        commits = await _get_recent_commits(days=GIT_LOG_DAYS, max_commits=MAX_COMMITS)
        stats["commits_read"] = commits.count("\n## ")
        if not commits.strip():
            stats["error"] = "no_commits"
            return stats

        summary = await _summarize_with_llm(commits)
        if not summary:
            stats["error"] = "llm_summary_failed"
            return stats

        wrote = _update_codex_md(summary)
        stats["summary_written"] = wrote
        if wrote:
            committed = await _git_commit_and_push()
            stats["committed"] = committed

        return stats
    except Exception as e:
        logger.error(f"codex_auto_reflector 全体失敗: {e}", exc_info=True)
        stats["error"] = str(e)[:200]
        return stats
