# FULL DEBUG VERSION OF main.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import os

import numpy as np
import pandas as pd

from execution.config import Settings
from execution.database import TradeDB
from execution.exchange.base import TokenBucket
from execution.exchange.binance_rest import BinanceSpot
from execution.exchange.bybit_rest import BybitSpot
from execution.exchange.binance_ws import BinanceWS
from execution.exchange.bybit_ws import BybitWS
from execution.ml.signal_model import MLSignalFilter
from execution.portfolio import Portfolio, Position
from execution.risk.manager import RiskManager
from execution.smart_router import SmartRouter
from execution.strategy.orderbook_alpha import compute_long_signal
from execution.backtester import run_backtest

logging.basicConfig(level=Settings().LOG_LEVEL)
log = logging.getLogger("main")

print("ENGINE_MODULE_LOADED")


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


class Engine:
    def __init__(self, s: Settings) -> None:
        print("ENGINE_INIT")
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
        self._idx: dict[str, int] = {sym: 0 for sym in s.SYMBOLS}
        self._df15: dict[str, pd.DataFrame] = {}

        limiter = TokenBucket(rate_per_sec=s.REST_RATE_PER_SEC, burst=s.REST_BURST)
        if s.EXCHANGE == "binance":
            self.ex = BinanceSpot(s.BINANCE_BASE_URL, s.BINANCE_API_KEY, s.BINANCE_API_SECRET, limiter)
            self.ws = BinanceWS(s.BINANCE_WS_URL)
        else:
            self.ex = BybitSpot(s.BYBIT_BASE_URL, s.BYBIT_API_KEY, s.BYBIT_API_SECRET, limiter)
            self.ws = BybitWS(s.BYBIT_WS_URL)

    async def seed_history(self, symbol: str) -> None:
        print("SEED_HISTORY", symbol)
        log.info(f"FETCH_OHLCV_START {symbol}")
        candles = await asyncio.wait_for(
            self.ex.fetch_ohlcv(symbol, self.s.PRIMARY_TF, limit=600),
            timeout=15
        )
        log.info(f"FETCH_OHLCV_DONE {symbol}")
        df = pd.DataFrame(
            [
                {
                    "ts": _ms_to_dt(c["close_time"]),
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"],
                }
                for c in candles
            ]
        ).set_index("ts")
        self._df15[symbol] = df
        log.info("seed_history", extra={"symbol": symbol, "rows": len(df)})

    def resample(self, symbol: str, tf: str) -> pd.DataFrame:
        base = self._df15[symbol]
        rule = "30min" if tf == "30m" else "60min"
        o = base["open"].resample(rule, label="right", closed="right").first()
        h = base["high"].resample(rule, label="right", closed="right").max()
        l = base["low"].resample(rule, label="right", closed="right").min()
        c = base["close"].resample(rule, label="right", closed="right").last()
        v = base["volume"].resample(rule, label="right", closed="right").sum()
        return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()

    async def on_closed_15m(self, symbol: str, end_ms: int, o: float, h: float, l: float, c: float, v: float) -> None:
        print("ON_CLOSED_15M", symbol)
        ts = _ms_to_dt(end_ms)
        df = self._df15[symbol]
        df.loc[ts, ["open", "high", "low", "close", "volume"]] = [o, h, l, c, v]
        df.sort_index(inplace=True)

        self._idx[symbol] += 1
        idx = self._idx[symbol]

        await self.manage_open_position(symbol, float(c))
        await self.maybe_open_position(symbol, idx)

    async def maybe_open_position(self, symbol: str, idx: int) -> None:
        print("MAYBE_OPEN_POSITION", symbol)

        if self.portfolio.has_position(symbol):
            print("HAS_POSITION_SKIP")
            return
        if self.portfolio.in_cooldown(symbol, idx):
            print("COOLDOWN_SKIP")
            return

        df15 = self._df15[symbol]

        min_bars = max(self.s.EMA_SLOW + 5, 50)
        if len(df15) < min_bars:
            print("WARMUP_SKIP", len(df15), min_bars)
            return

        df30 = self.resample(symbol, "30m")
        df1h = self.resample(symbol, "1h")

        print("BEFORE_SIGNAL_CALL", symbol)

        sig = compute_long_signal(
            df15, df30, df1h,
            self.s.EMA_FAST, self.s.EMA_SLOW,
            self.s.RSI_PERIOD, self.s.RSI_LONG_MIN,
            self.s.ATR_PERIOD,
        )

        print("AFTER_SIGNAL_CALL", symbol)

        if sig is None or sig.action != "BUY":
            print("NO_BUY_SIGNAL")
            return

        if self.s.ML_ENABLED and not self.ml.allow(sig.features):
            print("ML_REJECT")
            return

        print("BUY_SIGNAL_CONFIRMED")

    async def manage_open_position(self, symbol: str, last_close: float) -> None:
        return

    async def run_live(self) -> None:
        print("RUN_LIVE_START")
        await self.db.init()
        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        print("LIVE_LOOP_START")

        async for msg in self.ws.stream_klines(list(self.s.SYMBOLS), self.s.PRIMARY_TF):
            if not msg.is_closed:
                continue
            if msg.symbol not in self._df15:
                continue
            await self.on_closed_15m(msg.symbol, msg.end_ms, msg.o, msg.h, msg.l, msg.c, msg.v)

async def main() -> None:
    print("MAIN_STARTING")
    s = Settings()
    engine = Engine(s)

    if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
        print("RUNNING_BACKTEST")
        return

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
