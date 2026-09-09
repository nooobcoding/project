"""orders — 매수/매도 체결 (01-erd.md 2장, 03-manual-trading·09-execution-engine).

status 전이(pending→filled/canceled)는 services/matcher.py(체결)와
services/orders.py(취소)가 담당하며, 모델 자체는 상태를 갖되 전이 로직은 갖지 않는다.

strategy_slot_id 컬럼은 strategy_slots 테이블이 아직 없어(07-auto-trading 미구현)
이 모델에서 생략했다. 07 구현 시 컬럼·FK·인덱스를 함께 추가한다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_orders_side"),
        CheckConstraint("order_type IN ('limit','market','reserved')", name="ck_orders_order_type"),
        CheckConstraint("status IN ('pending','filled','canceled')", name="ck_orders_status"),
        CheckConstraint("source IN ('manual','auto')", name="ck_orders_source"),
        CheckConstraint("trigger_direction IN ('rising','falling')", name="ck_orders_trigger_direction"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_user_source_created", "user_id", "source", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    coin_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("coins.symbol"))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    order_type: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(6), nullable=False, default="manual")
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=Decimal(0))
    # trigger_price/trigger_direction은 order_type='reserved'(예약가 주문)일 때만 값을 가진다.
    # 감시가격 도달 시 order_type이 'limit'으로 승격되고 이후는 기존 지정가 체결 경로를 그대로 탄다
    # (services/matcher.py run_matching_for_symbol의 승격 단계 참고).
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trigger_direction: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
