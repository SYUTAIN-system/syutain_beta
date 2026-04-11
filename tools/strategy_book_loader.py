"""
Strategy Book Loader — runtime parser for strategy/diffusion_execution_plan.md

Security design (2026-04-11 案B refactor):
- The strategy book itself is gitignored (contains non-public Day N scripts, pinned
  post variants, KPI targets, nickname heuristics, and other confidential content).
- Any code that references strategy book content MUST read it at runtime via this
  loader, not embed verbatim text/numbers in source files.
- This loader file itself contains zero verbatim strategy text. If the strategy
  book is absent (e.g. on another machine, in a CI environment, or on GitHub),
  the loader returns empty / default values and the caller must degrade gracefully.

Public API:
- get_day_items() -> list[dict]   # Day 1-7 complete scripts
- get_pinned_post_variants() -> dict[str, str]  # {'A': ..., 'B': ...}
- get_kpi_targets() -> dict[str, dict]  # lower/upper targets
- get_callout_nicknames() -> list[str]
- is_available() -> bool
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Strategy book path (gitignored, local-only file)
_STRATEGY_BOOK_PATH = Path(__file__).resolve().parent.parent / "strategy" / "diffusion_execution_plan.md"


def is_available() -> bool:
    """Strategy book が読める状態かチェック"""
    try:
        return _STRATEGY_BOOK_PATH.exists() and _STRATEGY_BOOK_PATH.is_file()
    except Exception:
        return False


def _read_book() -> str | None:
    """Strategy book 本文を読み込む。存在しなければ None"""
    if not is_available():
        logger.warning(
            "strategy_book_loader: strategy/diffusion_execution_plan.md not found. "
            "Returning empty results. (This is expected on machines without the gitignored book.)"
        )
        return None
    try:
        return _STRATEGY_BOOK_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"strategy_book_loader: read failed: {e}")
        return None


# ============================================================
# Day 1-7 parser
# ============================================================

_DAY_HEADING_RE = re.compile(
    r"^##\s*Day\s*(\d+)[^\n]*?[:：]?\s*(.*?)$",
    re.MULTILINE,
)

_CODEBLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_-]*)?\n(.*?)\n```", re.DOTALL)

_TITLE_RE = re.compile(r"\*\*タイトル\*\*[:：]\s*「?([^」\n]+)」?", re.MULTILINE)


def _slice_day_sections(text: str) -> list[tuple[int, str, str]]:
    """Day 1, Day 2, ... の範囲を切り出す。戻り値: [(day_num, day_label, body), ...]"""
    sections: list[tuple[int, str, str]] = []
    matches = list(_DAY_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        try:
            day_num = int(m.group(1))
        except (ValueError, IndexError):
            continue
        # Extract label from the heading line — strip "Day N" prefix and any parentheses
        label_raw = (m.group(2) or "").strip()
        # Drop "(日付)" prefix if present like "(4/11 金)：note記事①"
        label_clean = re.sub(r"^[（(][^）)]*[）)][:：]?\s*", "", label_raw)
        label_clean = label_clean.strip("：: ").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        sections.append((day_num, label_clean, body))
    return sections


def _extract_first_codeblock(body: str) -> str | None:
    m = _CODEBLOCK_RE.search(body)
    if not m:
        return None
    return m.group(1).strip()


def _extract_title(body: str) -> str | None:
    m = _TITLE_RE.search(body)
    if not m:
        return None
    return m.group(1).strip()


def _build_day_metadata(day_num: int, day_label: str, body: str) -> dict[str, Any]:
    """Day number から metadata を推定する(item_type, dynamic_fields 等)"""
    meta: dict[str, Any] = {"dynamic_values": False}
    label_lower = day_label.lower()
    # Day 3 的なもの — リプだけの日
    if "リプ" in day_label:
        meta["auto_executable"] = False
        meta["target_count"] = 5
    # Day 4, Day 7 は note 系
    if "note" in label_lower or "note" in day_label or "週報" in day_label:
        meta["dynamic_values"] = True
        if "週報" in day_label:
            meta["category"] = "weekly_report"
            meta["is_week_zero"] = True
        else:
            meta["category"] = "note_article"
    # Day 5 数字の投稿
    elif "数字" in day_label:
        meta["dynamic_values"] = True
        meta["category"] = "stats"
    elif "軽い" in day_label or "日曜" in day_label:
        meta["dynamic_values"] = True
        meta["category"] = "reflection"
    elif day_num == 1:
        meta["dynamic_values"] = True
        meta["pinned_post_variant"] = "A"
        meta["has_video_note"] = True
    elif "事件" in day_label:
        meta["category"] = "incident"
    return meta


def _classify_day_type(day_num: int, day_label: str) -> tuple[str, str, str]:
    """(item_type, platform, account) を返す"""
    label_lower = day_label.lower()
    if "リプ" in day_label:
        return ("reply_day", "x", "shimahara")
    if "週報" in day_label:
        return ("weekly_report", "note", "syutain")
    if "note" in day_label or "note" in label_lower:
        return ("note_article", "note", "syutain")
    # デフォルトは X shimahara post
    return ("x_post", "x", "shimahara")


def _load_placeholder_rules() -> list[tuple[str, str]]:
    """Snapshot number → placeholder replacement rules を設定から読み込む。

    Rules は .env の STRATEGY_BOOK_PLACEHOLDER_RULES か settings DB の
    strategy_book_placeholder_rules から JSON で読む。いずれも無ければ
    最小限のデフォルトを返す(行数/金額等の一般的なパターンのみ)。

    これにより、戦略書固有の snapshot 数値を source code に埋め込まない。
    """
    import os
    import json as _json
    try:
        raw = os.getenv("STRATEGY_BOOK_PLACEHOLDER_RULES", "").strip()
        if raw:
            data = _json.loads(raw)
            if isinstance(data, list):
                return [(r[0], r[1]) for r in data if isinstance(r, (list, tuple)) and len(r) == 2]
    except Exception:
        pass
    # 最小デフォルト — 単位付き数字の generic パターンのみ
    return [
        # 売上/収益の零表記
        (r"(?<=売上:)¥?0\b", r"¥{revenue}"),
        (r"(?<=売上:) ?¥0", r"¥{revenue}"),
        (r"(?<=収益 )¥0", r"¥{revenue}"),
        (r"(?<=収益)¥0\b", r"¥{revenue}"),
    ]


def _replace_verbatim_numbers_with_placeholders(content: str) -> str:
    """Strategy book snapshot 数値を runtime placeholder に置換する。

    Design: snapshot 数値(書いた時点の実測値)はコードに hard-code せず、
    _load_placeholder_rules() から読んだルールで置換する。
    caller は strategy_plan_executor._resolve_dynamic_values() が埋める
    placeholder を前提にしてよい。
    """
    rules = _load_placeholder_rules()
    for pattern, replacement in rules:
        try:
            content = re.sub(pattern, replacement, content)
        except re.error as e:
            logger.warning(f"invalid placeholder rule {pattern!r}: {e}")
    return content


def _infer_dynamic_fields(content: str) -> list[str]:
    """content 内の {placeholder} を抽出"""
    return list(set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", content)))


def _get_weekly_report_template(text: str) -> str | None:
    """「# 第4部 週報フォーマット」の code block を取得する"""
    # 「週報フォーマット」セクション
    start = text.find("週報フォーマット")
    if start < 0:
        return None
    end = text.find("# 第5部", start)
    if end < 0:
        end = len(text)
    section = text[start:end]
    return _extract_first_codeblock(section)


