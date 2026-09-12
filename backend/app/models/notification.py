"""notifications — 알림 (01-erd.md 2장, 04-settings·07-auto-trading).

strategy_slot_id 컬럼은 strategy_slots 테이블이 아직 없어(07-auto-trading 미구현)
이 모델에서 생략했다 (models/order.py와 동일한 사유). 07 구현 시 컬럼·FK를 함께 추가한다.
실제 알림 적재(신호/손절익절/오류 발생 시 insert)도 07 구현 시 붙는다 — 04는 설정 CRUD와
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
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
