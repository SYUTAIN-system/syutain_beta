"""
SYUTAINβ V25 Harness Linter
CLAUDE.md 22条の機械的強制

エージェントの出力・タスク実行結果を検証し、
ルール違反を構造的に不可能にする。

HarnessLinter: approval_managerの前段で実行する非同期制約強制レイヤー。
- taboo違反チェック（設計書ルール26）
- ペルソナ整合性チェック（設計書ルール23）
- 予算プリフライトチェック
- コンテンツ安全性チェック
"""

import os
import re
import json
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

from tools.db_pool import get_connection

load_dotenv()

logger = logging.getLogger("syutain.harness_linter")

# 検出パターン: APIキー・シークレット
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),          # OpenAI
    re.compile(r"sk-ant-[a-zA-Z0-9-]{20,}"),      # Anthropic
    re.compile(r"tvly-[a-zA-Z0-9]{20,}"),          # Tavily
    re.compile(r"AIza[a-zA-Z0-9_-]{35}"),          # Google
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),            # GitHub
    re.compile(r"gho_[a-zA-Z0-9]{36}"),            # GitHub OAuth
    re.compile(r"xoxb-[0-9-]+"),                   # Slack Bot
    re.compile(r"discord\.com/api/webhooks/\d+/[a-zA-Z0-9_-]+"),  # Discord Webhook
    re.compile(r"postgresql://[^@\s]+@[^/\s]+"),   # DB URL with credentials
]

# ===== ハーネスリンター重大度 =====
SEVERITY_BLOCK = "BLOCK"      # 即時拒否、承認キューにも入れない
SEVERITY_WARN = "WARN"        # 警告のみ、承認フローは継続

# コンテンツ安全パターン（非同期リンター用）
UNSAFE_CONTENT_PATTERNS = [
    (r"(?:死ね|殺す|自殺)", "暴力的表現"),
    (r"(?:個人情報|住所|電話番号)\s*[:：]\s*\S+", "個人情報の露出"),
]

# ペルソナ整合性 類似度閾値
PERSONA_SIMILARITY_THRESHOLD = 0.6

# 承認が必要なアクションタイプ（CLAUDE.md ルール11）
APPROVAL_REQUIRED_ACTIONS = {
    "sns_posting", "product_publish", "price_setting",
    "crypto_trade", "crypto_buy", "crypto_sell",
    "booth_publish", "stripe_charge",
}


class LintResult:
    """リンター結果"""

    def __init__(self):
        self.passed = True
        self.violations: list[dict] = []
        self.warnings: list[dict] = []

    def add_violation(self, rule: int, message: str, details: str = ""):
        self.passed = False
        self.violations.append({"rule": rule, "message": message, "details": details})

    def add_warning(self, rule: int, message: str, details: str = ""):
        self.warnings.append({"rule": rule, "message": message, "details": details})

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violation_count": len(self.violations),
            "warning_count": len(self.warnings),
            "violations": self.violations,
            "warnings": self.warnings,
        }


def lint_task_execution(
    task_type: str,
    model_used: Optional[str] = None,
    model_selection_method: Optional[str] = None,
    has_error_handling: bool = True,
    output_text: Optional[str] = None,
    log_text: Optional[str] = None,
    approval_id: Optional[str] = None,
    config_source: Optional[str] = None,
    strategy_referenced: bool = True,
) -> LintResult:
    """
    タスク実行結果をCLAUDE.md 22条に基づきリント。

    Returns: LintResult
    """
    result = LintResult()

    # ルール5: LLM呼び出し前にchoose_best_model_v6()でモデルを選択
    if model_used and model_selection_method != "v6":
        result.add_violation(
            5,
            "choose_best_model_v6()未使用",
            f"model={model_used}, selection={model_selection_method}",
        )

    # ルール7: try-exceptで囲みlog_usage()でエラーを記録
    if not has_error_handling:
        result.add_violation(7, "try-except未適用のツール呼び出し")

    # ルール8: .envの内容をログに出力しない / APIキーをコードにハードコードしない
    for text_label, text in [("output", output_text), ("log", log_text)]:
        if text:
            for pattern in _SECRET_PATTERNS:
                match = pattern.search(text)
                if match:
                    # マスク処理
                    masked = match.group()[:8] + "..."
                    result.add_violation(
                        8,
                        f"APIキー/シークレットが{text_label}に含まれている",
                        f"検出パターン: {masked}",
                    )

    # ルール9: 設定値はハードコードせずDBまたは.envから読み込む
    if config_source and config_source not in ("db", "env", "yaml", "feature_flags"):
        result.add_warning(9, f"設定値のソースが不適切: {config_source}")

    # ルール10: 戦略ファイル参照（コンテンツ生成タスクの場合）
    content_tasks = {"drafting", "sns_draft", "content_generation", "note_article",
                     "booth_description", "proposal_generation"}
    if task_type in content_tasks and not strategy_referenced:
        result.add_violation(10, "strategy/ファイル未参照でコンテンツ生成")

    # ルール11: SNS投稿・商品公開・価格設定・暗号通貨取引はApprovalManager経由
    if task_type in APPROVAL_REQUIRED_ACTIONS and not approval_id:
        result.add_violation(
            11,
            f"承認必須アクション'{task_type}'にApprovalManager承認なし",
        )

    # ルール13: ローカルLLM配置の厳守
    local_models = {"qwen3.5-9b", "qwen3.5:9b", "qwen3.5-9b-mlx", "nemotron-jp",
                    "qwen3.5-4b", "qwen3.5:4b"}
    if model_used and model_used in local_models:
        pass  # ローカルモデル使用OK
    elif model_used:
        # APIモデル使用時は警告（ルール違反ではない）
        result.add_warning(
            13,
            f"APIモデル使用: {model_used}（ローカルモデルが利用可能か確認推奨）",
        )

    return result


