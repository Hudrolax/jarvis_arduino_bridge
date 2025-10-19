from __future__ import annotations
import asyncio
import logging
from typing import Optional, Tuple

import serial_asyncio  # type: ignore

from .utils import hi_byte, lo_byte, u16_from_bytes

logger = logging.getLogger("arduino")

START_FLAG = 222

class ArduinoClient:
    """
    Асинхронный клиент для вашего протокола:
    Пакет: [222][cmd]['hi'][lo][arg], ответ всегда 2 байта (uint16)
    Команды:
      I: handshake (cval=666, cval2=1) -> 666 OK
      P: цифровой выход (cval=pin, cval2: 0/1/2)
      A: аналог чтение (cval=0..15)
      S: цифровой вход чтение (cval=pin)
    """

    def __init__(self, port: str, baudrate: int = 57600) -> None:
        self._port = port
        self._baud = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        logger.info("Opening Arduino serial: %s @ %d", self._port, self._baud)
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._port, baudrate=self._baud
        )
        await asyncio.sleep(0.1)

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def handshake(self, timeout: float = 1.0) -> bool:
        try:
            resp = await self._txrx(b'I', 666, 1, timeout=timeout)
            ok = (resp == 666)
            if ok:
                logger.info("Arduino handshake OK")
            else:
                logger.error("Arduino handshake failed: resp=%s", resp)
            return ok
        except Exception as e:
            logger.exception("Handshake error: %s", e)
            return False

    async def digital_write(self, pin: int, state: int, timeout: float = 0.3) -> int:
        """
        state: 0=LOW, 1=HIGH, 2=INVERT
        returns 3333 (ON) or 4444 (OFF)
        """
        return await self._txrx(b'P', pin, state, timeout=timeout)

    async def digital_read(self, pin: int, timeout: float = 0.25) -> int:
        """
        returns 1111 (HIGH) or 2222 (LOW)
        """
        return await self._txrx(b'S', pin, 0, timeout=timeout)

    async def analog_read(self, ch: int, timeout: float = 0.25) -> int:
        """
        returns 0..1023
        """
        return await self._txrx(b'A', ch, 0, timeout=timeout)

    async def _txrx(self, cmd: bytes, cval: int, cval2: int, timeout: float) -> int:
        if not self._reader or not self._writer:
            raise RuntimeError("Serial not open")
        payload = bytes((START_FLAG, cmd[0], hi_byte(cval), lo_byte(cval), cval2 & 0xFF))
        async with self._lock:
            self._writer.write(payload)
            await self._writer.drain()
            try:
                resp = await asyncio.wait_for(self._reader.readexactly(2), timeout=timeout)
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"Timeout waiting response for {cmd}/{cval}") from e
            return u16_from_bytes(resp)
