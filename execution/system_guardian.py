
import asyncio
import logging
import time

log = logging.getLogger("guardian")


class SystemGuardian:

    def __init__(self):
        self.loop_lag_threshold = 2.0
        self.ws_timeout = 120

        self._last_ws_message = time.time()
        self._start_time = time.time()

    # -------------------------------------------------------
    # WEBSOCKET HEARTBEAT
    # -------------------------------------------------------

    def notify_ws_message(self):
        self._last_ws_message = time.time()

    # -------------------------------------------------------
    # LOOP LATENCY CHECK
    # -------------------------------------------------------

    async def monitor_loop_latency(self):
        loop = asyncio.get_running_loop()

        while True:
            start = loop.time()
            await asyncio.sleep(1)
            lag = loop.time() - start - 1

            if lag > self.loop_lag_threshold:
                log.warning(
                    "EVENT_LOOP_LAG_DETECTED",
                    extra={"lag_seconds": round(lag, 3)}
                )

    # -------------------------------------------------------
    # WEBSOCKET STALL CHECK
    # -------------------------------------------------------

    async def monitor_ws_health(self):
        while True:
            idle = time.time() - self._last_ws_message

            if idle > self.ws_timeout:
                log.error(
                    "WEBSOCKET_STALLED",
                    extra={"idle_seconds": int(idle)}
                )

            await asyncio.sleep(15)

    # -------------------------------------------------------
    # TASK WATCHDOG
    # -------------------------------------------------------

    async def monitor_tasks(self):
        while True:
            tasks = asyncio.all_tasks()
            running = [t for t in tasks if not t.done()]

            log.info(
                "TASK_MONITOR",
                extra={"active_tasks": len(running)}
            )

            await asyncio.sleep(30)

    # -------------------------------------------------------
    # SYSTEM HEARTBEAT
    # -------------------------------------------------------

    async def heartbeat(self):
        while True:
            uptime = int(time.time() - self._start_time)

            log.info(
                "SYSTEM_HEALTH_OK",
                extra={"uptime_seconds": uptime}
            )

            await asyncio.sleep(20)

    # -------------------------------------------------------
    # START GUARDIAN
    # -------------------------------------------------------

    async def start(self):
        log.info("SYSTEM_GUARDIAN_STARTED")

        await asyncio.gather(
            self.monitor_loop_latency(),
            self.monitor_ws_health(),
            self.monitor_tasks(),
            self.heartbeat(),
        )
