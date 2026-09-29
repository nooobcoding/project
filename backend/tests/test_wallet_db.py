"""services/wallet.py — 입금/출금/출금가능액 (05-deposit-withdraw.md).

memo 30자 상한은 서비스가 아니라 라우터의 Pydantic 스키마(`schemas/wallet.py`)가
강제한다 — wallet.py 자체는 memo 길이를 검사하지 않는다. 그 경계값 테스트는
TestClient가 필요하므로 Phase 2(`test_api_contract.py`)에서 다룬다.
"""

import threading
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.database import session_scope
from app.models import Balance, DepositWithdrawal
from app.services.wallet import (
    InsufficientWithdrawableError,
    InvalidAmountError,
    deposit,
    get_withdrawable_krw,
    withdraw,
)
from tests.conftest import requires_db

SEED_KRW = Decimal("10000000")  # test_user 픽스처가 심어주는 시드머니


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


def _tx_values(transaction) -> dict:
    """세션이 닫히기 전에 필요한 값만 뽑아 둔다 (DetachedInstanceError 회피)."""
    return {
        "id": transaction.id,
        "type": transaction.type,
        "amount": transaction.amount,
        "balance_after": transaction.balance_after,
        "memo": transaction.memo,
    }


@requires_db
def test_deposit_increases_balance_and_records_history(test_user):
    with session_scope() as db:
        tx = _tx_values(deposit(db, test_user, Decimal("50000"), "월급"))

    assert tx["type"] == "deposit"
    assert tx["amount"] == Decimal("50000")
    assert tx["balance_after"] == SEED_KRW + Decimal("50000")
    assert tx["memo"] == "월급"

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance
        history = db.get(DepositWithdrawal, tx["id"])
        history_balance_after = history.balance_after if history is not None else None

    assert balance == SEED_KRW + Decimal("50000")
    assert history_balance_after == balance


@requires_db
def test_withdraw_decreases_balance_and_records_history(test_user):
    with session_scope() as db:
        tx = _tx_values(withdraw(db, test_user, Decimal("30000"), None))

    assert tx["type"] == "withdraw"
    assert tx["amount"] == Decimal("30000")
    assert tx["balance_after"] == SEED_KRW - Decimal("30000")

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    assert balance == SEED_KRW - Decimal("30000")


@requires_db
@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("-1000")])
def test_deposit_rejects_non_positive_amount(test_user, amount):
    with session_scope() as db:
        with pytest.raises(InvalidAmountError):
            deposit(db, test_user, amount, None)

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    assert balance == SEED_KRW, "거부된 입금이 잔고를 건드리면 안 된다"


@requires_db
@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("-1000")])
def test_withdraw_rejects_non_positive_amount(test_user, amount):
    with session_scope() as db:
        with pytest.raises(InvalidAmountError):
            withdraw(db, test_user, amount, None)

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    assert balance == SEED_KRW, "거부된 출금이 잔고를 건드리면 안 된다"


@requires_db
def test_withdrawable_krw_excludes_active_slot_remaining_allocation(test_user, make_slot):
    """슬롯이 아직 안 쓴 배정액(invest_amount 전액, position 없음)만큼 출금 가능액이 준다."""
    make_slot(invest_amount=Decimal("4000000"), is_active=True, state={})

    with session_scope() as db:
        withdrawable = get_withdrawable_krw(db, test_user)

    assert withdrawable == SEED_KRW - Decimal("4000000")


@requires_db
def test_withdrawable_krw_does_not_double_count_already_spent_position(test_user, make_slot):
    """position이 이미 취득원가만큼 집행됐으면, 그 집행분은 배정액에서 빼고 "남은" 만큼만 잠근다.

    집행분 자체는 매수 체결 시점에 이미 balances에서 빠져나가 가용 원화에 반영돼 있으므로,
    여기서 또 빼면 이중 차감이 된다 — wallet.py 25-30행이 주석으로 남긴 그 불변식을 검증한다.
    """
    make_slot(
        invest_amount=Decimal("1000000"),
        is_active=True,
        state={"position": {"quantity": "1", "avg_price": "600000"}},  # 60만원 집행, 40만원 남음
    )

    with session_scope() as db:
        withdrawable = get_withdrawable_krw(db, test_user)

    assert withdrawable == SEED_KRW - Decimal("400000")


