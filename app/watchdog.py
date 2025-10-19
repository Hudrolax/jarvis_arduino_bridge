from __future__ import annotations
import asyncio
import logging
from typing import Optional
import serial  # pyserial

logger = logging.getLogger("watchdog")

class WatchdogPinger:
    """
    Пинг аппаратного USB watchdog'а по отдельному порту.
    Реализация без зависимостей от asyncio, но управляется через asyncio-task.
    """
    def __init__(self, port: str, baudrate: int = 9600, interval: float = 3.0) -> None:
        self.port = port
        self.baud = baudrate
        self.interval = interval
        self._ser: Optional[serial.Serial] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        logger.info("Opening Watchdog serial: %s @ %d", self.port, self.baud)
        self._ser = serial.Serial(self.port, self.baud, timeout=1, write_timeout=1)
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        self._running = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    async def _run(self) -> None:
        try:
            while self._running:
                try:
                    if self._ser and self._ser.writable():
                        self._ser.write(b"~U")
                        self._ser.flush()
                except Exception as e:
                    logger.error("Watchdog write failed: %s", e)
                    raise
                await asyncio.sleep(self.interval)
        finally:
            try:
                if self._ser:
                    self._ser.close()
            except Exception:
                pass

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await self._task
            except Exception:
                pass
            self._task = None
