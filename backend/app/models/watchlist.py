"""watchlists — 대시보드 관심 코인 (01-erd.md 2장, 02-dashboard.md 4장).

최대 5개 제약은 API 레벨(services/dashboard.py)에서 검사한다.
"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "coin_symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    coin_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("coins.symbol"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
