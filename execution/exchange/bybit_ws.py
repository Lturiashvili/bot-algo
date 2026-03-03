from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import websockets


log = logging.getLogger("bybit_ws")


@dataclass(frozen=True)
class KlineMsg:
    symbol: str
    timeframe: str
    is_closed: bool
    o: float
    h: float
    l: float
    c: float
    v: float
    start_ms: int
    end_ms: int


class BybitWS:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def stream_klines(self, symbols: list[str], timeframe: str) -> AsyncIterator[KlineMsg]:
        if timeframe.endswith("m"):
            interval = timeframe[:-1]
        elif timeframe.endswith("h"):
            interval = str(int(timeframe[:-1]) * 60)
        else:
            raise ValueError("Unsupported timeframe")

        topics = [f"kline.{interval}.{s}" for s in symbols]
        sub = {"op": "subscribe", "args": topics}

        log.info(f"BYBIT_WS_INIT url={self.ws_url} topics={topics}")

        backoff = 0.5
        while not self._stop.is_set():
            try:
                log.info("BYBIT_WS_CONNECTING")
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:

                    log.info("BYBIT_WS_CONNECTED")

                    await ws.send(json.dumps(sub))
                    log.info("BYBIT_WS_SUB_SENT")

                    try:
                        first_msg = await asyncio.wait_for(ws.recv(), timeout=10)
                        first_data = json.loads(first_msg)
                        log.info(f"BYBIT_WS_FIRST_MSG {first_data}")
                    except asyncio.TimeoutError:
                        log.warning("BYBIT_WS_NO_SUB_CONFIRM_WITHIN_10S")

                    backoff = 0.5

                    async for raw in ws:
                        if self._stop.is_set():
                            break

                        try:
                            data = json.loads(raw)
                        except Exception:
                            log.warning("BYBIT_WS_BAD_JSON")
                            continue

                        if "success" in data and data.get("success") is False:
                            log.error(f"BYBIT_WS_SUBSCRIBE_ERROR {data}")
                            continue

                        topic = data.get("topic")
                        if not topic or not str(topic).startswith("kline."):
                            continue

                        items = data.get("data")
                        if not items or not isinstance(items, list):
                            continue

                        item = items[-1]
                        parts = str(topic).split(".")
                        if len(parts) < 3:
                            continue

                        sym = parts[2]

                        yield KlineMsg(
                            symbol=sym,
                            timeframe=timeframe,
                            is_closed=bool(item.get("confirm", False)),
                            o=float(item.get("open")),
                            h=float(item.get("high")),
                            l=float(item.get("low")),
                            c=float(item.get("close")),
                            v=float(item.get("volume")),
                            start_ms=int(item.get("start")),
                            end_ms=int(item.get("end")),
                        )

            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as e:
                log.error(f"BYBIT_WS_EXCEPTION {e}")
                await asyncio.sleep(backoff)
                backoff = min(10.0, backoff * 2)
