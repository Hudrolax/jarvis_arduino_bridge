# Jarvis Arduino Bridge

Асинхронный мост: **Arduino Mega 2560 ⇄ Serial ⇄ Python ⇄ MQTT ⇄ Home Assistant**  
Параллельно пингует аппаратный **USB Watchdog**.

## Возможности
- S-пины (входы) → `binary_sensor` (MQTT Discovery).
- P-пины (выходы) → `switch` (управление из HA, подтверждение по ответу 3333/4444).
- A-каналы (0..15) → `sensor` (значение 0–1023, публикация при заметном изменении).
- LWT/availability (`<base>/availability`: `online`/`offline`).
- Веб-настройка (FastAPI, порт 8080): MQTT + серийные порты, частоты.

## Быстрый старт
```bash
docker compose up --build -d
