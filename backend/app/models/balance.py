"""balances — 원화 잔고 (01-erd.md 2장). 가입 시 시드머니로 생성된다 (01-auth.md 5장)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import INITIAL_SEED_KRW
from app.models.base import Base


class Balance(Base):
    __tablename__ = "balances"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    krw_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=INITIAL_SEED_KRW
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
