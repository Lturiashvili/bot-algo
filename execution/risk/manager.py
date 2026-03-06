from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class RiskManager:
    position_pct: float = 0.20          # % ბალანსიდან ერთ პოზიციაზე
    stop_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    partial_tp_pct: float = 0.50        # 50% პოზიციის გაყიდვა პირველ TP-ზე
    trailing_activation_mult: float = 1.5  # როდის ჩავრთოთ trailing
    taker_fee: float = 0.001
    slippage_bps: float = 5             # 0.05%

    def calculate_position_size(self, balance: float, entry_price: float) -> float:
        notional = balance * self.position_pct
        size = notional / entry_price
        return size

    def calculate_stops(self, entry: float, atr: float) -> Tuple[float, float]:
        stop = entry - (atr * self.stop_atr_mult)
        initial_tp = entry + (atr * self.tp_atr_mult)
        return stop, initial_tp

    def apply_slippage(self, price: float, is_buy: bool) -> float:
        slip = price * (self.slippage_bps / 10000)
        return price + slip if is_buy else price - slip

    def fee_cost(self, notional: float) -> float:
        return notional * self.taker_fee

    def should_trail(self, current_price: float, entry: float, atr: float) -> bool:
        profit_pct = (current_price - entry) / entry
        return profit_pct >= (self.trailing_activation_mult * self.stop_atr_mult * (atr / entry))

    def new_trailing_stop(self, current_best: float, atr: float) -> float:
        return current_best - (atr * self.stop_atr_mult)

    def partial_take_profit_qty(self, current_qty: float) -> float:
        return current_qty * self.partial_tp_pct
