"""슬롯 강제 OFF (확장판 05-admin.md 3-C, 6장 검증 4)."""

import pytest
from sqlalchemy import select, update

from app.database import session_scope
from app.models import AuditLog, StrategySlot, User
from app.models.user import ROLE_ADMIN
from app.services.auth import create_access_token
from tests.conftest import requires_db

pytestmark = requires_db

POSITION = {"quantity": "3", "avg_price": "1000"}
GRID_STATE = {
    "position": POSITION,
    "grid": {"lines": [{"price": "900", "quantity": "3", "filled": True}]},
    "last_evaluated_candle_at": "2026-10-01T00:00:00+00:00",
}


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.fixture
def admin_id(make_user):
    user_id = make_user()
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(role=ROLE_ADMIN))
    return user_id


def _slot_row(slot_id: int) -> tuple[bool, dict]:
    with session_scope() as db:
        slot = db.get(StrategySlot, slot_id)
        return slot.is_active, dict(slot.state)


def _slot_audits(slot_id: int) -> list[tuple]:
    with session_scope() as db:
        return [
            (row.action, row.actor_user_id, row.detail)
            for row in db.scalars(
                select(AuditLog).where(
                    AuditLog.target_type == "strategy_slot", AuditLog.target_id == slot_id
                )
            )
        ]


def test_force_off_matches_the_users_own_off(client, admin_id, test_user, test_coin, make_slot):
    """관리자 OFF와 사용자 OFF가 슬롯을 똑같은 상태로 남겨야 한다 — 규칙이 갈라지면 버그가 난다.

    같은 state를 가진 슬롯 두 개를 만들어 하나는 사용자가, 하나는 관리자가 끄고 비교한다.
    """
    # 같은 코인에 활성 슬롯은 하나뿐이라, 사용자 쪽을 먼저 끄고 나서 관리자 쪽을 만든다
    by_user = make_slot(state=GRID_STATE)
    assert client.patch(
        f"/api/strategy-slots/{by_user}", headers=_headers(test_user), json={"is_active": False}
    ).status_code == 200
    by_admin = make_slot(state=GRID_STATE)

    response = client.post(
        f"/api/admin/strategy-slots/{by_admin}/deactivate", headers=_headers(admin_id)
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert _slot_row(by_admin) == _slot_row(by_user) == (False, GRID_STATE)

    [(action, actor, detail)] = _slot_audits(by_admin)
    assert (action, actor) == ("slot.deactivate", admin_id)
    assert detail == {"user_id": test_user, "coin_symbol": test_coin}


def test_force_off_of_an_inactive_slot_leaves_no_audit(client, admin_id, make_slot):
    slot_id = make_slot(is_active=False)

    response = client.post(
        f"/api/admin/strategy-slots/{slot_id}/deactivate", headers=_headers(admin_id)
    )

    assert response.status_code == 200
    assert _slot_audits(slot_id) == []


def test_force_off_unknown_slot(client, admin_id):
    response = client.post(
        "/api/admin/strategy-slots/999999999/deactivate", headers=_headers(admin_id)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "존재하지 않는 전략입니다."
