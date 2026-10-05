"""계정 정지·해제 (확장판 05-admin.md 3-B, 6장 검증 2·3·4).

정지는 "이 계정으로 더 이상 돈이 움직이지 않는다"가 성립해야 한다. 그래서 로그인 차단만이
아니라 슬롯 OFF, 미체결 주문 취소, 정지 직전에 출발한 주문 차단까지 본다.
"""

import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

from app.database import get_engine, session_scope
from app.models import AuditLog, Order, StrategySlot, User
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE, STATUS_SUSPENDED
from app.services import admin as admin_service
from app.services import wallet
from app.services.auth import create_access_token
from app.services.orders import AccountSuspendedError, create_order
from app.strategy_engine import worker
from tests.conftest import load_slot_state, requires_db

pytestmark = requires_db

POSITION = {"quantity": "3", "avg_price": "1000"}


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _set(user_id: int, **values) -> None:
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(**values))


def _status(user_id: int) -> str:
    with session_scope() as db:
        return db.get(User, user_id).status


def _order_status(order_id: int) -> str:
    with session_scope() as db:
        return db.get(Order, order_id).status


def _is_active(slot_id: int) -> bool:
    with session_scope() as db:
        return db.get(StrategySlot, slot_id).is_active


def _audits(user_id: int) -> list[tuple]:
    with session_scope() as db:
        rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.target_type == "user", AuditLog.target_id == user_id)
            .order_by(AuditLog.id)
        ).all()
        return [(row.action, row.actor_user_id, row.actor_email, row.detail) for row in rows]


@pytest.fixture
def admin_id(make_user):
    user_id = make_user()
    _set(user_id, role=ROLE_ADMIN)
    return user_id


def _patch(client, admin_id: int, user_id: int, status: str):
    return client.patch(
        f"/api/admin/users/{user_id}/status", headers=_headers(admin_id), json={"status": status}
    )


def _place_pending_orders(user_id: int, coin: str) -> tuple[int, int]:
    """지정가 매수 1건(현재가 아래라 안 걸림) + 예약가 매수 1건."""
    with session_scope() as db:
        limit = create_order(db, user_id, coin, "buy", "limit", Decimal("2"), price=Decimal("500"))
        reserved = create_order(
            db, user_id, coin, "buy", "reserved", Decimal("1"),
            price=Decimal("2100"), trigger_price=Decimal("2000"),
        )
        return limit.id, reserved.id


def _suspend(admin_id: int, user_id: int) -> dict:
    with session_scope() as db:
        return admin_service.set_user_status(db, db.get(User, admin_id), user_id, STATUS_SUSPENDED)


# ---------------------------------------------------------------- 정지가 하는 일


def test_suspend_stops_every_money_path(client, admin_id, test_user, test_coin, set_price, make_slot):
    set_price(1000)
    # 주문을 먼저 낸다 — 활성 슬롯이 있는 코인은 수동 주문이 잠긴다(FR-M10)
    limit_id, reserved_id = _place_pending_orders(test_user, test_coin)
    slot_id = make_slot(state={"position": POSITION})
    token = _headers(test_user)  # 정지 **전에** 발급된 토큰

    response = _patch(client, admin_id, test_user, "suspended")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["deactivated_slot_ids"] == [slot_id]
    assert sorted(body["canceled_order_ids"]) == sorted([limit_id, reserved_id])

    assert _status(test_user) == STATUS_SUSPENDED
    # 슬롯은 꺼지되 포지션은 그대로다 — 일반 OFF와 같은 규칙 (6장 검증 4)
    assert _is_active(slot_id) is False
    assert load_slot_state(slot_id)["position"] == POSITION
    # 주문이 전부 취소돼 동결이 풀렸다
    assert {_order_status(limit_id), _order_status(reserved_id)} == {"canceled"}
    with session_scope() as db:
        assert wallet.get_withdrawable_krw(db, test_user) == Decimal("10000000")
    # 기존 토큰이 즉시 막힌다 (6장 검증 2)
    assert client.get("/api/orders", headers=token).status_code == 403

    [(action, actor, actor_email, detail)] = _audits(test_user)
    assert (action, actor) == ("user.suspend", admin_id)
    assert actor_email.endswith("@example.com")
    assert detail["deactivated_slot_ids"] == [slot_id]
    assert sorted(detail["canceled_order_ids"]) == sorted([limit_id, reserved_id])


def test_worker_stops_evaluating_a_suspended_users_slots(admin_id, test_user, make_slot):
    """6장 검증 3 — 정지된 유저의 슬롯은 워커의 평가 목록에서 빠진다."""
    slot_id = make_slot()
    all_shards = set(range(64))
    assert slot_id in {sid for _, sid in worker._load_active_slots(all_shards)}

    _suspend(admin_id, test_user)

    assert slot_id not in {sid for _, sid in worker._load_active_slots(all_shards)}


def test_unsuspend_restores_access_but_leaves_slots_off(client, admin_id, test_user, make_slot):
    slot_id = make_slot()
    _patch(client, admin_id, test_user, "suspended")

    response = _patch(client, admin_id, test_user, "active")

    assert response.status_code == 200
    assert _status(test_user) == STATUS_ACTIVE
    assert client.get("/api/account", headers=_headers(test_user)).status_code == 200
    assert _is_active(slot_id) is False  # 다시 켜는 건 사용자 몫
    assert [a[0] for a in _audits(test_user)] == ["user.suspend", "user.unsuspend"]


def test_repeating_the_same_status_is_idempotent(client, admin_id, test_user):
    _patch(client, admin_id, test_user, "suspended")
    response = _patch(client, admin_id, test_user, "suspended")

    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert len(_audits(test_user)) == 1


