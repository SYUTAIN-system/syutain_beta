"""
SYUTAINβ V27 ドキュメントガーデニング（Document Gardening）
Harness Engineering: ドキュメントとコードの乖離を週次で検出する。

CLAUDE.md, strategy/ のルール・設定と実コードを突合し、
不整合を approval_queue に登録してレビューを促す。
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm

logger = logging.getLogger("syutain.doc_gardener")

# プロジェクトルート
BASE_DIR = Path(__file__).resolve().parent.parent


def _safe_read(path: Path, max_chars: int = 8000) -> Optional[str]:
    """ファイルを安全に読み込む（存在しない場合はNone）"""
    try:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8")
            return text[:max_chars]
    except Exception as e:
        logger.warning(f"ファイル読み込み失敗 ({path}): {e}")
    return None


def _collect_documentation() -> dict[str, str]:
    """監査対象ドキュメントを収集する"""
    docs = {}

    # CLAUDE.md
    claude_md = _safe_read(BASE_DIR / "CLAUDE.md")
    if claude_md:
        docs["CLAUDE.md"] = claude_md

    # AGENTS.md（存在する場合）
    agents_md = _safe_read(BASE_DIR / "AGENTS.md")
    if agents_md:
        docs["AGENTS.md"] = agents_md

    # strategy/ 配下
    strategy_dir = BASE_DIR / "strategy"
    if strategy_dir.exists():
        for f in sorted(strategy_dir.glob("*.md")):
            content = _safe_read(f, max_chars=4000)
            if content:
                docs[f"strategy/{f.name}"] = content

    return docs


def _collect_code_snapshots() -> dict[str, str]:
    """監査対象コードの主要部分を収集する"""
    snippets = {}

    key_files = [
        "agents/os_kernel.py",
        "agents/executor.py",
        "agents/planner.py",
        "agents/verifier.py",
        "agents/stop_decider.py",
        "agents/approval_manager.py",
        "agents/capability_audit.py",
        "tools/llm_router.py",
        "tools/loop_guard.py",
        "tools/budget_guard.py",
        "scheduler.py",
    ]

    for rel_path in key_files:
        full_path = BASE_DIR / rel_path
        content = _safe_read(full_path, max_chars=4000)
        if content:
            snippets[rel_path] = content

    return snippets


async def audit_documentation() -> list[dict]:
    """
    ドキュメントとコードの実態を比較し、不整合を検出する。

    Returns:
        list of inconsistencies found, each with:
          - file: ドキュメントファイル名
          - issue: 不整合の説明
          - severity: low / medium / high
          - suggestion: 修正提案
    """
    logger.info("ドキュメントガーデニング開始")

    docs = _collect_documentation()
    code_snippets = _collect_code_snapshots()

    if not docs:
        logger.warning("監査対象ドキュメントが見つかりません")
        return []

    if not code_snippets:
        logger.warning("監査対象コードが見つかりません")
        return []

    # LLMで不整合を検出（CLAUDE.md ルール5: choose_best_model_v6使用）
    model_sel = choose_best_model_v6(
        task_type="analysis",
        quality="medium",
        budget_sensitive=True,
        local_available=True,
    )

    # ドキュメント要約
    doc_summary = "\n\n".join(
        f"=== {name} ===\n{content[:2000]}" for name, content in docs.items()
    )
    # コード要約
    code_summary = "\n\n".join(
        f"=== {name} ===\n{content[:2000]}" for name, content in code_snippets.items()
    )

    # トークン削減のため全体を制限
    doc_summary = doc_summary[:6000]
    code_summary = code_summary[:6000]

    # 実在するファイルリストを明示（ハルシネーション防止）
    existing_files = sorted(set(list(docs.keys()) + list(code_snippets.keys())))
    existing_files_str = "\n".join(f"- {f}" for f in existing_files)

    audit_prompt = f"""以下のドキュメント（設計書・ルール）と実装コードを比較し、不整合を検出してください。

## 実在するファイル一覧（これ以外のファイル名を使わないこと）
{existing_files_str}

## ドキュメント
{doc_summary}

## 実装コード（抜粋）
{code_summary}

## 検出観点
1. CLAUDE.mdに記載されたルールがコードで守られているか
2. strategy/ に記載された戦略・設定値がコードに反映されているか
3. ドキュメントに記載されているが未実装の機能
4. コードに存在するがドキュメントに記載のない機能
5. 古い情報（モデル名、ノード名、パラメータ等）

## 絶対ルール
- "file"フィールドには上記「実在するファイル一覧」に含まれるファイル名のみ使用すること
- 存在しないファイル名、存在しない変数名、存在しない関数名を捏造しないこと
- 上記のドキュメントとコードに明確に書かれている内容だけを根拠にすること
- 推測や想像に基づく指摘は禁止

## 出力形式（JSON配列）
[
  {{
    "file": "上記一覧のファイル名のみ",
    "issue": "不整合の具体的な説明（該当行や変数名を引用）",
    "severity": "low|medium|high",
    "suggestion": "修正提案"
  }}
]

