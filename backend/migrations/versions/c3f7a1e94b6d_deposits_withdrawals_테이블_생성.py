"""deposits_withdrawals 테이블 생성

Revision ID: c3f7a1e94b6d
Revises: 7035d8b15fb8
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f7a1e94b6d'
down_revision: Union[str, Sequence[str], None] = '7035d8b15fb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "deposits_withdrawals",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("memo", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("type IN ('deposit','withdraw')", name="ck_deposits_withdrawals_type"),
    )
    op.create_index(
        "ix_deposits_withdrawals_user_created", "deposits_withdrawals", ["user_id", "created_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_deposits_withdrawals_user_created", table_name="deposits_withdrawals")
    op.drop_table("deposits_withdrawals")
