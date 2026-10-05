"""라우터 계층 인증 — 01-auth.md.

저장소에 `TestClient`가 한 번도 쓰인 적이 없어서 **라우터 14개가 전부 미검증**이었다.
서비스 계층이 아무리 튼튼해도 라우터가 인증 의존성을 빠뜨리면 그대로 무방비가 되는데,
그 연결을 지금까지 아무도 확인한 적이 없다.

여기서는 "토큰이 없거나 못 믿을 토큰이면 들어올 수 없다"만 본다. 남의 자원 접근(IDOR)은
test_api_contract.py가 맡는다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings
from app.database import session_scope
from app.services.auth import create_access_token
from tests.conftest import requires_db

# 인증이 필요한 엔드포인트 — (method, path).
#
# 목록을 손으로 적어 두는 이유: 라우터를 훑어 자동 생성하면 "인증을 빠뜨린 엔드포인트"가
# 목록에서도 같이 빠져 테스트가 통과한다. 빠뜨림을 잡는 것이 목적이므로 기대값은 손으로 쓴다.
PROTECTED_ENDPOINTS = [
    ("GET", "/api/account"),
    ("PATCH", "/api/account/password"),
    ("DELETE", "/api/account"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/coins"),
    ("GET", "/api/coins/BTC/balance"),
    ("GET", "/api/coins/BTC/candles"),
    ("GET", "/api/dashboard/summary"),
    ("GET", "/api/dashboard/recent-trades"),
    ("GET", "/api/watchlist"),
    ("POST", "/api/watchlist"),
    ("DELETE", "/api/watchlist/BTC"),
    ("GET", "/api/notifications"),
    ("PATCH", "/api/notifications/1/read"),
    ("GET", "/api/settings/notifications"),
    ("PATCH", "/api/settings/notifications"),
    ("POST", "/api/orders"),
    ("GET", "/api/orders"),
    ("DELETE", "/api/orders/1"),
    ("GET", "/api/wallet/balance"),
    ("POST", "/api/wallet/deposit"),
    ("POST", "/api/wallet/withdraw"),
    ("GET", "/api/wallet/transactions"),
    ("POST", "/api/strategy-slots"),
    ("GET", "/api/strategy-slots"),
    ("PATCH", "/api/strategy-slots/1"),
    ("DELETE", "/api/strategy-slots/1"),
    ("GET", "/api/strategy-slots/1/signals"),
    ("POST", "/api/backtest/run"),
    ("POST", "/api/backtest/results"),
    ("GET", "/api/backtest/results"),
    ("GET", "/api/backtest/results/1"),
    ("DELETE", "/api/backtest/results/1"),
    ("GET", "/api/portfolio/summary"),
    ("GET", "/api/portfolio/holdings"),
    ("GET", "/api/portfolio/trades"),
    ("GET", "/api/portfolio/trades/export"),
    ("GET", "/api/portfolio/report"),
]


def _call(client, method: str, path: str, **kwargs):
    return client.request(method, path, **kwargs)


@requires_db
@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_missing_token(client, method, path):
    """토큰 없이 부르면 401이어야 한다 — 인증 의존성이 빠진 라우터를 여기서 잡는다."""
    response = _call(client, method, path, json={})

    assert response.status_code == 401, (
        f"{method} {path} 가 토큰 없이 {response.status_code}를 돌려줬다 "
        f"(인증 의존성이 빠졌을 수 있다)"
    )


@requires_db
@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_garbage_token(client, method, path):
    response = _call(
        client, method, path, headers={"Authorization": "Bearer not-a-jwt"}, json={}
    )

    assert response.status_code == 401, f"{method} {path} 가 엉터리 토큰을 통과시켰다"


@requires_db
def test_token_signed_with_wrong_secret_is_rejected(client):
    """서명이 다른 토큰은 거부한다 — 이게 뚫리면 누구나 남의 계정이 된다."""
    forged = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "공격자가-고른-다른-키",
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/api/account", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


@requires_db
def test_expired_token_is_rejected(client, test_user):
    expired = jwt.encode(
        {"sub": str(test_user), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/api/account", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


@requires_db
def test_token_without_subject_is_rejected(client):
    """`sub`가 없는 토큰 — 서명은 맞지만 누구인지 알 수 없으므로 거부해야 한다."""
    no_sub = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/api/account", headers={"Authorization": f"Bearer {no_sub}"})

    assert response.status_code == 401


@requires_db
def test_token_for_deleted_user_is_rejected(client, make_user):
    """유효한 토큰이라도 그 유저가 사라졌으면 거부한다 (탈퇴 후 남은 토큰)."""
    from sqlalchemy import text

    user_id = make_user()
    token = create_access_token(user_id)
    assert client.get("/api/account", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    with session_scope() as db:
        db.execute(text("DELETE FROM balances WHERE user_id = :uid"), {"uid": user_id})
        db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})

    response = client.get("/api/account", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


@requires_db
def test_valid_token_is_accepted(client, auth_headers):
    """음성 대조군 — 위 거부들이 "전부 401"이라서 통과하는 것이 아님을 보인다."""
    assert client.get("/api/account", headers=auth_headers).status_code == 200


@requires_db
def test_token_stays_valid_after_logout(client, auth_headers):
    """**의도된 동작** — 로그아웃은 서버 상태를 바꾸지 않는다 (01-auth.md 7장).

    Refresh Token도 토큰 블랙리스트도 없는 설계라, 로그아웃은 클라이언트가 토큰을 버리는
    것일 뿐이다. 나중에 누가 이걸 버그로 보고 "고치기" 전에, 알고 남겨둔 한계임을 여기에
    박아 둔다.
    """
    assert client.post("/api/auth/logout", headers=auth_headers).status_code == 200

    assert client.get("/api/account", headers=auth_headers).status_code == 200


# ---------------------------------------------------------------- 공개 엔드포인트


@requires_db
def test_check_email_does_not_require_token(client):
    """가입 화면의 이메일 중복 확인은 토큰 없이 닿아야 한다."""
    response = client.get("/api/auth/check-email", params={"email": "nobody@example.com"})

    assert response.status_code == 200


@requires_db
def test_login_issues_a_usable_token_without_any_prior_token(client, make_user):
    """로그인은 토큰 없이 닿을 수 있고, 받은 토큰이 실제로 보호 경로를 통과해야 한다.

    "토큰 없이 닿는다"를 401이 아닌지로만 보면 안 된다 — 로그인은 비밀번호가 틀려도 401을
    주므로 그 단언은 두 경우를 구분하지 못한다. 그래서 **성공하는** 로그인으로 확인한다.
    """
    from app.services.auth import hash_password

    password = "correct-horse-battery"
    user_id = make_user(password_hash=hash_password(password))
    with session_scope() as db:
        from app.models import User

        email = db.get(User, user_id).email

    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    token = login.json()["access_token"]
    assert client.get("/api/account", headers={"Authorization": f"Bearer {token}"}).status_code == 200


@requires_db
def test_login_with_wrong_password_is_rejected(client, make_user):
    from app.services.auth import hash_password

    user_id = make_user(password_hash=hash_password("right"))
    with session_scope() as db:
        from app.models import User

        email = db.get(User, user_id).email

    response = client.post("/api/auth/login", json={"email": email, "password": "wrong"})

    assert response.status_code == 401


# ---------------------------------------------------------------- 비밀번호 72바이트 상한


@pytest.fixture
def registered_emails():
    """API로 가입시킨 유저를 끝나면 지운다 (`make_user`를 거치지 않으므로 직접 정리)."""
    from sqlalchemy import text

    emails: list[str] = []
    yield emails
    with session_scope() as db:
        for email in emails:
            db.execute(
                text("DELETE FROM balances WHERE user_id IN (SELECT id FROM users WHERE email = :e)"),
                {"e": email},
            )
            db.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def _register(client, registered_emails, password: str):
    import uuid

    email = f"pw-cap-{uuid.uuid4().hex[:10]}@example.com"
    registered_emails.append(email)
    return client.post("/api/auth/register", json={"email": email, "password": password})


@requires_db
@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a1" * 36 + "x", id="영문 73바이트"),
        pytest.param("가" * 24 + "a1", id="한글 24자+영숫자 = 74바이트"),
    ],
)
def test_register_rejects_password_over_72_bytes(client, registered_emails, password):
    """bcrypt가 72바이트 이후를 조용히 잘라서, 그 뒤만 다른 비밀번호로도 로그인됐다 (실측)."""
    response = _register(client, registered_emails, password)

    assert response.status_code == 422
    assert "비밀번호가 너무 깁니다" in response.json()["detail"][0]["msg"]


@requires_db
@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a1" * 36, id="영문 정확히 72바이트"),
        pytest.param("가" * 23 + "a1", id="한글 23자+영숫자 = 71바이트"),
    ],
)
def test_register_accepts_password_at_or_under_72_bytes(client, registered_emails, password):
    assert _register(client, registered_emails, password).status_code == 201


@requires_db
def test_password_change_enforces_the_same_cap(client, make_user):
    """한쪽에만 상한이 있으면 가입 후 비밀번호 변경으로 우회된다."""
    from app.services.auth import hash_password

    user_id = make_user(password_hash=hash_password("current1"))
    token = create_access_token(user_id)

    response = client.patch(
        "/api/account/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "current1", "new_password": "a1" * 36 + "x"},
    )

    assert response.status_code == 422


@requires_db
def test_existing_long_password_user_can_still_log_in(client, make_user):
    """상한 도입 **전**에 긴 비밀번호로 가입한 유저가 잠기면 안 된다 — 로그인에는 상한을 걸지 않는다."""
    from app.models import User
    from app.services.auth import hash_password

    long_password = "a1" * 50  # 100바이트 — 상한 이전 가입자
    user_id = make_user(password_hash=hash_password(long_password))
    with session_scope() as db:
        email = db.get(User, user_id).email

    response = client.post("/api/auth/login", json={"email": email, "password": long_password})

    assert response.status_code == 200, response.text