def test_repeat_sweeps_orders_left_by_a_failed_second_phase(client, admin_id, test_user, test_coin, set_price):
    """2단계(주문 취소)가 실패해 주문이 남았다면, 같은 요청을 다시 보내 마저 치울 수 있어야 한다."""
    set_price(1000)
    limit_id, _ = _place_pending_orders(test_user, test_coin)
    _set(test_user, status=STATUS_SUSPENDED)  # 1단계만 끝난 상태를 흉내 낸다

    body = _patch(client, admin_id, test_user, "suspended").json()

    assert body["changed"] is False
    assert limit_id in body["canceled_order_ids"]
    assert _order_status(limit_id) == "canceled"
    assert limit_id in _audits(test_user)[0][3]["canceled_order_ids"]


@pytest.mark.parametrize(
    "target,message",
    [("self", "본인 계정은 정지할 수 없습니다."), ("admin", "관리자 계정은 정지할 수 없습니다.")],
)
def test_suspending_self_or_another_admin_is_refused(client, admin_id, make_user, target, message):
    if target == "self":
        target_id = admin_id
    else:
        target_id = make_user()
        _set(target_id, role=ROLE_ADMIN)

    response = _patch(client, admin_id, target_id, "suspended")

    assert response.status_code == 400
    assert response.json()["detail"] == message
    assert _status(target_id) == STATUS_ACTIVE
    assert _audits(target_id) == []


def test_unknown_user_and_bad_status(client, admin_id, test_user):
    assert _patch(client, admin_id, 999999999, "suspended").status_code == 404
    assert _patch(client, admin_id, test_user, "banned").status_code == 422


# ---------------------------------------------------------------- 정지 직전에 출발한 주문


@pytest.mark.parametrize("source", ["manual", "auto"])
def test_order_that_arrives_after_suspension_is_refused(test_user, test_coin, set_price, source):
    """인증은 정지 전에 통과했고 주문은 정지 뒤에 도착한 경우.

    HTTP 요청이 처리 중이었거나, 워커가 정지 전 스냅샷으로 tick을 돌던 경우다. 인증 단계 검사만
    있으면 이 주문은 그대로 나간다 — 시장가면 정지된 계정으로 실제 체결까지 된다.
    """
    set_price(1000)
    _set(test_user, status=STATUS_SUSPENDED)

    with pytest.raises(AccountSuspendedError):
        with session_scope() as db:
            create_order(db, test_user, test_coin, "buy", "market", Decimal("1"), source=source)

    with session_scope() as db:
        assert db.scalars(select(Order).where(Order.user_id == test_user)).all() == []


def test_worker_tick_started_before_suspension_places_nothing(admin_id, test_user, set_price, make_slot):
    set_price(1000)
    slot_id = make_slot()
    snapshot = worker._load_slot_snapshot(slot_id)  # 정지 전에 읽은 스냅샷

    _suspend(admin_id, test_user)

    assert worker._place_buy(snapshot, Decimal("10000")) is None
    with session_scope() as db:
        assert db.scalars(select(Order).where(Order.user_id == test_user)).all() == []


# ---------------------------------------------------------------- 정지 vs 체결


def test_suspend_does_not_deadlock_with_a_fill_in_progress(admin_id, test_user, test_coin, set_price):
    """체결이 주문 행을 선점한 채 balances를 기다리는 순간에 정지가 들어오는 경우.

    체결의 잠금 순서는 `orders(선점) → balances`다. 정지를 한 트랜잭션으로 짜면
    `balances → orders`가 되어 서로를 기다린다 — PostgreSQL이 교착을 감지해 한쪽을 죽인다.
    체결 쪽이 죽으면 matcher가 그 주문을 다음 틱에 다시 시도하지만, 정지 쪽이 죽으면 관리자가
    500을 받는다. 어느 쪽이든 틀렸다.

    체결을 실제 `fill_order`로 돌리면 선점과 잠금 사이에 끼어들 틈을 만들 수 없어서, 같은 SQL을
    두 단계로 나눠 그 사이에 정지를 끼워 넣는다.
    """
    set_price(1000)
    with session_scope() as db:
        order_id = create_order(
            db, test_user, test_coin, "buy", "limit", Decimal("1"), price=Decimal("900")
        ).id

    claimed = threading.Event()
    errors: list[BaseException] = []
    fill_outcome: list[str] = []
    suspend_result: list[dict] = []

    def fill():
        try:
            with get_engine().connect() as conn:
                with conn.begin():
                    conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                    won = conn.execute(
                        text("UPDATE orders SET status = 'filled' WHERE id = :id AND status = 'pending'"),
                        {"id": order_id},
                    ).rowcount
                    claimed.set()
                    time.sleep(1.5)  # 정지가 들어와 무언가를 기다리기 시작할 시간
                    conn.execute(
                        text("SELECT 1 FROM balances WHERE user_id = :uid FOR UPDATE"),
                        {"uid": test_user},
                    )
                    fill_outcome.append("filled" if won else "lost")
        except BaseException as exc:  # noqa: BLE001 - 스레드 예외를 본 테스트로 옮긴다
            errors.append(exc)
            claimed.set()

    def suspend():
        try:
            claimed.wait(5)
            suspend_result.append(_suspend(admin_id, test_user))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=fill), threading.Thread(target=suspend)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert errors == [], f"교착 또는 잠금 실패: {errors!r}"
    assert fill_outcome == ["filled"]
    # 체결이 이겼으니 정지는 그 주문을 취소 목록에 넣지 않았다 — 둘 다 성공한 척하지 않는다
    assert order_id not in suspend_result[0]["canceled_order_ids"]
    assert _order_status(order_id) == "filled"
    assert _status(test_user) == STATUS_SUSPENDED
