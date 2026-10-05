"""audit_logs — 관리자 행위 감사 로그 (확장판 05-admin.md 4장).

행위자가 탈퇴해도 기록이 남아야 하므로 `actor_user_id`는 `ON DELETE SET NULL`이고, 누가
했는지는 `actor_email` 스냅샷으로 보존한다. `target_id`에는 FK를 걸지 않는다 — 대상 유저가
탈퇴해도 남아야 한다. CLI(`scripts/set_admin.py`)가 남긴 행은 행위자가 없어 둘 다 NULL이다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created", text("created_at DESC")),
        Index("ix_audit_logs_actor_created", "actor_user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
