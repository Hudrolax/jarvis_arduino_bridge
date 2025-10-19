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
        # Передаём доп. флаги на всякий случай (не требуются, но не мешают)
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._port,
            baudrate=self._baud,
            rtscts=False,
            dsrdtr=False,
        )

        # Некоторые платы (в т.ч. Mega2560) ресетятся при открытии порта.
        # Дадим бутлоадеру время, очистим мусор.
        await self._post_open_stabilize()

    async def _post_open_stabilize(self) -> None:
        await asyncio.sleep(0.05)
        try:
            # Попробуем аккуратно подёргать DTR через транспорт
            transport = getattr(self._writer, "transport", None) if self._writer else None
            ser = getattr(transport, "serial", None)
            if ser is not None:
                try:
                    ser.dtr = False
                    await asyncio.sleep(0.05)
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    ser.dtr = True
                except Exception:
                    # Не критично, продолжаем
                    pass
        except Exception:
            pass
        # Главное — подождать, пока плата поднимется после reset
        await asyncio.sleep(2.0)  # ~2s обычно достаточно для загрузки скетча

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def handshake(self, timeout: float = 2.5, attempts: int = 3) -> bool:
        """
        Несколько попыток handshake, учитывая возможный ресет после открытия.
        """
        for i in range(1, attempts + 1):
            try:
                resp = await self._txrx(b'I', 666, 1, timeout=timeout)
                ok = (resp == 666)
                if ok:
                    logger.info("Arduino handshake OK (attempt %d/%d)", i, attempts)
                    return True
                else:
                    logger.error("Arduino handshake bad resp=%s (attempt %d/%d)", resp, i, attempts)
            except Exception as e:
                logger.warning("Handshake try %d/%d failed: %s", i, attempts, e)
                # на следующую попытку чуть подождём
                await asyncio.sleep(0.5)
        logger.error("Arduino handshake failed after %d attempts", attempts)
        return False

    async def digital_write(self, pin: int, state: int, timeout: float = 0.5) -> int:
        """
        state: 0=LOW, 1=HIGH, 2=INVERT
        returns 3333 (ON) or 4444 (OFF)
        """
        return await self._txrx(b'P', pin, state, timeout=timeout)

    async def digital_read(self, pin: int, timeout: float = 0.3) -> int:
        """
        returns 1111 (HIGH) or 2222 (LOW)
        """
        return await self._txrx(b'S', pin, 0, timeout=timeout)

    async def analog_read(self, ch: int, timeout: float = 0.3) -> int:
        """
        returns 0..1023
        """
        return await self._txrx(b'A', ch, 0, timeout=timeout)

    async def _txrx(self, cmd: bytes, cval: int, cval2: int, timeout: float) -> int:
        if not self._reader or not self._writer:
            raise RuntimeError("Serial not open")
        payload = bytes((START_FLAG, cmd[0], hi_byte(cval), lo_byte(cval), cval2 & 0xFF))
        async with self._lock:
            # Сброс входного буфера перед запросом, чтобы не читать старый мусор
            try:
                transport = getattr(self._writer, "transport", None)
                ser = getattr(transport, "serial", None)
                if ser is not None:
                    ser.reset_input_buffer()
            except Exception:
                pass

            self._writer.write(payload)
            await self._writer.drain()
            try:
                resp = await asyncio.wait_for(self._reader.readexactly(2), timeout=timeout)
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"Timeout waiting response for {cmd}/{cval}") from e
            return u16_from_bytes(resp)
