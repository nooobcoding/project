"""동시 요청 경합 회귀 테스트 (Step 3 착수 전 통합 점검에서 발견).

체크-후-잠금(check-then-lock) 순서로 짜인 코드는 두 요청이 겹치면 각자 "아직 괜찮다"를 보고
통과한 뒤 커밋 시점에야 DB 제약(부분 유니크 인덱스)에 걸린다 — 그 결과가 서비스가 정의한
친절한 예외(DuplicateActiveSlotError 등)가 아니라 raw `IntegrityError`(→ 처리 안 된 500)로
새어나가는 것이 진짜 버그다. `services/strategy_slots.py::toggle_slot`과
`services/orders.py::create_order`를 "잠금을 먼저, 검사를 그 뒤에"로 재정렬해 고쳤고, 이
테스트는 실제 스레드로 두 요청을 동시에 흘려보내 그 재정렬이 실제로 직렬화하는지 검증한다.

`threading.Barrier`로 두 스레드의 시작 시각만 맞춘다 — 그 뒤의 직렬화는 인위적인 지연이 아니라
실제 `SELECT ... FOR UPDATE` 잠금이 만드는 것이므로, 이 테스트의 통과 여부는 스레드 스케줄링
운(flaky)에 기대지 않는다.
"""

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Balance, Holding, Order, StrategySlot
from app.services import matcher, slot_state
from app.services.orders import (
    CoinLockedByAutoTradingError,
    InsufficientBalanceError,
    InsufficientHoldingError,
    create_order,
)
from app.services.strategy_slots import DuplicateActiveSlotError, delete_slot, toggle_slot
from app.strategy_engine import costs
from tests.conftest import requires_db

PRICE = Decimal("100000")


