import asyncio
import logging
from datetime import datetime
import os

from config import Settings
from portfolio import Portfolio
from risk_manager import RiskManager
from execution_brain import ExecutionBrain
from database import TradeDB   # თუ გაქვს database.py
# დანარჩენი იმპორტები შენი სტრუქტურის მიხედვით (exchange, strategy და ა.შ.)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("main")

class TradingEngine:
    def __init__(self):
        self.settings = Settings()
        self.portfolio = Portfolio()
        self.risk = RiskManager(
            position_pct=self.settings.POSITION_PCT,
            stop_atr_mult=self.settings.STOP_ATR_MULT,
            tp_atr_mult=self.settings.TP_ATR_MULT,
            partial_tp_pct=self.settings.PARTIAL_TP_PCT,
        )
        self.brain = ExecutionBrain(self.settings, self.portfolio)
        self.db = TradeDB(self.settings.DB_PATH)  # თუ გაქვს
        # აქ დაამატე exchange კლასი, websocket client და ა.შ.

    async def process_signal(self, symbol: str, current_price: float, atr: float, signal_strength: float):
        """მაგალითი: როგორ უნდა გამოიყენო brain + risk + portfolio ერთად"""
        decision = self.brain.approve_trade(
            symbol=symbol,
            signal_strength=signal_strength,
            regime="NEUTRAL"  # შეცვალე შენი ლოგიკით
        )

        if not decision:
            return

        balance = 10000.0  # ← აქ რეალურად exchange-დან აიღე
        qty = self.risk.calculate_position_size(balance, current_price)
        stop, tp = self.risk.calculate_stops(current_price, atr)

        trade_id = self.portfolio.open(
            symbol=symbol,
            qty=qty,
            entry_price=current_price,
            atr=atr,
            stop=stop,
            tp=tp,
            idx=0  # candle index თუ გაქვს
        )

        logger.info(f"პოზიცია გახსნილი: {symbol} | qty={qty:.4f} | entry={current_price:.2f}")

        # აქ შეგიძლია exchange-ზე გაგზავნა (market buy)

    async def monitor_positions(self):
        """მარტივი მონიტორინგის მაგალითი (loop-ში გაუშვი)"""
        while True:
            for symbol, pos in list(self.portfolio.positions.items()):
                # აქ current_price რეალურად websocket-დან ან API-დან
                current_price = pos.entry_price * 1.02  # ტესტისთვის

                # trailing განახლება
                if self.risk.should_trail(current_price, pos.entry_price, pos.atr_at_entry):
                    new_stop = self.risk.new_trailing_stop(pos.best_price, pos.atr_at_entry)
                    if new_stop > pos.trailing_stop:
                        pos.trailing_stop = new_stop
                        logger.info(f"Trailing stop განახლდა: {symbol} → {new_stop:.4f}")

                # partial TP ან full exit ლოგიკა აქვე

            await asyncio.sleep(10)  # ან შენი timeframe-ის მიხედვით

    async def run(self):
        logger.info("Trading Engine გაშვებულია")
        # აქ websocket loop ან polling loop
        await self.monitor_positions()


async def main():
    engine = TradingEngine()
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
