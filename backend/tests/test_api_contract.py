"""라우터 계약 — 남의 자원 접근(IDOR)과 문서에 고정된 에러 응답.

**IDOR가 이 파일의 핵심이다.** 서비스 계층에는 `_get_owned_slot` 류의 소유권 검사가 있지만,
라우터가 그 함수를 부르면서 `current_user.id`를 제대로 넘기는지는 전 구간에서 확인된 적이
없다. 경로에 남의 id를 넣어 실제로 요청을 흘려보내는 것이 유일한 확인 방법이다.

응답은 403이 아니라 **404**여야 한다 — 403은 "그 id는 존재하지만 네 것이 아니다"를 알려주어
남의 자원 존재 여부가 새어나간다 (서비스 docstring도 "없는 것과 똑같이 취급한다"고 적혀 있다).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.database import session_scope
from app.models import Notification, Order, StrategySlot
from app.services.auth import create_access_token
from tests.conftest import requires_db


@pytest.fixture
def victim(make_user):
    """자원을 가진 다른 유저 — 공격자는 `test_user`/`auth_headers` 쪽이다."""
    return make_user()


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _make_slot_for(user_id: int, coin: str) -> int:
    with session_scope() as db:
        slot = StrategySlot(
            user_id=user_id,
            coin_symbol=coin,
            strategy_type="trend",
            indicator="ma",
            params={"interval": "1d", "short_period": 2, "long_period": 3},
            invest_amount=Decimal("1000000"),
            state={},
            is_active=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(slot)
        db.flush()
        return slot.id


def _make_order_for(user_id: int, coin: str) -> int:
    with session_scope() as db:
        order = Order(
            user_id=user_id,
            coin_symbol=coin,
            side="buy",
            order_type="limit",
            price=Decimal("100000"),
            quantity=Decimal("0.1"),
            status="pending",
            source="manual",
            fee=Decimal(0),
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.flush()
        return order.id


def _make_notification_for(user_id: int, coin: str) -> int:
    with session_scope() as db:
        notification = Notification(
            user_id=user_id,
            type="signal",
            message="남의 알림",
            coin_symbol=coin,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.flush()
        return notification.id


# ---------------------------------------------------------------- IDOR


@requires_db
def test_cannot_read_another_users_slot_signals(client, auth_headers, victim, test_coin, stub_candles):
    """`stub_candles`가 붙은 이유: 소유권 검사가 무너지면 요청이 확정봉 조회까지 내려가
    실제 Upbit API를 때린다. 그 상태에서도 테스트는 외부를 건드리지 않아야 한다."""
    slot_id = _make_slot_for(victim, test_coin)

    response = client.get(f"/api/strategy-slots/{slot_id}/signals", headers=auth_headers)

    assert response.status_code == 404, f"남의 슬롯 신호가 새어나갔다: {response.text}"


@requires_db
def test_cannot_toggle_another_users_slot(client, auth_headers, victim, test_coin):
    """남의 슬롯을 켤 수 있으면 **남의 돈으로 자동매매가 돈다** — IDOR 중 가장 비싼 경우다."""
    slot_id = _make_slot_for(victim, test_coin)

    response = client.patch(
        f"/api/strategy-slots/{slot_id}", headers=auth_headers, json={"is_active": True}
    )

    assert response.status_code == 404
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).is_active is False, "남의 슬롯이 켜졌다"


@requires_db
def test_cannot_delete_another_users_slot(client, auth_headers, victim, test_coin):
    slot_id = _make_slot_for(victim, test_coin)

    response = client.delete(f"/api/strategy-slots/{slot_id}", headers=auth_headers)

    assert response.status_code == 404
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id) is not None, "남의 슬롯이 삭제됐다"


@requires_db
def test_cannot_cancel_another_users_order(client, auth_headers, victim, test_coin):
    """남의 미체결 주문을 취소할 수 있으면 남의 거래를 방해할 수 있다."""
    order_id = _make_order_for(victim, test_coin)

    response = client.delete(f"/api/orders/{order_id}", headers=auth_headers)

    assert response.status_code == 404
    with session_scope() as db:
        assert db.get(Order, order_id).status == "pending", "남의 주문이 취소됐다"


@requires_db
def test_cannot_mark_another_users_notification_read(client, auth_headers, victim, test_coin):
    notification_id = _make_notification_for(victim, test_coin)

    response = client.patch(f"/api/notifications/{notification_id}/read", headers=auth_headers)

    assert response.status_code == 404
    with session_scope() as db:
        assert db.get(Notification, notification_id).is_read is False


@pytest.fixture
def stub_candles(monkeypatch):
    """확정봉 조회를 가로막는다 — 안 하면 합성 코인(ZZTEST) 때문에 **실제 Upbit API를 때린다.**

    테스트가 외부 API에 의존하면 네트워크 사정에 따라 결과가 바뀌고, 상장되지도 않은 심볼로
    남의 서비스에 요청을 보내게 된다.
    """
    from app.services import candles as candles_service

    monkeypatch.setattr(
        candles_service, "get_confirmed_candles", lambda db, symbol, interval, **kwargs: []
    )


@requires_db
def test_owner_can_do_what_the_attacker_could_not(client, victim, test_coin, stub_candles):
    """음성 대조군 — 위 404들이 "그 경로가 늘 404"라서 나온 것이 아님을 보인다.

    이게 없으면 라우터가 통째로 망가져 모든 요청이 404여도 IDOR 테스트는 전부 통과한다.
    """
    owner = _headers(victim)
    slot_id = _make_slot_for(victim, test_coin)
    notification_id = _make_notification_for(victim, test_coin)
    order_id = _make_order_for(victim, test_coin)

    assert client.get(f"/api/strategy-slots/{slot_id}/signals", headers=owner).status_code == 200
    assert client.patch(f"/api/notifications/{notification_id}/read", headers=owner).status_code == 200
    assert client.delete(f"/api/orders/{order_id}", headers=owner).status_code == 204
    assert client.delete(f"/api/strategy-slots/{slot_id}", headers=owner).status_code == 200


@requires_db
def test_another_users_slot_is_absent_from_the_list(client, auth_headers, victim, test_coin):
    """목록 조회에도 남의 것이 섞이면 안 된다 (경로 id가 없는 쪽의 누출 경로)."""
    slot_id = _make_slot_for(victim, test_coin)

    response = client.get("/api/strategy-slots", headers=auth_headers)

    assert response.status_code == 200
    assert slot_id not in [item["id"] for item in response.json()]


# ---------------------------------------------------------------- 입력 검증 경계


@requires_db
def test_withdraw_memo_over_30_chars_is_rejected(client, auth_headers):
    """memo 30자 상한은 서비스가 아니라 스키마가 강제한다 (Phase 1.1에서 여기로 미뤄둔 항목)."""
    response = client.post(
        "/api/wallet/withdraw",
        headers=auth_headers,
        json={"amount": "1000", "memo": "가" * 31},
    )

    assert response.status_code == 422


@requires_db
def test_withdraw_memo_at_30_chars_is_accepted(client, auth_headers):
    response = client.post(
        "/api/wallet/withdraw",
        headers=auth_headers,
        json={"amount": "1000", "memo": "가" * 30},
    )

    assert response.status_code == 201, response.text


@requires_db
def test_withdraw_beyond_withdrawable_returns_documented_message(client, auth_headers):
    """문서(05-deposit-withdraw.md 3장)가 고정한 한국어 문구 — 바뀌면 프론트가 깨진다."""
    response = client.post(
        "/api/wallet/withdraw", headers=auth_headers, json={"amount": "999999999"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "출금 금액이 보유 잔고를 초과합니다. (자동매매에 배정된 금액이 있다면 이를 제외한 금액 기준)"
    )


@requires_db
def test_withdraw_non_numeric_amount_returns_documented_message(client, auth_headers):
    response = client.post("/api/wallet/withdraw", headers=auth_headers, json={"amount": "abc"})

    assert response.status_code == 400
    assert response.json()["detail"] == "올바른 금액을 입력해주세요. (1원 이상)"


@requires_db
def test_transactions_reject_unknown_type_filter(client, auth_headers):
    response = client.get(
        "/api/wallet/transactions", headers=auth_headers, params={"type": "transfer"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "지원하지 않는 type 값입니다."
