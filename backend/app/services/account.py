"""04-settings Control 계층 — 계정 설정(비밀번호 변경, 회원 탈퇴)."""

from sqlalchemy.orm import Session

from app.models import User
from app.services.auth import hash_password, verify_password


class CurrentPasswordIncorrectError(Exception):
    """04-settings.md 3장 — 현재 비밀번호 검증에 실패한 경우."""


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise CurrentPasswordIncorrectError()
    user.password_hash = hash_password(new_password)
    db.commit()


def delete_account(db: Session, user: User) -> None:
    """01-erd.md 3.4절 삭제 정책 — users 행 삭제, 하위 전 테이블 ON DELETE CASCADE로 함께 삭제."""
    db.delete(user)
    db.commit()
