"""ACTIONタグの実行 — Bot応答に必要なデータ取得・操作実行"""
import re, json, logging, asyncio
from datetime import timezone, timedelta
from tools.db_pool import get_connection

logger = logging.getLogger("syutain.bot_actions")

# JST変換ヘルパー
_JST = timezone(timedelta(hours=9))


def _to_jst(dt) -> str:
    """datetime → JST文字列 (MM/DD HH:MM)"""
    if dt is None:
        return "-"
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_JST).strftime("%m/%d %H:%M")
    except Exception:
        return str(dt)[:16]


def _to_jst_time(dt) -> str:
    """datetime → JST時刻のみ (HH:MM)"""
    if dt is None:
        return "-"
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_JST).strftime("%H:%M")
    except Exception:
        return str(dt)[:5]

# ACTIONハンドラーのレジストリ
_ACTION_HANDLERS = {}


def _register(name):
    def decorator(func):
        _ACTION_HANDLERS[name] = func
        return func
    return decorator


async def process_actions(response_text: str) -> dict:
    """LLM応答からACTIONタグを抽出して実行。結果を返す"""
    actions = re.findall(r'\[ACTION:([^\]]+)\]', response_text)
    clean_text = re.sub(r'\[ACTION:[^\]]+\]', '', response_text).strip()
    results = {}

    for action in actions:
        parts = action.split(":", 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        handler = _ACTION_HANDLERS.get(cmd)
        if handler:
            try:
                if arg:
                    results[cmd] = await handler(arg)
                else:
                    results[cmd] = await handler()
            except Exception as e:
                logger.warning(f"ACTION {cmd} 失敗: {e}")
                results[cmd] = {"error": str(e)}
        elif cmd == "set_goal" and arg:
            results["goal_set"] = await _execute_goal(arg)
        else:
            logger.warning(f"未知のACTION: {cmd}")

    return {"clean_text": clean_text, "actions": actions, "results": results}


# === データ取得関数 ===

@_register("status_check")
async def get_system_status() -> dict:
    """全エージェント・ノード・LLM・SNS・情報収集のリアルタイム状態を取得"""
    try:
        from bots.bot_conversation import _get_full_system_report
        report = await _get_full_system_report()
        return {"report": report}
    except Exception as e:
        # フォールバック: 最低限のhealth
        import httpx
        try:
            r = httpx.get("http://127.0.0.1:8000/health", timeout=5)
            return r.json()
        except Exception:
            return {"error": str(e)}


@_register("node_detail")
async def get_node_detail(node: str = "") -> dict:
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT node_name, state, reason, changed_at FROM node_state WHERE node_name = $1",
            node.lower(),
        )
        return dict(row) if row else {"error": f"ノード{node}が見つかりません"}


@_register("posting_status")
async def get_today_posts() -> dict:
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) FILTER (WHERE status='posted') as posted,
                COUNT(*) FILTER (WHERE status='pending') as pending,
                COUNT(*) FILTER (WHERE status='failed') as failed
            FROM posting_queue WHERE scheduled_at::date = CURRENT_DATE"""
        )
        return dict(row) if row else {}


@_register("error_check")
async def get_recent_errors(hours: int = 24) -> list:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT event_type, LEFT(payload->>'error', 100) as error, source_node, created_at
            FROM event_log WHERE severity IN ('error','critical')
            AND created_at > NOW() - $1 * INTERVAL '1 hour'
            ORDER BY created_at DESC LIMIT 5""",
            hours,
        )
        return [{"type": r["event_type"], "error": r["error"], "node": r["source_node"],
                 "at": _to_jst(r["created_at"])} for r in rows]


@_register("budget_status")
async def get_cost_summary() -> dict:
    async with get_connection() as conn:
        today = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
        )
        week = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '7 days'"
        )
        local_pct = await conn.fetchval(
            """SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE tier IN ('local','L'))
               / GREATEST(COUNT(*), 1), 1)
            FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours'"""
        )
        return {"today_jpy": float(today), "week_jpy": float(week), "local_pct": float(local_pct or 0)}


@_register("artifacts_list")
async def get_artifacts_list(limit: int = 5) -> list:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, type, quality_score, LEFT(output_data::text, 100) as preview, created_at
            FROM tasks WHERE type IN ('content','drafting','note_article','product_desc')
            AND status IN ('completed','success')
            ORDER BY created_at DESC LIMIT $1""",
            limit,
        )
        return [dict(r) for r in rows]


@_register("pending_approvals")
async def get_pending_approvals() -> list:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, request_type, request_data, requested_at
            FROM approval_queue WHERE status='pending'
            ORDER BY requested_at DESC LIMIT 10"""
        )
        return [dict(r) for r in rows]


