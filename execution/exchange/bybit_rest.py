import aiohttp
import logging
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

log = logging.getLogger("bybit_rest")


class BybitSpot:
    def __init__(self, base_url, api_key, api_secret, limiter):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.limiter = limiter

    # ==========================================================
    # INTERNAL: SIGNING
    # ==========================================================

    def _sign(self, params: dict) -> dict:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"

        params_str = urlencode(sorted(params.items()))
        payload = timestamp + self.api_key + recv_window + params_str

        signature = hmac.new(
            self.api_secret,
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "Content-Type": "application/json"
        }

        return headers

    # ==========================================================
    # FETCH OHLCV
    # ==========================================================

    async def fetch_ohlcv(self, symbol: str, interval: str, limit: int = 200):
        url = f"{self.base_url}/v5/market/kline"

        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

        if not isinstance(data, dict):
            raise Exception(f"Invalid OHLCV response: {data}")

        if data.get("retCode") != 0:
            raise Exception(f"Bybit OHLCV error: {data}")

        result = data.get("result", {})
        candles = result.get("list", [])

        # Normalize structure
        parsed = []
        for c in candles:
            parsed.append([
                int(c[0]),        # timestamp
                float(c[1]),      # open
                float(c[2]),      # high
                float(c[3]),      # low
                float(c[4]),      # close
                float(c[5])       # volume
            ])

        return parsed[::-1]  # oldest → newest

    # ==========================================================
    # MARKET BUY (QUOTE SIZE)
    # ==========================================================

    async def market_buy_quote(self, symbol: str, quote_usdt: float):
        url = f"{self.base_url}/v5/order/create"

        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "qty": str(quote_usdt),
            "marketUnit": "quoteCoin"
        }

        headers = self._sign(body)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()

        log.info(f"BYBIT_RAW_RESPONSE {data}")

        if not isinstance(data, dict):
            raise Exception(f"Invalid order response: {data}")

        if data.get("retCode") != 0:
            raise Exception(
                f"Order failed retCode={data.get('retCode')} "
                f"msg={data.get('retMsg')}"
            )

        result = data.get("result")
        if not result:
            raise Exception("Missing 'result' in order response")

        order_id = result.get("orderId") or result.get("order_id")
        if not order_id:
            raise Exception(f"Missing orderId field: {result}")

        # Unified return object
        class OrderResult:
            def __init__(self, oid):
                self.order_id = str(oid)
                self.executed_qty = None
                self.avg_price = None
                self.status = "SUBMITTED"

        return OrderResult(order_id)
