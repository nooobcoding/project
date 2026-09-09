"""notification_settings — 알림 설정 (01-erd.md 2장, 04-settings)."""

from sqlalchemy import Boolean, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    signal_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 기본 ON — 07의 "잔고 부족으로 매수 스킵" 알림이 type='error'라 기본 OFF면
    # 자동매매 중단 사실을 사용자가 놓친다 (04-settings.md 2-B).
    error_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
