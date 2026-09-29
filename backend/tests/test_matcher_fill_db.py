"""services/matcher.py 체결 후처리 — 09-execution-engine.md 3장.

지금까지 auto 훅(test_matcher_auto_hook.py)만 검증돼 있었고 체결 루프 본체는 미검증이었다.
여기서 보는 것은 크게 셋이다:

1. **체결 규칙표**(3장) — 조건·체결가·부분체결 없음
2. **중복 체결/취소 경합**(3.1, 3.3) — 조건부 UPDATE가 실제로 XOR을 만드는가
3. **자금 정합성** — `realized_profit`(화면에 보이는 손익)이 실제 잔고 변화와 일치하는가.
   이 둘이 어긋나면 아무도 예외를 못 보고 손익만 조용히 틀린다.
"""

import threading
from decimal import Decimal

from sqlalchemy import select

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Balance, Holding, Notification, Order
from app.services import matcher
from app.services.orders import cancel_order, create_order
from app.services.wallet import withdraw
from app.strategy_engine import costs
from tests.conftest import requires_db

PRICE = Decimal("100000")
QUANTITY = Decimal("0.1")


def _balance(user_id) -> Decimal:
    with session_scope() as db:
        return db.get(Balance, user_id).krw_balance


def _holding(user_id, coin) -> tuple[Decimal, Decimal]:
    with session_scope() as db:
        row = db.get(Holding, (user_id, coin))
        return (Decimal(0), Decimal(0)) if row is None else (row.quantity, row.avg_buy_price)


def _order_row(order_id) -> dict:
    with session_scope() as db:
        order = db.get(Order, order_id)
        return {
            "status": order.status,
            "price": order.price,
            "quantity": order.quantity,
            "fee": order.fee,
            "realized_profit": order.realized_profit,
            "filled_at": order.filled_at,
        }


def _place_limit(user_id, coin, side, price, quantity=QUANTITY) -> int:
    with session_scope() as db:
        return create_order(
            db,
            user_id=user_id,
            coin_symbol=coin,
            side=side,
            order_type="limit",
            quantity=quantity,
            price=price,
            source="manual",
        ).id


def _place_market(user_id, coin, side, quantity=QUANTITY) -> int:
    with session_scope() as db:
        return create_order(
            db,
            user_id=user_id,
            coin_symbol=coin,
            side=side,
            order_type="market",
            quantity=quantity,
            source="manual",
        ).id


# ------------------------------------------------------------------ 3장 체결 규칙표


@requires_db
def test_limit_buy_fills_at_order_price_not_market_price(test_user, test_coin, set_price):
    """매수 지정가는 현재가가 더 낮아도 **주문가**로 체결된다 (3장 표).

    현재가로 체결하면 사용자에게 유리하지만 명세와 다르고, 동결액(주문가 기준)과 실제
    차감액이 어긋나 가용 원화 계산이 틀어진다.
    """
    set_price(PRICE)
    order_id = _place_limit(test_user, test_coin, "buy", PRICE)
    before = _balance(test_user)

    matcher.run_matching_for_symbol(test_coin, PRICE - 10000)  # 현재가가 지정가보다 낮다

    row = _order_row(order_id)
    assert row["status"] == "filled"
    assert row["price"] == PRICE, "지정가가 아니라 현재가로 체결됐다"
    assert _balance(test_user) == before - costs.calc_buy_amount(PRICE, QUANTITY, TRADING_FEE_RATE)


@requires_db
def test_limit_buy_does_not_fill_above_order_price(test_user, test_coin, set_price):
    set_price(PRICE)
    order_id = _place_limit(test_user, test_coin, "buy", PRICE)

    matcher.run_matching_for_symbol(test_coin, PRICE + 1)

    assert _order_row(order_id)["status"] == "pending"


@requires_db
def test_limit_sell_fills_at_or_above_order_price(test_user, test_coin, set_price):
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")
    order_id = _place_limit(test_user, test_coin, "sell", PRICE + 10000)

    matcher.run_matching_for_symbol(test_coin, PRICE + 9999)
    assert _order_row(order_id)["status"] == "pending"

    matcher.run_matching_for_symbol(test_coin, PRICE + 10000)
    row = _order_row(order_id)
    assert row["status"] == "filled"
    assert row["price"] == PRICE + 10000


