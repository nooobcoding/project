"""관리자 권한 경계와 유저 목록·상세 (확장판 05-admin.md 3-A, 6장 검증 1)."""

import re
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.database import session_scope
from app.main import app
from app.models import User
from app.models.user import ROLE_ADMIN, STATUS_SUSPENDED
from app.services import wallet
from app.services.auth import create_access_token
from app.services.orders import create_order
from tests.conftest import requires_db

pytestmark = requires_db


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _set(user_id: int, **values) -> None:
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(**values))


def _email(user_id: int) -> str:
    with session_scope() as db:
        return db.get(User, user_id).email


@pytest.fixture
def admin_headers(make_user):
    admin_id = make_user()
    _set(admin_id, role=ROLE_ADMIN)
    return _headers(admin_id)


def _admin_routes() -> list[tuple[str, str]]:
    """`/api/admin` 아래 엔드포인트 전부. 경로 파라미터는 1로 채운다.

    다른 인증 테스트는 기대 목록을 손으로 쓰지만(빠뜨린 엔드포인트가 목록에서도 빠지는 걸
    막으려고), 여기서는 라우터 단위 의존성이 보호막이라 **새로 생긴 경로가 그 밖에서 만들어지는
    것**을 잡는 쪽이 중요하다 — 그래서 앱에 실제로 등록된 경로를 훑는다.

    OpenAPI 스키마에서 읽는다 — FastAPI 0.141부터 `app.routes`는 포함된 라우터를 펼치지 않고
    묶음으로 담아서, 거기서 찾으면 0개가 나온다(실제로 그랬다).
    """
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/admin"):
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        for method in operations:
            routes.append((method.upper(), concrete))
    return routes


ADMIN_ROUTES = _admin_routes()


def test_admin_routes_exist():
    """훑은 목록이 비면 아래 매개변수화 테스트가 0개로 '통과'한다 — 그것부터 막는다."""
    assert ("GET", "/api/admin/users") in ADMIN_ROUTES


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_regular_user_gets_403_on_every_admin_route(client, auth_headers, method, path):
    response = client.request(method, path, headers=auth_headers, json={})

    assert response.status_code == 403, f"{method} {path} 가 일반 유저에게 열려 있다"
    assert response.json()["detail"] == "권한이 없습니다."


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_route_requires_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_suspended_admin_is_blocked_too(client, make_user):
    """정지 검사가 권한 검사보다 먼저다 — 관리자라도 정지되면 못 들어온다."""
    admin_id = make_user()
    _set(admin_id, role=ROLE_ADMIN, status=STATUS_SUSPENDED)

    response = client.get("/api/admin/users", headers=_headers(admin_id))

    assert response.status_code == 403
    assert response.json()["detail"].startswith("정지된 계정")


# ---------------------------------------------------------------- 목록


def _find(client, headers, user_id: int, **params) -> dict | None:
    response = client.get(
        "/api/admin/users", headers=headers, params={"q": _email(user_id), **params}
    )
    assert response.status_code == 200, response.text
    matches = [item for item in response.json()["items"] if item["id"] == user_id]
    return matches[0] if matches else None


def test_list_row_matches_what_the_user_sees(client, admin_headers, test_user, test_coin, set_price, make_slot):
    """목록의 금액은 유저 본인 화면(/api/portfolio/summary)과 같아야 한다.

    목록은 N+1을 피하려고 집계를 따로 짜므로, 같은 값을 내는지 본인 API와 대조한다.
    """
    set_price(1000)
    with session_scope() as db:
        create_order(db, test_user, test_coin, "buy", "market", Decimal("10"))
    set_price(1500)  # 평단과 다른 시세라야 평가 단가가 실제로 쓰였는지 보인다
    make_slot()

    row = _find(client, admin_headers, test_user)
    mine = client.get("/api/portfolio/summary", headers=_headers(test_user)).json()

    assert row is not None
    assert row["active_slot_count"] == 1
    assert Decimal(row["krw_balance"]) == Decimal(mine["krw_balance"])
    assert Decimal(row["total_valuation"]) == Decimal(mine["krw_balance"]) + Decimal(mine["coin_valuation"])
    assert Decimal(mine["coin_valuation"]) == Decimal("15000")


def test_filters(client, admin_headers, make_user, make_slot, test_user):
    suspended = make_user()
    _set(suspended, status=STATUS_SUSPENDED)
    make_slot()  # test_user만 활성 슬롯 보유

    assert _find(client, admin_headers, suspended, status="suspended") is not None
    assert _find(client, admin_headers, suspended, status="active") is None
    assert _find(client, admin_headers, test_user, has_active_slots="true") is not None
    assert _find(client, admin_headers, test_user, has_active_slots="false") is None
    assert _find(client, admin_headers, suspended, has_active_slots="false") is not None


def test_email_search_treats_wildcards_literally(client, admin_headers, test_user):
    """`_`는 LIKE에서 아무 글자 하나다. 그대로 넘기면 검색어 `_`가 모든 이메일에 걸린다."""
    response = client.get("/api/admin/users", headers=admin_headers, params={"q": "_", "page_size": 100})
    assert all("_" in item["email"] for item in response.json()["items"])


def test_pagination_and_page_size_cap(client, admin_headers, make_user):
    make_user(), make_user()
    response = client.get("/api/admin/users", headers=admin_headers, params={"page_size": 1})
    body = response.json()
    assert len(body["items"]) == 1 and body["total"] >= 2

    newest = body["items"][0]["id"]
    oldest = client.get(
        "/api/admin/users", headers=admin_headers, params={"page_size": 1, "sort": "oldest"}
    ).json()["items"][0]["id"]
    assert newest != oldest

    assert client.get("/api/admin/users", headers=admin_headers, params={"page_size": 101}).status_code == 422


# ---------------------------------------------------------------- 상세


def test_detail_reuses_the_users_own_views(client, admin_headers, test_user, test_coin, set_price, make_slot):
    set_price(1000)
    with session_scope() as db:
        create_order(db, test_user, test_coin, "buy", "market", Decimal("10"))
        pending = create_order(db, test_user, test_coin, "buy", "limit", Decimal("1"), price=Decimal("500"))
        pending_id = pending.id
    with session_scope() as db:
        wallet.deposit(db, test_user, Decimal("12345"), "admin-detail")
    slot_id = make_slot()

    response = client.get(f"/api/admin/users/{test_user}", headers=admin_headers)
    assert response.status_code == 200, response.text
    detail = response.json()

    mine = _headers(test_user)
    assert detail["holdings"] == client.get("/api/portfolio/holdings", headers=mine).json()
    assert detail["slots"] == client.get("/api/strategy-slots", headers=mine).json()
    balance = client.get("/api/wallet/balance", headers=mine).json()
    assert detail["summary"]["withdrawable_krw"] == balance["withdrawable_krw"]
    assert detail["summary"]["krw_balance"] == balance["krw_balance"]

    assert [o["id"] for o in detail["pending_orders"]] == [pending_id]
    assert detail["recent_orders"][0]["status"] == "filled"
    assert detail["recent_transactions"][0]["memo"] == "admin-detail"
    assert [s["id"] for s in detail["slots"]] == [slot_id]


def test_detail_unknown_user(client, admin_headers):
    response = client.get("/api/admin/users/999999999", headers=admin_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "해당 유저를 찾을 수 없습니다."
