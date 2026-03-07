"""
Production-grade Bybit REST client (Spot V5)
Hardened with retry / timeout / validation
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

        if not api_key or not api_secret:
            raise RuntimeError("Bybit API credentials missing")

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
                    "BYBIT_REST_RETRY",
                    extra={
                        "attempt": attempt,
                        "url": url,
                        "err": str(e)
                    }
                )

                await asyncio.sleep(self.RETRY_DELAY)

        raise RuntimeError(f"Bybit request failed after retries: {url}")

    # ==========================================================
    # SIGNATURE
    # ==========================================================

    def _sign(self, payload: str) -> str:

        return hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

    # ==========================================================
    # BALANCE
    # ==========================================================

    async def get_balance(self, asset: str = "USDT") -> float:

        endpoint = "/v5/account/wallet-balance"
        url = f"{self.BASE_URL}{endpoint}"

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

        if data.get("retCode") != 0:

            raise RuntimeError(f"Balance error: {data}")

        coins = data["result"]["list"][0]["coin"]

        for c in coins:

            if c["coin"] == asset:
                return float(c["walletBalance"])

        return 0.0

    # ==========================================================
    # FETCH OHLCV
    # ==========================================================

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:

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
    # MARKET BUY
    # ==========================================================

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
            "qty": str(quote_amount),
            "marketUnit": "quoteCoin",
        }

        body_str = json.dumps(body, separators=(",", ":"))

        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + body_str
        )

        signature = self._sign(sign_payload)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        data = await self._request(
            "POST",
            url,
            headers=headers,
            data=body_str
        )

        if data.get("retCode") != 0:
            raise RuntimeError(f"Buy error: {data}")

        result = data.get("result", {})

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

        timestamp = str(int(time.time() * 1000))

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Market",
            "qty": str(qty),
        }

        body_str = json.dumps(body, separators=(",", ":"))

        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + body_str
        )

        signature = self._sign(sign_payload)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        data = await self._request(
            "POST",
            url,
            headers=headers,
            data=body_str
        )

        if data.get("retCode") != 0:
            raise RuntimeError(f"Sell error: {data}")

        return data

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

        timestamp = str(int(time.time() * 1000))

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(price),
            "timeInForce": "GTC",
        }

        body_str = json.dumps(body, separators=(",", ":"))

        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + body_str
        )

        signature = self._sign(sign_payload)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        data = await self._request(
            "POST",
            url,
            headers=headers,
            data=body_str
        )

        if data.get("retCode") != 0:
            raise RuntimeError(f"Limit sell error: {data}")

        return data

    # ==========================================================
    # CANCEL ALL
    # ==========================================================

    async def cancel_all(self, symbol: str):

        url = f"{self.BASE_URL}/v5/order/cancel-all"

        timestamp = str(int(time.time() * 1000))

        body = {
            "category": "spot",
            "symbol": symbol
        }

        body_str = json.dumps(body, separators=(",", ":"))

        sign_payload = (
            timestamp
            + self.api_key
            + str(self.recv_window)
            + body_str
        )

        signature = self._sign(sign_payload)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        return await self._request(
            "POST",
            url,
            headers=headers,
            data=body_str
        )


BybitSpot = BybitREST
