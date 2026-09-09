"""`strategy_slots.state` JSONB의 소유권 경계 (07-auto-trading.md 4장, 09-execution-engine.md 3.2절).

같은 컬럼을 두 주체가 나눠 쓴다:

| 키 | 쓰는 주체 |
|---|---|
| `state.position` | 체결 후처리(`services/matcher.py` `_apply_auto_trading_hook`)만 |
| `state.last_evaluated_candle_at`, `state.grid.*`, `state.dca.*` | 워커(`app/strategy_engine/worker.py`)만 |

**왜 이 모듈이 따로 있나**: Python에서 `slot.state`를 통째로 읽어 dict를 고치고 다시 대입하는
방식(read-modify-write)은, 읽은 시점과 쓰는 시점 사이에 다른 주체가 자기 키를 갱신했을 때 그
변경을 통째로 덮어써 잃는다. 워커 tick과 체결 후처리는 서로 다른 트랜잭션에서 동시에 돌 수
있으므로 이 경합이 실제로 발생한다. 그래서 이 모듈의 모든 쓰기는 PostgreSQL의 `jsonb_set` /
`-`(키 삭제) 연산으로 **자기 키만** 갱신한다 — 슬롯 행에 배타 잠금을 걸지 않고도 서로의 키를
건드릴 수 없게 만드는 방식이며, 워커가 잠금을 쥔 채 주문을 내다가 체결 경로와 교착하는 것도
함께 피한다.

**커밋 책임의 비대칭**(중요): `claim_candle`은 스스로 커밋한다(워커의 독립된 짧은 트랜잭션).
`write_position`은 커밋하지 않는다 — `fill_order`가 체결·잔고·보유수량과 **같은 트랜잭션에서**
원자적으로 커밋해야 하기 때문이다.
"""

import json
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.strategy_engine.costs import calc_buy_amount

# state.position에 저장하는 수치의 자릿수 — holdings 컬럼(01-erd.md 3.3절)과 맞춘다.
_QUANTITY_STEP = Decimal("0.00000001")  # NUMERIC(28,8)
_PRICE_STEP = Decimal("0.00000001")  # NUMERIC(20,8)


def read_position(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """state.position을 꺼낸다. 수량이 0 이하면 포지션이 없는 것으로 본다."""
    if not state:
        return None
    position = state.get("position")
    if not position:
        return None
    if Decimal(position["quantity"]) <= 0:
        return None
    return position


def apply_buy(
    position: dict[str, Any] | None,
    fill_price: Decimal,
    quantity: Decimal,
    fee_rate: Decimal,
    filled_at: datetime,
) -> dict[str, Any]:
    """매수 체결을 포지션에 누적한다 (01-erd.md 3.2절 수수료 포함 취득원가 가중평균).

    `holdings.avg_buy_price`와 동일한 계산식을 써야 슬롯 포지션과 실제 보유분의 평단이
    어긋나지 않는다 — 그래서 `strategy_engine/costs.calc_buy_amount`(수수료 포함 매수액)를
    공유한다.
    """
    prev_quantity = Decimal(position["quantity"]) if position else Decimal(0)
    prev_avg_price = Decimal(position["avg_price"]) if position else Decimal(0)

    added_cost = calc_buy_amount(fill_price, quantity, fee_rate)
    new_quantity = prev_quantity + quantity
    new_avg_price = (prev_quantity * prev_avg_price + added_cost) / new_quantity

    return {
        "quantity": str(new_quantity.quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)),
        "avg_price": str(new_avg_price.quantize(_PRICE_STEP, rounding=ROUND_HALF_UP)),
        # 최초 진입 시각은 이후 추가 매수(그리드/DCA)로도 갱신하지 않는다 — 포지션을 언제
        # 열었는지가 의미이므로 (01-erd.md 3.6절).
        "entry_at": position["entry_at"] if position else filled_at.isoformat(),
    }


def apply_sell(position: dict[str, Any] | None, quantity: Decimal) -> dict[str, Any] | None:
    """매도 체결을 포지션에서 차감한다. 전량 청산되면 None(=키 삭제)을 반환한다.

    평단(`avg_price`)은 매도로 바뀌지 않는다 — 취득원가는 남은 수량에 그대로 따라간다.
    """
    if position is None:
        return None

    remaining = Decimal(position["quantity"]) - quantity
    if remaining <= 0:
        return None

    return {
        "quantity": str(remaining.quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)),
        "avg_price": position["avg_price"],
        "entry_at": position["entry_at"],
    }


def write_position(db: Session, slot_id: int, position: dict[str, Any] | None) -> None:
    """`state.position`만 갱신한다 (None이면 키 삭제).

    호출자(`fill_order`)의 트랜잭션에 참여하며 **커밋하지 않는다** — 체결과 포지션 갱신이
    한 트랜잭션에서 함께 확정되어야 한다 (09-execution-engine.md 3.2절).
    """
    if position is None:
        db.execute(
            text("UPDATE strategy_slots SET state = state - 'position' WHERE id = :slot_id"),
            {"slot_id": slot_id},
        )
        return

    db.execute(
        text(
            "UPDATE strategy_slots "
            "SET state = jsonb_set(state, '{position}', CAST(:position AS jsonb)) "
            "WHERE id = :slot_id"
        ),
        {"slot_id": slot_id, "position": _to_json(position)},
    )


def claim_candle(db: Session, slot_id: int, candle_opened_at: datetime) -> bool:
    """확정봉 하나를 이 슬롯의 "평가 완료"로 선점한다 (07-auto-trading.md 4장 중복 평가 방지).

    조건부 UPDATE 한 방으로 비교와 기록을 원자적으로 처리한다 — `services/matcher.py`의
    `WHERE status='pending'` 선점과 같은 패턴이다. 이미 같은(또는 더 최신) 봉이 기록돼
    있으면 rowcount가 0이 되어 False를 반환하고, 호출자는 이번 봉 평가를 건너뛴다.

    워커는 이 함수가 True를 반환한 "뒤에" 주문을 낸다 — 봉 선점을 주문보다 먼저 커밋해야
    주문 도중 실패해도 같은 봉으로 다시 진입하지 않는다. 스스로 커밋한다.
    """
    result = db.execute(
        text(
            "UPDATE strategy_slots "
            "SET state = jsonb_set(state, '{last_evaluated_candle_at}', CAST(:ts_json AS jsonb)) "
            "WHERE id = :slot_id "
            "  AND (state->>'last_evaluated_candle_at' IS NULL "
            "       OR CAST(state->>'last_evaluated_candle_at' AS timestamptz) < CAST(:ts AS timestamptz))"
        ),
        {
            "slot_id": slot_id,
            "ts": candle_opened_at.isoformat(),
            "ts_json": _to_json(candle_opened_at.isoformat()),
        },
    )
    db.commit()
    return result.rowcount > 0


def _to_json(value: Any) -> str:
    """jsonb 파라미터로 넘길 JSON 문자열. 수치는 이미 문자열로 담겨 있어 기본 인코더로 충분하다
    (01-erd.md 3.6절 — state의 모든 수치는 부동소수점 오차 방지를 위해 문자열로 저장)."""
    return json.dumps(value)
