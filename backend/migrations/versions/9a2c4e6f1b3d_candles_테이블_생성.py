"""candles 테이블 생성

Revision ID: 9a2c4e6f1b3d
Revises: 7d3a9c1e5f2b
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a2c4e6f1b3d'
down_revision: Union[str, Sequence[str], None] = '7d3a9c1e5f2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("coin_symbol", sa.String(length=10), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.ForeignKeyConstraint(["coin_symbol"], ["coins.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coin_symbol", "interval", "opened_at"),
        sa.CheckConstraint("interval IN ('1m','10m','30m','1h','1d')", name="ck_candles_interval"),
    )
    op.create_index(
        "ix_candles_symbol_interval_opened_at",
        "candles",
        ["coin_symbol", "interval", "opened_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_candles_symbol_interval_opened_at", table_name="candles")
    op.drop_table("candles")
