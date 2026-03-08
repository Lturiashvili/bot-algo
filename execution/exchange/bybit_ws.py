from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Dict

import websockets

log = logging.getLogger("bybit_ws")


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



class BybitWS:

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._stop = asyncio.Event()
        self._last_candle = {}



    def stop(self) -> None:
        self._stop.set()

    # =====================================================
    # MAIN STREAM
    # =====================================================

    async def stream_klines(
        self,
        symbols: list[str],
        timeframe: str
    ) -> AsyncIterator[KlineMsg]:

        # timeframe normalize
        if timeframe.endswith("m"):
            interval = timeframe[:-1]

        elif timeframe.endswith("h"):
            interval = str(int(timeframe[:-1]) * 60)

        else:
            raise ValueError(f"Unsupported timeframe {timeframe}")

        topics = [f"kline.{interval}.{s}" for s in symbols]

        subscribe_msg = {
            "op": "subscribe",
            "args": topics
        }

        log.info(
            "BYBIT_WS_INIT",
            extra={
                "url": self.ws_url,
                "topics": topics
            }
        )

        backoff = 1.0

        while not self._stop.is_set():

            try:

                log.info("BYBIT_WS_CONNECTING")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=5_000_000,
                ) as ws:

                    log.info("BYBIT_WS_CONNECTED")

                    await ws.send(json.dumps(subscribe_msg))
                    log.info("BYBIT_WS_SUBSCRIBE_SENT")

                    backoff = 1.0

                    # ============================
                    # RECEIVE LOOP
                    # ============================

                    while not self._stop.is_set():

                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(),
                                timeout=30
                            )

                        except asyncio.TimeoutError:

                            log.warning("BYBIT_WS_TIMEOUT_NO_DATA")

                            try:
                                await ws.ping()
                                continue
                            except Exception:
                                log.warning("BYBIT_WS_PING_FAILED")
                                break

                        except websockets.ConnectionClosed:

                            log.warning("BYBIT_WS_CONNECTION_CLOSED")
                            break

                        # --------------------------
                        # JSON PARSE
                        # --------------------------

                        try:
                            data = json.loads(raw)

                        except Exception:

                            log.warning(
                                "BYBIT_WS_JSON_ERROR",
                                extra={"raw": raw[:200]}
                            )
                            continue

                        # --------------------------
                        # SUBSCRIBE RESPONSE
                        # --------------------------

                        if "success" in data and "op" in data:
                            continue

                        topic = data.get("topic")

                        if not topic:
                            continue

                        if not topic.startswith("kline."):
                            continue

                        payload = data.get("data")

                        if not payload:
                            continue

                        # normalize payload
                        if isinstance(payload, dict):
                            payload = [payload]

                        if not isinstance(payload, list):
                            continue

                        symbol = parts[2]

                        try:

                            start = int(item["start"])

                            last = self._last_candle.get(symbol)

                            if last == start:
                                continue

                            self._last_candle[symbol] = start

                            msg = KlineMsg(
                                symbol=symbol,
                                timeframe=timeframe,
                                is_closed=bool(item.get("confirm", False)),
                                open=float(item["open"]),
                                high=float(item["high"]),
                                low=float(item["low"]),
                                close=float(item["close"]),
                                volume=float(item["volume"]),
                                start_ms=start,
                                end_ms=int(item["end"]),
                            )

                        except Exception as e:

                            log.warning(
                                "BYBIT_WS_PARSE_ERROR",
                                extra={
                                    "symbol": symbol,
                                    "err": str(e)
                                }
                            )
                            continue

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
