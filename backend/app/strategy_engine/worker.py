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
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import select

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Coin, Notification, NotificationSetting, StrategySlot
from app.services import candles as candles_service
from app.services import price_stream, slot_state
from app.services.orders import (
    InsufficientBalanceError,
    InsufficientHoldingError,
    create_order,
    get_available_quantity,
)
from app.strategy_engine import runner
from app.strategy_engine.signals import Signal

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 10  # 07-auto-trading.md 4장
_QUANTITY_STEP = Decimal("0.00000001")  # orders.quantity NUMERIC(28,8)


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


def calc_buy_quantity(invest_amount: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    """수수료까지 포함한 총 지출이 `invest_amount`를 넘지 않는 최대 매수 수량.

    매수 체결액이 `price × quantity × (1 + fee_rate)`이므로(01-erd.md 3.2절) 그 역산이다.
    소수점 8자리에서 내림한다 — 올림하면 배정액을 초과할 수 있다.
    """
    if price <= 0:
        return Decimal(0)
    raw = invest_amount / (price * (1 + fee_rate))
    return raw.quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)


def decide_exit(
    avg_price: Decimal,
    current_price: Decimal,
    stop_loss_pct: Decimal | None,
    take_profit_pct: Decimal | None,
) -> str | None:
    """손절·익절 도달 여부를 판정한다 (06-backtesting.md 2.5절 추세추종/역추세 규칙).

    `stop_loss_pct`/`take_profit_pct`는 양수 퍼센트로 저장된다 — 손절은 진입가 대비
    `-stop_loss_pct%` 이하로 내려갔을 때다.

    Returns:
        "take_profit" / "stop_loss" / None
    """
    if avg_price <= 0:
        return None

    profit_pct = (current_price - avg_price) / avg_price * 100
    if take_profit_pct is not None and profit_pct >= take_profit_pct:
        return "take_profit"
    if stop_loss_pct is not None and profit_pct <= -stop_loss_pct:
        return "stop_loss"
    return None


def run_tick() -> None:
    """활성 슬롯 전체를 1회 순회한다. APScheduler가 TICK_INTERVAL_SECONDS마다 호출한다.

    슬롯 하나의 실패가 나머지 슬롯을 막지 않도록 슬롯 단위로 예외를 삼키고 로그만 남긴다
    (main.py의 coins 동기화 잡과 같은 방침).
    """
    try:
        slot_ids = _load_active_slot_ids()
    except Exception:
        logger.exception("자동매매 워커: 활성 슬롯 조회 실패")
        return

    for slot_id in slot_ids:
        try:
            process_slot(slot_id)
        except Exception:
            logger.exception("자동매매 워커: 슬롯 %s 처리 실패", slot_id)


def process_slot(slot_id: int) -> None:
    """슬롯 하나의 청산·신호 평가를 처리한다 (tick 1회분)."""
    slot = _load_slot_snapshot(slot_id)
    if slot is None:
        return

    # 청산이 일어났으면 이번 tick에서는 재진입을 시도하지 않는다 — 방금 판 포지션을 같은
    # tick에 도로 사는 것을 막는다.
    if _try_exit(slot):
        return

    _try_signal(slot)


def _load_active_slot_ids() -> list[int]:
    with session_scope() as db:
        return list(db.scalars(select(StrategySlot.id).where(StrategySlot.is_active)))


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


def _current_price(coin_symbol: str) -> Decimal | None:
    tick = price_stream.get_cached_price(coin_symbol)
    if tick is None:
        return None
    return Decimal(str(tick["trade_price"]))


def _try_exit(slot: _SlotSnapshot) -> bool:
    """손절·익절 도달 시 슬롯 보유분을 청산한다. 청산 주문을 냈으면 True."""
    position = slot_state.read_position(slot.state)
    if position is None:
        return False

    current_price = _current_price(slot.coin_symbol)
    if current_price is None:
        return False

    reason = decide_exit(
        Decimal(position["avg_price"]), current_price, slot.stop_loss_pct, slot.take_profit_pct
    )
    if reason is None:
        return False

    return _place_sell(slot, position)