@_register("pending_approvals_detail")
async def get_pending_approvals_detail() -> str:
    """承認待ちタスクの詳細を人間が読める形式で返す"""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, request_type, request_data, requested_at
            FROM approval_queue WHERE status='pending'
            ORDER BY requested_at DESC LIMIT 10"""
        )
        if not rows:
            return "✅ 承認待ちはありません"

        lines = [f"📋 **承認待ち: {len(rows)}件**\n"]
        for r in rows:
            import json as _json
            data = r["request_data"]
            if isinstance(data, str):
                try:
                    data = _json.loads(data)
                except Exception:
                    pass

            req_type = r["request_type"]
            item_id = r["id"]
            age_hours = (datetime.now(timezone.utc) - r["requested_at"]).total_seconds() / 3600

            # タイプ別に分かりやすい説明を生成
            if req_type == "product_publish":
                title = data.get("title", "不明")[:60] if isinstance(data, dict) else "不明"
                price = data.get("price_jpy", "?") if isinstance(data, dict) else "?"
                lines.append(
                    f"**#{item_id}** 📝 note記事公開\n"
                    f"  タイトル: {title}\n"
                    f"  価格: ¥{price}\n"
                    f"  待機: {age_hours:.0f}時間\n"
                    f"  → 承認: `承認 {item_id}` / 却下: `却下 {item_id}`\n"
                )
            elif req_type == "approval_request":
                task_type = data.get("task_type", "不明") if isinstance(data, dict) else "不明"
                desc = data.get("description", "")[:100] if isinstance(data, dict) else ""
                lines.append(
                    f"**#{item_id}** 🔄 タスク承認\n"
                    f"  種類: {task_type}\n"
                    f"  内容: {desc or '詳細なし'}\n"
                    f"  待機: {age_hours:.0f}時間\n"
                    f"  → 承認: `承認 {item_id}` / 却下: `却下 {item_id}`\n"
                )
            elif req_type == "x_post":
                content = data.get("content", "")[:100] if isinstance(data, dict) else ""
                lines.append(
                    f"**#{item_id}** 🐦 X投稿\n"
                    f"  内容: {content}\n"
                    f"  → 承認: `承認 {item_id}` / 却下: `却下 {item_id}`\n"
                )
            else:
                preview = str(data)[:100] if data else "詳細なし"
                lines.append(
                    f"**#{item_id}** {req_type}\n"
                    f"  内容: {preview}\n"
                    f"  → 承認: `承認 {item_id}` / 却下: `却下 {item_id}`\n"
                )

        return "\n".join(lines)


@_register("approve")
async def approve_item(item_id: int = 0) -> str:
    if isinstance(item_id, str):
        item_id = int(item_id)
    async with get_connection() as conn:
        # 承認対象の内容を取得してからapprove
        row = await conn.fetchrow(
            "SELECT request_type, request_data FROM approval_queue WHERE id=$1", item_id
        )
        if not row:
            return f"ID {item_id} が見つかりません"
        await conn.execute(
            "UPDATE approval_queue SET status='approved', responded_at=NOW() WHERE id=$1",
            item_id,
        )
        import json as _json
        data = row["request_data"]
        if isinstance(data, str):
            try:
                data = _json.loads(data)
            except Exception:
                pass
        title = data.get("title", data.get("content", str(data)))[:60] if isinstance(data, dict) else str(data)[:60]
    return f"✅ 承認しました (ID: {item_id})\n内容: {title}"


@_register("reject")
async def reject_item(item_id: int = 0, reason: str = None) -> str:
    if isinstance(item_id, str):
        item_id = int(item_id)
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT request_type, request_data FROM approval_queue WHERE id=$1", item_id
        )
        if not row:
            return f"ID {item_id} が見つかりません"
        await conn.execute(
            "UPDATE approval_queue SET status='rejected', responded_at=NOW(), response=$2 WHERE id=$1",
            item_id, reason or "Discordから却下",
        )
        import json as _json
        data = row["request_data"]
        if isinstance(data, str):
            try:
                data = _json.loads(data)
            except Exception:
                pass
        title = data.get("title", data.get("content", str(data)))[:60] if isinstance(data, dict) else str(data)[:60]
    return f"❌ 却下しました (ID: {item_id})\n内容: {title}" + (f"\n理由: {reason}" if reason else "")


@_register("intel_digest")
async def get_today_digest() -> str:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT title, importance_score, category
            FROM intel_items WHERE review_flag = 'actionable'
            ORDER BY importance_score DESC LIMIT 5"""
        )
        if not rows:
            return "今日のactionableなニュースはありません。"
        return "\n".join(
            f"- [{r['category']}] {r['title'][:60]} (重要度: {r['importance_score']:.2f})"
            for r in rows
        )


@_register("news_check")
async def get_latest_news(topic: str = None) -> str:
    async with get_connection() as conn:
        if topic:
            rows = await conn.fetch(
                """SELECT title, summary, importance_score FROM intel_items
                WHERE (title ILIKE $1 OR summary ILIKE $1) AND review_flag IN ('actionable','reviewed')
                ORDER BY created_at DESC LIMIT 3""",
                f"%{topic}%",
            )
        else:
            rows = await conn.fetch(
                """SELECT title, summary, importance_score FROM intel_items
                WHERE review_flag = 'actionable'
                ORDER BY importance_score DESC LIMIT 3"""
            )
        if not rows:
            return "特にないです。"
        return "\n".join(f"- {r['title'][:60]}: {(r['summary'] or '')[:80]}" for r in rows)


@_register("proposals_list")
async def get_latest_proposals() -> list:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT id, proposal_id, title, primary_channel, created_at
            FROM proposal_history ORDER BY created_at DESC LIMIT 5"""
        )
        return [dict(r) for r in rows]


@_register("model_info")
async def get_current_models() -> list:
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT model, tier, COUNT(*) as calls, COALESCE(SUM(amount_jpy), 0) as cost
            FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours'
            GROUP BY model, tier ORDER BY calls DESC LIMIT 5"""
        )
        return [{"model": r["model"], "tier": r["tier"], "calls": r["calls"],
                 "cost": float(r["cost"])} for r in rows]


