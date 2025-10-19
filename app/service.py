from __future__ import annotations
import asyncio
import logging
from typing import Dict, List

from .config import AppConfig
from .arduino import ArduinoClient
from .watchdog import WatchdogPinger
from .mqtt_client import MqttManager
from .ha_discovery import device_block, cfg_binary_sensor, cfg_switch, cfg_analog_sensor
from .utils import on_off, as_bool

logger = logging.getLogger("service")

# Пины из прошивки:
S_PINS: List[int] = [38,40,42,44,46,48,50,52,53,39,37,35,33,31,29,27]
P_PINS: List[int] = [36,34,32,30,28,26,24,22,13,12,11,10,9,8,7,6,5,4,3,2,45,47,14,15,16,17,18,19,49,51,23,25]
A_CHANS: List[int] = list(range(16))  # 0..15

class AppService:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.arduino = ArduinoClient(cfg.serial.arduino_port, cfg.serial.arduino_baud)
        self.watchdog = WatchdogPinger(cfg.serial.watchdog_port, cfg.serial.watchdog_baud, 3.0)
        self.mqtt = MqttManager(
            host=cfg.mqtt.host, port=cfg.mqtt.port,
            username=cfg.mqtt.username, password=cfg.mqtt.password,
            base_topic=cfg.mqtt.base_topic,
            lwt_topic=f"{cfg.mqtt.base_topic}/availability",
        )
        self._tasks: List[asyncio.Task] = []
        self._alive = False

        # состояние:
        self._s_state: Dict[int, bool] = {}
        self._p_state: Dict[int, bool] = {}
        self._a_state: Dict[int, int] = {}

    async def start(self) -> None:
        logger.info("Service starting...")
        # MQTT
        await self.mqtt.connect()

        # Arduino
        await self.arduino.open()
        ok = await self.arduino.handshake()
        if not ok:
            logger.error("Arduino handshake failed, exiting.")
            raise SystemExit(2)

        # Watchdog
        self.watchdog.start()

        # Discovery
        await self._publish_discovery()

        # Subscribe to commands for all switches (P*)
        await self.mqtt.subscribe(f"{self.cfg.mqtt.base_topic}/+/set")

        # launch workers
        self._alive = True
        self._tasks = [
            asyncio.create_task(self._mqtt_commands_worker(), name="mqtt_cmds"),
            asyncio.create_task(self._digital_poll_worker(), name="poll_S"),
            asyncio.create_task(self._analog_poll_worker(), name="poll_A"),
        ]
        logger.info("Service started.")

    async def stop(self) -> None:
        logger.info("Service stopping...")
        self._alive = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except Exception:
                pass
        await self.mqtt.disconnect()
        await self.arduino.close()
        await self.watchdog.stop()
        logger.info("Service stopped.")

    async def _publish_discovery(self) -> None:
        import json
        dev = device_block(
            self.cfg.device.name, self.cfg.device.manufacturer,
            self.cfg.device.model, self.cfg.device.identifiers
        )
        # Binary sensors for S pins
        for pin in S_PINS:
            topic, payload = cfg_binary_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)
        # Switches for P pins
        for pin in P_PINS:
            topic, payload = cfg_switch(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)
        # Analog sensors
        for ch in A_CHANS:
            topic, payload = cfg_analog_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, ch)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)

    async def _mqtt_commands_worker(self) -> None:
        """
        Читаем все входящие сообщения и реагируем на `<base>/P<pin>/set`
        """
        async for topic, payload in self.mqtt.unfiltered_messages():
            try:
                if not topic.startswith(f"{self.cfg.mqtt.base_topic}/"):
                    continue
                parts = topic.split("/")
                if len(parts) != 3 or not parts[1].startswith("P") or parts[2] != "set":
                    continue
                pin = int(parts[1][1:])
                if pin not in P_PINS:
                    logger.warning("Command for unknown P-pin: %s", topic)
                    continue
                s = payload.decode("utf-8", errors="ignore").strip()
                if s.upper() == "TOGGLE":
                    state_code = 2
                else:
                    state_code = 1 if as_bool(s) else 0
                resp = await self.arduino.digital_write(pin, state_code)
                # ответ 3333 или 4444:
                new_state = True if resp == 3333 else False
                self._p_state[pin] = new_state
                await self.mqtt.publish(f"{self.cfg.mqtt.base_topic}/P{pin}/state", on_off(new_state), qos=1, retain=False)
            except Exception as e:
                logger.exception("Error handling MQTT command: %s", e)
                # критическая ошибка → стоп контейнер (даст рестарт)
                raise SystemExit(3)

    async def _digital_poll_worker(self) -> None:
        """
        Быстрый цикл опроса S-пинов. Цель — ~digital_hz на ВСЕ пины (то есть цикл пробегает весь список).
        """
        target_hz = max(1, self.cfg.polling.digital_hz)
        # Время на один полный проход списка:
        interval = 1.0 / target_hz
        while self._alive:
            start = asyncio.get_running_loop().time()
            try:
                for pin in S_PINS:
                    val = await self.arduino.digital_read(pin)
                    is_high = (val == 1111)
                    prev = self._s_state.get(pin)
                    if prev is None or prev != is_high:
                        self._s_state[pin] = is_high
                        await self.mqtt.publish(f"{self.cfg.mqtt.base_topic}/S{pin}/state",
                                                on_off(is_high), qos=1, retain=False)
            except Exception as e:
                logger.exception("S-poll error: %s", e)
                raise SystemExit(4)
            # Дозададим частоту прохода по всем S-пинам
            elapsed = asyncio.get_running_loop().time() - start
            sleep_for = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_for)

    async def _analog_poll_worker(self) -> None:
        """
        Опрос аналоговых каналов, публикация при изменении больше порога.
        """
        thr = max(0, self.cfg.polling.analog_threshold)
        interval = max(50, self.cfg.polling.analog_interval_ms) / 1000.0
        while self._alive:
            try:
                for ch in A_CHANS:
                    val = await self.arduino.analog_read(ch)
                    prev = self._a_state.get(ch)
                    if prev is None or abs(val - prev) >= thr:
                        self._a_state[ch] = val
                        await self.mqtt.publish(f"{self.cfg.mqtt.base_topic}/A{ch}/state", str(val), qos=0, retain=False)
            except Exception as e:
                logger.exception("A-poll error: %s", e)
                raise SystemExit(5)
            await asyncio.sleep(interval)
