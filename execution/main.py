from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from execution.config import Settings
from execution.database import TradeDB
from execution.exchange.base import TokenBucket
from execution.exchange.binance_rest import BinanceSpot
from execution.exchange.bybit_rest import BybitSpot
from execution.exchange.binance_ws import BinanceWS
from execution.exchange.bybit_ws import BybitWS

from execution.portfolio import Portfolio
from execution.risk.manager import RiskManager
from execution.smart_router import SmartRouter
from execution.trade_manager import TradeManager

from execution.ml.signal_model import MLSignalFilter
from execution.strategy.orderbook_alpha import compute_long_signal
from ui.env_override import EnvOverrideBridge


logging.basicConfig(level=Settings().LOG_LEVEL)
log = logging.getLogger("main")


MAX_CANDLES = 2000


def _ms_to_dt(ms: int):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


class Engine:

    def __init__(self, s: Settings):

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

        self.ml = MLSignalFilter(
            enabled=s.ML_ENABLED,
            min_proba=s.ML_MIN_PROBA
        )

        self.router = SmartRouter()
        self.trade_manager = TradeManager(self.router)

        self.override = EnvOverrideBridge()

        self._df15: dict[str, pd.DataFrame] = {}

        limiter = TokenBucket(
            rate_per_sec=s.REST_RATE_PER_SEC,
            burst=s.REST_BURST
        )

        if s.EXCHANGE == "binance":

            self.ex = BinanceSpot(
                s.BINANCE_BASE_URL,
                s.BINANCE_API_KEY,
                s.BINANCE_API_SECRET,
                limiter
            )

            self.ws = BinanceWS(s.BINANCE_WS_URL)

        else:

            self.ex = BybitSpot(
                s.BYBIT_API_KEY,
                s.BYBIT_API_SECRET
            )

            self.ws = BybitWS(s.BYBIT_WS_URL)

    # =========================================================
    # HISTORY SEED
    # =========================================================

    async def seed_history(self, symbol: str):

        candles = await self.ex.fetch_ohlcv(
            symbol,
            self.s.PRIMARY_TF,
            limit=600
        )

        df = pd.DataFrame([
            {
                "ts": _ms_to_dt(c["ts"]),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            }
            for c in candles
        ]).set_index("ts")

        self._df15[symbol] = df

    # =========================================================
    # POSITION MONITOR
    # =========================================================

    async def monitor_positions(self, symbol: str):

        pos = self.portfolio.get(symbol)

        if not pos:
            return

        df = self._df15[symbol]

        price = float(df["close"].iloc[-1])

        if pos.tp_price and price >= pos.tp_price:

            log.info("TP_HIT", extra={"symbol": symbol, "price": price})

            await asyncio.wait_for(
                self.trade_manager.close_position(
                    self.ex,
                    self.portfolio,
                    symbol
                ),
                timeout=10
            )

            return

        if pos.stop_price and price <= pos.stop_price:

            log.warning("SL_HIT", extra={"symbol": symbol, "price": price})

            await asyncio.wait_for(
                self.trade_manager.close_position(
                    self.ex,
                    self.portfolio,
                    symbol
                ),
                timeout=10
            )

            return

    # =========================================================
    # BUY ENGINE
    # =========================================================

    async def maybe_open_position(self, symbol: str, idx: int):

        if self.portfolio.has_position(symbol):
            return

        if self.portfolio.in_cooldown(symbol, idx):
            return

        df15 = self._df15[symbol]

        min_bars = max(self.s.EMA_SLOW + 5, 50)

        if len(df15) < min_bars:
            return

        sig = compute_long_signal(
            df15,
            df15,
            df15,
            self.s.EMA_FAST,
            self.s.EMA_SLOW,
            self.s.RSI_PERIOD,
            self.s.RSI_LONG_MIN,
            self.s.ATR_PERIOD,
        )

        if sig is None:
            return

        if sig.action != "BUY":
            return

        if self.s.ML_ENABLED and not self.ml.allow(sig.features):
            return

        try:

            balance = await asyncio.wait_for(
                self.ex.get_balance("USDT"),
                timeout=5
            )

            if balance <= 0:
                return

            price = float(df15["close"].iloc[-1])

            size_usdt = self.risk.order_notional_usdt(balance)

            if size_usdt < 5:
                return

            await asyncio.wait_for(
                self.trade_manager.open_long(
                    self.ex,
                    self.portfolio,
                    symbol,
                    size_usdt,
                    price
                ),
                timeout=10
            )

        except asyncio.TimeoutError:

            log.warning("EXECUTION_TIMEOUT", extra={"symbol": symbol})

        except Exception as e:

            log.exception(f"EXECUTION_ERROR {symbol} err={e}")

    # =========================================================
    # LIVE LOOP
    # =========================================================

    async def run_live(self):

        await self.db.init()

        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        while True:

            try:

                async for msg in self.ws.stream_klines(
                    list(self.s.SYMBOLS),
                    self.s.PRIMARY_TF
                ):

                    if not msg.is_closed:
                        continue

                    if msg.symbol not in self._df15:
                           self._df15[msg.symbol] = pd.DataFrame(
                               columns=["open","high","low","close","volume"],
                               dtype=float
                           )

                    df = self._df15[msg.symbol]

                    new_row = {
                        "open": msg.open,
                        "high": msg.high,
                        "low": msg.low,
                        "close": msg.close,
                        "volume": msg.volume
                    }

                    df.loc[_ms_to_dt(msg.start_ms)] = new_row

                    if len(df) > MAX_CANDLES:
                        self._df15[msg.symbol] = df.iloc[-MAX_CANDLES:]

                    idx = len(df)

                    await self.monitor_positions(msg.symbol)

                    await self.maybe_open_position(
                        msg.symbol,
                        idx
                    )

            except Exception as e:

                log.error(
                    "MAIN_LOOP_EXCEPTION",
                    extra={"err": str(e)}
                )

                await asyncio.sleep(2)


async def main():

    s = Settings()

    engine = Engine(s)

    if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
        return

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