def lint_output_content(content: str, platform: Optional[str] = None) -> LintResult:
    """
    出力コンテンツのリント（SNS投稿、記事等）

    Returns: LintResult
    """
    result = LintResult()

    # APIキーチェック
    for pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            result.add_violation(8, "コンテンツにAPIキー/シークレットが含まれている")

    # .env変数の漏洩チェック
    env_vars = ["DATABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "TAVILY_API_KEY", "DISCORD_WEBHOOK_URL"]
    for var in env_vars:
        val = os.getenv(var, "")
        if val and len(val) > 10 and val in content:
            result.add_violation(8, f"環境変数{var}の値がコンテンツに含まれている")

    # プラットフォーム固有チェック
    if platform == "x" and len(content) > 280:
        result.add_warning(0, f"X投稿が280文字超過: {len(content)}文字")
    elif platform == "bluesky" and len(content) > 300:
        result.add_warning(0, f"Bluesky投稿が300文字超過: {len(content)}文字")

    return result


def sanitize_output(text: str) -> str:
    """出力テキストからシークレットをマスク"""
    sanitized = text
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


# ======================================================================
# HarnessLinter — 非同期制約強制レイヤー（approval_manager前段）
# ======================================================================

@dataclass
class HarnessLintResult:
    """非同期ハーネスリンターの結果"""
    passed: bool = True
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def add_violation(self, severity: str, rule: str, detail: str):
        entry = {"severity": severity, "rule": rule, "detail": detail}
        if severity == SEVERITY_BLOCK:
            self.passed = False
            self.violations.append(entry)
        else:
            self.warnings.append(entry)

    def merge(self, other: "HarnessLintResult"):
        if not other.passed:
            self.passed = False
        self.violations.extend(other.violations)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violation_count": len(self.violations),
            "warning_count": len(self.warnings),
            "violations": self.violations,
            "warnings": self.warnings,
        }


