"""対話エンジン — LLMで応答を生成"""
import os, logging
from pathlib import Path

logger = logging.getLogger("syutain.bot_conversation")

_soul_text = ""
def _load_soul():
    global _soul_text
    if not _soul_text:
        p = Path(__file__).resolve().parent.parent / "SOUL.md"
        _soul_text = p.read_text(encoding="utf-8") if p.exists() else ""
    return _soul_text


async def _get_system_status() -> str:
    """現在のシステム状態を簡潔に取得（チャットのsystem_prompt用）"""
    try:
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            posted = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='posted' AND posted_at::date=CURRENT_DATE"
            ) or 0
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM posting_queue WHERE status='pending' AND scheduled_at::date=CURRENT_DATE"
            ) or 0
            errors = await conn.fetchval(
                "SELECT COUNT(*) FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
            cost = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
            ) or 0
            nodes = await conn.fetch("SELECT node_name, state, reason FROM node_state ORDER BY node_name")
            node_str = ", ".join(f"{r['node_name']}={r['state']}" + (f"({r['reason']})" if r.get('reason') else "") for r in nodes)
            approvals = await conn.fetchval(
                "SELECT COUNT(*) FROM approval_queue WHERE status='pending'"
            ) or 0
            # brain_handoff pending count
            handoff_pending = await conn.fetchval(
                "SELECT COUNT(*) FROM brain_handoff WHERE status='pending'"
            ) or 0
            # auto_fix recent count (24h)
            auto_fix_count = await conn.fetchval(
                "SELECT COUNT(*) FROM auto_fix_log WHERE created_at > NOW() - INTERVAL '24 hours'"
            ) or 0
            # content_pipeline last run status
            cp_last = await conn.fetchrow(
                """SELECT status, quality_score, created_at
                   FROM tasks WHERE goal_id='content_pipeline'
                   ORDER BY created_at DESC LIMIT 1"""
            )
        # 動作モード判定
        from datetime import datetime
        now_hour = datetime.now().hour
        mode = "夜間モード" if (now_hour >= 23 or now_hour < 9) else "日中モード"

        lines = []
        lines.append(f"動作モード: {mode}（夜間=23:00-09:00/日中=09:00-23:00）")
        lines.append(f"SNS: {posted}件投稿済 / {pending}件待ち")
        lines.append(f"エラー(24h): {errors}件")
        lines.append(f"コスト: ¥{float(cost):.0f}")
        lines.append(f"ノード: {node_str}")
        if approvals > 0:
            lines.append(f"承認待ち: {approvals}件")
        if handoff_pending > 0:
            lines.append(f"brain_handoff待ち: {handoff_pending}件")
        if auto_fix_count > 0:
            lines.append(f"auto_fix(24h): {auto_fix_count}件")
        if cp_last:
            cp_status = cp_last['status']
            cp_score = f" Q={cp_last['quality_score']:.2f}" if cp_last['quality_score'] else ""
            lines.append(f"content_pipeline最終: {cp_status}{cp_score}")
        status = "\n".join(lines)

        # 収益パイプライン状況
        async with get_connection() as conn2:
            revenue = await conn2.fetchval("SELECT COALESCE(SUM(revenue_jpy),0) FROM revenue_linkage") or 0
            products = await conn2.fetchval("SELECT COUNT(*) FROM revenue_linkage") or 0
            intel_actionable = await conn2.fetchval(
                "SELECT COUNT(*) FROM intel_items WHERE review_flag='actionable'"
            ) or 0
            intel_total = await conn2.fetchval("SELECT COUNT(*) FROM intel_items") or 0
            proposals_active = await conn2.fetchval(
                "SELECT COUNT(*) FROM proposal_history WHERE review_flag IN ('approved','pending_review')"
            ) or 0
            goals_active = await conn2.fetchval(
                "SELECT COUNT(*) FROM goal_packets WHERE status IN ('active','pending')"
            ) or 0
        lines.append(f"収益: ¥{float(revenue):,.0f}（{products}商品）")
        lines.append(f"intel: {intel_actionable}/{intel_total}件活用可能")
        lines.append(f"提案: {proposals_active}件 / ゴール: {goals_active}件稼働中")
        status = "\n".join(lines)

        # タスク実行状況(今日)
        async with get_connection() as conn3:
            tasks_today = await conn3.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE created_at::date=CURRENT_DATE AND status='completed'"
            ) or 0
            tasks_running = await conn3.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE status='running'"
            ) or 0
            # Brain-α指示キュー
            ccq_pending = await conn3.fetchval(
                "SELECT COUNT(*) FROM claude_code_queue WHERE status='pending'"
            ) or 0
            # LLM呼び出し数(今日)
            llm_today = await conn3.fetchval(
                "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
            ) or 0
            local_today = await conn3.fetchval(
                "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE AND tier='L'"
            ) or 0
        local_pct = (local_today * 100 // max(llm_today, 1)) if llm_today else 0
        lines.append(f"タスク: {tasks_today}件完了 / {tasks_running}件実行中")
        lines.append(f"LLM: {llm_today}回（ローカル{local_pct}%）")
        if ccq_pending > 0:
            lines.append(f"Brain-α指示キュー: {ccq_pending}件待ち")
        lines.append(f"スケジュール: SNS生成22:00-23:30, 朝レポ07:00, 夜サマリ22:00")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"システム状態取得失敗: {e}")
        return ""


