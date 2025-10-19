import logging
import sys
from typing import Any

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"

def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(stream=sys.stdout, level=level, format=LOG_FORMAT)

def hi_byte(val: int) -> int:
    return (val >> 8) & 0xFF

def lo_byte(val: int) -> int:
    return val & 0xFF

def u16_from_bytes(b: bytes) -> int:
    if len(b) != 2:
        raise ValueError("expected 2 bytes")
    return (b[0] << 8) | b[1]

def clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))

def as_bool(on_off: str) -> bool:
    s = on_off.strip().lower()
    if s in ("1", "on", "true", "high"):
        return True
    if s in ("0", "off", "false", "low"):
        return False
    raise ValueError(f"bad boolean payload: {on_off}")

def on_off(val: bool) -> str:
    return "ON" if val else "OFF"