async def get_bot_info() -> dict:
    return {
        "response_model": "DeepSeek V3.2 / Claude Haiku 4.5 (自動選択)",
        "features": ["対話学習", "プロアクティブ報告", "Brain-αエスカレーション", "深さ検知モデル切替"],
    }


# === 新規ACTIONハンドラー ===

@_register("sns_preview")
async def get_sns_preview(date: str = "") -> str:
    """SNS投稿プレビュー（今日or明日のpending投稿内容を表示）"""
    async with get_connection() as conn:
        target = "CURRENT_DATE + 1" if "明日" in date or "tomorrow" in date else "CURRENT_DATE"
        rows = await conn.fetch(f"""
            SELECT id, platform, account, quality_score, LEFT(content, 120) as preview,
              scheduled_at
            FROM posting_queue
            WHERE scheduled_at::date = {target} AND status='pending'
            ORDER BY scheduled_at LIMIT 10
        """)
        if not rows:
            return "該当する投稿はありません。"
        lines = []
        for r in rows:
            lines.append(f"[{_to_jst_time(r['scheduled_at'])}] #{r['id']} {r['platform']}/{r['account']} (品質:{r['quality_score']:.2f})")
            lines.append(f"  {r['preview']}")
        return "\n".join(lines)


@_register("goals_list")
async def get_goals_list(status: str = "") -> str:
    """ゴール一覧（status指定可能）"""
    async with get_connection() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT goal_id, status, LEFT(raw_goal, 80) as goal, created_at FROM goal_packets WHERE status=$1 ORDER BY created_at DESC LIMIT 5",
                status,
            )
        else:
            rows = await conn.fetch(
                "SELECT goal_id, status, LEFT(raw_goal, 80) as goal, created_at FROM goal_packets ORDER BY created_at DESC LIMIT 5"
            )
        if not rows:
            return "ゴールはありません。"
        lines = []
        for r in rows:
            lines.append(f"[{r['status']}] {r['goal']}")
            lines.append(f"  ID: {r['goal_id']} ({_to_jst(r['created_at'])})")
        return "\n".join(lines)


@_register("engagement")
async def get_engagement_summary(platform: str = "") -> str:
    """SNSエンゲージメント概要"""
    async with get_connection() as conn:
        if platform:
            rows = await conn.fetch("""
                SELECT platform, account, quality_score,
                  engagement_data->>'like_count' as likes,
                  engagement_data->>'impression_count' as imps,
                  LEFT(content, 50) as preview
                FROM posting_queue
                WHERE engagement_data IS NOT NULL AND platform=$1
                ORDER BY (engagement_data->>'like_count')::int DESC NULLS LAST LIMIT 5
            """, platform)
        else:
            rows = await conn.fetch("""
                SELECT platform, account, quality_score,
                  engagement_data->>'like_count' as likes,
                  engagement_data->>'impression_count' as imps,
                  LEFT(content, 50) as preview
                FROM posting_queue
                WHERE engagement_data IS NOT NULL
                ORDER BY (engagement_data->>'like_count')::int DESC NULLS LAST LIMIT 5
            """)
        if not rows:
            return "エンゲージメントデータはまだありません。"
        lines = ["**反応が高い投稿:**"]
        for r in rows:
            imp = f" imp={r['imps']}" if r['imps'] else ""
            lines.append(f"  {r['platform']}: likes={r['likes']}{imp} — {r['preview']}")
        return "\n".join(lines)


