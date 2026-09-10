"""그리드 전략 (06-backtesting.md 2.3절·2.4-1절·2.5절).

**격자 구조**: 하한가~상한가를 `grid_count`칸으로 균등 분할한다. 칸이 `grid_count`개면 가격
레벨은 `grid_count + 1`개이고, 그중 **아래쪽 `grid_count`개가 매수 라인**이다. 각 매수 라인의
매도 목표는 바로 한 칸 위 레벨이다.

    하한가 100, 상한가 200, 격자 수 4 → step 25
      매수 라인   : [100, 125, 150, 175]
      매도 목표   : [125, 150, 175, 200]
      라인당 배분 : invest_amount / 4

06-backtesting.md 2.3절은 파라미터로 "그리드 간격(%), 상한가, 하한가, 격자 수" 넷을 나열하지만,
상한·하한·격자 수가 정해지면 간격은 거기서 따라 나오는 종속값이라 넷 다 자유 입력일 수 없다.
그래서 상한/하한/격자 수만 입력으로 받고 간격은 파생 표시값으로 다룬다 (문서도 함께 정정).

**매매 규칙**
  - 매수: 아직 안 채워진 라인 중 `현재가 ≤ 라인가` 인 라인 — 가격이 그 라인까지 내려왔다는 뜻이다.
    가격이 여러 라인을 한 번에 관통하면 그만큼 여러 라인이 동시에 채워진다.
  - 매도: 이미 채워진 라인 중 `현재가 ≥ 그 라인의 매도 목표` 인 라인 — 한 칸 위에서 실현한다.
  - 하한가 아래에서는 매수하지 않는다. 범위를 벗어난 구간은 그리드가 다루기로 한 영역이 아니며,
    이 방어가 없으면 하한가 밑으로 떨어진 순간 전 라인이 한꺼번에 체결돼 배정액을 다 써버린다.

**손절·익절**: 그리드는 "하한가 이탈 손절"만 있고 익절은 없다(라인별로 개별 실현하므로).
이탈 청산은 워커의 매 tick 실시간 경로가 담당한다 — 이 모듈은 판정 함수만 제공한다.
"""

from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.strategy_engine.intents import TradeIntent

_PRICE_STEP = Decimal("0.00000001")  # 01-erd.md 3.3절 코인 가격 NUMERIC(20,8)


def _params(params: dict[str, Any]) -> tuple[Decimal, Decimal, int]:
    lower = Decimal(str(params["lower_price"]))
    upper = Decimal(str(params["upper_price"]))
    count = int(params["grid_count"])
    return lower, upper, count


def step_size(params: dict[str, Any]) -> Decimal:
    """격자 한 칸의 가격 폭."""
    lower, upper, count = _params(params)
    return (upper - lower) / count


def build_line_prices(params: dict[str, Any]) -> list[Decimal]:
    """매수 라인 가격 배열(오름차순). 상한가는 최상단 라인의 매도 목표이므로 포함하지 않는다."""
    lower, _, count = _params(params)
    step = step_size(params)
    return [(lower + step * index).quantize(_PRICE_STEP, rounding=ROUND_DOWN) for index in range(count)]


def sell_target_price(params: dict[str, Any], line_index: int) -> Decimal:
    """`line_index` 라인의 매도 목표가 — 한 칸 위 레벨."""
    lower, _, _ = _params(params)
    step = step_size(params)
    return (lower + step * (line_index + 1)).quantize(_PRICE_STEP, rounding=ROUND_DOWN)


def allocation_per_line(invest_amount: Decimal, params: dict[str, Any]) -> Decimal:
    """라인 하나에 배분할 원화 — invest_amount는 "전체 격자에 배분할 총 자금 상한"이다
    (06-backtesting.md 2.4-1절). 전 라인이 채워지면 합계가 정확히 invest_amount가 된다."""
    _, _, count = _params(params)
    return invest_amount / count


def initial_lines(params: dict[str, Any]) -> list[dict[str, Any]]:
    """빈 라인 상태(01-erd.md 3.6절 `state.grid.lines` 스키마). 수치는 문자열로 저장한다."""
    return [{"price": str(price), "filled": False, "quantity": "0"} for price in build_line_prices(params)]


def lines_match_params(lines: list[dict[str, Any]] | None, params: dict[str, Any]) -> bool:
    """저장된 라인이 지금 파라미터에서 나오는 라인과 같은지 — 슬롯을 OFF한 상태에서 상한/하한/
    격자 수를 바꾸면 기존 라인이 의미를 잃으므로, 워커가 이 검사로 재초기화 시점을 판단한다."""
    if not lines:
        return False
    expected = [str(price) for price in build_line_prices(params)]
    return [line["price"] for line in lines] == expected


def is_below_lower_bound(price: Decimal, params: dict[str, Any]) -> bool:
    """하한가 이탈 여부 (06-backtesting.md 2.5절 "그리드 이탈 손절")."""
    lower, _, _ = _params(params)
    return price < lower


def evaluate(
    price: Decimal,
    lines: list[dict[str, Any]],
    params: dict[str, Any],
    invest_amount: Decimal,
) -> list[TradeIntent]:
    """현재가로 전 라인을 훑어 채울 라인·비울 라인을 주문 의도로 만든다.

    매도를 먼저 담는다 — 같은 평가에서 매도와 매수가 함께 나올 때(가격이 중간대로 올라와
    아래 라인은 실현하고 위 라인은 아직 매수 구간인 경우) 먼저 팔아 원화를 확보한 뒤 사는 쪽이
    가용 잔고 부족으로 매수가 스킵될 확률이 낮다.
    """
    intents: list[TradeIntent] = []

    for index, line in enumerate(lines):
        if not line["filled"]:
            continue
        if price >= sell_target_price(params, index):
            intents.append(
                TradeIntent(side="sell", quantity=Decimal(line["quantity"]), grid_line_index=index)
            )

    # 하한가 아래는 그리드가 다루기로 한 구간이 아니다 — 여기서 매수를 허용하면 이탈 순간
    # 전 라인이 한꺼번에 체결된다 (모듈 docstring 참고).
    if not is_below_lower_bound(price, params):
        allocation = allocation_per_line(invest_amount, params)
        for index, line in enumerate(lines):
            if line["filled"]:
                continue
            if price <= Decimal(line["price"]):
                intents.append(TradeIntent(side="buy", amount=allocation, grid_line_index=index))

    return intents
