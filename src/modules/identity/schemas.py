from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    status: Literal["authenticated"] = "authenticated"
