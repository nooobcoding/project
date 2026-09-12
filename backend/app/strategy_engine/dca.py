"""DCA(분할매수) 전략 (06-backtesting.md 2.4절·2.4-1절·2.5절).

**다른 전략과 결정적으로 다른 점**: DCA는 캔들이 아니라 **시간 스케줄**로 트리거된다
(07-auto-trading.md 4장 — "DCA는 캔들이 아닌 시간 스케줄: state.dca.next_buy_at ≤ now").
그래서 워커도 확정봉 선점(claim_candle) 경로가 아니라 매 tick 도는 경로에서 이 모듈을 부른다.
확정봉에 묶어두면 봉 하나당 한 번만 평가되어 "매주 화요일 15시" 같은 스케줄을 맞출 수 없다.

**매수는 두 갈래**
  - 정기 매수: `next_buy_at ≤ now` 이면 회당 매수금액만큼 산다. 체결 후 다음 예정 시각을 민다.
  - 추가 매수(옵션): 직전 매수가 대비 `-X%` 이상 떨어지면 1회 더 산다. "1회"는 별도 카운터로
    세지 않아도 자연히 지켜진다 — 매수할 때마다 기준점(`last_buy_price`)이 그 체결가로
    내려가므로 같은 자리에서 다시 발동하지 않는다.
  한 번의 평가에서 둘 다 내지는 않는다(정기 매수 우선) — 한 tick에 두 번 사면 예산이 예상보다
  빨리 소진된다.

**종료 조건** (06-backtesting.md 2.4절)
  - `count`: 매수 횟수가 `max_count`에 도달하면 더 사지 않는다.
  - `budget`: 누적 지출이 `invest_amount`에 도달하면 더 사지 않는다.
  어느 쪽을 고르든 **예산 상한은 항상 적용한다** — `invest_amount`는 "전체 분할매수 예산의 총
  상한"이므로(06-backtesting.md 2.4-1절) 종료조건과 무관하게 넘을 수 없다. 추가 매수도 횟수와
  지출에 똑같이 반영해, 옵션을 켰다고 해서 상한을 우회하지 못하게 한다.

  종료 조건에 걸려 매수가 끝나도 슬롯은 ON으로 남는다 — 목표 수익률 익절을 계속 지켜봐야 하기
  때문이다. 슬롯을 실제로 끄는 것은 익절이 체결됐을 때뿐이다(06-backtesting.md 2.5절
  "전량 매도 후 전략 종료").
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.strategy_engine.intents import TradeIntent

SCHEDULED_BUY = "dca_scheduled"
EXTRA_BUY = "dca_extra"

# "월"은 달마다 길이가 달라 스케줄이 흔들리므로 30일로 고정한다 (구현 고정값).
_PERIOD_DELTAS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


def period_delta(params: dict[str, Any]) -> timedelta:
    return _PERIOD_DELTAS[params["buy_period"]]


def next_schedule(now: datetime, params: dict[str, Any]) -> datetime:
    """다음 정기 매수 시각.

    직전 예정 시각이 아니라 `now`에서 한 주기를 더한다 — 워커가 한동안 멈춰 있었더라도
    밀린 횟수만큼 몰아서 사지 않게 하기 위함이다(그 대신 스케줄이 조금씩 뒤로 밀린다).
    """
    return now + period_delta(params)


def read_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """state.dca를 기본값과 함께 꺼낸다 (01-erd.md 3.6절 스키마)."""
    dca = (state or {}).get("dca") or {}
    return {
        "executed_count": int(dca.get("executed_count", 0)),
        "next_buy_at": dca.get("next_buy_at"),
        "last_buy_price": dca.get("last_buy_price"),
        "spent_amount": dca.get("spent_amount", "0"),
    }


def is_finished(dca_state: dict[str, Any], params: dict[str, Any], invest_amount: Decimal) -> bool:
    """더 이상 매수하지 않는 상태인지 (종료조건 도달 또는 예산 소진)."""
    amount = Decimal(str(params["amount_per_buy"]))
    spent = Decimal(dca_state["spent_amount"])

    if spent + amount > invest_amount:
        return True
    if params["end_condition"] == "count" and dca_state["executed_count"] >= int(params["max_count"]):
        return True
    return False


def advance_after_buy(
    dca_state: dict[str, Any],
    intent: TradeIntent,
    fill_price: Decimal,
    spent: Decimal,
    now: datetime,
    params: dict[str, Any],
) -> dict[str, Any]:
    """매수 체결을 진행 상태에 반영한 **새 dict**를 만든다 (원본은 건드리지 않는다).

    `spent`는 **수수료까지 포함한 실제 체결액**이어야 한다 — 예산 상한(`invest_amount`)이
    수수료를 빼놓고 쌓이면 상한을 조금씩 넘게 된다 (01-erd.md 3.2절).

    다음 예정 시각은 정기 매수(`SCHEDULED_BUY`)일 때만 민다. 추가 매수는 스케줄과 무관한
    보너스 회차라 예정 시각을 건드리면 정기 주기가 뒤로 밀려버린다.

    실매매(워커)와 백테스팅이 같은 함수를 써야 분할매수 진행이 양쪽에서 동일해진다 (06 계획 A-2).
    """
    updated = dict(dca_state)
    updated["executed_count"] = int(dca_state["executed_count"]) + 1
    updated["last_buy_price"] = str(fill_price)
    updated["spent_amount"] = str(Decimal(dca_state["spent_amount"]) + spent)
    if intent.reason == SCHEDULED_BUY:
        updated["next_buy_at"] = next_schedule(now, params).isoformat()
    return updated


def skip_scheduled_buy(
    dca_state: dict[str, Any], now: datetime, params: dict[str, Any]
) -> dict[str, Any]:
    """이번 정기 회차를 사지 못했을 때(잔고 부족 등) 다음 예정 시각만 민 새 dict.

    밀지 않으면 `next_buy_at`이 과거인 채로 남아 매 tick마다 같은 실패와 알림이 반복된다 —
    이번 회차를 건너뛰고 다음 회차에서 재시도하는 편이 낫다.
    """
    updated = dict(dca_state)
    updated["next_buy_at"] = next_schedule(now, params).isoformat()
    return updated


def evaluate(
    now: datetime,
    current_price: Decimal,
    dca_state: dict[str, Any],
    params: dict[str, Any],
    invest_amount: Decimal,
) -> list[TradeIntent]:
    """이번 tick에 낼 매수 의도를 판정한다 (최대 1건).

    `next_buy_at`이 아직 없으면 "지금이 첫 회차"로 보고 즉시 매수한다 — 슬롯을 켠 시점부터
    분할매수가 시작되는 것이 사용자가 기대하는 동작이다.
    """
    if is_finished(dca_state, params, invest_amount):
        return []

    amount = Decimal(str(params["amount_per_buy"]))

    next_buy_at = dca_state["next_buy_at"]
    if next_buy_at is None or datetime.fromisoformat(next_buy_at) <= now:
        return [TradeIntent(side="buy", amount=amount, reason=SCHEDULED_BUY)]

    if params.get("extra_buy_enabled") and dca_state["last_buy_price"]:
        last_price = Decimal(dca_state["last_buy_price"])
        if last_price > 0:
            drop_pct = (current_price - last_price) / last_price * 100
            if drop_pct <= -Decimal(str(params["extra_buy_drop_pct"])):
                return [TradeIntent(side="buy", amount=amount, reason=EXTRA_BUY)]

    return []
