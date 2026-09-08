"""coins — 코인 마스터 (01-erd.md 2장).

전 기능이 이 테이블의 symbol을 FK로 참조하므로 로드맵 0번에서 가장 먼저 만든다.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Coin(Base):
    __tablename__ = "coins"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    market_code: Mapped[str] = mapped_column(String(20), nullable=False)
    korean_name: Mapped[str] = mapped_column(String(50), nullable=False)
    english_name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