class HarnessLinter:
    """
    機械的制約強制レイヤー。
    approval_managerの前段で実行し、違反を早期キャッチする。
    ドキュメントに頼らず、コードで制約を強制する。
    """

    def __init__(self):
        self._taboo_cache: list = []
        self._taboo_loaded: bool = False

    async def lint_action(
        self,
        action_type: str,
        content: str,
        context: Optional[dict] = None,
    ) -> HarnessLintResult:
        """
        メインエントリポイント。全チェックを並行実行し結果をマージ。

        Args:
            action_type: アクション種別 (sns_posting, product_publish, etc.)
            content: チェック対象のテキスト内容
            context: 追加コンテキスト (estimated_cost_jpy, platform, check_persona, etc.)

        Returns:
            HarnessLintResult — passed=Falseの場合、承認キューに入れずBLOCK
        """
        context = context or {}
        results = await asyncio.gather(
            self._check_taboo(content),
            self._check_persona_alignment(content, context),
            self._check_budget_precheck(action_type, context),
            self._check_content_safety(content),
            return_exceptions=True,
        )

        merged = HarnessLintResult()
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"リントチェックエラー: {r}")
                continue
            merged.merge(r)

        # イベントログ記録（違反・警告がある場合のみ）
        if not merged.passed or merged.warnings:
            try:
                from tools.event_logger import log_event
                await log_event(
                    "harness_lint.result",
                    "safety",
                    {
                        "action_type": action_type,
                        "passed": merged.passed,
                        "violations": len(merged.violations),
                        "warnings": len(merged.warnings),
                        "content_preview": content[:100],
                    },
                    severity="warning" if merged.passed else "critical",
                )
            except Exception:
                pass

        if not merged.passed:
            logger.warning(
                f"HarnessLinter BLOCK: action={action_type}, "
                f"violations={len(merged.violations)}, "
                f"detail={merged.violations[0]['detail'][:80] if merged.violations else 'N/A'}"
            )
        elif merged.warnings:
            logger.info(
                f"HarnessLinter WARN: action={action_type}, warnings={len(merged.warnings)}"
            )

        return merged

    # ========== 個別チェック ==========

    async def _check_taboo(self, content: str) -> HarnessLintResult:
        """
        persona_memory category='taboo' のエントリと照合。
        taboo違反は即座にBLOCK（設計書ルール26）。
        """
        result = HarnessLintResult()
        try:
            taboos = await self._load_taboos()
            content_lower = content.lower()
            for taboo in taboos:
                taboo_text = (taboo.get("content") or "").lower()
                if not taboo_text:
                    continue
                # tabooテキストのキーワード分割で照合
                # 2文字以上のキーワードが全て含まれていればtaboo違反
                keywords = [w.strip() for w in taboo_text.split() if len(w.strip()) >= 2]
                if not keywords:
                    continue
                if all(kw in content_lower for kw in keywords):
                    result.add_violation(
                        SEVERITY_BLOCK,
                        "taboo_violation",
                        f"タブー違反: {taboo_text[:80]}",
                    )
        except Exception as e:
            logger.error(f"tabooチェックエラー: {e}")
        return result

    async def _check_persona_alignment(
        self, content: str, context: dict
    ) -> HarnessLintResult:
        """
        コンテンツがペルソナの価値観と整合するかベクトル類似度で検証。
        context['check_persona']=True のときのみ実行（SNS投稿・公開コンテンツ向け）。
        """
        result = HarnessLintResult()
        if not context.get("check_persona", False):
            return result

        try:
            from tools.embedding_tools import search_similar_persona
            matches = await search_similar_persona(content[:500], limit=3)
            if not matches:
                result.add_violation(
                    SEVERITY_WARN,
                    "persona_no_data",
                    "ペルソナベクトルデータなし — 整合性チェック不可",
                )
                return result

            max_sim = max(m.get("similarity", 0) for m in matches)
            if max_sim < PERSONA_SIMILARITY_THRESHOLD:
                result.add_violation(
                    SEVERITY_WARN,
                    "persona_misalignment",
                    f"ペルソナ整合性低 (最大類似度={max_sim:.3f}, 閾値={PERSONA_SIMILARITY_THRESHOLD})",
                )
        except Exception as e:
            logger.error(f"ペルソナ整合性チェックエラー: {e}")
        return result

    async def _check_budget_precheck(
        self, action_type: str, context: dict
    ) -> HarnessLintResult:
        """
        高コストアクション前の予算プリフライトチェック。
        estimated_cost_jpy がcontextにあれば予算ガードに照会。
        """
        result = HarnessLintResult()
        estimated_cost = context.get("estimated_cost_jpy")
        if estimated_cost is None:
            return result

        try:
            from tools.budget_guard import get_budget_guard
            guard = get_budget_guard()
            budget_check = await guard.check_before_call(estimated_cost)
            if not budget_check.get("allowed", True):
                result.add_violation(
                    SEVERITY_BLOCK,
                    "budget_exceeded",
                    budget_check.get("reason", "予算超過"),
                )
            elif budget_check.get("suggest_tier_downgrade"):
                result.add_violation(
                    SEVERITY_WARN,
                    "budget_warning",
                    budget_check.get("reason", "予算警告圏内"),
                )
        except Exception as e:
            logger.error(f"予算プリチェックエラー: {e}")
        return result

    async def _check_content_safety(self, content: str) -> HarnessLintResult:
        """
        生成コンテンツの安全パターンチェック。
        APIキー露出・暴力的表現・個人情報などを検出。
        既存の _SECRET_PATTERNS と UNSAFE_CONTENT_PATTERNS の両方を使用。
        """
        result = HarnessLintResult()
        # APIキー・シークレットの露出チェック
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                result.add_violation(
                    SEVERITY_BLOCK,
                    "content_safety",
                    "安全性違反: 秘密情報の露出",
                )
                break  # 1件見つかれば十分

        # 追加の安全パターン
        for pat_str, description in UNSAFE_CONTENT_PATTERNS:
            try:
                if re.search(pat_str, content, re.IGNORECASE):
                    result.add_violation(
                        SEVERITY_BLOCK,
                        "content_safety",
                        f"安全性違反: {description}",
                    )
            except re.error:
                pass
        return result

    # ========== ヘルパー ==========

    async def _load_taboos(self) -> list:
        """persona_memoryからtabooカテゴリを読み込み（キャッシュ付き）"""
        if self._taboo_loaded and self._taboo_cache:
            return self._taboo_cache

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, content, reasoning FROM persona_memory WHERE category = 'taboo'"
                )
                self._taboo_cache = [dict(r) for r in rows]
                self._taboo_loaded = True
                logger.info(f"tabooエントリ読み込み: {len(self._taboo_cache)}件")
        except Exception as e:
            logger.error(f"taboo読み込みエラー: {e}")
            self._taboo_cache = []
        return self._taboo_cache

    def invalidate_taboo_cache(self):
        """tabooキャッシュを無効化（persona_memory更新時に呼ぶ）"""
        self._taboo_loaded = False
        self._taboo_cache = []


# ===== シングルトン =====
_harness_instance: Optional[HarnessLinter] = None


def get_harness_linter() -> HarnessLinter:
    """HarnessLinterのシングルトンを取得"""
    global _harness_instance
    if _harness_instance is None:
        _harness_instance = HarnessLinter()
    return _harness_instance
