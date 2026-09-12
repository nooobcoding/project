"""04-settings Control 계층 — 계정 설정(비밀번호 변경, 회원 탈퇴)."""

from sqlalchemy.orm import Session

from app.models import User
from app.services.auth import hash_password, verify_password


class CurrentPasswordIncorrectError(Exception):
    """04-settings.md 3장 — 현재 비밀번호 검증에 실패한 경우."""


class NewPasswordSameAsCurrentError(Exception):
    """04-settings.md 3장 — 새 비밀번호가 현재 비밀번호와 같은 경우."""


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise CurrentPasswordIncorrectError()
    # current_password가 이미 위에서 실제 현재 비밀번호로 확인됐으므로, 두 평문을 그대로
    # 비교하는 것으로 "새 비밀번호 == 현재 비밀번호" 판정이 된다 (해시 재계산 불필요).
    if new_password == current_password:
        raise NewPasswordSameAsCurrentError()
    user.password_hash = hash_password(new_password)
    db.commit()


def delete_account(db: Session, user: User) -> None:
    """01-erd.md 3.4절 삭제 정책 — users 행 삭제, 하위 전 테이블 ON DELETE CASCADE로 함께 삭제."""
    db.delete(user)
    db.commit()
