from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    database_pool_size: int = Field(default=20, ge=1, le=100)
    wallet_manual_topup_max_vnd: int = Field(default=10_000_000, gt=0, le=2**63 - 1)
    wallet_reconciliation_interval_seconds: int = Field(default=300, gt=0)

    auth_max_failed_attempts: int = Field(default=5, gt=0)
    auth_lock_seconds: int = Field(default=900, gt=0)
    auth_session_ttl_seconds: int = Field(default=86_400, gt=0)
    auth_cookie_secure: bool = False
    ocpp_heartbeat_interval_seconds: int = Field(default=60, gt=0)
    ocpp_reply_cleanup_interval_seconds: int = Field(default=3600, gt=0)
    charging_abnormal_offline_seconds: int = Field(default=21600, gt=0)
    charging_recovery_scan_interval_seconds: int = Field(default=60, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
