"""backtest_results — 백테스팅 결과 (01-erd.md 2장, 06-backtesting.md 5장).

`equity_curve`는 `[{at, asset}]` 형태의 JSONB다 — `at`은 ISO8601 datetime, `asset`은 문자열
수치다. ERD 초안은 `[{date, asset}]`이었으나 분봉 백테스트는 하루에 여러 점이 나오므로 날짜로
접으면 수익 곡선이 뭉개진다(성과지표의 Sharpe만 별도로 날짜 접기를 한다 —
`strategy_engine/metrics.py`). 그래서 시각을 유지하는 쪽으로 정정했고 `strategy_engine`의
`EquityPoint` 필드명(`at`/`asset`)을 그대로 JSON 키로 쓴다.

성과지표 컬럼이 nullable인 것은 ERD 표기를 그대로 따른 것이다 — 저장 시점에는 계산이 끝나
있으므로 서비스는 항상 값을 채운다.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BacktestResult(Base):
    __tablename__ = "backtest_results"
    __table_args__ = (
        CheckConstraint(
            "strategy_type IN ('trend','counter_trend','grid','dca')",
            name="ck_backtest_results_strategy_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    coin_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("coins.symbol"))
    strategy_type: Mapped[str] = mapped_column(String(20), nullable=False)
    indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 최상위 키 interval 포함 (06-backtesting.md 2.1-1절)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    # % 단위 (01-erd.md 3.2절) — 엔진에 넘기기 전 costs.percent_to_decimal로 변환한다.
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    slippage_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    total_return: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    mdd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_asset: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    benchmark_return: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    equity_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
