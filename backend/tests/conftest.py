"""DB 연동 테스트용 픽스처.

전략 슬롯의 state 갱신은 PostgreSQL의 `jsonb_set`/`-` 연산에 직접 의존하므로(그것이
services/slot_state.py가 경합을 막는 방식이다) SQLite로는 검증할 수 없다. 그래서 이 픽스처들은
docker-compose의 개발용 postgres에 붙는다 — DB가 없으면 해당 테스트만 skip한다.

각 테스트는 자기 전용 유저를 만들고 끝나면 지운다. 개발 중 쌓인 기존 데이터와 섞이지 않게 하기
위함이며, `create_order`/`fill_order`가 내부에서 커밋하기 때문에 트랜잭션 롤백으로 격리할 수
없어 명시적으로 정리한다.
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import get_engine, session_scope
from app.models import Balance, Coin, StrategySlot, User

TEST_COIN_SYMBOL = "ZZTEST"

# DB 없이 돌리는 것을 **명시적으로** 허용하는 스위치. 기본값은 꺼짐이다.
ALLOW_SKIP_ENV = "ALLOW_SKIP_DB_TESTS"


def _database_available() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


_DB_AVAILABLE = _database_available()

# DB가 없을 때 무엇을 할지가 이 파일에서 가장 중요한 결정이다.
#
# 예전에는 무조건 skip이었다. 그런데 DB 연동 테스트가 전체의 2/3라, postgres를 안 띄우고
# 돌리면 **3분의 2가 조용히 빠지고 결과는 "passed"로 보인다.** 자금 경로 테스트가 전부 그
# 안에 있으므로, 그 상태의 초록불은 아무것도 보장하지 않으면서 보장하는 것처럼 보인다 —
# 조용한 실패 금지 규칙이 테스트 스위트 자신에게도 적용돼야 한다.
#
# 그래서 기본값을 **실패**로 바꾼다. DB 없이 순수 함수만 빠르게 돌리고 싶을 때는
# `ALLOW_SKIP_DB_TESTS=1`로 의도를 밝히면 된다.
_SKIP_ALLOWED = os.getenv(ALLOW_SKIP_ENV, "").lower() in ("1", "true", "yes")

if _DB_AVAILABLE or not _SKIP_ALLOWED:
    # DB가 있으면 그냥 돈다. 없는데 건너뛰기도 허용 안 됐으면 아래 훅이 세션을 중단시키므로
    # 여기서는 마커만 달아 둔다 (`-m db`로 골라 돌릴 수도 있다).
    requires_db = pytest.mark.db
else:
    requires_db = pytest.mark.skipif(
        True,
        reason=f"postgres 없음 — {ALLOW_SKIP_ENV}로 건너뛰기를 명시적으로 허용했다",
    )


def pytest_collection_modifyitems(config, items):
    """DB가 필요한 테스트를 수집했는데 DB가 없으면 **세션을 중단한다.**

    조용히 skip하지 않는 이유가 이 파일의 핵심이다 — 위 주석 참고. 다만 순수 함수 테스트만
    돌리는 경우(`pytest tests/test_grid.py`)는 DB가 필요 없으므로, **DB 연동 테스트가 실제로
    수집됐을 때만** 막는다.
    """
    if _DB_AVAILABLE or _SKIP_ALLOWED:
        return

    db_items = [item for item in items if item.get_closest_marker("db")]
    if not db_items:
        return

    raise pytest.UsageError(
        f"DB 연동 테스트 {len(db_items)}개를 수집했지만 개발용 postgres에 붙을 수 없다.\n"
        "  `docker compose up -d postgres`로 띄우거나,\n"
        f"  의도적으로 건너뛰려면 {ALLOW_SKIP_ENV}=1 을 지정할 것.\n"
        "  (그냥 skip하면 자금 경로 테스트가 통째로 빠진 채 초록불이 된다)"
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
def make_user(test_coin):
    """시드머니를 가진 임시 유저를 만드는 팩토리. 만든 유저는 전부 종료 시 지운다.

    IDOR 검증처럼 **서로 다른 두 유저**가 필요한 테스트가 있어서 팩토리로 둔다 — 정리
    목록(FK 순서)을 한 곳에만 두기 위해 `test_user`도 이 팩토리를 쓴다.
    """
    created: list[int] = []

    def _make(password_hash: str = "x") -> int:
        email = f"worker-test-{uuid.uuid4().hex[:12]}@example.com"
        with session_scope() as db:
            user = User(
                email=email, password_hash=password_hash, created_at=datetime.now(timezone.utc)
            )
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
        created.append(user_id)
        return user_id

    yield _make

    # FK 의존 순서대로 정리한다 — orders.strategy_slot_id가 strategy_slots를 참조하므로
    # 슬롯보다 주문을 먼저 지워야 한다. backtest_trades는 backtest_results를 ON DELETE CASCADE로
    # 참조하므로 따로 지우지 않아도 함께 사라진다.
    with session_scope() as db:
        for user_id in created:
            # 슬롯 대상 감사 로그는 슬롯이 지워져도 남는다(target_id에 FK가 없다) — 슬롯을 지우기 전에 치운다.
            db.execute(
                text(
                    "DELETE FROM audit_logs WHERE target_type = 'strategy_slot' AND target_id IN "
                    "(SELECT id FROM strategy_slots WHERE user_id = :user_id)"
                ),
                {"user_id": user_id},
            )
            for table in (
                "notifications",
                "orders",
                "holdings",
                "strategy_slots",
                "backtest_results",
                "balances",
                "watchlists",
                "notification_settings",
            ):
                db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :user_id"), {"user_id": user_id}
                )
            # 감사 로그는 대상이 탈퇴해도 남는 게 정상 동작이라 FK로 안 지워진다 — 테스트 유저 것만 치운다.
            db.execute(
                text(
                    "DELETE FROM audit_logs WHERE actor_user_id = :user_id"
                    " OR (target_type = 'user' AND target_id = :user_id)"
                ),
                {"user_id": user_id},
            )
            db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})


@pytest.fixture
def test_user(make_user):
    """시드머니를 가진 임시 유저 하나."""
    return make_user()


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트.

    `with` 없이 만든다 — 컨텍스트 매니저로 쓰면 lifespan이 돌면서 시세 스트림·스케줄러·
    워커가 실제로 뜬다. 라우터 계약만 보는 테스트에 그 백그라운드 스레드는 불필요하고,
    개발 DB를 건드리는 부작용까지 따라온다.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture
def auth_headers(test_user):
    """`test_user`로 인증된 요청 헤더."""
    from app.services.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(test_user)}"}


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

    시장가 체결(services/orders.py)과 워커의 손절·익절 판정이 모두 이 캐시를 읽으므로,
    실제 Upbit 연결 없이 가격을 통제하려면 여기서 주입하는 것이 유일한 지점이다 (07 계획
    Step 2B "가짜 시세를 주입해 tick을 직접 호출"). `price_cache.set_price`를 그대로 써서
    received_at도 함께 찍는다 — 그래야 확장판 stale 방어(02-market-data.md 3.3절)에
    걸리지 않는다.
    """
    from app.services import price_cache

    def _set(price) -> None:
        price_cache.set_price(test_coin, {"symbol": test_coin, "trade_price": float(price)})

    yield _set
    price_cache.delete_price(test_coin)


def load_slot_state(slot_id: int) -> dict:
    with session_scope() as db:
        return dict(db.get(StrategySlot, slot_id).state)
