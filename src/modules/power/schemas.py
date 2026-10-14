from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectorSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    rated_kw: Decimal = Field(
        gt=0, le=Decimal("99999.999"), decimal_places=3, allow_inf_nan=False
    )

    @field_validator("rated_kw", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Power cannot be boolean")  # noqa: TRY004 - Pydantic needs ValueError for 422.
        return value


class PowerSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0, strict=True)
    limit_kw: Decimal = Field(
        gt=0, le=Decimal("999999.999"), decimal_places=3, allow_inf_nan=False
    )
    connectors: list[ConnectorSetting] = Field(min_length=1, max_length=200)
    zero_limit_verified: bool = Field(default=False, strict=True)
    offline_retention_verified: bool = Field(default=False, strict=True)
    verification_note: str = Field(default="", max_length=500)

    @field_validator("limit_kw", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Power cannot be boolean")  # noqa: TRY004 - Pydantic needs ValueError for 422.
        return value


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
