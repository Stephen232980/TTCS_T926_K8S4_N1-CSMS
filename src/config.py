from functools import lru_cache
from typing import Literal, Self

from pydantic import (
    EmailStr,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    reservation_command_timeout_seconds: float = Field(default=5, gt=0, le=30)
    alert_offline_grace_seconds: int = Field(default=300, ge=60, le=86400)
    alert_error_window_seconds: int = Field(default=600, ge=60, le=86400)
    alert_error_threshold: int = Field(default=3, ge=2, le=1000)
    alert_scan_interval_seconds: int = Field(default=15, ge=1, le=15)
    alert_smtp_enabled: bool = False
    alert_smtp_host: str = ""
    alert_smtp_port: int = Field(default=587, ge=1, le=65535)
    alert_smtp_security: Literal["starttls", "ssl", "plain"] = "starttls"
    alert_smtp_from: EmailStr | None = None
    alert_email_recipients: list[EmailStr] = Field(default_factory=list)
    alert_smtp_username: str = ""
    alert_smtp_password: SecretStr | None = Field(default=None, repr=False)
    alert_smtp_timeout_seconds: float = Field(default=5, gt=0, le=15)
    alert_email_max_attempts: int = Field(default=6, ge=1, le=20)

    @field_validator("alert_smtp_from", "alert_smtp_password", mode="before")
    @classmethod
    def empty_alert_smtp_values(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_alert_smtp(self) -> Self:
        if self.alert_smtp_enabled and not (
            self.alert_smtp_host
            and self.alert_smtp_from
            and self.alert_email_recipients
        ):
            raise ValueError("Enabled alert SMTP requires host, sender and recipients")
        if bool(self.alert_smtp_username) != bool(self.alert_smtp_password):
            raise ValueError("SMTP username and password must be configured together")
        return self

    database_url: str = ""
    database_pool_size: int = Field(default=20, ge=1, le=100)
    power_command_timeout_seconds: float = Field(default=5, gt=0, le=30)
    wallet_manual_topup_max_vnd: int = Field(default=10_000_000, gt=0, le=2**63 - 1)
    wallet_topup_min_vnd: int = Field(default=10_000, gt=0, le=2**63 - 1)
    wallet_topup_max_vnd: int = Field(default=5_000_000, gt=0, le=2**63 - 1)
    wallet_reconciliation_interval_seconds: int = Field(default=300, gt=0)
    charging_minimum_kwh: int = Field(default=5, gt=0)
    wallet_reserve_vnd: int = Field(default=10_000, ge=0, le=2**63 - 1)
    # Enable only for a fleet whose Available notification proves EV unplugging.
    billing_available_confirms_unplug: bool = False
    # Explicit opt-in; never expose a simulator-only command in normal deployments.
    demo_driver_unplug_enabled: bool = False

    payment_gateway: Literal["disabled", "fake", "sandbox"] = "disabled"
    payment_webhook_secret: SecretStr | None = Field(default=None, repr=False)
    payment_return_url: HttpUrl = HttpUrl("http://localhost:5173/wallet/topup/return")
    payment_fake_base_url: HttpUrl = HttpUrl("http://localhost:8000")
    vnpay_tmn_code: str = ""
    vnpay_query_ip: str = ""

    @field_validator("vnpay_query_ip")
    @classmethod
    def validate_query_ip(cls, value: str) -> str:
        from ipaddress import ip_address

        return str(ip_address(value)) if value else ""

    vnpay_return_url: HttpUrl | None = None
    vnpay_payment_url: Literal["https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"] = (
        "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
    )
    vnpay_expiry_minutes: int = Field(default=15, ge=1, le=60)

    @field_validator("vnpay_return_url")
    @classmethod
    def validate_vnpay_return(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (
            value.scheme != "https"
            or value.username is not None
            or value.password is not None
            or value.fragment
            or value.query
        ):
            raise ValueError("VNPAY return must be a plain HTTPS URL")
        return value

    @field_validator("vnpay_tmn_code")
    @classmethod
    def validate_vnpay_merchant(cls, value: str) -> str:
        if value and (len(value) != 8 or not value.isascii() or not value.isalnum()):
            raise ValueError("VNPAY merchant code must contain 8 ASCII letters/digits")
        return value

    @field_validator("payment_webhook_secret", mode="before")
    @classmethod
    def empty_payment_secret(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("payment_return_url", "payment_fake_base_url")
    @classmethod
    def validate_payment_return_url(cls, value: HttpUrl) -> HttpUrl:
        if value.username is not None or value.password is not None or value.fragment:
            raise ValueError(
                "payment return URL must not contain credentials or fragment"
            )
        return value

    @model_validator(mode="after")
    def validate_payment_configuration(self) -> Self:
        if self.payment_gateway != "disabled" and (
            self.payment_webhook_secret is None
            or not self.payment_webhook_secret.get_secret_value().strip()
        ):
            raise ValueError("enabled payment gateway requires PAYMENT_WEBHOOK_SECRET")
        if self.wallet_topup_min_vnd > self.wallet_topup_max_vnd:
            raise ValueError("wallet topup minimum must not exceed maximum")
        return self

    auth_max_failed_attempts: int = Field(default=5, gt=0)
    auth_lock_seconds: int = Field(default=900, gt=0)
    auth_session_ttl_seconds: int = Field(default=86_400, gt=0)
    auth_cookie_secure: bool = False
    ocpp_heartbeat_interval_seconds: int = Field(default=60, gt=0)
    ocpp_reply_cleanup_interval_seconds: int = Field(default=3600, gt=0)
    charging_abnormal_offline_seconds: int = Field(default=21600, gt=0)
    charging_recovery_scan_interval_seconds: int = Field(default=60, gt=0)
    charging_closure_scan_interval_seconds: int = Field(default=60, gt=0)
    legacy_settlement_cutoff: str = ""

    retention_cleanup_interval_seconds: int = Field(default=86_400, gt=0)
    retention_login_attempts_days: int = Field(default=1, ge=1)
    retention_expired_sessions_days: int = Field(default=30, ge=1)
    retention_idempotency_days: int = Field(default=7, ge=1)
    retention_pending_messages_days: int = Field(default=7, ge=1)
    retention_telemetry_hours: int = Field(default=25, ge=1)
    retention_sent_alert_emails_days: int = Field(default=30, ge=1)
    retention_health_samples_days: int = Field(default=30, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
