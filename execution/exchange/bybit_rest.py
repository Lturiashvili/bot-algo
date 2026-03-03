"""
Production-grade Bybit REST client (Spot V5)

Features:
- Async aiohttp session reuse
- Interval normalization (Binance → Bybit)
- Normalized OHLCV schema
- Proper V5 header-based authentication
- Safe order parsing
- Private API ping
- Backward compatibility alias (BybitSpot)
"""

import aiohttp
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, List, Any, Optional


logger = logging.getLogger(__name__)


# ==========================================================
# Interval Converter
# ==========================================================

def _normalize_interval(interval: str) -> str:
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
# Bybit REST Client (V5)
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
        self.name = "bybit"

        if not api_key or not api_secret:
            raise RuntimeError("Bybit API credentials missing")

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
    # Private Ping — Wallet Balance (V5 Auth Check)
    # ------------------------------------------------------

    async def private_ping(self) -> Dict[str, Any]:
        """
        Simple authenticated GET call to verify API permissions.
        Uses /v5/account/wallet-balance
        """

        endpoint = "/v5/account/wallet-balance"
        url = f"{self.BASE_URL}{endpoint}"

        timestamp = str(int(time.time() * 1000))
        query_string = "accountType=UNIFIED"

        # V5 GET signature format:
        # timestamp + api_key + recv_window + query_string
        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + query_string
        )

        signature = hmac.new(
            self.api_secret.encode(),
            sign_payload.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
        }

        session = await self._get_session()

        async with session.get(
            url,
            headers=headers,
            params={"accountType": "UNIFIED"},
        ) as resp:
            data = await resp.json()

        if data.get("retCode") != 0:
            logger.error(f"PRIVATE_PING_ERROR {data}")
            raise Exception(f"Bybit private ping error: {data}")

        logger.info("PRIVATE_PING_OK")

        return data

    # ------------------------------------------------------
    # Fetch OHLCV (Public)
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

    # ------------------------------------------------------
    # Market Buy (Quote Amount) — V5 Correct Auth
    # ------------------------------------------------------

    async def market_buy_quote(
        self,
        symbol: str,
        quote_amount: float,
    ) -> Dict[str, Any]:

        url = f"{self.BASE_URL}/v5/order/create"
        timestamp = str(int(time.time() * 1000))

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "quoteOrderQty": str(quote_amount),
        }

        body_str = json.dumps(body, separators=(",", ":"))

        # V5 signature format:
        # timestamp + api_key + recv_window + body_json
        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + body_str
        )

        signature = hmac.new(
            self.api_secret.encode(),
            sign_payload.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        session = await self._get_session()

        async with session.post(
            url,
            headers=headers,
            data=body_str,
        ) as resp:
            data = await resp.json()

        if data.get("retCode") != 0:
            logger.error(f"MARKET_BUY_ERROR {data}")
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


# ==========================================================
# Backward Compatibility Alias
# ==========================================================

BybitSpot = BybitREST