@_register("intel_search")
async def search_intel(query: str = "") -> str:
    """情報収集結果を検索"""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT title, summary, importance_score, source, review_flag
            FROM intel_items
            WHERE (title ILIKE $1 OR summary ILIKE $1)
            ORDER BY importance_score DESC LIMIT 5""",
            f"%{query}%",
        )
        if not rows:
            return f"「{query}」に関する情報は見つかりませんでした。"
        lines = []
        for r in rows:
            lines.append(f"[{r['review_flag']}] {r['title'][:60]} (重要度:{r['importance_score']:.2f})")
            if r['summary']:
                lines.append(f"  {r['summary'][:100]}")
        return "\n".join(lines)


@_register("persona_check")
async def get_persona_summary(category: str = "") -> str:
    """persona_memoryの蓄積データ確認"""
    async with get_connection() as conn:
        if category:
            rows = await conn.fetch(
                "SELECT content FROM persona_memory WHERE category=$1 ORDER BY created_at DESC LIMIT 5",
                category,
            )
            return "\n".join(f"- {r['content'][:80]}" for r in rows) if rows else f"カテゴリ'{category}'のデータはありません。"
        else:
            rows = await conn.fetch(
                "SELECT category, COUNT(*) as cnt FROM persona_memory GROUP BY category ORDER BY cnt DESC"
            )
            return "\n".join(f"  {r['category']}: {r['cnt']}件" for r in rows)


@_register("artifact_detail")
async def get_artifact_detail(task_id: str = "") -> str:
    """成果物の全文表示"""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT type, quality_score, LEFT(output_data::text, 1500) as content FROM tasks WHERE id=$1",
            task_id,
        )
        if not row:
            return f"成果物 {task_id} が見つかりません。"
        return f"**{row['type']}** (品質: {row['quality_score']})\n{row['content']}"


@_register("proposal_detail")
async def get_proposal_detail(proposal_id: str = "") -> str:
    """提案の詳細表示"""
    async with get_connection() as conn:
        # IDが数値ならint検索、そうでなければproposal_id(UUID)検索
        try:
            pid_int = int(proposal_id)
            row = await conn.fetchrow(
                "SELECT title, score, review_flag, proposal_data FROM proposal_history WHERE id=$1",
                pid_int,
            )
        except (ValueError, TypeError):
            row = await conn.fetchrow(
                "SELECT title, score, review_flag, proposal_data FROM proposal_history WHERE proposal_id=$1",
                proposal_id,
            )
        if not row:
            return f"提案 {proposal_id} が見つかりません。"
        pdata = row['proposal_data'] or {}
        if isinstance(pdata, str):
            pdata = json.loads(pdata)
        why_now = pdata.get("why_now", [])
        outcome = pdata.get("expected_outcome", {})
        lines = [
            f"**{row['title']}**",
            f"スコア: {row['score']}点 / 状態: {row['review_flag']}",
        ]
        if why_now:
            lines.append(f"理由: {why_now[0][:150]}")
        if outcome:
            lines.append(f"見込み: {outcome.get('timeline', '?')} / 収益推定¥{outcome.get('revenue_estimate_jpy', 0):,}")
        return "\n".join(lines)


@_register("browse")
async def browse_page(instruction: str = "") -> str:
    """BRAVOのブラウザでURLアクセスまたは操作を実行し結果を返す。

    instruction形式:
    - URL直接: "https://example.com" → ページ内容を抽出
    - URL+指示: "https://example.com|クリック:ボタン名" → 操作実行
    - 検索指示: "search:DeepSeek V4 最新情報" → Jina検索→内容取得
    """
    try:
        from tools.nats_client import get_nats_client
        import re

        nats = await get_nats_client()
        if not nats or not nats.nc:
            return "NATS未接続。ブラウザ操作を実行できません。"

        url = ""
        action_type = "extract"
        params = {}

        parts = instruction.split("|", 1)
        target = parts[0].strip()
        extra = parts[1].strip() if len(parts) > 1 else ""

        # URL判定
        if target.startswith("http://") or target.startswith("https://"):
            url = target
        elif target.startswith("search:"):
            # Tavily検索
            query = target[7:].strip()
            try:
                from tools.tavily_client import TavilyClient
                tavily = TavilyClient()
                search_result = await tavily.search(query, max_results=3)
                items = search_result.get("results", [])
                if items:
                    lines = ["**検索結果:**"]
                    for r in items[:3]:
                        lines.append(f"- [{r.get('title','')}]({r.get('url','')})")
                        lines.append(f"  {r.get('content','')[:120]}")
                    answer = search_result.get("answer", "")
                    if answer:
                        lines.insert(1, f"**AI回答:** {answer[:200]}")
                    return "\n".join(lines)
            except Exception as e:
                logger.warning(f"Tavily検索失敗: {e}")
            return f"検索「{query}」の結果を取得できませんでした。"
        else:
            # URLなし → Tavilyで検索して最初の結果をブラウザで取得
            try:
                from tools.tavily_client import TavilyClient
                tavily = TavilyClient()
                search_result = await tavily.search(target, max_results=3)
                items = search_result.get("results", [])
                if items:
                    lines = ["**検索結果:**"]
                    for r in items[:3]:
                        lines.append(f"- [{r.get('title','')}]({r.get('url','')})")
                        lines.append(f"  {r.get('content','')[:120]}")
                    url = items[0].get("url", "")
                    if not url:
                        return "\n".join(lines)
                else:
                    return f"「{target}」に関する情報が見つかりませんでした。"
            except Exception as e:
                return f"検索失敗: {e}"

        if not url:
            return "URLまたは検索キーワードを指定してください。"

        # 操作指示の解析
        if extra:
            if extra.startswith("クリック:") or extra.startswith("click:"):
                action_type = "act"
                params["instruction"] = extra
            else:
                params["instruction"] = extra

        # BRAVOにNATSリクエスト送信（60秒タイムアウト）
        response = await nats.request(
            "req.browser.bravo",
            {
                "action_type": action_type,
                "url": url,
                "params": params,
            },
            timeout=60.0,
        )

        if not response:
            return f"BRAVOからの応答がありませんでした。(URL: {url})"

        if response.get("success"):
            data = response.get("data", "")
            if isinstance(data, str):
                # テキスト抽出結果 → 先頭1200文字
                return f"**{url}**\n{data[:1200]}"
            elif isinstance(data, dict):
                return f"**{url}**\n{json.dumps(data, ensure_ascii=False, indent=2)[:1200]}"
            elif isinstance(data, list):
                return f"**{url}**\n" + "\n".join(str(d)[:100] for d in data[:10])
            return f"操作成功: {url}"
        else:
            error = response.get("error", "不明なエラー")
            return f"ブラウザ操作失敗: {error} (URL: {url})"

    except Exception as e:
        return f"ブラウザ操作エラー: {e}"


async def _execute_goal(raw_goal: str) -> str:
    """ゴールを設定して自律ループを起動"""
    try:
        from agents.os_kernel import get_os_kernel
        kernel = get_os_kernel()
        asyncio.create_task(kernel.execute_goal(raw_goal))
        return f"ゴール受付: {raw_goal[:100]}。自律ループを開始します。"
    except Exception as e:
        return f"ゴール起動失敗: {e}"


# ==========================================
# 追加機能 (#1-#7)
# ==========================================

# --- #1: SNS投稿の編集/削除 ---

@_register("sns_edit")
async def edit_sns_post(args: str = "") -> str:
    """pending投稿を編集。形式: ID|新しい内容"""
    parts = args.split("|", 1)
    if len(parts) < 2:
        return "形式: [ACTION:sns_edit:ID|新しい内容]"
    try:
        post_id = int(parts[0].strip())
        new_content = parts[1].strip()
    except ValueError:
        return "IDは数字で指定してください。"

    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, platform FROM posting_queue WHERE id=$1", post_id
        )
        if not row:
            return f"投稿 #{post_id} が見つかりません。"
        if row["status"] != "pending":
            return f"投稿 #{post_id} は既に{row['status']}です。pendingのみ編集可能。"
        await conn.execute(
            "UPDATE posting_queue SET content=$1 WHERE id=$2",
            new_content, post_id,
        )
        return f"投稿 #{post_id} ({row['platform']}) を編集しました。"


@_register("sns_delete")
async def delete_sns_post(post_id: str = "") -> str:
    """pending投稿を削除（rejected に変更）"""
    try:
        pid = int(post_id)
    except ValueError:
        return "IDは数字で指定してください。"

    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, platform FROM posting_queue WHERE id=$1", pid
        )
        if not row:
            return f"投稿 #{pid} が見つかりません。"
        if row["status"] != "pending":
            return f"投稿 #{pid} は既に{row['status']}です。"
        await conn.execute(
            "UPDATE posting_queue SET status='rejected' WHERE id=$1", pid
        )
        return f"投稿 #{pid} ({row['platform']}) を削除しました。"


# --- #2: コンテンツ直接生成 ---

@_register("generate")
async def generate_content(instruction: str = "") -> str:
    """LLMでコンテンツを直接生成して返す。SNS投稿文、記事ドラフト等。"""
    if not instruction:
        return "生成内容を指定してください。例: [ACTION:generate:Blueskyに投稿する文を作って。テーマはAI活用]"
    try:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from tools.llm_router import choose_best_model_v6, call_llm

        model_sel = choose_best_model_v6(
            task_type="drafting", quality="medium",
            budget_sensitive=True, needs_japanese=True,
        )
        result = await call_llm(
            prompt=instruction,
            system_prompt="島原大知の文体で作成するライター。投稿テキストのみ出力。AI臭い表現禁止。",
            model_selection=model_sel,
        )
        text = result.get("text", "").strip()
        model = result.get("model_used", "?")
        return f"**生成結果** ({model})\n{text}" if text else "生成に失敗しました。"
    except Exception as e:
        return f"生成エラー: {e}"


# --- #3: 日報/週報 ---

@_register("daily_report")
async def generate_daily_report(arg: str = "") -> str:
    """今日の活動サマリーを生成"""
    async with get_connection() as conn:
        # ゴール
        goals = await conn.fetch(
            "SELECT status, COUNT(*) FROM goal_packets WHERE created_at::date=CURRENT_DATE GROUP BY status"
        )
        # タスク
        tasks = await conn.fetchrow("""
            SELECT COUNT(*) as total,
              COUNT(*) FILTER (WHERE status='success') as success,
              ROUND(AVG(quality_score) FILTER (WHERE quality_score > 0)::numeric, 2) as avg_q
            FROM tasks WHERE created_at::date=CURRENT_DATE
        """)
        # SNS
        sns = await conn.fetchrow("""
            SELECT COUNT(*) FILTER (WHERE status='posted') as posted,
              COUNT(*) FILTER (WHERE status='pending') as pending
            FROM posting_queue WHERE scheduled_at::date=CURRENT_DATE
        """)
        # コスト
        cost = await conn.fetchrow("""
            SELECT COALESCE(SUM(amount_jpy),0) as total,
              COUNT(*) as calls,
              COUNT(*) FILTER (WHERE tier='L') as local
            FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE
        """)
        # エラー
        errors = await conn.fetchval(
            "SELECT COUNT(*) FROM event_log WHERE severity IN ('error','critical') AND created_at::date=CURRENT_DATE"
        )
        # 情報収集
        intel = await conn.fetchval(
            "SELECT COUNT(*) FROM intel_items WHERE created_at::date=CURRENT_DATE"
        )

        lines = ["**日報**"]
        # ゴール
        goal_str = ", ".join(f"{g['status']}={g['count']}" for g in goals) if goals else "なし"
        lines.append(f"ゴール: {goal_str}")
        # タスク
        if tasks:
            lines.append(f"タスク: {tasks['total']}件 (成功{tasks['success']}) 品質平均{tasks['avg_q'] or '-'}")
        # SNS
        if sns:
            lines.append(f"SNS: 投稿{sns['posted']}件 / 待ち{sns['pending']}件")
        # コスト
        if cost:
            local_pct = cost['local'] * 100 // max(cost['calls'], 1)
            lines.append(f"LLM: {cost['calls']}回 (ローカル{local_pct}%) ¥{float(cost['total']):.0f}")
        lines.append(f"エラー: {errors}件 / 情報収集: {intel}件")
        return "\n".join(lines)


@_register("weekly_report")
async def generate_weekly_report_action(arg: str = "") -> str:
    """直近7日の活動サマリー"""
    async with get_connection() as conn:
        cost = await conn.fetch("""
            SELECT recorded_at::date as d, COUNT(*) as calls,
              ROUND(SUM(amount_jpy)::numeric, 1) as cost
            FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '7 days'
            GROUP BY d ORDER BY d
        """)
        goals = await conn.fetchrow("""
            SELECT COUNT(*) as total,
              COUNT(*) FILTER (WHERE status='completed') as completed,
              COUNT(*) FILTER (WHERE status='emergency_stopped') as stopped
            FROM goal_packets WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        sns = await conn.fetchrow("""
            SELECT COUNT(*) FILTER (WHERE status='posted') as posted
            FROM posting_queue WHERE posted_at > NOW() - INTERVAL '7 days'
        """)
        lines = ["**週報 (直近7日)**"]
        if goals:
            lines.append(f"ゴール: {goals['total']}件 (完了{goals['completed']} / 停止{goals['stopped']})")
        if sns:
            lines.append(f"SNS投稿: {sns['posted']}件")
        if cost:
            total_cost = sum(float(c['cost'] or 0) for c in cost)
            total_calls = sum(c['calls'] for c in cost)
            lines.append(f"LLM: {total_calls}回 / 合計¥{total_cost:.0f}")
            lines.append("日別:")
            for c in cost:
                lines.append(f"  {c['d'].strftime('%m/%d')}: {c['calls']}回 ¥{float(c['cost'] or 0):.0f}")
        return "\n".join(lines)


