"""공통 실행기 — 06-backtesting과 07-auto-trading의 공유 진입점 (06-backtesting.md 2.6절).

`evaluate(slot, candles, now)` 인터페이스로 통일한다: 06은 과거 캔들 배열을 통째로 넣고, 07 워커는
확정봉 1개씩 늘려가며 넣는 차이만 있을 뿐 이 함수의 계약은 동일하다 (07-auto-trading.md 4장).

`SlotSpec`은 SQLAlchemy 모델(`StrategySlot`)에 의존하지 않는 순수 dataclass다 — 06-backtesting은
DB에 슬롯을 저장하지 않고도 이 엔진을 호출해야 하고, 07은 `StrategySlot` → `SlotSpec` 변환을
호출부(워커)에서 책임진다. 엔진 자체는 어느 쪽 DB 모델도 몰라야 재사용이 성립한다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Literal, Protocol, Sequence

import pandas as pd

from app.strategy_engine import dca, grid, signals
from app.strategy_engine.intents import TradeIntent
from app.strategy_engine.signals import Signal

StrategyType = Literal["trend", "counter_trend", "grid", "dca"]
Indicator = Literal["ma", "rsi", "macd", "bollinger"]


@dataclass
class SlotSpec:
    """전략 슬롯 1건의 평가에 필요한 값 (01-erd.md `strategy_slots` 발췌, DB 비의존)."""

    strategy_type: StrategyType
    indicator: Indicator | None
    params: dict[str, Any]
    invest_amount: Decimal
    state: dict[str, Any] = field(default_factory=dict)


class CandleLike(Protocol):
    """엔진이 필요로 하는 캔들 최소 인터페이스. SQLAlchemy `Candle` 모델과 06-backtesting의
    순수 데이터 구조 양쪽 모두 `opened_at`/`close` 속성만 있으면 그대로 넘길 수 있다."""

    opened_at: datetime
    close: Decimal


# 06-backtesting.md 2.2절 표를 그대로 매핑한다. grid/dca는 지표가 없어 이 표에 들지 않고 evaluate()에서 별도 분기한다.
_SIGNAL_FUNCS: dict[tuple[StrategyType, Indicator], Callable[[pd.Series, dict[str, Any]], Signal | None]] = {
    ("trend", "ma"): signals.evaluate_trend_ma,
    ("trend", "rsi"): signals.evaluate_trend_rsi,
    ("trend", "macd"): signals.evaluate_trend_macd,
    ("trend", "bollinger"): signals.evaluate_trend_bollinger,
    ("counter_trend", "ma"): signals.evaluate_counter_trend_ma,
    ("counter_trend", "rsi"): signals.evaluate_counter_trend_rsi,
    ("counter_trend", "macd"): signals.evaluate_counter_trend_macd,
    ("counter_trend", "bollinger"): signals.evaluate_counter_trend_bollinger,
}


def _position_quantity(state: dict[str, Any]) -> Decimal:
    position = state.get("position") if state else None
    return Decimal(position["quantity"]) if position else Decimal(0)


def _evaluate_indicator(slot: SlotSpec, candles: Sequence[CandleLike]) -> list[TradeIntent]:
    """추세추종/역추세 — 지표 신호 1개를 주문 의도 0~1개로 옮긴다."""
    if slot.indicator is None:
        raise ValueError(f"strategy_type={slot.strategy_type!r}는 indicator가 필요하다")

    signal_func = _SIGNAL_FUNCS.get((slot.strategy_type, slot.indicator))
    if signal_func is None:
        raise ValueError(f"지원하지 않는 조합: strategy_type={slot.strategy_type!r}, indicator={slot.indicator!r}")

    if len(candles) < 2:
        return []

    closes = pd.Series([float(c.close) for c in candles], dtype="float64")
    signal: Signal | None = signal_func(closes, slot.params)
    held = _position_quantity(slot.state)

    if signal == "buy":
        # invest_amount는 "1회 진입 금액"이고 진입 후 청산까지 재사용하지 않는다
        # (06-backtesting.md 2.4-1절) — 이미 보유 중이면 추가 매수하지 않는다.
        if held > 0:
            return []
        return [TradeIntent(side="buy", amount=slot.invest_amount)]

    if signal == "sell":
        if held <= 0:
            return []
        return [TradeIntent(side="sell", quantity=held)]

    return []


def evaluate(
    slot: SlotSpec,
    candles: Sequence[CandleLike],
    now: datetime,
    current_price: Decimal | None = None,
) -> list[TradeIntent]:
    """이번에 낼 주문들을 판정한다.

    반환이 목록인 이유는 `intents.py` 참고 — 그리드는 가격이 여러 라인을 관통하면 한 번의
    평가에서 여러 주문이 나오고, 전략유형마다 1회 주문 규모의 의미가 달라 금액/수량까지 엔진이
    정해야 하기 때문이다.

    Args:
        slot: 평가 대상 슬롯 스펙
        candles: 오래된 순으로 정렬된 확정봉 시퀀스. 진행 중인(미확정) 봉은 호출자가 미리
            제외해야 한다 — 07 워커는 시세 스트림상 마지막 봉이 진행 중일 수 있으므로 잘라서
            넘긴다 (07-auto-trading.md 4장 "확정봉 기준" 규칙). DCA는 캔들로 트리거하지 않아
            빈 시퀀스를 받아도 된다.
        now: 평가 시각. DCA의 시간 스케줄 트리거(`state.dca.next_buy_at`) 판정에 쓰인다.
        current_price: 판정에 쓸 현재가. 생략하면 마지막 확정봉 종가를 쓴다. 07 워커는 실시간
            시세를 넣고(DCA 추가매수는 매 tick 판정한다), 06 백테스팅은 재생 중인 봉의 종가를
            넣게 된다.

    Returns:
        이번에 낼 주문 의도 목록 (없으면 빈 목록)
    """
    price = current_price if current_price is not None else (candles[-1].close if candles else None)

    if slot.strategy_type == "dca":
        if price is None:
            return []
        return dca.evaluate(now, price, dca.read_state(slot.state), slot.params, slot.invest_amount)

    if slot.strategy_type == "grid":
        if price is None:
            return []
        # 그리드는 확정봉 종가로 판정한다 (07-auto-trading.md 4장 — 신호 평가는 확정봉 기준).
        # 라인 상태는 워커가 채워 넣은 state.grid.lines를 그대로 읽는다.
        lines = (slot.state.get("grid") or {}).get("lines") or []
        if not lines:
            return []
        return grid.evaluate(price, lines, slot.params, slot.invest_amount)

    return _evaluate_indicator(slot, candles)
