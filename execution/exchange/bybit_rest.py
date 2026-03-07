"""
Production-grade Bybit REST client (Spot V5)
FULLY FIXED VERSION
"""

import aiohttp
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ==========================================================
# INTERVAL NORMALIZER (FIX)
# ==========================================================

def normalize_interval(interval: str) -> str:

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


class BybitREST:

    BASE_URL = "https://api.bybit.com"

    MAX_RETRIES = 3
    RETRY_DELAY = 0.7

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        recv_window: int = 5000,
        timeout: int = 15,
    ):

        self.name = "bybit"
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.timeout = timeout

        self._session: Optional[aiohttp.ClientSession] = None

    # ==========================================================
    # SESSION
    # ==========================================================

    async def _get_session(self) -> aiohttp.ClientSession:

        if self._session is None or self._session.closed:

            timeout = aiohttp.ClientTimeout(total=self.timeout)

            self._session = aiohttp.ClientSession(timeout=timeout)

        return self._session

    # ==========================================================
    # RETRY ENGINE
    # ==========================================================

    async def _request(self, method: str, url: str, **kwargs):

        for attempt in range(1, self.MAX_RETRIES + 1):

            try:

                session = await self._get_session()

                async with session.request(method, url, **kwargs) as resp:

                    data = await resp.json()

                    return data

            except Exception as e:

                logger.warning(
                    f"BYBIT_RETRY attempt={attempt} err={e}"
                )

                await asyncio.sleep(self.RETRY_DELAY)

        raise RuntimeError(f"Bybit request failed: {url}")

    # ==========================================================
    # SIGN
    # ==========================================================

    def _sign(self, payload: str) -> str:

        return hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

    # ==========================================================
    # FETCH OHLCV (FIXED)
    # ==========================================================

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:

        interval = normalize_interval(interval)

        url = f"{self.BASE_URL}/v5/market/kline"

        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        data = await self._request(
            "GET",
            url,
            params=params
        )

        if not data:
            raise RuntimeError("Empty response from Bybit")

        if data.get("retCode") != 0:
            raise RuntimeError(f"Kline error: {data}")

        result = data.get("result")

        if not result:
            return []

        raw = result.get("list", [])

        candles = []

        for c in raw:

            candles.append({
                "ts": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            })

        candles.sort(key=lambda x: x["ts"])

        return candles

    # ==========================================================
    # BALANCE
    # ==========================================================

    async def get_balance(self, asset: str = "USDT") -> float:

        url = f"{self.BASE_URL}/v5/account/wallet-balance"

        timestamp = str(int(time.time() * 1000))

        query = "accountType=UNIFIED"

        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + query
        )

        signature = self._sign(sign_payload)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
        }

        data = await self._request(
            "GET",
            url,
            headers=headers,
            params={"accountType": "UNIFIED"}
        )

        coins = data["result"]["list"][0]["coin"]

        for c in coins:

            if c["coin"] == asset:
                return float(c["walletBalance"])

        return 0.0


BybitSpot = BybitREST