# --- #4: スケジューラージョブの手動実行 ---

@_register("run_job")
async def run_scheduler_job(job_name: str = "") -> str:
    """スケジューラージョブを手動実行"""
    job_map = {
        "情報収集": "info_pipeline",
        "intel": "info_pipeline",
        "SNS再生成": "sns_batch",
        "sns": "sns_batch",
        "提案": "proposal",
        "キーワード": "keyword",
        "intel_digest": "intel_digest",
        "エンゲージメント": "engagement",
        "バックアップ": "backup",
        "学習": "learning",
    }

    matched = job_map.get(job_name, "")
    if not matched:
        available = ", ".join(job_map.keys())
        return f"利用可能: {available}"

    try:
        if matched == "info_pipeline":
            from tools.info_pipeline import InfoPipeline
            pipeline = InfoPipeline()
            result = await pipeline.run_full_pipeline()
            return f"情報収集完了: {result.get('total_saved', 0)}件保存"

        elif matched == "sns_batch":
            from brain_alpha.sns_batch import generate_batch, build_full_schedule
            schedule = build_full_schedule()
            from datetime import datetime, timedelta, timezone
            tomorrow = datetime.now(timezone(timedelta(hours=9))) + timedelta(days=1)
            result = await generate_batch("manual", schedule)
            return f"SNS生成完了: {result.get('inserted', 0)}/{result.get('total', 0)}件"

        elif matched == "proposal":
            from agents.proposal_engine import ProposalEngine
            pe = ProposalEngine()
            await pe.initialize()
            result = await pe.generate_proposal(
                context="Discord経由の日次提案リクエスト",
                objective="revenue",
                target_icp="hot_icp",
                primary_channel="note",
            )
            return f"提案生成完了: {result.get('title', '無題')} (スコア: {result.get('total_score', 0)})"

        elif matched == "keyword":
            from tools.keyword_generator import generate_search_keywords
            keywords = await generate_search_keywords()
            return f"キーワード更新完了: {len(keywords)}件 — {', '.join(keywords[:5])}"

        elif matched == "intel_digest":
            from tools.intel_digest import generate_intel_digest
            result = await generate_intel_digest()
            return f"intel_digest生成完了: {result.get('items_count', 0)}件"

        elif matched == "engagement":
            from bots.bot_actions import get_engagement_summary
            # 手動でエンゲージメント取得を実行
            from tools.social_tools import get_bluesky_engagement
            async with get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT id, post_url FROM posting_queue
                    WHERE platform = 'bluesky' AND status = 'posted'
                    AND post_url IS NOT NULL AND engagement_data IS NULL
                    LIMIT 10
                """)
                count = 0
                for row in rows:
                    eng = await get_bluesky_engagement(row["post_url"])
                    if not eng.get("error"):
                        await conn.execute(
                            "UPDATE posting_queue SET engagement_data = $1 WHERE id = $2",
                            json.dumps(eng, ensure_ascii=False), row["id"],
                        )
                        count += 1
            return f"エンゲージメント取得完了: {count}件更新"

        elif matched == "backup":
            import subprocess
            from datetime import datetime
            import os
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "backup")
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            backup_file = os.path.join(backup_dir, f"syutain_beta_{ts}.sql.gz")
            result = subprocess.run(
                f"pg_dump syutain_beta | gzip > {backup_file}",
                shell=True, capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                size = os.path.getsize(backup_file)
                return f"バックアップ完了: {backup_file} ({size//1024}KB)"
            return f"バックアップ失敗: {result.stderr[:100]}"

        elif matched == "learning":
            from agents.learning_manager import LearningManager
            lm = LearningManager()
            await lm.initialize()
            report = await lm.generate_weekly_report()
            return f"学習レポート生成完了: {str(report.get('summary', ''))[:200]}"

    except Exception as e:
        return f"ジョブ実行失敗 ({matched}): {e}"

    return f"未実装: {matched}"


# --- #5: BRAVOスクリーンショット ---

@_register("screenshot")
async def take_screenshot(url: str = "") -> str:
    """BRAVOのブラウザでスクリーンショットを撮影。
    画像はDiscordに送信する（ファイルパスを返す）"""
    if not url:
        return "URLを指定してください。例: [ACTION:screenshot:https://example.com]"
    try:
        from tools.nats_client import get_nats_client
        nats = await get_nats_client()
        if not nats or not nats.nc:
            return "NATS未接続。"

        response = await nats.request(
            "req.browser.bravo",
            {"action_type": "screenshot", "url": url, "params": {}},
            timeout=30.0,
        )
        if not response:
            return "BRAVOからの応答なし。"
        if response.get("success") and response.get("data"):
            # base64画像データの場合
            import base64, os, tempfile
            img_data = response["data"]
            if isinstance(img_data, str) and len(img_data) > 100:
                # base64 → ファイル保存
                filepath = os.path.join(tempfile.gettempdir(), f"screenshot_{url.split('//')[-1][:20].replace('/','_')}.png")
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(img_data))
                return f"__SCREENSHOT__:{filepath}"
            return f"スクリーンショット取得（データ形式不明）: {str(img_data)[:100]}"
        return f"スクリーンショット失敗: {response.get('error', '不明')}"
    except Exception as e:
        return f"スクリーンショットエラー: {e}"


# --- #6: 直接SNS投稿 ---

@_register("post_sns")
async def post_to_sns(args: str = "") -> str:
    """SNSに直接投稿。形式: platform|内容
    platform: x_shimahara, x_syutain, bluesky, threads"""
    parts = args.split("|", 1)
    if len(parts) < 2:
        return "形式: [ACTION:post_sns:bluesky|投稿内容] — 対応: x_shimahara, x_syutain, bluesky, threads"

    platform_key = parts[0].strip().lower()
    content = parts[1].strip()

    if not content:
        return "投稿内容が空です。"

    # NGワードチェック
    try:
        from tools.platform_ng_check import check_platform_ng
        platform_for_check = "x" if "x_" in platform_key else platform_key
        ng = check_platform_ng(content, platform_for_check)
        if not ng["passed"]:
            return f"NGワード検出: {ng['violations']}"
    except Exception as e:
        logger.warning(f"NGチェック失敗（投稿は続行）: {e}")

    # 承認キューに入れる（直接投稿ではなく、承認後に投稿）
    try:
        async with get_connection() as conn:
            platform = "x" if "x_" in platform_key else platform_key
            account = "shimahara" if platform_key == "x_shimahara" else "syutain"

            post_id = await conn.fetchval(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category)
                   VALUES ($1, $2, $3, NOW(), 'pending', 0.80, 'manual')
                   RETURNING id""",
                platform, account, content,
            )
            return f"投稿キューに追加 (#{post_id})。次の毎分投稿ジョブで送信されます。\n{platform}/{account}: {content[:60]}"
    except Exception as e:
        return f"投稿キュー追加失敗: {e}"


