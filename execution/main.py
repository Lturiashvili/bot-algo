# execution/main.py

import asyncio
import logging
import os
import sys
from datetime import datetime

# ყველა იმპორტი ახლა რელატიურია execution/ საქაღალდის შიგნით
from .config import Settings
from .database import TradeDB
from .portfolio import Portfolio
from .risk_manager import RiskManager
from .execution_brain import ExecutionBrain
from .smart_router import SmartRouter

# exchange-ებიდან
from .exchange.base import Exchange
from .exchange.binance_rest import BinanceSpot
from .exchange.bybit_rest import BybitSpot

# სტრატეგია
from .strategy.orderbook_alpha import compute_long_signal

# logging setup
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")

class Engine:
    def __init__(self):
        self.settings = Settings()
        
        # exchange ინიციალიზაცია
        if self.settings.EXCHANGE == "binance":
            self.ex: Exchange = BinanceSpot()
        elif self.settings.EXCHANGE == "bybit":
            self.ex: Exchange = BybitSpot()
        else:
            raise ValueError(f"Unsupported exchange: {self.settings.EXCHANGE}")

        self.db = TradeDB(self.settings.DB_PATH)
        self.portfolio = Portfolio()
        self.risk = RiskManager(
            position_pct=self.settings.POSITION_PCT,
            stop_atr_mult=self.settings.STOP_ATR_MULT,
            tp_atr_mult=self.settings.TP_ATR_MULT,
            partial_tp_pct=self.settings.PARTIAL_TP_PCT,
            taker_fee=0.00075,          # შეცვალე თუ გჭირდება
            maker_fee=0.00025,
            slippage_bps=5,
        )
        self.brain = ExecutionBrain(self.settings, self.portfolio)
        self.router = SmartRouter(self.ex)

        logger.info(f"Engine initialized | Exchange: {self.settings.EXCHANGE} | Symbols: {self.settings.SYMBOLS}")

    async def run(self):
        logger.info("Engine starting...")
        
        # აქ უნდა იყოს websocket ან polling loop
        # მაგალითად ძალიან მარტივი ტესტ-ლუპი (შეცვალე შენი რეალური ლოგიკით)
        while True:
            try:
                for symbol in self.settings.SYMBOLS:
                    # მაგალითად: price-ის მიღება
                    price = await self.ex.get_price(symbol)
                    logger.debug(f"{symbol} price: {price}")

                    # აქ შეიძლება იყოს შენი სიგნალის გენერაცია
                    # მაგ: signal = compute_long_signal(...)

                    # ტესტისთვის: ყოველ 60 წამში ლოგავს
                    await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                await asyncio.sleep(10)

async def main():
    engine = Engine()
    try:
        await engine.run()
    finally:
        await engine.ex.close()
        logger.info("Engine shutdown")

if __name__ == "__main__":
    asyncio.run(main())
