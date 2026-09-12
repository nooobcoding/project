"""strategy_slots — 자동매매 슬롯 (01-erd.md 2장·3.6절, 07-auto-trading).

`state` JSONB는 두 주체가 서로 다른 키만 쓴다 (07-auto-trading.md 4장):
  - `state.position` — 09-execution-engine 체결 후처리(`services/matcher.py`
    `_apply_auto_trading_hook`)만 갱신한다.
  - `state.last_evaluated_candle_at`, `state.grid.lines`, `state.dca.*` — 워커
    (`app/strategy_engine/worker.py`)만 갱신한다.
모델 자체는 이 소유권 규칙을 갖지 않는다 — 컬럼 하나를 여러 주체가 부분적으로 쓸 뿐, 강제는
호출부(services/strategy_slots.py, matcher.py)의 책임이다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StrategySlot(Base):
    __tablename__ = "strategy_slots"
    __table_args__ = (
        CheckConstraint(
            "strategy_type IN ('trend','counter_trend','grid','dca')",
            name="ck_strategy_slots_strategy_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    coin_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("coins.symbol"))
    strategy_type: Mapped[str] = mapped_column(String(20), nullable=False)
    indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    invest_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
