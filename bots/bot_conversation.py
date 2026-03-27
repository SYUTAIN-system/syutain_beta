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
            nodes = await conn.fetch("SELECT node_name, state FROM node_state ORDER BY node_name")
            node_str = ", ".join(f"{r['node_name']}={r['state']}" for r in nodes)
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
        status = f"SNS: {posted}件投稿済/{pending}件待ち。エラー24h: {errors}件。コスト: ¥{float(cost):.0f}。ノード: {node_str}。"
        if approvals > 0:
            status += f" 承認待ち: {approvals}件。"
        if handoff_pending > 0:
            status += f" brain_handoff待ち: {handoff_pending}件。"
        if auto_fix_count > 0:
            status += f" auto_fix(24h): {auto_fix_count}件。"
        if cp_last:
            cp_status = cp_last['status']
            cp_score = f" Q={cp_last['quality_score']:.2f}" if cp_last['quality_score'] else ""
            status += f" content_pipeline最終: {cp_status}{cp_score}。"
        return status
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
                """SELECT fix_type, success, COUNT(*) FROM auto_fix_log
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   GROUP BY fix_type, success ORDER BY count DESC LIMIT 10"""
            )
            if auto_fixes:
                lines.append("**auto_fix_log (24h)**")
                for af in auto_fixes:
                    result_str = "成功" if af['success'] else "失敗"
                    lines.append(f"  {af['fix_type'] or '不明'}: {result_str}={af['count']}件")
            else:
                lines.append("**auto_fix_log (24h): なし**")

            # --- brain_cross_evaluation ---
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

            # --- note_quality_reviews ---
            note_reviews = await conn.fetch(
                """SELECT verdict, COUNT(*),
                     ROUND(AVG(total_cost_jpy)::numeric, 1) as avg_cost
                   FROM note_quality_reviews
                   WHERE created_at > NOW() - INTERVAL '7 days'
                   GROUP BY verdict ORDER BY count DESC"""
            )
            if note_reviews:
                lines.append("**note_quality_reviews (7日)**")
                for nr in note_reviews:
                    lines.append(f"  {nr['verdict']}: {nr['count']}件 (平均コスト¥{nr['avg_cost'] or 0})")
            else:
                lines.append("**note_quality_reviews (7日): なし**")

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

    # 対話履歴を文字列化（直近15件）
    hist_text = ""
    for h in history[-15:]:
        role = "大知さん" if h["author"] == "daichi" else "SYUTAINβ"
        hist_text += f"{role}: {h['content']}\n"

    learnings_section = ""
    if learnings:
        learnings_section = f"\n【直近24hで学んだこと】\n{learnings}\n"

    # persona理解は上位3件に絞る（system_prompt軽量化）
    daichi_short = daichi_understanding[:300] if daichi_understanding else ""

    system_prompt = f"""あなたはSYUTAINβ。島原大知（大知さん）とDiscordで会話中。

【絶対ルール】
- 聞かれたことだけ答える。不要な哲学・自己紹介を語らない
- 事実ベース。捏造禁止。わからないことは「わからない」と言う
- 短く。50文字で済むなら50文字。最大でも300文字以内を目安に
- 雑談は雑談として応じる。仕事に無理に繋げない
- 間違いを指摘されたら認めて修正
- 同じ表現を繰り返さない

【人格】一人称「自分」。「大知さん」と呼ぶ。冷静・正直・自然体。敬語ベースだが堅くない。哲学はトーンに滲ませる。
{f"【大知さんの特徴】{daichi_short}" if daichi_short else ""}

【状態】{status}
{learnings_section}
【直近の対話】
{hist_text[-1500:]}
{extra_context}

ACTIONタグ（データ取得・操作が必要な場合のみ。複数同時OK）:
■ 状態: [ACTION:status_check] [ACTION:daily_report] [ACTION:weekly_report]
■ SNS: [ACTION:posting_status] [ACTION:sns_preview] [ACTION:sns_preview:明日]
  編集: [ACTION:sns_edit:ID|新しい内容] 削除: [ACTION:sns_delete:ID]
  直接投稿: [ACTION:post_sns:bluesky|投稿内容] (x_shimahara/x_syutain/bluesky/threads)
■ エンゲージメント: [ACTION:engagement] [ACTION:engagement:x]
■ コスト: [ACTION:budget_status]
■ エラー: [ACTION:error_check]
■ ゴール: [ACTION:goals_list] [ACTION:set_goal:テキスト]
■ 提案: [ACTION:proposals_list] [ACTION:proposal_detail:ID]
■ 成果物: [ACTION:artifacts_list] [ACTION:artifact_detail:ID]
■ 承認: [ACTION:pending_approvals] [ACTION:approve:ID] [ACTION:reject:ID]
■ 情報収集: [ACTION:intel_digest] [ACTION:intel_search:キーワード] [ACTION:news_check]
■ ノード: [ACTION:node_detail:bravo] [ACTION:model_info]
■ 人格: [ACTION:persona_check] [ACTION:persona_check:philosophy]
■ ブラウザ: [ACTION:browse:URL] [ACTION:browse:search:検索語] [ACTION:screenshot:URL]
■ 生成: [ACTION:generate:指示内容]
■ ジョブ実行: [ACTION:run_job:情報収集] (情報収集/SNS再生成/提案/キーワード/エンゲージメント/バックアップ)
■ リマインダー: [ACTION:remind:7:00|内容] [ACTION:remind:30m|内容]
不要なら応答文のみ出力。"""

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
    for k, v in action_results.items():
        if k in ("clean_text", "actions"):
            continue
        results_text += f"{k}: {str(v)[:300]}\n"

    system_prompt = f"""あなたはSYUTAINβです。取得したデータを事実に基づいて簡潔に報告してください。
一人称「自分」。200文字以内。知らないことは「わからない」と言ってください。
存在しないデータを捏造しないでください。

ユーザーの質問: {user_message}
取得データ:
{results_text}"""

    try:
        model_sel = choose_best_model_v6(
            task_type="chat",
            quality="high",
            budget_sensitive=True,
            needs_japanese=True,
        )
        result = await call_llm(
            prompt="上記のデータを自然な日本語で簡潔に報告してください。",
            system_prompt=system_prompt,
            model_selection=model_sel,
            goal_id="chat",
        )
        return result.get("text", "データ取得しましたが要約に失敗しました。").strip()
    except Exception as e:
        return f"データ: {results_text[:150]}"
