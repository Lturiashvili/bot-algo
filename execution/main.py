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
from execution.portfolio import Portfolio
from execution.risk.manager import RiskManager
from execution.smart_router import SmartRouter
from execution.strategy.orderbook_alpha import compute_long_signal
from ui.env_override import EnvOverrideBridge


logging.basicConfig(level=Settings().LOG_LEVEL)
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

        self.filter_diagnostic = os.getenv("FILTER_DIAGNOSTIC", "0") == "1"

        boot_cfg = self.override.read_override()
        log.info(f"BOOT_OVERRIDE_STATE {boot_cfg}")

        self._idx: dict[str, int] = {sym: 0 for sym in s.SYMBOLS}
        self._df15: dict[str, pd.DataFrame] = {}

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

        self._df15[symbol] = df

    async def maybe_open_position(self, symbol: str, idx: int) -> None:

        if self.portfolio.has_position(symbol):
            return

        if self.portfolio.in_cooldown(symbol, idx):
            return

        df15 = self._df15[symbol]

        min_bars = max(self.s.EMA_SLOW + 5, 50)
        if len(df15) < min_bars:
            return

        df30 = df15
        df1h = df15

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

        if sig is None:
            return

        # =====================================================
        # INSTITUTIONAL FILTER AUDIT MATRIX
        # =====================================================
        if self.filter_diagnostic:

            last_row = df15.iloc[-1]
            close_price = float(last_row["close"])

            ema_fast_15 = float(
                df15["close"].ewm(span=self.s.EMA_FAST).mean().iloc[-1]
            )
            ema_slow_15 = float(
                df15["close"].ewm(span=self.s.EMA_SLOW).mean().iloc[-1]
            )

            delta = df15["close"].diff()
            gain = delta.clip(lower=0).rolling(self.s.RSI_PERIOD).mean()
            loss = (-delta.clip(upper=0)).rolling(self.s.RSI_PERIOD).mean()
            rs = gain / loss
            rsi_15 = float((100 - (100 / (1 + rs))).iloc[-1])

            high = df15["high"]
            low = df15["low"]
            close = df15["close"]

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)

            atr_15 = float(tr.rolling(self.s.ATR_PERIOD).mean().iloc[-1])
            ts = df15.index[-1].isoformat()

            log.info(
                f"FILTER_AUDIT {symbol} "
                f"ts={ts} "
                f"action={getattr(sig, 'action', None)} "
                f"close={close_price:.2f} "
                f"ema_fast_15={ema_fast_15:.2f} "
                f"ema_slow_15={ema_slow_15:.2f} "
                f"rsi_15={rsi_15:.2f} "
                f"atr_15={atr_15:.2f} "
                f"ema_ok={getattr(sig, 'ema_ok', None)} "
                f"rsi_ok={getattr(sig, 'rsi_ok', None)} "
                f"atr_ok={getattr(sig, 'atr_ok', None)} "
                f"confidence={getattr(sig, 'confidence', None)}"
            )

        if sig.action != "BUY":
            return

        if self.s.ML_ENABLED and not self.ml.allow(sig.features):
            return

        override = self.override.read_override()

        if override.enabled:
            if override.disable_new_entries:
                log.info("ENV: new entries disabled")
                return

            if override.min_confidence_override:
                if hasattr(sig, "confidence"):
                    if sig.confidence < override.min_confidence_override:
                        log.info("ENV: confidence override reject")
                        return

        log.info(f"BUY_SIGNAL_CONFIRMED {symbol}")

        try:
            balance = await self.ex.get_balance("USDT")

            position_pct = 0.20

            size_usdt = round(balance * position_pct, 2)
            
            if size_usdt < 5.0:
               size_usdt = 5.0
            log.info(f"POSITION_SIZE {symbol} balance={balance} size={size_usdt}")

            order = await self.router.open_long(
                self.ex,
                symbol,
                size_usdt
            )

            log.info(
                f"EXECUTION_DONE {symbol} "
                f"order_id={getattr(order, 'order_id', None)} "
                f"qty={getattr(order, 'executed_qty', None)} "
                f"avg_price={getattr(order, 'avg_price', None)} "
                f"status={getattr(order, 'status', None)}"
            )

        except Exception as e:
            log.exception(f"EXECUTION_FAILED {symbol} err={e}")

    async def run_live(self) -> None:

        await self.db.init()

        for sym in self.s.SYMBOLS:
            await self.seed_history(sym)

        async for msg in self.ws.stream_klines(
            list(self.s.SYMBOLS), self.s.PRIMARY_TF
        ):

            if not msg.is_closed:
                continue

            if msg.symbol not in self._df15:
                continue

            override = self.override.read_override()

            if override.enabled and override.kill_switch:
                log.warning("GLOBAL KILL SWITCH ACTIVE — trading halted")
                continue

            await self.maybe_open_position(msg.symbol, 0)


async def main() -> None:

    s = Settings()
    engine = Engine(s)

    if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
        return

    await engine.run_live()


if __name__ == "__main__":
    asyncio.run(main())
