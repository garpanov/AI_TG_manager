from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")
    rabbitmq_url: str = "amqp://ai_manager:development@rabbitmq/"
    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.5-flash-lite"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
