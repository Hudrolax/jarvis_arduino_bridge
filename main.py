import asyncio
import logging
import signal
from app.utils import setup_logging
from app.config import AppConfig
from app.web import create_app
from app.service import AppService
import uvicorn

async def runner():
    setup_logging(logging.INFO)
    cfg = AppConfig.load()
    service = AppService(cfg)

    # Запускаем FastAPI (uvicorn) параллельно с сервисом
    app = create_app(cfg)
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)

    async def start_service():
        await service.start()
        # не возвращаемся — живём пока не отменят
        while True:
            await asyncio.sleep(3600)

    async def start_web():
        await server.serve()

    svc_task = asyncio.create_task(start_service(), name="service")
    web_task = asyncio.create_task(start_web(), name="web")

    # Грейсфул остановка по сигналу
    stop_evt = asyncio.Event()

    def _signal_handler():
        stop_evt.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, _signal_handler)

    await stop_evt.wait()
    # Завершаем
    await service.stop()
    web_task.cancel()
    svc_task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        pass
