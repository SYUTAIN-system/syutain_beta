"""
SYUTAINβ セマンティックキャッシュ
pgvector + Jina Embeddings でLLM応答をキャッシュし、API呼び出しを30-50%削減。

類似プロンプト（cosine similarity > 0.92）にはキャッシュから応答を返す。
完全一致ハッシュによる高速パス + ベクトル類似検索の2段構成。
"""

import hashlib
import logging
import time
from typing import Optional

logger = logging.getLogger("syutain.semantic_cache")

# キャッシュ対象タスクタイプ（分析・分類・要約など再利用性の高いもの）
CACHEABLE_TASK_TYPES = {
    "research", "analysis", "classification", "tagging", "translation",
    "translation_draft", "keyword_extraction", "sentiment_analysis",
    "compression", "data_extraction", "duplicate_check", "log_formatting",
    "intel_summary", "health_check", "monitoring", "quality_scoring",
    "competitive_analysis", "content_review",
}

# キャッシュ除外タスクタイプ（創作系・対話・戦略は毎回フレッシュ生成）
NON_CACHEABLE_TASK_TYPES = {
    "content", "sns_draft", "note_article", "note_draft", "note_article_final",
    "variation_gen", "drafting", "bulk_draft", "content_final",
    "booth_description", "booth_description_final", "product_desc",
    "persona_extraction", "persona_deep_analysis",
    "chat", "chat_light",
    "proposal", "proposal_generation", "strategy",
    "approval", "safety_check",
}

# 類似度閾値（高め設定で誤キャッシュ防止）
SIMILARITY_THRESHOLD = 0.92

# デフォルトTTL（秒）
DEFAULT_TTL_SECONDS = 24 * 3600  # 24時間
TIME_SENSITIVE_TTL_SECONDS = 1 * 3600  # 1時間

# タスクタイプ別TTL（秒）
TASK_TTL_SECONDS = {
    "classification": 7 * 24 * 3600,  # 7日
    "tagging": 7 * 24 * 3600,
    "compression": 3 * 24 * 3600,     # 3日
    "content_review": 2 * 24 * 3600,  # 2日
    "analysis": 24 * 3600,
    "research": 12 * 3600,            # 12時間（情報は古くなりやすい）
}

# テーブル最大行数
MAX_CACHE_ROWS = 10000

# 時間依存キーワード（短TTLで管理）
_TIME_SENSITIVE_KEYWORDS = [
    "今日", "本日", "現在", "最新", "today", "current", "latest", "now",
    "リアルタイム", "real-time", "速報",
]


def is_cacheable(task_type: str) -> bool:
    """タスクタイプがキャッシュ対象か判定"""
    if task_type in NON_CACHEABLE_TASK_TYPES:
        return False
    if task_type in CACHEABLE_TASK_TYPES:
        return True
    # 未知のタスクタイプはキャッシュしない（安全側に倒す）
    return False


def _prompt_hash(prompt: str, system_prompt: str = "") -> str:
    """プロンプト＋システムプロンプトのSHA256ハッシュ（完全一致高速パス用）"""
    content = f"{system_prompt}|||{prompt}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _system_hash(system_prompt: str) -> str:
    """システムプロンプトのハッシュ（同じsystem_promptのキャッシュのみ検索するため）"""
    if not system_prompt:
        return ""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def _is_time_sensitive(prompt: str) -> bool:
    """プロンプトが時間依存情報を含むか判定"""
    lower = prompt.lower()
    return any(kw in lower for kw in _TIME_SENSITIVE_KEYWORDS)


def _get_ttl(task_type: str, prompt: str) -> float:
    """タスクタイプとプロンプト内容に基づくTTL（秒）を返す"""
    if _is_time_sensitive(prompt):
        return float(TIME_SENSITIVE_TTL_SECONDS)
    return float(TASK_TTL_SECONDS.get(task_type, DEFAULT_TTL_SECONDS))


