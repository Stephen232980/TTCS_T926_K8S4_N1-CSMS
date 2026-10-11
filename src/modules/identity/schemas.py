from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    status: Literal["authenticated"] = "authenticated"


class CurrentUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    roles: list[str]
    default_role: str | None = None


class DefaultRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "operator", "station_owner", "driver", "accountant"]
