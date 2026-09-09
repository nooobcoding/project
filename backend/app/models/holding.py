"""holdings — 보유 코인 (01-erd.md 2장, 03-manual-trading).

전량 매도 시에도 행을 삭제하지 않고 quantity=0, avg_buy_price=0으로 리셋해 유지한다
(재매수 시 이전 평단이 섞여 오염되는 것을 방지, 01-erd.md 2장 holdings 정의).
"""

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Holding(Base):
    __tablename__ = "holdings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    coin_symbol: Mapped[str] = mapped_column(
        String(10), ForeignKey("coins.symbol"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False, default=Decimal(0))
    avg_buy_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal(0)
    )
