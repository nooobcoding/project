"""users — 계정 (01-erd.md 2장, 확장판 05-admin.md 2.1절 role·status)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ROLE_USER = "user"
ROLE_ADMIN = "admin"
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
        CheckConstraint("status IN ('active','suspended')", name="ck_users_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False, server_default=ROLE_USER)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=STATUS_ACTIVE)