class SemanticCache:
    """pgvector-based semantic cache for LLM responses.

    Before calling an LLM:
    1. Generate embedding of the prompt
    2. Search for similar cached prompts (cosine similarity > 0.92)
    3. If found, return cached response (skip LLM call)
    4. If not found, call LLM, cache the response
    """

    _instance = None

    @classmethod
    def get_instance(cls) -> "SemanticCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._stats = {"hits": 0, "misses": 0, "stores": 0, "errors": 0}
        self._last_eviction = 0.0

    @property
    def hit_rate(self) -> float:
        total = self._stats["hits"] + self._stats["misses"]
        return self._stats["hits"] / total if total > 0 else 0.0

    async def get_or_call(
        self,
        prompt: str,
        system_prompt: str,
        model_selection: Optional[dict],
        call_llm_func,
        goal_id: str = "",
        task_type: str = "",
        **kwargs,
    ) -> dict:
        """Main entry point. Returns cached or fresh LLM response.

        Args:
            prompt: ユーザープロンプト
            system_prompt: システムプロンプト
            model_selection: choose_best_model_v6() の戻り値
            call_llm_func: 実際のLLM呼び出し関数（キャッシュミス時に使用）
            goal_id: ゴールID
            task_type: タスクタイプ
            **kwargs: call_llm に渡す追加引数

        Returns:
            dict with "text", "model_used", etc. + "cache_hit" flag
        """
        # キャッシュ対象外ならそのまま呼び出し
        if not is_cacheable(task_type):
            result = await call_llm_func(
                prompt, system_prompt, model_selection, goal_id=goal_id, **kwargs
            )
            result["cache_hit"] = False
            return result

        try:
            # Step 1: 完全一致の高速パス（embedding不要、DBハッシュ検索のみ）
            p_hash = _prompt_hash(prompt, system_prompt)
            exact = await self._search_exact(p_hash)
            if exact:
                self._stats["hits"] += 1
                logger.info(f"セマンティックキャッシュHIT(exact): task={task_type}")
                exact["cache_hit"] = True
                exact["cache_type"] = "exact"
                return exact

            # Step 2: ベクトル類似検索
            from tools.embedding_tools import get_embedding
            embedding = await get_embedding(prompt[:2000])  # 先頭2000文字で十分

            if embedding:
                sys_hash = _system_hash(system_prompt)
                similar = await self._search_similar(embedding, sys_hash)
                if similar:
                    self._stats["hits"] += 1
                    logger.info(
                        f"セマンティックキャッシュHIT(similar={similar.get('similarity', 0):.3f}): "
                        f"task={task_type}"
                    )
                    similar["cache_hit"] = True
                    similar["cache_type"] = "semantic"
                    return similar

            # Step 3: キャッシュミス → LLM呼び出し
            self._stats["misses"] += 1
            result = await call_llm_func(
                prompt, system_prompt, model_selection, goal_id=goal_id, **kwargs
            )
            result["cache_hit"] = False

            # Step 4: 結果をキャッシュに保存（失敗しても処理続行）
            if result.get("text") and embedding:
                try:
                    ttl = _get_ttl(task_type, prompt)
                    model = model_selection.get("model", "") if model_selection else ""
                    await self._store_cache(
                        prompt, system_prompt, result, embedding, p_hash, model, ttl
                    )
                    self._stats["stores"] += 1
                except Exception as e:
                    logger.warning(f"キャッシュ保存失敗（処理続行）: {e}")
                    self._stats["errors"] += 1

            # Step 5: 定期キャッシュ掃除（1時間おき）
            if time.time() - self._last_eviction > 3600:
                try:
                    await self._evict_old_entries()
                    self._last_eviction = time.time()
                except Exception as e:
                    logger.warning(f"キャッシュ掃除失敗: {e}")

            return result

        except Exception as e:
            # キャッシュ層のエラーはLLM呼び出しを阻害しない
            self._stats["errors"] += 1
            logger.error(f"セマンティックキャッシュエラー（フォールスルー）: {e}")
            result = await call_llm_func(
                prompt, system_prompt, model_selection, goal_id=goal_id, **kwargs
            )
            result["cache_hit"] = False
            return result

    async def _search_exact(self, prompt_hash: str) -> Optional[dict]:
        """完全一致ハッシュで高速検索"""
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                row = await conn.fetchrow(
                    """SELECT id, response_text, model
                    FROM semantic_cache
                    WHERE prompt_hash = $1
                      AND expires_at > NOW()
                    LIMIT 1""",
                    prompt_hash,
                )
                if row:
                    await conn.execute(
                        "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE id = $1",
                        row["id"],
                    )
                    return {
                        "text": row["response_text"],
                        "model_used": row["model"],
                        "cost_jpy": 0.0,
                        "tier": "cache",
                    }
        except Exception as e:
            logger.debug(f"完全一致検索失敗: {e}")
        return None

    async def _search_similar(
        self, prompt_embedding: list, system_prompt_hash: str = ""
    ) -> Optional[dict]:
        """ベクトル類似検索（cosine similarity > threshold）"""
        try:
            from tools.db_pool import get_connection
            embedding_str = "[" + ",".join(str(x) for x in prompt_embedding) + "]"

            async with get_connection() as conn:
                # system_promptが同じキャッシュのみ検索（異なるsystemでは意味が変わる）
                if system_prompt_hash:
                    row = await conn.fetchrow(
                        """SELECT id, response_text, model,
                            1 - (embedding <=> $1::vector) as similarity
                        FROM semantic_cache
                        WHERE system_prompt_hash = $2
                          AND expires_at > NOW()
                          AND embedding IS NOT NULL
                        ORDER BY embedding <=> $1::vector
                        LIMIT 1""",
                        embedding_str, system_prompt_hash,
                    )
                else:
                    row = await conn.fetchrow(
                        """SELECT id, response_text, model,
                            1 - (embedding <=> $1::vector) as similarity
                        FROM semantic_cache
                        WHERE (system_prompt_hash = '' OR system_prompt_hash IS NULL)
                          AND expires_at > NOW()
                          AND embedding IS NOT NULL
                        ORDER BY embedding <=> $1::vector
                        LIMIT 1""",
                        embedding_str,
                    )

                if row and float(row["similarity"]) >= SIMILARITY_THRESHOLD:
                    await conn.execute(
                        "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE id = $1",
                        row["id"],
                    )
                    return {
                        "text": row["response_text"],
                        "model_used": row["model"],
                        "cost_jpy": 0.0,
                        "tier": "cache",
                        "similarity": float(row["similarity"]),
                    }
        except Exception as e:
            logger.debug(f"類似検索失敗: {e}")
        return None

    async def _store_cache(
        self,
        prompt: str,
        system_prompt: str,
        response: dict,
        embedding: list,
        prompt_hash: str,
        model: str,
        ttl_seconds: float,
    ):
        """応答をキャッシュに保存"""
        from tools.db_pool import get_connection

        response_text = response.get("text", "")
        if not response_text or len(response_text) < 10:
            return  # 短すぎる応答はキャッシュしない

        sys_hash = _system_hash(system_prompt)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO semantic_cache
                    (prompt_hash, prompt_text, system_prompt_hash, model,
                     response_text, embedding, hit_count, created_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6::vector, 0, NOW(),
                        NOW() + make_interval(secs => $7))
                ON CONFLICT (prompt_hash) DO UPDATE SET
                    response_text = EXCLUDED.response_text,
                    model = EXCLUDED.model,
                    embedding = EXCLUDED.embedding,
                    expires_at = NOW() + make_interval(secs => $7),
                    created_at = NOW(),
                    hit_count = 0
                """,
                prompt_hash,
                prompt[:2000],  # プレビュー用に先頭2000文字のみ保存
                sys_hash,
                model,
                response_text,
                embedding_str,
                ttl_seconds,
            )

    async def _evict_old_entries(self):
        """期限切れエントリ削除 + 行数上限管理"""
        from tools.db_pool import get_connection

        async with get_connection() as conn:
            # 1. 期限切れ削除
            await conn.execute(
                "DELETE FROM semantic_cache WHERE expires_at < NOW()"
            )
            # 2. 7日超の古いエントリ削除
            await conn.execute(
                "DELETE FROM semantic_cache WHERE created_at < NOW() - INTERVAL '7 days'"
            )
            # 3. 行数上限: MAX_CACHE_ROWS超過分をhit_countが低い順に削除
            count = await conn.fetchval("SELECT COUNT(*) FROM semantic_cache")
            if count and count > MAX_CACHE_ROWS:
                excess = count - MAX_CACHE_ROWS
                await conn.execute(
                    """DELETE FROM semantic_cache
                    WHERE id IN (
                        SELECT id FROM semantic_cache
                        ORDER BY hit_count ASC, created_at ASC
                        LIMIT $1
                    )""",
                    excess,
                )
                logger.info(f"キャッシュ掃除: 超過{excess}件削除（残{MAX_CACHE_ROWS}件）")

    async def get_stats(self) -> dict:
        """キャッシュ統計を返す"""
        stats = dict(self._stats)
        stats["hit_rate"] = f"{self.hit_rate:.1%}"
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                stats["total_entries"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM semantic_cache"
                ) or 0
                stats["active_entries"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM semantic_cache WHERE expires_at > NOW()"
                ) or 0
                stats["total_hits"] = await conn.fetchval(
                    "SELECT COALESCE(SUM(hit_count), 0) FROM semantic_cache"
                ) or 0
        except Exception:
            stats["total_entries"] = "unknown"
            stats["active_entries"] = "unknown"
            stats["total_hits"] = "unknown"
        return stats


# ===== 後方互換API（旧インターフェース）=====

async def check_cache(prompt: str, task_type: str = "") -> Optional[str]:
    """旧API互換: キャッシュ確認。ヒットしたらレスポンスtextを返す。"""
    cache = SemanticCache.get_instance()
    exact = await cache._search_exact(_prompt_hash(prompt))
    if exact:
        return exact.get("text")
    return None


async def store_cache(prompt: str, response: str, model: str = "", task_type: str = ""):
    """旧API互換: キャッシュ保存（embeddingなしの完全一致のみ）"""
    if task_type in NON_CACHEABLE_TASK_TYPES:
        return
    if len(response) < 10:
        return

    p_hash = _prompt_hash(prompt)
    ttl = _get_ttl(task_type, prompt)

    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO semantic_cache
                    (prompt_hash, prompt_text, system_prompt_hash, model,
                     response_text, hit_count, created_at, expires_at)
                VALUES ($1, $2, '', $3, $4, 0, NOW(),
                        NOW() + make_interval(secs => $5))
                ON CONFLICT (prompt_hash) DO UPDATE SET
                    response_text = EXCLUDED.response_text,
                    model = EXCLUDED.model,
                    expires_at = NOW() + make_interval(secs => $5),
                    hit_count = 0
                """,
                p_hash, prompt[:2000], model, response, ttl,
            )
    except Exception as e:
        logger.debug(f"cache store failed: {e}")


