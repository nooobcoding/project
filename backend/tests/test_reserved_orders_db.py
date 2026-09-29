"""예약가(order_type='reserved') 주문 — 생성·동결·승격 (01-erd.md 3.7절, FR-M11).

전 구간 미검증이던 경로다. 예약가는 **자체 체결 경로를 갖지 않고** 감시가격 도달 시
`limit`으로 승격만 되며, 그 뒤는 기존 지정가 체결 인프라를 그대로 탄다 — 그래서 검증
지점이 "승격이 정확히 한 번, 정확한 조건에서 일어나는가"에 몰려 있다.
"""

import threading
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Order
from app.services import matcher
from app.services.orders import (
    InvalidOrderInputError,
    OrderNotCancelableError,
    cancel_order,
    create_order,
    get_available_krw,
    get_available_quantity,
)
from tests.conftest import requires_db

CURRENT = Decimal("100000")
QUANTITY = Decimal("0.1")


def _order_values(order) -> dict:
    """세션이 닫히기 전에 필요한 값만 뽑아 둔다 (DetachedInstanceError 회피)."""
    return {
        "id": order.id,
        "order_type": order.order_type,
        "status": order.status,
        "price": order.price,
        "trigger_price": order.trigger_price,
        "trigger_direction": order.trigger_direction,
    }


def _create_reserved(user_id, coin, side, trigger_price, price):
    with session_scope() as db:
        return _order_values(
            create_order(
                db,
                user_id=user_id,
                coin_symbol=coin,
                side=side,
                order_type="reserved",
                quantity=QUANTITY,
                price=price,
                trigger_price=trigger_price,
                source="manual",
            )
        )


def _load(order_id) -> dict:
    with session_scope() as db:
        return _order_values(db.get(Order, order_id))


def _buy_some(user_id, coin):
    """매도 테스트용 보유수량을 확보한다."""
    with session_scope() as db:
        create_order(
            db,
            user_id=user_id,
            coin_symbol=coin,
            side="buy",
            order_type="market",
            quantity=QUANTITY,
            source="manual",
        )


# ---------------------------------------------------------------- 생성 시 방향 확정


@requires_db
def test_reserved_order_rejects_trigger_equal_to_current_price(test_user, test_coin, set_price):
    """감시가격 == 현재가는 상승/하락 어느 쪽을 기다리는지 모호하므로 생성 자체를 거부한다."""
    set_price(CURRENT)

    with pytest.raises(InvalidOrderInputError):
        _create_reserved(test_user, test_coin, "buy", trigger_price=CURRENT, price=CURRENT)


@requires_db
def test_reserved_order_direction_is_fixed_at_creation(test_user, test_coin, set_price):
    set_price(CURRENT)

    rising = _create_reserved(
        test_user, test_coin, "buy", trigger_price=CURRENT + 10000, price=CURRENT + 20000
    )
    assert rising["trigger_direction"] == "rising"

    falling = _create_reserved(
        test_user, test_coin, "buy", trigger_price=CURRENT - 10000, price=CURRENT - 5000
    )
    assert falling["trigger_direction"] == "falling"


@requires_db
def test_reserved_direction_survives_price_round_trip(test_user, test_coin, set_price):
    """가격이 감시가를 넘었다가 되돌아와도 방향이 재계산되면 안 된다 (3.7절 1번).

    재계산하면 같은 주문이 상황에 따라 반대 방향으로 해석돼 엉뚱한 시점에 승격된다.
    """
    set_price(CURRENT)
    order = _create_reserved(
        test_user, test_coin, "buy", trigger_price=CURRENT + 10000, price=CURRENT + 20000
    )

    # 감시가를 넘겼다가(승격됨) 다시 아래로 내려온 뒤에도 방향은 그대로여야 한다.
    matcher.run_matching_for_symbol(test_coin, CURRENT - 50000)
    after_dip = _load(order["id"])
    assert after_dip["trigger_direction"] == "rising"
    assert after_dip["order_type"] == "reserved", "조건을 안 채웠는데 승격되면 안 된다"


