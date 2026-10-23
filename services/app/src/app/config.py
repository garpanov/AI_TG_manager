from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    bot_token: str
    database_url: str = "postgresql+asyncpg://ai_manager:development@postgres/ai_manager"
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://ai_manager:development@rabbitmq/"
    voice_directory: Path = Path("/var/lib/ai-manager/voice")
    voice_whitelist: Annotated[frozenset[int], NoDecode] = frozenset()
    stars_price: int = Field(default=500, gt=0)
    log_level: str = "INFO"

    @field_validator("voice_whitelist", mode="before")
    @classmethod
    def parse_whitelist(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
