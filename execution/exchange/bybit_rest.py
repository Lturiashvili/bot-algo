"""
Production-grade Bybit REST client (Spot V5)
Compatible with SmartRouter / TradeManager execution pipeline
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

        if not api_key or not api_secret:
            raise RuntimeError("Bybit API credentials missing")

        self.name = "bybit"
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.timeout = timeout

        self._session: Optional[aiohttp.ClientSession] = None


# ==========================================================
# Session
# ==========================================================

    async def _get_session(self) -> aiohttp.ClientSession:

        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

        return self._session


    async def close(self):

        if self._session and not self._session.closed:
            await self._session.close()


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

        session = await self._get_session()

        async with session.get(
            url,
            headers=headers,
            params={"accountType": "UNIFIED"},
        ) as resp:

            data = await resp.json()

        if data.get("retCode") != 0:
            raise Exception(f"Bybit balance error: {data}")

        coins = data["result"]["list"][0]["coin"]

        for c in coins:
            if c["coin"] == asset:
                return float(c["walletBalance"])

        return 0.0


# ==========================================================
# Fetch OHLCV
# ==========================================================

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

        logger.info(f"FETCH_OHLCV_OK {symbol}")

        return normalized


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
            "status": result.get("orderStatus"),
            "qty": float(result.get("qty", 0)),
            "avg_price": float(result.get("avgPrice", 0)),
        }

        logger.info(f"MARKET_BUY_OK {symbol}")

        return parsed


# ==========================================================
# MARKET SELL
# ==========================================================

    async def market_sell_base(
        self,
        symbol: str,
        qty: float
    ) -> Dict[str, Any]:

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

        session = await self._get_session()

        async with session.post(
            url,
            headers=headers,
            data=body_str,
        ) as resp:

            data = await resp.json()

        if data.get("retCode") != 0:
            raise Exception(f"Bybit sell error: {data}")

        logger.info(f"MARKET_SELL_OK {symbol}")

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

        session = await self._get_session()

        async with session.post(
            url,
            headers=headers,
            data=body_str,
        ) as resp:

            data = await resp.json()

        if data.get("retCode") != 0:
            raise Exception(f"Bybit limit sell error: {data}")

        logger.info(f"LIMIT_SELL_OK {symbol}")

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

        session = await self._get_session()

        async with session.post(
            url,
            headers=headers,
            data=body_str,
        ) as resp:

            data = await resp.json()

        logger.info(f"CANCEL_ALL {symbol}")

        return data


# ==========================================================
# Alias
# ==========================================================

BybitSpot = BybitREST
