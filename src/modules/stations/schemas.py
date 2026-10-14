from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from src.modules.stations.connector_status import (
    ConnectorStatusGroup,
    connector_status_group,
)
from src.modules.stations.timezones import (
    DEFAULT_STATION_TIMEZONE,
    validate_station_timezone,
)


class StationCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=150)
    address: str = Field(min_length=1, max_length=500)
    timezone: str = Field(default=DEFAULT_STATION_TIMEZONE, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return validate_station_timezone(value)

    latitude: Decimal = Field(
        ge=Decimal(-90),
        le=Decimal(90),
    )
    longitude: Decimal = Field(
        ge=Decimal(-180),
        le=Decimal(180),
    )


class StationUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str | None = Field(default=None, min_length=1, max_length=150)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return validate_station_timezone(value) if value is not None else None

    latitude: Decimal | None = Field(
        default=None,
        ge=Decimal(-90),
        le=Decimal(90),
    )
    longitude: Decimal | None = Field(
        default=None,
        ge=Decimal(-180),
        le=Decimal(180),
    )

    @model_validator(mode="after")
    def reject_empty_or_null_payload(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Payload cập nhật không được rỗng")

        if any(
            getattr(self, field_name) is None for field_name in self.model_fields_set
        ):
            raise ValueError("Trường cập nhật không được null")

        return self


class StationListQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: Literal["inactive", "active", "suspended", "blocked"] | None = None
    search: str | None = Field(default=None, max_length=100)


class StationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    address: str
    photo_url: str | None = None
    latitude: float
    longitude: float
    status: str
    timezone: str
    created_at: datetime
    updated_at: datetime


class StationListResponse(BaseModel):
    items: list[StationResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class ChargePointCodeAvailabilityQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    code: str = Field(min_length=1, max_length=64)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip()


class ChargePointCodeAvailabilityResponse(BaseModel):
    code: str
    available: bool


class ChargePointListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ConnectorConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connector_number: int = Field(ge=1, le=4)
    connector_type: str | None = Field(default=None, min_length=1, max_length=50)
    current_type: Literal["AC", "DC"] | None = None
    max_power_kw: Decimal | None = Field(
        default=None, gt=0, max_digits=8, decimal_places=3
    )
    voltage: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)
    amperage: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)


class ChargePointCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    code: str = Field(min_length=1, max_length=64)
    connector_count: int = Field(ge=1, le=4)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    connectors: list[ConnectorConfiguration] | None = None

    @model_validator(mode="after")
    def validate_connectors(self) -> Self:
        if self.connectors is not None:
            numbers = [item.connector_number for item in self.connectors]
            if sorted(numbers) != list(range(1, self.connector_count + 1)):
                raise ValueError("Cấu hình phải có đủ từng đầu nối, không trùng số")
        return self

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip()


class ChargePointUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    connectors: list[ConnectorConfiguration] | None = Field(
        default=None, min_length=1, max_length=4
    )

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Payload cập nhật không được rỗng")
        if "code" in self.model_fields_set and self.code is None:
            raise ValueError("Mã trụ không được null")
        if "connectors" in self.model_fields_set and self.connectors is None:
            raise ValueError("Cấu hình đầu nối không được null")
        numbers = [item.connector_number for item in self.connectors or []]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Số đầu nối không được trùng")
        return self

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_number: int
    status: str
    connector_type: str | None = None
    current_type: str | None = None
    max_power_kw: Decimal | None = None
    voltage: Decimal | None = None
    amperage: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_group(self) -> ConnectorStatusGroup:
        return connector_status_group(self.status)


class ChargePointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    station_id: UUID
    code: str
    name: str | None
    vendor: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    status: str
    code_locked_at: datetime | None = None
    connectors: list[ConnectorResponse]
    created_at: datetime
    updated_at: datetime


class ChargePointListResponse(BaseModel):
    items: list[ChargePointResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
