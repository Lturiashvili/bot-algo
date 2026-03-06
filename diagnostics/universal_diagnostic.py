
# universal_diagnostic.py
# Universal Python Bot Diagnostic Engine
# Works in most Python trading bot projects (Render / Docker / VPS)

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

logger = logging.getLogger("UNIVERSAL_DIAG")

logger.info("=" * 80)
logger.info("JAIANI UNIVERSAL DIAGNOSTIC ENGINE")
logger.info("🚀 UNIVERSAL BOT DIAGNOSTIC STARTED")
logger.info(f"Time: {datetime.now()}")
logger.info(f"Python: {sys.version}")
logger.info(f"Working dir: {os.getcwd()}")

try:
    logger.info(f"Directory: {os.listdir('.')}")
except Exception:
    pass

logger.info("═" * 80)

logger.info("PYTHON PATH CHECK")
for p in sys.path:
    logger.info(f"PATH → {p}")

logger.info("═" * 80)
logger.info("ENVIRONMENT VARIABLES CHECK")

COMMON_ENV = [
    "EXCHANGE",
    "API_KEY",
    "API_SECRET",
    "SYMBOLS",
    "LOG_LEVEL",
    "PRIMARY_TF",
    "SECONDARY_TF",
    "CONFIRM_TF"
]

for var in COMMON_ENV:
    val = os.getenv(var)
    if val:
        if "KEY" in var or "SECRET" in var:
            logger.info(f"ENV {var} → {val[:6]}***")
        else:
            logger.info(f"ENV {var} → {val}")
    else:
        logger.warning(f"ENV {var} → NOT SET")

logger.info("═" * 80)
logger.info("PACKAGE CHECK")

try:
    import pkg_resources
    packages = sorted([p.project_name for p in pkg_resources.working_set])
    for pkg in packages[:50]:
        logger.info(pkg)
    if len(packages) > 50:
        logger.info(f"... and {len(packages)-50} more")
except Exception as e:
    logger.warning(f"Package scan failed: {e}")

logger.info("═" * 80)
logger.info("MEMORY CHECK")

try:
    import psutil
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / 1024 / 1024
    logger.info(f"Memory usage: {mem:.2f} MB")
except Exception as e:
    logger.warning(f"Memory check unavailable: {e}")

logger.info("═" * 80)
logger.info("MODULE IMPORT DISCOVERY")

COMMON_IMPORTS = [

    "execution.config",
    "execution.database",
    "execution.portfolio",
    "execution.risk",
    "execution.risk.manager",
    "execution.smart_router",
    "execution.strategy",
    "execution.strategy.orderbook_alpha",
    "execution.execution_brain",
    "execution.trade_manager",
    "execution.position_manager",
    "execution.exchange",
    "execution.exchange.binance_rest",
    "execution.exchange.bybit_rest",
    "execution.exchange.binance_ws",
    "execution.exchange.bybit_ws",

    "ui.env_override"
]

for module in COMMON_IMPORTS:

    try:

        importlib.import_module(module)

        logger.info(f"✅ IMPORT OK → {module}")

    except Exception as e:

        logger.error("BUG DETECTED")
        logger.error(f"MODULE → {module}")

        tb = traceback.extract_tb(e.__traceback__)

        if tb:

            last = tb[-1]

            logger.error(f"FILE  → {last.filename}")
            logger.error(f"LINE  → {last.lineno}")
            logger.error(f"CODE  → {last.line}")

        logger.error(f"ERROR → {type(e).__name__}: {e}")

        logger.debug(traceback.format_exc())

logger.info("═" * 80)
logger.info("SETTINGS TEST")

try:
    config = importlib.import_module("execution.config")
    if hasattr(config, "Settings"):
        Settings = getattr(config, "Settings")
        s = Settings()
        logger.info("Settings instance created")
        for attr in ["EXCHANGE", "SYMBOLS", "LOG_LEVEL"]:
            if hasattr(s, attr):
                logger.info(f"{attr} → {getattr(s, attr)}")
    else:
        logger.warning("Settings class not found")
except Exception as e:
    logger.error(f"Settings load FAILED → {e}")
    logger.debug(traceback.format_exc())

logger.info("═" * 80)
logger.info("CORE CLASS TEST")

CLASS_TESTS = [
    ("execution.portfolio", "Portfolio"),
    ("execution.risk.manager", "RiskManager"),
    ("execution.database", "TradeDB")
]
for module_name, class_name in CLASS_TESTS:
    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, class_name):
            cls = getattr(mod, class_name)
            obj = cls()
            logger.info(f"✅ {class_name} instance OK")
        else:
            logger.warning(f"{class_name} not found in {module_name}")
    except Exception as e:
        logger.warning(f"{class_name} failed → {e}")

logger.info("═" * 80)
logger.info("ASYNCIO LOOP TEST")

async def async_test():
    logger.info("Async test start")
    await asyncio.sleep(1)
    logger.info("Async loop OK")

try:
    asyncio.run(async_test())
except Exception as e:
    logger.error(f"Async test FAILED → {e}")

logger.info("═" * 80)
logger.info("DIAGNOSTIC RUNTIME LOOP STARTED")

for i in range(60):
    logger.info(f"Tick {i+1:02d}/60 | Process alive | {time.strftime('%H:%M:%S')}")
    time.sleep(10)

logger.info("═" * 80)
logger.info("DIAGNOSTIC FINISHED")
logger.info("If this message appears → system stable")
