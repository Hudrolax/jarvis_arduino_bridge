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
from .state_store import load_p_states, save_p_states
from .failsafe import load_failsafe_map

logger = logging.getLogger("service")

S_PINS: List[int] = [38,40,42,44,46,48,50,52,53,39,37,35,33,31,29,27]
P_PINS: List[int] = [36,34,32,30,28,26,24,22,13,12,11,10,9,8,7,6,5,4,3,2,45,47,14,15,16,17,18,19,49,51,23,25]
A_CHANS: List[int] = list(range(16))

class AppService:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._tasks: List[asyncio.Task] = []
        self._alive = False

        self._s_state: Dict[int, bool] = {}
        self._p_state: Dict[int, bool] = {}
        self._a_state: Dict[int, int] = {}

        self._mqtt_online: bool = False
        self._failsafe_map: Dict[int, int] = {}

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
        self._failsafe_map = load_failsafe_map(self.cfg.paths.failsafe_path)
        logger.info("Failsafe map: %s", self._failsafe_map or "empty")

        await self.mqtt.connect()
        self._mqtt_online = True

        await self.arduino.open()
        ok = await self.arduino.handshake()
        if not ok:
            logger.error("Arduino handshake failed, exiting.")
            raise SystemExit(2)

        self.watchdog.start()

        await self._restore_pins()
        await self._publish_discovery()
        await self._publish_all_states(retain=True)

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
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        try:
            await self.mqtt.disconnect()
        except Exception:
            pass
        self._mqtt_online = False
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
        logger.info("Service reloading with new config...")
        await self.stop()
        self.cfg = new_cfg
        self._build_clients()
        await self.start()
        logger.info("Service reloaded.")

    async def _safe_publish(self, topic: str, payload: str, *, qos: int = 1, retain: bool = True) -> None:
        if not self._mqtt_online:
            return
        try:
            await self.mqtt.publish(topic, payload, qos=qos, retain=retain)
        except Exception as e:
            if self._mqtt_online:
                logger.warning("MQTT publish failed (%s). Entering failsafe and disconnecting...", e)
                self._mqtt_online = False
                try:
                    await self.mqtt.disconnect()
                except Exception:
                    pass

    async def _ensure_mqtt_online(self) -> None:
        backoff = 1.0
        while self._alive and not self._mqtt_online:
            try:
                await self.mqtt.connect()
                self._mqtt_online = True
                await self.mqtt.subscribe(f"{self.cfg.mqtt.base_topic}/+/set")
                await self._publish_discovery()
                await self._publish_all_states(retain=True)
                logger.info("Reconnected to MQTT, leaving failsafe.")
                return
            except Exception as e:
                logger.warning("Reconnect to MQTT failed: %s", e)
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2.0, 30.0)

    async def _restore_pins(self) -> None:
        path = self.cfg.paths.state_path
        saved = load_p_states(path)
        if not saved:
            logger.info("No saved P states found at %s", path)
            return
        logger.info("Restoring P states from %s: %s", path, saved)
        for pin, state in saved.items():
            if pin not in P_PINS:
                continue
            try:
                resp = await self.arduino.digital_write(pin, 1 if state else 0)
                new_state = True if resp == 3333 else False
                self._p_state[pin] = new_state
                await self._safe_publish(f"{self.cfg.mqtt.base_topic}/P{pin}/state", on_off(new_state), qos=1, retain=True)
            except Exception as e:
                logger.warning("Failed to restore P%d: %s", pin, e)

    async def _publish_discovery(self) -> None:
        import json
        dev = device_block(
            self.cfg.device.name, self.cfg.device.manufacturer,
            self.cfg.device.model, self.cfg.device.identifiers
        )
        for pin in S_PINS:
            topic, payload = cfg_binary_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self._safe_publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
        for pin in P_PINS:
            topic, payload = cfg_switch(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, pin)
            await self._safe_publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
        # публикуем discovery только для включённых A-каналов
        for ch in A_CHANS:
            if not self.cfg.inputs.analog_enabled[ch]:
                continue
            topic, payload = cfg_analog_sensor(self.cfg.mqtt.discovery_prefix, self.cfg.mqtt.base_topic, dev, ch)
            await self._safe_publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)

    async def _publish_all_states(self, *, retain: bool) -> None:
        # S (всегда публикуем)
        for pin in S_PINS:
            try:
                val = await self.arduino.digital_read(pin)
                is_high = (val == 1111)
                self._s_state[pin] = is_high
                await self._safe_publish(f"{self.cfg.mqtt.base_topic}/S{pin}/state", on_off(is_high), qos=1, retain=retain)
            except Exception as e:
                logger.warning("Initial S read failed for %d: %s", pin, e)

        # P (всегда публикуем, если знаем состояние)
        for pin in P_PINS:
            if pin in self._p_state:
                await self._safe_publish(f"{self.cfg.mqtt.base_topic}/P{pin}/state", on_off(self._p_state[pin]), qos=1, retain=retain)

        # A — только включённые
        for ch in A_CHANS:
            if not self.cfg.inputs.analog_enabled[ch]:
                continue
            try:
                val = await self.arduino.analog_read(ch)
                self._a_state[ch] = val
                await self._safe_publish(f"{self.cfg.mqtt.base_topic}/A{ch}/state", str(val), qos=0, retain=retain)
            except Exception as e:
                logger.warning("Initial A read failed for %d: %s", ch, e)

    async def _mqtt_commands_worker(self) -> None:
        while self._alive:
            if not self._mqtt_online:
                await self._ensure_mqtt_online()
                if not self._mqtt_online:
                    await asyncio.sleep(2.0)
                    continue
            try:
                async for topic, payload in self.mqtt.unfiltered_messages():
                    base = self.cfg.mqtt.base_topic.rstrip("/")
                    prefix = base + "/"
                    if not topic.startswith(prefix):
                        continue
                    rel = topic[len(prefix):]
                    parts = rel.split("/")
                    if len(parts) != 2 or not parts[0].startswith("P") or parts[1] != "set":
                        continue

                    pin = int(parts[0][1:])
                    if pin not in P_PINS:
                        logger.warning("Command for unknown P-pin: %s", topic)
                        continue

                    s = payload.decode("utf-8", errors="ignore").strip()
                    state_code = 2 if s.upper() == "TOGGLE" else (1 if as_bool(s) else 0)

                    resp = await self.arduino.digital_write(pin, state_code)
                    new_state = True if resp == 3333 else False
                    self._p_state[pin] = new_state

                    await self._safe_publish(f"{self.cfg.mqtt.base_topic}/P{pin}/state", on_off(new_state), qos=1, retain=True)
                    try:
                        save_p_states(self.cfg.paths.state_path, self._p_state)
                    except Exception as e:
                        logger.warning("Failed to persist P states: %s", e)

                    if not self._mqtt_online:
                        break

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("MQTT consumer failed, going offline: %s", e)
                self._mqtt_online = False

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
                        await self._safe_publish(f"{self.cfg.mqtt.base_topic}/S{pin}/state", on_off(is_high), qos=1, retain=True)

                        if not self._mqtt_online and pin in self._failsafe_map:
                            p_pin = self._failsafe_map[pin]
                            if self._p_state.get(p_pin) != is_high:
                                try:
                                    resp = await self.arduino.digital_write(p_pin, 1 if is_high else 0)
                                    new_state = True if resp == 3333 else False
                                    self._p_state[p_pin] = new_state
                                    try:
                                        save_p_states(self.cfg.paths.state_path, self._p_state)
                                    except Exception as e:
                                        logger.warning("Persist P states failed (failsafe): %s", e)
                                except Exception as e:
                                    logger.warning("Failsafe write P%d from S%d failed: %s", p_pin, pin, e)

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
                    if not self.cfg.inputs.analog_enabled[ch]:
                        # читаем можно и не читать, но так меньше шуметь шиной
                        continue
                    val = await self.arduino.analog_read(ch)
                    prev = self._a_state.get(ch)
                    if prev is None or abs(val - prev) >= thr:
                        self._a_state[ch] = val
                        await self._safe_publish(f"{self.cfg.mqtt.base_topic}/A{ch}/state", str(val), qos=0, retain=True)
            except Exception as e:
                logger.exception("A-poll error: %s", e)
                raise SystemExit(5)
            await asyncio.sleep(interval)
