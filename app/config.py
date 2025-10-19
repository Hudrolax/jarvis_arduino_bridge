from __future__ import annotations
import os
import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Any

DEFAULT_CONFIG_PATH = os.environ.get("JARVIS_CFG", "/data/config.yaml")

@dataclass
class DeviceInfo:
    name: str = "jarvis_arduino"
    manufacturer: str = "Hudrolax"
    model: str = "JA01"
    identifiers: List[str] = field(default_factory=lambda: ["ja01-arduino-7573532333035190B061"])

@dataclass
class MQTTConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    base_topic: str = "home/jarvis_arduino"   # <-- по умолчанию в home/
    discovery_prefix: str = "homeassistant"
    retain_discovery: bool = True

@dataclass
class SerialPorts:
    arduino_port: str = "/dev/ttyACM1"
    arduino_baud: int = 57600
    watchdog_port: str = "/dev/ttyACM0"
    watchdog_baud: int = 9600

@dataclass
class Polling:
    digital_hz: int = 50
    analog_interval_ms: int = 1000
    analog_threshold: int = 5

@dataclass
class AppConfig:
    device: DeviceInfo = field(default_factory=DeviceInfo)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    serial: SerialPorts = field(default_factory=SerialPorts)
    polling: Polling = field(default_factory=Polling)

    @staticmethod
    def load(path: str = DEFAULT_CONFIG_PATH) -> "AppConfig":
        if not os.path.exists(path):
            cfg = AppConfig()
            cfg.save(path)
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig(
            device=DeviceInfo(**raw.get("device", {})),
            mqtt=MQTTConfig(**raw.get("mqtt", {})),
            serial=SerialPorts(**raw.get("serial", {})),
            polling=Polling(**raw.get("polling", {})),
        )

    def save(self, path: str = DEFAULT_CONFIG_PATH) -> None:
        data: Dict[str, Any] = {
            "device": {
                "name": self.device.name,
                "manufacturer": self.device.manufacturer,
                "model": self.device.model,
                "identifiers": self.device.identifiers,
            },
            "mqtt": {
                "host": self.mqtt.host,
                "port": self.mqtt.port,
                "username": self.mqtt.username,
                "password": self.mqtt.password,
                "base_topic": self.mqtt.base_topic,
                "discovery_prefix": self.mqtt.discovery_prefix,
                "retain_discovery": self.mqtt.retain_discovery,
            },
            "serial": {
                "arduino_port": self.serial.arduino_port,
                "arduino_baud": self.serial.arduino_baud,
                "watchdog_port": self.serial.watchdog_port,
                "watchdog_baud": self.serial.watchdog_baud,
            },
            "polling": {
                "digital_hz": self.polling.digital_hz,
                "analog_interval_ms": self.polling.analog_interval_ms,
                "analog_threshold": self.polling.analog_threshold,
            },
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
