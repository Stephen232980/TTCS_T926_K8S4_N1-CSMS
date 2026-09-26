from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    auth_max_failed_attempts: int = Field(default=5, gt=0)
    auth_lock_seconds: int = Field(default=900, gt=0)
    auth_session_ttl_seconds: int = Field(default=86_400, gt=0)
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
