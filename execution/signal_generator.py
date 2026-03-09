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
logger.setLevel(logging.INFO)


# -------------------------------------------------
# ENV CONFIG
# -------------------------------------------------

TIMEFRAME = os.getenv("BOT_TIMEFRAME", "15m")
CANDLE_LIMIT = int(os.getenv("BOT_CANDLE_LIMIT", "80"))

BOT_QUOTE_PER_TRADE = float(
    os.getenv("BOT_QUOTE_PER_TRADE", "15")
)

COOLDOWN_SECONDS = int(
    os.getenv("BOT_SIGNAL_COOLDOWN_SECONDS", "180")
)

ALLOW_LIVE_SIGNALS = (
    os.getenv("ALLOW_LIVE_SIGNALS", "true").lower() == "true"
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
_CORE: Optional[ExcelLiveCore] = None


# -------------------------------------------------
# EXCHANGE
# -------------------------------------------------

EXCHANGE = ccxt.bybit({
    "enableRateLimit": True
})


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

    try:

        append_signal(signal, OUTBOX_PATH)

        _last_emit_ts = time.time()

        logger.info(
            f"SIGNAL_EMITTED | {signal['execution']['symbol']} | {signal['signal_id']}"
        )

    except Exception as e:

        logger.error(f"SIGNAL_WRITE_FAILED | {e}")


def _core() -> Optional[ExcelLiveCore]:

    global _CORE

    if _CORE:
        return _CORE

    if not os.path.exists(EXCEL_MODEL_PATH):

        logger.warning(
            f"EXCEL_MODEL_NOT_FOUND | fallback mode | {EXCEL_MODEL_PATH}"
        )

        return None

    try:

        _CORE = ExcelLiveCore(EXCEL_MODEL_PATH)

        logger.info(f"EXCEL_CORE_LOADED | {EXCEL_MODEL_PATH}")

        return _CORE

    except Exception as e:

        logger.error(f"EXCEL_CORE_LOAD_FAIL | {e}")

        return None


def _sma(vals: List[float], n: int):

    if len(vals) < n:
        return sum(vals) / len(vals)

    return sum(vals[-n:]) / n


# -------------------------------------------------
# VOLATILITY REGIME
# -------------------------------------------------

def _volatility_regime(closes):

    last = closes[-1]
    prev = closes[-10]

    change = abs(last - prev) / prev

    if change < 0.01:
        return "LOW"

    if change < 0.03:
        return "MEDIUM"

    return "HIGH"


# -------------------------------------------------
# CONFIDENCE MODEL
# -------------------------------------------------

def _confidence(closes):

    last = closes[-1]
    prev = closes[-2]

    ma20 = _sma(closes, 20)
    ma50 = _sma(closes, 50)

    score = 0.0

    if last > ma20:
        score += 0.4

    if last > ma50:
        score += 0.3

    if last > prev:
        score += 0.3

    return max(0, min(1, score))


# -------------------------------------------------
# SIGNAL ENGINE
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

            logger.warning(f"FETCH_FAIL | {symbol} | {e}")
            continue

        if not ohlcv or len(ohlcv) < 30:
            continue

        closes = [c[4] for c in ohlcv]

        last = closes[-1]

        ma20 = _sma(closes, 20)

        trend_strength = max(
            0,
            min(1, (last - ma20) / ma20 + 0.5)
        )

        confidence = _confidence(closes)

        regime = _volatility_regime(closes)

        volume_score = 0.6

        ai_execute = True

        if core:

            try:

                inputs = CoreInputs(
                    trend_strength=trend_strength,
                    structure_ok=(last > ma20),
                    volume_score=volume_score,
                    risk_state="OK",
                    confidence_score=confidence,
                    volatility_regime=regime,
                )

                decision = core.decide(inputs)

                logger.info(
                    f"AI_DECISION | {symbol} | score={decision.get('ai_score')} | final={decision.get('final_trade_decision')}"
                )

                ai_execute = (
                    decision.get("final_trade_decision") == "EXECUTE"
                )

            except Exception as e:

                logger.error(f"EXCEL_CORE_ERROR | {e}")
                continue

        if not ai_execute:
            continue

        signal_id = str(uuid.uuid4())

        signal = {

            "schema_version": "1.0",
            "signal_id": signal_id,
            "strategy_id": "DYZEN_AI_V1",
            "ts_utc": _now(),
            "certified_signal": True,
            "final_verdict": "TRADE",

            "meta": {
                "source": "DYZEN_EXCEL_LIVE_CORE",
                "symbol": symbol
            },

            "execution": {

                "symbol": symbol,
                "direction": "LONG",

                "entry": {
                    "type": "MARKET"
                },

                "quote_amount": BOT_QUOTE_PER_TRADE
            }
        }

        if ALLOW_LIVE_SIGNALS:

            _emit(signal)

        else:

            logger.info("SIGNAL_READY_BUT_ENV_BLOCKED")

        return signal

    return None


# -------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------

def run_once():

    return generate_signal()


if __name__ == "__main__":

    logger.info("SIGNAL_GENERATOR_STARTED")

    while True:

        try:

            generate_signal()

        except Exception as e:

            logger.error(f"GENERATOR_CRASH | {e}")

        time.sleep(30)
