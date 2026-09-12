"""orders, holdings 테이블 생성

Revision ID: b6f1c8a34d02
Revises: 9a2c4e6f1b3d
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6f1c8a34d02'
down_revision: Union[str, Sequence[str], None] = '9a2c4e6f1b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # strategy_slot_id는 strategy_slots 테이블이 아직 없어(07-auto-trading 미구현) 이 마이그레이션에서는
    # 생략한다. 07 구현 시 컬럼·FK·인덱스를 함께 추가한다 (01-erd.md 2장 orders 정의 참고).
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("order_type", sa.String(length=6), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=6), nullable=False, server_default="manual"),
        sa.Column("realized_profit", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fee", sa.Numeric(precision=20, scale=4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_orders_side"),
        sa.CheckConstraint("order_type IN ('limit','market')", name="ck_orders_order_type"),
        sa.CheckConstraint("status IN ('pending','filled','canceled')", name="ck_orders_status"),
        sa.CheckConstraint("source IN ('manual','auto')", name="ck_orders_source"),
    )
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index("ix_orders_user_source_created", "orders", ["user_id", "source", "created_at"])

    op.create_table(
        "holdings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=False, server_default="0"),
        sa.Column("avg_buy_price", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("user_id", "coin_symbol"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("holdings")
    op.drop_index("ix_orders_user_source_created", table_name="orders")
    op.drop_index("ix_orders_user_status", table_name="orders")
    op.drop_index("ix_orders_user_created", table_name="orders")
    op.drop_table("orders")
