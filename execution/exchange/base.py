from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

class Exchange(ABC):
    """ძირითადი ინტერფეისი ყველა ბირჟისთვის"""

    name: str

    @abstractmethod
    async def get_usdt_balance(self) -> float:
        """ბალანსი USDT-ში"""
        pass

    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """მიმდინარე საუკეთესო ფასი"""
        pass

    @abstractmethod
    async def market_buy_quote(self, symbol: str, quote_amount_usdt: float) -> Dict[str, Any]:
        """მარკეტ ყიდვა quote (USDT) რაოდენობით"""
        pass

    @abstractmethod
    async def market_sell_base(self, symbol: str, base_qty: float) -> Dict[str, Any]:
        """მარკეტ გაყიდვა base (მაგ. BTC) რაოდენობით"""
        pass

    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> List[Dict]:
        """OHLCV მონაცემები"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """რესურსების გათავისუფლება"""
        pass
