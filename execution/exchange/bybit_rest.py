"""
Production-grade Bybit REST client (Spot V5)

Features:
- Async aiohttp session reuse
- Interval normalization (Binance → Bybit)
- Normalized OHLCV schema
- Safe order parsing
- Proper exception handling
- Backward compatibility alias (BybitSpot)
"""

import aiohttp
import asyncio
import hashlib
import hmac
import logging
import time
from typing import Dict, List, Any, Optional


logger = logging.getLogger(__name__)


# ==========================================================
# Interval Converter (Binance-style -> Bybit-style)
# ==========================================================

def _normalize_interval(interval: str) -> str:
    """
    Converts common Binance-style intervals to Bybit V5 format.
    """
    mapping = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "D",
        "1w": "W",
        "1M": "M",
    }
    return mapping.get(interval, interval)


# ==========================================================
# Bybit REST Client
# ==========================================================

class BybitREST:
    BASE_URL = "https://api.bybit.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        recv_window: int = 5000,
        timeout: int = 15,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------
    # Session Handling
    # ------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------
    # Signing
    # ------------------------------------------------------

    def _sign(self, params: Dict[str, Any]) -> str:
        ordered = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hmac.new(
            self.api_secret.encode(),
            ordered.encode(),
            hashlib.sha256
        ).hexdigest()

    # ------------------------------------------------------
    # Fetch OHLCV (Normalized)
    # ------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:

        interval = _normalize_interval(interval)

        url = f"{self.BASE_URL}/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        session = await self._get_session()

        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

                if data.get("retCode") != 0:
                    raise Exception(f"Bybit error: {data}")

                raw = data["result"]["list"]

                normalized: List[Dict[str, Any]] = []

                for c in raw:
                    normalized.append({
                        "ts": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    })

                normalized.sort(key=lambda x: x["ts"])

                logger.info(
                    f"FETCH_OHLCV_OK {symbol} interval={interval} candles={len(normalized)}"
                )

                return normalized

        except Exception as e:
            logger.exception(f"FETCH_OHLCV_FAILED {symbol}: {e}")
            raise

    # ------------------------------------------------------
    # Market Buy (Quote Amount)
    # ------------------------------------------------------

    async def market_buy_quote(
        self,
        symbol: str,
        quote_amount: float,
    ) -> Dict[str, Any]:

        url = f"{self.BASE_URL}/v5/order/create"
        timestamp = int(time.time() * 1000)

        params = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "quoteOrderQty": str(quote_amount),
            "apiKey": self.api_key,
            "timestamp": str(timestamp),
            "recvWindow": str(self.recv_window),
        }

        params["sign"] = self._sign(params)

        session = await self._get_session()

        try:
            async with session.post(url, json=params) as resp:
                data = await resp.json()

                if data.get("retCode") != 0:
                    raise Exception(f"Bybit order error: {data}")

                result = data.get("result", {})

                parsed = {
                    "order_id": result.get("orderId"),
                    "symbol": result.get("symbol"),
                    "side": result.get("side"),
                    "status": result.get("orderStatus"),
                    "qty": result.get("qty"),
                    "avg_price": result.get("avgPrice"),
                    "raw": result,
                }

                logger.info(
                    f"MARKET_BUY_OK {symbol} order_id={parsed['order_id']}"
                )

                return parsed

        except Exception as e:
            logger.exception(f"MARKET_BUY_FAILED {symbol}: {e}")
            raise


# ==========================================================
# Async Constructor Helper
# ==========================================================

async def create_bybit_client(
    api_key: str,
    api_secret: str
) -> BybitREST:
    return BybitREST(api_key, api_secret)


# ==========================================================
# Backward Compatibility Alias
# ==========================================================

BybitSpot = BybitREST
