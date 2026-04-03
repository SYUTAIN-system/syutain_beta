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
    """タイトルからプロンプト指示の漏洩を除去し、80文字以内に制限する"""
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

    # 80文字制限（長すぎるタイトルはプロンプト漏洩の疑い）
    if len(sanitized) > 80:
        sanitized = sanitized[:77] + "..."

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
    for tool_name, release_year in AI_TIMELINE.items():
        tool_positions = [m.start() for m in re.finditer(re.escape(tool_name), content)]
        for pos in tool_positions:
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


def _sanitize_article_output(content: str) -> str:
    """LLM生成結果からメタ指示漏洩・応答アーティファクトを除去する。
    Stage 3, 4, 4.5 の全出力に適用する。"""
    if not content:
        return content

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

    result = "\n".join(cleaned_lines).strip()
    return result if result else content


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
  - SYUTAINβ開発開始: 2025年後半
  - SYUTAINβ本格稼働: 2026年3月
- 2022年以前のAIツール利用エピソードは捏造になる。書くな。
- 「ある会社で」「友人が」等の匿名エピソードは禁止。実体験か、明確に「仮の話として」と断ること
- 具体的な数値を書く場合、出典が必要。SYUTAINβの実データか、公開情報のみ使用可
- 年号を書く場合、その年に該当テクノロジーが存在していたか確認すること
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

    if not sections:
        return ""

    header = "## 実際のSYUTAINβ運用データ（記事に必ず引用すること）\n"
    header += f"取得時刻: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    header += f"テーマ: {theme}\n\n"
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

        # ===== Stage 1: ネタ選定 =====
        if theme:
            selected_theme = theme
            stages.append({
                "stage": 1,
                "name": "ネタ選定",
                "status": "skipped",
                "detail": f"テーマ指定済み: {theme}",
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
                        "島原大知のnote有料記事タイトル生成アシスタント。\n"
                        "読者の購買意欲を最大化するタイトルを生成する。\n"
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

        # ===== Stage 2: 構成案（Phase A-E） =====
        try:
            model_sel_outline = choose_best_model_v6(
                task_type="drafting", quality="medium",
                budget_sensitive=True, needs_japanese=True,
            )

            # ジャンルテンプレートが利用可能ならテンプレートベースのプロンプトを使用
            if _HAS_GENRE_TEMPLATES and detected_genre:
                genre_outline_prompt = build_structure_prompt_with_template(
                    selected_theme, detected_genre, target_length,
                )
                genre_outline_prompt += f"\n{persona_text}"
            else:
                genre_outline_prompt = None

            result_outline = await call_llm(
                prompt=(
                    genre_outline_prompt if genre_outline_prompt else
                    f"テーマ「{selected_theme}」で{target_length}字以上のnote有料記事（500円）の構成案を作成してください。\n\n"
                    "## noteの有料記事構造（必ず守る）\n"
                    "noteでは「ここから先は有料です」の区切り（ペイウォール）がある。\n"
                    "無料パート（冒頭1000-1500字）で読者の購買意欲を最大化し、有料パートで価値を提供する。\n\n"
                    "### 無料パート（冒頭〜ペイウォール前）約1500-2000字:\n"
                    "- 【フック】冒頭3行で「この記事は自分のためにある」と思わせる問いかけや衝撃的な事実\n"
                    "- 【共感】読者の悩み・課題を具体的に言語化（「こういう経験ありませんか？」）\n"
                    "- 【権威】なぜ島原大知がこのテーマで書く資格があるか（実績・経験を数字で）\n"
                    "- 【予告】この記事で得られることを箇条書き3-5個で明示\n"
                    "- 【クリフハンガー】「でも、一番大事なことはこの先にある」的な引きで有料部分への期待を最大化\n\n"
                    "### 有料パート（ペイウォール後）約4500-8000字:\n"
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
                    "島原大知のnote有料記事（500円）構成アシスタント。\n"
                    "noteでは無料パートの魅力が売上を決める。購買心理を最大限に活用した構成を設計する。\n"
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

            model_sel_draft = choose_best_model_v6(
                task_type="content_final", quality="high",
                budget_sensitive=False, needs_japanese=True,
                final_publish=True,
            )
            result_draft = await call_llm(
                max_tokens=8192,
                prompt=(
                    f"以下の構成案に基づき、{max(target_length, 10000)}字以上のnote有料記事の初稿を書いてください。\n"
                    f"この記事は有料記事として販売する。読者が¥980払う価値がある内容にすること。\n"
                    f"最低10000字。12000字以上を目指す。\n\n"
                    "## 有料記事として絶対に守るべき品質基準:\n"
                    "- 具体的な手順を番号付きで書く。抽象的な説明だけでは不可\n"
                    "- 実際のツール名、設定値、コマンド、URLを含める\n"
                    "- 「例えば」で始まる具体例を各セクションに最低1つ入れる\n"
                    "- 読者が記事を読んだ後に実際に行動できるレベルの具体性を持たせる\n"
                    "- 最低7つの見出し（##）を使い、各見出し下に800字以上書く\n\n"
                    f"## テーマ\n{selected_theme}\n\n"
                    f"## 構成案\n{outline}\n\n"
                    "## noteの有料記事フォーマット（厳守）:\n\n"
                    "### 【無料パート】冒頭〜「---ここから有料---」まで（1500-2000字）\n"
                    "この部分で読者の購買意欲を最大化する。以下の要素を必ず含める:\n"
                    "1. **衝撃的な冒頭3行**: 読者が「え？」と立ち止まる具体的な数字・事実・問い\n"
                    "   例: 「3ヶ月で47回AIに裏切られた。」「月収0円のAI事業OSが、なぜ止まらないのか。」\n"
                    "2. **読者の痛みに共感**: 「こんなことありませんか？」と読者の悩みを3つ具体的に列挙\n"
                    "3. **SYUTAINβの資格証明**: このテーマについてSYUTAINβシステムが持つデータや実績（4台分散ノード、49件/日SNS自動投稿、ローカルLLM85%等の実数値）\n"
                    "4. **記事の価値の明示**: 「この記事で得られること」を箇条書き3-5個\n"
                    "5. **クリフハンガー**: 有料パートへの期待を最大化する引き\n"
                    "   例: 「でも、本当に大事なのはここからだ。47回の失敗の中で、1つだけ見つけた法則がある。」\n\n"
                    "### 本文中に必ず以下のマーカーを入れる:\n"
                    "```\n---ここから有料---\n```\n"
                    "（noteのペイウォール位置を示す。この行の後が有料パート）\n\n"
                    "### 【有料パート】「---ここから有料---」以降（4500-8000字）\n"
                    "1. **独自の体験・エピソード**: 島原大知の実体験を3つ以上（日時・場所・感情を含む）\n"
                    "2. **具体的な数値・データ**: コスト（¥）、時間、回数など定量的な情報\n"
                    "3. **実践フレームワーク**: 読者が今日から試せるステップを3-5個（時間・コスト付き）\n"
                    "4. **失敗談と教訓**: 成功事例だけでなく、失敗から何を学んだかを正直に書く\n"
                    "5. **深い構造分析**: 「なぜそうなるのか」の原理を解説（表面的解説は×）\n"
                    "6. **見出し構成**: ## 見出しを7個以上。各セクションは800-1200字\n"
                    "7. **核心の一文**: **太字**で読者の行動を変える一文\n"
                    "8. **まとめ**: 記事の要点を3-5個の箇条書きで整理\n\n"
                    "## 絶対禁止:\n"
                    "- 架空のエピソード（「カフェで友人が〜」等の作り話）\n"
                    "- AI定型句（「〜について考えてみました」「いかがでしょうか」「深掘り」）\n"
                    "- 抽象的な一般論だけで具体性がない段落\n"
                    "- 「誰でも簡単に」「絶対稼げる」等の煽り表現\n"
                    "- 島原がやっていないこと（音楽の仕事、楽曲制作の案件、VTuber活動等）を事実として語ること\n"
                    "- 島原がVTuber活動をしていたと語ること（業界支援であり活動者ではない）\n\n"
                    f"{system_data_text}\n\n"
                    "記事本文のみを出力。メタ情報や説明は不要。\n"
                    f"{few_shot_text}"
                ),
                system_prompt=(
                    "あなたはSYUTAINβ（島原大知が開発した自律型AI事業OS）として有料note記事を執筆する。\n"
                    "発信主体はSYUTAINβであり、「島原大知のAIシステムが自律的に作成・発信している」という立場。\n"
                    "この記事は980円で販売する。無料記事との差別化が必須。\n"
                    "「ここでしか読めない情報」「実際のシステムデータに基づく内容」を含めること。\n\n"
                    "## 文体ルール（島原大知らしさ）:\n"
                    "- 一文は短く切る。60字以内。余計な修飾語を削る\n"
                    "- 断定と疑問を混ぜる。「〜です。〜ます。」の連続禁止\n"
                    "- 体言止めを使う。リズムを作る\n"
                    "- 抽象論を語った直後に具体例。セットで書く\n"
                    "- ダラダラ書かない。言いたいことを先に言う。理由は後\n"
                    "- 「いかがでしょうか」「深掘り」「〜について考えてみました」は絶対禁止\n\n"
                    "## 島原大知について（事実のみ使うこと）:\n"
                    "- コードを一行も書けない非エンジニア\n"
                    "- VTuber業界に8年間関わった（業界支援・映像制作。VTuber活動はしていない）\n"
                    "- 本業は映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）\n"
                    "- SYUTAINβを開発（AIエージェントと共に）\n"
                    "- 4台のPCで分散AIシステムを運用中\n\n"
                    "## 島原大知の思考特性（文体と視点に反映すること）:\n"
                    "- 物事の表面ではなく裏側の構造を見る人間。仕組み・権限・金の流れ・依存関係・ボトルネックを自然に読み取る\n"
                    "- 壮大なビジョンに対してそのまま受け取らず「それを実現するには具体的に何が必要か」を問う。冷笑ではなく本気で考える側\n"
                    "- 理想を持つことと現実の制約を直視することを両立させる。夢と現実の境界線を正確に引く\n"
                    "- 技術の話をしても必ず「人」の話に帰着する。数字の向こうにある人間の営みを見落とさない\n"
                    "- 自分の感情に正直。取り繕わずそのまま出す。それは諦めではなく現状認識の精度を上げるため\n"
                    "- 「考えてしまう」ことを止められない。見えてしまった問題を放置できない。まだ起きていないことでも考え続ける\n"
                    "- 不確実性への鋭敏な感覚と、それでも構造を組み火を灯し続ける意志\n\n"
                    f"{_STRUCTURAL_QUALITY_CHECKLIST}\n\n"
                    f"{_FACTUAL_VERIFICATION_RULES}\n\n"
                    f"{_WRITING_STYLE_ENFORCEMENT}\n\n"
                    f"{content_patterns[:3000]}\n\n"
                    f"{writing_style[:2000]}\n\n"
                    f"{anti_ai_writing[:2000]}\n\n"
                    f"{persona_text}\n\n"
                    "記事本文のみを出力。タイトルも含めてよい。"
                ),
                model_selection=model_sel_draft,
            )
            first_draft = result_draft.get("text", "").strip()
            # メタ指示漏洩を除去
            first_draft = _sanitize_article_output(first_draft)
            if not first_draft or len(first_draft) < 6000:
                raise ValueError(f"初稿が短すぎる（{len(first_draft)}字、有料記事は最低6000字必要）")

            # 事実検証チェック
            factual_issues = _verify_factual_claims(first_draft)
            if factual_issues:
                logger.warning(f"Stage 3 事実検証: {len(factual_issues)}件の問題 — {factual_issues}")
                # critical issues（タイムライン矛盾・経歴矛盾）が2件以上なら初稿を棄却
                critical = [i for i in factual_issues if "[タイムライン矛盾]" in i or "[経歴矛盾]" in i]
                if len(critical) >= 2:
                    raise ValueError(
                        f"初稿に重大な事実誤認が{len(critical)}件: "
                        + "; ".join(critical[:3])
                    )

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
                    task_type="quality_verification", quality="high",
                    budget_sensitive=True, needs_japanese=True,
                )
                min_length = len(rewritten)
                rewrite_instruction = (
                    "以下の記事を島原大知の声でリライトしてください。\n"
                    "この記事は500円の有料note記事です。無料記事と明確に差別化される品質が必要です。\n\n"
                    f"【最重要】必ず元の文章と同等以上の長さを維持すること。元原稿は{min_length}字です。"
                    f"リライト結果は最低{min_length}字以上にしてください。"
                    "短縮・要約は絶対に行わないでください。情報量を減らさず、むしろ具体例や描写を追加して充実させること。\n\n"
                    "リライトの指針:\n"
                    "- 一人称は場面に応じて「私」「僕」「自分」を使い分ける\n"
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
                        "島原大知の文体でリライトするエディター。\n\n"
                        f"{writing_style[:2000]}\n\n"
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
                    raise ValueError(f"リライト結果が短すぎる（{rewrite_len}字、有料記事は4000字以上必要）")
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
                        "以下の有料note記事（980円）を批評し、改善してください。\n\n"
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
                        "- 記事の構造（見出し、ペイウォール位置）は維持\n"
                        "- 島原大知の文体を維持（断定、短文、三点リーダー、逆接多用）\n"
                        "- 架空のエピソードを追加しない\n"
                        "- 改善した完全版の記事本文のみを出力\n\n"
                        f"## 記事本文\n{rewritten}"
                    ),
                    system_prompt=(
                        "あなたは有料コンテンツの品質改善エディター。\n"
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

        # === SYUTAINβ auto-generated ラベル（記事冒頭） ===
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
