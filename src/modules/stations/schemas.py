from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StationCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=150)
    address: str = Field(min_length=1, max_length=500)
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
    status: Literal["inactive", "active"] | None = None
    search: str | None = Field(default=None, max_length=100)


class StationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    address: str
    latitude: float
    longitude: float
    status: str
    created_at: datetime
    updated_at: datetime


class StationListResponse(BaseModel):
    items: list[StationResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
