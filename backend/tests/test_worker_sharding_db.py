"""워커 샤드 점유와 샤드 경계 tick (확장판 7단계, 03-worker-orchestration.md 2장).

**`max_instances=1`은 한 프로세스 안에서만 유효하다.** 프로세스를 늘리는 순간 같은 슬롯을
두 워커가 동시에 평가해 중복 주문이 나가므로, 샤드 점유가 그 자리를 대신한다.

여기서 못 박는 것:

1. 샤드 경계가 실제로 슬롯을 가른다 — 내 샤드가 아닌 슬롯은 평가하지 않는다.
2. 아무 샤드도 못 잡으면 아무것도 안 한다 (남의 샤드를 침범하지 않는다).
3. `claim_candle`이 샤드 소유권과 **무관하게** 두 번째 방어선으로 남는다 — 재균형 중 두
   프로세스가 같은 슬롯을 잠깐 보더라도 주문은 한 번만 나간다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database import session_scope
from app.models import Order, StrategySlot
from app.services import leader, sharding, slot_state
from app.strategy_engine import worker
from tests.conftest import requires_db

MA_PARAMS = {"interval": "1d", "short_period": 2, "long_period": 3}
PRICE = Decimal("1000")
CANDLE_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Candle:
    def __init__(self, opened_at: datetime, close: Decimal) -> None:
        self.opened_at = opened_at
        self.close = close


def _buy_signal_candles() -> list[_Candle]:
    """골든크로스가 나는 확정봉 (test_worker_db.py와 같은 모양)."""
    return [
        _Candle(CANDLE_START + timedelta(days=index), Decimal(str(close)))
        for index, close in enumerate([100, 100, 100, 100, 300])
    ]


@pytest.fixture
def feed_candles(monkeypatch):
    from app.services import candles as candles_service

    monkeypatch.setattr(
        candles_service,
        "get_confirmed_candles",
        lambda db, symbol, interval, **kwargs: _buy_signal_candles(),
    )


@pytest.fixture(autouse=True)
def released_shards():
    """테스트마다 점유를 깨끗이 비운다. 샤드 락은 모듈 전역이라 안 놓으면 다음 테스트가
    이전 테스트의 점유 상태를 물려받는다."""
    worker.release_shards()
    yield
    worker.release_shards()


def _shard_without_active_slots(*, exclude: set[int]) -> int | None:
    """활성 슬롯이 하나도 없는 샤드 하나.

    `(my_shard + 1)`처럼 고정으로 고르면 안 된다 — 개발 DB에는 이 테스트와 무관한 활성
    슬롯이 남아 있어서, 하필 그 샤드를 고르면 "한가한 샤드"가 한가하지 않다.
    """
    with session_scope() as db:
        busy = {
            int(shard)
            for shard in db.scalars(
                select(StrategySlot.user_id % settings.shard_count)
                .where(StrategySlot.is_active)
                .distinct()
            )
        }
    free = set(range(settings.shard_count)) - busy - exclude
    return min(free) if free else None


def _order_count(user_id: int) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user_id))


@requires_db
def test_tick_skips_slots_outside_owned_shards(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """내 샤드가 아닌 슬롯은 평가하지 않는다 — 이게 없으면 프로세스를 늘린 만큼 중복 주문이 난다."""
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)

    my_shard = sharding.shard_of_user(test_user)
    others = {shard for shard in range(settings.shard_count) if shard != my_shard}
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: others)

    worker.run_tick()

    assert _order_count(test_user) == 0
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).state.get("last_evaluated_candle_at") is None


@requires_db
def test_tick_processes_slots_in_owned_shards(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """내 샤드의 슬롯은 지금까지와 똑같이 평가된다 (샤딩이 동작을 바꾸지 않는다)."""
    make_slot(params=MA_PARAMS)
    set_price(PRICE)

    my_shard = sharding.shard_of_user(test_user)
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: {my_shard})

    worker.run_tick()

    assert _order_count(test_user) == 1


@requires_db
def test_tick_does_nothing_without_shards(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """아무 샤드도 못 잡으면 아무것도 하지 않는다.

    DB가 흔들려 점유 갱신에 실패한 경우도 여기로 떨어진다 — 소유를 확신할 수 없는 상태에서
    계속 주문을 내는 것보다 멈추는 편이 안전하다. 빈 샤드 자체는 커버리지 검사가 잡는다.
    """
    make_slot(params=MA_PARAMS)
    set_price(PRICE)
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: set())

    worker.run_tick()

    assert _order_count(test_user) == 0


@requires_db
def test_claim_candle_blocks_duplicate_even_across_shards(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """**샤드 소유권과 무관한 두 번째 방어선.**

    재균형 중에는 두 프로세스가 같은 슬롯을 잠깐 함께 볼 수 있다. 그때도 주문이 한 번만
    나가야 한다 — 봉 선점(`claim_candle`)의 조건부 갱신이 그걸 보장한다
    (03-worker-orchestration.md 3.2절). 여기서는 같은 샤드를 두 번 돌려 그 상황을 만든다.
    """
    make_slot(params=MA_PARAMS)
    set_price(PRICE)
    my_shard = sharding.shard_of_user(test_user)
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: {my_shard})

    worker.run_tick()
    worker.run_tick()  # 다른 프로세스가 같은 슬롯을 또 본 것과 같다

    assert _order_count(test_user) == 1


@requires_db
def test_heartbeat_is_written_per_shard(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """샤드별로 한 행씩 남긴다 — 슬롯이 없는 샤드도 남겨야 "한가한 샤드"와 "아무도 점유
    안 한 샤드"가 구분된다 (06-observability.md 3.4절)."""
    from app.models import WorkerHeartbeat
    from app.services import heartbeat

    if settings.shard_count < 2:
        pytest.skip("한가한 샤드를 만들 수 없다 (SHARD_COUNT=1 롤백 구성)")

    make_slot(params=MA_PARAMS)
    set_price(PRICE)
    my_shard = sharding.shard_of_user(test_user)
    idle_shard = _shard_without_active_slots(exclude={my_shard})
    if idle_shard is None:
        pytest.skip("모든 샤드에 활성 슬롯이 있어 한가한 샤드를 만들 수 없다")
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: {my_shard, idle_shard})

    worker.run_tick()

    # 값은 세션 안에서 꺼낸다 — ORM 객체를 들고 나오면 세션이 닫히는 순간 속성이 만료된다.
    with session_scope() as db:
        item_counts = dict(
            db.execute(
                select(WorkerHeartbeat.shard_id, WorkerHeartbeat.item_count).where(
                    WorkerHeartbeat.role == "worker",
                    WorkerHeartbeat.process_id == heartbeat._PROCESS_ID,
                    WorkerHeartbeat.shard_id.in_([my_shard, idle_shard]),
                )
            ).all()
        )

    assert set(item_counts) == {my_shard, idle_shard}
    assert item_counts[my_shard] >= 1
    assert item_counts[idle_shard] == 0


@requires_db
def test_user_shard_matches_sql_expression(test_user):
    """애플리케이션과 SQL이 같은 샤드 번호를 낸다.

    유저 샤딩을 고른 이유 중 하나가 이것이다 — crc32였다면 Python과 PostgreSQL의 구현이
    일치하는지부터 맞춰야 했다 (03-worker-orchestration.md 2.1절). 어긋나면 워커가 자기
    샤드라고 믿는 슬롯과 SQL이 돌려주는 슬롯이 달라진다.
    """
    with session_scope() as db:
        from_sql = db.scalar(
            select(StrategySlot.user_id % settings.shard_count).where(
                StrategySlot.user_id == test_user
            ).limit(1)
        )
        if from_sql is None:  # 이 유저의 슬롯이 아직 없으면 직접 계산해 비교한다
            from_sql = db.scalar(select(func.mod(test_user, settings.shard_count)))

    assert int(from_sql) == sharding.shard_of_user(test_user)