async def cleanup_expired() -> int:
    """旧API互換: 期限切れキャッシュ削除"""
    try:
        cache = SemanticCache.get_instance()
        await cache._evict_old_entries()
        return 0
    except Exception as e:
        logger.warning(f"cache cleanup failed: {e}")
        return 0


async def get_cache_stats() -> dict:
    """旧API互換: キャッシュ統計"""
    cache = SemanticCache.get_instance()
    return await cache.get_stats()


async def ensure_table():
    """テーブル作成（db_init.pyのDDLで作成済みの場合は不要だが、互換性のため残す）"""
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    id SERIAL PRIMARY KEY,
                    prompt_hash TEXT NOT NULL UNIQUE,
                    prompt_text TEXT,
                    system_prompt_hash TEXT DEFAULT '',
                    model TEXT,
                    response_text TEXT NOT NULL,
                    embedding vector(1024),
                    hit_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_cache_hash ON semantic_cache(prompt_hash)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_cache_expires ON semantic_cache(expires_at)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_cache_sys_hash ON semantic_cache(system_prompt_hash)"
            )
    except Exception as e:
        logger.error(f"semantic_cache table creation failed: {e}")


def get_semantic_cache() -> SemanticCache:
    """シングルトンインスタンスを取得"""
    return SemanticCache.get_instance()
