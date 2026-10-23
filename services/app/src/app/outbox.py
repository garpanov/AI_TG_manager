import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from .config import get_settings
from .db import session_factory
from .models import OutboxJob
from .rabbit import open_channel, persistent_message

log = structlog.get_logger()


async def publish_once(exchange) -> int:
    published = 0
    async with session_factory() as session, session.begin():
        jobs = list(
            await session.scalars(
                select(OutboxJob)
                .where(OutboxJob.published_at.is_(None))
                .order_by(OutboxJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(50)
            )
        )
        for job in jobs:
            job.attempts += 1
            try:
                await exchange.publish(
                    persistent_message(job.payload, str(job.id)),
                    routing_key=job.routing_key,
                    mandatory=True,
                )
                job.published_at = datetime.now(UTC)
                job.last_error = None
                published += 1
            except Exception as error:
                job.last_error = str(error)[:2000]
                log.exception(
                    "outbox_publish_failed", job_id=str(job.id), routing_key=job.routing_key
                )
    return published


async def run_publisher() -> None:
    settings = get_settings()
    async for connection, _channel, exchange in open_channel(settings.rabbitmq_url):
        try:
            while True:
                count = await publish_once(exchange)
                await asyncio.sleep(0.1 if count else 1)
        finally:
            await connection.close()
