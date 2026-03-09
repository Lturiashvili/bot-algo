import os
import time
import logging
import traceback

from execution.engine import ExecutionEngine
from execution.signal_client import pop_next_signal
from execution.signal_generator import generate_signal


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

MODE = os.getenv("MODE", "DEMO").upper()

SIGNAL_OUTBOX_PATH = os.getenv(
    "SIGNAL_OUTBOX_PATH",
    "/var/data/signal_outbox.json"
)

LOOP_SLEEP_SECONDS = float(
    os.getenv("LOOP_SLEEP_SECONDS", "10")
)

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO"
).upper()


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("gbm")


# --------------------------------------------------
# BOOT INFO
# --------------------------------------------------

def print_boot_banner():

    logger.info("===================================")
    logger.info("GENIUS BOT STARTING")
    logger.info(f"MODE = {MODE}")
    logger.info(f"OUTBOX = {SIGNAL_OUTBOX_PATH}")
    logger.info(f"SLEEP = {LOOP_SLEEP_SECONDS}s")
    logger.info("===================================")


# --------------------------------------------------
# WORKER LOOP
# --------------------------------------------------

def worker_loop():

    engine = ExecutionEngine()

    logger.info("ExecutionEngine initialized")

    while True:

        try:

            # -----------------------------------------
            # STEP 1 — GENERATE SIGNAL
            # -----------------------------------------

            try:
                generate_signal()
            except Exception as e:
                logger.warning(f"SIGNAL_GENERATOR_ERROR | {e}")

            # -----------------------------------------
            # STEP 2 — READ SIGNAL FROM OUTBOX
            # -----------------------------------------

            signal = pop_next_signal(SIGNAL_OUTBOX_PATH)

            if signal:

                signal_id = signal.get("signal_id")
                verdict = signal.get("final_verdict")
                symbol = signal.get("execution", {}).get("symbol")

                logger.info(
                    f"SIGNAL_RECEIVED | {symbol} | id={signal_id} verdict={verdict}"
                )

                # -------------------------------------
                # STEP 3 — EXECUTE TRADE
                # -------------------------------------

                try:
                    engine.execute_signal(signal)

                    logger.info(
                        f"EXECUTION_COMPLETE | id={signal_id}"
                    )

                except Exception as exec_err:

                    logger.error(
                        f"EXECUTION_FAILED | id={signal_id} | {exec_err}"
                    )

            else:

                logger.info("Worker alive | waiting for signals")

        except Exception as e:

            logger.error("WORKER_EXCEPTION")
            logger.error(str(e))
            traceback.print_exc()

        time.sleep(LOOP_SLEEP_SECONDS)


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

def main():

    print_boot_banner()

    try:

        worker_loop()

    except KeyboardInterrupt:

        logger.warning("Worker stopped manually")

    except Exception as e:

        logger.error("FATAL_ERROR")
        logger.error(str(e))
        traceback.print_exc()


# --------------------------------------------------

if __name__ == "__main__":
    main()
