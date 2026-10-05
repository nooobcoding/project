"""계정 정지와 관리자 권한의 인증 경계 (확장판 05-admin.md 2.2절, 6장 검증 1·2)."""

import pytest
from sqlalchemy import update

from app.database import session_scope
from app.models import User
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE, STATUS_SUSPENDED
from app.services.auth import create_access_token, hash_password
from tests.conftest import requires_db
from tests.test_api_auth import PROTECTED_ENDPOINTS

pytestmark = requires_db

SUSPENDED = "정지된 계정입니다. 관리자에게 문의해주세요."


def _set(user_id: int, **values) -> None:
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(**values))


def _email(user_id: int) -> str:
    with session_scope() as db:
        return db.get(User, user_id).email


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_suspension_blocks_an_already_issued_token_immediately(client, test_user, method, path):
    """정지 **전에** 받은 토큰으로도 즉시 막힌다 — 토큰 만료(24시간)를 기다리지 않는다.

    토큰만 검사했다면 이 토큰은 서명도 만료도 멀쩡하므로 하루 동안 계속 통과한다.
    """
    token = create_access_token(test_user)
    _set(test_user, status=STATUS_SUSPENDED)

    response = client.request(method, path, headers={"Authorization": f"Bearer {token}"}, json={})

    assert response.status_code == 403, f"{method} {path} 가 정지된 계정을 통과시켰다"
    assert response.json()["detail"] == SUSPENDED


def test_reactivation_restores_the_same_token(client, test_user):
    token = create_access_token(test_user)
    headers = {"Authorization": f"Bearer {token}"}
    _set(test_user, status=STATUS_SUSPENDED)
    assert client.get("/api/account", headers=headers).status_code == 403

    _set(test_user, status=STATUS_ACTIVE)
    assert client.get("/api/account", headers=headers).status_code == 200


def test_suspended_account_cannot_log_in(client, make_user):
    password = "correct-horse-battery"
    user_id = make_user(password_hash=hash_password(password))
    _set(user_id, status=STATUS_SUSPENDED)

    response = client.post("/api/auth/login", json={"email": _email(user_id), "password": password})

    assert response.status_code == 403
    assert response.json()["detail"] == SUSPENDED
    assert "access_token" not in response.json()


def test_suspension_is_not_revealed_to_a_wrong_password(client, make_user):
    """비밀번호가 틀리면 정지 여부를 알려주지 않는다 — 남의 이메일로 계정 상태를 떠볼 수 없게."""
    user_id = make_user(password_hash=hash_password("right-password"))
    _set(user_id, status=STATUS_SUSPENDED)

    response = client.post("/api/auth/login", json={"email": _email(user_id), "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "이메일 또는 비밀번호가 올바르지 않습니다."


def test_account_exposes_role(client, test_user, auth_headers):
    assert client.get("/api/account", headers=auth_headers).json()["role"] == "user"

    _set(test_user, role=ROLE_ADMIN)
    assert client.get("/api/account", headers=auth_headers).json()["role"] == "admin"
