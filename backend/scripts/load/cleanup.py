"""부하 측정용으로 만든 유저를 지운다 — 개발 DB에 흔적을 남기지 않는다.

사용법 (컨테이너 안):
    python scripts/load/cleanup.py --run bench
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import session_scope  # noqa: E402

# FK 순서 — orders.strategy_slot_id가 슬롯을 참조하므로 주문을 먼저 지운다 (tests/conftest.py와 같다)
TABLES = (
    "notifications",
    "orders",
    "holdings",
    "strategy_slots",
    "backtest_results",
    "balances",
    "watchlists",
    "notification_settings",
    "deposits_withdrawals",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="bench")
    args = parser.parse_args()
    pattern = f"load-{args.run}-%"

    with session_scope() as db:
        ids = db.execute(text("SELECT id FROM users WHERE email LIKE :p"), {"p": pattern}).scalars().all()
        if not ids:
            print(f"run={args.run}: 지울 유저가 없다")
            return 0
        for table in TABLES:
            db.execute(
                text(f"DELETE FROM {table} WHERE user_id = ANY(CAST(:ids AS bigint[]))"), {"ids": list(ids)}
            )
        db.execute(text("DELETE FROM users WHERE id = ANY(CAST(:ids AS bigint[]))"), {"ids": list(ids)})
    print(f"run={args.run}: 유저 {len(ids)}명 삭제")
    return 0


if __name__ == "__main__":
    sys.exit(main())
