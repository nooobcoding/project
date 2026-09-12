"""04-settings 계정 서비스(비밀번호 변경) 검증. DB 없이 순수 로직만 본다.

`change_password`는 전달받은 `User` 객체 하나의 필드만 바꾸고 `db.commit()`을 부를 뿐이라
(services/account.py), 실제 세션 대신 커밋 여부만 기록하는 가짜 세션으로 충분하다.
"""

import pytest

from app.models import User
from app.services.account import (
    CurrentPasswordIncorrectError,
    NewPasswordSameAsCurrentError,
    change_password,
)
from app.services.auth import hash_password, verify_password


class _FakeSession:
    """`change_password`가 쓰는 `commit()` 하나만 흉내 낸다."""

    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _make_user(password: str) -> User:
    return User(id=1, email="test@example.com", password_hash=hash_password(password))


def test_change_password_succeeds_with_correct_current_password():
    user = _make_user("OldPass123")
    db = _FakeSession()

    change_password(db, user, "OldPass123", "NewPass456")

    assert verify_password("NewPass456", user.password_hash)
    assert db.committed


def test_change_password_rejects_wrong_current_password():
    user = _make_user("OldPass123")
    db = _FakeSession()

    with pytest.raises(CurrentPasswordIncorrectError):
        change_password(db, user, "WrongPass000", "NewPass456")

    # 실패 시 비밀번호도 바뀌지 않고 커밋도 일어나지 않아야 한다.
    assert verify_password("OldPass123", user.password_hash)
    assert not db.committed


def test_change_password_rejects_new_password_same_as_current():
    """현재 비밀번호와 같은 값으로는 "변경"할 수 없다."""
    user = _make_user("OldPass123")
    db = _FakeSession()

    with pytest.raises(NewPasswordSameAsCurrentError):
        change_password(db, user, "OldPass123", "OldPass123")

    assert verify_password("OldPass123", user.password_hash)
    assert not db.committed
