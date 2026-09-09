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

from app.strategy_engine import signals
from app.strategy_engine.signals import Signal

StrategyType = Literal["trend", "counter_trend", "grid", "dca"]
Indicator = Literal["ma", "rsi", "macd", "bollinger"]


@dataclass
class SlotSpec:
    """전략 슬롯 1건의 평가에 필요한 값 (01-erd.md `strategy_slots` 발췌, DB 비의존)."""

    strategy_type: StrategyType
    indicator: Indicator | None
    params: dict[str, Any]
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


def evaluate(slot: SlotSpec, candles: Sequence[CandleLike], now: datetime) -> Signal | None:
    """확정봉 시퀀스로 슬롯의 매수/매도 신호를 판정한다.

    Args:
        slot: 평가 대상 슬롯 스펙
        candles: 오래된 순으로 정렬된 확정봉 시퀀스. 진행 중인(미확정) 봉은 호출자가 미리
            제외해야 한다 — 07 워커는 시세 스트림상 마지막 봉이 진행 중일 수 있으므로 잘라서
            넘긴다 (07-auto-trading.md 4장 "확정봉 기준" 규칙).
        now: 평가 시각. DCA의 시간 스케줄 트리거(`state.dca.next_buy_at`) 판정에 쓰인다.

    Returns:
        "buy" / "sell" / None (신호 없음)
    """
    if slot.strategy_type == "grid":
        raise NotImplementedError("그리드는 07 Step 4에서 구현한다 (07-auto-trading.md 참고)")
    if slot.strategy_type == "dca":
        raise NotImplementedError("DCA는 07 Step 5에서 구현한다 (07-auto-trading.md 참고)")

    if slot.indicator is None:
        raise ValueError(f"strategy_type={slot.strategy_type!r}는 indicator가 필요하다")

    signal_func = _SIGNAL_FUNCS.get((slot.strategy_type, slot.indicator))
    if signal_func is None:
        raise ValueError(f"지원하지 않는 조합: strategy_type={slot.strategy_type!r}, indicator={slot.indicator!r}")

    if len(candles) < 2:
        return None

    closes = pd.Series([float(c.close) for c in candles], dtype="float64")
    return signal_func(closes, slot.params)
