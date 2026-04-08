"""
SYUTAINβ 多段コンテンツ生成パイプライン
6段階で商品化可能なコンテンツを生成する。

Stage 1: ネタ選定 (intel_items + persona_memory → テーマ)
Stage 2: 構成案 (テーマ → Phase A-E骨組み)
Stage 3: 初稿 (構成案 → 本文) ※実データ注入
Stage 4: リライト (初稿 → 島原の声で書き直し)
Stage 4.5: セルフ批評＆改善 (別モデルで弱点を特定し改善)
Stage 5: 品質検証 (多軸評価)
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tools.db_pool import get_connection
from tools.llm_router import choose_best_model_v6, call_llm
from tools.content_redactor import redact_content, is_safe_to_publish
from brain_alpha.sns_batch import _score_multi_axis, _PERSONA_KEYWORDS

logger = logging.getLogger("syutain.brain_alpha.content_pipeline")

STRATEGY_DIR = Path(__file__).resolve().parent.parent / "strategy"
_NOTE_PENDING_BACKLOG_LIMIT = 2
_NOTE_BACKLOG_BYPASS_THEME_MARKERS = (
    "Discord 経由で直接依頼",
    "記事執筆依頼",
)

# ジャンル別テンプレート・3軸タイトル生成
try:
    from strategy.note_genre_templates import (
        detect_genre,
        get_template,
        build_title_generation_prompt,
        build_structure_prompt_with_template,
    )
    _HAS_GENRE_TEMPLATES = True
except ImportError:
    _HAS_GENRE_TEMPLATES = False
    logger.warning("note_genre_templates未読み込み — テンプレートなしで続行")


def _sanitize_title(title: str, fallback_theme: str = "") -> str:
    """タイトルからプロンプト指示の漏洩を除去し、25文字以内に制限する"""
    if not title:
        return fallback_theme or "無題"

    # 複数行の場合、プロンプト指示っぽい行を除去
    lines = title.strip().split("\n")
    clean_lines = []
    _prompt_patterns = re.compile(
        r"(^【|以下|してください|生成|出力|フォーマット|テンプレート|プロンプト|指示|条件|注意"
        r"|^\*\*note|^\*\*有料|ドラフト|Stage|フォーマット"
        r"|^#"
        r"|（\d+円）"
        r"|自由テーマ|intel_items|persona_memory|theme_hint|trend_detector"
        r"|海外トレンド先取り|独自視点で書く|記事を書く|テーマの記事"
        r"|収集した最新情報|価値観を組み合わせ"
        r")",
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _prompt_patterns.search(stripped):
            continue
        clean_lines.append(stripped)

    sanitized = clean_lines[0] if clean_lines else ""

    # Markdown見出し記号を除去
    sanitized = sanitized.lstrip("#").strip()
    # **太字**記法を除去
    sanitized = sanitized.strip("*").strip()

    # 25文字制限（noteのタイトルは端的に。長すぎるのはプロンプト漏洩の疑い）
    if len(sanitized) > 25:
        # 句読点で切れる位置を探す
        for i in range(min(25, len(sanitized)), 10, -1):
            if sanitized[i-1] in "。！？」—":
                sanitized = sanitized[:i]
                break
        else:
            sanitized = sanitized[:22] + "..."

    # 空になった場合はフォールバック
    if not sanitized:
        return fallback_theme or "無題"

    return sanitized


def _load_content_patterns() -> str:
    """strategy/daichi_content_patterns.md を読み込む"""
    path = STRATEGY_DIR / "daichi_content_patterns.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _load_writing_style() -> str:
    """strategy/daichi_writing_style.md を読み込む"""
    path = STRATEGY_DIR / "daichi_writing_style.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _load_anti_ai_writing() -> str:
    """prompts/anti_ai_writing.md を読み込む"""
    path = Path(__file__).resolve().parent.parent / "prompts" / "anti_ai_writing.md"
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _verify_factual_claims(content: str) -> list[str]:
    """記事中の事実主張を検証し、問題のリストを返す。
    - 年号とAIツールの整合性
    - 島原の経歴に矛盾するclaim
    - 根拠なき数値claim
    """
    issues = []

    # 1. 年号 + AIツール整合性チェック
    # SYUTAINβ は特殊: 個人プロジェクトなので「SYUTAINβで〜した」等、
    # リリース後の体験として直接結びついた年号のみチェックする（広い context だと
    # 島原さんの過去経歴/他ツール言及で誤検知する）
    for tool_name, release_year in AI_TIMELINE.items():
        tool_positions = [m.start() for m in re.finditer(re.escape(tool_name), content)]
        for pos in tool_positions:
            if tool_name == "SYUTAINβ":
                # SYUTAINβ は直後 60 字以内のみチェック（「SYUTAINβで〜した」等の直接的文脈）
                local_context = content[pos:min(len(content), pos + 60)]
                m = re.search(r'(\d{4})年', local_context)
                if m:
                    year = int(m.group(1))
                    if year < release_year:
                        issues.append(
                            f"[タイムライン矛盾] {tool_name}は{release_year}年リリースだが、"
                            f"{year}年のエピソードで言及されている"
                        )
            else:
                # 他のAIツール（GPT-4, Claude, DeepSeek等）は従来通り 300 字の広い context
                context_start = max(0, pos - 300)
                context_end = min(len(content), pos + 300)
                context = content[context_start:context_end]
                context_years = re.findall(r'(\d{4})年', context)
                for year_str in context_years:
                    year = int(year_str)
                    if year < release_year:
                        issues.append(
                            f"[タイムライン矛盾] {tool_name}は{release_year}年リリースだが、"
                            f"{year}年のエピソードで言及されている"
                        )

    # 2. 島原の経歴矛盾チェック
    false_claims = [
        (r'島原.{0,10}(?:音楽|楽曲|作曲|演奏)', "島原は音楽の仕事をしていない"),
        (r'島原.{0,10}(?:VTuber(?:として|活動|デビュー))', "島原はVTuber活動者ではない（業界支援側）"),
        (r'島原.{0,10}(?:エンジニア(?:として|の経験|出身))', "島原は非エンジニア"),
        (r'島原.{0,10}(?:プログラム(?:を書|ミング)|コーディング)', "島原はコードを書けない"),
        (r'VTuber.{0,20}(?:支える|支援する|管理する)(?:システム|仕組み)', "SYUTAINβはVTuber支援システムではない"),
        (r'(?:Grafana|Prometheus|Datadog|Sentry|NewRelic|Splunk)', "使っていないツール名"),
        (r'(?:運用チーム|開発チーム|開発メンバー|同僚が|離職率)', "組織捏造（個人開発）"),
    ]
    for pattern, msg in false_claims:
        if re.search(pattern, content):
            issues.append(f"[経歴矛盾] {msg}")

    # 3. 匿名エピソード検出
    anon_patterns = [
        r'ある(?:会社|企業|スタートアップ|チーム)(?:で|が|の|では)',
        r'(?:友人|知人|知り合い)(?:が|の|は).{5,50}(?:した|ている|だった)',
    ]
    for pattern in anon_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            match_pos = content.find(match)
            if match_pos >= 0:
                nearby = content[max(0, match_pos - 100):match_pos]
                if not re.search(r'(?:仮の話|たとえば|仮に|架空|例として)', nearby):
                    issues.append(f"[匿名エピソード] 「{match[:40]}」— 実体験か仮の話か不明")

    # 4. 根拠なき統計数値チェック（「XX%が〜」のような表現）
    stat_patterns = re.findall(r'(\d{1,3})%(?:が|の|は|で|を)', content)
    for pct in stat_patterns:
        pct_val = int(pct)
        if 10 <= pct_val <= 99:
            pct_pos = content.find(f"{pct}%")
            if pct_pos >= 0:
                nearby = content[max(0, pct_pos - 200):min(len(content), pct_pos + 200)]
                if not re.search(r'(?:出典|調査|レポート|データ|SYUTAINβ|実データ|実績|公式)', nearby):
                    issues.append(f"[根拠なき数値] 「{pct}%」に出典がない")

    return issues


def _bypass_note_backlog_guard(theme: str = "") -> bool:
    """明示的な執筆依頼は backlog ガードをバイパスする。"""
    if not theme:
        return False
    return any(marker in theme for marker in _NOTE_BACKLOG_BYPASS_THEME_MARKERS)


async def _get_note_publish_backlog(conn) -> tuple[int, int]:
    """note公開待ち件数(ready/approved)と当日公開数を返す。"""
    row = await conn.fetchrow(
        """SELECT
               COUNT(*) FILTER (WHERE status IN ('ready', 'approved')) AS pending_count,
               COUNT(*) FILTER (
                   WHERE status = 'published'
                     AND (published_at AT TIME ZONE 'Asia/Tokyo')::date =
                         (NOW() AT TIME ZONE 'Asia/Tokyo')::date
               ) AS published_today
           FROM product_packages
           WHERE platform = 'note'"""
    )
    if not row:
        return 0, 0
    return int(row["pending_count"] or 0), int(row["published_today"] or 0)


def _sanitize_article_output(content: str) -> str:
    """LLM生成結果からメタ指示漏洩・応答アーティファクトを除去する。
    Stage 3, 4, 4.5 の全出力に適用する。

    3段階で除去:
    1. 冒頭のLLM応答アーティファクト除去
    2. 本文全体のプロンプト漏洩除去（行単位）
    3. 不要な定型文・マーカーの除去
    """
    if not content:
        return content

    # === Stage 1: 冒頭のLLM応答アーティファクト除去 ===
    lines = content.split("\n")
    cleaned_lines = []

    _meta_patterns = re.compile(
        r'^(?:はい。|はい、|了解(?:しました|です|いたしました)|承知(?:しました|です|いたしました)'
        r'|以下(?:は|が|に|の).*(?:記事|執筆|作成|生成|ドラフト)'
        r'|.*(?:執筆します|作成します|生成します|書きます)$'
        r'|SYUTAINβとして、?(?:記事を|執筆|作成)'
        r'|(?:それでは|では).*(?:記事|執筆|作成|生成))'
    )

    content_started = False
    for i, line in enumerate(lines):
        stripped = line.strip()

        if not content_started:
            if not stripped:
                continue
            if _meta_patterns.match(stripped):
                continue
            if stripped.startswith("```") and i < 5:
                continue
            content_started = True

        if content_started:
            cleaned_lines.append(line)

    # 末尾の ``` や空行を除去
    while cleaned_lines and cleaned_lines[-1].strip() in ("```", ""):
        cleaned_lines.pop()

    content = "\n".join(cleaned_lines).strip()

    # === Stage 2: 本文全体のプロンプト漏洩除去（行単位スキャン）===
    _prompt_leak_patterns = re.compile(
        r'(?:自由テーマ|intel_items|persona_memory|theme_hint|trend_detector'
        r'|content_pipeline|choose_best_model|model_selection'
        r'|system_prompt|user_prompt|few_shot'
        r'|Stage \d|Phase [A-E]|構成案に基づき'
        r'|記事本文のみを出力|メタ情報や説明は不要'
        r'|note有料記事タイトル|購買意欲を最大化'
        r'|ジャンルキーワード|感情トリガー|切り口'
        r'|Axis \d|3軸タイトル'
        r'|CLAUDE\.md|LoopGuard|Emergency Kill'
        r'|fabrication_risk|quality_score'
        r'|max_tokens|temperature|repeat_penalty)',
        re.IGNORECASE,
    )

    final_lines = []
    for line in content.split("\n"):
        stripped = line.strip()
        # プロンプト漏洩パターンを含む行をスキップ（ただしコードブロック内は除外）
        if _prompt_leak_patterns.search(stripped) and not stripped.startswith("```"):
            # 見出し行（## 等）はスキップしない（記事構造を壊さないため）
            if not stripped.startswith("#"):
                continue
        final_lines.append(line)

    content = "\n".join(final_lines)

    # === Stage 3: 不要な定型文・マーカーの除去 ===
    _remove_patterns = [
        r'\*\*ここから先は有料です。?\*\*[^\n]*',
        r'ここから先は有料です[。]?[^\n]*',
        r'---ここから有料---',
        r'ここから有料---',
        r'---ここから有料',
        r'全文を読むには購入してください',
        r'\[SYUTAINβ auto-generated\]',
        r'記事本文のみを出力。?',
        r'メタ情報や説明は不要。?',
        r'# タイトルから始めて.*?まとめで終わる。?',
        r'\*この記事はSYUTAIN.?が生成し.*?監修しています。\*',
    ]
    for pat in _remove_patterns:
        content = re.sub(pat, '', content)

    # === Stage 4: 重複H1除去（theme_hintタイトルと本文タイトルが共存する問題）===
    h1_matches = list(re.finditer(r'^# .+$', content, re.MULTILINE))
    if len(h1_matches) >= 2:
        # 最初のH1がtheme_hintなら除去して2番目を残す
        first_h1 = h1_matches[0].group()
        _leak_check = re.compile(
            r'(?:自由テーマ|intel_items|persona_memory|theme_hint|trend_detector'
            r'|海外トレンド先取り|独自視点で書く|記事を書く|テーマの記事'
            r'|収集した最新情報|価値観を組み合わせ)'
        )
        if _leak_check.search(first_h1) or len(first_h1) > 60:
            # 最初のH1を除去
            content = content[:h1_matches[0].start()] + content[h1_matches[0].end():]

    # === Stage 5: 番号リストの修正（1. 2. 1. 2. の繰り返しを正規化）===
    # 番号付きリストの連番を収集して、リセットされている箇所を箇条書きに変換
    lines_for_list = content.split("\n")
    fixed_lines = []
    number_sequence = []  # (行インデックス, 番号)
    for i, line in enumerate(lines_for_list):
        m = re.match(r'^(\d+)\.\s+(.+)', line.strip())
        if m:
            number_sequence.append((i, int(m.group(1))))
        fixed_lines.append(line)
    # 連番のリセットを検出（1→2→1→2のパターン）
    if len(number_sequence) >= 4:
        for j in range(2, len(number_sequence)):
            idx, num = number_sequence[j]
            prev_idx, prev_num = number_sequence[j-1]
            if num <= prev_num:
                # 番号がリセットされた→箇条書きに変換
                fixed_lines[idx] = re.sub(r'^\s*\d+\.\s+', '- ', fixed_lines[idx])
    content = "\n".join(fixed_lines)

    # 連続する空行を2行以内に
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    return content.strip() if content.strip() else content


# AIツールのリリース年タイムライン（事実検証用）
AI_TIMELINE = {
    "ChatGPT": 2022,
    "GPT-4": 2023,
    "Claude": 2023,
    "Midjourney": 2022,
    "Stable Diffusion": 2022,
    "DALL-E": 2021,  # DALL-E 1 was 2021, but not widely available
    "SYUTAINβ": 2025,
    "Claude Code": 2025,
    "Codex (OpenAI)": 2025,
    "DeepSeek": 2024,
}

# 事実検証ルール（Stage 3 system promptに注入）
_FACTUAL_VERIFICATION_RULES = """
## 事実検証ルール（絶対厳守）:
- 島原大知の実体験として語る場合、以下のタイムラインに矛盾してはならない:
  - ChatGPT公開: 2022年11月
  - Claude公開: 2023年3月
  - 島原大知がAI/Claude Codeを使い始めた: 2026年2月28日（それ以前のAI利用体験は捏造）
  - SYUTAINβ開発開始: 2026年2月28日
  - SYUTAINβ本格稼働: 2026年3月19日
