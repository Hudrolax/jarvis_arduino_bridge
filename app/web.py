from __future__ import annotations
import asyncio
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from .config import AppConfig, DEFAULT_CONFIG_PATH
from .service import AppService

def create_app(cfg: AppConfig, service: AppService) -> FastAPI:
    app = FastAPI(title="Jarvis Arduino Bridge", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return f"""
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Jarvis Arduino Bridge</title></head>
<body style="font-family:system-ui;max-width:800px;margin:2rem auto;">
  <h1>Jarvis Arduino Bridge</h1>
  <form method="post" action="/save" style="display:grid;grid-template-columns: 200px 1fr;gap:.5rem 1rem;">
    <h2 style="grid-column:1/-1;">MQTT</h2>
    <label>Host</label><input name="mqtt_host" value="{cfg.mqtt.host}">
    <label>Port</label><input name="mqtt_port" type="number" value="{cfg.mqtt.port}">
    <label>Username</label><input name="mqtt_user" value="{cfg.mqtt.username or ''}">
    <label>Password</label><input name="mqtt_pass" type="password" value="{cfg.mqtt.password or ''}">
    <label>Base topic</label><input name="base_topic" value="{cfg.mqtt.base_topic}">

    <h2 style="grid-column:1/-1;">Serial</h2>
    <label>Arduino port</label><input name="arduino_port" value="{cfg.serial.arduino_port}">
    <label>Arduino baud</label><input name="arduino_baud" type="number" value="{cfg.serial.arduino_baud}">
    <label>Watchdog port</label><input name="watchdog_port" value="{cfg.serial.watchdog_port}">
    <label>Watchdog baud</label><input name="watchdog_baud" type="number" value="{cfg.serial.watchdog_baud}">

    <h2 style="grid-column:1/-1;">Polling</h2>
    <label>Digital Hz</label><input name="digital_hz" type="number" value="{cfg.polling.digital_hz}">
    <label>Analog interval (ms)</label><input name="analog_interval_ms" type="number" value="{cfg.polling.analog_interval_ms}">
    <label>Analog threshold</label><input name="analog_threshold" type="number" value="{cfg.polling.analog_threshold}">

    <div style="grid-column:1/-1;">
      <button type="submit">Save & Apply</button>
    </div>
  </form>
  <p>Config path: <code>{DEFAULT_CONFIG_PATH}</code>. State path: <code>{cfg.paths.state_path}</code>.</p>
</body></html>
"""

    @app.post("/save")
    async def save(
        mqtt_host: str = Form(...),
        mqtt_port: int = Form(...),
        mqtt_user: str = Form(""),
        mqtt_pass: str = Form(""),
        base_topic: str = Form(...),
        arduino_port: str = Form(...),
        arduino_baud: int = Form(...),
        watchdog_port: str = Form(...),
        watchdog_baud: int = Form(...),
        digital_hz: int = Form(...),
        analog_interval_ms: int = Form(...),
        analog_threshold: int = Form(...),
    ):
        cfg.mqtt.host = mqtt_host
        cfg.mqtt.port = int(mqtt_port)
        cfg.mqtt.username = mqtt_user or None
        cfg.mqtt.password = mqtt_pass or None
        cfg.mqtt.base_topic = base_topic

        cfg.serial.arduino_port = arduino_port
        cfg.serial.arduino_baud = int(arduino_baud)
        cfg.serial.watchdog_port = watchdog_port
        cfg.serial.watchdog_baud = int(watchdog_baud)

        cfg.polling.digital_hz = int(digital_hz)
        cfg.polling.analog_interval_ms = int(analog_interval_ms)
        cfg.polling.analog_threshold = int(analog_threshold)

        cfg.save()

        try:
            await service.reload(cfg)
        except asyncio.CancelledError:
            return RedirectResponse("/", status_code=303)
        except Exception:
            return RedirectResponse(f"/?error=reload_failed", status_code=303)

        return RedirectResponse("/", status_code=303)

    @app.get("/status")
    async def status():
        return JSONResponse({
            "mqtt": {"host": cfg.mqtt.host, "port": cfg.mqtt.port, "base_topic": cfg.mqtt.base_topic},
            "serial": {"arduino_port": cfg.serial.arduino_port, "watchdog_port": cfg.serial.watchdog_port},
            "polling": {"digital_hz": cfg.polling.digital_hz, "analog_interval_ms": cfg.polling.analog_interval_ms,
                        "analog_threshold": cfg.polling.analog_threshold},
            "paths": {"state_path": cfg.paths.state_path},
        })

    return app
