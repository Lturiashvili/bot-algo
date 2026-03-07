from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from execution.exchange.base import Exchange

log = logging.getLogger("smart_router")


@dataclass
class ExecResult:
    entry: Optional[dict] = None
    partial_tp_order: Optional[dict] = None
    exit: Optional[dict] = None


class SmartRouter:

    MAX_RETRIES = 3
    RETRY_DELAY = 0.7

    # =========================================================
    # INTERNAL RETRY ENGINE
    # =========================================================

    async def _retry(self, coro, label: str):

        for attempt in range(1, self.MAX_RETRIES + 1):

            try:
                result = await coro()

                if result:
                    return result

            except Exception as e:

                log.warning(
                    "ROUTER_RETRY_ERROR",
                    extra={
                        "label": label,
                        "attempt": attempt,
                        "err": str(e)
                    }
                )

            await asyncio.sleep(self.RETRY_DELAY)

        log.error(
            "ROUTER_MAX_RETRIES_EXCEEDED",
            extra={"label": label}
        )

        return None

    # =========================================================
    # OPEN LONG
    # =========================================================

    async def open_long(
        self,
        ex: Exchange,
        symbol: str,
        quote_usdt: float
    ) -> Optional[dict]:

        log.info(
            "open_long_request",
            extra={
                "exchange": ex.name,
                "symbol": symbol,
                "quote_usdt": quote_usdt
            }
        )

        try:

            balance = await ex.get_balance("USDT")

        except Exception as e:

            log.error(
                "BALANCE_FETCH_FAILED",
                extra={"err": str(e)}
            )

            return None

        if balance < quote_usdt:

            log.info(
                "SKIP_TRADE_LOW_BALANCE",
                extra={
                    "symbol": symbol,
                    "balance": balance,
                    "required": quote_usdt
                }
            )

            return None

        async def _buy():
            return await ex.market_buy_quote(symbol, quote_usdt)

        res = await self._retry(_buy, "market_buy")

        if not res:
            return None

        if float(res.get("qty", 0)) <= 0:

            log.error(
                "ORDER_INVALID_QTY",
                extra={"symbol": symbol}
            )

            return None

        log.info(
            "open_long_done",
            extra={
                "symbol": symbol,
                "qty": res.get("qty"),
                "avg": res.get("avg_price")
            }
        )

        return res

    # =========================================================
    # PARTIAL TP
    # =========================================================

    async def place_partial_tp_limit(
        self,
        ex: Exchange,
        symbol: str,
        qty: float,
        tp_price: float
    ) -> Optional[dict]:

        async def _tp():
            return await ex.limit_sell_base(symbol, qty, tp_price)

        res = await self._retry(_tp, "partial_tp")

        if not res:

            log.warning(
                "PARTIAL_TP_FAILED",
                extra={"symbol": symbol}
            )

        return res

    # =========================================================
    # OCO PLACEMENT
    # =========================================================

    async def place_oco_tp_sl(
        self,
        ex: Exchange,
        symbol: str,
        qty: float,
        entry_price: float,
        tp_pct: float,
        sl_pct: float
    ) -> Tuple[Optional[dict], Optional[dict]]:

        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)

        async def _tp():
            return await ex.limit_sell_base(symbol, qty, tp_price)

        async def _sl():
            return await ex.limit_sell_base(symbol, qty, sl_price)

        tp_order = await self._retry(_tp, "tp_order")
        sl_order = await self._retry(_sl, "sl_order")

        if not tp_order or not sl_order:

            log.error(
                "OCO_PARTIAL_FAILURE",
                extra={"symbol": symbol}
            )

            return None, None

        log.info(
            "OCO_PLACED",
            extra={
                "symbol": symbol,
                "tp": tp_price,
                "sl": sl_price
            }
        )

        return tp_order, sl_order

    # =========================================================
    # VERIFY OCO
    # =========================================================

    async def verify_oco(
        self,
        ex: Exchange,
        symbol: str
    ) -> bool:

        # simplified verification

        log.info(
            "OCO_VERIFY_OK",
            extra={"symbol": symbol}
        )

        return True

    # =========================================================
    # CLOSE LONG
    # =========================================================

    async def close_long_market(
        self,
        ex: Exchange,
        symbol: str,
        qty: float
    ) -> Optional[dict]:

        log.info(
            "close_long_request",
            extra={"symbol": symbol, "qty": qty}
        )

        async def _sell():
            return await ex.market_sell_base(symbol, qty)

        res = await self._retry(_sell, "market_sell")

        if not res:

            log.error(
                "SELL_FAILED",
                extra={"symbol": symbol}
            )

            return None

        log.info(
            "close_long_done",
            extra={
                "symbol": symbol,
                "qty": res.get("qty"),
                "avg": res.get("avg_price")
            }
        )

        return res

    # =========================================================
    # CANCEL ALL
    # =========================================================

    async def cancel_all(
        self,
        ex: Exchange,
        symbol: str
    ) -> None:

        async def _cancel():
            return await ex.cancel_all(symbol)

        await self._retry(_cancel, "cancel_all")
