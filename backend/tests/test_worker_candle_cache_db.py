"""워커 tick의 확정봉 캐시 (worker._confirmed_candles).

슬롯마다 매 tick 확정봉을 DB에서 읽던 것이 워커 처리 한계의 97%였다(슬롯당 6.3ms 중 6.1ms).
(코인, 봉 간격)마다 tick당 한 번만 읽게 바꿨고, 여기서는 그 캐시가 **tick 하나를 넘어 살지
않는지**를 함께 본다 — 넘어 살면 새 확정봉을 놓쳐 자동매매가 조용히 멈춘다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.config import settings
from app.database import session_scope
from app.models import StrategySlot
from app.services import candles as candles_service
from app.services import leader
from app.strategy_engine import worker
from tests.conftest import requires_db

pytestmark = requires_db

MA_PARAMS = {"interval": "1d", "short_period": 2, "long_period": 3}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Candle:
    def __init__(self, opened_at: datetime, close: Decimal) -> None:
        self.opened_at = opened_at
        self.close = close


def _flat_candles(count: int) -> list[_Candle]:
    """신호가 안 나는 평평한 봉 — 주문 없이 평가 경로만 태운다."""
    return [_Candle(START + timedelta(days=i), Decimal("100")) for i in range(count)]


@pytest.fixture
def candle_feed(monkeypatch, test_coin):
    """확정봉 조회를 가로채 테스트 코인 조회 횟수를 센다. `feed["count"]`로 봉 수를 바꾼다."""
    feed = {"count": 5, "calls": 0}

    def fake(db, symbol, interval, **kwargs):
        if symbol == test_coin:
            feed["calls"] += 1
        return _flat_candles(feed["count"])

    monkeypatch.setattr(candles_service, "get_confirmed_candles", fake)
    return feed


@pytest.fixture
def all_shards(monkeypatch):
    monkeypatch.setattr(leader.ShardLocks, "refresh", lambda self: set(range(settings.shard_count)))
    yield
    worker.release_shards()


def _active_slot(user_id: int, coin: str) -> int:
    with session_scope() as db:
        slot = StrategySlot(
            user_id=user_id,
            coin_symbol=coin,
            strategy_type="trend",
            indicator="ma",
            params=MA_PARAMS,
            invest_amount=Decimal("1000000"),
            state={},
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(slot)
        db.flush()
        return slot.id


def _evaluated_at(slot_id: int) -> str | None:
    with session_scope() as db:
        return db.get(StrategySlot, slot_id).state.get("last_evaluated_candle_at")


def test_one_load_per_coin_per_tick(make_user, test_coin, candle_feed, all_shards):
    """같은 코인의 슬롯이 여럿이어도 tick 한 번에 봉은 한 번만 읽는다."""
    slots = [_active_slot(make_user(), test_coin) for _ in range(3)]

    worker.run_tick()

    assert candle_feed["calls"] == 1
    # 셋 다 실제로 평가됐다 — 캐시가 평가를 건너뛰게 만든 게 아니다
    assert all(_evaluated_at(slot_id) is not None for slot_id in slots)


def test_cache_does_not_outlive_the_tick(make_user, test_coin, candle_feed, all_shards):
    """다음 tick에는 새로 읽는다 — 그 사이 새 확정봉이 나왔으면 그 봉으로 평가해야 한다."""
    slot_id = _active_slot(make_user(), test_coin)

    worker.run_tick()
    first = _evaluated_at(slot_id)

    candle_feed["count"] = 6  # 새 확정봉 하나
    worker.run_tick()

    assert candle_feed["calls"] == 2
    assert _evaluated_at(slot_id) > first
    assert worker._tick_candles is None


def test_outside_a_tick_every_call_reads_fresh(make_user, test_coin, candle_feed):
    """tick 밖(테스트·수동 호출)에서는 캐시가 없다 — 이전 호출의 봉을 물려받지 않는다."""
    slot_id = _active_slot(make_user(), test_coin)

    worker.process_slot(slot_id)
    worker.process_slot(slot_id)

    assert candle_feed["calls"] == 2
