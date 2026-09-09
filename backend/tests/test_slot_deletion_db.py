"""거래 이력이 있는 슬롯의 삭제 회귀 테스트 (07 Step 2B 실기동 검증에서 발견한 버그).

`orders.strategy_slot_id` FK를 삭제 동작 지정 없이(RESTRICT) 만들어 두는 바람에 **한 번이라도
체결된 슬롯은 삭제가 500으로 실패**했고, 같은 이유로 자동매매를 써 본 계정은 회원 탈퇴까지
실패했다. Step 2A 테스트는 거래 이력이 없는 슬롯만 지워봐서 이 결함을 놓쳤다 —
그래서 "체결이 있는 상태"를 명시적으로 만들어 두 경로를 모두 검증한다 (마이그레이션
a69df04a6703에서 ON DELETE SET NULL로 수정).
"""

from decimal import Decimal

from sqlalchemy import func, select

from app.database import session_scope
from app.models import Notification, Order, User
from app.services.account import delete_account
from app.services.orders import create_order
from app.services.strategy_slots import delete_slot
from tests.conftest import requires_db

PRICE = Decimal("100000")


def _fill_auto_order(user_id, coin_symbol, slot_id):
    with session_scope() as db:
        create_order(
            db,
            user_id=user_id,
            coin_symbol=coin_symbol,
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            source="auto",
            strategy_slot_id=slot_id,
        )


@requires_db
def test_delete_slot_with_trade_history_keeps_orders(make_slot, test_user, test_coin, set_price):
    """체결 이력이 있어도 슬롯을 지울 수 있고, 주문 기록은 남되 연결만 끊긴다."""
    slot_id = make_slot()
    set_price(PRICE)
    _fill_auto_order(test_user, test_coin, slot_id)

    with session_scope() as db:
        result = delete_slot(db, test_user, slot_id)

    assert result.coin_symbol == test_coin
    assert result.remaining_quantity == Decimal("1")  # 수동 보유분으로 남는다는 안내용 (07 4.2절)

    with session_scope() as db:
        rows = list(
            db.execute(
                select(Order.source, Order.strategy_slot_id).where(Order.user_id == test_user)
            )
        )
    assert rows == [("auto", None)]


@requires_db
def test_delete_slot_keeps_notifications(make_slot, test_user, test_coin, set_price):
    """알림도 같은 이유로 남는다 — 지난 알림 기록이 슬롯 삭제로 사라지면 안 된다."""
    slot_id = make_slot()
    set_price(PRICE)
    _fill_auto_order(test_user, test_coin, slot_id)

    with session_scope() as db:
        delete_slot(db, test_user, slot_id)

    with session_scope() as db:
        rows = list(
            db.execute(
                select(Notification.type, Notification.strategy_slot_id).where(
                    Notification.user_id == test_user
                )
            )
        )
    assert rows == [("signal", None)]


@requires_db
def test_delete_account_works_after_auto_trading(make_slot, test_user, test_coin, set_price):
    """회원 탈퇴(users CASCADE)가 자동매매 이력이 있는 계정에서도 동작해야 한다 (01-erd.md 3.4절)."""
    slot_id = make_slot()
    set_price(PRICE)
    _fill_auto_order(test_user, test_coin, slot_id)

    with session_scope() as db:
        delete_account(db, db.get(User, test_user))

    with session_scope() as db:
        assert db.get(User, test_user) is None
        remaining = db.scalar(
            select(func.count()).select_from(Order).where(Order.user_id == test_user)
        )
    assert remaining == 0
