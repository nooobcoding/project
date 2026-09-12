"""청산(손절·익절) 판정 — 06-backtesting.md 2.5절 전략유형별 규칙을 한 곳에 모은 순수 함수.

**왜 워커에서 여기로 옮겼나**: 이 판정이 워커의 private 함수로 남아 있으면 백테스팅이 같은
규칙을 복제하게 되고, 이후 한쪽만 고치면 "백테스트에선 익절됐는데 실매매에선 안 됨" 같은
괴리가 조용히 생긴다 (06 계획 A-1). 신호 평가(`runner.evaluate`)가 이미 공유되고 있으므로
청산도 같은 자리에 있어야 엔진 공유가 성립한다.

**책임 경계**: 이 모듈은 "무엇을 할지"(청산할지, 얼마나, 왜)만 정하고 `TradeIntent`로 돌려준다.
"어떻게 기록할지"(주문 발행·슬롯 OFF·그리드 라인 리셋)는 호출부의 몫이다 — 실매매(워커)는 DB에
쓰고, 백테스팅은 메모리 상태를 고친다.

**전략유형별 규칙** (06-backtesting.md 2.5절)

| 전략 유형 | 손절 | 익절 |
|---|---|---|
| 추세추종/역추세 | 진입가 대비 -X% | 진입가 대비 +X% |
| 그리드 | 하한가 이탈 시 전량 | 없음 (라인별로 개별 실현하므로) |
| DCA | 없음 | 평균매수가 대비 +X% 도달 시 전량 매도 후 전략 종료 |

`reason`은 호출부가 후처리를 가르는 데 쓴다 — 그리드 이탈은 라인 리셋, DCA 익절은 전략 종료가
뒤따르지만 추세추종/역추세 청산은 포지션이 비는 것 외에 남는 일이 없다.
"""

from decimal import Decimal
from typing import Any

from app.strategy_engine import grid
from app.strategy_engine.intents import TradeIntent
from app.strategy_engine.runner import SlotSpec

STOP_LOSS = "stop_loss"
TAKE_PROFIT = "take_profit"
GRID_BREAKOUT = "grid_breakout"
DCA_TAKE_PROFIT = "dca_take_profit"


def calc_profit_pct(avg_price: Decimal, current_price: Decimal) -> Decimal | None:
    """평단 대비 손익률(%). 평단이 0 이하인 비정상 포지션이면 None(판정 불가)."""
    if avg_price <= 0:
        return None
    return (current_price - avg_price) / avg_price * 100


def decide_exit(
    spec: SlotSpec, position: dict[str, Any] | None, current_price: Decimal
) -> TradeIntent | None:
    """지금 청산해야 하는지 판정한다.

    Args:
        spec: 전략 스펙. `stop_loss_pct`/`take_profit_pct`는 **양수 퍼센트**로 담긴다 —
            손절은 `-stop_loss_pct%` 이하로 내려갔을 때 발동한다.
        position: `state.position` 스키마의 dict (01-erd.md 3.6절). 없거나 수량이 0이면 청산할
            것이 없다.
        current_price: 판정 시각의 가격. 워커는 실시간 시세를, 백테스팅은 재생 중인 봉의 종가를 넣는다.

    Returns:
        전량 매도 의도(`reason`에 사유). 청산 조건이 아니면 None.
    """
    if not position:
        return None
    quantity = Decimal(position["quantity"])
    if quantity <= 0:
        return None

    def sell(reason: str) -> TradeIntent:
        return TradeIntent(side="sell", quantity=quantity, reason=reason)

    # 그리드는 평단이 아니라 하한가 이탈로 판정하므로 손익률 계산 전에 갈라진다.
    if spec.strategy_type == "grid":
        return sell(GRID_BREAKOUT) if grid.is_below_lower_bound(current_price, spec.params) else None

    profit_pct = calc_profit_pct(Decimal(position["avg_price"]), current_price)
    if profit_pct is None:
        return None

    if spec.strategy_type == "dca":
        # DCA에는 손절이 없다 — 하락 구간에 계속 사 모으는 것이 전략의 전제이기 때문이다.
        if spec.take_profit_pct is not None and profit_pct >= spec.take_profit_pct:
            return sell(DCA_TAKE_PROFIT)
        return None

    # 설정이 이상해 둘 다 걸리는 경우(익절 기준 ≤ 0 등)에도 판정이 흔들리지 않게 익절을 먼저 본다.
    if spec.take_profit_pct is not None and profit_pct >= spec.take_profit_pct:
        return sell(TAKE_PROFIT)
    if spec.stop_loss_pct is not None and profit_pct <= -spec.stop_loss_pct:
        return sell(STOP_LOSS)
    return None
