from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Dict, List

import websockets

log = logging.getLogger("bybit_ws")


# =========================================================
# DATA MODEL
# =========================================================

@dataclass(frozen=True)
class KlineMsg:
    symbol: str
    timeframe: str
    is_closed: bool
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_ms: int
    end_ms: int


# =========================================================
# WEBSOCKET CLIENT
# =========================================================

class BybitWS:

    def __init__(self, ws_url: str) -> None:

        self.ws_url = ws_url
        self._stop = asyncio.Event()

        # guard for last CLOSED candle per symbol
        self._last_closed: Dict[str, int] = {}

    def stop(self) -> None:
        self._stop.set()

    # =========================================================
    # MAIN STREAM
    # =========================================================

    async def stream_klines(
        self,
        symbols: List[str],
        timeframe: str
    ) -> AsyncIterator[KlineMsg]:

        # -----------------------------
        # timeframe normalization
        # -----------------------------

        if timeframe.endswith("m"):
            interval = timeframe[:-1]

        elif timeframe.endswith("h"):
            interval = str(int(timeframe[:-1]) * 60)

        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        topics = [f"kline.{interval}.{s}" for s in symbols]

        subscribe_msg = {
            "op": "subscribe",
            "args": topics
        }

        log.info(
            "BYBIT_WS_INIT",
            extra={"url": self.ws_url, "topics": topics}
        )

        backoff = 1.0

        while not self._stop.is_set():

            try:

                log.info("BYBIT_WS_CONNECTING")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=10_000_000,
                ) as ws:

                    log.info("BYBIT_WS_CONNECTED")

                    # -----------------------------
                    # subscribe
                    # -----------------------------

                    await ws.send(json.dumps(subscribe_msg))

                    log.info(
                        "BYBIT_WS_SUBSCRIBE_SENT",
                        extra={"topics": topics}
                    )

                    # -----------------------------
                    # first message
                    # -----------------------------

                    try:

                        first = await asyncio.wait_for(ws.recv(), timeout=10)

                        log.info(
                            "BYBIT_WS_FIRST_MESSAGE",
                            extra={"payload": first[:300]}
                        )

                    except asyncio.TimeoutError:

                        log.warning("BYBIT_WS_SUB_CONFIRM_TIMEOUT")

                    backoff = 1.0

                    # =================================================
                    # MESSAGE LOOP
                    # =================================================

                    async for raw in ws:

                        if self._stop.is_set():
                            break

                        # -----------------------------
                        # JSON PARSE
                        # -----------------------------

                        try:
                            data = json.loads(raw)

                        except Exception:

                            log.warning(
                                "BYBIT_WS_JSON_ERROR",
                                extra={"raw": raw[:200]}
                            )
                            continue

                        # -----------------------------
                        # filter system messages
                        # -----------------------------

                        topic = data.get("topic")

                        if not topic:
                            continue

                        if not topic.startswith("kline."):
                            continue

                        payload = data.get("data")

                        if not payload or not isinstance(payload, list):
                            continue

                        item = payload[-1]

                        parts = topic.split(".")

                        if len(parts) < 3:
                            continue

                        symbol = parts[2]

                        # -----------------------------
                        # SAFE PARSE
                        # -----------------------------

                        try:

                            start = int(item["start"])
                            end = int(item["end"])

                            open_p = float(item["open"])
                            high_p = float(item["high"])
                            low_p = float(item["low"])
                            close_p = float(item["close"])
                            volume = float(item["volume"])

                            closed = bool(item.get("confirm", False))

                        except Exception as e:

                            log.warning(
                                "BYBIT_WS_PARSE_ERROR",
                                extra={"symbol": symbol, "err": str(e)}
                            )

                            continue

                        # -----------------------------
                        # DUPLICATE CLOSED CANDLE GUARD
                        # -----------------------------

                        if closed:

                            last = self._last_closed.get(symbol)

                            if last == start:
                                continue

                            self._last_closed[symbol] = start

                        # -----------------------------
                        # BUILD MESSAGE
                        # -----------------------------

                        msg = KlineMsg(
                            symbol=symbol,
                            timeframe=timeframe,
                            is_closed=closed,
                            open=open_p,
                            high=high_p,
                            low=low_p,
                            close=close_p,
                            volume=volume,
                            start_ms=start,
                            end_ms=end,
                        )

                        yield msg

            except asyncio.CancelledError:
                raise

            except Exception as e:

                log.error(
                    "BYBIT_WS_CONNECTION_ERROR",
                    extra={"err": str(e)}
                )

                await asyncio.sleep(backoff)

                backoff = min(30.0, backoff * 2)

                log.warning(
                    "BYBIT_WS_RECONNECTING",
                    extra={"backoff": backoff}
                )
