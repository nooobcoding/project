"""체결 후처리의 자동매매 훅 검증 (09-execution-engine.md 3.2절 5단계, 07 계획 Step 2B).

이 훅은 `state.position`을 쓰는 유일한 주체다. 검증 포인트는 두 가지:
  - source='auto' 체결만 포지션을 건드리고, 수동 체결은 절대 건드리지 않는다.
  - 포지션 갱신이 체결과 같은 트랜잭션에서 확정된다(주문이 filled인데 포지션이 비어 있거나
    그 반대인 상태가 생기지 않는다).
"""

from decimal import Decimal

from sqlalchemy import select

from app.database import session_scope
from app.models import Notification, Order
from app.services.matcher import _format_quantity
from app.services.orders import create_order
from tests.conftest import load_slot_state, requires_db

PRICE = Decimal("100000")
FEE_INCLUSIVE_PRICE = Decimal("100050.00000000")  # 100,000 × 1.0005 (01-erd.md 3.2절)


def _auto_order(user_id, coin_symbol, slot_id, side, quantity) -> str:
    """워커가 내는 것과 같은 형태의 주문(시장가·source=auto)을 넣고 체결 상태를 돌려준다.

    ORM 객체를 그대로 반환하면 세션이 닫힌 뒤 속성 접근에서 DetachedInstanceError가 나므로
    필요한 값만 뽑아 나온다.
    """
    with session_scope() as db:
        order = create_order(
            db,
            user_id=user_id,
            coin_symbol=coin_symbol,
            side=side,
            order_type="market",
            quantity=quantity,
            source="auto",
            strategy_slot_id=slot_id,
        )
        return order.status


def test_format_quantity_trims_trailing_zeros():
    """알림 문구의 수량 표시 — NUMERIC(28,8)이라 그대로 쓰면 '2.00000000'처럼 나온다."""
    assert _format_quantity(Decimal("0.00093393")) == "0.00093393"
    assert _format_quantity(Decimal("1.50000000")) == "1.5"


def test_format_quantity_keeps_integers_out_of_scientific_notation():
    """Decimal.normalize()만 쓰면 정수 수량이 '1E+2'가 되어 사용자에게 그대로 노출된다."""
    assert _format_quantity(Decimal("100.00000000")) == "100"


@requires_db
def test_auto_buy_fill_opens_position(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)

    status = _auto_order(test_user, test_coin, slot_id, "buy", Decimal("2"))

    assert status == "filled"
    position = load_slot_state(slot_id)["position"]
    assert Decimal(position["quantity"]) == Decimal("2")
    # 평단은 수수료 포함 취득원가여야 holdings.avg_buy_price와 어긋나지 않는다.
    assert Decimal(position["avg_price"]) == FEE_INCLUSIVE_PRICE


@requires_db
def test_auto_buy_accumulates_into_existing_position(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)

    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("1"))
    set_price(Decimal("200000"))
    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("1"))

    position = load_slot_state(slot_id)["position"]
    assert Decimal(position["quantity"]) == Decimal("2")
    # (100,050 + 200,100) / 2 = 150,075
    assert Decimal(position["avg_price"]) == Decimal("150075.00000000")


@requires_db
def test_auto_sell_partial_keeps_average_price(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)
    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("3"))

    _auto_order(test_user, test_coin, slot_id, "sell", Decimal("1"))

    position = load_slot_state(slot_id)["position"]
    assert Decimal(position["quantity"]) == Decimal("2")
    assert Decimal(position["avg_price"]) == FEE_INCLUSIVE_PRICE


@requires_db
def test_auto_sell_full_clears_position(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)
    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("2"))

    _auto_order(test_user, test_coin, slot_id, "sell", Decimal("2"))

    assert "position" not in load_slot_state(slot_id)


@requires_db
def test_manual_fill_never_touches_position(make_slot, test_user, test_coin, set_price):
    """수동 체결은 슬롯 포지션과 무관하다 — 슬롯이 산 몫만 슬롯이 관리한다 (07 4.2절).

    슬롯을 OFF로 두는 이유: ON이면 애초에 수동 주문 자체가 잠긴다 (FR-M10).
    """
    slot_id = make_slot(is_active=False)
    set_price(PRICE)

    with session_scope() as db:
        create_order(
            db,
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="market",
            quantity=Decimal("2"),
            source="manual",
        )

    assert "position" not in load_slot_state(slot_id)


@requires_db
def test_auto_fill_records_notification_linked_to_slot(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)

    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("1"))

    with session_scope() as db:
        rows = list(
            db.execute(
                select(
                    Notification.type, Notification.strategy_slot_id, Notification.coin_symbol
                ).where(Notification.user_id == test_user)
            )
        )
    assert rows == [("signal", slot_id, test_coin)]  # 매수 체결 (07 3-C)


@requires_db
def test_auto_sell_notification_is_exit_type(make_slot, test_user, test_coin, set_price):
    slot_id = make_slot()
    set_price(PRICE)
    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("1"))

    _auto_order(test_user, test_coin, slot_id, "sell", Decimal("1"))

    with session_scope() as db:
        types = list(
            db.scalars(
                select(Notification.type)
                .where(Notification.user_id == test_user)
                .order_by(Notification.id)
            )
        )
    assert types == ["signal", "exit"]


@requires_db
def test_auto_order_is_linked_to_slot(make_slot, test_user, test_coin, set_price):
    """orders.strategy_slot_id가 채워져야 07 3-B의 슬롯별 체결 내역 필터가 성립한다."""
    slot_id = make_slot()
    set_price(PRICE)

    _auto_order(test_user, test_coin, slot_id, "buy", Decimal("1"))

    with session_scope() as db:
        row = db.execute(
            select(Order.source, Order.strategy_slot_id).where(Order.user_id == test_user)
        ).one()
    assert row == ("auto", slot_id)
