"""worker_heartbeats — 프로세스·역할·샤드 단위 tick 상태의 최신 스냅샷 1행씩.

시계열이 아니라 현재 상태만 담는다 (확장판 00단계, docs-scale/06-observability.md 2장).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        UniqueConstraint("role", "shard_id", "process_id", name="uq_worker_heartbeats_role_shard_process"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    shard_id: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    process_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    over_budget_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_connections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
