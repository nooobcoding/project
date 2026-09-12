"""worker_heartbeats 유니크 제약 NULLS NOT DISTINCT 수정

Revision ID: f2b91c40a7de
Revises: e91a4c7b2f08
Create Date: 2026-09-13 00:00:00.000000

(role, shard_id, process_id) 유니크 제약이 사실상 동작하지 않고 있었다. PostgreSQL은
기본적으로 NULL을 서로 다른 값으로 보는데, 샤드가 없는 역할(worker·market-data·scheduler)은
shard_id가 NULL이라 같은 키로 몇 행이든 들어갈 수 있었다. NULLS NOT DISTINCT(PG15+)로
바꿔 문서가 말하는 "역할·샤드·프로세스당 1행"을 DB가 실제로 보장하게 한다.

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f2b91c40a7de'
down_revision: Union[str, Sequence[str], None] = 'e91a4c7b2f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "uq_worker_heartbeats_role_shard_process"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(_CONSTRAINT, "worker_heartbeats", type_="unique")
    op.execute(
        f"ALTER TABLE worker_heartbeats ADD CONSTRAINT {_CONSTRAINT} "
        "UNIQUE NULLS NOT DISTINCT (role, shard_id, process_id)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_CONSTRAINT, "worker_heartbeats", type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT, "worker_heartbeats", ["role", "shard_id", "process_id"]
    )