@requires_db
def test_market_order_fills_at_cached_price(test_user, test_coin, set_price):
    """시장가는 주문 접수 시점의 시세 캐시 현재가로 즉시 체결된다 (3장 표)."""
    set_price(PRICE)
    order_id = _place_market(test_user, test_coin, "buy")

    row = _order_row(order_id)
    assert row["status"] == "filled"
    assert row["price"] == PRICE
    assert row["filled_at"] is not None


@requires_db
def test_fill_moves_entire_quantity_no_partial_fill(test_user, test_coin, set_price):
    """부분체결은 지원하지 않는다 (3장) — 체결되면 주문 수량 전부가 보유로 넘어간다."""
    set_price(PRICE)
    quantity = Decimal("0.37")
    order_id = _place_limit(test_user, test_coin, "buy", PRICE, quantity=quantity)

    matcher.run_matching_for_symbol(test_coin, PRICE)

    assert _order_row(order_id)["quantity"] == quantity
    held, _ = _holding(test_user, test_coin)
    assert held == quantity


# ------------------------------------------------------------------ 3.1/3.3 중복·취소 경합


@requires_db
def test_double_fill_of_same_order_moves_money_once(test_user, test_coin, set_price):
    """같은 주문을 두 번 체결 시도하면 두 번째는 아무것도 하지 않아야 한다 (조건부 UPDATE)."""
    set_price(PRICE)
    order_id = _place_limit(test_user, test_coin, "buy", PRICE)
    before = _balance(test_user)

    with session_scope() as db:
        first = matcher.fill_order(db, db.get(Order, order_id), fill_price=PRICE)
    with session_scope() as db:
        second = matcher.fill_order(db, db.get(Order, order_id), fill_price=PRICE)

    assert first is True
    assert second is False, "이미 체결된 주문이 또 체결됐다"
    assert _balance(test_user) == before - costs.calc_buy_amount(PRICE, QUANTITY, TRADING_FEE_RATE)
    held, _ = _holding(test_user, test_coin)
    assert held == QUANTITY, "보유수량이 두 번 가산됐다"


