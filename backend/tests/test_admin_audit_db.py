"""감사 로그 조회와 보존 (확장판 05-admin.md 4장, 6장 검증 5)."""

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database import get_engine, session_scope
from app.models import User
from app.models.user import ROLE_ADMIN, ROLE_USER
from app.services.account import delete_account
from app.services.admin import LastAdminError
from app.services.auth import create_access_token
from tests.conftest import requires_db

pytestmark = requires_db


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _make_admin(make_user) -> int:
    user_id = make_user()
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(role=ROLE_ADMIN))
    return user_id


def _logs(client, headers, **params) -> dict:
    response = client.get("/api/admin/audit-logs", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _suspend(client, admin_id: int, user_id: int, status: str = "suspended") -> None:
    response = client.patch(
        f"/api/admin/users/{user_id}/status", headers=_headers(admin_id), json={"status": status}
    )
    assert response.status_code == 200, response.text


def test_logs_are_listed_newest_first_and_filterable(client, make_user, test_user):
    admin_id = _make_admin(make_user)
    _suspend(client, admin_id, test_user)
    _suspend(client, admin_id, test_user, "active")
    headers = _headers(admin_id)

    body = _logs(client, headers, target_type="user", target_id=test_user)
    assert body["total"] == 2
    assert [item["action"] for item in body["items"]] == ["user.unsuspend", "user.suspend"]
    assert body["items"][0]["actor_user_id"] == admin_id

    only_suspend = _logs(client, headers, action="user.suspend", target_id=test_user)["items"]
    assert [item["action"] for item in only_suspend] == ["user.suspend"]

    mine = _logs(client, headers, actor_user_id=admin_id)
    assert mine["total"] == 2

    page = _logs(client, headers, actor_user_id=admin_id, page_size=1, page=2)
    assert [item["action"] for item in page["items"]] == ["user.suspend"]


def test_log_survives_target_deleting_their_account(client, make_user):
    """대상 유저가 탈퇴해도 기록은 남는다 — target_id에 FK를 걸지 않은 이유다."""
    admin_id = _make_admin(make_user)
    target = make_user()
    _suspend(client, admin_id, target)
    _suspend(client, admin_id, target, "active")

    assert client.delete("/api/account", headers=_headers(target)).status_code == 204

    items = _logs(client, _headers(admin_id), target_type="user", target_id=target)["items"]
    assert [item["action"] for item in items] == ["user.unsuspend", "user.suspend"]


def test_log_survives_the_acting_admin_leaving(client, make_user, test_user):
    """행위한 관리자가 탈퇴해도 기록은 남고, 누가 했는지는 이메일로 남는다.

    설계 초안대로 그냥 FK를 걸었다면 CASCADE면 기록이 같이 지워지고, RESTRICT면 탈퇴가 막힌다.
    """
    leaving = _make_admin(make_user)
    staying = _make_admin(make_user)  # 마지막 관리자는 탈퇴할 수 없으므로 한 명 더 둔다
    with session_scope() as db:
        leaving_email = db.get(User, leaving).email
    _suspend(client, leaving, test_user)

    assert client.delete("/api/account", headers=_headers(leaving)).status_code == 204

    [item] = _logs(client, _headers(staying), target_type="user", target_id=test_user)["items"]
    assert item["actor_user_id"] is None
    assert item["actor_email"] == leaving_email


def test_last_admin_cannot_delete_their_account(make_user):
    """탈퇴는 권한 회수와 결과가 같다 — CLI 회수만 막고 탈퇴를 열어 두면 규칙이 새어 나간다.

    개발 DB의 실제 관리자를 건드리지 않으려고 SAVEPOINT 안에서 "관리자가 나 하나뿐"을 만들고
    바깥째 롤백한다 (test_admin_roles_db.py와 같은 방식).
    """
    admin_id = make_user()
    with get_engine().connect() as connection:
        outer = connection.begin()
        try:
            db = Session(bind=connection, join_transaction_mode="create_savepoint")
            db.execute(update(User).where(User.role == ROLE_ADMIN).values(role=ROLE_USER))
            db.execute(update(User).where(User.id == admin_id).values(role=ROLE_ADMIN))
            admin = db.get(User, admin_id)

            with pytest.raises(LastAdminError):
                delete_account(db, admin)
            db.rollback()
            assert db.get(User, admin_id) is not None
            db.close()
        finally:
            outer.rollback()


def test_last_admin_deletion_is_a_409_with_the_documented_message(client, make_user, monkeypatch):
    """라우터가 LastAdminError를 문서의 문구로 바꾸는지. 관리자 수 판정은 위 테스트가 본다."""
    admin_id = _make_admin(make_user)

    def refuse(db, user):
        raise LastAdminError()

    monkeypatch.setattr("app.services.account.ensure_not_last_admin", refuse)

    response = client.delete("/api/account", headers=_headers(admin_id))

    assert response.status_code == 409
    assert response.json()["detail"] == "관리자가 최소 1명은 있어야 합니다."
    with session_scope() as db:
        assert db.get(User, admin_id) is not None


def test_regular_user_can_still_delete_their_account(client, make_user):
    """관리자 규칙이 일반 유저의 탈퇴를 막지 않는다 — 관리자가 0명인 개발 DB에서도."""
    user_id = make_user()

    assert client.delete("/api/account", headers=_headers(user_id)).status_code == 204
