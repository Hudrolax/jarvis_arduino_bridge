from __future__ import annotations
import json
import os
import tempfile
from typing import Dict


def load_p_states(path: str) -> Dict[int, bool]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        # ожидаем формат: {"P": {"22": true, "24": false, ...}}
        p = raw.get("P", {})
        result: Dict[int, bool] = {}
        for k, v in p.items():
            try:
                pin = int(k)
                result[pin] = bool(v)
            except Exception:
                continue
        return result
    except Exception:
        return {}


def save_p_states(path: str, mapping: Dict[int, bool]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"P": {str(k): bool(v) for k, v in sorted(mapping.items())}}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # атомарная запись
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_state_", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as w:
            w.write(data)
            w.flush()
            os.fsync(w.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