def _run_concurrently(*funcs):
    """각 함수를 별 스레드에서 동시에 시작하고 (결과, 예외) 쌍의 리스트로 모은다."""
    barrier = threading.Barrier(len(funcs))
    results: list[tuple[object, Exception | None]] = [(None, None)] * len(funcs)

    def _wrapper(index, func):
        barrier.wait()
        try:
            results[index] = (func(), None)
        except Exception as exc:  # noqa: BLE001 — 테스트가 예외 종류 자체를 검사해야 한다
            results[index] = (None, exc)

    threads = [threading.Thread(target=_wrapper, args=(i, f)) for i, f in enumerate(funcs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _race(*funcs):
    """`_run_concurrently`와 같지만 barrier를 각 함수에 넘겨준다.

    세션·커넥션 확보처럼 시간이 들쭉날쭉한 준비 작업을 barrier "앞"에서 끝내게 해, 정작
    경합을 봐야 할 구간만 같은 순간에 시작시킨다. 커넥션 풀이 첫 연결을 맺는 수 밀리초가
    그대로 경합 창 크기와 맞먹어서, 준비까지 barrier 뒤에 두면 경합이 재현되지 않는다.
    """
    barrier = threading.Barrier(len(funcs))
    results: list[tuple[object, Exception | None]] = [(None, None)] * len(funcs)

    def _wrapper(index, func):
        try:
            results[index] = (func(barrier), None)
        except Exception as exc:  # noqa: BLE001 — 테스트가 예외 종류 자체를 검사해야 한다
            results[index] = (None, exc)

    threads = [threading.Thread(target=_wrapper, args=(i, f)) for i, f in enumerate(funcs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@requires_db
def test_concurrent_toggle_on_same_coin_serializes_cleanly(make_slot):
    """같은 코인에 두 슬롯을 동시에 ON하면 정확히 하나만 성공하고, 나머지는 raw 500이 아니라
    DuplicateActiveSlotError여야 한다."""
    slot_a = make_slot(is_active=False, strategy_type="trend", indicator="ma")
    slot_b = make_slot(
        is_active=False,
        strategy_type="counter_trend",
        indicator="rsi",
        params={"interval": "1d", "period": 14, "oversold": 30, "overbought": 70},
    )
    with session_scope() as db:
        user_id = db.get(StrategySlot, slot_a).user_id

    def _toggle(slot_id):
        with session_scope() as db:
            return toggle_slot(db, user_id, slot_id, True).is_active

    results = _run_concurrently(lambda: _toggle(slot_a), lambda: _toggle(slot_b))

    successes = [r for r, e in results if e is None]
    failures = [e for r, e in results if e is not None]

    assert len(successes) == 1
    assert len(failures) == 1
    # 정확히 DuplicateActiveSlotError여야 한다 — IntegrityError 등 다른 예외가 새어나오면 실패.
    assert isinstance(failures[0], DuplicateActiveSlotError)

    with session_scope() as db:
        active_ids = list(
            db.scalars(
                select(StrategySlot.id).where(
                    StrategySlot.id.in_([slot_a, slot_b]), StrategySlot.is_active
                )
            )
        )
    assert len(active_ids) == 1  # 부분 유니크 인덱스가 지키려던 제약이 실제로 지켜졌다


@requires_db
def test_concurrent_toggle_never_raises_raw_integrity_error(make_slot):
    """여러 번 반복해도 매번 깨끗하게 직렬화되는지 확인 — 스레드 스케줄링에 따라 어느 쪽이
    이기는지는 매번 다를 수 있으므로 반복해서 "항상 정확히 1승 1패"만 확인한다."""
    for _ in range(5):
        slot_a = make_slot(is_active=False, strategy_type="trend", indicator="ma")
        slot_b = make_slot(
            is_active=False,
            strategy_type="counter_trend",
            indicator="rsi",
            params={"interval": "1d", "period": 14, "oversold": 30, "overbought": 70},
        )
        with session_scope() as db:
            user_id = db.get(StrategySlot, slot_a).user_id

        def _toggle(slot_id):
            with session_scope() as db:
                return toggle_slot(db, user_id, slot_id, True).is_active

        results = _run_concurrently(lambda sa=slot_a: _toggle(sa), lambda sb=slot_b: _toggle(sb))
        successes = [r for r, e in results if e is None]
        failures = [e for r, e in results if e is not None]

        assert len(successes) == 1, results
        assert len(failures) == 1 and isinstance(failures[0], DuplicateActiveSlotError), results

        # 다음 반복을 위해 끄고 정리한다 (make_slot이 만든 두 슬롯 모두 지운다).
        with session_scope() as db:
            for sid in (slot_a, slot_b):
                slot = db.get(StrategySlot, sid)
                if slot is not None:
                    db.delete(slot)


@requires_db
def test_concurrent_manual_buy_and_toggle_on_never_crashes(make_slot, test_user, test_coin, set_price):
    """수동 매수와 슬롯 ON이 같은 코인에서 동시에 들어와도 처리되지 않은 예외가 새어나오면 안 된다.

    둘 중 어느 쪽이 잠금을 먼저 잡느냐에 따라 "매수 성공 + 슬롯 ON 성공"(매수가 먼저 잠금을
    잡아 그 시점엔 아직 안 잠겨 있었으므로 정상) 또는 "매수가 CoinLockedByAutoTradingError로
    거부"(슬롯이 먼저 커밋) 둘 다 유효한 결과다 — balances 잠금이 두 트랜잭션을 완전히
    직렬화하므로 어느 쪽이 이기든 self-consistent해야 하고, 중간 상태(raw IntegrityError 등)는
    나오면 안 된다.
    """
    for _ in range(5):
        slot_id = make_slot(is_active=False, strategy_type="trend", indicator="ma")
        set_price(PRICE)

        def _toggle():
            with session_scope() as db:
                return toggle_slot(db, test_user, slot_id, True).is_active

        def _buy():
            with session_scope() as db:
                order = create_order(
                    db,
                    user_id=test_user,
                    coin_symbol=test_coin,
                    side="buy",
                    order_type="market",
                    quantity=Decimal("0.1"),
                    source="manual",
                )
                return order.status

        results = _run_concurrently(_toggle, _buy)

        for result, exc in results:
            if exc is not None:
                assert isinstance(
                    exc, (CoinLockedByAutoTradingError, InsufficientBalanceError)
                ), f"예상 못 한 예외 누출: {exc!r}"

        with session_scope() as db:
            slot = db.get(StrategySlot, slot_id)
            slot.is_active = False
            db.flush()


FILL_QUANTITY = Decimal("0.1")


def _make_pending_buy(user_id: int, coin_symbol: str) -> int:
    """즉시 체결되지 않는 미체결 매수 주문 1건을 만들어 id를 돌려준다.

    지정가로 만드는 이유는 생성 시점에 체결이 일어나지 않게 하기 위해서다 — 경합을 봐야 할
    구간은 `fill_order`뿐이므로 생성은 순차로 끝내 놓는다.
    """
    with session_scope() as db:
        order = create_order(
            db,
            user_id=user_id,
            coin_symbol=coin_symbol,
            side="buy",
            order_type="limit",
            quantity=FILL_QUANTITY,
            price=PRICE,
            source="manual",
        )
        return order.id


def _fill_at_barrier(barrier, order_id):
    """barrier 앞에서 세션·커넥션을 확보하고, 체결만 다른 스레드와 같은 순간에 시작한다."""
    with session_scope() as db:
        order = db.get(Order, order_id)
        barrier.wait()
        return matcher.fill_order(db, order, fill_price=PRICE)


@requires_db
def test_concurrent_fills_do_not_lose_balance_or_holding_updates(test_user, test_coin, set_price):
    """같은 유저의 체결 두 건이 동시에 일어나도 잔고 차감·보유수량 가산이 유실되면 안 된다.

    `fill_order`가 지키던 원자성은 `Order.status` 조건부 UPDATE뿐이었다 — 그건 "같은 주문의
    중복 체결"만 막지, "같은 유저의 서로 다른 주문 두 건이 동시에 잔고를 갱신하는 것"은 막지
    못한다. balances/holdings를 잠금 없이 읽어 절대값으로 UPDATE하므로, 두 체결이 겹치면
    먼저 커밋한 쪽의 차감이 나중 UPDATE에 통째로 덮여 사라진다(lost update).

    실제로 이 두 체결은 서로 다른 스레드에서 동시에 일어날 수 있다: 지정가 체결은 시세 스트림
    스레드(price_stream.py의 `asyncio.to_thread`)가, 시장가 체결은 요청 스레드(create_order)가,
    자동매매 주문은 워커 스레드가 각각 자기 세션으로 `fill_order`를 부른다.
    """
    set_price(PRICE)
    spend_per_order = costs.calc_buy_amount(PRICE, FILL_QUANTITY, TRADING_FEE_RATE)

    # holdings 행을 미리 만들어 둔다 — 행이 없는 상태의 동시 INSERT 경합은 아래 별도 테스트가
    # 다루고, 이 테스트는 "이미 있는 행을 동시에 갱신"하는 lost update만 본다.
    warmup_order_id = _make_pending_buy(test_user, test_coin)
    with session_scope() as db:
        matcher.fill_order(db, db.get(Order, warmup_order_id), fill_price=PRICE)

    for attempt in range(5):
        order_ids = [_make_pending_buy(test_user, test_coin) for _ in range(2)]

        with session_scope() as db:
            balance_before = db.get(Balance, test_user).krw_balance
            quantity_before = db.get(Holding, (test_user, test_coin)).quantity

        results = _race(*[(lambda b, oid=oid: _fill_at_barrier(b, oid)) for oid in order_ids])

        for filled, exc in results:
            assert exc is None, f"체결 중 예상 못 한 예외: {exc!r}"
            assert filled is True, "두 주문 모두 체결되어야 한다 (서로 다른 주문이므로)"

        with session_scope() as db:
            balance_after = db.get(Balance, test_user).krw_balance
            quantity_after = db.get(Holding, (test_user, test_coin)).quantity

        assert balance_after == balance_before - spend_per_order * 2, (
            f"{attempt + 1}회차: 잔고 차감이 유실됐다 "
            f"(before={balance_before}, after={balance_after}, 건당 차감={spend_per_order})"
        )
        assert quantity_after == quantity_before + FILL_QUANTITY * 2, (
            f"{attempt + 1}회차: 보유수량 가산이 유실됐다 "
            f"(before={quantity_before}, after={quantity_after})"
        )


@requires_db
def test_concurrent_first_fills_of_a_coin_do_not_raise_raw_integrity_error(
    test_user, test_coin, set_price
):
    """그 코인을 처음 사는 두 체결이 동시에 일어나도 raw IntegrityError가 새면 안 된다.

    `_apply_holdings`는 holdings 행이 없으면 새로 만드는데, 두 체결이 겹치면 양쪽 다 "행이
    없다"를 보고 각자 INSERT해 한쪽이 holdings_pkey 유니크 위반으로 터진다 — 서비스가 정의한
    예외가 아니라 처리되지 않은 500이 새어나가고, 그 주문은 이미 status='filled'로 선점된
    뒤라 잔고·보유수량만 반영되지 않은 채 남는다.
    """
    set_price(PRICE)
    spend_per_order = costs.calc_buy_amount(PRICE, FILL_QUANTITY, TRADING_FEE_RATE)

    order_ids = [_make_pending_buy(test_user, test_coin) for _ in range(2)]
    with session_scope() as db:
        balance_before = db.get(Balance, test_user).krw_balance
        assert db.get(Holding, (test_user, test_coin)) is None, "이 테스트는 보유행이 없는 상태를 본다"

    results = _race(*[(lambda b, oid=oid: _fill_at_barrier(b, oid)) for oid in order_ids])

    for filled, exc in results:
        assert exc is None, f"체결 중 예상 못 한 예외: {exc!r}"
        assert filled is True

    with session_scope() as db:
        balance_after = db.get(Balance, test_user).krw_balance
        holding = db.get(Holding, (test_user, test_coin))
        holding_quantity = holding.quantity if holding is not None else None

    assert balance_after == balance_before - spend_per_order * 2
    assert holding_quantity == FILL_QUANTITY * 2


@requires_db
def test_fill_and_slot_deletion_do_not_deadlock(make_slot, test_user, test_coin, set_price):
    """자동매매 주문이 체결되는 그 순간 슬롯이 삭제돼도 교착하면 안 된다.

    체결은 orders 행을 먼저 선점하고 마지막에 strategy_slots(state.position)를 쓴다. 슬롯
    삭제가 strategy_slots를 먼저 잠근 뒤 FK(ON DELETE SET NULL)로 orders를 갱신하려 들면 정확히
    반대 순서가 되어 교착한다 — `delete_slot`이 참조를 먼저 끊어 양쪽 다 orders → strategy_slots
    순서가 되게 고쳤다.

    실제 체결 경로 한복판(`write_position` 직전)에서 삭제를 끼워 넣어야 이 순서가 재현되므로,
    그 지점을 감싸 삭제 스레드를 출발시킨다.
    """
    set_price(PRICE)
    slot_id = make_slot(is_active=True)

    with session_scope() as db:
        order = Order(
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="limit",
            price=PRICE,
            quantity=FILL_QUANTITY,
            status="pending",
            source="auto",
            fee=Decimal(0),
            strategy_slot_id=slot_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.flush()
        order_id = order.id

    delete_errors: list[Exception] = []

    def _delete():
        try:
            with session_scope() as db:
                delete_slot(db, test_user, slot_id)
        except Exception as exc:  # noqa: BLE001
            delete_errors.append(exc)

    deleter = threading.Thread(target=_delete)
    original_write_position = slot_state.write_position

    def _write_position_with_deletion_in_flight(db, sid, position):
        # 체결이 orders 행 잠금을 쥔 상태에서 삭제를 출발시키고, 삭제가 실제로 그 잠금을 기다리는
        # 지점까지 도달할 시간을 준다. 이 지연이 없으면 두 트랜잭션이 겹치지 않아 순서 문제가
        # 드러나지 않는다 (교착 재현에 필요한 유일한 인위적 지연이다).
        deleter.start()
        time.sleep(1)
        return original_write_position(db, sid, position)

    slot_state.write_position = _write_position_with_deletion_in_flight
    try:
        with session_scope() as db:
            filled = matcher.fill_order(db, db.get(Order, order_id), fill_price=PRICE)
    finally:
        slot_state.write_position = original_write_position
        deleter.join(timeout=30)

    assert filled is True, "체결이 교착으로 밀려나면 안 된다"
    assert delete_errors == [], f"슬롯 삭제가 실패했다: {delete_errors!r}"

    with session_scope() as db:
        assert db.get(StrategySlot, slot_id) is None
        assert db.get(Order, order_id).status == "filled"


@requires_db
def test_failed_market_fill_leaves_no_pending_order(
    monkeypatch, test_user, test_coin, set_price
):
    """시장가 체결이 실패하면 주문 행 자체가 남지 않아야 한다.

    주문을 먼저 커밋하고 체결하면, 체결이 실패했을 때 pending 시장가 주문이 남는다 — 매칭
    엔진은 지정가만 훑으므로 그 주문은 영영 체결되지 않고 가용 원화만 동결한다. 주문 insert와
    체결을 한 트랜잭션으로 묶어 "체결된 주문이 되거나, 아예 없거나" 둘 중 하나만 되게 했다.
    """
    set_price(PRICE)

    with session_scope() as db:
        balance_before = db.get(Balance, test_user).krw_balance

    def _boom(db, order):
        raise RuntimeError("체결 도중 실패")

    monkeypatch.setattr(matcher, "_apply_balance", _boom)

    with pytest.raises(RuntimeError):
        with session_scope() as db:
            create_order(
                db,
                user_id=test_user,
                coin_symbol=test_coin,
                side="buy",
                order_type="market",
                quantity=FILL_QUANTITY,
                source="manual",
            )

    with session_scope() as db:
        orders = list(db.scalars(select(Order).where(Order.user_id == test_user)))
        balance_after = db.get(Balance, test_user).krw_balance

    assert orders == [], f"체결 실패한 시장가 주문이 남았다: {orders!r}"
    assert balance_after == balance_before


@requires_db
def test_concurrent_manual_sell_and_toggle_on_never_crashes(
    make_slot, test_user, test_coin, set_price
):
    """수동 매도와 슬롯 ON이 동시에 들어와도 처리되지 않은 예외가 새어나오면 안 된다.

    매수 경로(위 테스트)와 같은 TOCTOU가 매도 경로에도 있었다 — FR-M10 체크가 balances 잠금
    없이 먼저 끝나 슬롯이 막 활성화된 코인을 수동 매도로 통과시킬 수 있었다. 매도도 balances를
    먼저 잠그도록 정렬해 두 요청이 직렬화된다.

    **이 테스트가 잡는 범위**: 잠금이 새어 "매도가 통과했는지"는 밖에서 관측할 수 없다 —
    두 트랜잭션 중 매도가 먼저 커밋된 경우와 구분이 안 되기 때문이다(매수 경로 테스트도 같은
    이유로 예외 종류만 본다). 여기서 실제로 지키는 것은 매도 경로에 balances 잠금을 새로
    추가하면서 교착이나 예상 못 한 예외가 생기지 않았다는 점이다.
    """
    set_price(PRICE)

    for _ in range(5):
        # 팔 수량을 먼저 확보한다 (활성 슬롯이 없는 상태에서 매수).
        with session_scope() as db:
            create_order(
                db,
                user_id=test_user,
                coin_symbol=test_coin,
                side="buy",
                order_type="market",
                quantity=FILL_QUANTITY,
                source="manual",
            )

        slot_id = make_slot(is_active=False, strategy_type="trend", indicator="ma")

        def _toggle():
            with session_scope() as db:
                return toggle_slot(db, test_user, slot_id, True).is_active

        def _sell():
            with session_scope() as db:
                order = create_order(
                    db,
                    user_id=test_user,
                    coin_symbol=test_coin,
                    side="sell",
                    order_type="market",
                    quantity=FILL_QUANTITY,
                    source="manual",
                )
                return order.status

        results = _run_concurrently(_toggle, _sell)

        for _, exc in results:
            if exc is not None:
                assert isinstance(
                    exc, (CoinLockedByAutoTradingError, InsufficientHoldingError)
                ), f"예상 못 한 예외 누출: {exc!r}"

        with session_scope() as db:
            db.get(StrategySlot, slot_id).is_active = False
