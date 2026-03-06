import logging
from typing import Optional

logger = logging.getLogger("smart_router")

class SmartRouter:
    """მარტივი abstraction order-ების გასაგზავნად (binance/bybit)"""

    def __init__(self, exchange):
        self.exchange = exchange  # შენი Exchange კლასის ინსტანსი

    async def market_buy(self, symbol: str, quote_amount: float) -> Optional[dict]:
        try:
            result = await self.exchange.market_buy_quote(symbol, quote_amount)
            logger.info(f"BUY შესრულდა: {symbol} | {quote_amount} USDT")
            return result
        except Exception as e:
            logger.error(f"BUY წარუმატებელი: {symbol} | {e}")
            return None

    async def market_sell(self, symbol: str, base_qty: float) -> Optional[dict]:
        try:
            result = await self.exchange.market_sell_base(symbol, base_qty)
            logger.info(f"SELL შესრულდა: {symbol} | {base_qty}")
            return result
        except Exception as e:
            logger.error(f"SELL წარუმატებელი: {symbol} | {e}")
            return None

    async def emergency_close_all(self):
        logger.critical("EMERGENCY CLOSE ALL გააქტიურდა!")
        # აქ ყველა ღია პოზიციის დახურვა
