"""05-deposit-withdraw Control 계층 — 가상 원화 입금/출금/내역 조회.

get_withdrawable_krw는 01-erd.md 3.1절의 "출금 가능액" 파생식이다. 07-auto-trading이
아직 없어 활성 슬롯 배정액 차감 항이 존재하지 않으므로, 지금은 가용 원화와 동일하다.
07 구현 시 strategy_slots.is_active 조건의 배정액 차감을 이 함수에 추가해야 한다.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Balance, DepositWithdrawal
from app.services.orders import get_available_krw


class InvalidAmountError(Exception):
    """입출금 금액이 0 이하인 경우 (05-deposit-withdraw.md 3장)."""


class InsufficientWithdrawableError(Exception):
    """출금액이 출금 가능액을 초과하는 경우."""


def get_withdrawable_krw(db: Session, user_id: int) -> Decimal:
    return get_available_krw(db, user_id)


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
