from __future__ import annotations
import os
import yaml
from typing import Dict


def load_failsafe_map(path: str) -> Dict[int, int]:
    """
    Загружает соответствия S→P.
    Поддерживает два формата:
    1) YAML-список:
        bindings:
          - s: 30
            p: 18
          - s: 31
            p: 22
    2) YAML-словарь:
        map:
          "30": 18
          "31": 22
    Возвращает словарь {S_pin: P_pin}.
    """
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    result: Dict[int, int] = {}
    if "bindings" in data and isinstance(data["bindings"], list):
        for item in data["bindings"]:
            try:
                s = int(item["s"])
                p = int(item["p"])
                result[s] = p
            except Exception:
                continue
    elif "map" in data and isinstance(data["map"], dict):
        for s_str, p in data["map"].items():
            try:
                s = int(s_str)
                p = int(p)
                result[s] = p
            except Exception:
                continue
    return result
