"""05-deposit-withdraw Boundary 계층 — /api/wallet/*. Control(services/wallet.py)만 호출한다."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.wallet import (
    DepositRequest,
    TransactionListResponse,
    TransactionResponse,
    WalletBalanceResponse,
    WithdrawRequest,
)
from app.services.auth import get_current_user
from app.services.wallet import (
    InsufficientWithdrawableError,
    InvalidAmountError,
    deposit,
    get_balance_summary,
    list_transactions,
    withdraw,
)

router = APIRouter(prefix="/api/wallet", tags=["wallet"])

_KST = ZoneInfo("Asia/Seoul")


def _to_response(transaction) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        type=transaction.type,
        amount=str(transaction.amount),
        balance_after=str(transaction.balance_after),
        memo=transaction.memo,
        created_at=transaction.created_at,
    )


def _parse_amount(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바른 금액을 입력해주세요. (1원 이상)")


@router.get("/balance", response_model=WalletBalanceResponse)
def get_balance(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> WalletBalanceResponse:
    krw_balance, withdrawable_krw = get_balance_summary(db, current_user.id)
    return WalletBalanceResponse(krw_balance=str(krw_balance), withdrawable_krw=str(withdrawable_krw))


@router.post("/deposit", response_model=TransactionResponse, status_code=http_status.HTTP_201_CREATED)
def post_deposit(
    payload: DepositRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> TransactionResponse:
    amount = _parse_amount(payload.amount)
    try:
        transaction = deposit(db, current_user.id, amount, payload.memo)
    except InvalidAmountError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바른 금액을 입력해주세요. (1원 이상)"
        )
    return _to_response(transaction)


@router.post("/withdraw", response_model=TransactionResponse, status_code=http_status.HTTP_201_CREATED)
def post_withdraw(
    payload: WithdrawRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> TransactionResponse:
    amount = _parse_amount(payload.amount)
    try:
        transaction = withdraw(db, current_user.id, amount, payload.memo)
    except InvalidAmountError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바른 금액을 입력해주세요. (1원 이상)"
        )
    except InsufficientWithdrawableError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="출금 금액이 보유 잔고를 초과합니다. (자동매매에 배정된 금액이 있다면 이를 제외한 금액 기준)",
        )
    return _to_response(transaction)


@router.get("/transactions", response_model=TransactionListResponse)
def get_transactions(
    type: str | None = Query(None, alias="type"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> TransactionListResponse:
    if type is not None and type not in ("deposit", "withdraw"):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="지원하지 않는 type 값입니다."
        )

    # 화면의 날짜 범위는 KST 기준 하루 단위이므로, 저장된 UTC created_at과 비교하려면
    # KST 자정 경계를 UTC로 변환해야 한다 (01-erd.md 3.3절 — 저장은 UTC, 표시는 KST).
    start_at = datetime.combine(start, time.min, tzinfo=_KST) if start is not None else None
    end_at = datetime.combine(end, time.min, tzinfo=_KST) + timedelta(days=1) if end is not None else None

    items, total = list_transactions(
        db,
        current_user.id,
        type_=type,
        start=start_at,
        end=end_at,
        page=page,
        page_size=page_size,
    )
    return TransactionListResponse(items=[_to_response(item) for item in items], total=total)
