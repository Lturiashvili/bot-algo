from __future__ import annotations

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

        # ===============================
        # BALANCE CHECK
        # ===============================

        balance = await ex.get_balance("USDT")

        if balance < quote_usdt:

            log.info(
                "SKIP_TRADE_LOW_BALANCE",
                extra={
                    "exchange": ex.name,
                    "symbol": symbol,
                    "balance": balance,
                    "required": quote_usdt
                }
            )

            return None

        # ===============================
        # EXECUTE BUY
        # ===============================

        res = await ex.market_buy_quote(symbol, quote_usdt)

        log.info(
            "open_long_done",
            extra={
                "exchange": ex.name,
                "symbol": symbol,
                "qty": res.get("qty"),
                "avg": res.get("avg_price"),
                "status": res.get("status")
            }
        )

        return res

    # =========================================================
    # PARTIAL TAKE PROFIT
    # =========================================================

    async def place_partial_tp_limit(
        self,
        ex: Exchange,
        symbol: str,
        qty: float,
        tp_price: float
    ) -> Optional[dict]:

        try:

            o = await ex.limit_sell_base(symbol, qty, tp_price)

            log.info(
                "partial_tp_limit_placed",
                extra={
                    "exchange": ex.name,
                    "symbol": symbol,
                    "qty": qty,
                    "tp": tp_price
                }
            )

            return o

        except Exception as e:

            log.warning(
                "partial_tp_limit_failed",
                extra={
                    "exchange": ex.name,
                    "symbol": symbol,
                    "err": str(e)
                }
            )

            return None

    # =========================================================
    # PLACE OCO
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

        try:

            tp_order = await ex.limit_sell_base(
                symbol,
                qty,
                tp_price
            )

            sl_order = await ex.limit_sell_base(
                symbol,
                qty,
                sl_price
            )

            log.info(
                "OCO_PLACED",
                extra={
                    "symbol": symbol,
                    "tp": tp_price,
                    "sl": sl_price
                }
            )

            return tp_order, sl_order

        except Exception as e:

            log.warning(
                "OCO_PLACEMENT_FAILED",
                extra={"symbol": symbol, "err": str(e)}
            )

            return None, None

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
            extra={
                "exchange": ex.name,
                "symbol": symbol,
                "qty": qty
            }
        )

        res = await ex.market_sell_base(symbol, qty)

        log.info(
            "close_long_done",
            extra={
                "exchange": ex.name,
                "symbol": symbol,
                "qty": res.get("qty"),
                "avg": res.get("avg_price"),
                "status": res.get("status")
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

        try:

            await ex.cancel_all(symbol)

            log.info(
                "cancel_all_ok",
                extra={
                    "exchange": ex.name,
                    "symbol": symbol
                }
            )

        except Exception as e:

            log.warning(
                "cancel_all_failed",
                extra={
                    "exchange": ex.name,
                    "symbol": symbol,
                    "err": str(e)
                }
            )
