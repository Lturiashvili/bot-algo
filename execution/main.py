from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict

import pandas as pd

from execution.config import Settings
from execution.database import TradeDB
from execution.exchange.base import TokenBucket
from execution.exchange.binance_rest import BinanceSpot
from execution.exchange.bybit_rest import BybitSpot
from execution.exchange.binance_ws import BinanceWS
from execution.exchange.bybit_ws import BybitWS
from execution.ml.signal_model import MLSignalFilter
from execution.portfolio import Portfolio
from execution.risk.manager import RiskManager
from execution.smart_router import SmartRouter
from execution.strategy.orderbook_alpha import compute_long_signal


logging.basicConfig(
    level=Settings().LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("engine")


def _ms_to_dt(ms: int):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class Engine:

    def __init__(self, s: Settings):

        self.s = s
        self.db = TradeDB(s.DB_PATH)

        self.portfolio = Portfolio()

        self.router = SmartRouter()

        self.ml = MLSignalFilter(enabled=s.ML_ENABLED, min_proba=s.ML_MIN_PROBA)

        self.risk = RiskManager(
            position_pct=s.POSITION_PCT,
            stop_atr_mult=s.STOP_ATR_MULT,
            tp_atr_mult=s.TP_ATR_MULT,
            taker_fee=s.TAKER_FEE,
            maker_fee=s.MAKER_FEE,
            slippage_bps=s.SLIPPAGE_BPS,
            partial_tp_pct=s.PARTIAL_TP_PCT,
        )

        self._df: Dict[str, pd.DataFrame] = {}

        self._idx = {s: 0 for s in self.s.SYMBOLS}

        # execution race fix
        self._locks = {s: asyncio.Lock() for s in self.s.SYMBOLS}

        limiter = TokenBucket(rate_per_sec=s.REST_RATE_PER_SEC, burst=s.REST_BURST)

        if s.EXCHANGE == "binance":

            self.ex = BinanceSpot(
                s.BINANCE_BASE_URL,
                s.BINANCE_API_KEY,
                s.BINANCE_API_SECRET,
                limiter,
            )

            self.ws = BinanceWS(s.BINANCE_WS_URL)

        else:

            self.ex = BybitSpot(
                s.BYBIT_API_KEY,
                s.BYBIT_API_SECRET,
            )

            self.ws = BybitWS(s.BYBIT_WS_URL)

    # -------------------------------------------------
    # REST RETRY
    # -------------------------------------------------

    async def safe_rest(self, fn, *args, retries=3):

        for i in range(retries):

            try:
                return await fn(*args)

            except Exception as e:

                log.warning(f"REST_RETRY {fn.__name__} {i} {e}")

                await asyncio.sleep(1 + i)

        raise RuntimeError("REST failed")

    # -------------------------------------------------
    # STARTUP SYNC
    # -------------------------------------------------

    async def sync_with_exchange(self):

        try:

            positions = await self.safe_rest(self.ex.fetch_positions)

            for p in positions:

                symbol = p["symbol"]

                if float(p["size"]) > 0:

                    log.info(f"SYNC_POSITION {symbol}")

                    self.portfolio.register_position(symbol)

        except Exception as e:

            log.warning(f"SYNC_FAILED {e}")

    # -------------------------------------------------
    # HISTORY
    # -------------------------------------------------

    async def seed_history(self, symbol):

        candles = await self.safe_rest(
            self.ex.fetch_ohlcv,
            symbol,
            self.s.PRIMARY_TF,
            600,
        )

        df = pd.DataFrame(
            [
                {
                    "ts": _ms_to_dt(c["ts"]),
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"],
                }
                for c in candles
            ]
        ).set_index("ts")

        self._df[symbol] = df

    # -------------------------------------------------
    # POSITION SIZE
    # -------------------------------------------------

    async def compute_size(self):

        balance = await self.safe_rest(self.ex.fetch_usdt_balance)

        size = balance * self.s.POSITION_PCT

        if size < 3:
            return None

        return size

    # -------------------------------------------------
    # EXIT DETECTION
    # -------------------------------------------------

    async def check_position_exit(self, symbol):

        if not self.portfolio.has_position(symbol):
            return

        pos = await self.safe_rest(self.ex.fetch_position, symbol)

        if not pos or float(pos["size"]) == 0:

            log.info(f"POSITION_CLOSED {symbol}")

            self.portfolio.close_position(symbol)

    # -------------------------------------------------
    # SIGNAL
    # -------------------------------------------------

    def build_tf(self, df):

        df2 = df.resample(self.s.SECONDARY_TF).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        df3 = df.resample(self.s.CONFIRM_TF).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        df4 = df.resample("1h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        return df2, df3, df4

    # -------------------------------------------------
    # TRADE EXECUTION
    # -------------------------------------------------

    async def execute_trade(self, symbol, signal):

        async with self._locks[symbol]:

            if self.portfolio.has_position(symbol):
                return

            if self.portfolio.in_cooldown(symbol, self._idx[symbol]):
                return

            size = await self.compute_size()

            if not size:
                return

            order = await self.safe_rest(
                self.router.open_long,
                self.ex,
                symbol,
                size,
            )

            if not order:

                log.error("ORDER_FAILED")

                return

            log.info(f"ORDER_OPENED {symbol}")

            self.portfolio.register_position(symbol)

    # -------------------------------------------------
    # STRATEGY
    # -------------------------------------------------

    async def maybe_open_position(self, symbol):

        df = self._df[symbol]

        if len(df) < 50:
            return

        df2, df3, df4 = self.build_tf(df)

        sig = compute_long_signal(
            df2,
            df3,
            df4,
            self.s.EMA_FAST,
            self.s.EMA_SLOW,
            self.s.RSI_PERIOD,
            self.s.RSI_LONG_MIN,
            self.s.ATR_PERIOD,
        )

        if not sig:
            return

        if sig.action != "BUY":
            return

        if self.s.ML_ENABLED:

            if not self.ml.allow(sig.features):

                log.info("ML_BLOCK")

                return

        await self.execute_trade(symbol, sig)

    # -------------------------------------------------
    # CANDLE UPDATE
    # -------------------------------------------------

    def update_candle(self, symbol, msg):

        df = self._df[symbol]

        ts = _ms_to_dt(msg.ts)

        candle = {
        "open": msg.kline.open,
        "high": msg.kline.high,
        "low": msg.kline.low,
        "close": msg.kline.close,
        "volume": msg.kline.volume,
    }

    # -----------------------------------------
    # duplicate candle protection
    # -----------------------------------------

    if ts in df.index:
        df.loc[ts] = candle
        return

    # -----------------------------------------
    # out-of-order protection
    # -----------------------------------------

    if len(df) > 0:

        last_ts = df.index[-1]

        if ts < last_ts:

            log.warning(
                f"CANDLE_OUT_OF_ORDER {symbol} ts={ts} last={last_ts}"
            )

            return

    # -----------------------------------------
    # append new candle
    # -----------------------------------------

    df.loc[ts] = candle


    # increment only on NEW candle
    self._idx[symbol] += 1

    # -------------------------------------------------
    # ENGINE LOOP
    # -------------------------------------------------

    async def run(self):

        log.info("ENGINE_START")

        await self.sync_with_exchange()

        for s in self.s.SYMBOLS:
            await self.seed_history(s)

        async for msg in self.ws.stream_klines(
            list(self.s.SYMBOLS),
            self.s.PRIMARY_TF,
        ):

            if not msg.is_closed:
                continue

            self.update_candle(msg.symbol, msg)

            await self.check_position_exit(msg.symbol)

            await self.maybe_open_position(msg.symbol)


async def main():

    s = Settings()

    engine = Engine(s)

    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
