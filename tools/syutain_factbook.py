"""
SYUTAINβ ファクトブック — SNS投稿・note記事の「事実素材」を収集する

目的: LLMに抽象的な指示を渡すとポエム化する問題の根本対策。
事実・数字・固有名詞をDBから収集し、LLMに「これを材料に書け」と強制する。

使い方:
    facts = await build_daily_factbook(limit=20)
    # facts = [Fact, Fact, ...]
    # facts[0].fact_text = "CORTEXのheartbeatが10分止まった"
    # facts[0].numbers = [10]
    # facts[0].entities = ["CORTEX"]
"""

import os
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

logger = logging.getLogger("syutain.factbook")


@dataclass
class Fact:
    """1つの事実を表す構造体"""
    category: str  # "error" / "metric" / "deploy" / "bot_event" / "cost" / "content" / "intel" / "loopguard"
    fact_text: str  # 30-60字の事実文
    numbers: list = field(default_factory=list)  # 含まれる具体的数値
    entities: list = field(default_factory=list)  # 含まれる固有名詞
    timestamp: Optional[datetime] = None
    source: str = ""  # どこから取ったか

    def to_prompt_line(self) -> str:
        """LLMプロンプトに注入可能な一行形式"""
        parts = [f"[{self.category}] {self.fact_text}"]
        if self.numbers:
            parts.append(f"数値={self.numbers}")
        if self.entities:
            parts.append(f"固有名詞={self.entities}")
        return " ".join(parts)


