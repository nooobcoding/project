"""strategy_slots 테이블 생성

Revision ID: cbdbedb27af6
Revises: c3f7a1e94b6d
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'cbdbedb27af6'
down_revision: Union[str, Sequence[str], None] = 'c3f7a1e94b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 01-erd.md 2장 strategy_slots 정의 그대로. strategy_slots가 이제 생겼으므로
    # orders/notifications에 미뤄뒀던 strategy_slot_id 컬럼도 이 마이그레이션에서 함께 추가한다
    # (models/order.py, models/notification.py docstring "07 구현 시 컬럼·FK를 함께 추가한다" 참고).
    op.create_table(
        "strategy_slots",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("strategy_type", sa.String(length=20), nullable=False),
        sa.Column("indicator", sa.String(length=20), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("invest_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("stop_loss_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("take_profit_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        # state 스키마(position/grid/dca)는 01-erd.md 3.6절 참고. 워커·체결훅이 이 컬럼의
        # 서로 다른 키만 갱신한다 (07-auto-trading.md 4장 — state.position은 09-execution-engine
        # 체결 후처리만, 나머지 신호 판단용 키는 워커만 쓴다).
        sa.Column(
            "state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "strategy_type IN ('trend','counter_trend','grid','dca')",
            name="ck_strategy_slots_strategy_type",
        ),
    )
    # 코인당 활성 슬롯 1개 제약 (01-erd.md 2장·3.5절, 07-auto-trading.md 2절).
    op.create_index(
        "ux_strategy_slots_active_coin",
        "strategy_slots",
        ["user_id", "coin_symbol"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.add_column(
        "orders", sa.Column("strategy_slot_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_orders_strategy_slot_id",
        "orders",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
    )
    op.create_index("ix_orders_strategy_slot", "orders", ["strategy_slot_id"])

    op.add_column(
        "notifications", sa.Column("strategy_slot_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_notifications_strategy_slot_id",
        "notifications",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_notifications_strategy_slot_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "strategy_slot_id")

    op.drop_index("ix_orders_strategy_slot", table_name="orders")
    op.drop_constraint("fk_orders_strategy_slot_id", "orders", type_="foreignkey")
    op.drop_column("orders", "strategy_slot_id")

    op.drop_index("ux_strategy_slots_active_coin", table_name="strategy_slots")
    op.drop_table("strategy_slots")
