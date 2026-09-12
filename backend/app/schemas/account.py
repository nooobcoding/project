"""04-settings 요청/응답 DTO — 계정 설정."""

import re

from pydantic import BaseModel, field_validator

# 01-auth.md 2-B와 동일 규칙 — backend/app/schemas/auth.py의 검증과 동기화되어야 한다
_PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


class AccountResponse(BaseModel):
    email: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError("비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다.")
        return value
