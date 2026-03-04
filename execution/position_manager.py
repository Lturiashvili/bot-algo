from __future__ import annotations

import logging

log = logging.getLogger("position_manager")


class PositionManager:

    def __init__(
        self,
        tp_pct: float = 0.02,
        sl_pct: float = 0.01,
        max_bars: int = 30,
    ):

        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.max_bars = max_bars

    async def maybe_close_position(
        self,
        router,
        exchange,
        portfolio,
        symbol: str,
        price: float,
        bar_index: int,
    ) -> None:

        if not portfolio.has_position(symbol):
            return

        pos = portfolio.get_position(symbol)

        entry_price = pos.entry_price
        entry_bar = pos.entry_index

        pnl_pct = (price - entry_price) / entry_price

        # TAKE PROFIT
        if pnl_pct >= self.tp_pct:

            log.info(
                f"TP_TRIGGER {symbol} pnl={pnl_pct:.4f}"
            )

            await router.close_long(
                exchange,
                symbol,
                pos.qty
            )

            portfolio.close_position(symbol)
            return

        # STOP LOSS
        if pnl_pct <= -self.sl_pct:

            log.info(
                f"SL_TRIGGER {symbol} pnl={pnl_pct:.4f}"
            )

            await router.close_long(
                exchange,
                symbol,
                pos.qty
            )

            portfolio.close_position(symbol)
            return

        # TIME EXIT
        if (bar_index - entry_bar) >= self.max_bars:

            log.info(
                f"TIME_EXIT {symbol}"
            )

            await router.close_long(
                exchange,
                symbol,
                pos.qty
            )

            portfolio.close_position(symbol)
