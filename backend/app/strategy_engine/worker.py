"""07-auto-trading 상시 워커 — 활성 슬롯을 주기적으로 순회하며 신호 평가·청산을 수행한다.

브라우저 접속과 무관하게 서버에서 항상 돌아야 하므로(00-overview.md 원칙 1) main.py의
APScheduler에 10초 간격 잡으로 등록된다. tick이 겹치면 같은 슬롯을 두 번 평가해 중복 주문이
나므로 `max_instances=1`로 등록해야 한다 (main.py 참고).

tick 1회가 슬롯 하나에 대해 하는 일은 두 가지이고, 트리거 주기가 서로 다르다:

1. **청산(손절·익절)** — 매 tick 실시간 현재가로 판정한다. 확정봉을 기다리지 않는다
   (07-auto-trading.md 4장). 포지션을 지키는 일이 새 진입보다 급하므로 신호 평가보다 먼저 본다.
2. **신호 평가** — 새 확정봉이 생겼을 때만 한다. 같은 봉을 여러 tick에서 반복 평가하면 같은
   신호로 중복 주문이 나가므로, `slot_state.claim_candle`로 봉을 선점한 뒤에만 평가한다.

**주문 중에는 슬롯 행 잠금을 쥐지 않는다.** 주문 경로(`create_order` → `fill_order` →
체결 후처리)가 같은 슬롯 행의 `state.position`을 갱신하므로, 워커가 잠금을 쥔 채 주문하면
교착하거나 tick이 멈춘다. 봉 선점은 주문 "전에" 별도 트랜잭션으로 커밋한다.

`state`의 어느 키를 누가 쓰는지는 services/slot_state.py 참고 — 워커는 `position`을 읽기만 하고
절대 쓰지 않는다.

**워커는 Upbit REST를 부르지 않는다** (확장판 6단계, docs-scale/03-worker-orchestration.md
5.1절). 캔들은 DB 캐시만 읽고, 없으면 이번 tick 평가를 건너뛴 뒤 기록한다. 캐시를 채우는
일은 `scheduler` 역할이 맡는다 (services/candle_prefill.py).

**워커는 자기가 점유한 샤드의 슬롯만 순회한다** (확장판 7단계, 같은 문서 2장). 샤딩 키는
`user_id`다 — 심볼로 나누면 BTC 쏠림 하나로 프로세스를 늘려도 유효 병렬도가 안 오른다
(00-architecture.md 3.1절). `max_instances=1`은 한 프로세스 안에서만 유효하므로, 프로세스를
늘리는 순간 그것만으로는 중복 평가를 막지 못한다.

**샤딩이 보장하는 것은 "한 유저의 슬롯이 두 워커에서 동시에 평가되지 않는다" 하나뿐이다.**
자금 정합성은 여전히 DB가 지킨다 — 같은 `balances` 행을 matcher(심볼 샤드)와 api(수동 주문)도
건드리므로, 09-execution-engine.md 3.4절 잠금 순서 규칙이 그대로 유효하다
(00-architecture.md 3.1.1절). 그리고 `claim_candle`의 조건부 갱신이 샤드 소유권과 **무관하게**
두 번째 방어선으로 남는다 — 재균형 중 두 프로세스가 같은 슬롯을 잠깐 보더라도 주문은 한 번만
나간다.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.strategy_engine.costs import calc_buy_amount, calc_buy_quantity
from app.models import Coin, Notification, NotificationSetting, StrategySlot
from app.services import candles as candles_service
from app.services import heartbeat, leader, sharding
from app.services import notifications as notifications_service
from app.services import price_cache, slot_state
from app.strategy_engine import reconcile
from app.services.orders import (
    InsufficientBalanceError,
    InsufficientHoldingError,
    create_order,
    get_available_quantity,
)
from app.strategy_engine import dca, exits, grid, runner
from app.strategy_engine.intents import TradeIntent

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 10  # 07-auto-trading.md 4장
_QUANTITY_STEP = Decimal("0.00000001")  # orders.quantity NUMERIC(28,8)

# tick 1회 동안 건너뛴 횟수 누적 (캔들 없음·시세 stale·잔고 부족, 06-observability.md 5장).
# run_tick이 매 tick 시작 시 리셋하고 끝에 heartbeat로 흘려보낸다 — max_instances=1이라
# 동시 접근이 없다(main.py 참고).
_tick_skip_count = 0

# 건너뛴 이유들. worker_heartbeats.skip_count는 합계 하나뿐이라, "왜 건너뛰었는지 구분
# 가능해야 한다"(06-observability.md 5장 2항)는 로그가 감당한다. 이유를 상수로 묶어 두면
# 로그를 이유별로 집계할 수 있다.
SKIP_NO_CANDLES = "candles"
SKIP_NO_PRICE = "price"
SKIP_INSUFFICIENT_BALANCE = "balance"
SKIP_INSUFFICIENT_HOLDING = "holding"

# 이 프로세스가 점유한 워커 샤드. tick마다 갱신하며, 이전 tick 대비 **새로 잡은** 샤드가
# 재조정 대상이다 (03-worker-orchestration.md 2.4절).
_shards: "leader.ShardLocks | None" = None
_owned_shards: set[int] = set()


def _record_skip(reason: str, slot_id: int, detail: str = "") -> None:
    """건너뛴 사실을 세고 이유를 남긴다.

    숫자만 올리면 "스킵 12회"까지만 알 수 있고 "왜"는 알 수 없다. 자동매매에서 스킵은
    "신호가 났는데 주문이 안 나갔다"는 뜻이라, 사용자에게는 침묵으로만 보인다.
    """
    global _tick_skip_count
    _tick_skip_count += 1
    logger.info("자동매매 워커: 슬롯 %s 건너뜀 (reason=%s)%s", slot_id, reason, detail)


@dataclass
class _SlotSnapshot:
    """세션 밖에서 쓰기 위해 슬롯 값을 복사해 둔 것.

    ORM 객체를 그대로 들고 다니면 세션이 닫히는 순간 속성이 만료돼(detached) 접근할 수 없고,
    반대로 세션을 열어둔 채 주문을 내면 트랜잭션이 길어져 체결 경로와 경합한다.
    """

    id: int
    user_id: int
    coin_symbol: str
    strategy_type: str
    indicator: str | None
    params: dict[str, Any]
    state: dict[str, Any]
    invest_amount: Decimal
    stop_loss_pct: Decimal | None
    take_profit_pct: Decimal | None


@dataclass
class _CandlePoint:
    """runner.evaluate가 요구하는 CandleLike(opened_at/close)만 담은 값 복사본."""

    opened_at: datetime
    close: Decimal


@dataclass
class _ShardStats:
    """샤드 하나의 이번 tick 집계. 샤드별로 따로 남겨야 편차가 보인다 —
    관리자 화면이 이 값으로 `SHARD_COUNT`를 올릴 시점을 판단한다 (5.2절)."""

    item_count: int = 0
    duration_ms: int = 0
    error_count: int = 0
    skip_count: int = 0


def _shard_locks() -> leader.ShardLocks:
    """이 프로세스의 워커 샤드 점유. 프로세스 수명 내내 **전용 커넥션 하나**를 붙잡는다
    (2.2절 함정 — 풀에서 꺼낸 커넥션으로 잠그면 반납·재활용되는 순간 락이 풀리고, 두
    프로세스가 같은 샤드를 점유해 중복 주문이 나기 시작한다)."""
    global _shards
    if _shards is None:
        _shards = leader.ShardLocks(
            leader.WORKER_SHARD_NAMESPACE, settings.shard_count, "worker"
        )
    return _shards


def release_shards() -> None:
    """프로세스 종료 시 샤드를 놓는다 (main.py lifespan). 안 놓아도 세션이 끊기면 풀리지만,
    명시적으로 풀어야 남은 프로세스가 다음 주기에 바로 집어간다."""
    global _shards, _owned_shards
    if _shards is not None:
        _shards.release_all()
        _shards = None
    _owned_shards = set()


def run_tick() -> None:
    """점유한 샤드의 활성 슬롯을 1회 순회한다. APScheduler가 TICK_INTERVAL_SECONDS마다 호출한다.

    슬롯 하나의 실패가 나머지 슬롯을 막지 않도록 슬롯 단위로 예외를 삼키고 로그만 남긴다
    (main.py의 coins 동기화 잡과 같은 방침). tick이 끝나면 소요 시간·예외·건너뛴 횟수를
    **샤드별로** worker_heartbeats에 남긴다 (확장판 00단계, docs-scale/06-observability.md).
    """
    global _tick_skip_count, _owned_shards
    _tick_skip_count = 0
    started_at = datetime.now(timezone.utc)
    tick_start = time.monotonic()
    stats: dict[int, _ShardStats] = {}

    previous = _owned_shards
    owned = _shard_locks().refresh()
    if not owned:
        # 아무 샤드도 못 잡았다. 다른 프로세스가 전부 쥐고 있거나 DB가 흔들린 것이다.
        # 어느 쪽이든 이번 tick에 할 일이 없다 — 빈 샤드 자체는 커버리지 검사가 잡는다
        # (services/shard_coverage.py).
        _owned_shards = owned
        return

    # **새로 점유한 샤드는 재조정부터 한다** (2.4절). 이 샤드를 이전에 들고 있던 프로세스가
    # 체결 직후·상태 기록 직전에 죽었을 수 있고, 그대로 평가하면 그리드는 같은 라인을 또
    # 사고 DCA는 10초 뒤에 또 산다. 점유가 곧 복구 트리거다.
    #
    # **재조정에 실패한 샤드는 이번 tick에 거래하지 않는다.** 실패했는데도 점유 기록에
    # 넣어버리면 그 샤드는 "재조정을 마친 샤드"가 되어 다시는 재조정되지 않고, 재조정이
    # 막으려던 창이 그대로 열린 채로 주문이 나간다 — DB가 잠깐 흔들린 것만으로 중복 매수가
    # 난다. 못 미더운 상태 위에서 자금을 움직이는 것보다 한 주기 쉬는 편이 낫다.
    newly_acquired = owned - previous
    unreconciled: set[int] = set()
    if newly_acquired:
        report = reconcile.reconcile_shards(newly_acquired)
        if report.errors:
            unreconciled = newly_acquired
            logger.warning(
                "자동매매 워커: 샤드 %s 재조정에 실패해 이번 tick은 건너뛴다 (다음 주기에 재시도)",
                sorted(unreconciled),
            )
            # 지표에도 남긴다 — 안 남기면 이 샤드는 heartbeat상 "슬롯 0개인 한가한 샤드"와
            # 구분되지 않는다. 실제로는 그 샤드의 자동매매가 통째로 멈춰 있는 상태다.
            for shard_id in unreconciled:
                stats.setdefault(shard_id, _ShardStats()).error_count += report.errors

    # 재조정에 실패한 샤드는 점유 기록에 넣지 않는다 — 다음 tick에 "새로 점유한 샤드"로
    # 다시 잡혀 재조정을 다시 시도하게 된다.
    _owned_shards = owned - unreconciled
    tradable = _owned_shards
    if not tradable:
        _write_heartbeats(owned, stats, started_at)
        return

    slots: list[tuple[int, int]] = []
    try:
        slots = _load_active_slots(tradable)
    except Exception:
        logger.exception("자동매매 워커: 활성 슬롯 조회 실패 (shards=%s)", sorted(tradable))
        for shard_id in tradable:
            stats.setdefault(shard_id, _ShardStats()).error_count += 1

    for shard_id, slot_id in slots:
        shard_stats = stats.setdefault(shard_id, _ShardStats())
        shard_stats.item_count += 1
        slot_start = time.monotonic()
        skips_before = _tick_skip_count
        try:
            process_slot(slot_id)
        except Exception:
            logger.exception("자동매매 워커: 슬롯 %s 처리 실패", slot_id)
            shard_stats.error_count += 1
        finally:
            shard_stats.duration_ms += int((time.monotonic() - slot_start) * 1000)
            shard_stats.skip_count += _tick_skip_count - skips_before

    total_ms = int((time.monotonic() - tick_start) * 1000)
    if total_ms > TICK_INTERVAL_SECONDS * 1000:
        # 샤드별 행만 보면 이 초과가 안 보인다 — 샤드 하나하나는 예산 안인데 합이 넘는
        # 경우가 정확히 "샤드를 더 나눠야 하는" 상태다 (5.2절 조용히 넘기지 않는다).
        logger.warning(
            "worker tick 예산 초과: %dms > %dms (샤드 %d개, 슬롯 %d개)",
            total_ms,
            TICK_INTERVAL_SECONDS * 1000,
            len(owned),
            len(slots),
        )

    _write_heartbeats(owned, stats, started_at)


def _write_heartbeats(
    owned: set[int], stats: dict[int, _ShardStats], started_at: datetime
) -> None:
    """샤드마다 한 행씩 남긴다. 슬롯이 하나도 없는 샤드도 남겨야 한다 — 행이 없으면
    "점유 중인데 한가한 샤드"와 "아무도 점유 안 한 샤드"가 구분되지 않는다."""
    for shard_id in sorted(owned):
        shard_stats = stats.get(shard_id, _ShardStats())
        try:
            heartbeat.record_tick(
                role="worker",
                shard_id=shard_id,
                started_at=started_at,
                duration_ms=shard_stats.duration_ms,
                budget_ms=TICK_INTERVAL_SECONDS * 1000,
                item_count=shard_stats.item_count,
                error_count=shard_stats.error_count,
                skip_count=shard_stats.skip_count,
            )
        except Exception:
            # 관측이 관측 대상을 망가뜨려서는 안 된다 — DB가 잠깐 흔들리거나 마이그레이션이
            # 아직 안 올라갔다고 해서 tick 잡이 예외로 끝나면 안 된다.
            logger.exception("자동매매 워커: heartbeat 기록 실패 (shard=%s)", shard_id)


def process_slot(slot_id: int) -> None:
    """슬롯 하나의 청산·신호 평가를 처리한다 (tick 1회분)."""
    slot = _load_slot_snapshot(slot_id)
    if slot is None:
        return

    # 청산이 일어났으면 이번 tick에서는 재진입을 시도하지 않는다 — 방금 판 포지션을 같은
    # tick에 도로 사는 것을 막는다.
    if _try_exit(slot):
        return

    # DCA만 확정봉 경로를 타지 않는다 — 시간 스케줄로 트리거되므로(07-auto-trading.md 4장)
    # 봉 선점에 묶으면 봉 하나당 한 번밖에 평가되지 않아 예정 시각을 맞출 수 없다.
    if slot.strategy_type == "dca":
        _try_dca(slot)
        return

    _try_signal(slot)


def _load_active_slots(owned: set[int]) -> list[tuple[int, int]]:
    """점유한 샤드의 활성 슬롯 `(shard_id, slot_id)` 목록 (2.1절의 SQL).

    샤드 번호를 SQL에서 함께 받아 온다 — 애플리케이션에서 다시 계산하면 두 곳의 식이
    어긋날 여지가 생기는데, 그게 어긋나면 슬롯이 통계상 엉뚱한 샤드에 잡힌다.
    """
    with session_scope() as db:
        rows = db.execute(
            select(
                (StrategySlot.user_id % settings.shard_count).label("shard_id"),
                StrategySlot.id,
            ).where(
                StrategySlot.is_active,
                sharding.owned_by_user_shard(StrategySlot.user_id, owned),
            )
        ).all()
    return [(int(row.shard_id), row.id) for row in rows]


def _load_slot_snapshot(slot_id: int) -> _SlotSnapshot | None:
    with session_scope() as db:
        slot = db.get(StrategySlot, slot_id)
        if slot is None or not slot.is_active:
            return None
        return _SlotSnapshot(
            id=slot.id,
            user_id=slot.user_id,
            coin_symbol=slot.coin_symbol,
            strategy_type=slot.strategy_type,
            indicator=slot.indicator,
            params=dict(slot.params),
            state=dict(slot.state),
            invest_amount=slot.invest_amount,
            stop_loss_pct=slot.stop_loss_pct,
            take_profit_pct=slot.take_profit_pct,
        )


def _current_price(slot: "_SlotSnapshot") -> Decimal | None:
    """현재가를 읽는다. 시세가 없으면(스트림 중단·Redis 장애 등) None이고, 그 자체가
    "이번 tick에서 이 슬롯을 건너뛴다"는 뜻이라 여기서 한 번만 기록한다 — 호출부마다
    따로 세면 같은 코드가 세 군데로 흩어진다."""
    tick = price_cache.get_cached_price(slot.coin_symbol)
    if tick is None:
        _record_skip(SKIP_NO_PRICE, slot.id, f" symbol={slot.coin_symbol}")
        return None
    return Decimal(str(tick["trade_price"]))


def _build_spec(slot: _SlotSnapshot) -> runner.SlotSpec:
    """`StrategySlot` → 엔진이 아는 DB 비의존 스펙으로 옮긴다 (runner.py 모듈 docstring)."""
    return runner.SlotSpec(
        strategy_type=slot.strategy_type,
        indicator=slot.indicator,
        params=slot.params,
        invest_amount=slot.invest_amount,
        state=slot.state,
        stop_loss_pct=slot.stop_loss_pct,
        take_profit_pct=slot.take_profit_pct,
    )


def _try_exit(slot: _SlotSnapshot) -> bool:
    """손절·익절 도달 시 슬롯 보유분을 청산한다. 청산 주문을 냈으면 True.

    판정은 전부 `exits.decide_exit`(엔진, 백테스팅과 공유)이 하고, 여기서는 그 결과를 주문과
    DB 기록으로 옮기기만 한다 (06 계획 A-1의 "무엇을 할지 / 어떻게 기록할지" 경계).
    """
    position = slot_state.read_position(slot.state)
    if position is None:
        return False

    current_price = _current_price(slot)
    if current_price is None:
        return False

    intent = exits.decide_exit(_build_spec(slot), position, current_price)
    if intent is None:
        return False

    requested = intent.quantity or Decimal(0)
    sold = _place_sell(slot, requested)
    if sold <= 0:
        return False

    _record_exit(slot, intent.reason, sold=sold, requested=requested)
    return True


def _record_exit(
    slot: _SlotSnapshot, reason: str, *, sold: Decimal, requested: Decimal
) -> None:
    """청산 체결 뒤 전략별 뒷정리 — 주문 자체 외에 남는 DB 작업이 여기 모인다."""
    if reason == exits.GRID_BREAKOUT:
        # 라인을 전부 비운다 — 포지션이 사라졌는데 라인이 "채워짐"으로 남아 있으면 가격이
        # 회복돼도 그 라인은 다시 매수되지 않고, 있지도 않은 수량을 팔려고 하게 된다. 슬롯은
        # 계속 ON으로 두어 가격이 범위 안으로 돌아오면 그리드를 다시 시작한다.
        #
        # **단, 전량이 실제로 팔렸을 때만이다.** 가용 수량이 모자라 일부만 팔렸는데 라인을
        # 전부 비우면 라인 합이 남은 포지션보다 작아져(불변식 위반) 그 몫을 다시 사게 된다.
        # 덜 팔렸으면 판 만큼만 높은 가격 라인부터 뺀다.
        lines = slot_state.read_grid_lines(slot.state)
        if not lines:
            return
        drained = (
            grid.initial_lines(slot.params)
            if sold >= requested
            else grid.drain_lines(lines, sold)
        )
        with session_scope() as db:
            slot_state.write_grid_lines(db, slot.id, drained)
        return

    if reason == exits.DCA_TAKE_PROFIT:
        # "전략 종료"는 슬롯을 OFF로 내리는 것으로 구현한다 (06-backtesting.md 2.5절) — 목표를
        # 달성했으니 더 분할매수하지 않는다는 뜻이고, 설정과 진행 상태는 남아 있어 사용자가
        # 확인하고 다시 켤 수 있다.
        with session_scope() as db:
            db.get(StrategySlot, slot.id).is_active = False
        _notify(
            slot,
            "exit",
            f"[{_korean_name(slot.coin_symbol)}] 목표 수익률에 도달해 전량 매도하고 자동매매를 종료했습니다.",
        )


def _ensure_grid_lines(slot: _SlotSnapshot) -> list[dict[str, Any]] | None:
    """그리드 라인 상태를 보장한다 — 없거나 파라미터와 어긋나면 새로 초기화해 저장한다.

    라인 가격은 상한/하한/격자 수에서 나오므로, 슬롯을 OFF한 사이 그 값이 바뀌면 기존 라인은
    의미를 잃는다. 포지션을 들고 있는 그리드 슬롯의 설정 변경은 services/strategy_slots.py가
    막고 있어(라인과 포지션이 어긋나면 배정액을 넘겨 사게 된다), 여기서 재초기화가 일어나는
    경우는 포지션이 없는 상태뿐이다.
    """
    lines = slot_state.read_grid_lines(slot.state)
    if grid.lines_match_params(lines, slot.params):
        return lines

    lines = grid.initial_lines(slot.params)
    with session_scope() as db:
        slot_state.write_grid_lines(db, slot.id, lines)
    slot.state.setdefault("grid", {})["lines"] = lines
    return lines


def _try_signal(slot: _SlotSnapshot) -> None:
    """새 확정봉이 있으면 그 봉으로 평가하고, 엔진이 낸 주문 의도를 순서대로 집행한다."""
    interval = slot.params.get("interval", "1d")
    with session_scope() as db:
        candles = [
            _CandlePoint(opened_at=candle.opened_at, close=candle.close)
            for candle in candles_service.get_confirmed_candles(
                db, slot.coin_symbol, interval, fetch_if_missing=False
            )
        ]
    if len(candles) < 2:
        # **여기서 Upbit를 부르지 않는다** (확장판 6단계, 03-worker-orchestration.md 5.1절).
        # 캐시 미스가 곧 블로킹 HTTP였고, 봉 경계 직후에는 활성 조합 수만큼 그 호출이
        # 순차로 터져 tick 예산을 넘겼다. 채우는 일은 `scheduler`가 맡고(services/
        # candle_prefill.py) 워커는 건너뛴다 — 이 스킵이 늘어난다면 그건 "채우기가 밀리고
        # 있다"는 뜻이다 (06-observability.md 3장).
        _record_skip(
            SKIP_NO_CANDLES, slot.id, f" symbol={slot.coin_symbol} interval={interval}"
        )
        return

    if slot.strategy_type == "grid" and _ensure_grid_lines(slot) is None:
        return

    # 봉 선점을 주문보다 "먼저" 커밋한다 — 주문 도중 실패해도 같은 봉으로 다시 진입하지
    # 않게 하기 위함이다(그 봉은 건너뛰고 다음 신호에서 재시도, 07-auto-trading.md 2.1절).
    with session_scope() as db:
        if not slot_state.claim_candle(db, slot.id, candles[-1].opened_at):
            return

    intents = runner.evaluate(_build_spec(slot), candles, now=datetime.now(timezone.utc))

    for intent in intents:
        _execute_intent(slot, intent)


def _try_dca(slot: _SlotSnapshot) -> None:
    """DCA의 매 tick 경로 — 정기 매수 시각이 됐거나 추가매수 조건이면 한 건 산다."""
    current_price = _current_price(slot)
    if current_price is None:
        return  # 시세를 모르면 판정 자체가 불가능하다. 상태를 건드리지 않고 다음 tick에 재시도.

    now = datetime.now(timezone.utc)
    intents = runner.evaluate(_build_spec(slot), [], now=now, current_price=current_price)

    for intent in intents:
        _execute_dca_buy(slot, intent, now)


def _execute_dca_buy(slot: _SlotSnapshot, intent: TradeIntent, now: datetime) -> None:
    """DCA 매수 한 건을 집행하고 진행 상태를 갱신한다.

    매수가 잔고 부족으로 실패해도 정기 매수분은 다음 예정 시각으로 **민다**. 밀지 않으면
    `next_buy_at`이 과거인 채로 남아 매 tick(10초)마다 같은 실패와 알림이 반복된다 — 이번
    회차를 건너뛰고 다음 회차에서 재시도하는 편이 낫다.
    """
    filled = _place_buy(slot, intent.amount or Decimal(0))
    dca_state = dca.read_state(slot.state)

    if filled is None:
        if intent.reason == dca.SCHEDULED_BUY:
            _write_dca_state(slot, dca.skip_scheduled_buy(dca_state, now, slot.params))
        return

    fill_price, fill_quantity = filled
    # 지출은 수수료까지 포함한 실제 체결액으로 쌓는다 — 예산 상한(invest_amount)이 수수료를
    # 빼놓고 계산되면 상한을 조금씩 넘게 된다 (01-erd.md 3.2절 매수 체결액 계산식).
    spent = calc_buy_amount(fill_price, fill_quantity, TRADING_FEE_RATE)
    _write_dca_state(
        slot, dca.advance_after_buy(dca_state, intent, fill_price, spent, now, slot.params)
    )


def _write_dca_state(slot: _SlotSnapshot, dca_state: dict[str, Any]) -> None:
    with session_scope() as db:
        slot_state.write_dca_state(db, slot.id, dca_state)
    slot.state["dca"] = dca_state


def _execute_intent(slot: _SlotSnapshot, intent: TradeIntent) -> None:
    """주문 의도 하나를 실제 주문으로 옮기고, 그리드면 체결 결과로 라인을 갱신한다."""
    if intent.side == "buy":
        filled = _place_buy(slot, intent.amount or Decimal(0))
        if filled is not None and intent.grid_line_index is not None:
            # 기록하는 수량은 "살 예정이던 양"이 아니라 **실제 체결된 주문에서 되읽은 값**이다
            # (07 계획 Step 4) — 시장가는 create_order 안에서 체결까지 끝나고 갱신된 주문을
            # 돌려주므로 예상과 실제가 벌어질 여지가 없다. 라인(워커 소유)과 state.position
            # (체결 훅 소유)이 같은 체결을 근거로 갱신되어 서로 어긋나지 않는다.
            _write_grid_lines(slot, grid.mark_line_filled, intent.grid_line_index, filled[1])
        return

    sold = _place_sell(slot, intent.quantity or Decimal(0))
    if sold > 0 and intent.grid_line_index is not None:
        # **판 만큼만 깎는다.** 가용 수량이 모자라 덜 팔렸는데 라인을 통째로 비우면, 라인 합이
        # state.position보다 작아지고(불변식 위반) 그 라인이 다시 매수 대상이 되어 배정액을
        # 넘겨 산다 (grid.reduce_line_quantity docstring).
        _write_grid_lines(slot, grid.reduce_line_quantity, intent.grid_line_index, sold)


def _write_grid_lines(slot: _SlotSnapshot, mark, line_index: int, *args: Any) -> None:
    """엔진의 라인 갱신 함수로 새 라인 상태를 계산해 저장한다 (계산=엔진, 저장=워커)."""
    lines = slot_state.read_grid_lines(slot.state)
    if not lines:
        return

    lines = mark(lines, line_index, *args)
    with session_scope() as db:
        slot_state.write_grid_lines(db, slot.id, lines)
    slot.state.setdefault("grid", {})["lines"] = lines


def _place_buy(slot: _SlotSnapshot, amount: Decimal) -> tuple[Decimal, Decimal] | None:
    """`amount`(원화)만큼 시장가로 매수한다 (07-auto-trading.md 4.1절 — 워커는 항상 시장가).

    Returns:
        체결된 (체결가, 체결수량). 주문을 내지 못했으면 None.
    """
    if amount <= 0:
        return None

    current_price = _current_price(slot)
    if current_price is None:
        return None

    quantity = calc_buy_quantity(amount, current_price, TRADING_FEE_RATE)
    if quantity <= 0:
        return None

    try:
        with session_scope() as db:
            order = create_order(
                db,
                user_id=slot.user_id,
                coin_symbol=slot.coin_symbol,
                side="buy",
                order_type="market",
                quantity=quantity,
                source="auto",
                strategy_slot_id=slot.id,
            )
            return order.price, order.quantity
    except InsufficientBalanceError:
        # 활성화 시점엔 배정액이 확보돼 있었어도 그 사이 수동 출금 등으로 가용 원화가 줄어들 수
        # 있다. 이번 매수만 건너뛰고 슬롯은 ON으로 유지한다 (07-auto-trading.md 2.1절·6장).
        _record_skip(SKIP_INSUFFICIENT_BALANCE, slot.id)
        _notify(
            slot,
            "error",
            f"[{_korean_name(slot.coin_symbol)}] 매수 신호가 발생했으나 가용 잔고 부족으로 스킵되었습니다.",
        )
        return None


def _place_sell(slot: _SlotSnapshot, quantity: Decimal) -> Decimal:
    """슬롯이 보유한 몫 안에서 `quantity`만큼 시장가로 매도한다.

    Returns:
        **실제로 주문에 실린 수량.** 못 냈으면 0. 요청량보다 적을 수 있다 — 호출부는 이 값으로
        라인을 깎아야 한다(`grid.reduce_line_quantity`). "주문을 냈다/못 냈다"만 돌려주면
        덜 팔렸는데도 라인을 통째로 비우게 되고, 그 라인을 또 사서 배정액을 넘긴다.
    """
    with session_scope() as db:
        sellable = _sellable_quantity(db, slot, quantity)
    if sellable <= 0:
        return Decimal(0)

    try:
        with session_scope() as db:
            create_order(
                db,
                user_id=slot.user_id,
                coin_symbol=slot.coin_symbol,
                side="sell",
                order_type="market",
                quantity=sellable,
                source="auto",
                strategy_slot_id=slot.id,
            )
    except InsufficientHoldingError:
        # 가용 수량을 이미 상한으로 걸었으므로 정상 경로에서는 나오지 않는다. 그 사이 다른
        # 매도가 끼어든 경우이므로 이번 청산만 건너뛴다.
        _record_skip(SKIP_INSUFFICIENT_HOLDING, slot.id)
        return Decimal(0)
    return sellable


def _sellable_quantity(db, slot: _SlotSnapshot, requested: Decimal) -> Decimal:
    """실제로 팔 수량 = min(요청 수량, 슬롯 포지션, 가용 코인 수량) (07-auto-trading.md 4.2절).

    사용자가 같은 코인을 수동으로도 보유할 수 있으므로 슬롯이 매수한 몫을 넘겨 팔지 않는다.
    가용 수량(미체결 매도 주문분 제외, 01-erd.md 3.1절)으로 한 번 더 상한을 거는 이유는,
    슬롯 활성화 전에 낸 수동 지정가 매도가 남아 있으면 그만큼은 팔 수 없기 때문이다.
    """
    position = slot_state.read_position(slot.state)
    position_quantity = Decimal(position["quantity"]) if position else Decimal(0)
    available = get_available_quantity(db, slot.user_id, slot.coin_symbol)
    return min(requested, position_quantity, available).quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)


def _korean_name(coin_symbol: str) -> str:
    with session_scope() as db:
        coin = db.get(Coin, coin_symbol)
        return coin.korean_name if coin is not None else coin_symbol


def _notify(slot: _SlotSnapshot, type_: str, message: str) -> None:
    """워커가 직접 내는 알림(현재는 잔고 부족 오류뿐).

    체결 알림은 워커가 아니라 체결 후처리(services/matcher.py)가 낸다 — 주문을 냈다고 해서
    체결됐다는 보장이 없으므로, 체결 사실을 아는 쪽이 알리는 것이 맞다.
    """
    with session_scope() as db:
        settings = db.get(NotificationSetting, slot.user_id)
        if not notifications_service.is_type_enabled(settings, type_):
            return
        db.add(
            Notification(
                user_id=slot.user_id,
                type=type_,
                message=message,
                coin_symbol=slot.coin_symbol,
                strategy_slot_id=slot.id,
                is_read=False,
                created_at=datetime.now(timezone.utc),
            )
        )
