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

        # Execution Brain
        self.execution_brain = ExecutionBrain(s, self.portfolio)

        # Position Manager (EXIT ENGINE)
        self.position_manager = PositionManager(
            tp_pct=0.02,
            sl_pct=0.01,
            max_bars=30,
        )

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

        decision = self.execution_brain.evaluate_trade(
            symbol=symbol,
            signal="BUY",
            signal_score=getattr(sig, "confidence", 50),
            regime="NEUTRAL"
        )

        if not decision:
            log.info(f"EXECUTION_BLOCKED_BY_BRAIN {symbol}")
            return

        try:

            test_quote_usdt = 5.0

            log.info(f"EXECUTION_START {symbol} size={test_quote_usdt}USDT")

            order = await self.router.open_long(
                self.ex,
                symbol,
                test_quote_usdt
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

            df = self._df15[msg.symbol]

            new_row = {
                "open": msg.kline.open,
                "high": msg.kline.high,
                "low": msg.kline.low,
                "close": msg.kline.close,
                "volume": msg.kline.volume,
            }

            df.loc[_ms_to_dt(msg.ts)] = new_row

            if len(df) > 1000:
                df = df.iloc[-1000:]

            self._df15[msg.symbol] = df

            self._idx[msg.symbol] += 1

            override = self.override.read_override()

            if override.enabled and override.kill_switch:
                log.warning("GLOBAL KILL SWITCH ACTIVE — trading halted")
                continue

            # ENTRY ENGINE
            await self.maybe_open_position(msg.symbol, self._idx[msg.symbol])

            # EXIT ENGINE
            price = msg.close

            await self.position_manager.maybe_close_position(
                self.router,
                self.ex,
                self.portfolio,
                msg.symbol,
                price,
                self._idx[msg.symbol],
            )


async def main() -> None:

    s = Settings()
    engine = Engine(s)

    try:

        if (os.getenv("RUN_BACKTEST") or "").strip() == "1":
            return

        await engine.run_live()

    finally:

        # graceful shutdown
        try:
            if engine.ws and hasattr(engine.ws, "close"):
                await engine.ws.close()
        except Exception:
            pass

        try:
            if engine.ex and hasattr(engine.ex, "close"):
                await engine.ex.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
