"""watchlists 테이블 생성

Revision ID: 7d3a9c1e5f2b
Revises: 1b513aeebc6e
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d3a9c1e5f2b'
down_revision: Union[str, Sequence[str], None] = '1b513aeebc6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "coin_symbol"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("watchlists")
