"""
SYUTAINβ x402 Payment Foundation — クレジットベース課金基盤

現段階ではシンプルなクレジットシステムを実装:
- APIキーごとにクレジット残高を管理
- ツール呼び出しごとにクレジットを消費
- 手動でクレジットを追加可能

将来的にx402/Stripe等の実決済システムと接続予定。
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("syutain.payment_manager")


class PaymentManager:
    """Foundation for x402 machine-to-machine payments.

    For now, implements a simple credit system:
    - API keys have credit balances
    - Each tool call deducts credits
    - Credits can be added manually

    Future: integrate with actual x402/Stripe when ready.
    """

    # 各ケイパビリティのデフォルトコスト
    DEFAULT_COSTS = {
        "research": 10.0,
        "content_generation": 50.0,
        "trend_detection": 15.0,
        "system_monitoring": 0.0,
    }

    def __init__(self, get_pool_func):
        """
        Args:
            get_pool_func: async callable that returns asyncpg pool
        """
        self._get_pool = get_pool_func

    async def check_credits(self, api_key: str) -> dict:
        """Check remaining credits for an API key.

        Returns:
            dict with credits_remaining, total_spent, last_used
        """
        try:
            pool = await self._get_pool()
            row = await pool.fetchrow(
                "SELECT credits_remaining, total_spent, last_used "
                "FROM api_credits WHERE api_key = $1",
                api_key,
            )
            if not row:
                return {
                    "api_key": api_key,
                    "credits_remaining": 0.0,
                    "total_spent": 0.0,
                    "last_used": None,
                    "exists": False,
                }
            return {
                "api_key": api_key,
                "credits_remaining": float(row["credits_remaining"]),
                "total_spent": float(row["total_spent"]),
                "last_used": row["last_used"].isoformat() if row["last_used"] else None,
                "exists": True,
            }
        except Exception as e:
            logger.error(f"クレジット確認エラー: {e}")
            raise

    async def deduct_credits(self, api_key: str, amount: float, description: str) -> dict:
        """Deduct credits for a tool call.

        Args:
            api_key: The API key to charge
            amount: Credits to deduct
            description: What the credits are for (e.g. "research call")

        Returns:
            dict with success status and remaining credits

        Raises:
            ValueError: If insufficient credits
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT credits_remaining FROM api_credits "
                        "WHERE api_key = $1 FOR UPDATE",
                        api_key,
                    )
                    if not row:
                        raise ValueError(f"API key not found: {api_key}")

                    remaining = float(row["credits_remaining"])
                    if remaining < amount:
                        raise ValueError(
                            f"Insufficient credits: {remaining} < {amount}"
                        )

                    new_remaining = remaining - amount
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "UPDATE api_credits "
                        "SET credits_remaining = $1, total_spent = total_spent + $2, "
                        "    last_used = $3 "
                        "WHERE api_key = $4",
                        new_remaining, amount, now, api_key,
                    )

            logger.info(
                f"クレジット消費: key={api_key[:8]}... amount={amount} "
                f"desc={description} remaining={new_remaining}"
            )
            return {
                "success": True,
                "credits_deducted": amount,
                "credits_remaining": new_remaining,
                "description": description,
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"クレジット消費エラー: {e}")
            raise

    async def add_credits(self, api_key: str, amount: float) -> dict:
        """Add credits (manual top-up for now).

        If the API key doesn't exist yet, creates it.

        Args:
            api_key: The API key to top up
            amount: Credits to add

        Returns:
            dict with new balance
        """
        try:
            pool = await self._get_pool()
            now = datetime.now(timezone.utc)
            await pool.execute(
                "INSERT INTO api_credits (api_key, credits_remaining, total_spent, created_at) "
                "VALUES ($1, $2, 0, $3) "
                "ON CONFLICT (api_key) DO UPDATE "
                "SET credits_remaining = api_credits.credits_remaining + $2",
                api_key, amount, now,
            )

            row = await pool.fetchrow(
                "SELECT credits_remaining FROM api_credits WHERE api_key = $1",
                api_key,
            )
            new_balance = float(row["credits_remaining"]) if row else amount

            logger.info(
                f"クレジット追加: key={api_key[:8]}... amount={amount} "
                f"new_balance={new_balance}"
            )
            return {
                "success": True,
                "credits_added": amount,
                "credits_remaining": new_balance,
            }
        except Exception as e:
            logger.error(f"クレジット追加エラー: {e}")
            raise

    def get_capability_cost(self, capability: str) -> float:
        """Get the credit cost for a capability.

        Args:
            capability: Name of the capability (e.g. "research")

        Returns:
            Credit cost (float)
        """
        return self.DEFAULT_COSTS.get(capability, 10.0)

    async def validate_and_charge(self, api_key: str, capability: str) -> dict:
        """Validate API key has enough credits and charge for a capability.

        Convenience method combining check + deduct.

        Args:
            api_key: The API key
            capability: The capability being invoked

        Returns:
            dict with charge details

        Raises:
            ValueError: If insufficient credits or unknown key
        """
        cost = self.get_capability_cost(capability)
        if cost == 0.0:
            return {
                "success": True,
                "credits_deducted": 0.0,
                "description": f"{capability} (free)",
            }
        return await self.deduct_credits(
            api_key, cost, f"a2a invoke: {capability}"
        )
