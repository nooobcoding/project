"""07-auto-trading Control 계층 — 전략 슬롯 CRUD·ON/OFF·신호 조회.

주문 발행·체결·워커 tick 로직은 이 파일의 책임이 아니다 (07 Step 2B `app/strategy_engine/worker.py`,
`services/matcher.py`). 이 서비스는 슬롯 설정 자체의 생성·수정·활성화 검증만 다룬다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Balance, Coin, Notification, Order, StrategySlot
from app.services import candles as candles_service
from app.services import slot_state
from app.services.orders import get_available_krw
from app.services.wallet import get_withdrawable_krw
from app.strategy_engine import runner
from app.strategy_engine.signals import Signal

_INDICATOR_STRATEGY_TYPES = ("trend", "counter_trend")
_NO_INDICATOR_STRATEGY_TYPES = ("grid", "dca")
_VALID_INDICATORS = ("ma", "rsi", "macd", "bollinger")


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼로 슬롯을 생성하려는 경우."""


class InvalidSlotInputError(Exception):
    """투자금이 0 이하거나, strategy_type과 indicator 조합이 맞지 않는 경우 (07 2·6장)."""


class SlotNotFoundError(Exception):
    """존재하지 않거나 본인 소유가 아닌 슬롯을 조회/수정/삭제하려는 경우."""


class SlotActiveError(Exception):
    """활성(ON) 상태인 슬롯의 설정을 수정하려는 경우 — 먼저 OFF해야 한다."""


class SlotHasPositionError(Exception):
    """포지션을 보유한 그리드 슬롯의 설정을 수정하려는 경우 (services 내 update_slot 참고)."""


class InsufficientBalanceError(Exception):
    """슬롯 생성 시 투자금이 가용 원화를 초과하는 경우 (07 6장 "최대 투자금 > 가용 잔고")."""


class InsufficientAllocatableBalanceError(Exception):
    """슬롯 활성화(ON) 시 투자금이 출금 가능액을 초과하는 경우 (07 2.1절)."""


class DuplicateActiveSlotError(Exception):
    """같은 코인에 이미 활성(ON) 슬롯이 있는 경우 (07 2절 "코인당 활성 슬롯 1개")."""


@dataclass
class SlotDeletionResult:
    """슬롯 삭제 응답용 — 삭제 직전 잔여 포지션을 프론트가 확인 모달에 표시한다 (07 4.2절)."""

    coin_symbol: str
    korean_name: str
    remaining_quantity: Decimal


def _validate_strategy_type_indicator(strategy_type: str, indicator: str | None) -> None:
    """strategy_type-indicator 조합의 구조적 유효성만 검사한다.

    indicator 값 자체가 유효 목록에 있는지, 파라미터 범위(RSI 0~100 등)가 맞는지는
    schemas/strategy_slots.py의 Pydantic 모델이 담당한다 (경계 계층의 입력 검증과 제어
    계층의 도메인 규칙 검증을 분리).
    """
    if strategy_type in _INDICATOR_STRATEGY_TYPES:
        if indicator not in _VALID_INDICATORS:
            raise InvalidSlotInputError()
    elif strategy_type in _NO_INDICATOR_STRATEGY_TYPES:
        # 그리드/DCA는 지표를 쓰지 않는다 (06-backtesting.md 2.3·2.4절).
        if indicator is not None:
            raise InvalidSlotInputError()
    else:
        raise InvalidSlotInputError()


