"""
SYUTAINβ コンテンツ情報漏洩防止
記事/SNS投稿が公開される前に、秘密情報を自動的に除去する。

除去対象:
- APIキー（sk-ant-, sk-, key-等のパターン）
- パスワード
- メールアドレス
- IPアドレス（100.xx.xx.xx等のTailscale IP含む）
- Discord Token/Webhook URL
- データベース接続文字列
- .envに記載されてる全ての値
"""

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger("syutain.content_redactor")

# ===== パターンベース除去（正規表現） =====

REDACTION_PATTERNS: list[tuple[str, str]] = [
    # API Keys
    (r'sk-ant-[a-zA-Z0-9_-]+', '[REDACTED_API_KEY]'),
    (r'sk-[a-zA-Z0-9_-]{20,}', '[REDACTED_API_KEY]'),
    (r'key-[a-zA-Z0-9_-]{20,}', '[REDACTED_API_KEY]'),
    (r'GOCSPX-[a-zA-Z0-9_-]+', '[REDACTED]'),
    (r'xai-[a-zA-Z0-9_-]{20,}', '[REDACTED_API_KEY]'),
    (r'ghp_[a-zA-Z0-9]{36,}', '[REDACTED_API_KEY]'),
    (r'glpat-[a-zA-Z0-9_-]{20,}', '[REDACTED_API_KEY]'),

    # IP Addresses (Tailscale + local)
    (r'100\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[REDACTED_IP]'),
    (r'192\.168\.\d{1,3}\.\d{1,3}', '[REDACTED_IP]'),
    (r'10\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[REDACTED_IP]'),

    # Email addresses
    (r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]'),

    # Discord tokens/webhooks
    (r'https://discord\.com/api/webhooks/\d+/[a-zA-Z0-9_-]+', '[REDACTED_WEBHOOK]'),
    (r'https://discordapp\.com/api/webhooks/\d+/[a-zA-Z0-9_-]+', '[REDACTED_WEBHOOK]'),
    (r'[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}', '[REDACTED_TOKEN]'),

    # Database URLs
    (r'postgresql://[^\s"\']+', '[REDACTED_DB_URL]'),
    (r'postgres://[^\s"\']+', '[REDACTED_DB_URL]'),
    (r'nats://[^\s"\']+', '[REDACTED_NATS_URL]'),
    (r'redis://[^\s"\']+', '[REDACTED_URL]'),

    # SSH user@host
    (r'shimahara@[\d.]+', '[REDACTED_SSH]'),
    (r'shimahara@[a-zA-Z0-9._-]+', '[REDACTED_SSH]'),

    # Passwords (common patterns in configs/text)
    (r'(?i)password["\s:=]+[^\s"\']{4,}', '[REDACTED_PASSWORD]'),
    (r'NOTE_PASSWORD[^\n]*', '[REDACTED]'),
    (r'(?i)secret["\s:=]+[^\s"\']{8,}', '[REDACTED_SECRET]'),

    # OpenRouter / Anthropic / OpenAI bearer tokens
    (r'Bearer\s+[a-zA-Z0-9_-]{20,}', '[REDACTED_BEARER]'),

    # Generic long hex/base64 tokens (40+ chars, likely a secret)
    (r'(?<![a-zA-Z0-9])[a-f0-9]{40,}(?![a-zA-Z0-9])', '[REDACTED_HEX]'),
]

# コンパイル済みパターンキャッシュ
_compiled_patterns: list[tuple[re.Pattern, str]] | None = None


def _get_compiled_patterns() -> list[tuple[re.Pattern, str]]:
    """正規表現パターンをコンパイルしてキャッシュ"""
    global _compiled_patterns
    if _compiled_patterns is None:
        _compiled_patterns = []
        for pattern_str, replacement in REDACTION_PATTERNS:
            try:
                _compiled_patterns.append((re.compile(pattern_str), replacement))
            except re.error as e:
                logger.error(f"正規表現コンパイル失敗: {pattern_str} — {e}")
    return _compiled_patterns


# ===== .env値ベース除去 =====

_env_values: list[str] | None = None


def _load_env_values() -> list[str]:
    """
    .envファイルから値を読み込み、除去対象とする。
    短すぎる値（4文字未満）や一般的すぎる値は除外（誤検知防止）。
    """
    global _env_values
    if _env_values is not None:
        return _env_values

    _env_values = []
    env_path = Path(__file__).resolve().parent.parent / ".env"

    if not env_path.exists():
        logger.debug(f".envファイル未検出: {env_path}")
        return _env_values

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                _, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                # 短すぎる値、空値、一般的な値は除外
                if len(value) < 4:
                    continue
                if value.lower() in ("true", "false", "none", "null", "yes", "no",
                                     "localhost", "0.0.0.0", "127.0.0.1"):
                    continue
                # 数値のみ（ポート番号等）は除外
                if value.isdigit():
                    continue
                _env_values.append(value)
    except Exception as e:
        logger.error(f".env読み込み失敗: {e}")

    logger.debug(f".envから{len(_env_values)}個の除去対象値を読み込み")
    return _env_values


def redact_content(text: str) -> str:
    """
    テキストから秘密情報を除去する。

    1. 正規表現パターンマッチで除去
    2. .envの実値を完全一致で除去

    Args:
        text: 除去対象テキスト

    Returns:
        除去済みテキスト
    """
    if not text:
        return text

    result = text

    # 1. パターンベース除去
    for compiled_pat, replacement in _get_compiled_patterns():
        result = compiled_pat.sub(replacement, result)

    # 2. .env値の完全一致除去（長い値から順に — 部分一致の問題を回避）
    env_values = _load_env_values()
    sorted_values = sorted(env_values, key=len, reverse=True)
    for val in sorted_values:
        if val in result:
            result = result.replace(val, "[REDACTED_ENV]")

    return result


def is_safe_to_publish(text: str) -> tuple[bool, list[str]]:
    """
    テキストに秘密情報が含まれていないか検査する。

    Returns:
        (safe: bool, issues: list[str])
        safe=True なら公開OK、False なら秘密情報が残っている
    """
    if not text:
        return True, []

    issues = []

    # 1. パターンベースチェック
    for compiled_pat, replacement in _get_compiled_patterns():
        matches = compiled_pat.findall(text)
        if matches:
            # 実際の値はログに出さない（それ自体が漏洩になる）
            issues.append(
                f"パターン検出: {replacement} x{len(matches)}件"
            )

    # 2. .env値チェック
    env_values = _load_env_values()
    for val in env_values:
        if val in text:
            # 値自体は出さない
            issues.append(f".env値検出: [REDACTED_ENV] (長さ{len(val)})")

    safe = len(issues) == 0
    return safe, issues


def redact_and_validate(text: str) -> tuple[str, bool, list[str]]:
    """
    除去と検証を一括実行する便利関数。

    Returns:
        (redacted_text, is_safe_after_redaction, issues_before_redaction)
    """
    # まず問題を検出
    _, issues_before = is_safe_to_publish(text)

    # 除去実行
    redacted = redact_content(text)

    # 除去後に再検証
    safe_after, issues_after = is_safe_to_publish(redacted)

    if not safe_after:
        logger.error(f"除去後も秘密情報が残存: {len(issues_after)}件")

    return redacted, safe_after, issues_before


def clear_cache():
    """キャッシュをクリア（テスト用・.env変更後に使用）"""
    global _compiled_patterns, _env_values
    _compiled_patterns = None
    _env_values = None