@requires_db
def test_concurrent_fill_and_cancel_resolve_to_exactly_one(test_user, test_coin, set_price):
    """체결과 취소가 동시에 들어오면 정확히 하나만 성립한다 (3.3절).

    둘 다 성립하면 잔고는 차감됐는데 주문은 취소로 남아 동결분이 이중으로 풀린다.
    """
    set_price(PRICE)

    for _ in range(5):
        order_id = _place_limit(test_user, test_coin, "buy", PRICE)
        before = _balance(test_user)
        barrier = threading.Barrier(2)
        outcomes: dict[str, object] = {}
        errors: list[Exception] = []

        def _fill():
            barrier.wait()
            try:
                with session_scope() as db:
                    outcomes["filled"] = matcher.fill_order(
                        db, db.get(Order, order_id), fill_price=PRICE
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def _cancel():
            barrier.wait()
            try:
                with session_scope() as db:
                    cancel_order(db, test_user, order_id)
                outcomes["canceled"] = True
            except Exception as exc:
                outcomes["canceled"] = False
                if type(exc).__name__ != "OrderNotCancelableError":
                    errors.append(exc)

        threads = [threading.Thread(target=_fill), threading.Thread(target=_cancel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"예상 못 한 예외 누출: {errors!r}"
        assert outcomes.get("filled") is not outcomes.get("canceled"), (
            f"체결과 취소가 동시에 성립했다: {outcomes!r}"
        )

        row = _order_row(order_id)
        after = _balance(test_user)
        if row["status"] == "filled":
            assert after == before - costs.calc_buy_amount(PRICE, QUANTITY, TRADING_FEE_RATE)
        else:
            assert row["status"] == "canceled"
            assert after == before, "취소됐는데 잔고가 움직였다"


# ------------------------------------------------------------------ 3.2 후처리 정확성


@requires_db
def test_realized_profit_uses_avg_before_holdings_update(test_user, test_coin, set_price):
    """매도 실현손익은 holdings 갱신 **직전** 평단으로 계산해야 한다 (3.2절 3번).

    갱신 후 값을 쓰면 전량 매도 시 평단이 0으로 리셋된 뒤라 손익이 매도대금 전액이 된다 —
    예외 하나 없이 손익만 조용히 틀린다.
    """
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")
    _, avg_before = _holding(test_user, test_coin)

    sell_price = PRICE + 20000
    set_price(sell_price)
    sell_id = _place_market(test_user, test_coin, "sell")

    expected = costs.calc_realized_profit(sell_price, QUANTITY, avg_before, TRADING_FEE_RATE)
    assert _order_row(sell_id)["realized_profit"] == expected.quantize(Decimal("0.0001"))


@requires_db
def test_buy_average_includes_fee_in_cost_basis(test_user, test_coin, set_price):
    """매수 평단은 수수료 포함 취득원가 기준 가중평균이다 (01-erd.md 3.2절)."""
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")

    second_price = PRICE + 50000
    set_price(second_price)
    _place_market(test_user, test_coin, "buy")

    quantity, avg = _holding(test_user, test_coin)
    total_cost = costs.calc_buy_amount(PRICE, QUANTITY, TRADING_FEE_RATE) + costs.calc_buy_amount(
        second_price, QUANTITY, TRADING_FEE_RATE
    )
    assert quantity == QUANTITY * 2
    assert abs(avg - total_cost / (QUANTITY * 2)) < Decimal("0.00000001")


@requires_db
def test_partial_sell_keeps_average_unchanged(test_user, test_coin, set_price):
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy", quantity=Decimal("0.2"))
    _, avg_before = _holding(test_user, test_coin)

    _place_market(test_user, test_coin, "sell", quantity=Decimal("0.05"))

    quantity, avg_after = _holding(test_user, test_coin)
    assert quantity == Decimal("0.15")
    assert avg_after == avg_before, "부분 매도가 평단을 바꿨다"


@requires_db
def test_full_sell_keeps_row_and_resets_average(test_user, test_coin, set_price):
    """전량 매도 후 holdings 행은 남고 평단은 0으로 리셋된다 (모델 docstring)."""
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")
    _place_market(test_user, test_coin, "sell")

    with session_scope() as db:
        row = db.get(Holding, (test_user, test_coin))
        exists = row is not None
        quantity = row.quantity if row else None
        avg = row.avg_buy_price if row else None

    assert exists, "전량 매도로 보유 행이 삭제됐다"
    assert quantity == Decimal(0)
    assert avg == Decimal(0)


@requires_db
def test_rebuy_after_full_sell_does_not_inherit_old_average(test_user, test_coin, set_price):
    """재매수 평단에 옛 평단이 섞이면 안 된다 — 0으로 리셋해 두는 이유가 이것이다."""
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")
    _place_market(test_user, test_coin, "sell")

    rebuy_price = Decimal("200000")
    set_price(rebuy_price)
    _place_market(test_user, test_coin, "buy")

    _, avg = _holding(test_user, test_coin)
    expected = costs.calc_buy_amount(rebuy_price, QUANTITY, TRADING_FEE_RATE) / QUANTITY
    assert abs(avg - expected) < Decimal("0.00000001"), f"옛 평단이 섞였다: {avg}"


@requires_db
def test_manual_fill_creates_no_notification(test_user, test_coin, set_price):
    """알림 적재는 source='auto' 체결에만 있다 (3.2절 6번) — 수동 체결은 남기지 않는다."""
    set_price(PRICE)
    _place_market(test_user, test_coin, "buy")

    with session_scope() as db:
        count = len(list(db.scalars(select(Notification).where(Notification.user_id == test_user))))

    assert count == 0


# ------------------------------------------------------------------ 경로 동일성 (1장)


@requires_db
def test_market_and_limit_paths_produce_identical_downstream(test_user, test_coin, set_price):
    """같은 거래면 시장가로 했든 지정가로 했든 잔고·보유·손익이 같아야 한다 (1장).

    시장가는 create_order 트랜잭션 안에서, 지정가는 매칭 루프에서 체결된다 — 진입 경로가
    다르므로 후처리가 갈라질 수 있는 지점이다.
    """
    set_price(PRICE)

    # (1) 시장가 경로로 매수→매도 한 바퀴
    base = _balance(test_user)
    _place_market(test_user, test_coin, "buy")
    sell_price = PRICE + 20000
    set_price(sell_price)
    market_sell_id = _place_market(test_user, test_coin, "sell")
    market_delta = _balance(test_user) - base
    market_profit = _order_row(market_sell_id)["realized_profit"]

    # (2) 같은 거래를 지정가 경로로
    set_price(PRICE)
    base = _balance(test_user)
    buy_id = _place_limit(test_user, test_coin, "buy", PRICE)
    matcher.run_matching_for_symbol(test_coin, PRICE)
    sell_id = _place_limit(test_user, test_coin, "sell", sell_price)
    matcher.run_matching_for_symbol(test_coin, sell_price)
    limit_delta = _balance(test_user) - base
    limit_profit = _order_row(sell_id)["realized_profit"]

    assert _order_row(buy_id)["status"] == "filled"
    assert limit_delta == market_delta, "경로에 따라 잔고 변화가 다르다"
    assert limit_profit == market_profit, "경로에 따라 실현손익이 다르다"


# ------------------------------------------------------------------ 자금 정합성


@requires_db
def test_realized_profit_matches_actual_balance_change_on_round_trip(
    test_user, test_coin, set_price
):
    """포지션을 완전히 청산하면 Σ실현손익 == 실제 잔고 변화여야 한다.

    화면의 손익과 통장이 따로 노는 것을 막는 핵심 불변식이다. 평단은 나눗셈으로 구해 8자리에서
    반올림되고 잔고·손익 컬럼도 4자리라, 완전 일치가 아니라 **반올림 한계 안**인지를 본다.
    """
    set_price(PRICE)
    base = _balance(test_user)

    # 서로 다른 가격에 두 번 사고, 두 번에 나눠 판다 (평단 나눗셈과 부분매도를 모두 태운다).
    _place_market(test_user, test_coin, "buy", quantity=Decimal("0.07"))
    set_price(Decimal("133333.33"))
    _place_market(test_user, test_coin, "buy", quantity=Decimal("0.03"))

    set_price(Decimal("155555.55"))
    sell_a = _place_market(test_user, test_coin, "sell", quantity=Decimal("0.04"))
    set_price(Decimal("99999.99"))
    sell_b = _place_market(test_user, test_coin, "sell", quantity=Decimal("0.06"))

    quantity, _ = _holding(test_user, test_coin)
    assert quantity == Decimal(0), "청산이 안 끝났다"

    total_profit = _order_row(sell_a)["realized_profit"] + _order_row(sell_b)["realized_profit"]
    balance_delta = _balance(test_user) - base

    assert abs(total_profit - balance_delta) < Decimal("0.01"), (
        f"실현손익 합({total_profit})과 잔고 변화({balance_delta})가 어긋난다"
    )


@requires_db
def test_recorded_fee_stays_within_rounding_bound_of_actual_deduction(
    test_user, test_coin, set_price
):
    """`orders.fee`(4자리 반올림)와 실제 차감에 쓰인 수수료의 괴리는 건당 0.00005원 이내다.

    집계 화면이 `SUM(orders.fee)`를 쓰면 이 오차가 쌓인다 — 그래서 이 값이 표시용이라는 것을
    여기에 못박아 둔다 (matcher._calculate_fee 주석).
    """
    set_price(PRICE)
    awkward_price = Decimal("123456.789")
    set_price(awkward_price)

    order_ids = [
        _place_market(test_user, test_coin, "buy", quantity=Decimal("0.00000007"))
        for _ in range(5)
    ]

    for order_id in order_ids:
        row = _order_row(order_id)
        exact = costs.calc_fee(awkward_price, row["quantity"], TRADING_FEE_RATE)
        assert abs(row["fee"] - exact) <= Decimal("0.00005"), (
            f"수수료 기록 오차가 반올림 한계를 넘었다: 기록={row['fee']}, 정확값={exact}"
        )


@requires_db
def test_pending_buy_freeze_survives_withdrawal_so_fill_cannot_overdraw(
    test_user, test_coin, set_price
):
    """미체결 매수가 있는 상태에서 최대한 출금한 뒤 그 주문이 체결돼도 잔고가 음수면 안 된다.

    출금 가능액이 미체결 동결분을 빼고 계산되는지를 **체결까지 이어서** 확인하는 교차 검증이다.
    한쪽만 맞고 다른 쪽이 틀리면 잔고가 마이너스로 내려간다.
    """
    set_price(PRICE)
    _place_limit(test_user, test_coin, "buy", PRICE)

    with session_scope() as db:
        from app.services.wallet import get_withdrawable_krw

        withdrawable = get_withdrawable_krw(db, test_user)
        withdraw(db, test_user, withdrawable, None)

    matcher.run_matching_for_symbol(test_coin, PRICE)

    final = _balance(test_user)
    assert final >= 0, f"체결 후 잔고가 음수가 됐다: {final}"
