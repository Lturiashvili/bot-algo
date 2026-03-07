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

        log.info(f"BUY_SIGNAL_CONFIRMED {symbol}")

        try:

            balance = await self.ex.get_balance("USDT")

            if balance <= 0:
                log.warning("NO_BALANCE")
                return

            price = float(df15["close"].iloc[-1])

            # ==============================
            # POSITION SIZE
            # ==============================

            size_usdt = self.risk.order_notional_usdt(balance)

            if size_usdt < 5:
                log.warning(f"POSITION_TOO_SMALL {size_usdt}")
                return

            log.info(
                f"POSITION_SIZE {symbol} "
                f"balance={balance} "
                f"size={size_usdt}"
            )

            # ==============================
            # EXECUTION
            # ==============================

            success = await self.trade_manager.open_long(
                self.ex,
                self.portfolio,
                symbol,
                size_usdt,
                price
            )

            if not success:

                log.warning(
                    f"BUY_EXECUTION_FAILED {symbol}"
                )

                return

            pos = self.portfolio.positions.get(symbol)

            if not pos:

                log.error(
                    f"PORTFOLIO_UPDATE_FAILED {symbol}"
                )

                return

            # ==============================
            # OCO RETRY
            # ==============================

            tp_pct = 0.02
            sl_pct = 0.01

            for attempt in range(3):

                ok = await self.trade_manager.place_safe_oco(
                    self.ex,
                    symbol,
                    pos.qty,
                    pos.entry_price,
                    tp_pct,
                    sl_pct
                )

                if ok:

                    log.info(
                        f"OCO_PLACED {symbol} attempt={attempt+1}"
                    )

                    break

                await asyncio.sleep(0.7)

            else:

                log.error(
                    f"OCO_FAILED_AFTER_RETRIES {symbol}"
                )

            log.info(
                f"EXECUTION_DONE {symbol} "
                f"qty={pos.qty} "
                f"entry={pos.entry_price}"
            )

        except Exception as e:

            log.exception(
                f"EXECUTION_ERROR {symbol} err={e}"
            )

    async def run_live(self):

        await self.db.init()

        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        async for msg in self.ws.stream_klines(
            list(self.s.SYMBOLS),
            self.s.PRIMARY_TF
        ):

            if not msg.is_closed:
                continue

            if msg.symbol not in self._df15:
                continue

            idx = len(self._df15[msg.symbol])

            await self.maybe_open_position(
                msg.symbol,
                idx
            )


async def main():

    s = Settings()

    engine = Engine(s)

    if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
        return

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
