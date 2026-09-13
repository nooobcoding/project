"""샤드를 점유할 때 그리드·DCA 진행 상태를 체결 기록으로 재조정한다
(확장판 03-worker-orchestration.md 2.4절, 07-roadmap.md 7단계 필수 확인 항목).

**이게 없으면 배포할 때마다 그리드 배정액 초과와 DCA 중복 매수의 창이 열린다.**

무엇이 깨지는가 — `worker.py`의 매수 경로는 두 번 커밋한다:

    _place_buy(...)          → 체결 + state.position 커밋   ← 여기서 죽으면
    _write_grid_lines(...)   → 라인 점유 표시 별도 커밋      ← 이게 안 돈다

라인이 비어 있는 걸로 남으므로 **다음 봉에 같은 라인을 또 산다.** 포지션은 이미 있는데 라인은
비어 있으니 그리드에 배정한 금액을 넘겨 사게 된다. DCA는 더 급하다 — 확정봉 경로를 타지
않으므로(봉 선점이 묶어주지 않는다) 10초 뒤 다음 tick에 바로 중복 매수가 나간다.

**이 방식이 맞는 이유는 위험이 열리는 순간과 복구가 도는 순간이 정확히 같기 때문이다.**
크래시·배포·재균형은 전부 다른 프로세스의 샤드 점유를 일으키는 사건이고, 점유가 곧 복구
트리거다. 원본에서 "프로세스가 죽는 것"은 드문 사고였지만 분산에서는 일상적 사건이 된다.

**새 발상이 아니다.** 슬롯 ON 경로의 `_reconcile_phantom_position`
(services/strategy_slots.py)이 `state.position`을 실제 `holdings`에 맞춰 낮추는 것과 정확히
같은 모양이다. 그 함수가 `position`에 하는 일을 `grid.lines`·`dca`에 하는 것뿐이며, 스키마
변경도 주문 경로 수정도 없다.

**추측으로 자금을 움직이지 않는다.** 재조정으로도 불변식이 안 맞으면 슬롯을 OFF하고 경고를
남긴다 — 설명되지 않는 불일치 위에서 주문을 계속 내는 것보다 멈추는 편이 낫다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Coin, Notification, NotificationSetting, Order, StrategySlot
from app.services import notifications as notifications_service
from app.services import sharding, slot_state
from app.strategy_engine import dca, grid
from app.strategy_engine.costs import calc_buy_amount

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    """한 번의 재조정 결과. 관측 지표로 흘려보낸다 (06-observability.md 5장 —
    조용히 고치는 것도 조용한 실패다. 고쳤으면 고쳤다고 남겨야 한다)."""

    checked: int = 0
    grid_repaired: int = 0
    dca_repaired: int = 0
    disabled: int = 0
    errors: int = 0


def reconcile_shards(shard_ids: set[int]) -> ReconcileReport:
    """방금 점유한 샤드들의 활성 슬롯을 전부 재조정한다.

    슬롯 하나의 실패가 나머지를 막지 않도록 슬롯 단위로 예외를 삼키되, 삼킨 예외는 센다.
    """
    report = ReconcileReport()
    if not shard_ids:
        return report

    try:
        with session_scope() as db:
            slot_ids = list(
                db.scalars(
                    select(StrategySlot.id).where(
                        StrategySlot.is_active,
                        sharding.owned_by_user_shard(StrategySlot.user_id, shard_ids),
                    )
                )
            )
    except Exception:
        logger.exception("샤드 재조정: 대상 슬롯 조회 실패 (shards=%s)", sorted(shard_ids))
        report.errors += 1
        return report

    for slot_id in slot_ids:
        report.checked += 1
        try:
            reconcile_slot(slot_id, report)
        except Exception:
            logger.exception("샤드 재조정 실패 (slot=%s)", slot_id)
            report.errors += 1

    if report.grid_repaired or report.dca_repaired or report.disabled:
        logger.warning(
            "샤드 재조정: 슬롯 %d개 검사, 그리드 복구 %d건, DCA 복구 %d건, OFF %d건 (shards=%s)",
            report.checked,
            report.grid_repaired,
            report.dca_repaired,
            report.disabled,
            sorted(shard_ids),
        )
    return report


def reconcile_slot(slot_id: int, report: ReconcileReport) -> None:
    """슬롯 하나를 재조정한다. 전략 종류에 따라 검사 대상이 다르다."""
    with session_scope() as db:
        slot = db.get(StrategySlot, slot_id)
        if slot is None or not slot.is_active:
            return
        reconcile_in_session(db, slot, report)


def reconcile_in_session(db: Session, slot: StrategySlot, report: ReconcileReport) -> None:
    """호출자의 트랜잭션에 참여하는 재조정. 커밋하지 않는다.

    샤드 점유 경로 외에 **슬롯 ON 경로**(`services/strategy_slots.py` `toggle_slot`)도 이걸
    부른다. 재조정이 슬롯을 OFF한 뒤 사용자가 그대로 다시 켜면, 샤드를 다음에 점유할 때까지
    못 미더운 상태 위에서 거래가 재개되기 때문이다 — ON 시점이 그 구멍을 닫는 자리다.
    """
    if slot.strategy_type == "grid":
        _reconcile_grid_lines(db, slot, report)
    elif slot.strategy_type == "dca":
        _reconcile_dca_progress(db, slot, report)


# --- 그리드 --------------------------------------------------------------


def _reconcile_grid_lines(db: Session, slot: StrategySlot, report: ReconcileReport) -> None:
    """불변식 `Σ lines[].quantity == state.position.quantity`를 회복한다 (2.4절 표).

    | 상태 | 의미 | 처리 |
    |---|---|---|
    | 같다 | 정상 | 통과 |
    | position > Σ lines | 라인 기록이 유실됨 (크래시) | 체결 기록에서 되채운다 |
    | position < Σ lines | 라인에 있는데 포지션이 없음 | 초과분 라인을 비운다 (수동 매도) |
    | 복구 후에도 안 맞음 | 설명되지 않는 불일치 | 슬롯 OFF + 경고 |
    """
    lines = slot_state.read_grid_lines(slot.state)
    if lines is None:
        # 아직 초기화 전이다. 워커가 다음 tick에 `_ensure_grid_lines`로 만든다.
        return
    if not grid.lines_match_params(lines, slot.params):
        # 파라미터가 바뀌어 라인 자체가 폐기 대상이다. 재초기화도 워커가 한다 — 여기서
        # 고쳐 봐야 곧 덮어쓰인다.
        return

    position = slot_state.read_position(slot.state)
    position_quantity = Decimal(position["quantity"]) if position else Decimal(0)
    if _lines_quantity(lines) == position_quantity:
        return

    repaired = _shrink_lines(lines, position_quantity)
    repaired = _refill_lines(db, slot, repaired, position_quantity)

    if _lines_quantity(repaired) != position_quantity:
        # 추측으로 자금을 움직이지 않는다. 슬롯을 멈추고 사람이 보게 한다.
        logger.warning(
            "샤드 재조정: 슬롯 %s 그리드 불일치를 복구하지 못했다 "
            "(라인 합=%s, 포지션=%s) — 슬롯을 OFF한다",
            slot.id,
            _lines_quantity(repaired),
            position_quantity,
        )
        slot.is_active = False
        # **서버 로그로만 끄면 안 된다.** 사용자에게는 자동매매가 아무 설명 없이 멈춘 것으로
        # 보인다 — 워커가 슬롯을 끄는 다른 경로(DCA 목표 수익 달성)도 전부 알림을 낸다.
        _notify_disabled(db, slot)
        report.disabled += 1
        return

    slot_state.write_grid_lines(db, slot.id, repaired)
    report.grid_repaired += 1
    logger.warning(
        "샤드 재조정: 슬롯 %s 그리드 라인을 체결 기록으로 복구했다 (포지션=%s)",
        slot.id,
        position_quantity,
    )


def _notify_disabled(db: Session, slot: StrategySlot) -> None:
    """슬롯이 멈췄다는 사실을 사용자에게 알린다.

    `services/notifications.py`의 설정 조회를 쓰지 않고 `db.get`으로 직접 읽는다 — 그 함수는
    내부에서 커밋하고, 여기는 재조정 트랜잭션 한가운데다 (03-worker-orchestration.md 3.3절
    "체결 트랜잭션 안에서 호출하는 어떤 함수도 스스로 커밋해서는 안 된다"와 같은 이유).
    """
    settings_row = db.get(NotificationSetting, slot.user_id)
    if not notifications_service.is_type_enabled(settings_row, "error"):
        return
    coin = db.get(Coin, slot.coin_symbol)
    name = coin.korean_name if coin is not None else slot.coin_symbol
    db.add(
        Notification(
            user_id=slot.user_id,
            type="error",
            message=(
                f"[{name}] 자동매매 진행 상태가 체결 기록과 맞지 않아 자동매매를 중지했습니다. "
                "보유 현황을 확인한 뒤 다시 켜주세요."
            ),
            coin_symbol=slot.coin_symbol,
            strategy_slot_id=slot.id,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
    )


def _lines_quantity(lines: list[dict[str, Any]]) -> Decimal:
    return sum(
        (Decimal(line["quantity"]) for line in lines if line["filled"]), start=Decimal(0)
    )


def _shrink_lines(
    lines: list[dict[str, Any]], position_quantity: Decimal
) -> list[dict[str, Any]]:
    """라인 합이 포지션보다 많으면 초과분 라인을 비운다.

    **높은 가격의 라인부터 비운다.** 그리드는 위 라인부터 파는 구조라(매도 목표가 한 칸 위),
    수동 매도로 사라진 수량은 그 라인에 있었다고 보는 것이 가장 그럴듯하다. 자금 위험이 없는
    방향이기도 하다 — 라인을 비우면 그 라인은 다시 매수 대상이 될 뿐, 없는 수량을 팔려고
    하지는 않게 된다.
    """
    excess = _lines_quantity(lines) - position_quantity
    if excess <= 0:
        return lines

    for index in sorted(range(len(lines)), key=lambda i: Decimal(lines[i]["price"]), reverse=True):
        if excess <= 0:
            break
        if not lines[index]["filled"]:
            continue
        excess -= Decimal(lines[index]["quantity"])
        lines = grid.mark_line_empty(lines, index)
    return lines


def _refill_lines(
    db: Session,
    slot: StrategySlot,
    lines: list[dict[str, Any]],
    position_quantity: Decimal,
) -> list[dict[str, Any]]:
    """라인 합이 포지션보다 적으면 체결된 auto 매수 주문에서 되채운다.

    `filled_at` **역순**으로 읽는 이유: 기록이 유실되는 사고는 "가장 최근 매수 직후에 죽은
    것"이므로, 최근 주문부터가 곧 기록 안 된 주문부터다.

    주문 수량이 부족분보다 크면 부족분만 기록한다 — 불변식을 정확히 맞추는 쪽이 우선이다.
    라인에 실제보다 많이 적히면 없는 수량을 팔려다 매도 상한(`_sellable_quantity`)에 걸려
    주문이 안 나가고, 적게 적히면 그 라인을 또 사서 배정액을 넘긴다. 둘 중 후자가 막으려던
    사고다.
    """
    deficit = position_quantity - _lines_quantity(lines)
    if deficit <= 0:
        return lines

    # 되채울 수 있는 라인은 빈 라인 수만큼뿐이고, 주문 하나가 라인 하나를 채운다. 그래서
    # 그만큼만 읽으면 충분하다 — 주문 이력 전체를 읽으면 오래된 슬롯일수록 재조정이 느려지고,
    # 재조정은 tick 안에서 손절 판정보다 먼저 도는 구간이다.
    empty_line_count = sum(1 for line in lines if not line["filled"])
    orders = db.scalars(
        select(Order)
        .where(
            Order.strategy_slot_id == slot.id,
            Order.source == "auto",
            Order.side == "buy",
            Order.status == "filled",
        )
        .order_by(Order.filled_at.desc())
        .limit(empty_line_count)
    ).all()

    for order in orders:
        if deficit <= 0:
            break
        index = _closest_empty_line(lines, order.price)
        if index is None:
            break
        quantity = min(order.quantity, deficit)
        lines = grid.mark_line_filled(lines, index, quantity)
        deficit -= quantity

    return lines


def _closest_empty_line(lines: list[dict[str, Any]], fill_price: Decimal) -> int | None:
    """체결가에 가장 가까운 빈 라인 (2.4절). 라인 가격은 격자 레벨이고 체결가는 시장가라
    정확히 같을 수 없으므로 "가장 가까운"이 유일하게 쓸 수 있는 기준이다."""
    candidates = [index for index, line in enumerate(lines) if not line["filled"]]
    if not candidates:
        return None
    return min(candidates, key=lambda index: abs(Decimal(lines[index]["price"]) - fill_price))


# --- DCA -----------------------------------------------------------------


def _reconcile_dca_progress(db: Session, slot: StrategySlot, report: ReconcileReport) -> None:
    """`state.dca`를 체결 기록에 맞춘다 (2.4절 "DCA도 같은 창을 갖는다 — 그리고 더 급하다").

    규칙은 두 가지다.

    1. **`next_buy_at` 이후에 체결된 auto 매수가 있으면 그 매수는 이미 일어난 것이다.**
       예정 시각을 그 주문 기준으로 민다. 안 밀면 10초 뒤 다음 tick에 바로 또 산다.
    2. **그 매수가 남겼어야 할 나머지도 함께 옮긴다** — `last_buy_price`, `executed_count`,
       `spent_amount`. 하나라도 빠뜨리면 각각 다른 사고가 된다 (본문 주석 참고).

    **기준점은 `next_buy_at`이고, 전체 체결 이력을 다시 합산하지 않는다.** 전량 합산은
    슬롯이 grid에서 dca로 바뀐 경우(`services/strategy_slots.py` `update_slot`은 전략을
    바꿀 때 state를 지우지 않는다) 예전 그리드 주문까지 세어 **예산을 즉시 소진시키고, 그
    슬롯은 아무 오류 없이 영영 안 산다.** 크래시를 고치려다 크래시 없이도 터지는 사고를
    만드는 셈이다.

    **한계**: 추가 매수(`dca_extra`)는 `next_buy_at`을 밀지 않으므로 이 기준으로는 "기록 안
    된 매수"로 잡히지 않는다. 그 회차의 상태 기록이 유실되면 지출이 그만큼 덜 쌓인다 —
    상한이 조금 느슨해지는 방향이며, 확장판 이전과 같은 수준이다.
    """
    dca_state = dca.read_state(slot.state)
    next_buy_at = dca_state["next_buy_at"]
    if next_buy_at is None:
        # 아직 한 번도 안 샀거나 진행 상태가 없다. 기준점이 없으면 어떤 체결이 "기록 안 된
        # 것"인지 판단할 수 없으므로 아무것도 하지 않는다 — 판단 근거 없이 자금 상태를
        # 되짚지 않는다.
        return

    scheduled = _parse(next_buy_at)
    # **기준점이 `next_buy_at`이라는 것이 이 재조정의 핵심이다.** 정기 매수가 기록됐다면
    # 그 시점에 `next_buy_at`이 미래로 밀렸을 것이므로, `next_buy_at` 이후에 체결된 auto
    # 매수는 **정의상 아직 기록되지 않은 매수다.** 전체 체결 이력을 다시 합산하지 않는
    # 이유이기도 하다 — 전량 합산은 (a) 슬롯이 grid에서 dca로 바뀌면 예전 그리드 주문까지
    # 세어 예산을 순식간에 소진시키고, (b) 주문 이력 전체를 매번 읽는다.
    unrecorded = db.scalars(
        select(Order)
        .where(
            Order.strategy_slot_id == slot.id,
            Order.source == "auto",
            Order.side == "buy",
            Order.status == "filled",
            Order.filled_at >= scheduled,
        )
        .order_by(Order.filled_at.desc())
    ).all()
    if not unrecorded:
        return

    latest = unrecorded[0]
    updated = dict(dca_state)
    # 1. 예정 시각을 그 매수 기준으로 민다 — 안 밀면 10초 뒤 다음 tick에 바로 또 산다.
    updated["next_buy_at"] = dca.next_schedule(latest.filled_at, slot.params).isoformat()
    # 2. `last_buy_price`도 반드시 함께 옮긴다. 안 옮기면 기준점이 옛 매수가(더 높은 값)에
    #    남아, 추가매수 조건(`-X%`)이 이번 체결가 대비로 잘못 성립한다 — 크래시가 없었다면
    #    일어나지 않았을 매수를 재조정이 만들어내는 셈이 된다 (strategy_engine/dca.py
    #    `evaluate`의 extra_buy 분기).
    updated["last_buy_price"] = str(latest.price)
    # 3. 횟수·지출에 기록 안 된 매수를 더한다. 안 더하면 예산 상한(invest_amount)이 그만큼
    #    풀려 상한을 넘겨 산다.
    updated["executed_count"] = int(dca_state["executed_count"]) + len(unrecorded)
    updated["spent_amount"] = str(
        Decimal(dca_state["spent_amount"])
        + sum(
            (calc_buy_amount(order.price, order.quantity, TRADING_FEE_RATE) for order in unrecorded),
            start=Decimal(0),
        )
    )

    slot_state.write_dca_state(db, slot.id, updated)
    report.dca_repaired += 1
    logger.warning(
        "샤드 재조정: 슬롯 %s DCA 진행 상태를 복구했다 — 기록 안 된 매수 %d건 "
        "(next_buy_at=%s, 횟수=%s, 지출=%s)",
        slot.id,
        len(unrecorded),
        updated["next_buy_at"],
        updated["executed_count"],
        updated["spent_amount"],
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