# --- #7: 商品パッケージ管理 ---

@_register("packages_list")
async def packages_list(args: str = "") -> str:
    """承認待ち商品パッケージ一覧"""
    try:
        from brain_alpha.product_packager import get_pending_packages
        packages = await get_pending_packages()
        if not packages:
            return "📦 承認待ちパッケージはありません"
        lines = ["📦 **承認待ちパッケージ一覧**"]
        for p in packages:
            tags = json.loads(p["tags"]) if isinstance(p["tags"], str) else (p["tags"] or [])
            lines.append(
                f"  #{p['id']} | {p['title'][:40]} | ¥{p['price_jpy']} | {p['category'] or '-'} | {', '.join(tags[:3])}"
            )
        lines.append(f"\n承認: [ACTION:package_approve:ID]  却下: [ACTION:package_reject:ID]")
        return "\n".join(lines)
    except Exception as e:
        return f"パッケージ一覧取得失敗: {e}"


@_register("package_approve")
async def package_approve(args: str = "") -> str:
    """商品パッケージを承認。形式: ID"""
    try:
        pkg_id = int(args.strip())
    except (ValueError, TypeError):
        return "形式: [ACTION:package_approve:ID]（IDは数値）"
    try:
        from brain_alpha.product_packager import approve_package
        result = await approve_package(pkg_id)
        if result["status"] == "approved":
            return f"✅ パッケージ #{pkg_id}『{result.get('title', '')}』を承認しました"
        elif result["status"] == "not_found":
            return f"パッケージ #{pkg_id} が見つかりません"
        return f"承認失敗: {result}"
    except Exception as e:
        return f"パッケージ承認失敗: {e}"


