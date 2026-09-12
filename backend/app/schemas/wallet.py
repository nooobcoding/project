"""05-deposit-withdraw 요청/응답 DTO — 입출금.

금액 필드는 문자열로 반환한다 (02-coding-conventions.md 9절).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DepositRequest(BaseModel):
    amount: str
    memo: str | None = Field(default=None, max_length=30)


class WithdrawRequest(BaseModel):
    amount: str
    memo: str | None = Field(default=None, max_length=30)


class WalletBalanceResponse(BaseModel):
    krw_balance: str
    withdrawable_krw: str


class TransactionResponse(BaseModel):
    id: int
    type: Literal["deposit", "withdraw"]
    amount: str
    balance_after: str
    memo: str | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
