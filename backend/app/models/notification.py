"""notifications — 알림 (01-erd.md 2장, 04-settings·07-auto-trading).

strategy_slot_id는 07-auto-trading이 발생시킨 알림(신호/손절익절/오류)일 때만 값을 가진다.
실제 알림 적재는 services/matcher.py `_apply_auto_trading_hook`(체결 이벤트)와
app/strategy_engine/worker.py(신호·오류 이벤트)가 담당한다 — 04는 설정 CRUD와
목록 조회/읽음 처리만 다룬다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("type IN ('signal','exit','error')", name="ck_notifications_type"),
        Index("ix_notifications_user_read", "user_id", "is_read"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    coin_symbol: Mapped[str | None] = mapped_column(String(10), ForeignKey("coins.symbol"), nullable=True)
    strategy_slot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("strategy_slots.id"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