@_register("package_reject")
async def package_reject(args: str = "") -> str:
    """商品パッケージを却下。形式: ID|理由"""
    parts = args.split("|", 1)
    try:
        pkg_id = int(parts[0].strip())
    except (ValueError, TypeError):
        return "形式: [ACTION:package_reject:ID] または [ACTION:package_reject:ID|理由]"
    reason = parts[1].strip() if len(parts) > 1 else ""
    try:
        from brain_alpha.product_packager import reject_package
        result = await reject_package(pkg_id, reason)
        if result["status"] == "rejected":
            return f"❌ パッケージ #{pkg_id} を却下しました"
        elif result["status"] == "not_found":
            return f"パッケージ #{pkg_id} が見つかりません"
        return f"却下失敗: {result}"
    except Exception as e:
        return f"パッケージ却下失敗: {e}"


@_register("package_preview")
async def package_preview(args: str = "") -> str:
    """商品パッケージのプレビュー。形式: ID"""
    try:
        pkg_id = int(args.strip())
    except (ValueError, TypeError):
        return "形式: [ACTION:package_preview:ID]（IDは数値）"
    try:
        from brain_alpha.product_packager import preview_package
        pkg = await preview_package(pkg_id)
        if "error" in pkg:
            return f"プレビュー取得失敗: {pkg['error']}"
        tags = json.loads(pkg["tags"]) if isinstance(pkg["tags"], str) else (pkg["tags"] or [])
        preview_text = (pkg.get("body_preview") or "")[:300]
        return (
            f"📦 **パッケージ #{pkg['id']}**\n"
            f"タイトル: {pkg['title']}\n"
            f"価格: ¥{pkg['price_jpy']}\n"
            f"カテゴリ: {pkg.get('category', '-')}\n"
            f"タグ: {', '.join(tags)}\n"
            f"ステータス: {pkg['status']}\n"
            f"---\n{preview_text}..."
        )
    except Exception as e:
        return f"プレビュー取得失敗: {e}"


