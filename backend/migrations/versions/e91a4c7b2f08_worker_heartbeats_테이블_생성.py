"""worker_heartbeats 테이블 생성

Revision ID: e91a4c7b2f08
Revises: dc87c2796bde
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e91a4c7b2f08'
down_revision: Union[str, Sequence[str], None] = 'dc87c2796bde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("shard_id", sa.SmallInteger(), nullable=True),
        sa.Column("process_id", sa.String(length=64), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_duration_ms", sa.Integer(), nullable=False),
        sa.Column("max_duration_ms", sa.Integer(), nullable=False),
        sa.Column("over_budget_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("db_connections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skip_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "role", "shard_id", "process_id", name="uq_worker_heartbeats_role_shard_process"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("worker_heartbeats")