def get_day_items() -> list[dict[str, Any]]:
    """Day 1-7 の完成稿を読み取り、strategy_plan_items 形式の dict リストで返す。

    戻り値が空リストの場合、strategy book が存在しない or parse失敗。
    caller は空を受け入れて degrade すること。
    """
    text = _read_book()
    if not text:
        return []

    # 週報テンプレ(Day 7 用)
    weekly_template = _get_weekly_report_template(text)

    # 「# 第7部 Week 1 完成原稿」以降を対象にする
    week1_start = text.find("Week 1 完成原稿")
    if week1_start < 0:
        logger.warning("strategy_book_loader: '# 第7部 Week 1 完成原稿' section not found")
        return []
    # 「# 第8部」で終わる
    week1_end = text.find("# 第8部", week1_start)
    if week1_end < 0:
        week1_end = len(text)

    week1_text = text[week1_start:week1_end]
    sections = _slice_day_sections(week1_text)

    items: list[dict[str, Any]] = []
    for day_num, day_label, body in sections:
        if day_num < 1 or day_num > 7:
            continue
        item_type, platform, account = _classify_day_type(day_num, day_label)

        title = _extract_title(body)
        content = _extract_first_codeblock(body) or ""

        if not content and item_type != "reply_day":
            # Day 3 のような投稿しない日はプレーンテキスト説明をそのまま使う
            # 空の code block の場合は body テキストの一部を使う
            first_para = body.strip().split("\n\n")[0] if body.strip() else ""
            content = first_para[:500]

        if item_type == "weekly_report":
            # Day 7 は「上記の週報フォーマットに数字を入れて公開」と書かれているだけなので、
            # 第4部の週報テンプレートを content として使う。
            if weekly_template:
                # Week 0 向け見出しを追加(第7部 Day 7 で指定されている)
                week0_title = "SYUTAINβ Week 0 —— まだ何も始まっていない"
                # テンプレートの XX や 〇〇 を placeholder に置換
                tpl = weekly_template
                # Week XX → Week 0
                tpl = re.sub(r"Week\s*XX", "Week {week_num}", tpl)
                # [一言見出し] → Day 7 は Week 0 タイトルを使う
                tpl = tpl.replace("[一言見出し]", "まだ何も始まっていない")
                # 数字プレースホルダ XX/XXX をそのままにしておくと意味が通らないので、
                # 専用のテンプレ変数に置き換える(executor 側で埋める)
                content = f"# {week0_title}\n\n{tpl}"
                if not title:
                    title = week0_title
        elif item_type == "note_article":
            # note 記事は title + markdown content を組み立てる
            if content:
                if title:
                    full_content = f"# {title}\n\n{content}"
                else:
                    full_content = content
                content = full_content

        # Day 3 特殊処理(リプだけの日なので投稿テキストは無い)
        if item_type == "reply_day":
            # body から説明文を抽出
            lines = []
            for line in body.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("**") or line.startswith("##") or line.startswith("```"):
                    continue
                lines.append(line)
            content = "\n".join(lines[:10])

        if not content:
            continue

        # 数値 → placeholder 変換
        content = _replace_verbatim_numbers_with_placeholders(content)

        meta = _build_day_metadata(day_num, day_label, body)
        dyn_fields = _infer_dynamic_fields(content)
        if dyn_fields:
            meta["dynamic_values"] = True
            meta["dynamic_fields"] = dyn_fields

        items.append({
            "day_number": day_num,
            "day_label": day_label,
            "item_type": item_type,
            "platform": platform,
            "account": account,
            "title": title,
            "content": content,
            "metadata": meta,
        })

    return items


