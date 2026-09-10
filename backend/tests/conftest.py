"""DB 연동 테스트용 픽스처.

전략 슬롯의 state 갱신은 PostgreSQL의 `jsonb_set`/`-` 연산에 직접 의존하므로(그것이
services/slot_state.py가 경합을 막는 방식이다) SQLite로는 검증할 수 없다. 그래서 이 픽스처들은
docker-compose의 개발용 postgres에 붙는다 — DB가 없으면 해당 테스트만 skip한다.

각 테스트는 자기 전용 유저를 만들고 끝나면 지운다. 개발 중 쌓인 기존 데이터와 섞이지 않게 하기
위함이며, `create_order`/`fill_order`가 내부에서 커밋하기 때문에 트랜잭션 롤백으로 격리할 수
없어 명시적으로 정리한다.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import get_engine, session_scope
from app.models import Balance, Coin, StrategySlot, User

TEST_COIN_SYMBOL = "ZZTEST"


def _database_available() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="개발용 postgres가 필요하다 (docker compose up -d postgres)",
)


@pytest.fixture
def test_coin():
    """FK 대상이 되는 합성 코인. 실제 Upbit 마켓과 무관한 심볼이라 시세 조회를 타지 않는다.

    `is_active`를 매번 되돌려 놓는다 — 개발 서버가 함께 떠 있으면 coins 동기화 잡이 Upbit
    마켓 목록에 없는 이 심볼을 상장폐지로 보고 `is_active=False`로 내려버려서, 주문 생성이
    CoinNotFoundError로 막힌다.
    """
    with session_scope() as db:
        coin = db.get(Coin, TEST_COIN_SYMBOL)
        if coin is None:
            db.add(
                Coin(
                    symbol=TEST_COIN_SYMBOL,
                    market_code=f"KRW-{TEST_COIN_SYMBOL}",
                    korean_name="테스트코인",
                    english_name="Test Coin",
                    is_active=True,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        else:
            coin.is_active = True
    yield TEST_COIN_SYMBOL
    # 코인은 다른 테스트도 공유하므로 지우지 않는다 (유저별 데이터만 정리한다).


@pytest.fixture
def test_user(test_coin):
    """시드머니를 가진 임시 유저. 종료 시 이 유저가 만든 모든 행을 지운다."""
    email = f"worker-test-{uuid.uuid4().hex[:12]}@example.com"
    with session_scope() as db:
        user = User(email=email, password_hash="x", created_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(
            Balance(
                user_id=user_id,
                krw_balance=Decimal("10000000"),
                updated_at=datetime.now(timezone.utc),
            )
        )

    yield user_id

    # FK 의존 순서대로 정리한다 — orders.strategy_slot_id가 strategy_slots를 참조하므로
    # 슬롯보다 주문을 먼저 지워야 한다. backtest_trades는 backtest_results를 ON DELETE CASCADE로
    # 참조하므로 따로 지우지 않아도 함께 사라진다.
    with session_scope() as db:
        for table in (
            "notifications",
            "orders",
            "holdings",
            "strategy_slots",
            "backtest_results",
            "balances",
        ):
            db.execute(text(f"DELETE FROM {table} WHERE user_id = :user_id"), {"user_id": user_id})
        db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})


@pytest.fixture
def make_slot(test_user, test_coin):
    """활성 상태의 전략 슬롯을 만들어 id를 돌려주는 팩토리."""

    def _make(
        strategy_type: str = "trend",
        indicator: str | None = "ma",
        params: dict | None = None,
        invest_amount: Decimal = Decimal("1000000"),
        stop_loss_pct: Decimal | None = None,
        take_profit_pct: Decimal | None = None,
        state: dict | None = None,
        is_active: bool = True,
    ) -> int:
        with session_scope() as db:
            slot = StrategySlot(
                user_id=test_user,
                coin_symbol=test_coin,
                strategy_type=strategy_type,
                indicator=indicator,
                params=params or {"interval": "1d", "short_period": 2, "long_period": 3},
                invest_amount=invest_amount,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                state=state if state is not None else {},
                is_active=is_active,
                created_at=datetime.now(timezone.utc),
            )
            db.add(slot)
            db.flush()
            return slot.id

    return _make


@pytest.fixture
def set_price(test_coin):
    """시세 캐시에 합성 코인의 현재가를 주입한다.

    시장가 체결(services/orders.py)과 워커의 손절·익절 판정이 모두 이 프로세스 메모리 캐시를
    읽으므로, 실제 Upbit 연결 없이 가격을 통제하려면 여기에 직접 넣는 것이 유일한 주입 지점이다
    (07 계획 Step 2B "가짜 시세를 주입해 tick을 직접 호출").
    """
    from app.services import price_stream

    def _set(price) -> None:
        price_stream._price_cache[test_coin] = {
            "symbol": test_coin,
            "trade_price": float(price),
        }

    yield _set
    price_stream._price_cache.pop(test_coin, None)


def load_slot_state(slot_id: int) -> dict:
    with session_scope() as db:
        return dict(db.get(StrategySlot, slot_id).state)