# --- #8: リマインダー ---

@_register("remind")
async def set_reminder(args: str = "") -> str:
    """リマインダー設定。形式: 時間|内容
    例: 7:00|note記事を確認する, 30m|ゴールの進捗確認"""
    parts = args.split("|", 1)
    if len(parts) < 2:
        return "形式: [ACTION:remind:7:00|内容] または [ACTION:remind:30m|内容]"

    time_str = parts[0].strip()
    message = parts[1].strip()

    try:
        from datetime import datetime, timedelta, timezone
        import re
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST)

        # 相対時間（30m, 1h等）
        rel_match = re.match(r'(\d+)\s*(m|min|h|hour)', time_str, re.IGNORECASE)
        if rel_match:
            amount = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if unit.startswith("h"):
                remind_at = now + timedelta(hours=amount)
            else:
                remind_at = now + timedelta(minutes=amount)
        else:
            # 絶対時間（HH:MM）
            hour, minute = map(int, time_str.split(":"))
            remind_at = now.replace(hour=hour, minute=minute, second=0)
            if remind_at <= now:
                remind_at += timedelta(days=1)

        # posting_queueにリマインダーとして保存（platform='reminder'）
        async with get_connection() as conn:
            rid = await conn.fetchval(
                """INSERT INTO posting_queue
                   (platform, account, content, scheduled_at, status, quality_score, theme_category)
                   VALUES ('reminder', 'daichi', $1, $2, 'pending', 1.0, 'reminder')
                   RETURNING id""",
                f"🔔 リマインダー: {message}", remind_at,
            )
        return f"リマインダー設定完了 (#{rid}): {remind_at.strftime('%m/%d %H:%M')} — {message}"
    except Exception as e:
        return f"リマインダー設定失敗: {e}"


# === Brain-α(Claude Code)関連アクション ===

@_register("escalate_alpha")
async def escalate_to_alpha(instruction: str = "") -> dict:
    """Brain-βからBrain-α(Claude Code)に指示を送信（三重経路）"""
    if not instruction:
        return {"error": "指示内容が必要です"}
    try:
        from bots.bot_escalation import send_instruction_to_brain_alpha
        await send_instruction_to_brain_alpha(
            instruction,
            context={"source": "discord_action", "triggered_by": "daichi"},
            priority="high",
        )
        return {"status": "sent", "instruction": instruction[:200], "routes": "DB+Webhook+Discord"}
    except Exception as e:
        return {"error": f"Brain-α送信失敗: {e}"}


@_register("alpha_queue_status")
async def get_alpha_queue_status() -> dict:
    """Brain-α指示キューの状態を取得"""
    try:
        async with get_connection() as conn:
            pending = await conn.fetch(
                """SELECT id, category, description, priority, source_agent, created_at
                   FROM claude_code_queue WHERE status='pending'
                   ORDER BY created_at DESC LIMIT 5"""
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM claude_code_queue WHERE status='pending'"
            ) or 0
            completed_24h = await conn.fetchval(
                "SELECT COUNT(*) FROM claude_code_queue WHERE status='completed' AND created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
        items = []
        for p in pending:
            items.append({
                "id": p["id"],
                "category": p["category"],
                "desc": (p["description"] or "")[:80],
                "priority": p["priority"],
                "from": p["source_agent"],
                "at": _to_jst(p["created_at"]),
            })
        return {
            "pending": total,
            "completed_24h": completed_24h,
            "items": items,
        }
    except Exception as e:
        return {"error": f"キュー取得失敗: {e}"}
