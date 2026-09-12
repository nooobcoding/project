"""지정가 체결 경로와 `pending_symbols` 힌트 검증 (확장판 5단계, 02-market-data.md 4.2절).

이 경로에는 그동안 테스트가 없었다 — 확장판에서 matcher 앞에 힌트 게이트가 생기면서,
힌트가 잘못되면 **주문이 영영 체결되지 않는데 서버는 정상으로 보이는** 실패가 가능해졌다.
그 실패를 잡는 것이 이 파일의 목적이다.

`PRICE_CACHE_BACKEND`에 따라 힌트가 켜지고 꺼지므로 양쪽 모두에서 의미가 있다:
- `memory`: 힌트를 안 쓴다 — 체결 경로 자체의 회귀 테스트
- `redis`: 힌트를 거쳐 체결된다 — 등록(SADD)이 실제로 일어났는지까지 검증
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import session_scope
from app.models import Order
from app.services import matcher, orders, pending_symbols
from tests.conftest import requires_db

LIMIT_PRICE = Decimal("1000")


def _order_status(order_id: int) -> str:
    with session_scope() as db:
        return db.get(Order, order_id).status


def _place_limit_buy(user_id: int, symbol: str) -> int:
    with session_scope() as db:
        order = orders.create_order(
            db,
            user_id=user_id,
            coin_symbol=symbol,
            side="buy",
            order_type="limit",
            price=LIMIT_PRICE,
            quantity=Decimal("1"),
            source="manual",
        )
        return order.id


@requires_db
def test_limit_order_fills_when_price_reaches(test_user, test_coin):
    """지정가 매수는 현재가가 주문가 이하로 내려오면 체결된다.

    확장판에서 matcher가 별도 프로세스로 나가도 이 절차는 그대로여야 한다
    (02-market-data.md 4.1절 — 누가 부르느냐만 바뀐다)."""
    order_id = _place_limit_buy(test_user, test_coin)
    assert _order_status(order_id) == "pending"

    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE)

    assert _order_status(order_id) == "filled"


@requires_db
def test_limit_order_stays_pending_above_limit(test_user, test_coin):
    """조건이 안 맞으면 그대로 미체결로 남는다."""
    order_id = _place_limit_buy(test_user, test_coin)

    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE + Decimal("1"))

    assert _order_status(order_id) == "pending"


@requires_db
def test_pending_symbols_tracks_order_lifecycle(test_user, test_coin):
    """주문을 내면 힌트에 올라가고, 체결되면 내려간다.

    **없는데 있다고 하는 것은 무해하지만, 있는데 없다고 하면 그 주문은 영영 체결되지
    않는다.** 그래서 등록 쪽을 특히 본다.
    """
    if not pending_symbols._enabled():
        pytest.skip("힌트는 redis 백엔드에서만 동작한다 (PRICE_CACHE_BACKEND=redis)")

    order_id = _place_limit_buy(test_user, test_coin)
    assert pending_symbols.has_pending(test_coin) is True

    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE)

    assert _order_status(order_id) == "filled"
    assert pending_symbols.has_pending(test_coin) is False


@requires_db
def test_rebuild_recovers_lost_hint(test_user, test_coin):
    """힌트가 통째로 날아가도(Redis 유실·SADD 누락) 재구성이 복구한다.

    복구 전에는 matcher가 DB를 아예 안 보므로 체결되지 않는다는 것까지 확인한다 — 이게
    `scheduler`의 주기적 재구성을 "반드시 함께 넣는다"고 못 박은 이유다.
    """
    if not pending_symbols._enabled():
        pytest.skip("힌트는 redis 백엔드에서만 동작한다 (PRICE_CACHE_BACKEND=redis)")

    order_id = _place_limit_buy(test_user, test_coin)

    from app.services.redis_client import get_redis

    get_redis().delete(pending_symbols.KEY)
    assert pending_symbols.has_pending(test_coin) is False

    # 힌트가 비어 있으면 체결 조건이 맞아도 매칭이 DB를 보지 않는다.
    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE)
    assert _order_status(order_id) == "pending"

    pending_symbols.rebuild()
    assert pending_symbols.has_pending(test_coin) is True

    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE)
    assert _order_status(order_id) == "filled"


@requires_db
def test_pending_symbols_survives_other_open_orders(test_user, test_coin):
    """같은 심볼에 다른 미체결이 남아 있으면 힌트에서 빼면 안 된다."""
    if not pending_symbols._enabled():
        pytest.skip("힌트는 redis 백엔드에서만 동작한다 (PRICE_CACHE_BACKEND=redis)")

    fillable = _place_limit_buy(test_user, test_coin)
    # 체결 조건이 안 맞는 주문을 하나 더 남겨 둔다.
    with session_scope() as db:
        orders.create_order(
            db,
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="limit",
            price=Decimal("1"),
            quantity=Decimal("1"),
            source="manual",
        )

    matcher.run_matching_for_symbol(test_coin, LIMIT_PRICE)

    assert _order_status(fillable) == "filled"
    assert pending_symbols.has_pending(test_coin) is True  # 남은 주문이 있으므로 유지

    with session_scope() as db:
        remaining = db.scalar(
            select(Order.id).where(Order.coin_symbol == test_coin, Order.status == "pending")
        )
    assert remaining is not None
