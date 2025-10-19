from __future__ import annotations
import asyncio
import logging
from typing import AsyncIterator, Tuple

from asyncio_mqtt import Client, MqttError, Will  # type: ignore

logger = logging.getLogger("mqtt")

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
        will = Will(self.lwt_topic, payload="offline", qos=1, retain=True)
        return Client(self.host, port=self.port, username=self.username, password=self.password, will=will)

    async def connect(self) -> None:
        self.client = self._make_client()
        await self.client.connect()
        await self.client.publish(self.lwt_topic, "online", qos=1, retain=True)
        logger.info("MQTT connected to %s:%d", self.host, self.port)

    async def disconnect(self) -> None:
        if self.client:
            try:
                await self.client.publish(self.lwt_topic, "offline", qos=1, retain=True)
                await self.client.disconnect()
            finally:
                self.client = None

    async def publish(self, topic: str, payload: str, *, qos: int = 0, retain: bool = False) -> None:
        assert self.client is not None
        await self.client.publish(topic, payload, qos=qos, retain=retain)

    async def subscribe(self, topic: str) -> None:
        assert self.client is not None
        await self.client.subscribe(topic)

    async def unfiltered_messages(self) -> AsyncIterator[Tuple[str, bytes]]:
        assert self.client is not None
        async with self.client.unfiltered_messages() as messages:
            while True:
                msg = await messages.__anext__()  # (topic, payload,...)
                yield msg.topic, msg.payload
