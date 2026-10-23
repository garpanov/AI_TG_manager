import asyncio
from logging.config import fileConfig

from alembic import context
from app.config import get_settings
from app.models import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_sync_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(run_sync_migrations)
    await engine.dispose()


asyncio.run(run_migrations())
