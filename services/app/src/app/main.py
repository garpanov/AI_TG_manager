import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from redis.asyncio import Redis

from .config import get_settings
from .handlers import router
from .outbox import run_publisher
from .results import consume_results


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        )
    )
    bot = Bot(settings.bot_token)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dispatcher = Dispatcher(redis=redis)
    dispatcher.include_router(router)
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(run_publisher())
            group.create_task(consume_results(bot, redis))
            group.create_task(dispatcher.start_polling(bot))
    finally:
        await redis.aclose()
        await bot.session.close()


def run() -> None:
    asyncio.run(main())
