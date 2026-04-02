"""
SYUTAINβ V25 x402 Payment Protocol (Feature 10)
HTTP 402 Payment Required ベースのAPI決済プロトコル。

外部クライアントがMCP/A2A経由でSYUTAINβのツールを使用する際の
マイクロペイメント決済レイヤー。

Phase 1: 使用量記録のみ（手動請求）
Phase 2: Stripe Payment Intents統合
Phase 3: Lightning Network対応

feature_flags.yaml: x402_protocol: false
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.x402")


async def ensure_table():
    """決済テーブル作成"""
    try:
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS x402_payments (
                    id SERIAL PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    amount_jpy REAL NOT NULL,
                    payment_method TEXT DEFAULT 'pending',
                    payment_status TEXT DEFAULT 'unpaid',
                    payment_reference TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)
    except Exception as e:
        logger.error(f"x402 table creation failed: {e}")


async def create_payment_request(client_id: str, tool_name: str, amount_jpy: float) -> dict:
    """決済リクエストを作成"""
    try:
        await ensure_table()
        async with get_connection() as conn:
            payment_id = await conn.fetchval("""
                INSERT INTO x402_payments (client_id, tool_name, amount_jpy)
                VALUES ($1, $2, $3) RETURNING id
            """, client_id, tool_name, amount_jpy)

            return {
                "payment_id": payment_id,
                "amount_jpy": amount_jpy,
                "status": "unpaid",
                "payment_methods": _available_payment_methods(),
            }
    except Exception as e:
        logger.error(f"payment request failed: {e}")
        return {"error": str(e)}


async def verify_payment(payment_id: int, payment_reference: str, method: str = "manual") -> dict:
    """決済を検証"""
    try:
        await ensure_table()
        async with get_connection() as conn:
            await conn.execute("""
                UPDATE x402_payments
                SET payment_status = 'paid', payment_method = $1,
                    payment_reference = $2, paid_at = NOW()
                WHERE id = $3
            """, method, payment_reference, payment_id)
            return {"payment_id": payment_id, "status": "paid"}
    except Exception as e:
        return {"error": str(e)}


async def check_payment_status(payment_id: int) -> dict:
    """決済ステータス確認"""
    try:
        await ensure_table()
        async with get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM x402_payments WHERE id = $1", payment_id)
            if row:
                return {
                    "payment_id": row["id"],
                    "status": row["payment_status"],
                    "amount_jpy": row["amount_jpy"],
                    "method": row["payment_method"],
                }
            return {"error": "payment not found"}
    except Exception as e:
        return {"error": str(e)}


async def get_revenue_summary() -> dict:
    """x402経由の収益サマリー"""
    try:
        await ensure_table()
        async with get_connection() as conn:
            total = await conn.fetchrow("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(amount_jpy), 0) as total
                FROM x402_payments WHERE payment_status = 'paid'
            """)
            monthly = await conn.fetchrow("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(amount_jpy), 0) as total
                FROM x402_payments
                WHERE payment_status = 'paid'
                  AND paid_at > date_trunc('month', CURRENT_DATE)
            """)
            return {
                "total_payments": total["cnt"] if total else 0,
                "total_revenue_jpy": float(total["total"]) if total else 0,
                "monthly_payments": monthly["cnt"] if monthly else 0,
                "monthly_revenue_jpy": float(monthly["total"]) if monthly else 0,
            }
    except Exception as e:
        return {"error": str(e)}


def _available_payment_methods() -> list:
    """利用可能な決済方法"""
    methods = ["manual"]  # Phase 1: 手動請求
    if os.getenv("STRIPE_SECRET_KEY"):
        methods.append("stripe")
    return methods
