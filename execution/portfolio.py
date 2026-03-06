from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict
import time

@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    entry_time: datetime
    entry_idx: int
    atr_at_entry: float
    stop_price: float
    tp_price: float
    best_price: float
    trailing_stop: float
    trailing_enabled: bool = True
    partial_done: bool = False
    trade_id: Optional[int] = None

class Portfolio:
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.cooldown_until: Dict[str, float] = {}
        self.trade_id_counter = 0

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def count_open_positions(self) -> int:
        return len(self.positions)

    def current_exposure(self) -> float:
        return len(self.positions)  # შეგიძლია გააფართოვო real USDT-ით

    def open(self, symbol: str, qty: float, entry_price: float, atr: float,
             stop: float, tp: float, idx: int) -> int:
        self.trade_id_counter += 1
        pos = Position(
            symbol=symbol,
            qty=qty,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            entry_idx=idx,
            atr_at_entry=atr,
            stop_price=stop,
            tp_price=tp,
            best_price=entry_price,
            trailing_stop=stop,
            trade_id=self.trade_id_counter
        )
        self.positions[symbol] = pos
        self.cooldown_until[symbol] = time.time() + 900 * 3  # 3 candle cooldown
        return pos.trade_id

    def close(self, symbol: str) -> None:
        self.positions.pop(symbol, None)
        self.cooldown_until.pop(symbol, None)

    def in_cooldown(self, symbol: str) -> bool:
        return time.time() < self.cooldown_until.get(symbol, 0)

    def update_trailing(self, symbol: str, current_price: float, atr: float):
        if symbol in self.positions:
            pos = self.positions[symbol]
            if current_price > pos.best_price:
                pos.best_price = current_price
                pos.trailing_stop = current_price - atr * 1.5
