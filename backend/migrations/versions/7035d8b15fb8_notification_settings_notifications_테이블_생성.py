"""notification_settings, notifications 테이블 생성

Revision ID: 7035d8b15fb8
Revises: d4e8f2a97c15
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7035d8b15fb8'
down_revision: Union[str, Sequence[str], None] = 'd4e8f2a97c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # strategy_slot_id는 strategy_slots 테이블이 아직 없어(07-auto-trading 미구현) 이 마이그레이션에서는
    # 생략한다. 07 구현 시 컬럼·FK를 함께 추가한다 (01-erd.md 2장 notifications 정의 참고).
    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("type IN ('signal','exit','error')", name="ck_notifications_type"),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_settings")
