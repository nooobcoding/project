"""orders 예약가 컬럼 추가

Revision ID: d4e8f2a97c15
Revises: b6f1c8a34d02
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8f2a97c15'
down_revision: Union[str, Sequence[str], None] = 'b6f1c8a34d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # order_type이 기존 VARCHAR(6)이라 'reserved'(8자)가 안 들어간다 — 폭을 넓힌다.
    op.alter_column("orders", "order_type", type_=sa.String(length=8))
    op.add_column("orders", sa.Column("trigger_price", sa.Numeric(precision=20, scale=8), nullable=True))
    op.add_column("orders", sa.Column("trigger_direction", sa.String(length=7), nullable=True))

    op.drop_constraint("ck_orders_order_type", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_order_type",
        "orders",
        "order_type IN ('limit','market','reserved')",
    )
    op.create_check_constraint(
        "ck_orders_trigger_direction",
        "orders",
        "trigger_direction IN ('rising','falling')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_orders_trigger_direction", "orders", type_="check")
    op.drop_constraint("ck_orders_order_type", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_order_type",
        "orders",
        "order_type IN ('limit','market')",
    )
    op.drop_column("orders", "trigger_direction")
    op.drop_column("orders", "trigger_price")
    op.alter_column("orders", "order_type", type_=sa.String(length=6))
