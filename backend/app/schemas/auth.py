"""01-auth 요청/응답 DTO (Boundary 계층 계약, models와 별개로 유지)."""

import re

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """01-auth.md 4장 — 8자 이상, 영문과 숫자를 포함해야 한다."""
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError("비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmailAvailabilityResponse(BaseModel):
    available: bool
