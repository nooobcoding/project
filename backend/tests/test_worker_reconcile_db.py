"""샤드 점유 시점의 그리드·DCA 재조정 (확장판 7단계, 03-worker-orchestration.md 2.4절).

**이 파일이 막는 사고는 돈이 새는 사고다.** 워커의 매수 경로는 두 번 커밋한다 —
체결 커밋과 진행 상태 기록 커밋 사이에 프로세스가 죽으면:

- 그리드: 라인이 비어 있는 걸로 남아 **다음 봉에 같은 라인을 또 산다** (배정액 초과)
- DCA: `next_buy_at`이 안 밀려 **10초 뒤 다음 tick에 또 산다** (그리드보다 급하다)

원본에서는 드문 사고였지만, 분산에서는 배포·크래시·재균형이 전부 이 창을 연다. 그래서
샤드를 점유하는 시점 — 그 창이 열리는 사건과 정확히 같은 순간 — 에 복구한다.

여기서는 **크래시를 재현하는 대신 크래시가 남기는 상태를 직접 만든다.** 체결은 실제로 내고
상태 기록만 건너뛰면, 그게 곧 `_write_grid_lines` 직전에 죽은 프로세스가 남긴 DB다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import session_scope
from app.models import Order, StrategySlot
from app.services import slot_state
from app.strategy_engine import grid, reconcile
from tests.conftest import load_slot_state, requires_db

GRID_PARAMS = {
    "interval": "1d",
    "lower_price": "100",
    "upper_price": "200",
    "grid_count": 4,
}  # 매수 라인 [100, 125, 150, 175]

DCA_PARAMS = {
    "interval": "1d",
    "buy_period": "day",
    "amount_per_buy": "10000",
    "end_condition": "budget",
}


def _lines(*quantities: str) -> list[dict]:
    """라인별 수량으로 라인 상태를 만든다 ("0"이면 빈 라인).

    가격은 **엔진이 만든 값을 그대로 쓴다** — 라인 가격은 8자리로 quantize되어 있어서
    직접 `"100"`이라고 쓰면 `lines_match_params`가 불일치로 보고 재조정이 통째로 건너뛰어진다.
    """
    lines = grid.initial_lines(GRID_PARAMS)
    return [
        {**line, "filled": Decimal(quantity) > 0, "quantity": quantity}
        for line, quantity in zip(lines, quantities)
    ]


def _line_price(index: int) -> str:
    return grid.initial_lines(GRID_PARAMS)[index]["price"]


EMPTY_LINES = _lines("0", "0", "0", "0")


def _set_state(slot_id: int, state: dict) -> None:
    with session_scope() as db:
        db.get(StrategySlot, slot_id).state = state


def _add_filled_auto_buy(
    slot_id: int, user_id: int, symbol: str, price: str, quantity: str, filled_at: datetime
) -> None:
    with session_scope() as db:
        db.add(
            Order(
                user_id=user_id,
                coin_symbol=symbol,
                side="buy",
                order_type="market",
                price=Decimal(price),
                quantity=Decimal(quantity),
                status="filled",
                source="auto",
                fee=Decimal("0"),
                strategy_slot_id=slot_id,
                created_at=filled_at,
                filled_at=filled_at,
            )
        )


def _shard_of(user_id: int) -> int:
    from app.services import sharding

    return sharding.shard_of_user(user_id)


# --- 그리드 --------------------------------------------------------------


@requires_db
def test_grid_lines_rebuilt_from_fills(make_slot, test_user, test_coin):
    """체결은 됐는데 라인 기록이 유실된 상태를 체결 이력으로 복구한다.

    **복구가 없으면 그리드는 그 라인을 또 산다** — 포지션은 이미 있는데 라인이 비어 있으니
    배정액을 넘겨 사게 된다 (2.4절 "무엇이 깨지는가").
    """
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    # 150 라인에서 매수가 체결됐지만 라인 기록 직전에 죽은 상태
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "150", "0.5", datetime.now(timezone.utc)
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    lines = slot_state.read_grid_lines(load_slot_state(slot_id))
    filled = [line for line in lines if line["filled"]]
    assert len(filled) == 1
    assert filled[0]["price"] == _line_price(2)  # 150 — 체결가에 가장 가까운 빈 라인
    assert Decimal(filled[0]["quantity"]) == Decimal("0.5")


@requires_db
def test_grid_reconcile_leaves_consistent_slot_alone(make_slot, test_user, test_coin):
    """불변식이 이미 맞으면 아무것도 건드리지 않는다."""
    lines = _lines("0", "0", "0.5", "0")
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": lines},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    report = reconcile.reconcile_shards({_shard_of(test_user)})

    assert report.grid_repaired == 0
    assert slot_state.read_grid_lines(load_slot_state(slot_id)) == lines


@requires_db
def test_grid_excess_lines_are_cleared(make_slot, test_user, test_coin):
    """포지션보다 라인이 많으면(수동 매도로 사라진 경우) 초과분을 비운다.

    높은 가격의 라인부터 비운다 — 그리드는 위 라인부터 파는 구조라 사라진 수량이 거기
    있었다고 보는 것이 가장 그럴듯하다.
    """
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": _lines("0", "0.5", "0", "0.5")},
            "position": {"quantity": "0.5", "avg_price": "125", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    lines = slot_state.read_grid_lines(load_slot_state(slot_id))
    filled = [line for line in lines if line["filled"]]
    assert len(filled) == 1
    assert filled[0]["price"] == _line_price(1)  # 125 — 175(높은 쪽)가 비워졌다


@requires_db
def test_grid_slot_disabled_when_unexplainable(make_slot, test_user, test_coin):
    """복구로도 설명이 안 되면 슬롯을 OFF한다 — 추측으로 자금을 움직이지 않는다.

    포지션은 있는데 그걸 설명할 체결 기록이 없는 상태다 (2.4절 표 마지막 줄).
    """
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )
    # 체결 기록을 일부러 남기지 않는다.

    report = reconcile.reconcile_shards({_shard_of(test_user)})

    assert report.disabled == 1
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).is_active is False


@requires_db
def test_grid_reconcile_skips_slots_in_other_shards(make_slot, test_user, test_coin):
    """내 샤드가 아닌 슬롯은 건드리지 않는다 — 재조정도 샤드 경계를 지켜야 한다."""
    if _shard_count() < 2:
        pytest.skip("남의 샤드가 존재하지 않는다 (SHARD_COUNT=1 롤백 구성)")

    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    other_shard = {(_shard_of(test_user) + 1) % _shard_count()}
    report = reconcile.reconcile_shards(other_shard)

    assert report.checked == 0
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).is_active is True


def _shard_count() -> int:
    from app.config import settings

    return settings.shard_count


# --- DCA -----------------------------------------------------------------


@requires_db
def test_dca_next_buy_at_pushed_after_recorded_fill(make_slot, test_user, test_coin):
    """예정 시각 이후에 체결된 매수가 있으면 그 매수는 이미 일어난 것이다.

    **안 밀면 10초 뒤 다음 tick에 바로 또 산다** — DCA는 확정봉 선점에 묶이지 않아서
    그리드보다 사고가 빠르다 (2.4절).
    """
    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    scheduled = datetime.now(timezone.utc) - timedelta(hours=1)
    filled_at = scheduled + timedelta(minutes=1)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 0,
                "next_buy_at": scheduled.isoformat(),
                "last_buy_price": None,
                "spent_amount": "0",
            }
        },
    )
    _add_filled_auto_buy(slot_id, test_user, test_coin, "1000", "10", filled_at)

    reconcile.reconcile_shards({_shard_of(test_user)})

    dca_state = load_slot_state(slot_id)["dca"]
    assert datetime.fromisoformat(dca_state["next_buy_at"]) > filled_at


@requires_db
def test_dca_spent_and_count_include_the_unrecorded_buy(make_slot, test_user, test_coin):
    """기록 안 된 매수의 지출·횟수를 더한다 — 안 더하면 예산 상한이 그만큼 풀린다.

    "기록 안 된 매수"의 기준은 `next_buy_at`이다: 정기 매수가 기록됐다면 그 시점에 예정
    시각이 미래로 밀렸을 것이므로, 예정 시각 이후 체결은 정의상 아직 안 세어진 매수다.
    """
    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    scheduled = datetime.now(timezone.utc) - timedelta(hours=1)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 2,
                "next_buy_at": scheduled.isoformat(),
                "last_buy_price": "900",
                "spent_amount": "20000",
            }
        },
    )
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "1000", "10", scheduled + timedelta(minutes=1)
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    dca_state = load_slot_state(slot_id)["dca"]
    assert dca_state["executed_count"] == 3  # 2 + 기록 안 된 1건
    assert Decimal(dca_state["spent_amount"]) > Decimal("30000")  # 수수료 포함 체결액이 더해진다


@requires_db
def test_dca_already_recorded_buy_is_not_counted_twice(make_slot, test_user, test_coin):
    """이미 반영된 매수는 다시 더하지 않는다.

    두 번 세면 예산이 실제보다 빨리 소진돼 그 슬롯은 아무 오류 없이 매수를 멈춘다 —
    재조정이 만들어서는 안 되는 방향이다.
    """
    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    now = datetime.now(timezone.utc)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 5,
                # 예정 시각이 미래다 = 직전 매수까지 전부 반영돼 있다는 뜻이다.
                "next_buy_at": (now + timedelta(days=1)).isoformat(),
                "last_buy_price": "1000",
                "spent_amount": "500000",
            }
        },
    )
    _add_filled_auto_buy(slot_id, test_user, test_coin, "1000", "1", now)

    report = reconcile.reconcile_shards({_shard_of(test_user)})

    assert report.dca_repaired == 0
    dca_state = load_slot_state(slot_id)["dca"]
    assert dca_state["executed_count"] == 5
    assert Decimal(dca_state["spent_amount"]) == Decimal("500000")


@requires_db
def test_reconcile_ignores_inactive_slots(make_slot, test_user, test_coin):
    """꺼진 슬롯은 재조정 대상이 아니다 — 워커가 평가하지도 않는다."""
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, is_active=False
    )
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    assert slot_state.read_grid_lines(load_slot_state(slot_id)) == EMPTY_LINES


@requires_db
def test_reconcile_does_not_touch_manual_orders(make_slot, test_user, test_coin):
    """수동 주문은 슬롯 진행 상태의 근거가 아니다.

    사용자가 같은 코인을 직접 산 것을 그리드 라인으로 기록하면, 슬롯이 관리하지도 않는
    수량을 자기 것으로 착각하게 된다.
    """
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )
    with session_scope() as db:
        db.add(
            Order(
                user_id=test_user,
                coin_symbol=test_coin,
                side="buy",
                order_type="market",
                price=Decimal("150"),
                quantity=Decimal("0.5"),
                status="filled",
                source="manual",  # auto가 아니다
                fee=Decimal("0"),
                created_at=datetime.now(timezone.utc),
                filled_at=datetime.now(timezone.utc),
            )
        )

    report = reconcile.reconcile_shards({_shard_of(test_user)})

    assert report.disabled == 1  # 설명할 수 없으므로 OFF (수동 주문으로 메우지 않는다)


# --- 리뷰에서 나온 실패 양상들 ------------------------------------------
#
# 아래는 전부 "재조정이 사고를 막으려다 새 사고를 만드는" 경우다. 재조정은 자금 경로 한가운데
# 있으므로, 여기서 틀리면 크래시가 없어도 돈이 샌다.


@requires_db
def test_dca_extra_buy_is_not_triggered_by_stale_last_price(make_slot, test_user, test_coin):
    """복구는 `last_buy_price`도 함께 옮겨야 한다.

    안 옮기면 기준점이 옛 매수가(더 높은 값)에 남아, 다음 tick에 추가매수 조건(`-X%`)이
    이번 체결가 대비로 성립한다 — **크래시가 없었다면 일어나지 않았을 매수를 재조정이
    만들어내는** 셈이다.
    """
    from app.strategy_engine import dca

    params = {**DCA_PARAMS, "extra_buy_enabled": True, "extra_buy_drop_pct": "5"}
    slot_id = make_slot(strategy_type="dca", indicator=None, params=params)
    scheduled = datetime.now(timezone.utc) - timedelta(hours=1)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 1,
                "next_buy_at": scheduled.isoformat(),
                "last_buy_price": "110",  # 옛 매수가
                "spent_amount": "10000",
            }
        },
    )
    # 실제로는 100에 체결됐는데 상태 기록이 유실됐다.
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "100", "100", scheduled + timedelta(minutes=1)
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    state = load_slot_state(slot_id)
    dca_state = dca.read_state(state)
    assert Decimal(dca_state["last_buy_price"]) == Decimal("100")
    # 기준점이 옮겨졌으므로 현재가 100에서 추가매수가 발동하지 않는다.
    intents = dca.evaluate(
        datetime.now(timezone.utc), Decimal("100"), dca_state, params, Decimal("1000000")
    )
    assert intents == []


@requires_db
def test_dca_rebuild_ignores_orders_from_a_previous_strategy(make_slot, test_user, test_coin):
    """체결 이력 전체를 합산하면 안 된다.

    `update_slot`은 전략을 바꿀 때 `state`를 지우지 않는다. grid에서 dca로 바꾼 슬롯의 옛
    그리드 주문까지 세면 **예산이 즉시 소진되고 그 슬롯은 아무 오류 없이 영영 안 산다** —
    크래시를 고치려다 크래시 없이도 터지는 사고를 만드는 셈이다.
    """
    from app.strategy_engine import dca

    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    scheduled = datetime.now(timezone.utc)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 0,
                "next_buy_at": (scheduled + timedelta(days=1)).isoformat(),
                "last_buy_price": None,
                "spent_amount": "0",
            }
        },
    )
    # 예전 그리드 시절의 대량 매수 이력 (예정 시각보다 과거다)
    for index in range(5):
        _add_filled_auto_buy(
            slot_id, test_user, test_coin, "1000", "100", scheduled - timedelta(days=10 + index)
        )

    reconcile.reconcile_shards({_shard_of(test_user)})

    dca_state = dca.read_state(load_slot_state(slot_id))
    assert dca_state["executed_count"] == 0
    assert Decimal(dca_state["spent_amount"]) == Decimal("0")


@requires_db
def test_dca_without_schedule_is_left_alone(make_slot, test_user, test_coin):
    """기준점(`next_buy_at`)이 없으면 아무것도 되짚지 않는다 — 판단 근거가 없다."""
    from app.strategy_engine import dca

    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    _set_state(slot_id, {})
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "1000", "10", datetime.now(timezone.utc)
    )

    report = reconcile.reconcile_shards({_shard_of(test_user)})

    assert report.dca_repaired == 0
    assert dca.read_state(load_slot_state(slot_id))["executed_count"] == 0


@requires_db
def test_disabled_slot_notifies_the_user(make_slot, test_user, test_coin):
    """설명되지 않는 상태로 슬롯을 끌 때는 사용자에게 알린다.

    서버 로그로만 끄면 사용자에게는 자동매매가 아무 설명 없이 멈춘 것으로 보인다.
    """
    from app.models import Notification

    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS)
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    with session_scope() as db:
        messages = db.scalars(
            select(Notification.message).where(
                Notification.user_id == test_user, Notification.strategy_slot_id == slot_id
            )
        ).all()
    assert any("중지" in message for message in messages)


@requires_db
def test_slot_cannot_be_turned_back_on_with_unexplainable_state(
    make_slot, test_user, test_coin
):
    """재조정이 끈 슬롯을 그대로 다시 켤 수 없다.

    워커는 **샤드를 새로 점유할 때만** 재조정한다. ON 경로가 같은 검사를 하지 않으면, 사용자가
    다시 켠 순간부터 다음 점유 때까지 못 미더운 상태 위에서 거래가 재개된다.
    """
    from app.services import strategy_slots

    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, is_active=False
    )
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )

    with session_scope() as db:
        with pytest.raises(strategy_slots.SlotStateInconsistentError):
            strategy_slots.toggle_slot(db, test_user, slot_id, True)

    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).is_active is False


@requires_db
def test_slot_turns_on_after_state_is_repaired(make_slot, test_user, test_coin):
    """설명 가능한 불일치는 ON 경로에서 복구하고 정상적으로 켜진다."""
    from app.services import strategy_slots

    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, is_active=False
    )
    _set_state(
        slot_id,
        {
            "grid": {"lines": EMPTY_LINES},
            "position": {"quantity": "0.5", "avg_price": "150", "entry_at": "2026-01-01T00:00:00+00:00"},
        },
    )
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "150", "0.5", datetime.now(timezone.utc)
    )

    with session_scope() as db:
        strategy_slots.toggle_slot(db, test_user, slot_id, True)

    lines = slot_state.read_grid_lines(load_slot_state(slot_id))
    assert [line for line in lines if line["filled"]]
    with session_scope() as db:
        assert db.get(StrategySlot, slot_id).is_active is True
