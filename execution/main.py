# execution/main.py

import os
import time
import logging
import traceback

from execution.engine import ExecutionEngine
from execution.signal_client import pop_next_signal


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
# BOOT BANNER
# --------------------------------------------------

def print_boot_banner():

    logger.info("===================================")
    logger.info("GENIUS BOT WORKER STARTING")
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

            signal = pop_next_signal(SIGNAL_OUTBOX_PATH)

            if signal:

                signal_id = signal.get("signal_id")
                verdict = signal.get("final_verdict")

                logger.info(
                    f"SIGNAL_RECEIVED | id={signal_id} verdict={verdict}"
                )

                engine.execute_signal(signal)

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
