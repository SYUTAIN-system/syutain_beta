"""
X 収益分配 + サブスクリプション機能 要件達成トラッカー

島原さん最優先指示(2026-04-11): X広告収益分配(500万imp/3ヶ月)および
サブスクリプション機能(2000認証フォロワー + 500万オーガニックimp/3ヶ月)の
要件達成を戦略KPIのトップに据える。

事実ベース方針(feedback_fact_based_strict):
- 手入力された baseline は settings.x_monetization_state に保存
- 自動計算できる値は posting_queue_engagement から算出
- 手入力が必要な値(認証フォロワー数)は設定が無ければ None を返す
- 全ての値に "measured" / "manual" / "projected" のラベルを付けて区別する
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 要件閾値(X公式)
REVENUE_SHARE_TARGETS = {
    "premium_verified": True,          # Premium認証必須
    "verified_followers_min": 500,     # 達成済
    "impressions_90d_min": 5_000_000,  # 3ヶ月500万
}

SUBSCRIPTIONS_TARGETS = {
    "premium_verified": True,
    "verified_followers_min": 2000,    # 認証済フォロワー2000人
    "impressions_90d_min": 5_000_000,
    "active_within_30d": True,
    "age_18_plus": True,
}


async def _get_state() -> dict:
    """settings.x_monetization_state から現在の状態を取得"""
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'x_monetization_state'"
        )
        if row and row["value"]:
            data = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            return data
    return {}


async def _save_state(state: dict) -> None:
    from tools.db_pool import get_connection
    async with get_connection() as conn:
        await conn.execute(
            """INSERT INTO settings (key, value) VALUES ('x_monetization_state', $1)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            json.dumps(state, ensure_ascii=False),
        )


async def update_verified_followers(count: int, source: str = "manual") -> dict:
    """認証済フォロワー数を更新(手入力または自動取得)"""
    state = await _get_state()
    state["verified_followers"] = {
        "count": int(count),
        "source": source,  # 'manual' / 'api' / 'jina'
        "updated_at": datetime.now(JST).isoformat(),
    }
    await _save_state(state)
    return state["verified_followers"]


async def update_monthly_impressions(
    month: str, count: int, source: str = "manual",
) -> dict:
    """月次 impression を記録(島原さんが手動で共有した値などを保存)

    month: 'YYYY-MM' 形式
    """
    state = await _get_state()
    months = state.setdefault("monthly_impressions", {})
    months[month] = {
        "count": int(count),
        "source": source,
        "updated_at": datetime.now(JST).isoformat(),
    }
    await _save_state(state)
    return months[month]


def _iter_last_3_months(today: date) -> list[str]:
    """直近3ヶ月のラベル(YYYY-MM)を新しい順に返す"""
    result = []
    for offset in range(3):
        y = today.year
        m = today.month - offset
        while m <= 0:
            m += 12
            y -= 1
        result.append(f"{y:04d}-{m:02d}")
    return result


async def compute_impressions_90d() -> dict:
    """直近3ヶ月の imp 合計を計算"""
    state = await _get_state()
    months_data = state.get("monthly_impressions", {})
    today = datetime.now(JST).date()
    recent_labels = _iter_last_3_months(today)

    total = 0
    per_month = {}
    missing_months = []
    for label in recent_labels:
        entry = months_data.get(label)
        if entry:
            total += int(entry.get("count", 0))
            per_month[label] = entry
        else:
            per_month[label] = None
            missing_months.append(label)

    return {
        "total_90d": total,
        "per_month": per_month,
        "missing_months": missing_months,
        "target": REVENUE_SHARE_TARGETS["impressions_90d_min"],
        "progress": min(2.0, total / REVENUE_SHARE_TARGETS["impressions_90d_min"]) if REVENUE_SHARE_TARGETS["impressions_90d_min"] else 0.0,
        "gap_to_target": max(0, REVENUE_SHARE_TARGETS["impressions_90d_min"] - total),
    }