# ============================================================
# Pinned post variants (第6部)
# ============================================================


def get_pinned_post_variants() -> dict[str, str]:
    """固定ポスト A案 / B案 を strategy book から読み取る。

    見つからない場合は空 dict を返す(caller は degrade)。
    """
    text = _read_book()
    if not text:
        return {}

    # 「# 第6部 固定ポスト」以降 「# 第7部」まで
    start = text.find("固定ポスト")
    if start < 0:
        return {}
    end = text.find("# 第7部", start)
    if end < 0:
        end = len(text)
    section = text[start:end]

    variants: dict[str, str] = {}
    # A案 / B案 の見出しで分割
    case_re = re.compile(r"##\s*([AB])案", re.MULTILINE)
    matches = list(case_re.finditer(section))
    for i, m in enumerate(matches):
        variant_name = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[body_start:body_end]
        block = _extract_first_codeblock(body)
        if block:
            # Remove link placeholders like "→ 全記録：[note link]"
            cleaned = re.sub(r"→[^\n]*\[.*?\][^\n]*", "", block).strip()
            # Remove trailing empty lines
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            # Replace verbatim numbers with placeholders
            cleaned = _replace_verbatim_numbers_with_placeholders(cleaned)
            variants[variant_name] = cleaned
    return variants


# ============================================================
# KPI targets (第11部)
# ============================================================


