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
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import session_scope
from app.models import StrategySlot
from app.services.orders import CoinLockedByAutoTradingError, InsufficientBalanceError, create_order
from app.services.strategy_slots import DuplicateActiveSlotError, toggle_slot
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
