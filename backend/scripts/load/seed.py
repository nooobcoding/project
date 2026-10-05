"""부하 측정용 유저·활성 슬롯 일괄 생성 (docs-scale/08-capacity.md).

유저 N명을 만들고 각자 잔고 1,000만 원 + 활성 슬롯 1개를 준다. 코인은 실제 KRW 마켓 24개,
봉은 1분이라 매분 새 확정봉이 나올 때 모든 슬롯이 실제로 평가된다. 전략은 추세추종·역추세 ×
지표 4개 = 8가지를 골고루 섞는다. user_id가 연속으로 잡히므로 샤드(user_id % 16)에 고르게 퍼진다.

API를 거치지 않고 SQL로 넣는다 — 만 명을 API로 만들면 bcrypt만 몇 분이다. 대신 파라미터는
API와 같은 `validate_params_for`로 검증해, 화면에서 만들 수 없는 슬롯이 섞이지 않게 한다.

사용법 (컨테이너 안):
    python scripts/load/seed.py --run bench --users 3000 [--tokens 200]
`--tokens K`를 주면 앞 K명의 JWT를 마지막 줄에 JSON으로 출력한다 (API 부하용).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import insert, text  # noqa: E402

from app.database import session_scope  # noqa: E402
from app.models import StrategySlot  # noqa: E402
from app.schemas.strategy_slots import validate_params_for  # noqa: E402
from app.services.auth import create_access_token, hash_password  # noqa: E402

COINS = [
    "BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "TRX", "AVAX", "LINK", "DOT", "BCH", "ETC",
    "XLM", "SUI", "NEAR", "APT", "HBAR", "SHIB", "ATOM", "SAND", "AAVE", "UNI", "ARB", "SEI",
]
# API 부하의 소액 시장가 매수용 — 단가가 낮아 수량 1이 잔고를 크게 안 쓴다
ORDER_COINS = ["XRP", "DOGE", "ADA"]
INTERVAL = "1m"
STRATEGIES = [
    ("trend", "ma", {"short_period": 5, "long_period": 20}),
    ("trend", "rsi", {"period": 14}),
    ("trend", "macd", {"short_period": 12, "long_period": 26, "signal_period": 9}),
    ("trend", "bollinger", {"period": 20, "std_multiplier": 2.0}),
    ("counter_trend", "ma", {"short_period": 5, "long_period": 20, "deviation_pct": 3}),
    ("counter_trend", "rsi", {"period": 14, "oversold": 30, "overbought": 70}),
    ("counter_trend", "macd", {"short_period": 12, "long_period": 26, "signal_period": 9}),
    ("counter_trend", "bollinger", {"period": 20, "std_multiplier": 2.0}),
]
SEED_KRW = Decimal("10000000")
INVEST_KRW = Decimal("1000000")
PASSWORD = "Passw0rd!load"


def email_prefix(run: str) -> str:
    return f"load-{run}-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="bench")
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--tokens", type=int, default=0)
    args = parser.parse_args()

    strategies = [
        (strategy_type, indicator, validate_params_for(strategy_type, indicator, {"interval": INTERVAL, **params}))
        for strategy_type, indicator, params in STRATEGIES
    ]
    password_hash = hash_password(PASSWORD)  # 전원 같은 해시 — bcrypt를 N번 돌리지 않는다
    prefix = email_prefix(args.run)
    now = datetime.now(timezone.utc)

    with session_scope() as db:
        start = db.scalar(
            text("SELECT COUNT(*) FROM users WHERE email LIKE :p"), {"p": f"{prefix}%"}
        )
        user_ids = db.execute(
            text(
                "INSERT INTO users (email, password_hash, created_at) "
                "SELECT :prefix || g || '@example.com', :hash, now() "
                "FROM generate_series(:first, :last) g RETURNING id"
            ),
            {"prefix": prefix, "hash": password_hash, "first": start + 1, "last": start + args.users},
        ).scalars().all()
        db.execute(
            text(
                "INSERT INTO balances (user_id, krw_balance, updated_at) "
                "SELECT id, :krw, now() FROM unnest(CAST(:ids AS bigint[])) id"
            ),
            {"krw": SEED_KRW, "ids": list(user_ids)},
        )
        rows = []
        for index, user_id in enumerate(sorted(user_ids)):
            strategy_type, indicator, params = strategies[index % len(strategies)]
            rows.append(
                {
                    "user_id": user_id,
                    "coin_symbol": COINS[index % len(COINS)],
                    "strategy_type": strategy_type,
                    "indicator": indicator,
                    "params": params,
                    "invest_amount": INVEST_KRW,
                    "stop_loss_pct": None,
                    "take_profit_pct": None,
                    "state": {},
                    "is_active": True,
                    "created_at": now,
                }
            )
        for chunk in range(0, len(rows), 2000):
            db.execute(insert(StrategySlot), rows[chunk : chunk + 2000])

        total = db.scalar(
            text(
                "SELECT COUNT(*) FROM strategy_slots s JOIN users u ON u.id = s.user_id "
                "WHERE u.email LIKE :p AND s.is_active"
            ),
            {"p": f"{prefix}%"},
        )

    print(f"run={args.run}: 유저 {len(user_ids)}명 추가 (이 run 활성 슬롯 합계 {total}개)")
    if args.tokens:
        # 수동 주문 코인은 슬롯 코인과 달라야 한다 — 활성 슬롯이 있는 코인은 수동 주문이 잠긴다(FR-M10)
        users = [
            {
                "token": create_access_token(user_id),
                "order_coin": next(c for c in ORDER_COINS if c != COINS[index % len(COINS)]),
            }
            for index, user_id in enumerate(sorted(user_ids)[: args.tokens])
        ]
        print(json.dumps(users))
    return 0


if __name__ == "__main__":
    sys.exit(main())
