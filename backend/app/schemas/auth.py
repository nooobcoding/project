"""01-auth 요청/응답 DTO (Boundary 계층 계약, models와 별개로 유지)."""

import re

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")

# bcrypt는 72바이트를 넘는 부분을 **조용히 잘라서** 해시한다(bcrypt 3.2.2 실측). 그대로 받으면
# 72바이트 이후만 다른 비밀번호로도 로그인되고, 한글은 글자당 3바이트라 24자 뒤로는 전부
# 무시된다 — 사용자는 30자 비밀번호를 설정했다고 믿지만 실제로는 앞 24자만 쓰인다.
_PASSWORD_MAX_BYTES = 72


def validate_password_rules(value: str) -> str:
    """가입·비밀번호 변경 공용 규칙 (01-auth.md 4장, 04-settings.md 2-A).

    로그인 요청에는 걸지 않는다 — 이 상한이 생기기 전에 긴 비밀번호로 가입한 유저가 잠긴다.
    """
    if not _PASSWORD_PATTERN.match(value):
        raise ValueError("비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다.")
    if len(value.encode("utf-8")) > _PASSWORD_MAX_BYTES:
        raise ValueError("비밀번호가 너무 깁니다. (영문·숫자 72자, 한글 24자 이내)")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_rules(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmailAvailabilityResponse(BaseModel):
    available: bool
