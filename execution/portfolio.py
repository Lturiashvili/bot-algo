from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("portfolio")


@dataclass
class Position:

    symbol: str
    qty: float
    entry_price: float
    entry_time: datetime

    atr_at_entry: float
    stop_price: float
    tp_price: float

    best_price: float
    trailing_enabled: bool
    trailing_stop: float

    trade_id: int
    partial_done: bool = False


@dataclass
class Portfolio:

    positions: dict[str, Position] = field(default_factory=dict)
    cooldown_until_ts: dict[str, float] = field(default_factory=dict)

    # =========================================================
    # POSITION CHECK
    # =========================================================

    def has_position(self, symbol: str) -> bool:

        return symbol in self.positions

    # =========================================================
    # GET POSITION
    # =========================================================

    def get(self, symbol: str) -> Optional[Position]:

        return self.positions.get(symbol)

    # =========================================================
    # OPEN POSITION
    # =========================================================

    def open(self, p: Position, current_idx: int, cooldown_candles: int) -> None:

        if p.symbol in self.positions:

            log.warning(
                "POSITION_ALREADY_EXISTS",
                extra={"symbol": p.symbol}
            )

            return

        self.positions[p.symbol] = p

        cooldown_seconds = cooldown_candles * 900

        self.cooldown_until_ts[p.symbol] = time.time() + cooldown_seconds

        log.info(
            "PORTFOLIO_POSITION_OPENED",
            extra={
                "symbol": p.symbol,
                "qty": p.qty,
                "entry": p.entry_price
            }
        )

    # =========================================================
    # CLOSE POSITION
    # =========================================================

    def close(self, symbol: str) -> None:

        pos = self.positions.pop(symbol, None)

        if not pos:

            log.warning(
                "PORTFOLIO_CLOSE_MISSING",
                extra={"symbol": symbol}
            )

            return

        # cleanup cooldown as well
        self.cooldown_until_ts.pop(symbol, None)

        log.info(
            "PORTFOLIO_POSITION_CLOSED",
            extra={
                "symbol": symbol,
                "qty": pos.qty,
                "entry": pos.entry_price
            }
        )

    # =========================================================
    # COOLDOWN CHECK
    # =========================================================

    def in_cooldown(self, symbol: str, current_idx: int) -> bool:

        until = self.cooldown_until_ts.get(symbol, 0.0)

        return time.time() < until

    # =========================================================
    # PORTFOLIO SIZE
    # =========================================================

    def size(self) -> int:

        return len(self.positions)

    # =========================================================
    # CURRENT TIME
    # =========================================================

    @staticmethod
    def now() -> datetime:

        return datetime.now(timezone.utc)