# ---------------------------------------------------------------- 생성 즉시 동결


@requires_db
def test_reserved_buy_freezes_krw_immediately(test_user, test_coin, set_price):
    """트리거 도달 전이라도 예약가 매수는 지정가와 동일하게 잔고를 동결한다 (01-erd.md 3.1절
    "가용잔고 잠금은 order_type 무관")."""
    set_price(CURRENT)
    limit_price = CURRENT + 20000

    with session_scope() as db:
        before = get_available_krw(db, test_user)

    _create_reserved(test_user, test_coin, "buy", trigger_price=CURRENT + 10000, price=limit_price)

    with session_scope() as db:
        after = get_available_krw(db, test_user)

    expected_lock = limit_price * QUANTITY * (1 + TRADING_FEE_RATE)
    assert after == before - expected_lock


@requires_db
def test_reserved_sell_freezes_quantity_immediately(test_user, test_coin, set_price):
    set_price(CURRENT)
    _buy_some(test_user, test_coin)

    with session_scope() as db:
        before = get_available_quantity(db, test_user, test_coin)

    _create_reserved(
        test_user, test_coin, "sell", trigger_price=CURRENT - 10000, price=CURRENT - 20000
    )

    with session_scope() as db:
        after = get_available_quantity(db, test_user, test_coin)

    assert after == before - QUANTITY


# ---------------------------------------------------------------- 승격


@requires_db
def test_rising_reserved_promotes_when_price_reaches_trigger(test_user, test_coin, set_price):
    set_price(CURRENT)
    trigger = CURRENT + 10000
    # 승격 직후 같은 틱에 지정가 체결까지 가지 않도록, 매수 지정가를 현재가보다 낮게 둔다
    # (매수 지정가 조건은 현재가 <= 주문가라 승격만 일어나고 체결은 안 된다).
    order = _create_reserved(test_user, test_coin, "buy", trigger_price=trigger, price=trigger - 5000)

    matcher.run_matching_for_symbol(test_coin, trigger - 1)
    assert _load(order["id"])["order_type"] == "reserved", "도달 전에는 승격되면 안 된다"

    matcher.run_matching_for_symbol(test_coin, trigger)
    promoted = _load(order["id"])
    assert promoted["order_type"] == "limit"
    assert promoted["status"] == "pending"


@requires_db
def test_falling_reserved_promotes_when_price_drops_to_trigger(test_user, test_coin, set_price):
    set_price(CURRENT)
    trigger = CURRENT - 10000
    order = _create_reserved(
        test_user, test_coin, "buy", trigger_price=trigger, price=trigger - 5000
    )

    matcher.run_matching_for_symbol(test_coin, trigger + 1)
    assert _load(order["id"])["order_type"] == "reserved"

    matcher.run_matching_for_symbol(test_coin, trigger)
    assert _load(order["id"])["order_type"] == "limit"


@requires_db
def test_promotion_preserves_trigger_fields_as_history(test_user, test_coin, set_price):
    """승격 후에도 trigger_price/trigger_direction은 이력으로 남는다 (3.7절 4번)."""
    set_price(CURRENT)
    trigger = CURRENT + 10000
    order = _create_reserved(test_user, test_coin, "buy", trigger_price=trigger, price=trigger - 5000)

    matcher.run_matching_for_symbol(test_coin, trigger)

    promoted = _load(order["id"])
    assert promoted["trigger_price"] == trigger
    assert promoted["trigger_direction"] == "rising"


@requires_db
def test_reserved_order_never_fills_while_still_reserved(test_user, test_coin, set_price):
    """예약가는 자체 체결 경로가 없다 — 지정가 조건을 이미 만족해도 승격 전에는 체결되면 안 된다.

    매수 지정가 조건(현재가 ≤ 주문가)을 만족하지만 감시가격에는 아직 도달하지 않은 가격을
    흘려보낸다. 체결 엔진이 order_type을 안 가리고 후보에 넣으면 여기서 잡힌다.
    """
    set_price(CURRENT)
    # trigger는 위쪽(rising), 주문가는 현재가보다 높다 → 지정가였다면 즉시 체결될 조건이다.
    order = _create_reserved(
        test_user, test_coin, "buy", trigger_price=CURRENT + 20000, price=CURRENT + 30000
    )

    matcher.run_matching_for_symbol(test_coin, CURRENT)

    still = _load(order["id"])
    assert still["status"] == "pending", "승격 전 예약가가 체결됐다"
    assert still["order_type"] == "reserved"


