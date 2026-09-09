"""strategy_slot_id FK ON DELETE SET NULL 수정

Revision ID: a69df04a6703
Revises: cbdbedb27af6
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a69df04a6703'
down_revision: Union[str, Sequence[str], None] = 'cbdbedb27af6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    cbdbedb27af6에서 orders/notifications의 strategy_slot_id FK를 삭제 동작 지정 없이(=RESTRICT)
    만들어, **한 번이라도 거래한 슬롯을 삭제할 수 없는** 버그가 있었다. 같은 이유로 자동매매를
    써 본 계정은 회원 탈퇴(users CASCADE → strategy_slots)까지 실패한다.

    SET NULL로 바꾼다 — 체결 기록(orders)은 잔고 이력의 근거이자 08-portfolio 거래내역이라
    슬롯과 함께 지울 수 없고, 슬롯이 사라진 뒤의 연결값은 의미가 없으므로 NULL이 맞다
    (07-auto-trading.md 4.2절 "슬롯 삭제 시 포지션은 수동 보유분으로 남는다"와 같은 취지 —
    거래는 실제로 일어났고 그것을 지시한 전략만 없어지는 것).
    """
    op.drop_constraint("fk_orders_strategy_slot_id", "orders", type_="foreignkey")
    op.create_foreign_key(
        "fk_orders_strategy_slot_id",
        "orders",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("fk_notifications_strategy_slot_id", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "fk_notifications_strategy_slot_id",
        "notifications",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_notifications_strategy_slot_id", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "fk_notifications_strategy_slot_id",
        "notifications",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
    )

    op.drop_constraint("fk_orders_strategy_slot_id", "orders", type_="foreignkey")
    op.create_foreign_key(
        "fk_orders_strategy_slot_id",
        "orders",
        "strategy_slots",
        ["strategy_slot_id"],
        ["id"],
    )
