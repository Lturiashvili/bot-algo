# execution/exchange/bybit_rest.py

import aiohttp
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


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

    async def _get_session(self) -> aiohttp.ClientSession:

        if self._session is None or self._session.closed:

            timeout = aiohttp.ClientTimeout(total=self.timeout)

            self._session = aiohttp.ClientSession(timeout=timeout)

        return self._session

    async def _request(self, method: str, url: str, **kwargs):

        for attempt in range(1, self.MAX_RETRIES + 1):

            try:

                session = await self._get_session()

                async with session.request(method, url, **kwargs) as resp:

                    data = await resp.json()

                    return data

            except Exception as e:

                logger.warning(f"BYBIT_RETRY attempt={attempt} err={e}")

                await asyncio.sleep(self.RETRY_DELAY)

        raise RuntimeError(f"Bybit request failed: {url}")

    def _sign(self, payload: str) -> str:

        return hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

    # ==========================================================
    # OHLCV
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

        if data.get("retCode") != 0:
            raise RuntimeError(f"Kline error: {data}")

        raw = data["result"]["list"]

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

        data = await self._request(
            "GET",
            url,
            params={"accountType": "UNIFIED"}
        )

        coins = data["result"]["list"][0]["coin"]

        for c in coins:

            if c["coin"] == asset:
                return float(c["walletBalance"])

        return 0.0

    # ==========================================================
    # MARKET BUY
    # ==========================================================

    async def market_buy_quote(
        self,
        symbol: str,
        quote_amount: float,
    ) -> Dict[str, Any]:

        url = f"{self.BASE_URL}/v5/order/create"

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "qty": str(quote_amount),
            "marketUnit": "quoteCoin",
        }

        data = await self._request(
            "POST",
            url,
            json=body
        )

        result = data["result"]

        return {
            "qty": float(result.get("qty", 0)),
            "avg_price": float(result.get("avgPrice", 0)),
            "status": result.get("orderStatus")
        }

    # ==========================================================
    # MARKET SELL
    # ==========================================================

    async def market_sell_base(
        self,
        symbol: str,
        qty: float
    ):

        url = f"{self.BASE_URL}/v5/order/create"

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Market",
            "qty": str(qty),
        }

        return await self._request(
            "POST",
            url,
            json=body
        )

    # ==========================================================
    # LIMIT SELL
    # ==========================================================

    async def limit_sell_base(
        self,
        symbol: str,
        qty: float,
        price: float
    ):

        url = f"{self.BASE_URL}/v5/order/create"

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(price),
            "timeInForce": "GTC",
        }

        return await self._request(
            "POST",
            url,
            json=body
        )

    # ==========================================================
    # CANCEL ALL
    # ==========================================================

    async def cancel_all(self, symbol: str):

        url = f"{self.BASE_URL}/v5/order/cancel-all"

        body = {
            "category": "spot",
            "symbol": symbol
        }

        return await self._request(
            "POST",
            url,
            json=body
        )


BybitSpot = BybitREST
