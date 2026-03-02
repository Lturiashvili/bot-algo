from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


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

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def open(self, p: Position, current_idx: int, cooldown_candles: int) -> None:
        import time
        self.positions[p.symbol] = p
        # Convert candle cooldown to seconds (assume 15m candles default)
        cooldown_seconds = cooldown_candles * 900
        self.cooldown_until_ts[p.symbol] = time.time() + cooldown_seconds

    def close(self, symbol: str) -> None:
        self.positions.pop(symbol, None)

    def in_cooldown(self, symbol: str, current_idx: int) -> bool:
        import time
        until = self.cooldown_until_ts.get(symbol, 0.0)
        return time.time() < until

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
