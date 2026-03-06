from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    EXCHANGE: str = os.getenv("EXCHANGE", "binance").lower()
    SYMBOLS: list[str] = [s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
    PRIMARY_TF: str = os.getenv("PRIMARY_TF", "15m")
    POSITION_PCT: float = float(os.getenv("POSITION_PCT", "0.20"))
    STOP_ATR_MULT: float = float(os.getenv("STOP_ATR_MULT", "1.5"))
    TP_ATR_MULT: float = float(os.getenv("TP_ATR_MULT", "3.0"))
    PARTIAL_TP_PCT: float = float(os.getenv("PARTIAL_TP_PCT", "0.50"))
    SYMBOL_COOLDOWN_SECONDS: int = int(os.getenv("SYMBOL_COOLDOWN_SECONDS", "1800"))
    MAX_TRADES_WINDOW_SECONDS: int = int(os.getenv("MAX_TRADES_WINDOW_SECONDS", "3600"))
    MAX_TRADES_PER_WINDOW: int = int(os.getenv("MAX_TRADES_PER_WINDOW", "5"))
    MAX_EXPOSURE_POSITIONS: int = int(os.getenv("MAX_EXPOSURE_POSITIONS", "4"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DB_PATH: str = os.getenv("DB_PATH", "trades.db")

    # API გასაღებები (არ დაწეროთ კოდში!)
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
    BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
