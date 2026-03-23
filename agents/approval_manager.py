"""
SYUTAINβ V25 承認管理 — Step 11
設計書準拠

Tier 1（人間承認必須）: SNS投稿, 商品公開, 価格設定, 暗号通貨取引
Tier 2（自動＋通知）: 情報パイプライン, モデル切替, タスクリスケジュール
Tier 3（完全自動）: ヘルスチェック, ログローテーション

24時間タイムアウト → 自動却下
却下時: 却下理由を推測して代替案を提案
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg
import httpx
from dotenv import load_dotenv

from tools.llm_router import choose_best_model_v6, call_llm
from tools.nats_client import get_nats_client

load_dotenv()

logger = logging.getLogger("syutain.approval_manager")

# ===== 承認Tier定義（設計書準拠）=====
TIER_1_HUMAN_REQUIRED = [
    "sns_posting",       # SNS投稿
    "product_publish",   # 商品公開
    "pricing",           # 価格設定
    "crypto_trading",    # 暗号通貨取引
    "account_change",    # 外部アカウント変更
    "billing",           # 課金発生
]

TIER_2_AUTO_WITH_NOTIFICATION = [
    "info_pipeline",     # 情報収集パイプライン
    "model_switching",   # モデル切替
    "task_reschedule",   # タスクリスケジュール
    "content_draft",     # コンテンツ下書き
    "browser_collect",   # ブラウザ情報収集
]

TIER_3_FULLY_AUTO = [
    "health_check",      # ヘルスチェック
    "log_rotation",      # ログローテーション
    "cache_cleanup",     # キャッシュクリーンアップ
    "metric_collection", # メトリクス収集
    "heartbeat",         # ハートビート
]

# タイムアウト: 72時間で自動却下（島原が毎日確認できるとは限らない）
APPROVAL_TIMEOUT_HOURS = 72


def classify_tier(request_type: str) -> int:
    """リクエストタイプから承認Tierを判定"""
    if request_type in TIER_1_HUMAN_REQUIRED:
        return 1
    if request_type in TIER_2_AUTO_WITH_NOTIFICATION:
        return 2
    if request_type in TIER_3_FULLY_AUTO:
        return 3
    # 未分類はTier 1（安全側に倒す）
    logger.warning(f"未分類のリクエストタイプ: {request_type} → Tier 1として処理")
    return 1


class ApprovalManager:
    """
    承認管理エージェント

    設計書ルール11: SNS投稿・商品公開・価格設定・暗号通貨取引は
    ApprovalManagerを通じて承認を得てから実行する
    """

    def __init__(self):
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

    async def initialize(self):
        """初期化: PostgreSQL接続"""
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://localhost:5432/syutain_beta"
        )
        try:
            self.pg_pool = await asyncpg.create_pool(
                database_url, min_size=1, max_size=3
            )
            logger.info("ApprovalManager: PostgreSQL接続完了")
        except Exception as e:
            logger.error(f"ApprovalManager: PostgreSQL接続エラー: {e}")

    async def close(self):
        """リソース解放"""
        if self.pg_pool:
            await self.pg_pool.close()

    # ========== 承認リクエスト ==========

    async def request_approval(
        self,
        request_type: str,
        request_data: dict,
        requested_by: str = "system",
    ) -> dict:
        """
        承認リクエストを送信

        Tierに応じて処理を分岐:
        - Tier 1: キューに入れてDiscord通知、人間の承認待ち
        - Tier 2: 自動承認してDiscord通知
        - Tier 3: 自動承認（通知なし）
        """
        tier = classify_tier(request_type)
        now = datetime.now(timezone.utc)

        if tier == 3:
            # Tier 3: 完全自動承認
            logger.info(f"Tier 3 自動承認: {request_type}")
            return {
                "status": "approved",
                "tier": 3,
                "request_type": request_type,
                "auto": True,
                "responded_at": now.isoformat(),
            }

        if tier == 2:
            # Tier 2: 自動承認 + Discord通知
            approval_id = await self._queue_request(
                request_type, request_data, "auto_approved"
            )
            await self._notify_discord(
                f"🔔 **自動承認 (Tier 2)**: {request_type}\n"
                f"内容: {json.dumps(request_data, ensure_ascii=False)[:500]}",
                tier=2,
            )
            logger.info(f"Tier 2 自動承認+通知: {request_type} (id={approval_id})")
            return {
                "status": "approved",
                "tier": 2,
                "approval_id": approval_id,
                "request_type": request_type,
                "auto": True,
                "responded_at": now.isoformat(),
            }

        # 過去パターンに基づく自動承認チェック
        auto_result = await self._check_auto_approval(request_type, request_data)
        if auto_result:
            approval_id = await self._queue_request(
                request_type, request_data, "auto_approved"
            )
            await self._notify_discord(
                f"🤖 **自動承認**: {request_type}\n"
                f"理由: 過去の承認パターンと類似 (類似度: {auto_result['similarity']:.2f})\n"
                f"内容: {json.dumps(request_data, ensure_ascii=False)[:300]}",
                tier=2,
            )
            try:
                from tools.event_logger import log_event
                await log_event(
                    "approval.auto_approved", "approval",
                    {
                        "approval_id": approval_id,
                        "request_type": request_type,
                        "similarity": auto_result["similarity"],
                        "matched_id": auto_result.get("matched_id"),
                    },
                    severity="info",
                )
            except Exception:
                pass
            logger.info(f"自動承認: {request_type} (id={approval_id}, sim={auto_result['similarity']:.2f})")
            return {
                "status": "auto_approved",
                "tier": 1,
                "approval_id": approval_id,
                "request_type": request_type,
                "auto": True,
                "responded_at": now.isoformat(),
            }

        # Tier 1: 人間承認必須 → キューに入れてDiscord通知
        approval_id = await self._queue_request(
            request_type, request_data, "pending"
        )
        await self._notify_discord(
            f"🚨 **承認待ち (Tier 1)**: {request_type}\n"
            f"ID: {approval_id}\n"
            f"内容: {json.dumps(request_data, ensure_ascii=False)[:500]}\n"
            f"⏰ {APPROVAL_TIMEOUT_HOURS}時間以内に承認/却下してください。タイムアウトで自動却下されます。",
            tier=1,
        )

        # NATS通知
        try:
            nats_client = await get_nats_client()
            await nats_client.publish(
                "approval.request",
                {
                    "approval_id": approval_id,
                    "request_type": request_type,
                    "tier": 1,
                    "requested_at": now.isoformat(),
                },
            )
        except Exception as e:
            logger.error(f"NATS承認通知エラー: {e}")

        logger.info(f"Tier 1 承認待ち: {request_type} (id={approval_id})")
        return {
            "status": "pending",
            "tier": 1,
            "approval_id": approval_id,
            "request_type": request_type,
            "timeout_at": (now + timedelta(hours=APPROVAL_TIMEOUT_HOURS)).isoformat(),
        }

    # ========== 承認/却下レスポンス ==========

    async def respond(
        self, approval_id: int, approved: bool, reason: str = ""
    ) -> dict:
        """
        承認リクエストに対する応答

        Args:
            approval_id: 承認キューID
            approved: True=承認, False=却下
            reason: 承認/却下理由
        """
        if not self.pg_pool:
            return {"error": "DB未接続"}

        now = datetime.now(timezone.utc)
        status = "approved" if approved else "rejected"

        try:
            async with self.pg_pool.acquire() as conn:
                # 既にレスポンス済みでないか確認
                row = await conn.fetchrow(
                    "SELECT status, request_type, request_data FROM approval_queue WHERE id = $1",
                    approval_id,
                )
                if not row:
                    return {"error": "承認リクエストが見つかりません"}
                if row["status"] != "pending":
                    return {"error": f"既に処理済みです (status={row['status']})"}

                # ステータス更新
                await conn.execute(
                    """
                    UPDATE approval_queue
                    SET status = $1, responded_at = $2, response = $3
                    WHERE id = $4
                    """,
                    status,
                    now,
                    reason or status,
                    approval_id,
                )
        except Exception as e:
            logger.error(f"承認レスポンスDB更新エラー: {e}")
            return {"error": str(e)}

        request_type = row["request_type"]

        # NATS通知
        try:
            nats_client = await get_nats_client()
            await nats_client.publish(
                f"approval.{'approved' if approved else 'rejected'}",
                {
                    "approval_id": approval_id,
                    "request_type": request_type,
                    "status": status,
                    "reason": reason,
                },
            )
        except Exception as e:
            logger.error(f"NATS承認レスポンス通知エラー: {e}")

        result = {
            "approval_id": approval_id,
            "status": status,
            "request_type": request_type,
            "responded_at": now.isoformat(),
        }

        # 却下時: 却下理由を推測して代替案を提案
        if not approved:
            alternative = await self._handle_rejection(
                request_type,
                json.loads(row["request_data"]) if isinstance(row["request_data"], str) else row["request_data"],
                reason,
            )
            result["alternative"] = alternative

        # event_log記録
        try:
            from tools.event_logger import log_event
            await log_event(
                f"approval.{'approved' if approved else 'rejected'}", "approval",
                {
                    "approval_id": approval_id,
                    "request_type": request_type,
                    "action": status,
                    "reason": reason or "",
                },
                severity="info",
            )
        except Exception:
            pass

        logger.info(f"承認レスポンス: id={approval_id}, status={status}")
        return result

    # ========== タイムアウトチェック ==========

    async def check_timeouts(self) -> list:
        """
        72時間タイムアウトの承認リクエストを自動却下
        48時間経過時と68時間経過時にリマインドを送信

        定期的に（1時間ごと）呼び出す
        """
        if not self.pg_pool:
            return []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=APPROVAL_TIMEOUT_HOURS)
        reminder_48h = now - timedelta(hours=48)
        reminder_68h = now - timedelta(hours=68)
        timed_out = []

        try:
            async with self.pg_pool.acquire() as conn:
                # --- リマインド送信 (48h / 68h経過) ---
                reminder_rows = await conn.fetch(
                    """
                    SELECT id, request_type, request_data, requested_at
                    FROM approval_queue
                    WHERE status = 'pending'
                    AND requested_at < $1
                    AND requested_at >= $2
                    """,
                    reminder_48h, cutoff,
                )
                for row in reminder_rows:
                    age_hours = (now - row["requested_at"].replace(tzinfo=timezone.utc)).total_seconds() / 3600
                    # 48h前後 (47-49h) or 68h前後 (67-69h) にリマインド
                    if (47 <= age_hours <= 49) or (67 <= age_hours <= 69):
                        remaining = APPROVAL_TIMEOUT_HOURS - age_hours
                        await self._notify_discord(
                            f"⏰ **リマインド**: 承認ID {row['id']} ({row['request_type']}) が"
                            f"未処理です。あと{remaining:.0f}時間でタイムアウトします。",
                            tier=1,
                        )

                # --- タイムアウト却下 ---
                rows = await conn.fetch(
                    """
                    SELECT id, request_type, request_data
                    FROM approval_queue
                    WHERE status = 'pending' AND requested_at < $1
                    """,
                    cutoff,
                )

                for row in rows:
                    await conn.execute(
                        """
                        UPDATE approval_queue
                        SET status = 'timeout_rejected',
                            responded_at = NOW(),
                            response = '72時間タイムアウトによる自動却下'
                        WHERE id = $1
                        """,
                        row["id"],
                    )
                    timed_out.append({
                        "approval_id": row["id"],
                        "request_type": row["request_type"],
                    })
                    logger.warning(
                        f"承認タイムアウト自動却下: id={row['id']}, "
                        f"type={row['request_type']}"
                    )
                    # event_log記録
                    try:
                        from tools.event_logger import log_event
                        await log_event(
                            "approval.timeout_rejected", "approval",
                            {
                                "approval_id": row["id"],
                                "request_type": row["request_type"],
                                "reason": f"{APPROVAL_TIMEOUT_HOURS}時間タイムアウト",
                            },
                            severity="warning",
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"タイムアウトチェックエラー: {e}")

        if timed_out:
            await self._notify_discord(
                f"⏰ **タイムアウト自動却下**: {len(timed_out)}件の承認リクエストが"
                f"{APPROVAL_TIMEOUT_HOURS}時間タイムアウトにより自動却下されました。",
                tier=1,
            )

        return timed_out

    # ========== 承認キュー取得 ==========

    async def get_pending_approvals(self) -> list:
        """承認待ちキューを取得"""
        if not self.pg_pool:
            return []
        try:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, request_type, request_data, status,
                           requested_at, responded_at, response
                    FROM approval_queue
                    WHERE status = 'pending'
                    ORDER BY requested_at ASC
                    """
                )
                results = []
                for row in rows:
                    d = dict(row)
                    # タイムアウトまでの残り時間を計算
                    requested_at = row["requested_at"]
                    if requested_at:
                        timeout_at = requested_at + timedelta(hours=APPROVAL_TIMEOUT_HOURS)
                        remaining = timeout_at - datetime.now(timezone.utc)
                        d["timeout_at"] = timeout_at.isoformat()
                        d["remaining_hours"] = max(0, remaining.total_seconds() / 3600)
                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"承認キュー取得エラー: {e}")
            return []

    async def get_all_approvals(self, limit: int = 50) -> list:
        """全承認リクエストを取得（履歴含む）"""
        if not self.pg_pool:
            return []
        try:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, request_type, request_data, status,
                           requested_at, responded_at, response
                    FROM approval_queue
                    ORDER BY requested_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"承認履歴取得エラー: {e}")
            return []

    # ========== DB操作 ==========

    async def _queue_request(
        self, request_type: str, request_data: dict, status: str
    ) -> Optional[int]:
        """承認リクエストをPostgreSQLのapproval_queueに追加"""
        if not self.pg_pool:
            logger.error("PostgreSQL未接続。承認リクエストをキューに入れられません")
            return None

        try:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO approval_queue (request_type, request_data, status)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    request_type,
                    json.dumps(request_data, ensure_ascii=False),
                    status,
                )
                return row["id"] if row else None
        except Exception as e:
            logger.error(f"承認リクエストDB挿入エラー: {e}")
            return None

    # ========== 過去パターンに基づく自動承認 ==========

    async def _check_auto_approval(
        self, request_type: str, request_data: dict
    ) -> Optional[dict]:
        """
        過去に承認されたリクエストと類似度を比較し、
        類似度が閾値以上なら自動承認を推奨する。

        Returns: {"similarity": float, "matched_id": int} or None
        """
        if not self.pg_pool:
            return None

        # 自動承認の閾値（settingsテーブルから読み込み、デフォルト0.8）
        auto_threshold = 0.8
        try:
            async with self.pg_pool.acquire() as conn:
                threshold_row = await conn.fetchval(
                    "SELECT value FROM settings WHERE key = 'auto_approval_threshold'"
                )
                if threshold_row:
                    auto_threshold = float(threshold_row)

                # 自動承認が無効化されているか確認
                enabled_row = await conn.fetchval(
                    "SELECT value FROM settings WHERE key = 'auto_approval_enabled'"
                )
                if enabled_row and enabled_row.lower() in ("false", "0", "no"):
                    return None

                # 同じrequest_typeで承認済みの過去リクエストを取得
                past_rows = await conn.fetch(
                    """
                    SELECT id, request_data FROM approval_queue
                    WHERE request_type = $1
                    AND status IN ('approved', 'auto_approved')
                    ORDER BY responded_at DESC
                    LIMIT 10
                    """,
                    request_type,
                )

            if not past_rows:
                return None

            # 簡易類似度: request_dataのキー/値の一致率
            new_str = json.dumps(request_data, ensure_ascii=False, sort_keys=True)
            new_words = set(new_str.split())

            best_sim = 0.0
            best_id = None
            for row in past_rows:
                past_data = row["request_data"]
                if isinstance(past_data, str):
                    past_str = past_data
                else:
                    past_str = json.dumps(past_data, ensure_ascii=False, sort_keys=True)
                past_words = set(past_str.split())
                union = new_words | past_words
                if not union:
                    continue
                sim = len(new_words & past_words) / len(union)
                if sim > best_sim:
                    best_sim = sim
                    best_id = row["id"]

            if best_sim >= auto_threshold:
                return {"similarity": best_sim, "matched_id": best_id}

        except Exception as e:
            logger.error(f"自動承認チェックエラー: {e}")

        return None

    # ========== 却下時の代替案 ==========

    async def _handle_rejection(
        self, request_type: str, request_data: dict, reason: str
    ) -> dict:
        """
        却下時: 却下理由を推測し、代替案を提案

        設計書: 「却下理由を推測して代替案を即座に提示できる」
        """
        model_selection = choose_best_model_v6(
            task_type="proposal",
            quality="medium",
            budget_sensitive=True,
            needs_japanese=True,
        )

        prompt = f"""承認リクエストが却下されました。却下理由を推測し、代替アクションを提案してください。

リクエストタイプ: {request_type}
リクエスト内容: {json.dumps(request_data, ensure_ascii=False)[:1000]}
却下理由（島原から）: {reason if reason else "理由なし（推測してください）"}

以下のJSON形式で出力してください:
{{
  "guessed_reason": "推測した却下理由",
  "alternative_action": "代替アクションの説明",
  "requires_approval": true/false,
  "risk_level": "low|medium|high"
}}"""

        system_prompt = (
            "SYUTAINβの承認管理エンジン。却下された理由を推測し、"
            "代替アクションを提案する。必ず有効なJSONのみを出力すること。"
        )

        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                model_selection=model_selection,
            )
            text = result.get("text", "")
            # JSONパース
            cleaned = text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return {"guessed_reason": "推測不能", "alternative_action": "手動で検討"}
        except Exception as e:
            logger.error(f"却下代替案生成エラー: {e}")
            return {
                "guessed_reason": "推測不能（LLMエラー）",
                "alternative_action": "手動で検討してください",
                "requires_approval": True,
                "risk_level": "unknown",
            }

    # ========== Discord通知 ==========

    async def _notify_discord(self, message: str, tier: int = 1):
        """
        Discord Webhookで通知

        設計書ルール12: 重要な判断はDiscord Webhook + Web UIで通知する
        """
        if not self.discord_webhook_url:
            logger.debug("Discord Webhook URLが未設定。通知をスキップ")
            return

        # Tierに応じた色設定
        color_map = {1: 0xFF0000, 2: 0xFFAA00, 3: 0x00FF00}
        color = color_map.get(tier, 0x808080)

        payload = {
            "embeds": [
                {
                    "title": f"SYUTAINβ 承認通知 (Tier {tier})",
                    "description": message[:2000],
                    "color": color,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "SYUTAINβ V25 ApprovalManager"},
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.discord_webhook_url,
                    json=payload,
                )
                if resp.status_code not in (200, 204):
                    logger.warning(f"Discord通知失敗: status={resp.status_code}")
        except Exception as e:
            logger.error(f"Discord通知エラー: {e}")


# シングルトンインスタンス
_manager: Optional[ApprovalManager] = None


async def get_approval_manager() -> ApprovalManager:
    """ApprovalManagerのシングルトンを取得"""
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
        await _manager.initialize()
    return _manager
