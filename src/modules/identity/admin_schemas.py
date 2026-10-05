from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

RoleCode = Literal["admin", "operator", "station_owner", "driver", "accountant"]
AccountStatus = Literal[
    "active", "suspended", "deactivated", "pending_deletion", "anonymized"
]


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=1024)
    roles: list[RoleCode] = Field(min_length=1, max_length=5)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[RoleCode]) -> list[RoleCode]:
        if len(value) != len(set(value)):
            raise ValueError("Không lặp lại vai trò")
        return sorted(value)


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime
    roles: list[RoleCode] | None = Field(default=None, min_length=1, max_length=5)
    status: Literal["active", "suspended"] | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if self.roles is None and self.status is None:
            raise ValueError("Cần chọn vai trò hoặc trạng thái")
        if "roles" in self.model_fields_set and self.roles is None:
            raise ValueError("Vai trò không được null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Trạng thái không được null")
        if self.roles is not None:
            self.roles = AccountCreateRequest.unique_roles(self.roles)
        return self


class AccountResponse(BaseModel):
    id: UUID
    email: str
    roles: list[RoleCode]
    status: AccountStatus
    created_at: datetime
    updated_at: datetime


class AccountListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str | None = Field(default=None, max_length=320)
    role: RoleCode | None = None
    status: AccountStatus | None = None


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class RoleResponse(BaseModel):
    code: RoleCode
    name: str
