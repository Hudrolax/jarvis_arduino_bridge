from __future__ import annotations
from typing import Dict, Any

def device_block(name: str, manufacturer: str, model: str, identifiers: list[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "manufacturer": manufacturer,
        "model": model,
        "identifiers": identifiers,
    }

def cfg_binary_sensor(discovery_prefix: str, base_topic: str, dev: Dict[str, Any], pin: int) -> tuple[str, dict]:
    uid = f"{dev['name']}_s_{pin}"
    topic = f"{discovery_prefix}/binary_sensor/{dev['name']}/S{pin}/config"
    payload = {
        "name": f"S{pin}",
        "unique_id": uid,
        "state_topic": f"{base_topic}/S{pin}/state",
        "availability_topic": f"{base_topic}/availability",
        "payload_on": "ON",
        "payload_off": "OFF",
        "device": dev,
        "icon": "mdi:toggle-switch",
    }
    return topic, payload

def cfg_switch(discovery_prefix: str, base_topic: str, dev: Dict[str, Any], pin: int) -> tuple[str, dict]:
    uid = f"{dev['name']}_p_{pin}"
    topic = f"{discovery_prefix}/switch/{dev['name']}/P{pin}/config"
    payload = {
        "name": f"P{pin}",
        "unique_id": uid,
        "state_topic":  f"{base_topic}/P{pin}/state",
        "command_topic":f"{base_topic}/P{pin}/set",
        "availability_topic": f"{base_topic}/availability",
        "payload_on": "ON",
        "payload_off": "OFF",
        "icon": "mdi:electric-switch",
        "device": dev,
    }
    return topic, payload

def cfg_analog_sensor(discovery_prefix: str, base_topic: str, dev: Dict[str, Any], ch: int) -> tuple[str, dict]:
    uid = f"{dev['name']}_a_{ch}"
    topic = f"{discovery_prefix}/sensor/{dev['name']}/A{ch}/config"
    payload = {
        "name": f"A{ch}",
        "unique_id": uid,
        "state_topic": f"{base_topic}/A{ch}/state",
        "availability_topic": f"{base_topic}/availability",
        "state_class": "measurement",
        "icon": "mdi:waveform",
        "device": dev,
    }
    return topic, payload
