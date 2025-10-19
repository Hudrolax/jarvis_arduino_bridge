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
        self._tasks: List[asyncio.Task] = []
        self._alive = False

        # состояния
        self._s_state: Dict[int, bool] = {}
        self._p_state: Dict[int, bool] = {}
        self._a_state: Dict[int, int] = {}

        # клиенты
        self._build_clients()

    def _build_clients(self) -> None:
        self.arduino = ArduinoClient(self.cfg.serial.arduino_port, self.cfg.serial.arduino_baud)
        self.watchdog = WatchdogPinger(self.cfg.serial.watchdog_port, self.cfg.serial.watchdog_baud, 3.0)
        self.mqtt = MqttManager(
            host=self.cfg.mqtt.host, port=self.cfg.mqtt.port,
            username=self.cfg.mqtt.username, password=self.cfg.mqtt.password,
            base_topic=self.cfg.mqtt.base_topic,
            lwt_topic=f"{self.cfg.mqtt.base_topic}/availability",
        )

    async def start(self) -> None:
        logger.info("Service starting...")
        await self.mqtt.connect()

        await self.arduino.open()
        ok = await self.arduino.handshake()
        if not ok:
            logger.error("Arduino handshake failed, exiting.")
            raise SystemExit(2)

        self.watchdog.start()

        await self._publish_discovery()

        await self.mqtt.subscribe(f"{self.cfg.mqtt.base_topic}/+/set")

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
        self._tasks.clear()
        try:
            await self.mqtt.disconnect()
        except Exception:
            pass
        try:
            await self.arduino.close()
        except Exception:
            pass
        try:
            await self.watchdog.stop()
        except Exception:
            pass
        logger.info("Service stopped.")

    async def reload(self, new_cfg: AppConfig) -> None:
        """
        Мягкий перезапуск сервиса с новой конфигурацией (без перезапуска контейнера).
        """
        logger.info("Service reloading with new config...")
        await self.stop()
        self.cfg = new_cfg
        self._build_clients()
        await self.start()
        logger.info("Service reloaded.")

    async def _publish_discovery(self) -> None:
        import json
        dev = device_block(
            self.cfg.device.name, self.cfg.device.manufacturer,
            self.cfg.device.model, self.cfg.device.identifiers
        )
        for pin in S_PINS:
            topic, payload = cfg_binary_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)
        for pin in P_PINS:
            topic, payload = cfg_switch(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)
        for ch in A_CHANS:
            topic, payload = cfg_analog_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, ch)
            await self.mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=self.cfg.mqtt.retain_discovery)

    async def _mqtt_commands_worker(self) -> None:
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
                new_state = True if resp == 3333 else False
                self._p_state[pin] = new_state
                await self.mqtt.publish(f"{self.cfg.mqtt.base_topic}/P{pin}/state", on_off(new_state), qos=1, retain=False)
            except Exception as e:
                logger.exception("Error handling MQTT command: %s", e)
                raise SystemExit(3)

    async def _digital_poll_worker(self) -> None:
        target_hz = max(1, self.cfg.polling.digital_hz)
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
            elapsed = asyncio.get_running_loop().time() - start
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _analog_poll_worker(self) -> None:
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