@requires_db
def test_promotion_and_fill_happen_in_the_same_tick(test_user, test_coin, set_price):
    """승격 후 같은 틱의 지정가 매칭까지 이어진다 (_promote_reserved_orders가 먼저 돈다)."""
    set_price(CURRENT)
    trigger = CURRENT + 10000
    order = _create_reserved(
        test_user, test_coin, "buy", trigger_price=trigger, price=trigger + 5000
    )

    matcher.run_matching_for_symbol(test_coin, trigger)

    filled = _load(order["id"])
    assert filled["order_type"] == "limit"
    assert filled["status"] == "filled", "승격된 주문이 같은 틱에 체결되지 않았다"


# ---------------------------------------------------------------- 취소와의 경합


@requires_db
def test_canceled_reserved_order_is_not_promoted(test_user, test_coin, set_price):
    set_price(CURRENT)
    trigger = CURRENT + 10000
    order = _create_reserved(test_user, test_coin, "buy", trigger_price=trigger, price=trigger - 5000)

    with session_scope() as db:
        cancel_order(db, test_user, order["id"])

    matcher.run_matching_for_symbol(test_coin, trigger)

    after = _load(order["id"])
    assert after["status"] == "canceled"
    assert after["order_type"] == "reserved", "취소된 주문이 승격됐다"


@requires_db
def test_concurrent_promotion_and_cancel_never_produce_both_fill_and_cancel(
    test_user, test_coin, set_price
):
    """승격→체결이 진행되는 그 순간 취소가 들어와도 "체결 XOR 취소"여야 한다.

    승격 자체는 취소와 배타적이지 **않다** — 아무것도 소비하지 않고 order_type만 바꾸므로,
    "승격이 먼저 커밋되고 그 뒤 취소"(canceled + limit)는 정상 직렬화 결과다. 실제로 막아야
    하는 것은 자금이 움직이는 쪽, 즉 체결과 취소가 둘 다 성립하는 경우다 — 그러면 잔고는
    차감됐는데 주문은 취소된 것으로 남아 동결분이 이중으로 풀린다.

    그래서 승격과 동시에 체결까지 가도록(주문가 > 감시가) 만들어 놓고 취소와 경합시킨다.
    """
    set_price(CURRENT)
    trigger = CURRENT + 10000

    for _ in range(5):
        order = _create_reserved(
            test_user, test_coin, "buy", trigger_price=trigger, price=trigger + 5000
        )
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def _cancel():
            barrier.wait()
            try:
                with session_scope() as db:
                    cancel_order(db, test_user, order["id"])
            except OrderNotCancelableError:
                pass  # 체결이 먼저 이겼다 — 정상
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def _promote_and_fill():
            barrier.wait()
            try:
                matcher.run_matching_for_symbol(test_coin, trigger)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_cancel), threading.Thread(target=_promote_and_fill)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"예상 못 한 예외 누출: {errors!r}"

        after = _load(order["id"])
        assert after["status"] in ("filled", "canceled"), f"pending으로 남았다: {after!r}"

        with session_scope() as db:
            # 같은 주문이 체결 이력과 취소 이력을 동시에 가질 수는 없다 (status는 하나뿐이므로
            # 여기서 보는 것은 "체결됐는데 취소로 덮였는가"다 — 체결이 잔고를 건드린 뒤
            # 취소가 status만 되돌리면 정확히 그 모양이 된다).
            row = db.get(Order, order["id"])
            filled_but_canceled = row.status == "canceled" and row.fee > 0
        assert not filled_but_canceled, f"체결 수수료가 찍힌 주문이 취소 상태다: {after!r}"
