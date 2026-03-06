from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import os

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
from execution.execution_brain import ExecutionBrain
from execution.position_manager import PositionManager
from execution.strategy.orderbook_alpha import compute_long_signal
from ui.env_override import EnvOverrideBridge

logging.basicConfig(
    level=Settings().LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("main")


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


class Engine:

    def __init__(self, s: Settings) -> None:

        self.s = s
        self.db = TradeDB(s.DB_PATH)
        self.portfolio = Portfolio()

        self.risk = RiskManager(
            position_pct=s.POSITION_PCT,
            stop_atr_mult=s.STOP_ATR_MULT,
            tp_atr_mult=s.TP_ATR_MULT,
            taker_fee=s.TAKER_FEE,
            maker_fee=s.MAKER_FEE,
            slippage_bps=s.SLIPPAGE_BPS,
            partial_tp_pct=s.PARTIAL_TP_PCT,
        )

        self.ml = MLSignalFilter(enabled=s.ML_ENABLED, min_proba=s.ML_MIN_PROBA)
        self.router = SmartRouter()
        self.override = EnvOverrideBridge()
        self.execution_brain = ExecutionBrain(s, self.portfolio)

        self.position_manager = PositionManager(
            tp_pct=0.002,
            sl_pct=0.01,
            max_bars=30,
        )

        self._idx: dict[str, int] = {sym: 0 for sym in s.SYMBOLS}

        # 5m base dataframe
        self._df5: dict[str, pd.DataFrame] = {}

        self._execution_lock: set[str] = set()

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

    async def seed_history(self, symbol: str) -> None:

        log.info(f"FETCH_OHLCV_START {symbol}")

        candles = await asyncio.wait_for(
            self.ex.fetch_ohlcv(symbol, self.s.PRIMARY_TF, limit=600),
            timeout=15,
        )

        log.info(f"FETCH_OHLCV_DONE {symbol}")

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

        self._df5[symbol] = df

    async def maybe_open_position(self, symbol: str, idx: int) -> None:

        if symbol in self._execution_lock:
            return

        if self.portfolio.has_position(symbol):
            return

        if self.portfolio.in_cooldown(symbol, idx):
            return

        df5 = self._df5[symbol]

        if len(df5) < 50:
            return

        # multi timeframe build
        df15 = df5.resample("15min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        df30 = df5.resample("30min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        df1h = df5.resample("1h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        sig = compute_long_signal(
            df15,
            df30,
            df1h,
            self.s.EMA_FAST,
            self.s.EMA_SLOW,
            self.s.RSI_PERIOD,
            self.s.RSI_LONG_MIN,
            self.s.ATR_PERIOD,
        )

        if sig is None or sig.action != "BUY":
            return

        if self.s.ML_ENABLED and not self.ml.allow(sig.features):
            return

        capital = await self.ex.fetch_usdt_balance()

        if capital < 3:
            return

        self._execution_lock.add(symbol)

        try:

            order = await self.router.open_long(
                self.ex,
                symbol,
                capital,
            )

            if not order:
                return

        finally:

            self._execution_lock.discard(symbol)

    async def run_live(self) -> None:

        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        async for msg in self.ws.stream_klines(
            list(self.s.SYMBOLS),
            self.s.PRIMARY_TF,
        ):

            if not msg.is_closed:
                continue

            df = self._df5[msg.symbol]

            df.loc[_ms_to_dt(msg.ts)] = {
                "open": msg.kline.open,
                "high": msg.kline.high,
                "low": msg.kline.low,
                "close": msg.kline.close,
                "volume": msg.kline.volume,
            }

            self._df5[msg.symbol] = df

            self._idx[msg.symbol] += 1

            await self.maybe_open_position(
                msg.symbol,
                self._idx[msg.symbol],
            )


async def main() -> None:

    s = Settings()
    engine = Engine(s)

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
