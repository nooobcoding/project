"""deposits_withdrawals — 가상 입출금 내역 (01-erd.md 2장, 05-deposit-withdraw)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DepositWithdrawal(Base):
    __tablename__ = "deposits_withdrawals"
    __table_args__ = (
        CheckConstraint("type IN ('deposit','withdraw')", name="ck_deposits_withdrawals_type"),
        Index("ix_deposits_withdrawals_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