@requires_db
def test_withdrawable_krw_ignores_fully_spent_slot(test_user, make_slot):
    """position 취득원가가 invest_amount 이상이면 남은 배정액은 0 — 음수로 더 얹으면 안 된다."""
    make_slot(
        invest_amount=Decimal("1000000"),
        is_active=True,
        state={"position": {"quantity": "1", "avg_price": "1200000"}},  # 배정액 초과 집행
    )

    with session_scope() as db:
        withdrawable = get_withdrawable_krw(db, test_user)

    assert withdrawable == SEED_KRW


@requires_db
def test_withdrawable_krw_ignores_inactive_slot(test_user, make_slot):
    """꺼진 슬롯은 더 이상 배정액을 쓰지 않으므로 출금 가능액을 줄이면 안 된다."""
    make_slot(invest_amount=Decimal("4000000"), is_active=False, state={})

    with session_scope() as db:
        withdrawable = get_withdrawable_krw(db, test_user)

    assert withdrawable == SEED_KRW


@requires_db
def test_withdraw_rejects_amount_exceeding_withdrawable_and_balance_unchanged(test_user, make_slot):
    make_slot(invest_amount=Decimal("4000000"), is_active=True, state={})
    # 출금가능액 = 1000만 - 400만 = 600만. 601만은 거부돼야 한다.
    with session_scope() as db:
        with pytest.raises(InsufficientWithdrawableError):
            withdraw(db, test_user, Decimal("6010000"), None)

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    assert balance == SEED_KRW, "거부된 출금이 잔고에 부분 반영되면 안 된다"


@requires_db
def test_withdraw_exactly_at_withdrawable_boundary_succeeds(test_user, make_slot):
    make_slot(invest_amount=Decimal("4000000"), is_active=True, state={})

    with session_scope() as db:
        tx = _tx_values(withdraw(db, test_user, Decimal("6000000"), None))

    assert tx["balance_after"] == SEED_KRW - Decimal("6000000")


@requires_db
def test_concurrent_withdrawals_serialize_via_balance_lock(test_user):
    """개별로는 출금가능액 안에 들지만 합치면 넘는 동시 출금 2건 — 정확히 하나만 성공해야 한다.

    `withdraw`가 balances 행을 `with_for_update()`로 잠근 뒤에야 출금가능액을 확인하므로,
    두 트랜잭션은 직렬화되고 나중에 도는 쪽은 이미 줄어든 잔고 기준으로 재평가된다.
    """
    amount = Decimal("6000000")  # 둘 다 성공하면 1200만 > 잔고 1000만

    def _withdraw():
        with session_scope() as db:
            return withdraw(db, test_user, amount, None).id

    results = _run_concurrently(_withdraw, _withdraw)

    successes = [r for r, e in results if e is None]
    failures = [e for r, e in results if e is not None]

    assert len(successes) == 1, results
    assert len(failures) == 1 and isinstance(failures[0], InsufficientWithdrawableError), results

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    assert balance == SEED_KRW - amount, "정확히 한 건만 반영돼야 한다 (lost update 금지)"


@requires_db
def test_deposit_and_withdraw_interleave_without_losing_updates(test_user):
    """입금 5건 + 출금 5건이 동시에 들어와도 최종 잔고가 순차 실행과 같아야 한다."""
    deposit_amount = Decimal("100000")
    withdraw_amount = Decimal("50000")

    def _deposit():
        with session_scope() as db:
            return deposit(db, test_user, deposit_amount, None).id

    def _withdraw():
        with session_scope() as db:
            return withdraw(db, test_user, withdraw_amount, None).id

    funcs = [_deposit] * 5 + [_withdraw] * 5
    results = _run_concurrently(*funcs)

    assert all(e is None for _, e in results), results

    with session_scope() as db:
        balance = db.get(Balance, test_user).krw_balance

    expected = SEED_KRW + deposit_amount * 5 - withdraw_amount * 5
    assert balance == expected, f"동시 입출금 10건 중 일부가 유실됐다 (expected={expected}, actual={balance})"
