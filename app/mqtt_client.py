from __future__ import annotations
import asyncio
import logging
from typing import AsyncIterator, Tuple, Union

logger = logging.getLogger("mqtt")

# Переход на aiomqtt (совместимо с asyncio-mqtt при fallback)
try:
    import aiomqtt as mqttlib  # type: ignore
    from aiomqtt import Client, MqttError, Will  # type: ignore
    _USING_AIO = True
except Exception:
    # на случай если кто-то оставит старую зависимость
    from asyncio_mqtt import Client, MqttError, Will  # type: ignore
    import asyncio_mqtt as mqttlib  # type: ignore
    _USING_AIO = False


class MqttManager:
    def __init__(self, host: str, port: int, username: str | None, password: str | None,
                 base_topic: str, lwt_topic: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.base_topic = base_topic
        self.lwt_topic = lwt_topic
        self.client: Client | None = None

    def _make_client(self) -> Client:
        will = Will(self.lwt_topic, payload=b"offline", qos=1, retain=True)
        return Client(self.host, port=self.port, username=self.username, password=self.password, will=will)

    async def connect(self) -> None:
        self.client = self._make_client()
        await self.client.connect()
        await self.publish(self.lwt_topic, "online", qos=1, retain=True)
        logger.info("MQTT connected to %s:%d (%s)", self.host, self.port, "aiomqtt" if _USING_AIO else "asyncio-mqtt")

    async def disconnect(self) -> None:
        if self.client:
            try:
                await self.publish(self.lwt_topic, "offline", qos=1, retain=True)
                await self.client.disconnect()
            finally:
                self.client = None

    async def publish(self, topic: str, payload: Union[str, bytes], *, qos: int = 0, retain: bool = False) -> None:
        assert self.client is not None
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        await self.client.publish(topic, payload, qos=qos, retain=retain)

    async def subscribe(self, topic: str) -> None:
        assert self.client is not None
        await self.client.subscribe(topic)

    async def unfiltered_messages(self) -> AsyncIterator[Tuple[str, bytes]]:
        """
        Итератор (topic, payload). Совместим с aiomqtt 1.x и asyncio-mqtt 0.16.x.
        """
        assert self.client is not None
        ctx = getattr(self.client, "unfiltered_messages", None)
        if ctx is None:
            # aiomqtt >=1.0: используется .messages() для всех сообщений
            ctx = getattr(self.client, "messages", None)
        if ctx is None:
            raise RuntimeError("MQTT client does not expose messages/unfiltered_messages context manager")

        async with ctx() as messages:
            while True:
                msg = await messages.__anext__()
                # у обоих либ есть .topic и .payload
                yield msg.topic, msg.payload