def _parse_kpi_range(cell: str) -> tuple[int, int] | int | None:
    """「+600〜1,000」「+3,000〜5,000」「50人以上」「5件以上」等の KPI セルを parse"""
    cell = cell.strip()
    # Remove leading +
    cell = cell.lstrip("+")
    # Try "A〜B" form
    m = re.match(r"([\d,]+)\s*[〜~]\s*([\d,]+)", cell)
    if m:
        try:
            return (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")))
        except ValueError:
            return None
    # Try "N以上" form
    m = re.match(r"([\d,]+)\s*(?:人|件|回|円|本)?\s*以上", cell)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    # Try plain number
    m = re.match(r"([\d,]+)", cell)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


# 戦略書の KPI ラベルを code 側のキー名に map する辞書
# ラベルそのものは戦略書にしか存在しないので、fuzzy match する
_KPI_LABEL_HINTS = [
    ("x_follower_delta", ["xフォロワー", "x フォロワー"]),
    ("note_follower_delta", ["noteフォロワー", "note フォロワー"]),
    ("note_total_pv", ["note累計pv", "note 累計 pv", "累計pv"]),
    ("weekly_report_readers", ["週報定期読者", "週報読者"]),
    ("third_party_mentions", ["第三者言及", "第三者 言及"]),
    ("external_media_mentions", ["外部メディア", "メディア露出"]),
]


def _label_to_key(label: str) -> str | None:
    label_norm = label.lower().strip()
    for key, hints in _KPI_LABEL_HINTS:
        for hint in hints:
            if hint in label_norm:
                return key
    return None


def get_kpi_targets() -> dict[str, dict[str, Any]]:
    """戦略書第11部の 2ヶ月後目標 (下限/上振れ) を dict で返す。

    戻り値: {"lower": {...}, "upper": {...}}
    見つからなければ空 dict。caller は degrade すること。
    """
    text = _read_book()
    if not text:
        return {}

    result: dict[str, dict[str, Any]] = {"lower": {}, "upper": {}}

    # 「## 2ヶ月後の目標」セクション
    start = text.find("2ヶ月後の目標")
    if start < 0:
        return {}
    # 「## 数字より重要な状態」で終わる想定
    end = text.find("数字より重要な状態", start)
    if end < 0:
        end = len(text)
    section = text[start:end]

    # 下限 / 上振れ の各ブロック
    lower_match = re.search(r"\*\*下限[^\*]*\*\*[^\n]*\n(.*?)(?=\*\*上振れ|$)", section, re.DOTALL)
    upper_match = re.search(r"\*\*上振れ[^\*]*\*\*[^\n]*\n(.*)", section, re.DOTALL)

    for tier, match in [("lower", lower_match), ("upper", upper_match)]:
        if not match:
            continue
        block = match.group(1)
        # Markdown テーブル行を処理: | 指標 | 目標 |
        for line in block.split("\n"):
            if not line.strip().startswith("|"):
                continue
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) < 2:
                continue
            label, value = parts[0], parts[1]
            if not label or label == "指標" or label.startswith("---") or label.startswith(":"):
                continue
            key = _label_to_key(label)
            if not key:
                continue
            parsed = _parse_kpi_range(value)
            if parsed is not None:
                result[tier][key] = parsed

    return result


# ============================================================
# Callout nicknames (第1部の「口コミで流通する呼び名」)
# ============================================================


def get_callout_nicknames() -> list[str]:
    """戦略書で想定されている「口コミで流通する呼び名」候補リスト。

    戻り値が空なら strategy book なし or parse失敗。
    """
    text = _read_book()
    if not text:
        return []

    # 「口コミで流通する呼び名」セクション
    start = text.find("口コミで流通する呼び名")
    if start < 0:
        return []
    # 次の「##」まで
    end = text.find("\n##", start + 10)
    if end < 0:
        end = len(text)
    section = text[start:end]

    nicknames: list[str] = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("-"):
            name = line.lstrip("- ").strip()
            if name and len(name) <= 40:
                nicknames.append(name)
    return nicknames


# ============================================================
# Start date (Day 1 date, default 2026-04-08 火 if parse fails)
# ============================================================


def get_week1_start_date() -> "date":
    """戦略書 Day 1 の日付を取得する。parse失敗時は 2026-04-08 を返す。"""
    from datetime import date as _date
    text = _read_book()
    if not text:
        return _date(2026, 4, 8)
    # Match "## Day 1（4/8 火）" or "Day 1 (4/8 火)"
    m = re.search(r"##\s*Day\s*1[（(]\s*(\d+)/(\d+)", text)
    if not m:
        return _date(2026, 4, 8)
    try:
        month = int(m.group(1))
        day = int(m.group(2))
        # Infer year: current year
        from datetime import datetime as _dt
        year = _dt.now().year
        return _date(year, month, day)
    except (ValueError, IndexError):
        return _date(2026, 4, 8)


if __name__ == "__main__":
    # Manual smoke test
    print(f"available: {is_available()}")
    print(f"start_date: {get_week1_start_date()}")
    items = get_day_items()
    print(f"day items: {len(items)}")
    for it in items:
        print(f"  Day {it['day_number']} [{it['item_type']}] {it['day_label']}: {len(it['content'])} chars, dyn={it['metadata'].get('dynamic_fields')}")
    print(f"pinned variants: {list(get_pinned_post_variants().keys())}")
    kpi = get_kpi_targets()
    print(f"kpi lower: {kpi.get('lower')}")
    print(f"kpi upper: {kpi.get('upper')}")
    print(f"nicknames: {get_callout_nicknames()}")
