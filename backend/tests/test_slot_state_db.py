"""state 소유권 경계의 DB 동작 검증 (07 계획 Step 2B의 핵심 안전장치).

여기서 지키려는 성질은 단 하나다: **워커와 체결 후처리가 같은 state 컬럼을 써도 서로의 키를
지우지 않는다.** 이게 깨지면 포지션이 조용히 사라지거나 확정봉 중복 평가가 되살아나 중복 주문이
난다 — 둘 다 정상 동작처럼 보이다가 잔고가 틀어지는 종류의 버그다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.database import session_scope
from app.services.slot_state import claim_candle, write_position
from tests.conftest import load_slot_state, requires_db

CANDLE_AT = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
POSITION = {"quantity": "1.50000000", "avg_price": "100050.00000000", "entry_at": "2026-09-09T00:00:00+00:00"}


@requires_db
def test_claim_candle_succeeds_once_for_same_candle(make_slot):
    """같은 확정봉을 두 번 선점할 수 없다 — 이것이 중복 주문을 막는 장치다."""
    slot_id = make_slot()

    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT) is True
    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT) is False


@requires_db
def test_claim_candle_accepts_newer_candle_only(make_slot):
    """더 최신 봉만 선점된다. 과거 봉이 뒤늦게 들어와도 되돌아가지 않는다."""
    slot_id = make_slot()

    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT) is True
    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT + timedelta(days=1)) is True
    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT - timedelta(days=1)) is False


@requires_db
def test_claim_candle_preserves_position(make_slot):
    """워커가 봉을 선점해도 체결 후처리가 쓴 position은 그대로 남아야 한다."""
    slot_id = make_slot(state={"position": POSITION})

    with session_scope() as db:
        assert claim_candle(db, slot_id, CANDLE_AT) is True

    state = load_slot_state(slot_id)
    assert state["position"] == POSITION
    assert state["last_evaluated_candle_at"] == CANDLE_AT.isoformat()


@requires_db
def test_write_position_preserves_worker_owned_keys(make_slot):
    """반대 방향 — 체결 후처리가 position을 써도 워커가 쓴 last_evaluated_candle_at은 살아남아야 한다."""
    slot_id = make_slot(state={"last_evaluated_candle_at": CANDLE_AT.isoformat()})

    with session_scope() as db:
        write_position(db, slot_id, POSITION)

    state = load_slot_state(slot_id)
    assert state["position"] == POSITION
    assert state["last_evaluated_candle_at"] == CANDLE_AT.isoformat()


@requires_db
def test_write_position_none_removes_only_position_key(make_slot):
    """전량 청산 시 position 키만 지우고 워커 상태는 건드리지 않는다."""
    slot_id = make_slot(
        state={"position": POSITION, "last_evaluated_candle_at": CANDLE_AT.isoformat()}
    )

    with session_scope() as db:
        write_position(db, slot_id, None)

    state = load_slot_state(slot_id)
    assert "position" not in state
    assert state["last_evaluated_candle_at"] == CANDLE_AT.isoformat()


@requires_db
def test_write_position_stores_numbers_as_strings(make_slot):
    """01-erd.md 3.6절 — state의 수치는 부동소수점 오차를 피하려 문자열로 저장한다."""
    slot_id = make_slot()

    with session_scope() as db:
        write_position(db, slot_id, POSITION)

    stored = load_slot_state(slot_id)["position"]
    assert isinstance(stored["quantity"], str)
    assert Decimal(stored["quantity"]) == Decimal("1.5")