async def build_daily_factbook(hours: int = 24, limit: int = 30) -> list[Fact]:
    """
    直近N時間のSYUTAINβの事実をDBから収集する。

    Args:
        hours: 何時間前まで遡るか
        limit: 返却するFact数の上限

    Returns:
        list[Fact]: 事実のリスト（重要度順）
    """
    from tools.db_pool import get_connection

    facts: list[Fact] = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_connection() as conn:
        # === 1. LLMコスト・呼び出し数（metric）===
        try:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as calls, COALESCE(SUM(amount_jpy), 0)::numeric(10,2) as cost
                FROM llm_cost_log WHERE recorded_at > $1""",
                since,
            )
            if row and row["calls"] > 0:
                facts.append(Fact(
                    category="metric",
                    fact_text=f"直近{hours}時間でLLM{row['calls']}回呼び出し、コスト¥{row['cost']}",
                    numbers=[int(row["calls"]), float(row["cost"])],
                    entities=["LLM"],
                    timestamp=datetime.now(timezone.utc),
                    source="llm_cost_log",
                ))
        except Exception as e:
            logger.debug(f"factbook llm_cost_log: {e}")

        # === 2. LoopGuard発動（critical event）===
        try:
            rows = await conn.fetch(
                """SELECT event_type, source_node, payload, created_at FROM event_log
                WHERE (event_type LIKE '%loop_guard%' OR event_type LIKE '%emergency_kill%')
                AND created_at > $1
                ORDER BY created_at DESC LIMIT 5""",
                since,
            )
            for r in rows:
                facts.append(Fact(
                    category="loopguard",
                    fact_text=f"LoopGuard発動: {r['event_type']} on {r['source_node'] or '不明'}",
                    entities=["LoopGuard", r["source_node"] or "system"],
                    timestamp=r["created_at"],
                    source="event_log",
                ))
        except Exception as e:
            logger.debug(f"factbook loop_guard: {e}")

        # === 3. エラー件数・種別（error）===
        try:
            rows = await conn.fetch(
                """SELECT event_type, COUNT(*) as cnt FROM event_log
                WHERE (event_type LIKE '%error%' OR event_type LIKE '%fail%')
                AND created_at > $1
                GROUP BY event_type ORDER BY cnt DESC LIMIT 5""",
                since,
            )
            for r in rows:
                if r["cnt"] > 0:
                    facts.append(Fact(
                        category="error",
                        fact_text=f"{r['event_type']}が{r['cnt']}回発生",
                        numbers=[int(r["cnt"])],
                        entities=[r["event_type"]],
                        timestamp=datetime.now(timezone.utc),
                        source="event_log",
                    ))
        except Exception as e:
            logger.debug(f"factbook error events: {e}")

        # === 4. SNS投稿の成果（content）===
        try:
            row = await conn.fetchrow(
                """SELECT
                    COUNT(*) FILTER (WHERE status='posted') as posted,
                    COUNT(*) FILTER (WHERE status='pending') as pending,
                    COUNT(*) FILTER (WHERE status='rejected_poem') as rejected_poem
                FROM posting_queue WHERE created_at > $1""",
                since,
            )
            if row:
                if row["posted"]:
                    facts.append(Fact(
                        category="content",
                        fact_text=f"SNS投稿を{row['posted']}件実行（pending {row['pending']}件、ポエムreject {row['rejected_poem']}件）",
                        numbers=[int(row["posted"]), int(row["pending"] or 0), int(row["rejected_poem"] or 0)],
                        entities=["SNS", "posting_queue"],
                        timestamp=datetime.now(timezone.utc),
                        source="posting_queue",
                    ))
        except Exception as e:
            logger.debug(f"factbook sns: {e}")

        # === 5. エンゲージメント最高値（content）===
        try:
            row = await conn.fetchrow(
                """SELECT pq.platform, pq.account, LEFT(pq.content, 40) as preview,
                       e.likes, e.impressions
                FROM posting_queue pq
                JOIN posting_queue_engagement e ON e.posting_queue_id = pq.id
                WHERE pq.status = 'posted' AND e.impressions IS NOT NULL
                ORDER BY e.impressions DESC LIMIT 1""",
            )
            if row and row["impressions"] and row["impressions"] > 0:
                facts.append(Fact(
                    category="content",
                    fact_text=f"{row['platform']}の{row['account']}投稿が最高{row['impressions']}インプレッション、{row['likes']}いいね",
                    numbers=[int(row["impressions"]), int(row["likes"] or 0)],
                    entities=[row["platform"], row["account"]],
                    timestamp=datetime.now(timezone.utc),
                    source="posting_queue_engagement",
                ))
        except Exception as e:
            logger.debug(f"factbook engagement: {e}")

        # === 6. intel（外部トレンド情報、既存ロジック流用）===
        try:
            rows = await conn.fetch(
                """SELECT title, summary, category FROM intel_items
                WHERE importance_score >= 0.5
                AND created_at > $1
                ORDER BY importance_score DESC LIMIT 5""",
                since,
            )
            for r in rows:
                title = (r["title"] or "")[:50]
                facts.append(Fact(
                    category="intel",
                    fact_text=f"外部トレンド: {title}",
                    entities=[r["category"] or "intel"],
                    timestamp=datetime.now(timezone.utc),
                    source="intel_items",
                ))
        except Exception as e:
            logger.debug(f"factbook intel: {e}")

        # === 7. note記事の公開状態（content）===
        try:
            rows = await conn.fetch(
                """SELECT id, LEFT(title, 40) as title, status, publish_url
                FROM product_packages
                WHERE created_at > $1 AND platform = 'note'
                ORDER BY id DESC LIMIT 3""",
                since,
            )
            for r in rows:
                if r["status"] == "published":
                    facts.append(Fact(
                        category="content",
                        fact_text=f"noteに新記事を公開: {r['title']}",
                        entities=["note", "記事"],
                        timestamp=datetime.now(timezone.utc),
                        source="product_packages",
                    ))
        except Exception as e:
            logger.debug(f"factbook note: {e}")

        # === 8. 承認処理（bot_event）===
        try:
            row = await conn.fetchrow(
                """SELECT
                    COUNT(*) FILTER (WHERE status='approved') as approved,
                    COUNT(*) FILTER (WHERE status='rejected') as rejected,
                    COUNT(*) FILTER (WHERE status='pending') as pending
                FROM approval_queue WHERE created_at > $1""",
                since,
            )
            if row and (row["approved"] or row["rejected"]):
                facts.append(Fact(
                    category="bot_event",
                    fact_text=f"承認処理: 承認{row['approved'] or 0}件、却下{row['rejected'] or 0}件、待機{row['pending'] or 0}件",
                    numbers=[int(row["approved"] or 0), int(row["rejected"] or 0), int(row["pending"] or 0)],
                    entities=["ApprovalManager"],
                    timestamp=datetime.now(timezone.utc),
                    source="approval_queue",
                ))
        except Exception as e:
            logger.debug(f"factbook approval: {e}")

        # === 9. ペルソナ記憶の更新（bot_event）===
        try:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as updates FROM persona_memory
                WHERE updated_at > $1 OR created_at > $1""",
                since,
            )
            if row and row["updates"] and row["updates"] > 0:
                facts.append(Fact(
                    category="bot_event",
                    fact_text=f"ペルソナ記憶が{row['updates']}件更新",
                    numbers=[int(row["updates"])],
                    entities=["persona_memory"],
                    timestamp=datetime.now(timezone.utc),
                    source="persona_memory",
                ))
        except Exception as e:
            logger.debug(f"factbook persona: {e}")

        # === 10. システム統計（metric、常に含める）===
        try:
            # Python行数（ファイルから取得）
            try:
                import subprocess
                result = subprocess.run(
                    "find . -name '*.py' -not -path './__pycache__/*' -not -path './.git/*' -not -path './venv/*' -not -path './.venv/*' | xargs wc -l 2>/dev/null | tail -1",
                    shell=True, capture_output=True, text=True, cwd="/Users/daichi/syutain_beta", timeout=5,
                )
                total_lines = int(result.stdout.strip().split()[0]) if result.stdout.strip() else 0
                if total_lines > 0:
                    facts.append(Fact(
                        category="metric",
                        fact_text=f"SYUTAINβのPythonコードは現在{total_lines}行",
                        numbers=[total_lines],
                        entities=["SYUTAINβ", "Python"],
                        timestamp=datetime.now(timezone.utc),
                        source="git+wc",
                    ))
            except Exception:
                pass

            # LLM呼び出し累計
            row = await conn.fetchrow(
                "SELECT COUNT(*) as total, COALESCE(SUM(amount_jpy), 0)::numeric(10,2) as cost FROM llm_cost_log",
            )
            if row and row["total"]:
                facts.append(Fact(
                    category="metric",
                    fact_text=f"累計LLM呼び出し{row['total']}回、累計コスト¥{row['cost']}",
                    numbers=[int(row["total"]), float(row["cost"])],
                    entities=["LLM"],
                    timestamp=datetime.now(timezone.utc),
                    source="llm_cost_log",
                ))
        except Exception as e:
            logger.debug(f"factbook stats: {e}")

    # 重要度順で並べ替え（loopguard > error > metric > content > bot_event > intel）
    priority = {"loopguard": 0, "error": 1, "metric": 2, "content": 3, "bot_event": 4, "deploy": 5, "intel": 6}
    facts.sort(key=lambda f: priority.get(f.category, 9))

    return facts[:limit]