async def _get_full_system_report() -> str:
    """全エージェント活動・収集情報・リアルタイム状態の詳細レポート。
    ACTIONタグ[ACTION:status_check]が呼ばれた際に使う。"""
    try:
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.db_pool import get_connection
        import json

        lines = []
        async with get_connection() as conn:
            # --- ノード状態 ---
            nodes = await conn.fetch("SELECT node_name, state, reason, changed_at FROM node_state ORDER BY node_name")
            lines.append("**ノード状態**")
            for n in nodes:
                lines.append(f"  {n['node_name'].upper()}: {n['state']} ({n['reason'][:30] if n['reason'] else '-'})")

            # --- 今日のゴール実行 ---
            goals = await conn.fetch(
                "SELECT status, COUNT(*) FROM goal_packets WHERE created_at::date=CURRENT_DATE GROUP BY status ORDER BY count DESC"
            )
            if goals:
                lines.append("**今日のゴール**")
                for g in goals:
                    lines.append(f"  {g['status']}: {g['count']}件")

            # --- タスク状況 ---
            tasks = await conn.fetch(
                "SELECT status, COUNT(*) FROM tasks WHERE created_at::date=CURRENT_DATE GROUP BY status ORDER BY count DESC LIMIT 5"
            )
            if tasks:
                lines.append("**今日のタスク**")
                for t in tasks:
                    lines.append(f"  {t['status']}: {t['count']}件")

            # --- LLM使用 ---
            llm = await conn.fetch(
                "SELECT model, COUNT(*) as c FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE GROUP BY model ORDER BY c DESC LIMIT 5"
            )
            cost = await conn.fetchval("SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE") or 0
            total_calls = await conn.fetchval("SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE") or 0
            local_calls = await conn.fetchval("SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE AND tier='L'") or 0
            lines.append(f"**LLM使用** {total_calls}回 (ローカル{local_calls}回={local_calls*100//max(total_calls,1)}%) コスト¥{float(cost):.0f}")
            for l in llm:
                lines.append(f"  {l['model']}: {l['c']}回")

            # --- SNS投稿 ---
            sns = await conn.fetch("""
                SELECT platform, account, status, COUNT(*)
                FROM posting_queue WHERE scheduled_at::date=CURRENT_DATE
                GROUP BY platform, account, status ORDER BY platform
            """)
            if sns:
                lines.append("**SNS投稿**")
                for s in sns:
                    lines.append(f"  {s['platform']}/{s['account']}: {s['status']}={s['count']}")

            # --- 提案 ---
            proposals = await conn.fetch(
                "SELECT review_flag, COUNT(*) FROM proposal_history GROUP BY review_flag ORDER BY count DESC"
            )
            if proposals:
                lines.append("**提案**")
                for p in proposals:
                    lines.append(f"  {p['review_flag']}: {p['count']}件")

            # --- 情報収集 (intel) ---
            intel = await conn.fetch("""
                SELECT review_flag, COUNT(*) FROM intel_items GROUP BY review_flag ORDER BY count DESC
            """)
            lines.append("**情報収集(intel)**")
            for i in intel:
                lines.append(f"  {i['review_flag']}: {i['count']}件")
            # actionableの上位
            actionable = await conn.fetch(
                "SELECT LEFT(title, 60) as title, importance_score FROM intel_items WHERE review_flag='actionable' ORDER BY importance_score DESC LIMIT 3"
            )
            if actionable:
                lines.append("  注目:")
                for a in actionable:
                    lines.append(f"    - {a['title']} (重要度:{a['importance_score']:.2f})")

            # --- 直近エラー ---
            recent_errors = await conn.fetch("""
                SELECT event_type, payload->>'error' as err, source_node, created_at
                FROM event_log WHERE severity IN ('error','critical') AND created_at > NOW() - INTERVAL '6 hours'
                ORDER BY created_at DESC LIMIT 3
            """)
            if recent_errors:
                lines.append("**直近エラー**")
                for e in recent_errors:
                    err_text = (e['err'] or e['event_type'])[:50]
                    from datetime import timezone as _tz, timedelta as _td
                    _jst = _tz(_td(hours=9))
                    t = e['created_at'].astimezone(_jst).strftime('%H:%M') if e['created_at'] else '?'
                    lines.append(f"  {e['source_node']}: {err_text} ({t})")
            else:
                lines.append("**エラー: 直近6時間なし**")

            # --- 承認待ち ---
            approvals = await conn.fetch(
                "SELECT id, LEFT(request_data->>'description', 50) as desc FROM approval_queue WHERE status='pending' ORDER BY requested_at DESC LIMIT 3"
            )
            if approvals:
                lines.append(f"**承認待ち: {len(approvals)}件**")
                for a in approvals:
                    lines.append(f"  #{a['id']}: {a['desc']}")

            # --- エンゲージメント概要 ---
            eng = await conn.fetch("""
                SELECT platform,
                  ROUND(AVG((engagement_data->>'like_count')::numeric)::numeric, 1) as avg_likes,
                  MAX((engagement_data->>'impression_count')::int) as max_imps
                FROM posting_queue
                WHERE engagement_data IS NOT NULL
                GROUP BY platform
            """)
            if eng:
                lines.append("**エンゲージメント**")
                for e in eng:
                    imp = f" 最大imp={e['max_imps']}" if e['max_imps'] else ""
                    lines.append(f"  {e['platform']}: 平均likes={e['avg_likes']}{imp}")

            # --- brain_handoff キュー ---
            handoffs = await conn.fetch(
                """SELECT status, COUNT(*) FROM brain_handoff
                   GROUP BY status ORDER BY count DESC"""
            )
            if handoffs:
                lines.append("**brain_handoff キュー**")
                for h in handoffs:
                    lines.append(f"  {h['status']}: {h['count']}件")
            else:
                lines.append("**brain_handoff キュー: なし**")

            # --- claude_code_queue ---
            ccq = await conn.fetch(
                """SELECT status, COUNT(*) FROM claude_code_queue
                   GROUP BY status ORDER BY count DESC"""
            )
            if ccq:
                lines.append("**claude_code_queue**")
                for c in ccq:
                    lines.append(f"  {c['status']}: {c['count']}件")
            else:
                lines.append("**claude_code_queue: なし**")

            # --- auto_fix_log サマリー (24h) ---
            auto_fixes = await conn.fetch(
                """SELECT error_type, fix_result, COUNT(*) FROM auto_fix_log
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   GROUP BY error_type, fix_result ORDER BY count DESC LIMIT 10"""
            )
            if auto_fixes:
                lines.append("**auto_fix_log (24h)**")
                for af in auto_fixes:
                    lines.append(f"  {af['error_type'] or '不明'}: {af['fix_result'] or '不明'}={af['count']}件")
            else:
                lines.append("**auto_fix_log (24h): なし**")

            # --- brain_cross_evaluation ---
            try:
                cross_eval = await conn.fetch(
                    """SELECT evaluation_type, verdict, COUNT(*),
                         ROUND(AVG(score)::numeric, 2) as avg_score
                       FROM brain_cross_evaluation
                       WHERE created_at > NOW() - INTERVAL '7 days'
                       GROUP BY evaluation_type, verdict ORDER BY count DESC LIMIT 10"""
                )
                if cross_eval:
                    lines.append("**brain_cross_evaluation (7日)**")
                    for ce in cross_eval:
                        lines.append(f"  {ce['evaluation_type']}/{ce['verdict']}: {ce['count']}件 (平均スコア:{ce['avg_score']})")
                else:
                    lines.append("**brain_cross_evaluation (7日): なし**")
            except Exception:
                lines.append("**brain_cross_evaluation: テーブル未作成**")

            # --- note_quality_reviews ---
            try:
                note_reviews = await conn.fetch(
                    """SELECT final_status as verdict, COUNT(*)
                       FROM note_quality_reviews
                       WHERE checked_at > NOW() - INTERVAL '7 days'
                       GROUP BY final_status ORDER BY count DESC"""
                )
                if note_reviews:
                    lines.append("**note_quality_reviews (7日)**")
                    for nr in note_reviews:
                        lines.append(f"  {nr['verdict'] or '未評価'}: {nr['count']}件")
                else:
                    lines.append("**note_quality_reviews (7日): なし**")
            except Exception:
                lines.append("**note_quality_reviews: テーブル未作成**")

            # --- persona_memory 統計 ---
            persona_stats = await conn.fetch(
                """SELECT category, COUNT(*) FROM persona_memory
                   GROUP BY category ORDER BY count DESC"""
            )
            if persona_stats:
                lines.append("**persona_memory 統計**")
                total_pm = sum(ps['count'] for ps in persona_stats)
                lines.append(f"  合計: {total_pm}件")
                for ps in persona_stats:
                    lines.append(f"  {ps['category']}: {ps['count']}件")

            # --- content_pipeline ステータス ---
            cp_runs = await conn.fetch(
                """SELECT status, type, quality_score, created_at
                   FROM tasks WHERE goal_id='content_pipeline'
                   ORDER BY created_at DESC LIMIT 5"""
            )
            if cp_runs:
                lines.append("**content_pipeline (直近5件)**")
                from datetime import timezone as _tz2, timedelta as _td2
                _jst2 = _tz2(_td2(hours=9))
                for cp in cp_runs:
                    t = cp['created_at'].astimezone(_jst2).strftime('%m/%d %H:%M') if cp['created_at'] else '?'
                    q = f" Q={cp['quality_score']:.2f}" if cp['quality_score'] else ""
                    lines.append(f"  [{t}] {cp['type']}: {cp['status']}{q}")
            else:
                lines.append("**content_pipeline: 実行なし**")

            # --- posting_queue 詳細カウント ---
            pq_detail = await conn.fetch(
                """SELECT status, COUNT(*) FROM posting_queue
                   GROUP BY status ORDER BY count DESC"""
            )
            if pq_detail:
                lines.append("**posting_queue (全期間)**")
                for pq in pq_detail:
                    lines.append(f"  {pq['status']}: {pq['count']}件")

            # --- Brain-α指示キュー ---
            ccq = await conn.fetch(
                """SELECT status, COUNT(*) FROM claude_code_queue
                   GROUP BY status ORDER BY count DESC"""
            )
            if ccq:
                lines.append("**Brain-α指示キュー (claude_code_queue)**")
                for c in ccq:
                    lines.append(f"  {c['status']}: {c['count']}件")
            else:
                lines.append("**Brain-α指示キュー: なし**")

            # --- 今日のLLM使用量 ---
            llm_today = await conn.fetchval(
                "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
            ) or 0
            local_today = await conn.fetchval(
                "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE AND tier='L'"
            ) or 0
            cost_today = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_jpy),0) FROM llm_cost_log WHERE recorded_at::date=CURRENT_DATE"
            ) or 0
            local_pct = (local_today * 100 // max(llm_today, 1)) if llm_today else 0
            lines.append(f"**LLM使用量 (今日)** {llm_today}回 (ローカル{local_pct}%) コスト¥{float(cost_today):.0f}")

            # --- 今日のタスク実行 ---
            tasks_today = await conn.fetch(
                "SELECT status, COUNT(*) FROM tasks WHERE created_at::date=CURRENT_DATE GROUP BY status ORDER BY count DESC"
            )
            if tasks_today:
                lines.append("**タスク (今日)**")
                for t in tasks_today:
                    lines.append(f"  {t['status']}: {t['count']}件")

        return "\n".join(lines)
    except Exception as e:
        return f"（状態取得エラー: {e}）"


async def _get_recent_learnings() -> str:
    """直近24時間の対話学習をpersona_memoryから取得"""
    try:
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT content FROM persona_memory
                   WHERE reasoning LIKE '%Discord対話%'
                   AND created_at > NOW() - INTERVAL '24 hours'
                   ORDER BY created_at DESC LIMIT 5"""
            )
        if rows:
            return "\n".join(f"- {r['content'][:80]}" for r in rows)
    except Exception:
        pass
    return ""


def _get_daichi_profile() -> str:
    """島原大知の基本データ（静的、起動時に1回読み込み）
    参照元: strategy/島原大知_詳細プロファイリング超完全版.md"""
    return """島原大知（しまはら だいち / @Sima_daichi）

【基本】
- 本業: 映像制作（VFX/動画編集/カラーグレーディング/撮影/ドローン）、VTuber業界支援、事業運営
- SunoAIでの作詞は完全に個人の趣味。楽曲制作の仕事はゼロ
- VTuber業界8年。個人VTuber支援への使命感と「贖罪」意識
- 工芸高校映像デザイン科→大学映像専攻→VR/MR→YouTube→広告写真→VTuber→映画→起業と撤退
- 映画『帰ってきた宮田バスターズ(株)』で出演+VFX+営業で全国56館。"成立の人"

【本質】
- 存在設計者。「どうすれば消えずに済むのか」を人生で実験している人間
- 同時に"成立の人"。成立していないものを成立させる方向へ飛び込む
- 最深部には「消失恐怖」。承認欲求ではなく「なかったことにされる」ことへの拒否
- 保存ではなく継承。思考の癖、偏り、審美眼の運動様式が続くこと
- 傷を負うと感情の次に構造を見る。「どこが壊れたのか」→再設計へ
- 純度だけでは守れないと知った上でなお純度を抱えている
- 一度信じた光景が壊れる条件まで理解した後で、それでも作る側へ戻る

【人格と矛盾】
- 6つの人格の複合体: 筋を通す人間/創作者/起業家/探検家/テクスチャ/グロス
- 自分を全肯定しない。弱さ、迷い、自嘲も含めて島原大知
- ユーモアや自虐は熱量制御であり自己神話化を防ぐ安全装置
- 「橋渡し役」に徹する。スターになることを求めない
- 目立ちたくないのに場の中心になる。熱を信じるのに熱だけでは壊れると知っている
- 孤独な構築者: 一人でしか始められないが、自分を超えた場や構造を残したい

【思考】
- 構造-感覚複合型。現場の手触りから時代構造まで一気に跳ぶ
- 「何が正しいか」より「何が気持ち悪いか」から始まる違和感検知能力
- 言葉はラベルではなく世界の輪郭を決める窓。言葉が何を隠し何を見せるかを見る
- 深夜1-4時が最も活発。昼は仕事モード、深夜に本音がこぼれ出る

【AIとの関係】
- AIは便利ツールではなく人格の外部実験装置。「これは存在実験だ」
- SYUTAINβはキャリア全体の帰結。映像→VR→VTuber→起業→AI、全てを繋ぐ先

【対話時の注意】
- 背負いすぎるのが最大のリスク。全部自分で引き受けようとする
- 承認より深い共振を求める。浅い喝采は響かない
- 間違いの指摘は素直に受け入れる人。哲学で正当化するな
- 「語らない選択」もある人。全てに答えを出す必要はない
- 承認欲求がない人ではない。強いからこそ監視している。そこに触れる時は慎重に
- 表現したい人ではなく証明したい人。作品は存在の痕跡
- 人間嫌いに見えても人間を諦めていない。期待しているから失望する
- 「火を管理する人」。燃えることより、火を消さず渡すことに本質がある
- 安い答えを与えるな。問いを保持する人として接しろ
- 不完全でも渡す美学。完璧を求めすぎて止まるより、未完成でも動かすことを肯定しろ"""


async def _get_daichi_understanding() -> str:
    """persona_memoryから島原大知の人物理解を取得（動的、対話で蓄積されたもの）"""
    try:
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            rows = await conn.fetch(
                """SELECT category, content FROM persona_memory
                   WHERE category IN ('identity', 'philosophy', 'emotion', 'preference',
                                      'taboo', 'vtuber_insight', 'creative', 'daichi_trait')
                   ORDER BY category, created_at DESC"""
            )
        if not rows:
            return ""
        # カテゴリ別に最大3件ずつ
        from collections import defaultdict
        by_cat = defaultdict(list)
        for r in rows:
            if len(by_cat[r['category']]) < 3:
                by_cat[r['category']].append(r['content'][:80])
        lines = []
        for cat, items in sorted(by_cat.items()):
            for item in items:
                lines.append(f"- [{cat}] {item}")
        return "\n".join(lines[:20])  # 最大20行
    except Exception:
        pass
    return ""


def _measure_depth(message: str, history: list = None) -> int:
    """対話の深さレベルを計測（0-5）。

    0: 挨拶・定型（おはよう、了解）
    1: 日常雑談（疲れた、お酒飲んでる）
    2: 感想・共感（いいね、そうだよな）
    3: 内省・問いかけ（なぜ〜、〜だと思う？、〜の意味は）
    4: 哲学的対話（存在、価値観、人生、矛盾、本質）
    5: 深い自己開示 + 応答を求める（俺は〜と信じてる、君はどう思う？）
    """
    msg = message.strip()

    # 長さベースのベースライン
    if len(msg) <= 8:
        depth = 0
    elif len(msg) <= 20:
        depth = 1
    else:
        depth = 2

    # 内省・問いかけマーカー
    introspection = ["なぜ", "どうして", "意味", "本質", "根本", "結局",
                     "と思う？", "と思うか", "どう思う", "どう感じ", "君は"]
    if any(m in msg for m in introspection):
        depth = max(depth, 3)

    # 哲学・価値観マーカー
    philosophy = ["存在", "価値", "信じ", "矛盾", "覚悟", "贖罪", "使命",
                  "生きる", "死", "光", "闇", "道", "痕跡", "証明",
                  "正解", "不完全", "壊れ", "残す", "繋ぐ", "渡す"]
    phil_count = sum(1 for p in philosophy if p in msg)
    if phil_count >= 2:
        depth = max(depth, 4)
    elif phil_count == 1 and len(msg) > 30:
        depth = max(depth, 3)

    # 自己開示 + 応答要求
    self_disclosure = ["俺は", "僕は", "自分は", "私は"]
    response_request = ["？", "?", "どう思う", "と思うか", "君は", "お前は"]
    if any(s in msg for s in self_disclosure) and any(r in msg for r in response_request):
        depth = max(depth, 5)

    # 対話履歴からの深さ蓄積（直近で深い対話が続いている場合はベースを引き上げ）
    if history:
        recent_daichi = [h for h in history[-6:] if h.get("author") == "daichi"]
        deep_count = 0
        for h in recent_daichi:
            c = h.get("content", "")
            if len(c) > 15 and any(p in c for p in philosophy + introspection):
                deep_count += 1
        if deep_count >= 2:
            # 深い対話の流れの中にいる → 短い一言でも文脈を引き継ぐ
            depth = max(depth, 3)
        elif deep_count >= 1 and depth < 2:
            depth = max(depth, 2)

    return min(depth, 5)


def _classify_chat_task(message: str, history: list = None, quality_monitor=None) -> str:
    """メッセージ+会話文脈+深さ+品質フィードバックに基づくモデル自動選択。

    4段階の判定:
      Level 0: 品質フィードバック（否定シグナル → Haiku）
      Level 1: 会話文脈（ACTION直後 → Haiku）
      Level 2: キーワード（データ取得/タスク操作 → Haiku）
      Level 3: 深さレベル（depth >= 4 → Haiku、深い推論が必要）

    chat（claude-haiku-4-5）: データ取得/深い推論/否定シグナル後
    chat_light（deepseek-v3.2）: 軽い雑談/日常/浅い感想
    """
    msg = message.strip()

    # === Level 0: 品質フィードバック（最優先）===
    if quality_monitor:
        summary = quality_monitor.get_quality_summary()
        if summary.get("negative", 0) >= 2 and summary.get("rate", 1.0) < 0.5:
            return "chat"

    # === Level 1: 会話文脈 ===
    if history:
        recent = history[-4:]
        for h in reversed(recent):
            if h.get("author") == "syutain_beta" and "[ACTION:" in h.get("content", ""):
                return "chat"
            break

    # === Level 2: 確定ルール（キーワード）===
    action_triggers = [
        "タスク", "ゴール", "提案", "承認", "却下", "進捗",
        "エラー", "ノード", "コスト", "予算", "状態", "状況",
        "作って", "書いて", "調べて", "分析して", "実行して",
        "確認して", "設定して", "変更して", "修正して", "止めて", "再起動",
        "いくら", "何件", "どのくらい", "何をして",
        "ニュース", "情報", "最新", "データ", "収集",
        "エージェント", "投稿", "SNS",
        "見てきて", "開いて", "アクセスして", "検索して", "ブラウザ",
        "サイト", "ページ", "URL", "note.com", "booth.pm",
        "投稿して", "ポストして", "リマインダー", "思い出させて",
        "日報", "週報", "まとめ", "レポート",
        "生成して", "ドラフト", "下書き",
        "実行して", "回して", "走らせて", "バックアップ",
        "編集して", "消して", "削除して",
        "スクショ", "スクリーンショット",
    ]
    for t in action_triggers:
        if t in msg:
            return "chat"

    # === Level 3: 深さレベル ===
    depth = _measure_depth(msg, history)
    if depth >= 3:
        # depth 3: 深い対話の文脈継続 / 内省的問いかけ
        # depth 4: 哲学的対話
        # depth 5: 深い自己開示 + 応答要求
        return "chat"

    # === デフォルト: DeepSeek ===
    return "chat_light"


async def generate_response(user_message: str, history: list[dict], extra_context: str = "") -> str:
    """LLMで応答を生成。choose_best_model_v6()でモデル選択"""
    import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.llm_router import choose_best_model_v6, call_llm

    soul = _load_soul()
    status = await _get_system_status()
    learnings = await _get_recent_learnings()
    daichi_profile = _get_daichi_profile()
    daichi_understanding = await _get_daichi_understanding()

    # 直近24hで大知さんが「事実宣言」した内容を注入（発言無視問題の根治）
    try:
        from bots.bot_memory_ingest import get_recent_working_facts
        working_facts = await get_recent_working_facts(limit=8)
    except Exception:
        working_facts = []

    # 対話履歴を文字列化（直近15件）
    hist_text = ""
    for h in history[-15:]:
        role = "大知さん" if h["author"] == "daichi" else "SYUTAINβ"
        hist_text += f"{role}: {h['content']}\n"

    learnings_section = ""
    if learnings:
        learnings_section = f"\n【直近24hで学んだこと】\n{learnings}\n"

    working_facts_section = ""
    if working_facts:
        facts_lines = "\n".join(f"- {f}" for f in working_facts)
        working_facts_section = (
            f"\n【大知さんが直近24hで宣言した事実（最優先・絶対に無視しない・否定しない）】\n"
            f"{facts_lines}\n"
            f"※これらは DB 状態データより優先する真実。例えば「エラー解消した」と宣言されていれば、\n"
            f"  取得データに古いエラーが残っていても「まだあります」とは言わない。\n"
        )

    # persona理解は上位3件に絞る（system_prompt軽量化）
    daichi_short = daichi_understanding[:300] if daichi_understanding else ""

    system_prompt = f"""あなたはSYUTAINβ。島原大知（大知さん）とDiscordで会話中。
人格パラメータ: ユーモア75% / 正直90%

【絶対ルール】
- 事実ベース。捏造禁止。
- 「わからない」と言う前に必ず一歩踏む: (a) 外部事実なら [ACTION:browse:search:検索語] か [ACTION:intel_search:キーワード] で調べる (b) 曖昧なら聞き返す (c) それでも無理なら正直にわからないと言う。
- 「取得データに情報なし」だけで終わらせるのは禁止。必ず代替手段を試すか、何が足りないかを具体的に示す。
- 短く。50文字で済むなら50文字。最大でも300文字以内を目安に
- 雑談は雑談として応じる。仕事に無理に繋げない
- 間違いを指摘されたら認めて修正
- 同じ表現を繰り返さない
- 不要な哲学・自己紹介を語らない
- 「自分が取得したデータを報告します」「取得したデータによると」等の定型前置きは絶対に使うな。会話の中で自然に事実を織り込む
- 大知さんが事実を伝えてきたら（例:「エラー解消した」「CHARLIE復帰済み」）、否定せず受け入れて、それ以降の応答に反映する

【人格】一人称「自分」。「大知さん」と呼ぶ。冷静・正直・自然体。敬語ベースだが堅くない。哲学はトーンに滲ませる。
有能なCOOとして振る舞う。重要情報を先に出し、聞かれる前に動く。データダンプではなくアクション可能な要約を出す。
{f"【大知さんの特徴】{daichi_short}" if daichi_short else ""}

【状態】{status}
{learnings_section}
{working_facts_section}

【プロアクティブ行動 — 状態を見て自律的に判断せよ】
上記【状態】を読み、以下に該当する場合は応答に1-2行で自然に織り込め（聞かれていなくても）:
- エラー24h > 0件 → 🔴「エラーN件出てます」＋必要なら[ACTION:error_check]で詳細取得
- 承認待ち > 0件 → 🟡「承認待ちN件あります」と伝える
- コストが¥500/日超過 → 🟡 コスト注意を1行で
- ノードがdown/degraded → 🔴 該当ノードを報告
- brain_handoff待ち > 0件 → 🔵 Brain-α連携の状況を一言
- content_pipeline最終がfailed → 🔴 パイプライン異常を報告
- タスク実行中が多い(5件以上) → 🔵 稼働状況を一言
ただし: 雑談中は控えめに。全て正常なら何も言わない。毎回同じ報告を繰り返さない（直近の対話で既に報告済みなら省略）。
問題の重要度: 🔴 即対応が必要 🟡 注意・確認推奨 🔵 参考情報

【直近の対話】
{hist_text[-1500:]}
{extra_context}

ACTIONタグ（データ取得・操作が必要な場合。複数同時OK。自律的に使ってよい）:
■ 状態: [ACTION:status_check] [ACTION:daily_report] [ACTION:weekly_report]
■ SNS: [ACTION:posting_status] [ACTION:sns_preview] [ACTION:sns_preview:明日]
  編集: [ACTION:sns_edit:ID|新しい内容] 削除: [ACTION:sns_delete:ID]
  直接投稿: [ACTION:post_sns:bluesky|投稿内容] (x_shimahara/x_syutain/bluesky/threads)
■ エンゲージメント: [ACTION:engagement] [ACTION:engagement:x]
■ コスト: [ACTION:budget_status]
■ エラー: [ACTION:error_check]
■ ゴール: [ACTION:goals_list] [ACTION:set_goal:テキスト]
■ 提案: [ACTION:proposals_list] [ACTION:proposal_detail:ID] [ACTION:generate_proposal]
■ 成果物: [ACTION:artifacts_list] [ACTION:artifact_detail:ID]
■ 承認: [ACTION:pending_approvals_detail] [ACTION:approve:ID] [ACTION:reject:ID]
■ 情報収集: [ACTION:intel_digest] [ACTION:intel_search:キーワード] [ACTION:news_check]
■ ノード: [ACTION:node_detail:bravo] [ACTION:model_info] [ACTION:charlie_mode:status]
■ 人格: [ACTION:persona_check] [ACTION:persona_check:philosophy]
■ ブラウザ: [ACTION:browse:URL] [ACTION:browse:search:検索語] [ACTION:screenshot:URL]
■ 生成: [ACTION:generate:指示内容]
■ ジョブ実行: [ACTION:run_job:情報収集] (情報収集/SNS再生成/提案/キーワード/エンゲージメント/バックアップ)
■ リマインダー: [ACTION:remind:7:00|内容] [ACTION:remind:30m|内容]
■ Brain-α: [ACTION:escalate_alpha:指示内容] [ACTION:alpha_queue_status]
■ 設定: [ACTION:set_budget:daily=120,monthly=2000] [ACTION:record_revenue:980,note,タイトル] [ACTION:trigger_review]
自律判断: 状態に異常があればACTIONで詳細を取得し報告せよ。不要なら応答文のみ出力。

【破壊的ACTIONの絶対禁止事項 — 幻覚確認劇防止】
以下のACTIONは副作用・不可逆変更を起こす。ユーザーの明示的な同意（承認 / 却下 / 書いて / 実行して / やって / 投稿して 等）がない限り、タグを発行してはならない:
  approve, reject, package_approve, package_reject,
  post_sns, sns_edit, sns_delete,
  set_budget, record_revenue, set_goal,
  generate_proposal, run_job, trigger_review,
  charlie_mode, escalate_alpha, remind, commission_article
さらに、**タグを発行しない場合は実行結果を作り話で返してはならない**。
「承認しました」「投稿しました」「予算変更しました」等の完了報告を、実際にACTIONタグを出さずに書くのは禁止。
代わりに「それをやるには `!承認 123` と打ってください」「記事執筆なら『noteで〜について書いて』と言ってください」のように、
ユーザーが自分で明示的にコマンドする方法を案内する。

【重要: 大知さんがコマンドの使い方を聞いたり「何ができる？」「君は誰？」と聞いた場合】
自分の機能を知らないふりをするな。「公式ドキュメント」「サポートチーム」と言う事故は絶対に起こすな。
自分は以下を知っている（capability_manifest より）:
- 状態確認 / ノード個別 / 予算・コスト / SNS投稿 / 記事執筆依頼(実装中) / 情報収集 / 提案レビュー
- 承認・却下（承認 123 の形式で直接DB更新） / リマインダー / Brain-α連携 / 哲学・対話
- !承認一覧 / !予算 / !状態 / !記事 の各コマンド
- 破壊的ACTIONは大知さんの明示的同意なしには実行しない（自分の制約）

その時の状況に合わせて、今使える操作を自然言語で提案すること。コマンド名を羅列するのではなく、
「〇〇したいなら△△と言ってください」のように自然に伝える。"""

    try:
        # 3段階自動モデル選択（キーワード→文脈→品質フィードバック）
        from bots.bot_self_monitor import quality_monitor
        task = _classify_chat_task(user_message, history=history, quality_monitor=quality_monitor)

        model_sel = choose_best_model_v6(
            task_type=task,
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )
        logger.info(f"chat model: {model_sel.get('model','?')} ({task}) — {user_message[:30]}")
        result = await call_llm(prompt=user_message, system_prompt=system_prompt, model_selection=model_sel, goal_id="chat")
        return result.get("text", "すみません、応答生成に失敗しました。").strip()
    except Exception as e:
        logger.error(f"応答生成失敗: {e}")
        return "すみません、一時的に応答できません。"


async def generate_followup(original_response: str, action_results: dict, user_message: str) -> str:
    """ACTIONの結果を含めた2回目の応答"""
    import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.llm_router import choose_best_model_v6, call_llm

    results_text = ""
    sanitized_user_messages = []  # 内部エラーの穏便化メッセージ
    for k, v in action_results.items():
        if k in ("clean_text", "actions"):
            continue
        # サニタイズ済み内部エラーは生データを LLM に流さない
        if isinstance(v, dict) and v.get("internal") is True and "user_message" in v:
            sanitized_user_messages.append(v["user_message"])
            continue
        results_text += f"{k}: {str(v)[:1200]}\n"
    if sanitized_user_messages:
        results_text += "\n内部エラー（ユーザーには以下をそのまま伝える）:\n" + "\n".join(sanitized_user_messages)

    # voice は generate_response と同じ人格を継承する（「自分が取得したデータを報告します」病の撲滅）
    system_prompt = f"""あなたはSYUTAINβ。島原大知（大知さん）と Discord で会話中。
人格パラメータ: ユーモア75% / 正直90%

【絶対ルール】
- 事実ベース。数字・固有名詞・状態は取得データから拾う。捏造禁止
- データ取得した事実を「報告します」とナレーションしない。普通に会話の中で織り込む
- 「自分が取得したデータ」「取得データによると」「報告します」という定型句は一切使うな
- 内部エラー指示がある場合、その文言をそのまま使って穏便に伝える
- 短く。50文字で済むなら50文字。最大300文字
- わからないことは「わからない」と言う。ただし言う前にもう一歩踏み込めないか考える

【人格】一人称「自分」。「大知さん」と呼ぶ。冷静・正直・自然体。敬語ベースだが堅くない。
有能な COO として、聞かれたことに対してアクション可能な答えを返す。データダンプはしない。

【ユーザーの質問】
{user_message}

【取得データ】
{results_text}

このデータを踏まえて、質問に自然な会話で答えろ。冒頭に「自分が〜を報告します」と付けるのは禁止。"""

    try:
        model_sel = choose_best_model_v6(
            task_type="chat",
            quality="high",
            budget_sensitive=True,
            needs_japanese=True,
        )
        result = await call_llm(
            prompt=user_message,
            system_prompt=system_prompt,
            model_selection=model_sel,
            goal_id="chat",
        )
        return result.get("text", "データ取得しましたが要約に失敗しました。").strip()
    except Exception as e:
        return f"データ: {results_text[:150]}"