def create_slot(
    db: Session,
    user_id: int,
    coin_symbol: str,
    strategy_type: str,
    indicator: str | None,
    params: dict[str, Any],
    invest_amount: Decimal,
    stop_loss_pct: Decimal | None,
    take_profit_pct: Decimal | None,
) -> StrategySlot:
    """슬롯을 생성한다. 항상 is_active=False로 시작한다 — 활성화는 별도 toggle_slot 호출로 한다."""
    coin = db.get(Coin, coin_symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()

    _validate_strategy_type_indicator(strategy_type, indicator)
    if invest_amount <= 0:
        raise InvalidSlotInputError()

    # 생성 시점 기본 검증은 "가용 잔고"(다른 활성 슬롯 배정액은 아직 고려하지 않음) 기준이다
    # (07-auto-trading.md 6장 표 "최대 투자금 > 가용 잔고"). 다른 슬롯과의 합산 검증은
    # 활성화(ON) 시점에 toggle_slot이 출금 가능액 기준으로 다시 한다 (07 2.1절).
    if invest_amount > get_available_krw(db, user_id):
        raise InsufficientBalanceError()

    slot = StrategySlot(
        user_id=user_id,
        coin_symbol=coin_symbol,
        strategy_type=strategy_type,
        indicator=indicator,
        params=params,
        invest_amount=invest_amount,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        state={},
        is_active=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def _has_duplicate_active_slot(db: Session, user_id: int, coin_symbol: str, exclude_slot_id: int) -> bool:
    return (
        db.scalar(
            select(StrategySlot).where(
                StrategySlot.user_id == user_id,
                StrategySlot.coin_symbol == coin_symbol,
                StrategySlot.is_active,
                StrategySlot.id != exclude_slot_id,
            )
        )
        is not None
    )


def _get_owned_slot(db: Session, user_id: int, slot_id: int) -> StrategySlot:
    slot = db.get(StrategySlot, slot_id)
    if slot is None or slot.user_id != user_id:
        raise SlotNotFoundError()
    return slot


def update_slot(
    db: Session,
    user_id: int,
    slot_id: int,
    strategy_type: str,
    indicator: str | None,
    params: dict[str, Any],
    invest_amount: Decimal,
    stop_loss_pct: Decimal | None,
    take_profit_pct: Decimal | None,
) -> StrategySlot:
    """슬롯 설정을 수정한다.

    활성(ON) 상태에서는 수정을 막는다 — 워커가 이미 이 설정으로 state(예:
    last_evaluated_candle_at, grid.lines)를 쌓아가고 있는 도중에 strategy_type/indicator/
    params가 바뀌면 그 상태의 의미가 깨진다. 설정을 바꾸려면 먼저 OFF해야 한다.
    """
    slot = _get_owned_slot(db, user_id, slot_id)
    if slot.is_active:
        raise SlotActiveError()

    # 그리드 라인 가격은 상한/하한/격자 수에서 파생되므로, 포지션을 든 채 그 값을 바꾸면
    # 라인이 전부 "빈 라인"으로 재초기화되면서 이미 산 몫을 또 사게 된다(배정액 초과).
    # 지표형 전략은 라인 같은 파생 상태가 없어 이 제약이 필요 없다.
    if (slot.strategy_type == "grid" or strategy_type == "grid") and slot_state.read_position(
        slot.state
    ) is not None:
        raise SlotHasPositionError()

    _validate_strategy_type_indicator(strategy_type, indicator)
    if invest_amount <= 0:
        raise InvalidSlotInputError()
    if invest_amount > get_available_krw(db, user_id):
        raise InsufficientBalanceError()

    slot.strategy_type = strategy_type
    slot.indicator = indicator
    slot.params = params
    slot.invest_amount = invest_amount
    slot.stop_loss_pct = stop_loss_pct
    slot.take_profit_pct = take_profit_pct
    db.commit()
    db.refresh(slot)
    return slot


def toggle_slot(db: Session, user_id: int, slot_id: int, is_active: bool) -> StrategySlot:
    """슬롯을 ON/OFF한다.

    ON 시에만 검증한다 (07 2절·2.1절):
      1) 같은 코인에 이미 활성 슬롯이 있으면 차단 (부분 유니크 인덱스가 최종 방어선이지만,
         사용자에게 보여줄 한국어 메시지를 위해 여기서 먼저 조회해 막는다).
      2) 이번 슬롯 투자금이 출금 가능액(다른 활성 슬롯의 남은 배정액까지 제외한 값)을
         초과하면 차단.
    OFF 시에는 is_active만 내린다 — state.position은 그대로 유지한다 (07 4.2절, 재ON 시
    이어서 관리).
    """
    slot = _get_owned_slot(db, user_id, slot_id)

    if not is_active:
        slot.is_active = False
        db.commit()
        db.refresh(slot)
        return slot

    if slot.is_active:
        return slot  # 이미 ON — 멱등하게 처리

    # 잠금을 "중복 슬롯 검사보다 먼저" 건다 — 같은 유저가 같은 코인의 서로 다른 슬롯 두 개를
    # 동시에 ON 요청하면, 잠금 없이 각자 중복 검사만 하는 순서로는 둘 다 "아직 활성 슬롯 없음"을
    # 보고 통과해버릴 수 있다(TOCTOU). 그러면 뒤늦게 부분 유니크 인덱스(ux_strategy_slots_active_
    # coin)가 커밋 시점에 막긴 하지만, 그건 이 함수가 잡지 못하는 raw IntegrityError로 터진다 —
    # 사용자에게 "이미 활성화된 전략이 있습니다"가 아니라 500이 뜬다. balances 행을 먼저 잠그면
    # 두 번째 요청은 첫 번째가 커밋할 때까지 여기서 블록되고, 그 뒤에 하는 중복 검사는 첫 번째의
    # 결과를 정확히 보게 된다 — 이 잠금은 출금 가능액 재검증(아래)에도 어차피 필요했던 것이라
    # 새 잠금 자원을 추가하는 게 아니라 기존 잠금의 순서만 바꾼 것이다 (01-erd.md 3.1절 동시성
    # 주의, services/orders.py create_order의 FOR UPDATE 패턴과 동일 자원).
    db.execute(select(Balance).where(Balance.user_id == user_id).with_for_update())

    if _has_duplicate_active_slot(db, user_id, slot.coin_symbol, exclude_slot_id=slot.id):
        raise DuplicateActiveSlotError()
    if slot.invest_amount > get_withdrawable_krw(db, user_id):
        raise InsufficientAllocatableBalanceError()

    slot.is_active = True
    db.commit()
    db.refresh(slot)
    return slot


def delete_slot(db: Session, user_id: int, slot_id: int) -> SlotDeletionResult:
    """슬롯을 삭제한다. 활성 상태여도 삭제를 막지 않는다 (07 8장 "활성 상태면 우선 OFF 처리").

    삭제 전 잔여 포지션 수량을 응답에 담아 반환한다 — 프론트가 "이 전략이 보유한 [코인] N개는
    수동 보유분으로 남습니다" 확인 모달에 쓴다 (07 4.2절). 포지션을 인계할 주체가 사라질 뿐,
    실제 holdings/balances는 건드리지 않는다 — 삭제 이후 그 코인은 그냥 수동 보유분이 된다.
    """
    slot = _get_owned_slot(db, user_id, slot_id)
    coin = db.get(Coin, slot.coin_symbol)

    position = slot.state.get("position") if slot.state else None
    remaining_quantity = Decimal(position["quantity"]) if position else Decimal(0)

    # 참조를 먼저 끊고 슬롯을 지운다. FK가 ON DELETE SET NULL이라 이 두 UPDATE를 생략해도 결과는
    # 같지만, 그 경우 잠금 순서가 strategy_slots → (FK 처리로) orders가 되어 체결
    # (`matcher.fill_order`: orders 행 선점 → … → strategy_slots)과 정반대가 된다. 그 슬롯의
    # 주문이 체결되는 바로 그 순간 삭제가 들어오면 실제로 교착이 발생한다(PostgreSQL이 감지해
    # 한쪽을 abort시킨다). 여기서 orders를 먼저 잠그면 양쪽 다 orders → strategy_slots 순서가
    # 되어 교착 자체가 성립하지 않는다.
    db.execute(
        update(Order).where(Order.strategy_slot_id == slot.id).values(strategy_slot_id=None)
    )
    db.execute(
        update(Notification)
        .where(Notification.strategy_slot_id == slot.id)
        .values(strategy_slot_id=None)
    )

    db.delete(slot)
    db.commit()

    return SlotDeletionResult(
        coin_symbol=slot.coin_symbol,
        korean_name=coin.korean_name if coin is not None else slot.coin_symbol,
        remaining_quantity=remaining_quantity,
    )


def list_slots(db: Session, user_id: int) -> list[StrategySlot]:
    return list(
        db.scalars(
            select(StrategySlot).where(StrategySlot.user_id == user_id).order_by(StrategySlot.created_at.desc())
        )
    )


def get_slot_signal_status(db: Session, user_id: int, slot_id: int) -> Signal | None:
    """슬롯의 현재 확정봉 기준 신호를 계산해 반환한다 (07 3-B "신호 모니터링" 카드 데이터).

    워커(07 Step 2B)와 달리 state를 갱신하지 않는 순수 조회다 — 화면에 보여주기 위해
    매번 새로 계산할 뿐, last_evaluated_candle_at 등 워커 소유 상태에는 관여하지 않는다.

    엔진은 주문 의도 목록을 돌려주지만 이 카드는 "지금 매수/매도 쪽인가"만 보여주면 되므로
    목록을 한 방향으로 접어서 반환한다 (그리드는 한 번에 여러 라인이 나올 수 있다).
    """
    slot = _get_owned_slot(db, user_id, slot_id)

    interval = slot.params.get("interval", "1d")
    confirmed_candles = candles_service.get_confirmed_candles(db, slot.coin_symbol, interval)

    spec = runner.SlotSpec(
        strategy_type=slot.strategy_type,
        indicator=slot.indicator,
        params=slot.params,
        invest_amount=slot.invest_amount,
        state=slot.state,
    )
    intents = runner.evaluate(spec, confirmed_candles, now=datetime.now(timezone.utc))

    if any(intent.side == "buy" for intent in intents):
        return "buy"
    if any(intent.side == "sell" for intent in intents):
        return "sell"
    return None
