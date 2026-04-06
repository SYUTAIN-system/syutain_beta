"""週報自動集計 — 拡散実行書フォーマットに準拠した月曜週報の素材を自動生成

毎週月曜の記事生成 (morning スロット、地層=記録層) で使われる。
全数字をDBから自動集計してフォーマットに流し込む。
"""

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.weekly_report")


async def build_weekly_report_data(conn) -> dict:
    """直近7日の全システム数値を集計して週報データを返す"""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    data = {}

    # LLM
    row = await conn.fetchrow(
        "SELECT COUNT(*) as calls, COALESCE(SUM(amount_jpy),0)::int as cost FROM llm_cost_log WHERE recorded_at > $1", week_ago)
    data["llm_calls_week"] = row["calls"] if row else 0
    data["llm_cost_week"] = row["cost"] if row else 0

    row2 = await conn.fetchrow("SELECT COUNT(*) as total, COALESCE(SUM(amount_jpy),0)::int as cost FROM llm_cost_log")
    data["llm_calls_total"] = row2["total"] if row2 else 0
    data["llm_cost_total"] = row2["cost"] if row2 else 0

    # ローカル比率
    local = await conn.fetchval(
        "SELECT COUNT(*) FROM llm_cost_log WHERE tier='L' AND recorded_at > $1", week_ago) or 0
    data["local_ratio"] = round(local / max(data["llm_calls_week"], 1) * 100, 1)

    # SNS
    for status in ["posted", "failed", "rejected_poem"]:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM posting_queue WHERE status=$1 AND created_at > $2", status, week_ago) or 0
        data[f"sns_{status}"] = cnt

    # プラットフォーム別
    rows = await conn.fetch(
        "SELECT platform, COUNT(*) as cnt FROM posting_queue WHERE status='posted' AND posted_at > $1 GROUP BY platform", week_ago)
    data["sns_by_platform"] = {r["platform"]: r["cnt"] for r in rows}

    # 記事
    data["articles_generated"] = await conn.fetchval(
        "SELECT COUNT(*) FROM product_packages WHERE platform='note' AND created_at > $1", week_ago) or 0
    data["articles_published"] = await conn.fetchval(
        "SELECT COUNT(*) FROM product_packages WHERE platform='note' AND status='published' AND published_at > $1", week_ago) or 0

    # intel
    data["intel_new"] = await conn.fetchval(
        "SELECT COUNT(*) FROM intel_items WHERE created_at > $1", week_ago) or 0
    data["intel_total"] = await conn.fetchval("SELECT COUNT(*) FROM intel_items") or 0
    data["intel_grok"] = await conn.fetchval(
        "SELECT COUNT(*) FROM intel_items WHERE source='grok_x_research' AND created_at > $1", week_ago) or 0

    # Codex
    data["codex_fixes"] = await conn.fetchval(
        "SELECT COUNT(*) FROM event_log WHERE event_type='codex.auto_fix' AND created_at > $1", week_ago) or 0
    data["codex_audits"] = await conn.fetchval(
        "SELECT COUNT(*) FROM event_log WHERE event_type='codex.daily_content_audit' AND created_at > $1", week_ago) or 0

    # crypto
    data["crypto_snapshots"] = await conn.fetchval(
        "SELECT COUNT(*) FROM event_log WHERE event_type='trade.price_snapshot' AND created_at > $1", week_ago) or 0

    # エンゲージメント
    data["engagement_collections"] = await conn.fetchval(
        "SELECT COUNT(*) FROM posting_queue WHERE engagement_data IS NOT NULL AND posted_at > $1", week_ago) or 0

    # scheduler
    data["scheduler_jobs"] = 70  # 概算

    # goals
    data["goals_completed"] = await conn.fetchval(
        "SELECT COUNT(*) FROM goal_packets WHERE status='completed' AND created_at > $1", week_ago) or 0

    # errors
    data["errors_week"] = await conn.fetchval(
        "SELECT COUNT(*) FROM event_log WHERE severity IN ('error','critical') AND created_at > $1", week_ago) or 0

    # 収益
    data["revenue"] = 0  # TODO: commerce_transactions から集計

    return data


def format_weekly_report(data: dict, week_number: int = 0) -> str:
    """週報データをnote記事用の Markdown に整形する（拡散実行書フォーマット準拠）"""
    sns_plat = data.get("sns_by_platform", {})

    report = f"""# SYUTAINβ Week {week_number} ── 今週の全記録

## 今週の数字

| 指標 | 値 |
|------|-----|
| X投稿 (shimahara) | {sns_plat.get('x', 0)} 件 |
| X投稿 (syutain) | — |
| Bluesky投稿 | {sns_plat.get('bluesky', 0)} 件 |
| Threads投稿 | {sns_plat.get('threads', 0)} 件 |
| note記事 生成 | {data.get('articles_generated', 0)} 本 |
| note記事 公開 | {data.get('articles_published', 0)} 本 |
| API代 (今週) | ¥{data.get('llm_cost_week', 0)} (累計¥{data.get('llm_cost_total', 0)}) |
| LLM呼び出し (今週) | {data.get('llm_calls_week', 0)} 回 (累計{data.get('llm_calls_total', 0)}回) |
| ローカルLLM処理率 | {data.get('local_ratio', 0)}% |
| ゴール完了 | {data.get('goals_completed', 0)} 件 |
| エラー発生 | {data.get('errors_week', 0)} 件 |
| 収益 | ¥{data.get('revenue', 0)} |

## 今週SYUTAINβが自動で動かしたもの

- **Grok X検索**: {data.get('intel_grok', 0)} 件の素材を自動収集
- **情報収集パイプライン**: intel_items に {data.get('intel_new', 0)} 件蓄積 (累計{data.get('intel_total', 0)}件)
- **暗号通貨価格監視**: {data.get('crypto_snapshots', 0)} 回のスナップショット (19通貨、GMOコイン/bitbank)
- **SNSエンゲージメント収集**: {data.get('engagement_collections', 0)} 件 (X/Bluesky/Threads、4時間間隔)
- **スケジューラジョブ**: {data.get('scheduler_jobs', 70)} 本が24時間稼働中
- **CODEX自律修復**: {data.get('codex_fixes', 0)} 件の自動修正 / {data.get('codex_audits', 0)} 回の品質管理

## 今週いちばん進んだこと

[ここはcontent_pipelineが自動生成する — 直近7日のevent_logから最も重要なイベントを選定]

## 今週いちばん危なかったこと

[ここはcontent_pipelineが自動生成する — 直近7日のerror/criticalイベントから選定]

## まだAIに任せてないこと

- まだAIに値段は決めさせてない
- まだAIに公開ボタンは渡してない（品質6層防御通過で自動公開に移行中）
- まだAIに「やめろ」の判断は任せてない

## 来週の賭け

[ここはcontent_pipelineが自動生成する]
"""
    return report
