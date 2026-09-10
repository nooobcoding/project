"""backtest_trades — 백테스팅 체결 상세 (01-erd.md 2장, 06-backtesting FR-B07).

수익 곡선의 매수/매도 마커를 클릭했을 때 보여줄 체결가·수량·실현손익이다.

FK는 **ON DELETE CASCADE**다 — 체결 상세는 결과에 종속된 값이라 결과를 지우면 함께 사라져야
한다 (마이그레이션 dc87c2796bde 주석 참고).

**이름 주의**: `app/strategy_engine/backtest.py`에도 같은 이름의 `BacktestTrade`(시뮬레이터가
만드는 순수 dataclass)가 있다. 둘을 함께 임포트하는 곳(services/backtest.py)은 별칭을 써서
DB 행과 계산 결과를 구분한다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_backtest_trades_side"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    backtest_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("backtest_results.id", ondelete="CASCADE")
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    # 매도 행만 값을 갖는다 — 매수는 실현손익이 없다.
    profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
