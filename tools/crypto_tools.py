"""
SYUTAINβ V25 暗号通貨取引モジュール (Step 20)
GMOコイン / bitbank API連携 (ccxt経由)

全取引はApprovalManager承認（Tier 1）を必須とする。
取引履歴はPostgreSQLのcrypto_tradesテーブルに保存する。
"""

import os
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("syutain.crypto")

# APIキーは.envから取得（ハードコード禁止 - CLAUDE.md ルール8）
GMO_API_KEY = os.getenv("GMO_API_KEY", "")
GMO_API_SECRET = os.getenv("GMO_API_SECRET", "")
BITBANK_API_KEY = os.getenv("BITBANK_API_KEY", "")
BITBANK_API_SECRET = os.getenv("BITBANK_API_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/syutain_beta")

# 取引安全設定
MAX_TRADE_JPY = float(os.getenv("CRYPTO_MAX_TRADE_JPY", "50000"))  # 1回の最大取引額
DAILY_TRADE_LIMIT_JPY = float(os.getenv("CRYPTO_DAILY_LIMIT_JPY", "100000"))  # 日次上限


class CryptoTrader:
    """暗号通貨取引クライアント（ccxt経由）"""

    def __init__(self):
        self.exchanges = {}
        self._initialized = False

    async def initialize(self) -> bool:
        """取引所接続を初期化"""
        try:
            import ccxt.async_support as ccxt

            # GMOコイン
            if GMO_API_KEY and GMO_API_SECRET:
                self.exchanges["gmo"] = ccxt.gmo({
                    "apiKey": GMO_API_KEY,
                    "secret": GMO_API_SECRET,
                    "enableRateLimit": True,
                })
                logger.info("GMOコイン接続初期化完了")

            # bitbank
            if BITBANK_API_KEY and BITBANK_API_SECRET:
                self.exchanges["bitbank"] = ccxt.bitbank({
                    "apiKey": BITBANK_API_KEY,
                    "secret": BITBANK_API_SECRET,
                    "enableRateLimit": True,
                })
                logger.info("bitbank接続初期化完了")

            if not self.exchanges:
                logger.warning("暗号通貨取引所のAPIキーが設定されていません")
                return False

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"取引所初期化失敗: {e}")
            return False

    async def get_ticker(self, exchange: str, pair: str) -> Optional[dict]:
        """現在のティッカー（価格情報）を取得"""
        if exchange not in self.exchanges:
            logger.error(f"取引所 '{exchange}' は未初期化")
            return None
        try:
            ticker = await self.exchanges[exchange].fetch_ticker(pair)
            return {
                "exchange": exchange,
                "pair": pair,
                "last": ticker.get("last"),
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "volume": ticker.get("baseVolume"),
                "timestamp": ticker.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"ティッカー取得失敗 ({exchange}/{pair}): {e}")
            return None

    async def get_balance(self, exchange: str) -> Optional[dict]:
        """残高を取得"""
        if exchange not in self.exchanges:
            logger.error(f"取引所 '{exchange}' は未初期化")
            return None
        try:
            balance = await self.exchanges[exchange].fetch_balance()
            # 主要通貨のみ抽出
            result = {}
            for currency in ["JPY", "BTC", "ETH", "XRP"]:
                if currency in balance:
                    result[currency] = {
                        "free": balance[currency].get("free", 0),
                        "used": balance[currency].get("used", 0),
                        "total": balance[currency].get("total", 0),
                    }
            return result
        except Exception as e:
            logger.error(f"残高取得失敗 ({exchange}): {e}")
            return None

    async def _check_daily_limit(self, amount_jpy: float) -> bool:
        """日次取引上限チェック"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT COALESCE(SUM(ABS(amount * price)), 0) as daily_total
                    FROM crypto_trades
                    WHERE created_at::date = CURRENT_DATE
                    """,
                )
                daily_total = float(row["daily_total"]) if row else 0.0
                if daily_total + amount_jpy > DAILY_TRADE_LIMIT_JPY:
                    logger.warning(
                        f"日次取引上限超過: 現在 {daily_total:.0f}円 + "
                        f"新規 {amount_jpy:.0f}円 > 上限 {DAILY_TRADE_LIMIT_JPY:.0f}円"
                    )
                    return False
                return True
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"日次取引上限チェック失敗: {e}")
            return False  # 安全側に倒す

    async def place_order(
        self,
        exchange: str,
        pair: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        strategy: str = "manual",
        approval_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        注文を発行する

        重要: この関数を直接呼ぶ前に、必ずApprovalManagerの承認を得ること（Tier 1）

        Args:
            exchange: 取引所名 ("gmo" or "bitbank")
            pair: 通貨ペア (例: "BTC/JPY")
            side: "buy" or "sell"
            amount: 数量
            price: 指値価格（Noneの場合は成行）
            strategy: 取引戦略名
            approval_id: ApprovalManagerの承認ID
        """
        # 承認ID必須チェック（CLAUDE.md ルール11）
        if not approval_id:
            logger.error("暗号通貨取引にはApprovalManager承認が必須です (Tier 1)")
            return None

        if exchange not in self.exchanges:
            logger.error(f"取引所 '{exchange}' は未初期化")
            return None

        # 金額チェック
        ticker = await self.get_ticker(exchange, pair)
        if not ticker:
            return None

        estimated_jpy = amount * (ticker["last"] or 0)
        if estimated_jpy > MAX_TRADE_JPY:
            logger.error(
                f"取引額が上限を超過: {estimated_jpy:.0f}円 > {MAX_TRADE_JPY:.0f}円"
            )
            return None

        # 日次上限チェック
        if not await self._check_daily_limit(estimated_jpy):
            return None

        try:
            order_type = "limit" if price else "market"
            order = await self.exchanges[exchange].create_order(
                symbol=pair,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
            )

            # PostgreSQLに取引記録を保存
            await self._save_trade(
                exchange=exchange,
                pair=pair,
                side=side,
                amount=amount,
                price=price or ticker["last"],
                strategy=strategy,
            )

            logger.info(
                f"注文成功: {exchange} {side} {amount} {pair} "
                f"@ {price or 'market'} (approval_id={approval_id})"
            )
            return {
                "order_id": order.get("id"),
                "exchange": exchange,
                "pair": pair,
                "side": side,
                "amount": amount,
                "price": price or ticker["last"],
                "type": order_type,
                "status": order.get("status"),
            }

        except Exception as e:
            logger.error(f"注文失敗 ({exchange} {side} {pair}): {e}")
            return None

    async def _save_trade(
        self,
        exchange: str,
        pair: str,
        side: str,
        amount: float,
        price: float,
        fee_jpy: float = 0.0,
        pnl_jpy: float = 0.0,
        strategy: str = "manual",
    ):
        """取引履歴をPostgreSQLに保存"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                await conn.execute(
                    """
                    INSERT INTO crypto_trades
                        (exchange, pair, side, amount, price, fee_jpy, pnl_jpy, strategy)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    exchange, pair, side, amount, price, fee_jpy, pnl_jpy, strategy,
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"取引履歴保存失敗: {e}")

    async def get_trade_history(
        self, exchange: Optional[str] = None, limit: int = 50
    ) -> list:
        """PostgreSQLから取引履歴を取得"""
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                if exchange:
                    rows = await conn.fetch(
                        """
                        SELECT * FROM crypto_trades
                        WHERE exchange = $1
                        ORDER BY created_at DESC LIMIT $2
                        """,
                        exchange, limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT * FROM crypto_trades
                        ORDER BY created_at DESC LIMIT $1
                        """,
                        limit,
                    )
                return [dict(r) for r in rows]
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"取引履歴取得失敗: {e}")
            return []

    async def close(self):
        """取引所接続を閉じる"""
        for name, ex in self.exchanges.items():
            try:
                await ex.close()
                logger.info(f"取引所接続 '{name}' を閉じました")
            except Exception as e:
                logger.error(f"取引所接続終了エラー ({name}): {e}")
