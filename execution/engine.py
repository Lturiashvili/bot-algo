import os
import logging

from execution.exchange_client import build_exchange_client

logger = logging.getLogger("gbm")


class ExecutionEngine:
    """
    Production execution engine for Bybit Spot trading.
    Fully compatible with main.py worker.
    """

    def __init__(self):

        self.mode = os.getenv("MODE", "DEMO").upper()

        self.default_quote = float(
            os.getenv("BOT_QUOTE_PER_TRADE", "10")
        )

        self.exchange = build_exchange_client()

        logger.info(
            f"ExecutionEngine initialized | MODE={self.mode}"
        )

    # -------------------------------------------------
    # EXECUTE SIGNAL
    # -------------------------------------------------

    def execute_signal(self, signal: dict):

        try:

            logger.info(f"SIGNAL_RECEIVED | {signal}")

            # -------------------------------------------------
            # SYMBOL
            # -------------------------------------------------

            symbol = (
                signal.get("symbol")
                or signal.get("execution", {}).get("symbol")
            )

            if not symbol:

                logger.warning("SIGNAL_REJECTED | missing symbol")

                return

            # -------------------------------------------------
            # VERDICT
            # -------------------------------------------------

            verdict = str(
                signal.get("final_verdict")
                or signal.get("verdict")
                or ""
            ).upper()

            if verdict not in ["BUY", "TRADE"]:

                logger.info(
                    f"SIGNAL_SKIPPED | verdict={verdict}"
                )

                return

            # -------------------------------------------------
            # ORDER SIZE
            # -------------------------------------------------

            quote_amount = (
                signal.get("quote_amount")
                or signal.get("execution", {}).get("quote_amount")
                or self.default_quote
            )

            quote_amount = float(quote_amount)

            logger.info(
                f"BYBIT_MARKET_BUY | symbol={symbol} quote={quote_amount}"
            )

            # -------------------------------------------------
            # PLACE ORDER
            # -------------------------------------------------

            order = self.exchange.place_market_buy_by_quote(
                symbol,
                quote_amount
            )

            # -------------------------------------------------
            # ORDER ID SAFE PARSING
            # -------------------------------------------------

            order_id = None

            if isinstance(order, dict):

                order_id = (
                    order.get("id")
                    or order.get("orderId")
                    or (order.get("info") or {}).get("orderId")
                )

            logger.info(
                f"ORDER_PLACED | symbol={symbol} order_id={order_id}"
            )

        except Exception as e:

            logger.error("EXECUTION_ERROR")

            logger.error(str(e))
