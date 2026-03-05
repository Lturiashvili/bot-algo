import os
import time
import logging

from core.excel_reader import ExcelReader
from core.decision_engine import build_trade_decision
from core.execution_engine import execute_order_safe
from core.safety_guard import is_system_healthy, is_risk_unlocked
from adapters.virtual_wallet import VirtualWallet

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("GENIUS")


def _to_bool(v: str) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


EXCEL_PATH = os.getenv("EXCEL_PATH", "DYZEN_CAPITAL_OS_AI_LIVE_CORE_READY_HARDENED.xlsx")

# ✅ ENV-driven
AUTO_TRADING = _to_bool(os.getenv("AUTO_TRADING", "false"))
BOT_SYMBOLS = [s.strip() for s in os.getenv("BOT_SYMBOLS", "BTC/USDT").split(",") if s.strip()]
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "10"))

# for paper mode (VirtualWallet), just a fixed amount
ORDER_AMOUNT = float(os.getenv("ORDER_AMOUNT", "0.001"))


def main_loop():
    reader = ExcelReader(EXCEL_PATH)
    exchange = VirtualWallet()

    log.info(
        f"BOOT | EXCEL_PATH={EXCEL_PATH} AUTO_TRADING={AUTO_TRADING} "
        f"BOT_SYMBOLS={BOT_SYMBOLS} LOOP_SECONDS={LOOP_SECONDS} ORDER_AMOUNT={ORDER_AMOUNT}"
    )

    while True:
        # 1) Read decision (required)
        master = reader.read_decision()

        # 2) Safety sheets (optional fallbacks)
        hb = reader.read_heartbeat()
        risk = reader.read_risk_lock()

        healthy = is_system_healthy(hb)
        unlocked = is_risk_unlocked(risk)

        decision = build_trade_decision(master)
        action = decision["action"]

        if not healthy or not unlocked:
            action = "HOLD"

        log.info(
            f"DECISION | action={action} macro={decision.get('MACRO_GATE')} "
            f"ai_score={decision.get('AI_SCORE')} healthy={healthy} unlocked={unlocked}"
        )

        if action in ("BUY", "SELL") and AUTO_TRADING:
            for sym in BOT_SYMBOLS:
                ok, res = execute_order_safe(exchange, sym, action, ORDER_AMOUNT)
                log.info(f"EXEC_RESULT | symbol={sym} action={action} ok={ok} res={res}")
        else:
            log.info("HOLD | no trade executed")

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main_loop()
