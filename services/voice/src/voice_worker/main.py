import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import aio_pika
import structlog
from ai_manager_contracts import AIRequest, MessageSource, TranscriptionFailed, TranscriptionRequest
from aio_pika import DeliveryMode, ExchangeType, Message

from .config import get_settings

log = structlog.get_logger()
EXCHANGE = "ai-manager"
REQUEST_KEY = "transcription.request.v1"
AI_KEY = "ai.request.v1"
FAILED_KEY = "transcription.failed.v1"


async def transcribe(source: Path) -> str:
    settings = get_settings()
    wav = source.with_suffix(".wav")
    try:
        converter = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            source,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-y",
            wav,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, convert_error = await converter.communicate()
        if converter.returncode:
            raise RuntimeError(convert_error.decode(errors="replace")[-2000:])
        process = await asyncio.create_subprocess_exec(
            settings.whisper_binary,
            "-m",
            settings.whisper_model,
            "-f",
            wav,
            "-l",
            settings.language,
            "-nt",
            "-np",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace")[-2000:])
        transcript = stdout.decode().strip()
        if not transcript:
            raise ValueError("whisper.cpp returned an empty transcript")
        return transcript
    finally:
        wav.unlink(missing_ok=True)


async def publish(exchange, routing_key: str, payload: dict, message_id: str) -> None:
    await exchange.publish(
        Message(
            json.dumps(payload, separators=(",", ":")).encode(),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
        ),
        routing_key=routing_key,
        mandatory=True,
    )


async def handle(message: aio_pika.IncomingMessage, exchange) -> None:
    request = TranscriptionRequest.model_validate_json(message.body)
    settings = get_settings()
    source = settings.voice_directory / request.audio_file
    try:
        transcript = await transcribe(source)
    except Exception:
        failure = TranscriptionFailed(
            job_id=request.job_id,
            user_id=request.user_id,
            chat_id=request.chat_id,
            reservation_id=request.reservation_id,
            quota_key=request.quota_key,
            local_date=request.local_date,
            reason="transcription",
            created_at=datetime.now(UTC),
        )
        await publish(exchange, FAILED_KEY, failure.model_dump(mode="json"), str(request.job_id))
        log.exception("transcription_failed", job_id=str(request.job_id))
        source.unlink(missing_ok=True)
        await message.ack()
        return
    ai_request = AIRequest(
        job_id=request.job_id,
        user_id=request.user_id,
        chat_id=request.chat_id,
        telegram_message_id=request.telegram_message_id,
        source=MessageSource.VOICE,
        text=transcript,
        timezone=request.timezone,
        local_datetime=request.local_datetime,
        active_tasks=request.active_tasks,
        created_at=datetime.now(UTC),
    )
    await publish(exchange, AI_KEY, ai_request.model_dump(mode="json"), str(request.job_id))
    source.unlink(missing_ok=True)
    await message.ack()


async def main() -> None:
    settings = get_settings()
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue("voice.transcription.v1", durable=True)
        await queue.bind(exchange, REQUEST_KEY)
        await queue.consume(lambda message: handle(message, exchange))
        await asyncio.Future()


def run() -> None:
    asyncio.run(main())
