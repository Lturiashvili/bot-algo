# execution/signal_generator.py

import os
import time
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import ccxt

from execution.signal_client import append_signal
from execution.excel_live_core import ExcelLiveCore, CoreInputs

logger = logging.getLogger("gbm")

# -------------------------------------------------
# ENV CONFIG
# -------------------------------------------------

TIMEFRAME = os.getenv("BOT_TIMEFRAME", "15m")
CANDLE_LIMIT = int(os.getenv("BOT_CANDLE_LIMIT", "80"))

BOT_QUOTE_PER_TRADE = float(os.getenv("BOT_QUOTE_PER_TRADE", "15"))

COOLDOWN_SECONDS = int(
    os.getenv("BOT_SIGNAL_COOLDOWN_SECONDS", "180")
)

ALLOW_LIVE_SIGNALS = (
    os.getenv("ALLOW_LIVE_SIGNALS", "false")
    .strip()
    .lower()
    == "true"
)

SYMBOLS = [
    s.strip()
    for s in os.getenv("BOT_SYMBOLS", "BTC/USDT").split(",")
    if s.strip()
]

EXCEL_MODEL_PATH = os.getenv(
    "EXCEL_MODEL_PATH",
    "/var/data/DYZEN_CAPITAL_OS_AI_LIVE_CORE_READY.xlsx"
)

OUTBOX_PATH = os.getenv(
    "SIGNAL_OUTBOX_PATH",
    "/var/data/signal_outbox.json"
)

_last_emit_ts = 0

# -------------------------------------------------
# EXCHANGE
# -------------------------------------------------

EXCHANGE = ccxt.binance({
    "enableRateLimit": True
})

_CORE: Optional[ExcelLiveCore] = None


# -------------------------------------------------
# UTIL
# -------------------------------------------------

def _now():
    return datetime.utcnow().isoformat() + "Z"


def _cooldown_ok():
    global _last_emit_ts
    return (time.time() - _last_emit_ts) >= COOLDOWN_SECONDS


def _emit(signal: Dict[str, Any]):

    global _last_emit_ts

    append_signal(signal, OUTBOX_PATH)

    _last_emit_ts = time.time()

    logger.info(
        f"SIGNAL_EMITTED | id={signal.get('signal_id')} "
        f"symbol={signal['execution']['symbol']}"
    )


def _core() -> ExcelLiveCore:

    global _CORE

    if _CORE is None:

        if not os.path.exists(EXCEL_MODEL_PATH):

            raise FileNotFoundError(
                f"Excel model not found: {EXCEL_MODEL_PATH}"
            )

        _CORE = ExcelLiveCore(EXCEL_MODEL_PATH)

        logger.info(
            f"EXCEL_CORE_LOADED | path={EXCEL_MODEL_PATH}"
        )

    return _CORE


def _sma(vals: List[float], n: int) -> float:

    if len(vals) < n:
        return sum(vals) / len(vals)

    return sum(vals[-n:]) / n


def _confidence(closes: List[float]) -> float:

    last = closes[-1]
    prev = closes[-2]

    ma20 = _sma(closes, 20)

    score = 0

    if last > ma20:
        score += 0.5

    if last > prev:
        score += 0.5

    return score


# -------------------------------------------------
# MAIN SIGNAL LOGIC
# -------------------------------------------------

def generate_signal() -> Optional[Dict[str, Any]]:

    if not _cooldown_ok():

        return None

    core = _core()

    for symbol in SYMBOLS:

        try:

            ohlcv = EXCHANGE.fetch_ohlcv(
                symbol,
                timeframe=TIMEFRAME,
                limit=CANDLE_LIMIT
            )

        except Exception as e:

            logger.warning(
                f"FETCH_FAIL | {symbol} | {e}"
            )

            continue

        if not ohlcv or len(ohlcv) < 30:

            continue

        closes = [c[4] for c in ohlcv]

        last = closes[-1]

        ma20 = _sma(closes, 20)

        trend_strength = (
            max(0, min(1, (last - ma20) / ma20 + 0.5))
        )

        conf = _confidence(closes)

        inputs = CoreInputs(
            trend_strength=trend_strength,
            structure_ok=(last > ma20),
            volume_score=0.5,
            risk_state="OK",
            confidence_score=conf,
            volatility_regime="NORMAL",
        )

        decision = core.decide(inputs)

        logger.info(
            f"CORE_DECISION | symbol={symbol} "
            f"ai={decision.get('ai_score')} "
            f"final={decision.get('final_trade_decision')}"
        )

        if decision.get("final_trade_decision") != "EXECUTE":

            continue

        if not ALLOW_LIVE_SIGNALS:

            logger.info(
                "BLOCKED_BY_ENV | ALLOW_LIVE_SIGNALS=false"
            )

            continue

        signal_id = str(uuid.uuid4())

        signal = {

            "signal_id": signal_id,

            "ts_utc": _now(),

            "certified_signal": True,

            "final_verdict": "TRADE",

            "meta": {

                "source": "DYZEN_EXCEL_LIVE_CORE",

                "symbol": symbol,

                "decision": decision,

            },

            "execution": {

                "symbol": symbol,

                "direction": "LONG",

                "entry": {

                    "type": "MARKET"

                },

                "quote_amount": BOT_QUOTE_PER_TRADE,

            }

        }

        _emit(signal)

        return signal

    return None


# -------------------------------------------------
# RENDER ENTRY
# -------------------------------------------------

def run_once():

    return generate_signal()


if __name__ == "__main__":

    while True:

        try:

            generate_signal()

        except Exception as e:

            logger.error(f"GENERATOR_ERROR | {e}")

        time.sleep(30)