def _try_signal(slot: _SlotSnapshot) -> None:
    """새 확정봉이 있으면 그 봉으로 신호를 평가하고 주문한다."""
    interval = slot.params.get("interval", "1d")
    with session_scope() as db:
        candles = [
            _CandlePoint(opened_at=candle.opened_at, close=candle.close)
            for candle in candles_service.get_confirmed_candles(db, slot.coin_symbol, interval)
        ]
    if len(candles) < 2:
        return

    # 봉 선점을 주문보다 "먼저" 커밋한다 — 주문 도중 실패해도 같은 봉으로 다시 진입하지
    # 않게 하기 위함이다(그 봉은 건너뛰고 다음 신호에서 재시도, 07-auto-trading.md 2.1절).
    with session_scope() as db:
        if not slot_state.claim_candle(db, slot.id, candles[-1].opened_at):
            return

    spec = runner.SlotSpec(
        strategy_type=slot.strategy_type,
        indicator=slot.indicator,
        params=slot.params,
        state=slot.state,
    )
    signal: Signal | None = runner.evaluate(spec, candles, now=datetime.now(timezone.utc))

    if signal == "buy":
        _place_buy(slot)
    elif signal == "sell":
        position = slot_state.read_position(slot.state)
        if position is not None:
            _place_sell(slot, position)


def _place_buy(slot: _SlotSnapshot) -> None:
    """매수 신호를 주문으로 옮긴다. 워커 주문은 항상 시장가다 (07-auto-trading.md 4.1절)."""
    # 추세추종/역추세의 invest_amount는 "1회 진입 금액"이며 진입 후 청산까지 재사용하지
    # 않는다 (06-backtesting.md 2.4-1절) — 이미 포지션이 있으면 추가 매수하지 않는다.
    if slot_state.read_position(slot.state) is not None:
        return

    current_price = _current_price(slot.coin_symbol)
    if current_price is None:
        return

    quantity = calc_buy_quantity(slot.invest_amount, current_price, TRADING_FEE_RATE)
    if quantity <= 0:
        return

    try:
        with session_scope() as db:
            create_order(
                db,
                user_id=slot.user_id,
                coin_symbol=slot.coin_symbol,
                side="buy",
                order_type="market",
                quantity=quantity,
                source="auto",
                strategy_slot_id=slot.id,
            )
    except InsufficientBalanceError:
        # 활성화 시점엔 배정액이 확보돼 있었어도 그 사이 수동 출금 등으로 가용 원화가 줄어들 수
        # 있다. 이번 매수만 건너뛰고 슬롯은 ON으로 유지한다 (07-auto-trading.md 2.1절·6장).
        _notify(
            slot,
            "error",
            f"[{_korean_name(slot.coin_symbol)}] 매수 신호가 발생했으나 가용 잔고 부족으로 스킵되었습니다.",
        )


def _place_sell(slot: _SlotSnapshot, position: dict[str, Any]) -> bool:
    """슬롯이 보유한 몫만 시장가로 매도한다. 주문을 냈으면 True."""
    with session_scope() as db:
        quantity = _sellable_quantity(db, slot, position)
    if quantity <= 0:
        return False

    try:
        with session_scope() as db:
            create_order(
                db,
                user_id=slot.user_id,
                coin_symbol=slot.coin_symbol,
                side="sell",
                order_type="market",
                quantity=quantity,
                source="auto",
                strategy_slot_id=slot.id,
            )
    except InsufficientHoldingError:
        # 가용 수량을 이미 상한으로 걸었으므로 정상 경로에서는 나오지 않는다. 그 사이 다른
        # 매도가 끼어든 경우이므로 이번 청산만 건너뛴다.
        logger.warning("자동매매 워커: 슬롯 %s 청산 수량 부족으로 스킵", slot.id)
        return False
    return True


def _sellable_quantity(db, slot: _SlotSnapshot, position: dict[str, Any]) -> Decimal:
    """청산 가능 수량 = min(슬롯 포지션, 가용 코인 수량) (07-auto-trading.md 4.2절).

    사용자가 같은 코인을 수동으로도 보유할 수 있으므로 슬롯이 매수한 몫을 넘겨 팔지 않는다.
    가용 수량(미체결 매도 주문분 제외, 01-erd.md 3.1절)으로 한 번 더 상한을 거는 이유는,
    슬롯 활성화 전에 낸 수동 지정가 매도가 남아 있으면 그만큼은 팔 수 없기 때문이다.
    """
    slot_quantity = Decimal(position["quantity"])
    available = get_available_quantity(db, slot.user_id, slot.coin_symbol)
    return min(slot_quantity, available).quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)


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
        if settings is not None and type_ == "error" and not settings.error_enabled:
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
