"""04-settings 요청/응답 DTO — 계정 설정."""

from pydantic import BaseModel, field_validator

from app.schemas.auth import validate_password_rules


class AccountResponse(BaseModel):
    email: str
    role: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        # 가입과 같은 규칙이어야 한다 — 한쪽에만 상한이 있으면 변경으로 우회된다.
        return validate_password_rules(value)
