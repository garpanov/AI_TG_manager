from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOICE_", env_file=".env", extra="ignore")
    rabbitmq_url: str = "amqp://ai_manager:development@rabbitmq/"
    voice_directory: Path = Path("/var/lib/ai-manager/voice")
    whisper_binary: Path = Path("/usr/local/bin/whisper-cli")
    whisper_model: Path = Path("/models/ggml-small.bin")
    language: str = "auto"


@lru_cache
def get_settings() -> Settings:
    return Settings()
