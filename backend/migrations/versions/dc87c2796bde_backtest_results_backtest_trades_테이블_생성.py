"""backtest_results / backtest_trades 테이블 생성

Revision ID: dc87c2796bde
Revises: a69df04a6703
Create Date: 2026-09-10 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'dc87c2796bde'
down_revision: Union[str, Sequence[str], None] = 'a69df04a6703'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 01-erd.md `backtest_results` 정의 그대로 (06-backtesting.md 5장).
    #
    # 성과지표 컬럼(total_return~benchmark_return)은 ERD에 NOT NULL 표기가 없어 nullable로 둔다.
    # 저장 시점에는 항상 계산이 끝나 있어 서비스가 전부 채우지만, 스키마는 ERD를 기준으로 삼는다.
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("strategy_type", sa.String(length=20), nullable=False),
        sa.Column("indicator", sa.String(length=20), nullable=True),
        # 최상위 키 interval을 포함한다 (06-backtesting.md 2.1-1절 — 봉단위는 전략유형과
        # 무관한 공통 설정이라 지표 파라미터가 아니라 params 최상위에 있다).
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(precision=20, scale=4), nullable=False),
        # % 단위로 저장한다 (01-erd.md 3.2절 단위 규칙) — 엔진에 넘길 때 소수로 변환한다.
        sa.Column("fee_rate", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("slippage_rate", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("total_return", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("mdd", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("win_rate", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("final_asset", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("benchmark_return", sa.Numeric(precision=10, scale=4), nullable=True),
        # `[{at, asset}]` — at은 ISO8601 datetime이다. ERD 초안은 `{date, asset}`이었으나
        # 분봉 백테스트는 하루에 여러 점이 나와 날짜로 접으면 곡선이 뭉개지므로 시각을 유지한다
        # (06-backtesting.md 5장에 정정 반영).
        sa.Column("equity_curve", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "strategy_type IN ('trend','counter_trend','grid','dca')",
            name="ck_backtest_results_strategy_type",
        ),
    )
    # 목록 조회가 항상 "내 결과"로 필터링된다 (GET /api/backtest/results).
    op.create_index("ix_backtest_results_user_id", "backtest_results", ["user_id"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("backtest_result_id", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("profit", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        # ON DELETE CASCADE — 체결 상세는 결과에 종속된 값이라 결과를 지우면 함께 사라져야 한다.
        # 07에서 orders.strategy_slot_id FK에 ondelete를 빠뜨려 RESTRICT가 되는 바람에 거래 이력이
        # 있는 슬롯 삭제가 500으로 실패했던 일(마이그레이션 a69df04a6703)을 반복하지 않기 위해
        # 테이블 생성 시점에 명시한다.
        sa.ForeignKeyConstraint(
            ["backtest_result_id"], ["backtest_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_backtest_trades_side"),
    )
    # 상세 조회가 결과 1건의 체결 전체를 훑는다 (GET /api/backtest/results/{id}).
    op.create_index("ix_backtest_trades_result_id", "backtest_trades", ["backtest_result_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_backtest_trades_result_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")

    op.drop_index("ix_backtest_results_user_id", table_name="backtest_results")
    op.drop_table("backtest_results")
