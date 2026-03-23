"""
SYUTAINβ V25 商取引ツール (Step 18)
設計書準拠

Stripe統合（決済）、Booth統合（デジタル商品販売）。
全ての商品公開・価格設定はApprovalManagerの承認が必須（CLAUDE.mdルール11）。
"""

import os
import logging
from typing import Optional
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.commerce_tools")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_API_URL = "https://api.stripe.com/v1"


async def _require_approval(action: str, data: dict) -> dict:
    """ApprovalManager承認（CLAUDE.mdルール11: 商品公開・価格設定は承認必須）"""
    try:
        from tools.nats_client import get_nats_client
        nats = await get_nats_client()
        response = await nats.request(
            "approval.request",
            {
                "request_type": "commerce",
                "action": action,
                "data": data,
                "requested_at": datetime.now().isoformat(),
            },
            timeout=300.0,
        )
        return response or {"approved": False, "reason": "タイムアウト"}
    except Exception as e:
        logger.error(f"承認リクエスト失敗: {e}")
        return {"approved": False, "reason": str(e)}


# ===== Stripe統合 =====

class StripeClient:
    """Stripe API クライアント（プレースホルダー）"""

    def __init__(self):
        self.api_key = STRIPE_SECRET_KEY
        if not self.api_key:
            logger.warning("STRIPE_SECRET_KEY未設定")

    async def create_product(self, name: str, description: str = "", metadata: Optional[dict] = None) -> dict:
        """Stripe商品を作成（承認必須）"""
        approval = await _require_approval("create_product", {"name": name, "description": description})
        if not approval.get("approved", False):
            return {"success": False, "reason": "approval_denied", "detail": approval}

        if not self.api_key:
            return {"success": False, "reason": "stripe_key_missing"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{STRIPE_API_URL}/products",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={
                        "name": name,
                        "description": description,
                        **({"metadata": metadata} if metadata else {}),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"Stripe商品作成: {data.get('id', '')}")
                return {"success": True, "product_id": data.get("id", ""), "data": data}
        except Exception as e:
            logger.error(f"Stripe商品作成失敗: {e}")
            return {"success": False, "reason": str(e)}

    async def create_price(self, product_id: str, amount_jpy: int, recurring: Optional[dict] = None) -> dict:
        """Stripe価格を設定（承認必須）"""
        approval = await _require_approval("set_price", {"product_id": product_id, "amount_jpy": amount_jpy})
        if not approval.get("approved", False):
            return {"success": False, "reason": "approval_denied", "detail": approval}

        if not self.api_key:
            return {"success": False, "reason": "stripe_key_missing"}

        try:
            price_data = {
                "product": product_id,
                "unit_amount": amount_jpy,
                "currency": "jpy",
            }
            if recurring:
                price_data["recurring"] = recurring  # {"interval": "month"}

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{STRIPE_API_URL}/prices",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=price_data,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"Stripe価格設定: {data.get('id', '')} ({amount_jpy}円)")
                return {"success": True, "price_id": data.get("id", ""), "data": data}
        except Exception as e:
            logger.error(f"Stripe価格設定失敗: {e}")
            return {"success": False, "reason": str(e)}

    async def create_checkout_session(self, price_id: str, success_url: str, cancel_url: str) -> dict:
        """Stripeチェックアウトセッション作成"""
        if not self.api_key:
            return {"success": False, "reason": "stripe_key_missing"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{STRIPE_API_URL}/checkout/sessions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={
                        "line_items[0][price]": price_id,
                        "line_items[0][quantity]": "1",
                        "mode": "payment",
                        "success_url": success_url,
                        "cancel_url": cancel_url,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return {"success": True, "session_id": data.get("id", ""), "url": data.get("url", "")}
        except Exception as e:
            logger.error(f"Stripeセッション作成失敗: {e}")
            return {"success": False, "reason": str(e)}

    async def list_products(self, limit: int = 10) -> dict:
        """Stripe商品一覧取得"""
        if not self.api_key:
            return {"success": False, "reason": "stripe_key_missing"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{STRIPE_API_URL}/products",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={"limit": limit},
                )
                resp.raise_for_status()
                return {"success": True, "products": resp.json().get("data", [])}
        except Exception as e:
            logger.error(f"Stripe商品一覧取得失敗: {e}")
            return {"success": False, "reason": str(e)}


# ===== Booth統合 =====

class BoothClient:
    """Booth API クライアント（プレースホルダー）

    注: Boothには公式APIが限定的。将来的にブラウザ自動操作（BRAVOの4層構成）で補完。
    """

    def __init__(self):
        self.booth_session = os.getenv("BOOTH_SESSION_COOKIE", "")
        if not self.booth_session:
            logger.warning("BOOTH_SESSION_COOKIE未設定")

    async def create_draft(self, title: str, description: str, price_jpy: int, tags: Optional[list] = None) -> dict:
        """Booth商品下書き作成（承認必須）"""
        try:
            approval = await _require_approval(
                "booth_create",
                {"title": title, "price_jpy": price_jpy},
            )
            if not approval.get("approved", False):
                return {"success": False, "reason": "approval_denied", "detail": approval}

            # Boothは公式APIが限定的 → 下書きデータを返す
            logger.info(f"Booth下書き作成: {title} ({price_jpy}円)")
            return {
                "success": True,
                "status": "draft_prepared",
                "draft": {
                    "title": title,
                    "description": description,
                    "price_jpy": price_jpy,
                    "tags": tags or [],
                },
                "note": "Boothへの実際のアップロードはブラウザ自動操作（BRAVO）で実行します",
            }
        except Exception as e:
            logger.error(f"Booth下書き作成エラー: {e}")
            return {"success": False, "reason": "error", "detail": str(e)}

    async def list_items(self) -> dict:
        """Booth出品アイテム一覧（プレースホルダー）"""
        logger.info("Booth一覧取得: ブラウザ自動操作が必要")
        return {
            "success": False,
            "reason": "browser_automation_required",
            "note": "Booth出品一覧の取得にはBRAVOのブラウザ自動操作が必要です",
        }


# ===== 収益記録 =====

async def record_revenue(
    platform: str,
    amount_jpy: int,
    product_id: str = "",
    source_content_id: str = "",
) -> bool:
    """収益をPostgreSQLに記録"""
    try:
        import asyncpg
        database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(
                """
                INSERT INTO revenue_linkage (platform, revenue_jpy, product_id, source_content_id)
                VALUES ($1, $2, $3, $4)
                """,
                platform, amount_jpy, product_id, source_content_id,
            )
            logger.info(f"収益記録: {platform} {amount_jpy}円")
            return True
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"収益記録失敗: {e}")
        return False
