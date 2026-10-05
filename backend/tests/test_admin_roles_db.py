"""관리자 권한 모델 — 스키마 기본값과 CLI 권한 부여·회수 (확장판 05-admin.md 2.1절)."""

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.database import get_engine, session_scope
from app.models import AuditLog, User
from app.models.user import ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE
from app.services.admin import LastAdminError, UserNotFoundError, set_role
from tests.conftest import requires_db

pytestmark = requires_db


def _email(user_id: int) -> str:
    with session_scope() as db:
        return db.get(User, user_id).email


def _role(user_id: int) -> str:
    with session_scope() as db:
        return db.get(User, user_id).role


def test_new_user_defaults_to_active_user(test_user):
    """마이그레이션 이전에 가입한 유저도, 새로 가입한 유저도 일반·활성으로 시작한다."""
    with session_scope() as db:
        user = db.get(User, test_user)
        assert (user.role, user.status) == (ROLE_USER, STATUS_ACTIVE)


def test_db_rejects_unknown_role_and_status(test_user):
    """CHECK 제약 — 앱 코드를 우회한 오타도 DB가 막는다."""
    for column, value in (("role", "superuser"), ("status", "banned")):
        with pytest.raises(Exception, match="ck_users_"):
            with session_scope() as db:
                db.execute(text(f"UPDATE users SET {column} = :v WHERE id = :id"), {"v": value, "id": test_user})


def test_grant_and_revoke_admin_leave_audit_trail(make_user):
    first, second = make_user(), make_user()
    with session_scope() as db:
        set_role(db, _email(first), ROLE_ADMIN)
        set_role(db, _email(second), ROLE_ADMIN)
    assert _role(first) == ROLE_ADMIN

    with session_scope() as db:
        set_role(db, _email(first), ROLE_USER)  # second가 남으므로 허용
    assert _role(first) == ROLE_USER

    with session_scope() as db:
        logs = db.execute(
            select(AuditLog.action, AuditLog.actor_user_id, AuditLog.detail)
            .where(AuditLog.target_type == "user", AuditLog.target_id == first)
            .order_by(AuditLog.id)
        ).all()
    assert [log.action for log in logs] == ["role.grant", "role.revoke"]
    assert all(log.actor_user_id is None for log in logs)  # CLI에는 로그인한 행위자가 없다
    assert logs[1].detail == {"before": ROLE_ADMIN, "after": ROLE_USER}


def test_set_role_is_idempotent_without_extra_audit(test_user):
    with session_scope() as db:
        set_role(db, _email(test_user), ROLE_USER)
    with session_scope() as db:
        count = db.execute(
            select(AuditLog).where(AuditLog.target_type == "user", AuditLog.target_id == test_user)
        ).all()
    assert count == []


def test_set_role_unknown_email():
    with pytest.raises(UserNotFoundError):
        with session_scope() as db:
            set_role(db, "nobody-here@example.com", ROLE_ADMIN)


def test_last_admin_cannot_be_revoked(test_user):
    """관리자가 0명이 되면 관리자 화면에 들어갈 사람이 없다.

    개발 DB에는 진짜 관리자가 있을 수 있어서 "관리자가 나 하나뿐"인 상황을 그냥은 만들 수
    없다. 바깥 트랜잭션 안의 SAVEPOINT에서 다른 관리자를 전부 내리고 검사한 뒤 **바깥째
    롤백한다** — 개발 데이터는 건드리지 않는다.
    """
    email = _email(test_user)
    with get_engine().connect() as connection:
        outer = connection.begin()
        try:
            db = Session(bind=connection, join_transaction_mode="create_savepoint")
            db.execute(update(User).where(User.role == ROLE_ADMIN).values(role=ROLE_USER))
            set_role(db, email, ROLE_ADMIN)

            with pytest.raises(LastAdminError):
                set_role(db, email, ROLE_USER)
            db.rollback()
            assert db.get(User, test_user).role == ROLE_ADMIN
            db.close()
        finally:
            outer.rollback()
    assert _role(test_user) == ROLE_USER  # 바깥 롤백으로 원상복구됐다