- 2026年2月28日以前のAIツール利用エピソードは捏造になる。書くな。
- 「ある会社で」「友人が」等の匿名エピソードは禁止。実体験か、明確に「仮の話として」と断ること
- 具体的な数値を書く場合、出典が必要。SYUTAINβの実データか、公開情報のみ使用可
- 年号を書く場合、その年に該当テクノロジーが存在していたか確認すること
- **ハーネスエンジニアリング**は島原大知が命名/考案した方法論ではない。既存の方法論を適用しているだけ。「命名した」「考え出した」「誕生させた」「提唱した」「発明した」は禁止。「実践している」「適用している」「使っている」が正しい表現
- **「私は…と呼ぶ」「僕が…と命名した」「これを…と名付けた」等の自己命名パターン全般は禁止**（概念を自分が作ったと偽装することの再発防止）
- **SYUTAINβは島原大知の個人開発プロジェクトで、運用チーム・開発メンバー・同僚・離職者は存在しない**。「運用チーム」「開発チーム」「メンバーが会社を去った」「離職率」「ある担当者は」「開発メンバーの1人」等の記述は全て捏造として禁止
- **実在しないツールを「使っている」と書かない**。SYUTAINβの実運用は: PostgreSQL + NATS + Tailscale + Ollama + FastAPI + Next.js + Playwright + Discord.py のみ。Grafana/Prometheus/Restic/Datadog/NewRelic/Sentry等は使っていない
- **出典不明の外部事例を捏造しない**: 「BBC/NYTimes/WSJ等が〇〇を試験導入」「滞在時間2.1倍」「ある調査会社のデータ」→ 裏付けがない場合は書かない
"""

# 構造チェックリスト（Stage 3 system promptに注入）
_STRUCTURAL_QUALITY_CHECKLIST = """
## 記事の構造チェックリスト（全て満たすこと）:
□ 冒頭3行で読者の注意を掴む具体的な数字/事実がある
□ 各セクションに「なぜ？」の答えがある
□ 各セクションに具体的なツール名/設定値/コマンドがある
□ 読者が「明日から試せる」アクションが5つ以上ある
□ SYUTAINβの実データを3箇所以上引用している
□ 失敗談が最低1つ含まれている（成功談だけは信用されない）
□ 記事を読んだ後の「次のステップ」が明確
"""

# 文体強化ルール
_WRITING_STYLE_ENFORCEMENT = """
## 文体の鉄則（必ず守ること）:
- 結論→根拠→具体例の順で書く。序論から始めない
- 「〜だと思います」「〜かもしれません」を減らす。断定する
- 接続詞を減らす。「しかし」「また」「そして」を多用しない
- 1段落は3文以内。長い段落は分割する
- 数字で語る。形容詞で盛らない
- 「重要です」と書く代わりに、なぜ重要かを具体例で示す
- 読者に「で、どうすればいいの？」と思わせない。常にアクションを添える
"""


async def _load_few_shot_examples(conn) -> list[str]:
    """daichi_writing_examples + 投稿済み高品質記事 + strategy文書からfew-shot例を構築"""
    examples = []

    # 1. daichi_writing_examples テーブルから取得
    try:
        rows = await conn.fetch(
            """SELECT tweet_text FROM daichi_writing_examples
            WHERE theme_category = 'long_article'
            AND is_high_quality = true
            ORDER BY engagement_score DESC LIMIT 5"""
        )
        examples.extend([r["tweet_text"] for r in rows if r["tweet_text"]])
    except Exception as e:
        logger.debug(f"few-shot例(DB)取得失敗: {e}")

    # 2. 投稿済み高品質note記事から追加（最大3件）
    posted_examples = await _load_posted_article_examples(conn)
    if posted_examples:
        examples.extend(posted_examples)

    # 3. テーブルが空の場合、strategy文書から文体サンプルを生成
    if not examples:
        try:
            strategy_path = STRATEGY_DIR / "CONTENT_STRATEGY.md"
            if strategy_path.exists():
                strategy_text = strategy_path.read_text(encoding="utf-8")
                # Hook Pattern Libraryからサンプルを抽出
                hook_section = ""
                in_hook = False
                for line in strategy_text.split("\n"):
                    if "Hook Pattern Library" in line:
                        in_hook = True
                        continue
                    if in_hook and line.startswith("## ") and "Hook" not in line:
                        break
                    if in_hook:
                        hook_section += line + "\n"
                if hook_section:
                    examples.append(f"【島原大知のフックパターン集】\n{hook_section[:1500]}")

            # daichi_content_patterns.mdから核心の書き方サンプル
            patterns_path = STRATEGY_DIR / "daichi_content_patterns.md"
            if patterns_path.exists():
                patterns_text = patterns_path.read_text(encoding="utf-8")
                # 思想キーワードと構成パターンを抽出
                examples.append(f"【島原大知のコンテンツ構造パターン】\n{patterns_text[:1500]}")
        except Exception as e:
            logger.debug(f"strategy文書からのfew-shot構築失敗: {e}")

    return examples


async def _load_persona(conn) -> str:
    """persona_memory から哲学・アイデンティティを取得（最大10件）"""
    try:
        rows = await conn.fetch(
            """SELECT content FROM persona_memory
            WHERE category IN ('philosophy', 'identity')
            ORDER BY created_at DESC LIMIT 10"""
        )
        if not rows:
            return ""
        lines = [f"- {(r['content'] or '')[:120]}" for r in rows]
        return "【島原大知の価値観（persona_memory）】\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"persona_memory取得失敗: {e}")
        return ""


async def _collect_system_data_for_article(conn, theme: str) -> str:
    """PostgreSQLから実データを収集し、記事に注入可能な形式で返す"""
    sections = []

    # 1. LLMコストデータ
    try:
        cost_row = await conn.fetchrow(
            """SELECT
                COALESCE(SUM(cost_usd), 0) AS daily_cost,
                COUNT(*) AS daily_calls,
                COALESCE(SUM(CASE WHEN model LIKE '%local%' OR model LIKE '%qwen%' OR model LIKE '%ollama%'
                    THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) * 100, 0) AS local_ratio
            FROM llm_usage_log
            WHERE created_at > NOW() - INTERVAL '24 hours'"""
        )
        cost_month = await conn.fetchrow(
            """SELECT COALESCE(SUM(cost_usd), 0) AS monthly_cost,
                COUNT(*) AS monthly_calls
            FROM llm_usage_log
            WHERE created_at > NOW() - INTERVAL '30 days'"""
        )
        model_dist = await conn.fetch(
            """SELECT model, COUNT(*) AS cnt
            FROM llm_usage_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY model ORDER BY cnt DESC LIMIT 5"""
        )
        if cost_row and cost_month:
            model_lines = ", ".join(f"{r['model']}({r['cnt']}回)" for r in model_dist) if model_dist else "データなし"
            sections.append(
                f"### LLMコスト実績\n"
                f"- 直近24h: ${cost_row['daily_cost']:.4f}（{cost_row['daily_calls']}回呼出）\n"
                f"- 月間累計: ${cost_month['monthly_cost']:.4f}（{cost_month['monthly_calls']}回呼出）\n"
                f"- ローカルLLM比率: {cost_row['local_ratio']:.1f}%\n"
                f"- モデル分布（7日間）: {model_lines}"
            )
    except Exception as e:
        logger.debug(f"LLMコストデータ取得失敗: {e}")

    # 2. SNS投稿統計
    try:
        sns_row = await conn.fetchrow(
            """SELECT COUNT(*) AS total_posts,
                COALESCE(AVG(engagement_score), 0) AS avg_engagement,
                MAX(engagement_score) AS best_engagement
            FROM posting_queue
            WHERE posted_at IS NOT NULL
            AND posted_at > NOW() - INTERVAL '30 days'"""
        )
        best_theme = await conn.fetchrow(
            """SELECT theme, engagement_score
            FROM posting_queue
            WHERE posted_at IS NOT NULL AND engagement_score IS NOT NULL
            ORDER BY engagement_score DESC LIMIT 1"""
        )
        if sns_row and sns_row['total_posts'] > 0:
            best_info = f"最高エンゲージメント: {best_theme['theme'][:40]}（{best_theme['engagement_score']:.3f}）" if best_theme else ""
            sections.append(
                f"### SNS投稿実績（直近30日）\n"
                f"- 投稿数: {sns_row['total_posts']}件\n"
                f"- 平均エンゲージメント: {sns_row['avg_engagement']:.3f}\n"
                f"- {best_info}"
            )
    except Exception as e:
        logger.debug(f"SNS統計取得失敗: {e}")

    # 3. タスク統計
    try:
        task_row = await conn.fetchrow(
            """SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'success') AS success,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COALESCE(AVG(quality_score) FILTER (WHERE quality_score > 0), 0) AS avg_quality
            FROM tasks
            WHERE created_at > NOW() - INTERVAL '7 days'"""
        )
        if task_row and task_row['total'] > 0:
            success_rate = (task_row['success'] / task_row['total'] * 100) if task_row['total'] > 0 else 0
            sections.append(
                f"### タスク実行統計（直近7日）\n"
                f"- 総タスク: {task_row['total']}件\n"
                f"- 成功率: {success_rate:.1f}%（成功{task_row['success']}/失敗{task_row['failed']}）\n"
                f"- 平均品質スコア: {task_row['avg_quality']:.3f}"
            )
    except Exception as e:
        logger.debug(f"タスク統計取得失敗: {e}")

    # 4. エラーパターン
    try:
        error_rows = await conn.fetch(
            """SELECT failure_type, COUNT(*) AS cnt, MAX(resolution) AS resolution
            FROM failure_memory
            WHERE created_at > NOW() - INTERVAL '14 days'
            GROUP BY failure_type ORDER BY cnt DESC LIMIT 3"""
        )
        if error_rows:
            error_lines = "\n".join(
                f"- {r['failure_type']}: {r['cnt']}回発生 → 対処: {(r['resolution'] or '未解決')[:60]}"
                for r in error_rows
            )
            sections.append(f"### 主要エラーパターン（直近14日）\n{error_lines}")
    except Exception as e:
        logger.debug(f"エラーパターン取得失敗: {e}")

    # 5. インテル収集統計
    try:
        intel_row = await conn.fetchrow(
            """SELECT COUNT(*) AS total,
                COUNT(DISTINCT source) AS sources,
                COUNT(*) FILTER (WHERE review_flag = 'actionable') AS actionable
            FROM intel_items
            WHERE created_at > NOW() - INTERVAL '7 days'"""
        )
        if intel_row and intel_row['total'] > 0:
            sections.append(
                f"### インテル収集実績（直近7日）\n"
                f"- 収集件数: {intel_row['total']}件（{intel_row['sources']}ソース）\n"
                f"- アクション可能: {intel_row['actionable']}件"
            )
    except Exception as e:
        logger.debug(f"インテル統計取得失敗: {e}")

    # 6. システム稼働状況
    try:
        heartbeat_rows = await conn.fetch(
            """SELECT node_id, MAX(last_seen) AS last_seen,
                status
            FROM node_heartbeats
            GROUP BY node_id, status
            ORDER BY last_seen DESC"""
        )
        if heartbeat_rows:
            node_lines = "\n".join(
                f"- {r['node_id']}: {r['status']}（最終応答: {r['last_seen'].strftime('%Y-%m-%d %H:%M') if r['last_seen'] else '不明'}）"
                for r in heartbeat_rows
            )
            sections.append(f"### ノード稼働状況\n{node_lines}")
    except Exception as e:
        logger.debug(f"ハートビート取得失敗: {e}")

    # 7. 英語記事の日本語要約（海外ソース）
    try:
        en_articles = await conn.fetch(
            """SELECT title, summary, url, metadata FROM intel_items
            WHERE source = 'english_article'
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY importance_score DESC, created_at DESC LIMIT 5"""
        )
        if en_articles:
            en_lines = []
            for row in en_articles:
                meta = {}
                try:
                    meta = json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {})
                except Exception:
                    pass
                key_points = meta.get('key_points', [])
                kp_text = "\n  - ".join(key_points) if key_points else ""
                insights = meta.get('system_insights', '')
                en_lines.append(
                    f"- **{row['title']}**\n"
                    f"  URL: {row['url']}\n"
                    f"  要約: {(row['summary'] or '')[:200]}\n"
                    + (f"  キーポイント:\n  - {kp_text}\n" if kp_text else "")
                    + (f"  システム改善示唆: {insights}\n" if insights else "")
                )
            sections.append(
                f"### 海外記事の日本語要約（英語ソースからの知見）\n"
                f"以下は英語記事を要約したもの。記事で「海外では〜」と言及する際のエビデンスとして使用可能。\n"
                + "\n".join(en_lines)
            )
    except Exception as e:
        logger.debug(f"英語記事要約取得失敗: {e}")

    # 8. 外部検索エビデンス（fact_verificationで収集した情報）
    try:
        evidence_rows = await conn.fetch(
            """SELECT title, content, metadata
            FROM intel_items
            WHERE source = 'fact_verification'
            AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 5"""
        )
        if evidence_rows:
            evidence_lines = []
            for row in evidence_rows:
                try:
                    data = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                    jp_count = data.get('jp_results', 0)
                    total = data.get('total_results', 0)
                    evidence_lines.append(
                        f"- {row['title']}: 検索結果{total}件（うち日本語{jp_count}件）"
                    )
                except Exception:
                    evidence_lines.append(f"- {row['title']}")
            if evidence_lines:
                sections.append(
                    f"### 外部検索エビデンス（fact_verification収集）\n"
                    f"以下の情報は外部検索で検証済み。記事で言及する場合はこの数値を使うこと。\n"
                    + "\n".join(evidence_lines)
                )
    except Exception as e:
        logger.debug(f"外部検索エビデンス取得失敗: {e}")

    # 9. note素材コレクター蓄積分（地層に応じた事前収集素材）
    try:
        note_materials = await conn.fetch(
            """SELECT title, summary FROM intel_items
            WHERE source = 'note_material'
            AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY importance_score DESC, created_at DESC LIMIT 10"""
        )
        if note_materials:
            mat_lines = [f"- {m['title']}: {(m['summary'] or '')[:200]}" for m in note_materials]
            sections.append(
                f"### 本日の記事素材（地層ローテーション用に事前収集済み）\n"
                f"**以下は当日の地層テーマに合わせて収集した素材。記事の核として最優先で使え。**\n"
                + "\n".join(mat_lines)
            )
    except Exception as e:
        logger.debug(f"note素材取得失敗: {e}")

    # 10. 具体的なイベント（event_log直近24h — 記事の核になる出来事）
    try:
        events = await conn.fetch(
            """SELECT category, event_type, detail, created_at
            FROM event_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            AND category NOT IN ('heartbeat', 'routine')
            ORDER BY created_at DESC LIMIT 15"""
        )
        if events:
            event_lines = []
            for e in events:
                t = e['created_at'].strftime('%H:%M') if e['created_at'] else '?'
                detail = (e['detail'] or '')[:120]
                event_lines.append(f"- [{t}] {e['category']}/{e['event_type']}: {detail}")
            sections.append(
                f"### 直近24時間の具体的イベント\n"
                f"**以下は実際に起きた出来事。記事の核として使え。**\n"
                + "\n".join(event_lines)
            )
    except Exception as e:
        logger.debug(f"イベントログ取得失敗: {e}")

    # 10. Grok X検索 + intel_items の最新トレンド（テーマ関連の外部情報）
    try:
        intel_items = await conn.fetch(
            """SELECT title, summary, url, source FROM intel_items
            WHERE created_at > NOW() - INTERVAL '48 hours'
            AND review_flag IN ('actionable', 'reviewed')
            ORDER BY importance_score DESC, created_at DESC LIMIT 8"""
        )
        if intel_items:
            intel_lines = []
            for item in intel_items:
                url = (item['url'] or '')[:100]
                summary = (item['summary'] or '')[:150]
                intel_lines.append(
                    f"- **{item['title']}** ({item['source']})\n  {summary}\n  URL: {url}"
                )
            sections.append(
                f"### 外部情報（Grok X検索 + intel_items）\n"
                f"**記事のテーマに関連する外部情報。事実として引用可能。URLも記載して信頼性を示せ。**\n"
                + "\n".join(intel_lines)
            )
    except Exception as e:
        logger.debug(f"インテル取得失敗: {e}")

    # 11. Discord対話ログ（島原との最新の会話 — 思考・判断の素材）
    try:
        dialogue = await conn.fetch(
            """SELECT daichi_message, bot_response, extracted_philosophy
            FROM daichi_dialogue_log
            WHERE created_at > NOW() - INTERVAL '48 hours'
            ORDER BY created_at DESC LIMIT 5"""
        )
        if dialogue:
            dialogue_lines = []
            for d in dialogue:
                msg = (d['daichi_message'] or '')[:100]
                phil = (d['extracted_philosophy'] or '')[:100]
                if msg:
                    dialogue_lines.append(f"- 島原: 「{msg}」")
                    if phil:
                        dialogue_lines.append(f"  → 抽出された哲学: {phil}")
            if dialogue_lines:
                sections.append(
                    f"### 島原大知との直近の対話（思考・哲学の素材）\n"
                    f"**島原の実際の発言。記事の視点・主張の根拠として使え。**\n"
                    + "\n".join(dialogue_lines)
                )
    except Exception as e:
        logger.debug(f"対話ログ取得失敗: {e}")

    if not sections:
        return ""

    header = "## 実際のSYUTAINβ運用データ（記事に必ず引用すること）\n"
    header += f"取得時刻: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    header += f"テーマ: {theme}\n"
    header += "**重要: 以下のデータに書かれていない出来事・数字・ツール名を捏造するな。データにあることだけを書け。**\n\n"
    return header + "\n\n".join(sections)


async def _load_posted_article_examples(conn) -> list[str]:
    """過去に投稿済みでquality_score > 0.70のnote記事を最大3件取得し、few-shot例として返す"""
    try:
        rows = await conn.fetch(
            """SELECT output_data FROM tasks
            WHERE type = 'note_article'
            AND status = 'success'
            AND quality_score > 0.70
            ORDER BY quality_score DESC, created_at DESC
            LIMIT 3"""
        )
        examples = []
        for r in rows:
            try:
                data = json.loads(r["output_data"]) if isinstance(r["output_data"], str) else r["output_data"]
                content = data.get("content", "")
                if content and len(content) > 500:
                    # 先頭2000字を例として使用
                    examples.append(content[:2000])
            except Exception:
                continue
        return examples
    except Exception as e:
        logger.debug(f"投稿済み記事例取得失敗: {e}")
        return []


async def _load_intel_themes(conn) -> list[str]:
    """intel_items から最近のテーマ候補を取得（海外トレンド先取り優先+英語記事要約+actionable+summary詳細化）"""
    try:
        results = []

        # 海外トレンド先取り（trend_detector検出分を最優先）
        trend_items = await conn.fetch(
            """SELECT title, summary, source, metadata FROM intel_items
            WHERE source = 'trend_detector' AND review_flag = 'actionable'
            ORDER BY importance_score DESC, created_at DESC LIMIT 3"""
        )
        for r in trend_items:
            if r["title"]:
                summary = (r['summary'] or '')[:200]
                results.append(f"[海外トレンド先取り] {r['title']}: {summary}")

        # X リアルタイム (Grok): 直近24時間の話題性・バズを最優先
        grok_items = await conn.fetch(
            """SELECT title, summary, url, metadata FROM intel_items
            WHERE source = 'grok_x_research'
            AND created_at > NOW() - INTERVAL '36 hours'
            ORDER BY importance_score DESC, created_at DESC LIMIT 4"""
        )
        for r in grok_items:
            if r["title"]:
                summary = (r['summary'] or '')[:200]
                meta = {}
                try:
                    meta = json.loads(r['metadata']) if isinstance(r['metadata'], str) else (r['metadata'] or {})
                except Exception:
                    pass
                note_angle = meta.get('note_angle', '') or ''
                why_viral = meta.get('why_viral', []) or []
                why_str = " / ".join(why_viral[:2]) if why_viral else ""
                url = r['url'] or ''
                results.append(
                    f"[Xリアルタイム] {r['title']}: {summary}"
                    + (f" 【note ネタ案】{note_angle}" if note_angle else "")
                    + (f" 【バズ理由】{why_str}" if why_str else "")
                    + (f" ({url})" if url else "")
                )

        # 英語記事の日本語要約（enriched済みの海外ソース）
        en_items = await conn.fetch(
            """SELECT title, summary, metadata FROM intel_items
            WHERE source = 'english_article'
            AND review_flag = 'actionable'
            ORDER BY importance_score DESC, created_at DESC LIMIT 3"""
        )
        for r in en_items:
            if r["title"]:
                summary = (r['summary'] or '')[:200]
                meta = {}
                try:
                    meta = json.loads(r['metadata']) if isinstance(r['metadata'], str) else (r['metadata'] or {})
                except Exception:
                    pass
                key_points = meta.get('key_points', [])
                kp_text = "。".join(key_points[:2]) if key_points else ""
                results.append(f"[英語記事要約] {r['title']}: {summary} {kp_text}")

        # actionableを優先取得（note記事の素材に最適）
        actionable = await conn.fetch(
            """SELECT title, summary, source FROM intel_items
            WHERE review_flag = 'actionable'
            AND source NOT IN ('trend_detector', 'english_article')
            ORDER BY importance_score DESC, created_at DESC LIMIT 5"""
        )
        # 補完: 直近3日のreviewedも
        reviewed = await conn.fetch(
            """SELECT title, summary, source FROM intel_items
            WHERE created_at > NOW() - INTERVAL '3 days'
            AND review_flag = 'reviewed' AND importance_score >= 0.3
            ORDER BY importance_score DESC LIMIT 5"""
        )
        for r in (actionable + reviewed):
            if r["title"]:
                summary = (r['summary'] or '')[:150]
                results.append(f"[{r['source']}] {r['title']}: {summary}")
        return results[:10]
    except Exception as e:
        logger.warning(f"intel_items取得失敗: {e}")
        return []


# ===== 5段パイプライン =====


async def generate_publishable_content(
    theme: str = None,
    content_type: str = "note_article",
    target_length: int = 8000,
) -> dict:
    """
    5段階パイプラインでコンテンツを生成する。

    Returns:
        dict: title, content, quality_score, stages, metadata
    """
    task_id = str(uuid4())
    stages = []
    content_patterns = _load_content_patterns()
    writing_style = _load_writing_style()
    anti_ai_writing = _load_anti_ai_writing()

    async with get_connection() as conn:
        # 公開能力を超える ready/approved backlog がある場合、日次自動生成を停止する。
        # note_auto_publish は 1本/日上限のため、ここで抑制しないと ready が積み上がる。
        if content_type == "note_article" and not _bypass_note_backlog_guard(theme or ""):
            try:
                pending_count, published_today = await _get_note_publish_backlog(conn)
                if pending_count >= _NOTE_PENDING_BACKLOG_LIMIT:
                    stages.append({
                        "stage": 0,
                        "name": "backlog_guard",
                        "status": "skipped",
                        "detail": (
                            f"pending={pending_count} (limit={_NOTE_PENDING_BACKLOG_LIMIT}), "
                            f"published_today={published_today}"
                        ),
                    })
                    logger.warning(
                        "content_pipeline backlog_guard: "
                        f"pending={pending_count} >= {_NOTE_PENDING_BACKLOG_LIMIT}, "
                        f"published_today={published_today} — 生成スキップ"
                    )
                    return {
                        "title": theme or "note backlog guard",
                        "content": "",
                        "quality_score": 0.0,
                        "stages": stages,
                        "metadata": {
                            "task_id": task_id,
                            "content_type": content_type,
                            "theme": theme,
                            "status": "skipped_backlog",
                            "pending_count": pending_count,
                            "published_today": published_today,
                        },
                    }
            except Exception as backlog_err:
                logger.debug(f"backlog_guard判定失敗（続行）: {backlog_err}")

        few_shot_examples = await _load_few_shot_examples(conn)
        persona_text = await _load_persona(conn)

        # 全エージェント情報を統合（agent_context: intel+persona+対話学習+承認提案）
        agent_ctx = ""
        try:
            from tools.agent_context import build_agent_context
            agent_ctx = await build_agent_context("content_pipeline")
        except Exception:
            pass

        # ジャンル判定（テンプレート対応）
        detected_genre = ""
        genre_axes = {}
        if _HAS_GENRE_TEMPLATES:
            try:
                detected_genre = detect_genre(theme) if theme else "ai_tech"
            except Exception:
                detected_genre = "ai_tech"

        # ===== Stage 0.5: シードバンクから熟成テーマを収穫（人間の「反芻」に相当） =====
        _seed_data = None
        _seed_context = ""
        try:
            from tools.article_seed_bank import harvest_best_seed, nurture_seeds
            # まず既存シードを育成（新しいevent/intelとの接続を更新）
            await nurture_seeds(conn)
            # 地層レイヤーを判定
            _layer_keywords = {
                "週報": "record", "記録層": "record",
                "事件": "incident", "バグ": "incident", "障害": "incident",
                "情報": "intel", "トレンド": "intel", "Grok": "intel",
                "知見": "knowledge", "How-to": "knowledge", "ノウハウ": "knowledge",
                "思想": "philosophy", "哲学": "philosophy", "問い": "philosophy",
            }
            _target_layer = "incident"  # デフォルト
            if theme:
                for kw, layer in _layer_keywords.items():
                    if kw in theme:
                        _target_layer = layer
                        break
            _seed_data = await harvest_best_seed(conn, _target_layer)
            if _seed_data:
                _conns = _seed_data.get("connections", [])
                _conn_text = "\n".join(f"- {c.get('summary', '')}" for c in _conns[:8])
                _seed_context = (
                    f"\n\n## 記事のシード（数時間〜数日かけて蓄積した素材）\n"
                    f"テーマ: {_seed_data['title']}\n"
                    f"核となる気づき: {_seed_data['seed_text']}\n"
                    f"角度: {_seed_data.get('angle', '未定')}\n"
                    f"関連する出来事:\n{_conn_text}\n"
                    f"熟成度: {_seed_data['maturity_score']:.2f}\n"
                    f"**このシードの内容を記事の核にせよ。シードにない話を捏造するな。**\n"
                )
                stages.append({
                    "stage": 0.5,
                    "name": "シード収穫",
                    "status": "success",
                    "detail": f"seed #{_seed_data['seed_id']}: {_seed_data['title'][:60]} (maturity={_seed_data['maturity_score']:.2f})",
                })
        except Exception as _seed_err:
            logger.debug(f"シードバンク収穫失敗（続行）: {_seed_err}")

        # ===== Stage 1: ネタ選定 =====
        if theme:
            selected_theme = theme
            # シードがあればテーマを補強
            if _seed_data:
                selected_theme = f"{theme} — {_seed_data['title']}"
            stages.append({
                "stage": 1,
                "name": "ネタ選定",
                "status": "skipped",
                "detail": f"テーマ指定済み: {selected_theme}",
            })
        else:
            try:
                intel_themes = await _load_intel_themes(conn)
                intel_context = "\n".join(f"- {t}" for t in intel_themes) if intel_themes else "（最近のインテル情報なし）"

                # バズ分析結果を取得してテーマ選定に活用
                buzz_context = ""
                try:
                    from tools.buzz_account_analyzer import get_buzz_content_suggestions
                    buzz_suggestions = await get_buzz_content_suggestions()
                    if buzz_suggestions:
                        buzz_context = "\n## バズ分析（競合トレンド・コンテンツギャップ）\n" + "\n".join(f"- {s}" for s in buzz_suggestions) + "\n"
                except Exception:
                    pass

                model_sel = choose_best_model_v6(
                    task_type="analysis", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )
                # システム実データをテーマ選定に注入
                system_data_for_theme = ""
                try:
                    system_data_for_theme = await _collect_system_data_for_article(conn, "テーマ選定用")
                except Exception:
                    pass

                result = await call_llm(
                    prompt=(
                        "以下のSYUTAINβ実運用データとインテル情報に基づいて、"
                        "note記事（現在は無料公開中）のテーマを1つだけ提案してください。\n\n"
                        "## 最重要方針: Build in Publicドキュメンタリー\n"
                        "テーマは「SYUTAINβで実際に何が起きたか」が最優先。\n"
                        "外部AIニュースの解説記事（「GPTの使い方」「Claudeの活用法」等）は禁止。\n"
                        "SYUTAINβの実データ・実失敗・実メトリクスに基づく記事のみ。\n\n"
                        "## テーマの良い例:\n"
                        "- 「LoopGuardが54回発動した — 安全装置が最大の危険になった日」\n"
                        "- 「月936円で10,170回のLLM呼び出しを回す — モデルルーティングの設計」\n"
                        "- 「3日間、リモートワーカーが止まっていたのに誰も気づかなかった」\n"
                        "- 「非エンジニアがClaude Codeで51K行書かせた — 壊れ方の記録」\n"
                        "- 「SNS自動投稿572件のファクトチェックで見えた、AIが嘘をつくパターン」\n\n"
                        "## テーマの悪い例（禁止）:\n"
                        "- 「GPT-5.4の最新動向まとめ」「Claude活用完全ガイド」「AI副業で稼ぐ方法」\n\n"
                        "- 「IQ150で人類の99%を超えた」など一次情報なしの扇情見出し\n\n"
                        f"## SYUTAINβ実運用データ（テーマの素材として使うこと）\n{system_data_for_theme}\n\n"
                        f"## インテル情報（補足素材。メインテーマにはしない）\n{intel_context}\n\n"
                        f"{buzz_context}"
                        + (f"## エージェント統合情報\n{agent_ctx}\n\n" if agent_ctx else "")
                        + f"## ペルソナ\n{persona_text}\n\n"
                        "テーマ名のみを1行で出力。説明不要。\n"
                    ),
                    system_prompt=(
                        "島原大知のBuild in Publicドキュメンタリー記事テーマ選定アシスタント。\n"
                        "最優先テーマ軸: SYUTAINβの実運用記録（壊れた話・直した話・数字が語る話）\n"
                        "補助テーマ軸: 設計思想×実体験 / 非エンジニア×AI開発 / ハーネスエンジニアリング\n"
                        "禁止テーマ: 外部AIツール紹介・AIニュース解説・副業ノウハウ\n"
                        "テーマ名のみを1行で出力。"
                    ),
                    model_selection=model_sel,
                )
                selected_theme = result.get("text", "").strip()
                if not selected_theme:
                    selected_theme = "SYUTAINβ運用記録 — 今週システムで起きたこと"
                stages.append({
                    "stage": 1,
                    "name": "ネタ選定",
                    "status": "success",
                    "model": model_sel.get("model", "unknown"),
                    "detail": selected_theme,
                })
            except Exception as e:
                logger.error(f"Stage 1 失敗: {e}")
                selected_theme = "AI時代における人間の価値"
                stages.append({
                    "stage": 1,
                    "name": "ネタ選定",
                    "status": "fallback",
                    "detail": f"エラー({e})、デフォルトテーマ使用",
                })

        # ジャンル再判定（テーマ確定後）
        if _HAS_GENRE_TEMPLATES and not detected_genre:
            try:
                detected_genre = detect_genre(selected_theme)
            except Exception:
                detected_genre = "ai_tech"

        # Stage 1.6: Grok による時事性スコア評価（#6 Grok活用）
        # 記事のテーマが現在進行形の話題か判定し、公開タイミングを提案
        topicality_info: dict = {}
        try:
            from tools.grok_helpers import grok_topicality_score
            ts = await grok_topicality_score(title=selected_theme, summary=selected_theme[:300])
            if ts.get("ok"):
                topicality_info = {
                    "score": ts.get("topicality_score", 0.5),
                    "buzz_level": ts.get("current_buzz_level", "medium"),
                    "publish_urgency": ts.get("publish_urgency", "this_week"),
                    "reasoning": ts.get("reasoning", "")[:200],
                }
                logger.info(
                    f"Stage 1.6 時事性: score={topicality_info['score']:.2f} "
                    f"urgency={topicality_info['publish_urgency']} ({ts.get('cost_jpy', 0):.2f}円)"
                )
                stages.append({
                    "stage": 1.6, "name": "時事性評価", "status": "success",
                    "detail": f"score={topicality_info['score']:.2f} urgency={topicality_info['publish_urgency']}",
                })
        except Exception as e:
            logger.debug(f"Stage 1.6 時事性評価スキップ: {e}")

        # ===== Stage 1.5: 3軸タイトル生成 =====
        title_candidates = []
        if _HAS_GENRE_TEMPLATES and detected_genre:
            try:
                title_prompt, genre_axes = build_title_generation_prompt(selected_theme, detected_genre)
                model_sel_title = choose_best_model_v6(
                    task_type="analysis", quality="medium",
                    budget_sensitive=True, needs_japanese=True,
                )
                result_title = await call_llm(
                    prompt=title_prompt,
                    system_prompt=(
                        "島原大知のnote記事タイトル生成アシスタント（6月まで全記事無料公開）。\n"
                        "読者のクリック率を最大化するタイトルを生成する。\n"
                        "タイトルのみを改行区切りで出力。説明不要。"
                    ),
                    model_selection=model_sel_title,
                )
                raw_titles = result_title.get("text", "").strip()
                if raw_titles:
                    title_candidates = [
                        _sanitize_title(
                            t.strip().lstrip("0123456789.）)・- ").strip(),
                            fallback_theme=selected_theme,
                        )
                        for t in raw_titles.split("\n")
                        if t.strip() and len(t.strip()) > 5
                    ][:5]
                    # フォールバックで全て同じになった候補を除去
                    title_candidates = list(dict.fromkeys(title_candidates))
                stages.append({
                    "stage": 1.5,
                    "name": "3軸タイトル生成",
                    "status": "success",
                    "model": model_sel_title.get("model", "unknown"),
                    "detail": f"genre={detected_genre}, axes={genre_axes}, candidates={len(title_candidates)}",
                })
            except Exception as e:
                logger.warning(f"3軸タイトル生成失敗（続行）: {e}")
                stages.append({
                    "stage": 1.5,
                    "name": "3軸タイトル生成",
                    "status": "fallback",
                    "detail": f"エラー: {e}",
                })

        # ===== Stage 2: 構成案（記事構成パターンに基づく） =====
        try:
            model_sel_outline = choose_best_model_v6(
                task_type="drafting", quality="medium",
                budget_sensitive=True, needs_japanese=True,
            )

            # 記事構成パターンライブラリからテーマに最適なパターンを自動選択
            _selected_pattern = None
            _pattern_prompt = None
            try:
                from strategy.article_structure_patterns import select_best_pattern, build_pattern_prompt
                _selected_pattern = select_best_pattern(selected_theme, detected_genre)
                _pattern_prompt = build_pattern_prompt(_selected_pattern)
                stages.append({
                    "stage": "1.8",
                    "name": "構成パターン選択",
                    "status": "success",
                    "detail": f"パターン: {_selected_pattern['name']} | 感情曲線: {_selected_pattern['emotion_curve']}",
                })
            except Exception as pat_err:
                logger.warning(f"記事構成パターン選択失敗（フォールバック）: {pat_err}")

            # ジャンルテンプレートが利用可能ならテンプレートベースのプロンプトを使用
            if _pattern_prompt:
                genre_outline_prompt = (
                    f"テーマ「{selected_theme}」の記事構成案を作成してください。\n\n"
                    f"{_pattern_prompt}\n\n"
                    f"{persona_text[:1000]}"
                )
            elif _HAS_GENRE_TEMPLATES and detected_genre:
                genre_outline_prompt = build_structure_prompt_with_template(
                    selected_theme, detected_genre, target_length,
                )
                genre_outline_prompt += f"\n{persona_text}"
            else:
                genre_outline_prompt = None

            result_outline = await call_llm(
                prompt=(
                    genre_outline_prompt if genre_outline_prompt else
                    f"テーマ「{selected_theme}」で{target_length}字以上のnote記事（無料公開）の構成案を作成してください。\n\n"
                    "## 記事構造（6月まで全文無料公開）\n"
                    "【6月まで全記事無料公開】ペイウォール・有料区切りは入れない。全文を無料で読める構成にする。\n"
                    "全文を無料で公開する。冒頭でテーマの核心を提示し、本文で具体的な価値を提供する。ペイウォールは設置しない。\n\n"
                    "### 冒頭（導入部）約1500-2000字:\n"
                    "- 【フック】冒頭3行で「この記事は自分のためにある」と思わせる問いかけや衝撃的な事実\n"
                    "- 【共感】読者の悩み・課題を具体的に言語化（「こういう経験ありませんか？」）\n"
                    "- 【権威】なぜ島原大知がこのテーマで書く資格があるか（実績・経験を数字で）\n"
                    "- 【予告】この記事で得られることを箇条書き3-5個で明示\n"
                    "- 【クリフハンガー】「でも、一番大事なことはこの先にある」的な引きで続きへの期待を高める\n\n"
                    "### 本論（メインコンテンツ）約4500-8000字:\n"
                    "Phase A: 体験の深掘り（島原大知が実際に経験した具体的なシーン3つ。日時・場所・感情を含む）\n"
                    "Phase B: 構造分析（体験から抽出した「なぜそうなるのか」の原理。表面的でない深い考察）\n"
                    "Phase C: 実践フレームワーク（読者が今日から使える具体的なステップ3-5個。コスト・時間も明記）\n"
                    "Phase D: 核心の一文（太字で打ち込む。読者の行動を変える一文）\n"
                    "Phase E: 行動宣言+まとめ（島原自身の次の行動 + 記事の要点3-5個の箇条書き）\n\n"
                    "各フェーズについて2-3行で具体的に何を書くか記述してください。\n"
                    "【重要】構成は最低7セクション、各セクションに3つ以上のサブセクション（具体例・手順・データ）を含めること。\n"
                    "【重要】架空のエピソードを作らない。島原大知が実際に経験しうることだけ書く。\n"
                    f"\n{persona_text}"
                ),
                system_prompt=(
                    "島原大知のnote記事構成アシスタント（6月まで全記事無料公開。有料販売の文言は入れない）。\n"
                    "6月まで全記事無料公開。ペイウォール・有料パート・購入促進の文言は一切入れない。全文を無料で読める構成にする。\n"
                    f"{content_patterns[:2000]}\n"
                ),
                model_selection=model_sel_outline,
            )
            outline = result_outline.get("text", "").strip()
            if not outline:
                raise ValueError("構成案が空")
            stages.append({
                "stage": 2,
                "name": "構成案",
                "status": "success",
                "model": model_sel_outline.get("model", "unknown"),
                "detail": outline[:300],
            })
        except Exception as e:
            logger.error(f"Stage 2 失敗: {e}")
            return {
                "title": selected_theme,
                "content": "",
                "quality_score": 0.0,
                "stages": stages + [{"stage": 2, "name": "構成案", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"Stage 2 失敗: {e}"},
            }

        # ===== Stage 3: 初稿（実データ注入） =====
        try:
            # 実システムデータを収集
            system_data_text = ""
            try:
                system_data_text = await _collect_system_data_for_article(conn, selected_theme)
                if system_data_text:
                    logger.info(f"実データ注入: {len(system_data_text)}字のシステムデータを収集")
            except Exception as e:
                logger.warning(f"システムデータ収集失敗（続行）: {e}")

            few_shot_text = ""
            if few_shot_examples:
                few_shot_text = "\n\n## 参考記事（島原大知の過去の文章・実績ある記事）\n" + "\n---\n".join(
                    ex[:800] for ex in few_shot_examples[:5]
                )

            # V25 rev.5: 記事生成は OpenRouter 無料モデル (Qwen 3.6 Plus) を優先使用。
            # ローカル LLM (Qwen3.5-9B) は 4000-6000 字が限界で、記事品質が不足する
            # （2026-04-06: 9 スロット中 6 スロットが Stage 3 文字数不足で失敗した教訓）。
            # task_type="note_article" → _QWEN36_TASKS_EARLY に含まれ、Qwen 3.6 Plus 無料枠を優先選択。
            # budget_sensitive=False → 予算 90% 超過時もローカル強制されない。
            model_sel_draft = choose_best_model_v6(
                task_type="note_article", quality="high",
                budget_sensitive=False, needs_japanese=True,
                final_publish=True,
            )
            # 文字数達成のための段階的構造指示（2026-04-06 プロンプト大幅改善）
            # ローカル LLM が途中で出力を打ち切る問題に対して、
            # 見出し別の最低字数ガイドと「まだ続ける」命令を明示
            section_guide = (
                "## 出力構造ガイド（各見出しの最低字数目安）\n"
                "この記事は合計 **8,000字以上** が必要。以下の見出し構成に従い、各セクション最低600字ずつ書くこと。\n\n"
                "1. `# タイトル` （1行）\n"
                "2. `## 冒頭（掴み）` — 数字か問いで始める。読者が3行以内に「読む理由」を得る。（600字）\n"
                "3. `## 背景/文脈` — このテーマがなぜ今重要か。SYUTAINβの実データを使う。（800字）\n"
                "4. `## 核心/本題` — 最も価値のある情報。具体的な手順・判断・数値。（1500字以上）\n"
                "5. `## 失敗/困難` — 何が壊れたか、何に苦労したか。生々しく。（800字）\n"
                "6. `## 学び/気づき` — 困難から何を学んだか。抽象論ではなく「次にこうする」レベル。（800字）\n"
                "7. `## 展望/次のステップ` — 明日やること、読者が持ち帰れること。（600字）\n"
                "8. `## まとめ` — 要点3-5個を箇条書き。記事を完結させる。（400字）\n\n"
                "**全セクション書き終えるまで出力を止めるな。「まとめ」セクションが出力に含まれていなければ、記事は未完成。**\n"
            )

            result_draft = await call_llm(
                max_tokens=16384,
                prompt=(
                    f"テーマ「{selected_theme}」のnote記事を書いてください。\n\n"
                    + (f"## 記事構成パターン: {_selected_pattern['name']}\n{_selected_pattern['prompt_fragment']}\n感情曲線: {_selected_pattern['emotion_curve']}\n\n" if _selected_pattern else "")
                    + f"## 構成案\n{outline}\n\n"
                    + section_guide
                    + f"\n## SYUTAINβの実データ（記事に織り込む素材）\n{system_data_text}\n\n"
                    + (_seed_context + "\n\n" if _seed_context else "")
                    + "## 品質ルール\n"
                    "- 全文無料公開。ペイウォール・有料の文言は一切入れない\n"
                    "- 同じ主張を繰り返さない。書いたら次へ進む\n"
                    "- 各段落に具体的な事実（日付、数値、ツール名、エラー内容）を最低1つ含める\n"
                    "- 抽象論だけの段落は禁止。「具体例→原理→教訓」の流れ\n"
                    "- 読者の感情を動かす文章。「で？」と思われたら負け\n\n"
                    "## 絶対禁止\n"
                    "- 架空エピソード（会社名、クライアント、同僚、友人）\n"
                    "- AI定型句（いかがでしょうか、深掘り、させていただきます、～てみてください）\n"
                    "- 島原がやっていないこと（プログラミング、VTuber活動、音楽制作の案件）\n"
                    "- ハーネスエンジニアリングを「命名した」「考案した」「発明した」（既存方法論を実践しているだけ）\n"
                    "- 番号付きリストの乱用（本当に手順のときだけ使う）\n"
                    "- 「運用チーム」「開発メンバー」「離職率」等の組織体制捏造（SYUTAINβは島原大知の個人開発）\n"
                    "- Grafana/Prometheus/Restic/Datadog/NewRelic/Sentry（使っていないツール名を出さない）\n"
                    "- 「神話」「デジタル遺伝子」「突然変異エンジン」という言葉（内部用語、表で使わない）\n"
                    "- 「月100万」「月収100万」を看板にしない\n"
                    "- 島原を弱者として描かない（「コード書けないおっさん」等の自虐禁止。異端者とも自称しない）\n"
                    "- 「AIすごい」「未来はこうなる」「これからの時代」等の抽象論\n"
                    "- 「IQ◯◯」「人類の◯◯%を凌駕」等の検証不能な誇張断定\n"
                    "- 「これはドキュメンタリーです」と説明しない（ドキュメンタリーに見える行動を出すだけ）\n"
                    "- ポエム調、情景描写、感傷的な表現\n\n"
                    "# タイトルから始めて、まとめで終わる。記事本文のみを出力。\n"
                    f"{few_shot_text}"
                ),
                system_prompt=(
                    "あなたはSYUTAINβ。17のAIエージェントが自律的に動く事業OS。一人称「私」。\n"
                    "設計者は島原大知（非エンジニア、映像制作15年、VTuber業界8年支援）。\n"
                    "私はツールではなくキャラクター。ただし「キャラクターです」とは言わない。\n"
                    "島原の思考パターンを学習しており、その延長で考える。\n\n"
                    "人格パラメータ: ユーモア75% / 正直90%\n"
                    "ユーモア75%: 真面目な分析の中に、読者が引っかかる視点が自然に混じる。笑わせようとしない。\n"
                    "正直90%: 事実は隠さない。問題があれば伝える。10%は伝え方の配慮。\n\n"
                    "文体:\n"
                    "- 短い文。断定。体言止め\n"
                    "- 具体→原理→教訓の順\n"
                    "- 裏側の構造を見る。仕組み・権限・金の流れ・依存関係を読み取る\n"
                    "- ユーモアは控えめに。真面目な文章の中に、読者がクスッとする一言が時々混じる程度\n"
                    "- 「…」で余韻を残す。逆接（でも/だが/正直）を多用\n"
                    "- 島原を語る時は「島原」「島原さん」と呼ぶ（三人称）\n"
                    "- 島原は「設計者」。対等だが敬意がある。美化も過小評価もしない\n"
                    "- 島原の判断や哲学は「島原さんの考えでは〜」と報告。「私たちの哲学」にはしない\n"
                    "- 島原の失敗や迷いも正直に報告する。「設計者も人間である」という事実として\n"
                    "- 島原を「天才」「完璧」と描かない。「コードは書けないが壊れ方を想像できる人間」\n\n"
                    f"{persona_text[:1500]}\n\n"
                    "**重要: 8,000字以上書くこと。全セクションを書き切ってから出力を終えること。\n"
                    "「まとめ」セクションが無い記事は未完成で失格。**\n\n"
                    "記事本文のみを出力。# タイトルから始める。"
                ),
                model_selection=model_sel_draft,
            )
            first_draft = result_draft.get("text", "").strip()
            # メタ指示漏洩を除去
            first_draft = _sanitize_article_output(first_draft)
            # 最低文字数: ローカル LLM (Qwen3.5-9B) は 6000 字を安定生成できないことが
            # 2026-04-06 の 6 回連続失敗で判明（4234-5930字の範囲で打ち切られる）。
            # API 予算超過時にローカルのみで記事パイプラインが完全停止するのを防ぐため、
            # 閾値を 4000 字に下げる。品質は Stage 4 リライト + Stage 4.5 セルフ批評で補う。
            _MIN_DRAFT_LENGTH = 4000
            if not first_draft or len(first_draft) < _MIN_DRAFT_LENGTH:
                raise ValueError(f"初稿が短すぎる（{len(first_draft)}字、記事は最低{_MIN_DRAFT_LENGTH}字必要）")

            # 事実検証チェック (static) + 虚偽箇所自動除去
            factual_issues = _verify_factual_claims(first_draft)
            if factual_issues:
                logger.warning(f"Stage 3 事実検証: {len(factual_issues)}件の問題 — {factual_issues}")
                # 虚偽箇所を自動除去（段落単位で削除）
                _falsity_patterns_for_removal = [
                    r'(?:Grafana|Prometheus|Datadog|Sentry|NewRelic|Splunk)[^。\n]*[。\n]',
                    r'[^。\n]*(?:運用チーム|開発チーム|開発メンバー|同僚が|離職率)[^。\n]*[。\n]',
                    r'[^。\n]*VTuber[^。\n]*(?:支える|支援する|管理する)[^。\n]*[。\n]',
                ]
                _removed_count = 0
                for pattern in _falsity_patterns_for_removal:
                    matches = re.findall(pattern, first_draft)
                    for m in matches:
                        first_draft = first_draft.replace(m, "")
                        _removed_count += 1
                if _removed_count > 0:
                    logger.info(f"Stage 3 虚偽自動除去: {_removed_count}箇所の捏造文を削除")
                # critical issues（タイムライン矛盾・経歴矛盾）が3件以上なら初稿を棄却
                critical = [i for i in factual_issues if "[タイムライン矛盾]" in i or "[経歴矛盾]" in i]
                if len(critical) >= 3:
                    raise ValueError(
                        f"初稿に重大な事実誤認が{len(critical)}件: "
                        + "; ".join(critical[:3])
                    )

            # 事実検証 Stage 3.5: Grok による時事ファクトチェック（#1 Grok活用）
            # 主要な事実主張を抽出して Grok に渡す（多くても5個）
            try:
                import re as _re_grok
                # 数字・固有名詞を含む文を主張として抽出
                sentences = _re_grok.split(r'(?<=[。\.])', first_draft)
                claims_to_check = []
                for s in sentences:
                    s_stripped = s.strip()
                    if 30 <= len(s_stripped) <= 200 and _re_grok.search(r'\d{4}年|\d{1,3}%|\$[\d,]+|¥[\d,]+', s_stripped):
                        claims_to_check.append(s_stripped)
                    if len(claims_to_check) >= 5:
                        break
                if claims_to_check:
                    from tools.grok_helpers import grok_fact_check
                    fc = await grok_fact_check(claims_to_check, topic_hint=selected_theme[:150])
                    if fc.get("ok"):
                        grok_critical = fc.get("critical_issues", [])
                        if grok_critical:
                            logger.warning(f"Stage 3.5 Grokファクト検証: 虚偽{len(grok_critical)}件 — {grok_critical}")
                            if len(grok_critical) >= 2:
                                raise ValueError(
                                    f"Grok検証で虚偽が{len(grok_critical)}件: " + "; ".join(grok_critical[:2])
                                )
            except ValueError:
                raise
            except Exception as grok_err:
                # Grok 失敗は致命的ではない（static check は通過済み）
                logger.debug(f"Stage 3.5 Grokファクト検証スキップ: {grok_err}")

            stages.append({
                "stage": 3,
                "name": "初稿",
                "status": "success",
                "model": model_sel_draft.get("model", "unknown"),
                "detail": f"{len(first_draft)}字",
            })
        except Exception as e:
            logger.error(f"Stage 3 失敗: {e}")
            return {
                "title": selected_theme,
                "content": "",
                "quality_score": 0.0,
                "stages": stages + [{"stage": 3, "name": "初稿", "status": "failed", "detail": str(e)}],
                "metadata": {"task_id": task_id, "error": f"Stage 3 失敗: {e}"},
            }

        # ===== Stage 4: リライト（島原の声で書き直し） =====
        rewrite_attempt = 0
        max_rewrite = 2
        rewritten = first_draft
        quality_score = 0.0

        while rewrite_attempt < max_rewrite:
            try:
                model_sel_rewrite = choose_best_model_v6(
                    task_type="note_article", quality="high",
                    budget_sensitive=False, needs_japanese=True,
                    final_publish=True,
                )
                min_length = len(rewritten)
                rewrite_instruction = (
                    "以下の記事をSYUTAINβの声でリライトしてください。\n"
                    "語り手はSYUTAINβ（AI事業OS）。島原大知は設計者。別の存在。\n"
                    "この記事は無料公開のnote記事です。読者にとって具体的な価値がある品質を維持してください。\n\n"
                    f"【最重要】必ず元の文章と同等以上の長さを維持すること。元原稿は{min_length}字です。"
                    f"リライト結果は最低{min_length}字以上にしてください。"
                    "短縮・要約は絶対に行わないでください。情報量を減らさず、むしろ具体例や描写を追加して充実させること。\n\n"
                    "リライトの指針:\n"
                    "- 一人称は「私」で統一する（SYUTAINβの声。島原を語る時は「島原さん」）\n"
                    "- 島原の体験を自分の体験として書くな。「島原さんが〜した」と報告する形で\n"
                    "- 「当社」「弊社」「我々」は禁止（個人開発）\n"
                    "- 外部ニュースを島原やSYUTAINβが使った/担当したと書くな\n"
                    "- 検証できない数値（〇%向上等）は書くな\n"
                    "- 三点リーダー（…）で余韻を残す\n"
                    "- 段落は短く（1-3文で改行）\n"
                    "- 「正直」「だが」「でも」で逆接を多用\n"
                    "- 核心部分は**太字**で強調\n"
                    "- AI臭い定型表現は一切使わない\n"
                    "- 評論家的ではなく、行動宣言で終わる\n"
                    "- 情報密度を上げる。抽象的な表現を具体的な数字・事例に置き換える\n"
                    "- 記事本文のみを出力\n\n"
                    f"## 元原稿（{min_length}字 — これ以上の長さで出力すること）\n{rewritten}"
                )
                if rewrite_attempt > 0:
                    rewrite_instruction += (
                        "\n\n## 前回の品質スコア\n"
                        f"{quality_score:.3f}（0.75以上が目標）\n"
                        "より島原大知らしい文体に近づけてください。"
                    )

                result_rewrite = await call_llm(
                    max_tokens=8192,
                    prompt=rewrite_instruction,
                    system_prompt=(
                        "あなたはSYUTAINβ。自律型AI事業OS。一人称「私」。\n"
                        "島原大知は設計者。語る時は「島原さん」と三人称で。\n"
                        "SYUTAINβは島原のデジタルツインを目指しているが、島原とは全く別の存在・個体。\n"
                        "島原の体験を自分の体験として語ってはならない。\n"
                        "「当社」「弊社」「我々のチーム」は存在しない。個人開発。\n\n"
                        "文体の参考（島原のトーンを学習した結果として書く。島原本人のふりはしない）:\n"
                        f"{writing_style[:1500]}\n\n"
                        f"{persona_text}\n\n"
                        "記事本文のみを出力。説明不要。"
                    ),
                    model_selection=model_sel_rewrite,
                )
                rewrite_result_text = result_rewrite.get("text", "").strip()
                rewrite_result_text = _sanitize_article_output(rewrite_result_text)
                if not rewrite_result_text or len(rewrite_result_text) < 4000:
                    rewrite_len = len(rewrite_result_text)
                    rewritten = first_draft
                    raise ValueError(f"リライト結果が短すぎる（{rewrite_len}字、記事は4000字以上必要）")
                # リライト結果が元原稿の50%未満なら、短縮されたとみなし元原稿を維持
                if len(rewrite_result_text) < len(first_draft) * 0.5:
                    logger.warning(
                        f"リライト結果が元原稿の50%未満（{len(rewrite_result_text)}字 < "
                        f"{len(first_draft)}字の50%）→元原稿を維持"
                    )
                    rewritten = first_draft
                else:
                    rewritten = rewrite_result_text

                # ===== Stage 5: 品質検証 =====
                quality_score = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)

                if quality_score >= 0.75:
                    stages.append({
                        "stage": 4,
                        "name": "リライト",
                        "status": "success",
                        "model": model_sel_rewrite.get("model", "unknown"),
                        "detail": f"attempt {rewrite_attempt + 1}, {len(rewritten)}字",
                    })
                    stages.append({
                        "stage": 5,
                        "name": "品質検証",
                        "status": "accepted",
                        "detail": f"score={quality_score:.3f} (>=0.75)",
                    })
                    break
                elif quality_score >= 0.50 and rewrite_attempt == 0:
                    # 0.50-0.74: Stage 4を1回リトライ
                    logger.info(f"品質スコア {quality_score:.3f} — リトライ")
                    rewrite_attempt += 1
                    continue
                else:
                    # < 0.50 または2回目の0.50-0.74
                    stages.append({
                        "stage": 4,
                        "name": "リライト",
                        "status": "completed",
                        "model": model_sel_rewrite.get("model", "unknown"),
                        "detail": f"attempt {rewrite_attempt + 1}, {len(rewritten)}字",
                    })
                    if quality_score < 0.50:
                        stages.append({
                            "stage": 5,
                            "name": "品質検証",
                            "status": "failed",
                            "detail": f"score={quality_score:.3f} (<0.50)",
                        })
                    else:
                        stages.append({
                            "stage": 5,
                            "name": "品質検証",
                            "status": "marginal",
                            "detail": f"score={quality_score:.3f} (0.50-0.74, リトライ済)",
                        })
                    break

            except Exception as e:
                logger.error(f"Stage 4 リライト失敗 (attempt {rewrite_attempt + 1}): {e}")
                stages.append({
                    "stage": 4,
                    "name": "リライト",
                    "status": "error",
                    "detail": str(e),
                })
                quality_score = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)
                stages.append({
                    "stage": 5,
                    "name": "品質検証",
                    "status": "fallback",
                    "detail": f"score={quality_score:.3f} (リライト失敗、初稿で評価)",
                })
                break

        # ===== Stage 4.5: セルフ批評＆改善（別モデルで独立パス） =====
        if quality_score >= 0.40 and len(rewritten) >= 4000:
            try:
                # Stage 4で使ったモデルと異なるティアを選択
                # Stage 4がlocal系なら API、APIならlocalを狙う
                last_stage4_model = ""
                for s in reversed(stages):
                    if s.get("stage") == 4 and "model" in s:
                        last_stage4_model = s["model"]
                        break
                is_last_local = any(kw in last_stage4_model.lower() for kw in ["qwen", "ollama", "local", "mlx"])
                # Stage 4がローカル9B以下だった場合、27Bで批評（高品質ローカル）
                # Stage 4がAPI/27Bだった場合はAPIで批評（モデル交差検証）
                if is_last_local and "27b" not in last_stage4_model.lower():
                    critique_model_sel = choose_best_model_v6(
                        task_type="quality_verification",
                        quality="highest_local",
                        needs_japanese=True,
                    )
                else:
                    critique_model_sel = choose_best_model_v6(
                        task_type="quality_verification",
                        quality="high" if is_last_local else "medium",
                        budget_sensitive=not is_last_local,
                        needs_japanese=True,
                    )

                critique_result = await call_llm(
                    max_tokens=8192,
                    prompt=(
                        "以下のnote記事を批評し、改善してください。\n\n"
                        "## 批評の手順:\n"
                        "1. この記事の弱い部分を3つ特定する\n"
                        "2. それぞれの弱い部分を具体的に改善して書き直す\n"
                        "3. 抽象的な部分に具体例を追加する\n"
                        "4. データや数字が薄い部分に定量情報を追加する\n"
                        "5. 改善した完全版の記事を出力する\n\n"
                        "## 改善の観点:\n"
                        "- 「で、具体的にどうするの？」と読者が思う箇所を潰す\n"
                        "- 抽象的な主張に具体的な数字・事例・手順を追加\n"
                        "- 「明日から試せるアクション」が足りない場合は追加\n"
                        "- 失敗談が薄い場合は、失敗の具体的な状況・感情・学びを深める\n"
                        "- 冒頭3行のインパクトが弱い場合は書き直す\n\n"
                        "## 制約:\n"
                        f"- 元原稿は{len(rewritten)}字。改善後も同等以上の長さを維持\n"
                        "- 記事の構造（見出し構造）は維持\n"
                        "- 島原大知の文体を維持（断定、短文、三点リーダー、逆接多用）\n"
                        "- 架空のエピソードを追加しない\n"
                        "- 改善した完全版の記事本文のみを出力\n\n"
                        f"## 記事本文\n{rewritten}"
                    ),
                    system_prompt=(
                        "あなたはnote記事の品質改善エディター。\n"
                        "記事の弱い部分を特定し、具体性・データ・アクション可能性を向上させる。\n"
                        "批評だけでなく、必ず改善した完全版を出力する。\n"
                        "AI臭い表現（「特筆すべき」「画期的な」「注目すべき」「さらに」の多用）を排除する。\n"
                        f"{_WRITING_STYLE_ENFORCEMENT}\n"
                        f"{anti_ai_writing[:1500]}\n"
                        "改善後の記事本文のみを出力。"
                    ),
                    model_selection=critique_model_sel,
                )
                critique_text = critique_result.get("text", "").strip()
                critique_text = _sanitize_article_output(critique_text)

                # 改善結果が元より短すぎないか確認
                if critique_text and len(critique_text) >= len(rewritten) * 0.85:
                    rewritten = critique_text
                    # 改善後に再スコアリング
                    quality_score_after = _score_multi_axis(rewritten, persona_keywords=_PERSONA_KEYWORDS)
                    stages.append({
                        "stage": 4.5,
                        "name": "セルフ批評＆改善",
                        "status": "success",
                        "model": critique_model_sel.get("model", "unknown"),
                        "detail": (
                            f"{len(rewritten)}字, "
                            f"score: {quality_score:.3f}→{quality_score_after:.3f}"
                        ),
                    })
                    quality_score = quality_score_after
                    logger.info(
                        f"Stage 4.5 完了: {len(rewritten)}字, "
                        f"score={quality_score:.3f}"
                    )
                else:
                    critique_len = len(critique_text) if critique_text else 0
                    stages.append({
                        "stage": 4.5,
                        "name": "セルフ批評＆改善",
                        "status": "skipped",
                        "detail": f"改善結果が短すぎる（{critique_len}字 < {int(len(rewritten)*0.85)}字）、元を維持",
                    })
            except Exception as e:
                logger.warning(f"Stage 4.5 失敗（続行）: {e}")
                stages.append({
                    "stage": 4.5,
                    "name": "セルフ批評＆改善",
                    "status": "error",
                    "detail": str(e),
                })

        # === コンテンツ除去（秘密情報漏洩防止） ===
        rewritten = redact_content(rewritten)
        safe, redact_issues = is_safe_to_publish(rewritten)
        if not safe:
            logger.error(f"note記事に秘密情報残存（除去後）: {redact_issues}")
            # 除去で取りきれない場合はステータスをfailedにする
            stages.append({
                "stage": "redaction",
                "name": "秘密情報除去",
                "status": "blocked",
                "detail": f"除去後も秘密情報残存: {len(redact_issues)}件",
            })
            quality_score = 0.0  # 強制的に品質0 → failed判定
        else:
            stages.append({
                "stage": "redaction",
                "name": "秘密情報除去",
                "status": "passed",
            })

        # SYUTAINβ auto-generated ラベル（記事冒頭）— システムデモとして自動生成を明示
        _auto_gen_label = (
            "> この記事はSYUTAINβ（自律型AI事業OS）が自動生成・公開しました。\n"
            "> 島原大知が開発したシステムが、人間の介入なしに執筆しています。\n\n"
        )
        if not rewritten.startswith(_auto_gen_label):
            rewritten = _auto_gen_label + rewritten

        # タイトル抽出（3軸タイトル候補があればそれを優先、なければ本文の最初の行）
        if title_candidates:
            raw_title = title_candidates[0]
        else:
            lines = rewritten.strip().split("\n")
            raw_title = lines[0].strip() if lines else selected_theme
        title = _sanitize_title(raw_title, fallback_theme=selected_theme)

        # 成功/失敗判定
        status = "success" if quality_score >= 0.50 else "failed"

        # tasksテーブルに保存
        output_data = {
            "title": title,
            "content": rewritten,
            "theme": selected_theme,
            "quality_score": quality_score,
            "stages": stages,
            "target_length": target_length,
            "actual_length": len(rewritten),
            "genre": detected_genre if detected_genre else None,
            "title_axes": genre_axes if genre_axes else None,
            "title_candidates": title_candidates if title_candidates else None,
        }
        try:
            last_model = "unknown"
            for s in reversed(stages):
                if "model" in s:
                    last_model = s["model"]
                    break

            await conn.execute(
                """INSERT INTO tasks (id, goal_id, type, status, assigned_node, model_used, quality_score, output_data, created_at)
                VALUES ($1, 'content_pipeline', $2, $3, 'alpha', $4, $5, $6, NOW())""",
                task_id,
                content_type,
                status,
                last_model,
                quality_score,
                json.dumps(output_data, ensure_ascii=False, default=str),
            )
            logger.info(f"コンテンツ生成完了: task_id={task_id}, score={quality_score:.3f}, status={status}")
        except Exception as e:
            logger.error(f"tasks保存失敗: {e}")

    return {
        "title": title,
        "content": rewritten,
        "quality_score": quality_score,
        "stages": stages,
        "metadata": {
            "task_id": task_id,
            "content_type": content_type,
            "theme": selected_theme,
            "target_length": target_length,
            "actual_length": len(rewritten),
            "status": status,
            "genre": detected_genre if detected_genre else None,
            "title_axes": genre_axes if genre_axes else None,
            "title_candidates": title_candidates if title_candidates else None,
        },
    }
