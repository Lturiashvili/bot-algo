from __future__ import annotations

import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from execution.exchange.base import Exchange
from execution.portfolio import Portfolio, Position
from execution.smart_router import SmartRouter

log = logging.getLogger("trade_manager")


class TradeManager:

    def __init__(self, router: SmartRouter):

        self.router = router

        # execution lock per symbol
        self._locks: dict[str, asyncio.Lock] = {}

    # =========================================================
    # GET LOCK
    # =========================================================

    def _get_lock(self, symbol: str) -> asyncio.Lock:

        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()

        return self._locks[symbol]

    # =========================================================
    # BUY EXECUTION
    # =========================================================

    async def open_long(
        self,
        ex: Exchange,
        portfolio: Portfolio,
        symbol: str,
        size_usdt: float,
        price: float,
        tp_pct: float = 0.02,
        sl_pct: float = 0.01
    ) -> bool:

        lock = self._get_lock(symbol)

        async with lock:

            if portfolio.has_position(symbol):

                log.info(
                    "BUY_SKIPPED_ALREADY_OPEN",
                    extra={"symbol": symbol}
                )

                return False

            try:

                order = await self.router.open_long(
                    ex,
                    symbol,
                    size_usdt
                )

                if not order:

                    log.error(
                        "ORDER_FAILED",
                        extra={"symbol": symbol}
                    )

                    return False

                qty = float(order.get("qty", 0))
                fill_price = float(order.get("avg_price", 0))

                if qty <= 0 or fill_price <= 0:

                    log.error(
                        "ORDER_FILL_INVALID",
                        extra={"symbol": symbol}
                    )

                    return False

                position = Position(
                    symbol=symbol,
                    qty=qty,
                    entry_price=fill_price,
                    entry_time=datetime.now(timezone.utc),
                    atr_at_entry=0.0,
                    stop_price=0.0,
                    tp_price=0.0,
                    best_price=fill_price,
                    trailing_enabled=False,
                    trailing_stop=0.0,
                    trade_id=0
                )

                portfolio.open(
                    position,
                    current_idx=0,
                    cooldown_candles=1
                )

                log.info(
                    "POSITION_OPENED",
                    extra={
                        "symbol": symbol,
                        "qty": qty,
                        "price": fill_price
                    }
                )

                ok = await self.place_safe_oco(
                    ex,
                    symbol,
                    qty,
                    fill_price,
                    tp_pct,
                    sl_pct
                )

                if not ok:

                    log.warning(
                        "OCO_FAILED_AFTER_BUY",
                        extra={"symbol": symbol}
                    )

                return True

            except Exception as e:

                log.error(
                    "BUY_EXECUTION_FAILED",
                    extra={
                        "symbol": symbol,
                        "err": str(e)
                    }
                )

                return False

    # =========================================================
    # SAFE OCO
    # =========================================================

    async def place_safe_oco(
        self,
        ex: Exchange,
        symbol: str,
        qty: float,
        entry_price: float,
        tp_pct: float,
        sl_pct: float
    ) -> bool:

        try:

            tp, sl = await self.router.place_oco_tp_sl(
                ex,
                symbol,
                qty,
                entry_price,
                tp_pct,
                sl_pct
            )

            if not tp or not sl:

                log.warning(
                    "OCO_PLACE_FAILED",
                    extra={"symbol": symbol}
                )

                return False

            ok = await self.router.verify_oco(ex, symbol)

            if not ok:

                log.warning(
                    "OCO_VERIFY_FAILED",
                    extra={"symbol": symbol}
                )

            return ok

        except Exception as e:

            log.warning(
                "place_safe_oco_error",
                extra={"symbol": symbol, "err": str(e)}
            )

            return False

    # =========================================================
    # CLOSE POSITION
    # =========================================================

    async def close_position(
        self,
        ex: Exchange,
        portfolio: Portfolio,
        symbol: str
    ) -> None:

        lock = self._get_lock(symbol)

        async with lock:

            if not portfolio.has_position(symbol):
                return

            pos = portfolio.positions.get(symbol)

            if not pos:
                return

            qty = pos.qty

            try:

                await self.router.cancel_all(ex, symbol)

                res = await self.router.close_long_market(
                    ex,
                    symbol,
                    qty
                )

                if not res:

                    log.error(
                        "SELL_FAILED",
                        extra={"symbol": symbol}
                    )

                    return

                portfolio.close(symbol)

                log.info(
                    "POSITION_CLOSED",
                    extra={"symbol": symbol, "qty": qty}
                )

            except Exception as e:

                log.warning(
                    "close_position_failed",
                    extra={"symbol": symbol, "err": str(e)}
                )

    # =========================================================
    # EMERGENCY CLOSE
    # =========================================================

    async def emergency_close(
        self,
        ex: Exchange,
        portfolio: Portfolio,
        symbol: str
    ) -> None:

        lock = self._get_lock(symbol)

        async with lock:

            if not portfolio.has_position(symbol):
                return

            pos = portfolio.positions.get(symbol)

            if not pos:
                return

            try:

                await self.router.close_long_market(
                    ex,
                    symbol,
                    pos.qty
                )

                portfolio.close(symbol)

                log.critical(
                    "EMERGENCY_POSITION_CLOSE",
                    extra={"symbol": symbol, "qty": pos.qty}
                )

            except Exception as e:

                log.critical(
                    "EMERGENCY_CLOSE_FAILED",
                    extra={"symbol": symbol, "err": str(e)}
                )
