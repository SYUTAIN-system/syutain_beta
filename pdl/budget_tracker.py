"""Budget tracking for PDL Session B.

Queries llm_cost_log to enforce daily budget limits for autonomous tasks.
"""
import os
import sys
from datetime import date

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def _load_limits() -> dict:
    """Load budget limits from config.yaml."""
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    sb = config.get("session_b", {})
    return {
        "daily_jpy": sb.get("budget_daily_jpy", 36),
        "per_task_jpy": sb.get("budget_per_task_jpy", 8),
    }


async def get_today_usage() -> float:
    """Get total Session B cost for today in JPY."""
    from tools.db_pool import get_connection, init_pool

    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(amount_jpy), 0) AS total
               FROM llm_cost_log
               WHERE recorded_at::date = $1
                 AND goal_id LIKE 'pdl_%'""",
            date.today(),
        )
        return float(row["total"]) if row else 0.0


async def check_budget() -> bool:
    """Check if Session B has remaining budget today.

    Returns True if under daily limit, False otherwise.
    """
    limits = _load_limits()
    usage = await get_today_usage()
    return usage < limits["daily_jpy"]


async def get_remaining() -> float:
    """Get remaining budget in JPY for today."""
    limits = _load_limits()
    usage = await get_today_usage()
    return max(0.0, limits["daily_jpy"] - usage)


async def record_cost(task_id: int, amount_jpy: float, model: str = "claude-code") -> None:
    """Record a PDL task cost to llm_cost_log."""
    from tools.db_pool import get_connection, init_pool

    await init_pool(min_size=1, max_size=2)
    async with get_connection() as conn:
        await conn.execute(
            """INSERT INTO llm_cost_log (model, tier, amount_jpy, goal_id, is_info)
               VALUES ($1, $2, $3, $4, $5)""",
            model,
            "session_b",
            amount_jpy,
            f"pdl_{task_id}",
            False,
        )


def check_budget_sync() -> bool:
    """Synchronous wrapper for shell script usage. Prints 'OK' or 'OVER'."""
    import asyncio

    try:
        result = asyncio.run(check_budget())
        remaining = asyncio.run(get_remaining())
        if result:
            print(f"OK:{remaining:.1f}")
        else:
            print(f"OVER:0.0")
        return result
    except Exception as e:
        # If DB is unavailable, allow task (fail-open for budget check)
        print(f"OK:999.0")
        return True


if __name__ == "__main__":
    check_budget_sync()
