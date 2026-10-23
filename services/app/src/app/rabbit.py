import json
from collections.abc import AsyncIterator

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

EXCHANGE = "ai-manager"
TRANSCRIPTION_REQUEST = "transcription.request.v1"
TRANSCRIPTION_FAILED = "transcription.failed.v1"
AI_REQUEST = "ai.request.v1"
AI_RESULT = "ai.result.v1"
ANALYSIS_REQUEST = "analysis.request.v1"
ANALYSIS_RESULT = "analysis.result.v1"


async def open_channel(
    url: str,
) -> AsyncIterator[
    tuple[
        aio_pika.abc.AbstractRobustConnection,
        aio_pika.abc.AbstractChannel,
        aio_pika.abc.AbstractExchange,
    ]
]:
    connection = await aio_pika.connect_robust(url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=8)
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
    yield connection, channel, exchange


def persistent_message(payload: dict, message_id: str) -> Message:
    return Message(
        body=json.dumps(payload, separators=(",", ":")).encode(),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
        message_id=message_id,
    )