def factbook_to_prompt(facts: list[Fact], max_chars: int = 1500) -> str:
    """ファクトブックをLLMプロンプト用の文字列に変換する"""
    if not facts:
        return "（事実データなし）"

    lines = ["## SYUTAINβの直近の事実（これらを材料に投稿を作ること）"]
    total = len(lines[0])
    for f in facts:
        line = f"- {f.to_prompt_line()}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def pick_facts_for_post(facts: list[Fact], n: int = 3, theme: str = "") -> list[Fact]:
    """投稿1件分の事実を選ぶ（テーマに応じて優先度調整）"""
    import random
    if len(facts) <= n:
        return facts

    # テーマに応じて優先カテゴリを決定
    theme_priority = {
        "開発進捗": ["metric", "content", "bot_event"],
        "AI技術": ["metric", "loopguard", "error"],
        "業界批評": ["intel", "metric"],
        "哲学/思考": ["loopguard", "error", "metric"],
        "自己内省": ["error", "content", "metric"],
        "ビジネス": ["metric", "content"],
    }
    preferred = theme_priority.get(theme, ["metric", "content", "error", "loopguard"])

    # 優先カテゴリから先に選ぶ
    selected = []
    for cat in preferred:
        matching = [f for f in facts if f.category == cat]
        if matching and len(selected) < n:
            selected.append(random.choice(matching))

    # 足りなければランダム補充
    remaining = [f for f in facts if f not in selected]
    while len(selected) < n and remaining:
        selected.append(remaining.pop(random.randint(0, len(remaining) - 1)))

    return selected[:n]
