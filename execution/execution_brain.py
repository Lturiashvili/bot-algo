import time
import logging
from typing import Optional, Dict

logger = logging.getLogger("execution_brain")

class ExecutionBrain:
    def __init__(self, config, portfolio):
        self.config = config
        self.portfolio = portfolio

        self.last_trade_timestamps = []
        self.symbol_last_trade: Dict[str, float] = {}

    def can_trade_symbol(self, symbol: str, now: float) -> bool:
        last = self.symbol_last_trade.get(symbol, 0)
        cooldown_sec = getattr(self.config, 'SYMBOL_COOLDOWN_SECONDS', 1800)  # 30 წუთი default
        return now - last >= cooldown_sec

    def can_trade_global(self, now: float) -> bool:
        window_sec = getattr(self.config, 'MAX_TRADES_WINDOW_SECONDS', 3600)     # 1 საათი
        max_in_window = getattr(self.config, 'MAX_TRADES_PER_WINDOW', 5)

        self.last_trade_timestamps = [t for t in self.last_trade_timestamps if now - t < window_sec]
        return len(self.last_trade_timestamps) < max_in_window

    def approve_trade(
        self,
        symbol: str,
        signal_strength: float = 1.0,
        regime: str = "NEUTRAL"
    ) -> Optional[dict]:
        now = time.time()

        if not self.can_trade_global(now):
            logger.info("გლობალური თროთლი → უარი")
            return None

        if not self.can_trade_symbol(symbol, now):
            logger.info(f"სიმბოლოს cooldown აქტიურია: {symbol}")
            return None

        exposure = self.portfolio.current_exposure()
        max_exposure = getattr(self.config, 'MAX_EXPOSURE_POSITIONS', 4)

        if exposure >= max_exposure:
            logger.info(f"მაქსიმალური ექსპოზიცია მიღწეულია ({exposure}/{max_exposure})")
            return None

        # რეჟიმის მიხედვით size multiplier (შეგიძლია გააფართოვო)
        size_mult = 1.0
        if regime == "BULL" and signal_strength > 0.75:
            size_mult = 1.0
        elif regime == "RANGE":
            size_mult = 0.6
        elif regime == "BEAR":
            size_mult = 0.4
        else:
            size_mult = 0.7

        # თუ ყველაფერი კარგადაა → დავამტკიცოთ
        self.last_trade_timestamps.append(now)
        self.symbol_last_trade[symbol] = now

        return {"approved": True, "size_multiplier": size_mult}
