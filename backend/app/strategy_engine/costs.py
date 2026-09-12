"""체결 비용 계산 공용 함수 (06-backtesting.md 2.6절 `costs.py`).

01-erd.md 3.2절 수수료 규칙과 동일한 함수를 실체결(수동·자동, `services/matcher.py`)과 백테스팅
(`06-backtesting`의 `runner.py`)이 함께 쓴다. 슬리피지는 백테스팅에서만 추가 적용한다 —
실체결은 실시세로 체결되므로 슬리피지를 더하면 이중 반영이 된다 (00-overview.md 원칙 7,
"의도된 비대칭"). 실체결 경로는 이 모듈의 함수에 `slippage_rate=0`을 넘기거나, 애초에 슬리피지
관련 함수(`calc_fill_price`)를 호출하지 않는 것으로 그 비대칭을 유지한다.

단위 규칙 (01-erd.md 3.2절): DB 컬럼 `backtest_results.fee_rate`/`slippage_rate`는 % 단위
(예: `0.05`, `0.1`)로 저장된다. 이 모듈의 모든 함수는 소수(비율) 단위 인자만 받는다 —
`percent_to_decimal`로 변환은 이 모듈에 들어오기 "전" 진입점 한 곳에서 끝내고, 이후 계산은
전부 소수로만 다룬다. 변환을 누락한 채 % 단위 값을 그대로 곱하면 100배 오차가 난다.
"""

from decimal import ROUND_DOWN, Decimal

# 주문 수량 자릿수 — orders.quantity NUMERIC(28,8) (01-erd.md 3.3절)
_QUANTITY_STEP = Decimal("0.00000001")


def percent_to_decimal(rate_percent: Decimal) -> Decimal:
    """% 단위 컬럼값(예: `0.05` = 0.05%)을 소수 비율(`0.0005`)로 변환한다 (01-erd.md 3.2절)."""
    return rate_percent / Decimal("100")


def calc_fill_price(theoretical_price: Decimal, side: str, slippage_rate: Decimal = Decimal("0")) -> Decimal:
    """체결가 = 이론가 × (1 ± 슬리피지율) (06-backtesting.md 3-A절).

    매수는 불리한 방향(더 비싸게), 매도는 불리한 방향(더 싸게)으로 슬리피지를 적용한다.
    실체결은 `slippage_rate=0`(기본값)을 그대로 써 이론가=체결가로 계산한다.
    """
    if side == "buy":
        return theoretical_price * (1 + slippage_rate)
    return theoretical_price * (1 - slippage_rate)


def calc_fee(price: Decimal, quantity: Decimal, fee_rate: Decimal) -> Decimal:
    """체결 수수료(원화) (01-erd.md 3.2절). 매수·매도 모두 체결금액에 같은 율을 곱한다."""
    return price * quantity * fee_rate


def calc_buy_amount(price: Decimal, quantity: Decimal, fee_rate: Decimal) -> Decimal:
    """매수 체결 시 원화 차감액 (01-erd.md 3.2절)."""
    return price * quantity * (1 + fee_rate)


def calc_buy_quantity(budget: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    """수수료까지 포함한 총 지출이 `budget`을 넘지 않는 최대 매수 수량.

    `calc_buy_amount`(= price × quantity × (1 + fee_rate))의 역산이다. 소수점 8자리에서
    내림한다 — 올림하면 예산을 초과한다.

    실매매 워커(배정액만큼 시장가 매수)와 백테스팅 시뮬레이터가 같은 함수를 써야 "백테스트에선
    살 수 있었는데 실매매에선 잔고가 모자란" 식의 괴리가 생기지 않는다 (06-backtesting.md 2.6절).
    """
    if price <= 0:
        return Decimal(0)
    raw = budget / (price * (1 + fee_rate))
    return raw.quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)


def calc_sell_amount(price: Decimal, quantity: Decimal, fee_rate: Decimal) -> Decimal:
    """매도 체결 시 원화 증가액 (01-erd.md 3.2절)."""
    return price * quantity * (1 - fee_rate)


def calc_realized_profit(
    sell_price: Decimal, quantity: Decimal, avg_buy_price: Decimal, fee_rate: Decimal
) -> Decimal:
    """매도 체결 시 실현손익을 계산한다 (01-erd.md 3.2절).

    매수 수수료가 이미 `avg_buy_price`(수수료 포함 취득원가)에 녹아 있으므로 이 한 줄로 왕복
    수수료가 모두 반영된다.

    Args:
        avg_buy_price: 체결 "직전"(holdings 갱신 이전) 평균매수가여야 한다 (01-erd.md 234행 규칙).
    """
    return calc_sell_amount(sell_price, quantity, fee_rate) - avg_buy_price * quantity
