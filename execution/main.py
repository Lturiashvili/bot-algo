from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from execution.config import Settings
from execution.module_switches import enabled

# =========================================================
# OPTIONAL IMPORTS
# =========================================================

if enabled("database"):
    from execution.database import TradeDB

if enabled("guardian"):
    from execution.system_guardian import SystemGuardian

if enabled("portfolio"):
    from execution.portfolio import Portfolio

if enabled("smart_router"):
    from execution.smart_router import SmartRouter

if enabled("trade_manager"):
    from execution.trade_manager import TradeManager

if enabled("ml"):
    from execution.ml.signal_model import MLSignalFilter


from execution.risk.manager import RiskManager
from execution.exchange.base import TokenBucket
from execution.exchange.binance_rest import BinanceSpot
from execution.exchange.bybit_rest import BybitSpot
from execution.exchange.binance_ws import BinanceWS
from execution.exchange.bybit_ws import BybitWS

from execution.strategy.orderbook_alpha import compute_long_signal


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

MAX_CANDLES = 2000


def _ms_to_dt(ms: int):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


# =========================================================
# ENGINE
# =========================================================

class Engine:

    def __init__(self, s: Settings):

        self.s = s

        # =============================
        # OPTIONAL MODULES
        # =============================

        self.db = None
        if enabled("database"):
            self.db = TradeDB(s.DB_PATH)

        self.guardian = None
        if enabled("guardian"):
            self.guardian = SystemGuardian()

        self.portfolio = None
        if enabled("portfolio"):
            self.portfolio = Portfolio()

        self.router = None
        if enabled("smart_router"):
            self.router = SmartRouter()

        self.trade_manager = None
        if enabled("trade_manager"):
            self.trade_manager = TradeManager(self.router)

        self.ml = None
        if enabled("ml"):
            self.ml = MLSignalFilter(
                enabled=s.ML_ENABLED,
                min_proba=s.ML_MIN_PROBA
            )

        # =============================
        # RISK
        # =============================

        self.risk = RiskManager(
            position_pct=s.POSITION_PCT,
            stop_atr_mult=s.STOP_ATR_MULT,
            tp_atr_mult=s.TP_ATR_MULT,
            taker_fee=s.TAKER_FEE,
            maker_fee=s.MAKER_FEE,
            slippage_bps=s.SLIPPAGE_BPS,
            partial_tp_pct=s.PARTIAL_TP_PCT,
        )

        self._df15: dict[str, pd.DataFrame] = {}

        limiter = TokenBucket(
            rate_per_sec=s.REST_RATE_PER_SEC,
            burst=s.REST_BURST
        )

        # =============================
        # EXCHANGE
        # =============================

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

        if not enabled("portfolio"):
            return

        pos = self.portfolio.get(symbol)

        if not pos:
            return

        df = self._df15[symbol]

        price = float(df["close"].iloc[-1])

        if pos.tp_price and price >= pos.tp_price:

            await self.trade_manager.close_position(
                self.ex,
                self.portfolio,
                symbol
            )

        if pos.stop_price and price <= pos.stop_price:

            await self.trade_manager.close_position(
                self.ex,
                self.portfolio,
                symbol
            )

    # =========================================================
    # BUY ENGINE
    # =========================================================

    async def maybe_open_position(self, symbol: str, idx: int):

        df15 = self._df15[symbol]

        if len(df15) < 50:
            return

        if enabled("portfolio") and self.portfolio.has_position(symbol):
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

        if enabled("ml") and self.s.ML_ENABLED:

            if not self.ml.allow(sig.features):
                return

        balance = await self.ex.get_balance("USDT")

        price = float(df15["close"].iloc[-1])

        size_usdt = self.risk.order_notional_usdt(balance)

        if size_usdt < 5:
            return

        if enabled("trade_manager"):

            await self.trade_manager.open_long(
                self.ex,
                self.portfolio,
                symbol,
                size_usdt,
                price
            )

    # =========================================================
    # LIVE LOOP
    # =========================================================

    async def run_live(self):

        if enabled("guardian"):
            asyncio.create_task(self.guardian.start())

        if enabled("database"):
            await self.db.init()

        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        stream = self.ws.stream_klines(
            list(self.s.SYMBOLS),
            self.s.PRIMARY_TF
        )

        async for msg in stream:

            if enabled("guardian"):
                self.guardian.notify_ws_message()

            if msg is None:
                continue

            sym = msg.symbol

            if not msg.is_closed:
                continue

            if sym not in self._df15:

                self._df15[sym] = pd.DataFrame(
                    columns=["open","high","low","close","volume"],
                    dtype=float
                )

            df = self._df15[sym]

            df.loc[_ms_to_dt(msg.start_ms)] = {
                "open": msg.open,
                "high": msg.high,
                "low": msg.low,
                "close": msg.close,
                "volume": msg.volume
            }

            if len(df) > MAX_CANDLES:
                self._df15[sym] = df.iloc[-MAX_CANDLES:]

            idx = len(df)

            await self.monitor_positions(sym)
            await self.maybe_open_position(sym, idx)


# =========================================================
# MAIN
# =========================================================

async def main():

    s = Settings()

    engine = Engine(s)

    if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
        return

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
