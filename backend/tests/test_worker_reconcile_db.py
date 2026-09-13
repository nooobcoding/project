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
def test_dca_spent_and_count_rebuilt_upward(make_slot, test_user, test_coin):
    """지출·횟수가 유실되면 체결 기록으로 되짚는다 — 안 그러면 예산 상한이 풀린다."""
    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 0,
                "next_buy_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "last_buy_price": None,
                "spent_amount": "0",
            }
        },
    )
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "1000", "10", datetime.now(timezone.utc)
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

    dca_state = load_slot_state(slot_id)["dca"]
    assert dca_state["executed_count"] == 1
    assert Decimal(dca_state["spent_amount"]) > Decimal("10000")  # 수수료 포함 체결액


@requires_db
def test_dca_progress_is_never_lowered(make_slot, test_user, test_coin):
    """재구성값이 저장값보다 작아도 내리지 않는다.

    내리면 이미 쓴 예산이 되살아나 상한이 되레 느슨해진다 — 재조정이 만들어서는 안 되는
    방향이다.
    """
    slot_id = make_slot(strategy_type="dca", indicator=None, params=DCA_PARAMS)
    _set_state(
        slot_id,
        {
            "dca": {
                "executed_count": 5,
                "next_buy_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "last_buy_price": "1000",
                "spent_amount": "500000",
            }
        },
    )
    _add_filled_auto_buy(
        slot_id, test_user, test_coin, "1000", "1", datetime.now(timezone.utc)
    )

    reconcile.reconcile_shards({_shard_of(test_user)})

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
