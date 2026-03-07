# execution/position_manager.py

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class Position:
    """
    Represents a single open position.
    """

    def __init__(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ):
        self.symbol = symbol
        self.qty = float(qty)
        self.entry_price = float(entry_price)
        self.tp_price = tp_price
        self.sl_price = sl_price

    def set_tp_sl(self, tp_price: float, sl_price: float):
        """
        Set take-profit and stop-loss levels.
        """
        self.tp_price = tp_price
        self.sl_price = sl_price

    def unrealized_pnl(self, current_price: float) -> float:
        """
        Calculate unrealized PnL for LONG position.
        """
        return (current_price - self.entry_price) * self.qty

    def to_dict(self):

        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "tp_price": self.tp_price,
            "sl_price": self.sl_price,
        }


class PositionManager:
    """
    Tracks active trading positions.
    Designed for LONG-only spot trading systems.
    """

    def __init__(self):

        self.positions: Dict[str, Position] = {}

        logger.info("POSITION_MANAGER_INITIALIZED")

    # ----------------------------------------
    # OPEN POSITION
    # ----------------------------------------

    def open_position(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
    ) -> Position:

        if symbol in self.positions:
            logger.warning("POSITION_ALREADY_EXISTS %s", symbol)
            return self.positions[symbol]

        position = Position(symbol, qty, entry_price, tp, sl)

        self.positions[symbol] = position

        logger.info(
            "POSITION_OPENED | %s | qty=%.6f entry=%.6f",
            symbol,
            qty,
            entry_price,
        )

        return position

    # ----------------------------------------
    # CLOSE POSITION
    # ----------------------------------------

    def close_position(self, symbol: str) -> Optional[Position]:

        if symbol not in self.positions:
            logger.warning("POSITION_NOT_FOUND %s", symbol)
            return None

        position = self.positions.pop(symbol)

        logger.info(
            "POSITION_CLOSED | %s | qty=%.6f entry=%.6f",
            symbol,
            position.qty,
            position.entry_price,
        )

        return position

    # ----------------------------------------
    # GET POSITION
    # ----------------------------------------

    def get_position(self, symbol: str) -> Optional[Position]:

        return self.positions.get(symbol)

    # ----------------------------------------
    # POSITION EXISTS
    # ----------------------------------------

    def has_position(self, symbol: str) -> bool:

        return symbol in self.positions

    # ----------------------------------------
    # POSITION COUNT
    # ----------------------------------------

    def count_open_positions(self) -> int:

        return len(self.positions)

    # ----------------------------------------
    # ALL POSITIONS
    # ----------------------------------------

    def get_all_positions(self):

        return [p.to_dict() for p in self.positions.values()]

    # ----------------------------------------
    # CLEAR ALL (emergency)
    # ----------------------------------------

    def clear_all(self):

        logger.warning("CLEARING_ALL_POSITIONS")

        self.positions.clear()
