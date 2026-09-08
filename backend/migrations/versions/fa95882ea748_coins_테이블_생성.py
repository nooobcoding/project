"""coins 테이블 생성

Revision ID: fa95882ea748
Revises: 
Create Date: 2026-09-08 22:14:16.968595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa95882ea748'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "coins",
        sa.Column("symbol", sa.String(length=10), primary_key=True),
        sa.Column("market_code", sa.String(length=20), nullable=False),
        sa.Column("korean_name", sa.String(length=50), nullable=False),
        sa.Column("english_name", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("coins")