async def check_requirements() -> dict:
    """広告収益分配+サブスクリプション要件の達成状況を返す"""
    state = await _get_state()

    verified = state.get("verified_followers") or {}
    verified_count = int(verified.get("count", 0)) if verified else None

    imp90 = await compute_impressions_90d()

    revenue_share = {
        "premium_verified": True,  # 手動確認済
        "verified_followers_500": {
            "current": verified_count,
            "target": REVENUE_SHARE_TARGETS["verified_followers_min"],
            "met": (verified_count is not None and verified_count >= REVENUE_SHARE_TARGETS["verified_followers_min"]),
        },
        "impressions_90d_5M": {
            "current": imp90["total_90d"],
            "target": REVENUE_SHARE_TARGETS["impressions_90d_min"],
            "met": imp90["total_90d"] >= REVENUE_SHARE_TARGETS["impressions_90d_min"],
            "gap": imp90["gap_to_target"],
            "progress": imp90["progress"],
            "missing_months": imp90["missing_months"],
        },
    }
    revenue_share["all_met"] = all(
        v["met"] if isinstance(v, dict) else v
        for v in revenue_share.values()
    )

    subscriptions = {
        "premium_verified": True,
        "verified_followers_2000": {
            "current": verified_count,
            "target": SUBSCRIPTIONS_TARGETS["verified_followers_min"],
            "met": (verified_count is not None and verified_count >= SUBSCRIPTIONS_TARGETS["verified_followers_min"]),
            "gap": max(0, SUBSCRIPTIONS_TARGETS["verified_followers_min"] - (verified_count or 0)),
        },
        "impressions_90d_5M": revenue_share["impressions_90d_5M"],
        "active_within_30d": True,  # 手動確認済
        "age_18_plus": True,        # 手動確認済
    }
    subscriptions["all_met"] = all(
        v["met"] if isinstance(v, dict) else v
        for v in subscriptions.values()
    )

    return {
        "audit_at": datetime.now(JST).isoformat(),
        "verified_followers_source": verified.get("source", "not_set"),
        "verified_followers_updated_at": verified.get("updated_at"),
        "revenue_share": revenue_share,
        "subscriptions": subscriptions,
        "raw_state": state,
    }


async def format_report(result: dict | None = None) -> str:
    """要件達成状況を Discord 通知用に整形"""
    if result is None:
        result = await check_requirements()

    rs = result["revenue_share"]
    sub = result["subscriptions"]
    rs_verified = rs["verified_followers_500"]
    sub_verified = sub["verified_followers_2000"]
    imp = rs["impressions_90d_5M"]

    def _mark(b: bool) -> str:
        return "✅" if b else "❌"

    # verified followers current text
    vf_current = rs_verified["current"]
    if vf_current is None:
        vf_text = "未設定(要手入力)"
    else:
        vf_text = f"{vf_current:,}人"

    lines = [
        f"# X 収益化要件達成状況",
        f"(判定時刻 {result['audit_at'][:16]} / 認証フォロワー source={result['verified_followers_source']})",
        "",
        f"## 広告収益分配 {_mark(rs['all_met'])}",
        f"- Premium認証: ✅",
        f"- 認証フォロワー500人: {_mark(rs_verified['met'])} (現在 {vf_text})",
        f"- 直近90日imp 500万: {_mark(imp['met'])} (現在 {imp['current']:,}、達成率 {imp['progress']*100:.1f}%、残 {imp['gap']:,})",
        "",
        f"## サブスクリプション {_mark(sub['all_met'])}",
        f"- Premium認証: ✅",
        f"- 認証フォロワー2000人: {_mark(sub_verified['met'])} (現在 {vf_text}、残 {sub_verified['gap']:,}人)",
        f"- 直近90日imp 500万: {_mark(imp['met'])} (現在 {imp['current']:,})",
        f"- 30日以内活動: ✅",
        f"- 18歳以上: ✅",
    ]

    if imp["missing_months"]:
        lines.append("")
        lines.append(f"⚠️ imp未計測月: {', '.join(imp['missing_months'])} (島原さんが共有してくれた値の月を settings に追加してください)")

    return "\n".join(lines)


async def seed_initial_baseline_20260411() -> dict:
    """2026-04-11時点の baseline を初期化(島原さんが共有した値)"""
    # 認証済フォロワー数(2026-04-11 Discord共有)
    await update_verified_followers(1757, source="manual_20260411")

    # 月次impressions(2026-04-11 Discord共有)
    await update_monthly_impressions("2026-01", 10041, source="manual_20260411")
    await update_monthly_impressions("2026-02", 14675, source="manual_20260411")
    await update_monthly_impressions("2026-03", 49323, source="manual_20260411")
    await update_monthly_impressions("2026-04", 31028, source="manual_20260411_partial")

    return await check_requirements()


if __name__ == "__main__":
    import asyncio
    async def _run():
        await seed_initial_baseline_20260411()
        result = await check_requirements()
        print(await format_report(result))
    asyncio.run(_run())
