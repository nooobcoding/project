"""`matcher` 역할 — `ticks:{symbol}`을 구독해 자기 샤드의 체결을 처리한다.

지금까지 체결 엔진은 시세 수신 루프 안에서 `asyncio.to_thread`로 불렸다. 즉 시세 프로세스와
체결 프로세스가 물리적으로 같은 프로세스였다 (00-architecture.md 1장 ③). 확장판 5단계에서
그 호출을 떼어내 구독으로 바꾼다 — **체결 절차 자체는 한 글자도 바뀌지 않는다. 누가
부르느냐만 바뀐다** (02-market-data.md 4.1절).

**샤딩 키는 `coin_symbol`이다.** 틱이 심볼 단위로 오고, 한 심볼 안에서의 체결 순서를
보장해야 하기 때문이다 (7단계의 worker는 `user_id`로 나눈다 — 이유는 sharding.py 참고).

**샤드가 겹치는 것은 무해하다.** 재균형 중 두 matcher가 같은 심볼을 볼 수 있지만,
[09-execution-engine 3.1절]의 조건부 `UPDATE`(`WHERE id=? AND status='pending'`)가 이미
중복 체결을 구조적으로 막는다 — 둘 중 하나만 `rowcount=1`을 받는다. 이것이 matcher 분리가
워커 샤딩(7단계)보다 훨씬 가벼운 이유다.

**반면 샤드가 비는 것은 위험하다.** 아무도 점유하지 않은 샤드의 지정가 주문은 영영 체결되지
않는데 프로세스는 전부 정상으로 보인다. 그래서 `scheduler`가 커버리지를 따로 감시한다
(06-observability.md 3.4절).
"""

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal

from app.config import settings
from app.services import heartbeat, leader, matcher, sharding, tick_bus

logger = logging.getLogger(__name__)

# 샤드 재균형 주기. 죽은 프로세스의 샤드를 다른 프로세스가 집어가는 데 걸리는 시간이자,
# 잃은 샤드를 알아채는 주기다.
SHARD_REFRESH_INTERVAL_SECONDS = 15
# matcher는 틱마다 도므로 매 틱 heartbeat를 쓰면 안 된다 — 묶어서 N초에 한 번만 쓴다
# (06-observability.md 2장).
HEARTBEAT_INTERVAL_SECONDS = 30


class _Counters:
    """heartbeat 주기 사이에 쌓이는 집계. 틱마다 DB를 쓰지 않기 위한 버퍼다."""

    def __init__(self) -> None:
        self.owned: set[int] = set()
        self.tick_count = 0
        self.error_count = 0
        self.max_duration_ms = 0

    def take(self) -> tuple[int, int, int]:
        counts = (self.tick_count, self.error_count, self.max_duration_ms)
        self.tick_count = 0
        self.error_count = 0
        self.max_duration_ms = 0
        return counts


async def run_matcher() -> None:
    """`matcher` 역할 진입점."""
    shards = leader.ShardLocks(
        leader.MATCHER_SHARD_NAMESPACE, settings.shard_count, "matcher"
    )
    counters = _Counters()

    subscribed = False

    async def sync_subscriptions(pubsub) -> bool:
        # 심볼별로 구독하지 않고 패턴 하나로 받는다 — 소유 샤드는 재균형 때마다 바뀌고
        # 상장/폐지로 심볼 목록도 바뀌는데, 패턴 구독이면 그때마다 구독을 다시 맞출 필요가
        # 없다. 내 샤드가 아닌 틱은 아래에서 버린다 (crc32 + 집합 조회라 싸다).
        nonlocal subscribed
        if not subscribed:
            await pubsub.psubscribe(f"{tick_bus.CHANNEL_PREFIX}*")
            subscribed = True
        return True

    def forget_subscription() -> None:
        nonlocal subscribed
        subscribed = False

    async def on_tick(symbol: str, tick: dict) -> None:
        if sharding.shard_of(symbol) not in counters.owned:
            return
        await asyncio.to_thread(_run_matching_safely, symbol, tick, counters)

    periodic = asyncio.create_task(_run_periodic(shards, counters))
    try:
        await tick_bus.consume_ticks(
            sync_subscriptions, on_tick, on_reconnect=forget_subscription
        )
    finally:
        periodic.cancel()
        with suppress(asyncio.CancelledError):
            await periodic
        await asyncio.to_thread(shards.release_all)


def _run_matching_safely(symbol: str, tick: dict, counters: _Counters) -> None:
    """체결 엔진 호출 (09-execution-engine.md 2장). 한 심볼의 실패가 구독 루프를 끊지
    않도록 예외를 삼키되, **삼킨 예외는 반드시 센다** (06-observability.md 5장)."""
    started = time.monotonic()
    try:
        matcher.run_matching_for_symbol(symbol, Decimal(str(tick["trade_price"])))
    except Exception:
        counters.error_count += 1
        logger.exception("체결 엔진 처리 실패 (symbol=%s)", symbol)
    finally:
        counters.tick_count += 1
        duration_ms = int((time.monotonic() - started) * 1000)
        counters.max_duration_ms = max(counters.max_duration_ms, duration_ms)


async def _run_periodic(shards: leader.ShardLocks, counters: _Counters) -> None:
    """샤드 재균형과 heartbeat를 한 루프에서 돌린다."""
    last_heartbeat = 0.0
    while True:
        counters.owned = await asyncio.to_thread(shards.refresh)

        if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            last_heartbeat = time.monotonic()
            await asyncio.to_thread(_write_heartbeats, counters)

        await asyncio.sleep(SHARD_REFRESH_INTERVAL_SECONDS)


def _write_heartbeats(counters: _Counters) -> None:
    """샤드마다 한 행씩 남긴다 — 커버리지·편차를 샤드 단위로 봐야 하기 때문이다.

    집계는 프로세스 단위로 쌓이므로 tick/error 수는 대표 샤드 하나에만 싣는다. 나눠 싣으면
    합계는 맞아도 샤드별 값이 실제 부하와 무관한 숫자가 된다.
    """
    tick_count, error_count, max_duration_ms = counters.take()
    started_at = datetime.now(timezone.utc)
    owned = sorted(counters.owned)

    for index, shard_id in enumerate(owned):
        try:
            heartbeat.record_tick(
                role="matcher",
                shard_id=shard_id,
                started_at=started_at,
                duration_ms=max_duration_ms if index == 0 else 0,
                budget_ms=HEARTBEAT_INTERVAL_SECONDS * 1000,
                item_count=tick_count if index == 0 else 0,
                error_count=error_count if index == 0 else 0,
                skip_count=0,
            )
        except Exception:
            logger.exception("matcher heartbeat 기록 실패 (shard=%s)", shard_id)
