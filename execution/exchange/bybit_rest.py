import aiohttp
import logging
import time
import hmac
import hashlib
from urllib.parse import urlencode

log = logging.getLogger("bybit_rest")


class BybitSpot:
    def __init__(self, base_url, api_key, api_secret, limiter):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.limiter = limiter

    # ==========================================================
    # INTERVAL MAPPING (CRITICAL FIX)
    # ==========================================================

    def _map_interval(self, interval: str) -> str:
        mapping = {
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "2h": "120",
            "4h": "240",
            "1d": "D"
        }
        return mapping.get(interval, interval)

    # ==========================================================
    # SIGNING
    # ==========================================================

    def _sign(self, params: dict) -> dict:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"

        param_str = urlencode(sorted(params.items()))
        payload = timestamp + self.api_key + recv_window + param_str

        signature = hmac.new(
            self.api_secret,
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "Content-Type": "application/json"
        }

    # ==========================================================
    # FETCH OHLCV
    # ==========================================================

    async def fetch_ohlcv(self, symbol: str, interval: str, limit: int = 200):
        url = f"{self.base_url}/v5/market/kline"

        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": self._map_interval(interval),
            "limit": limit
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

        if not isinstance(data, dict):
            raise Exception(f"Invalid OHLCV response: {data}")

        if data.get("retCode") != 0:
            raise Exception(f"Bybit OHLCV error: {data}")

        candles = data.get("result", {}).get("list", [])

        parsed = []
        for c in candles:
            parsed.append([
                int(c[0]),
                float(c[1]),
                float(c[2]),
                float(c[3]),
                float(c[4]),
                float(c[5])
            ])

        return parsed[::-1]

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
            raise Exception(f"Missing orderId in response: {result}")

        class OrderResult:
            def __init__(self, oid):
                self.order_id = str(oid)
                self.executed_qty = None
                self.avg_price = None
                self.status = "SUBMITTED"

        return OrderResult(order_id)