不整合がない場合は空配列[]を返してください。確信が持てない指摘は含めないでください。"""

    inconsistencies = []

    try:
        llm_result = await call_llm(
            prompt=audit_prompt,
            system_prompt=(
                "あなたはSYUTAINβのドキュメント監査エージェントです。"
                "ドキュメントとコードの乖離を正確に検出し、JSON配列で報告してください。"
            ),
            model_selection=model_sel,
        )

        text = llm_result.get("text", "")
        if text:
            import re
            json_match = re.search(r"\[[\s\S]*\]", text)
            if json_match:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, list):
                    # ハルシネーション検証: 実在しないファイルを参照していたら除外
                    all_known_files = set(docs.keys()) | set(code_snippets.keys())
                    verified = []
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        ref_file = item.get("file", "")
                        # ファイル名が実在するか確認
                        if ref_file and ref_file not in all_known_files:
                            logger.warning(f"ハルシネーション除外: 存在しないファイル '{ref_file}' を参照")
                            continue
                        # issueが空でないか確認
                        if not item.get("issue"):
                            continue
                        # severity が有効値か確認
                        if item.get("severity") not in ("low", "medium", "high"):
                            item["severity"] = "low"
                        verified.append(item)

                    # 追加検証: issue内の関数名/変数名がコード内に実在するか確認
                    import re as _re
                    final_verified = []
                    for item in verified:
                        issue_text = item.get("issue", "")
                        ref_file = item.get("file", "")
                        # issue内の関数名・変数名っぽいトークンを抽出（snake_case or camelCase）
                        referenced_names = _re.findall(
                            r'\b([a-z_][a-z0-9_]{2,}(?:\(\))?)\b', issue_text
                        )
                        # コードファイルを参照している場合のみ検証
                        if referenced_names and ref_file in code_snippets:
                            code_content = code_snippets[ref_file]
                            hallucinated = False
                            for name in referenced_names:
                                clean_name = name.rstrip("()")
                                # 一般的な英単語は除外（関数名/変数名のみチェック）
                                if clean_name in (
                                    "the", "and", "for", "not", "this", "that", "with",
                                    "from", "import", "class", "def", "return", "true",
                                    "false", "none", "status", "error", "success", "failure",
                                    "type", "data", "value", "result", "message", "info",
                                    "warning", "low", "medium", "high",
                                ):
                                    continue
                                if len(clean_name) >= 5 and clean_name not in code_content:
                                    logger.warning(
                                        f"ハルシネーション除外: '{clean_name}' がコード {ref_file} に存在しない"
                                    )
                                    hallucinated = True
                                    break
                            if hallucinated:
                                continue
                        final_verified.append(item)

                    rejected_count = len(parsed) - len(final_verified)
                    if rejected_count > 0:
                        logger.info(f"ハルシネーション検証: {rejected_count}件除外, {len(final_verified)}件採用")
                    inconsistencies = final_verified

        logger.info(f"ドキュメントガーデニング: {len(inconsistencies)}件の不整合を検出（検証済み）")

    except Exception as e:
        logger.error(f"ドキュメント監査LLM呼び出し失敗: {e}")

    return inconsistencies


async def run_and_queue() -> dict:
    """
    監査を実行し、検出された不整合をapproval_queueに登録する。

    Returns:
        {"total": int, "queued": int}
    """
    inconsistencies = await audit_documentation()

    if not inconsistencies:
        logger.info("ドキュメントガーデニング: 不整合なし")
        return {"total": 0, "queued": 0}

    queued = 0
    try:
        async with get_connection() as conn:
            for item in inconsistencies:
                try:
                    # 承認画面で読みやすい要約を生成
                    readable_desc = (
                        f"【{item.get('severity', '?').upper()}】{item.get('file', '?')}\n"
                        f"問題: {item.get('issue', '不明')}\n"
                        f"提案: {item.get('suggestion', 'なし')}"
                    )
                    item["readable_description"] = readable_desc

                    await conn.execute(
                        """
                        INSERT INTO approval_queue (request_type, request_data)
                        VALUES ($1, $2)
                        """,
                        "doc_gardening",
                        json.dumps(item, ensure_ascii=False, default=str),
                    )
                    queued += 1
                except Exception as e:
                    logger.warning(f"approval_queue登録失敗: {e}")
    except Exception as e:
        logger.error(f"DB接続失敗: {e}")

    logger.info(f"ドキュメントガーデニング完了: {len(inconsistencies)}件検出, {queued}件キュー登録")

    # Discord通知（CLAUDE.md ルール12）
    try:
        from tools.discord_notify import notify_discord
        severity_counts = {}
        for item in inconsistencies:
            sev = item.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        sev_str = ", ".join(f"{k}={v}" for k, v in severity_counts.items())
        await notify_discord(
            f"📋 ドキュメントガーデニング完了: {len(inconsistencies)}件の不整合検出 ({sev_str})\n"
            f"approval_queueで確認してください。"
        )
    except Exception:
        pass

    # イベント記録
    try:
        from tools.event_logger import log_event
        await log_event(
            "doc_gardening.completed", "harness",
            {"total": len(inconsistencies), "queued": queued,
             "severities": {item.get("severity", "unknown"): 1 for item in inconsistencies}},
        )
    except Exception:
        pass

    return {"total": len(inconsistencies), "queued": queued}
