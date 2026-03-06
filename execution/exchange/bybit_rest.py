import aiohttp
import hmac
import hashlib
import time
import json
from urllib.parse import urlencode
from typing import Dict, Any, List

from .base import Exchange
from config import Settings

class BybitSpot(Exchange):
    name = "bybit"

    def __init__(self):
        s = Settings()
        self.base_url = "https://api.bybit.com"
        self.api_key = s.BYBIT_API_KEY
        self.api_secret = s.BYBIT_API_SECRET
        self.session = aiohttp.ClientSession()
        self.recv_window = 5000

    def _sign(self, params: Dict, timestamp: int) -> str:
        param_str = str(timestamp) + self.api_key + str(self.recv_window) + json.dumps(params, separators=(',', ':'), sort_keys=True)
        return hmac.new(self.api_secret.encode(), param_str.encode(), hashlib.sha256).hexdigest()

    async def _signed_request(self, method: str, endpoint: str, payload: Dict = None) -> Dict:
        if payload is None:
            payload = {}
        timestamp = int(time.time() * 1000)
        sign = self._sign(payload, timestamp)

        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}{endpoint}"
        async with self.session.request(method, url, headers=headers, json=payload) as resp:
            data = await resp.json()
            if data.get("retCode", 0) != 0:
                raise Exception(f"Bybit error: {data.get('retMsg')}")
            return data["result"]

    async def get_usdt_balance(self) -> float:
        payload = {"accountType": "UNIFIED", "coin": "USDT"}
        data = await self._signed_request("GET", "/v5/account/wallet-balance", payload)
        for coin in data["list"][0]["coin"]:
            if coin["coin"] == "USDT":
                return float(coin["walletBalance"])
        return 0.0

    async def get_price(self, symbol: str) -> float:
        params = {"category": "spot", "symbol": symbol}
        url = f"{self.base_url}/v5/market/tickers?{urlencode(params)}"
        async with self.session.get(url) as resp:
            data = await resp.json()
            return float(data["result"]["list"][0]["lastPrice"])

    async def market_buy_quote(self, symbol: str, quote_amount_usdt: float) -> Dict:
        payload = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "qty": str(quote_amount_usdt),
            "marketUnit": "quoteCoin",
        }
        return await self._signed_request("POST", "/v5/order/create", payload)

    async def market_sell_base(self, symbol: str, base_qty: float) -> Dict:
        payload = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Market",
            "qty": str(base_qty),
        }
        return await self._signed_request("POST", "/v5/order/create", payload)

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> List[Dict]:
        params = {"category": "spot", "symbol": symbol, "interval": timeframe, "limit": limit}
        url = f"{self.base_url}/v5/market/kline?{urlencode(params)}"
        async with self.session.get(url) as resp:
            data = await resp.json()
            rows = data["result"]["list"]
            return [
                {"open_time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                for r in rows
            ]

    async def close(self):
        await self.session.close()
