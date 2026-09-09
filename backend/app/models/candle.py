"""candles — OHLCV 캐시 (01-erd.md 2장, 03-manual-trading/06-backtesting 겸용).

02-dashboard의 시세 차트가 최초 소비자다 — 03/06이 착수되기 전에 앞당겨 만들었다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("coin_symbol", "interval", "opened_at"),
        CheckConstraint("interval IN ('1m','10m','30m','1h','1d')", name="ck_candles_interval"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    coin_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("coins.symbol"))
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
