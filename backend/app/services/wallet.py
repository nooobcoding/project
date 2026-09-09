"""05-deposit-withdraw Control 계층 — 가상 원화 입금/출금/내역 조회.

get_withdrawable_krw는 01-erd.md 3.1절의 "출금 가능액" 파생식이다.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Balance, DepositWithdrawal, StrategySlot
from app.services.orders import get_available_krw


class InvalidAmountError(Exception):
    """입출금 금액이 0 이하인 경우 (05-deposit-withdraw.md 3장)."""


class InsufficientWithdrawableError(Exception):
    """출금액이 출금 가능액을 초과하는 경우."""


def get_withdrawable_krw(db: Session, user_id: int) -> Decimal:
    """출금 가능액 = 가용 원화 − Σ(활성 슬롯의 "남은" 배정액) (01-erd.md 3.1절).

    슬롯이 이미 집행한 금액(state.position 기준 취득원가)은 매수 체결 시점에 이미
    balances에서 빠져나가 가용 원화 계산에 반영돼 있다. 여기서는 슬롯이 앞으로 더
    쓸 수 있는 "남은" 배정액(invest_amount − 이미 집행한 금액)만 추가로 차감한다 —
    이미 집행분까지 또 빼면 이중 차감이 된다.
    """
    available = get_available_krw(db, user_id)

    active_slots = db.scalars(
        select(StrategySlot).where(StrategySlot.user_id == user_id, StrategySlot.is_active)
    )
    reserved = Decimal(0)
    for slot in active_slots:
        position = slot.state.get("position") if slot.state else None
        spent = Decimal(position["quantity"]) * Decimal(position["avg_price"]) if position else Decimal(0)
        remaining = slot.invest_amount - spent
        if remaining > 0:
            reserved += remaining

    return available - reserved


def get_balance_summary(db: Session, user_id: int) -> tuple[Decimal, Decimal]:
    """(krw_balance, withdrawable_krw) — GET /api/wallet/balance 전용 조회."""
    balance = db.get(Balance, user_id)
    krw_balance = balance.krw_balance if balance is not None else Decimal(0)
    return krw_balance, get_withdrawable_krw(db, user_id)


def deposit(db: Session, user_id: int, amount: Decimal, memo: str | None) -> DepositWithdrawal:
    if amount <= 0:
        raise InvalidAmountError()

    # 동시 입출금·주문 생성과 경쟁하지 않도록 balances 행을 잠근다 (01-erd.md 3.1절 동시성 주의).
    balance = db.execute(
        select(Balance).where(Balance.user_id == user_id).with_for_update()
    ).scalar_one()
    balance.krw_balance += amount
    balance.updated_at = datetime.now(timezone.utc)

    transaction = DepositWithdrawal(
        user_id=user_id,
        type="deposit",
        amount=amount,
        balance_after=balance.krw_balance,
        memo=memo,
        created_at=datetime.now(timezone.utc),
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def withdraw(db: Session, user_id: int, amount: Decimal, memo: str | None) -> DepositWithdrawal:
    if amount <= 0:
        raise InvalidAmountError()

    balance = db.execute(
        select(Balance).where(Balance.user_id == user_id).with_for_update()
    ).scalar_one()
    if amount > get_withdrawable_krw(db, user_id):
        raise InsufficientWithdrawableError()

    balance.krw_balance -= amount
    balance.updated_at = datetime.now(timezone.utc)

    transaction = DepositWithdrawal(
        user_id=user_id,
        type="withdraw",
        amount=amount,
        balance_after=balance.krw_balance,
        memo=memo,
        created_at=datetime.now(timezone.utc),
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def list_transactions(
    db: Session,
    user_id: int,
    type_: str | None,
    start: datetime | None,
    end: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[DepositWithdrawal], int]:
    conditions = [DepositWithdrawal.user_id == user_id]
    if type_ is not None:
        conditions.append(DepositWithdrawal.type == type_)
    if start is not None:
        conditions.append(DepositWithdrawal.created_at >= start)
    if end is not None:
        # end는 호출부(routers/wallet.py)에서 다음 날 자정으로 변환해 넘기는 배타적 상한이다.
        conditions.append(DepositWithdrawal.created_at < end)

    total = db.scalar(select(func.count()).select_from(DepositWithdrawal).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(DepositWithdrawal)
            .where(*conditions)
            .order_by(DepositWithdrawal.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total
