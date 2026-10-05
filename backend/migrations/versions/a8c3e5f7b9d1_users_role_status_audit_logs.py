"""users role·status 컬럼과 audit_logs 테이블 추가

Revision ID: a8c3e5f7b9d1
Revises: f2b91c40a7de
Create Date: 2026-10-05 00:00:00.000000

확장판 8단계 — 관리자 기능 (docs-scale/05-admin.md 2.1절, 4장).

기존 행은 서버 기본값으로 `role='user'`, `status='active'`를 받는다. 첫 관리자는
`scripts/set_admin.py`로 지정한다 — 화면에서 스스로 승격하는 경로는 두지 않는다.

`audit_logs.actor_user_id`는 `ON DELETE SET NULL`이다. 설계 초안은 그냥 FK였는데, 그러면
관리자가 탈퇴할 때 그 사람의 감사 기록이 CASCADE로 함께 지워지거나(CASCADE) 탈퇴 자체가
막힌다(RESTRICT). 감사 로그는 행위자가 사라져도 남아야 하므로 NULL로 끊고, 누가 했는지는
`actor_email` 스냅샷으로 남긴다. `target_id`는 설계대로 FK를 걸지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8c3e5f7b9d1'
down_revision: Union[str, Sequence[str], None] = 'f2b91c40a7de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("role", sa.String(length=10), nullable=False, server_default="user")
    )
    op.add_column(
        "users", sa.Column("status", sa.String(length=10), nullable=False, server_default="active")
    )
    op.create_check_constraint("ck_users_role", "users", "role IN ('user','admin')")
    op.create_check_constraint("ck_users_status", "users", "status IN ('active','suspended')")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_created", "audit_logs", [sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "status")
    op.drop_column("users", "role")
