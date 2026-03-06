# execution/main.py
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

# რელატიური იმპორტები — Render-ისთვის აუცილებელია
from .config import Settings
from .database import TradeDB
from .exchange.base import TokenBucket
from .exchange.binance_rest import BinanceSpot
from .exchange.bybit_rest import BybitSpot
from .exchange.binance_ws import BinanceWS
from .exchange.bybit_ws import BybitWS
from .ml.signal_model import MLSignalFilter
from .portfolio import Portfolio
from .risk.manager import RiskManager           # თუ risk/manager.py გაქვს
from .smart_router import SmartRouter
from .strategy.orderbook_alpha import compute_long_signal
from .ui.env_override import EnvOverrideBridge

# logging setup — უფრო საიმედო Render-ისთვის
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)
logger = logging.getLogger("main")

def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


class Engine:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.override = EnvOverrideBridge()  # თუ ui/env_override.py გაქვს

        # Exchange ინიციალიზაცია
        if self.s.EXCHANGE == "binance":
            self.ex = BinanceSpot()
            self.ws = BinanceWS()
        elif self.s.EXCHANGE == "bybit":
            self.ex = BybitSpot()
            self.ws = BybitWS()
        else:
            raise ValueError(f"Unsupported exchange: {self.s.EXCHANGE}")

        self.db = TradeDB(s.DB_PATH)
        self.portfolio = Portfolio()
        self.risk = RiskManager(
            position_pct=self.s.POSITION_PCT,
            stop_atr_mult=self.s.STOP_ATR_MULT,
            tp_atr_mult=self.s.TP_ATR_MULT,
            partial_tp_pct=self.s.PARTIAL_TP_PCT,
            taker_fee=0.00075,
            maker_fee=0.00025,
            slippage_bps=5,
        )
        self.router = SmartRouter(self.ex)
        self.ml_filter = MLSignalFilter()

        # Token bucket rate limiting-ისთვის (თუ გჭირდება)
        self.rate_limiter = TokenBucket(rate=8, burst=16)

        logger.info(f"Engine initialized | exchange={self.s.EXCHANGE} | symbols={self.s.SYMBOLS}")

    async def seed_history(self, symbol: str) -> None:
        """ჩაიტვირთოს საწყისი OHLCV"""
        try:
            ohlcv = await self.ex.get_ohlcv(symbol, self.s.PRIMARY_TF, limit=500)
            df = pd.DataFrame(ohlcv)
            # აქ შეიძლება დამუშავება, მაგრამ ჯერ მარტივად
            logger.debug(f"History seeded for {symbol}: {len(df)} candles")
        except Exception as e:
            logger.error(f"Failed to seed history for {symbol}: {e}")

    async def maybe_open_position(self, symbol: str, idx: int) -> None:
        """შენი ლოგიკის ადგილი — აქედან იწყება ტრეიდინგი"""
        override = self.override.read_override()
        if override.enabled and override.kill_switch:
            logger.warning("KILL SWITCH ACTIVE — no new positions")
            return

        if override.enabled and override.disable_new_entries:
            logger.info("New entries disabled via override")
            return

        # აქ უნდა მოხდეს სიგნალის გენერაცია
        # მაგალითად:
        # signal = compute_long_signal(df15, df30, df1h, ...)
        # თუ signal.action == "BUY":
        #     await self.router.market_buy(...)

        logger.debug(f"Checked {symbol} at index {idx} — no action yet")

    async def run_live(self) -> None:
        """ძირითადი live loop"""
        await self.db.init()

        # საწყისი ისტორიის ჩატვირთვა ყველა სიმბოლოსთვის
        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        try:
            async for msg in self.ws.stream_klines(
                symbols=self.s.SYMBOLS,
                timeframe=self.s.PRIMARY_TF
            ):
                if not msg.is_closed:
                    continue

                override = self.override.read_override()
                if override.enabled and override.kill_switch:
                    logger.warning("GLOBAL KILL SWITCH ACTIVE — halting")
                    continue

                await self.maybe_open_position(msg.symbol, 0)  # 0 = dummy index

        except asyncio.CancelledError:
            logger.info("Run loop cancelled")
        except Exception as e:
            logger.critical(f"Critical failure in run_live: {e}", exc_info=True)
            raise

    async def shutdown(self) -> None:
        """Graceful shutdown"""
        logger.info("Shutting down engine...")
        try:
            await self.ex.close()
            await self.ws.close()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def main() -> None:
    s = Settings()
    engine = Engine(s)

    if os.getenv("RUN_BACKTEST", "").strip() == "1":
        logger.info("BACKTEST mode — exiting main")
        return

    try:
        await engine.run_live()
    except KeyboardInterrupt:
        logger.info("Received Ctrl+C — shutting down")
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
    finally:
        await engine.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Main loop interrupted by user")
    except Exception as e:
        logger.critical(f"Main crashed: {e}", exc_info=True)
        raise
