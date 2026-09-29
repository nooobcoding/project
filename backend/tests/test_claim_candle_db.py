"""확정봉 선점 — 샤드 소유권과 **무관한** 2차 방어선 (07-auto-trading.md 4장).

워커 샤딩(`ShardLocks`)이 1차 방어선이고, 이것이 2차다. 둘의 관계가 이 파일의 요점이다:
락이 어떤 이유로든 새어 **두 워커가 같은 슬롯을 동시에 평가하더라도**, 같은 봉으로는
정확히 한 쪽만 주문을 낼 수 있어야 한다. 1차가 뚫렸을 때 돈이 새느냐 마느냐가 여기서 갈린다.

그런데 `claim_candle`에는 테스트가 하나도 없었다 — 샤딩 테스트들은 샤드 경계만 보고,
이 함수가 실제로 원자적인지는 아무도 확인한 적이 없다.

`worker.py`가 이 함수를 **주문보다 먼저** 커밋한다는 점도 중요하다. 순서가 뒤집히면 주문
도중 실패했을 때 같은 봉으로 다시 진입한다.
"""

import threading
from datetime import datetime, timedelta, timezone

from app.database import session_scope
from app.services import slot_state
from tests.conftest import load_slot_state, requires_db

CANDLE_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _claim(slot_id: int, candle_at: datetime) -> bool:
    with session_scope() as db:
        return slot_state.claim_candle(db, slot_id, candle_at)


@requires_db
def test_first_claim_wins_and_second_is_refused(make_slot):
    """같은 봉을 두 번 선점할 수 없다 — 이것이 무너지면 같은 신호로 두 번 산다."""
    slot_id = make_slot()

    assert _claim(slot_id, CANDLE_AT) is True
    assert _claim(slot_id, CANDLE_AT) is False


@requires_db
def test_claim_records_the_candle_in_state(make_slot):
    slot_id = make_slot()

    _claim(slot_id, CANDLE_AT)

    assert load_slot_state(slot_id)["last_evaluated_candle_at"] == CANDLE_AT.isoformat()


@requires_db
def test_newer_candle_can_be_claimed(make_slot):
    """다음 봉은 당연히 선점된다 — 막아버리면 슬롯이 영영 한 봉에 갇힌다."""
    slot_id = make_slot()
    assert _claim(slot_id, CANDLE_AT) is True

    assert _claim(slot_id, CANDLE_AT + timedelta(minutes=1)) is True


@requires_db
def test_older_candle_is_refused(make_slot):
    """늦게 도착한 옛 봉으로 되돌아가면 안 된다.

    캔들 조회가 잠깐 뒤처진 데이터를 주는 경우가 있는데, 그걸로 다시 평가하면 이미 지나간
    신호가 되살아난다.
    """
    slot_id = make_slot()
    assert _claim(slot_id, CANDLE_AT) is True

    assert _claim(slot_id, CANDLE_AT - timedelta(minutes=1)) is False
    assert load_slot_state(slot_id)["last_evaluated_candle_at"] == CANDLE_AT.isoformat()


@requires_db
def test_claim_preserves_other_state_keys(make_slot):
    """선점은 `last_evaluated_candle_at`만 건드려야 한다.

    state에는 포지션과 그리드 라인이 함께 들어 있다. 통째로 덮어쓰면 워커가 봉을 선점할
    때마다 포지션이 날아간다 — `jsonb_set`을 쓰는 이유가 이것이다.
    """
    slot_id = make_slot(
        state={
            "position": {"quantity": "1", "avg_price": "100", "entry_at": CANDLE_AT.isoformat()},
            "grid": {"lines": [{"price": "100", "filled": True, "quantity": "1"}]},
        }
    )

    _claim(slot_id, CANDLE_AT)

    state = load_slot_state(slot_id)
    assert state["position"]["quantity"] == "1"
    assert state["grid"]["lines"][0]["filled"] is True


@requires_db
def test_concurrent_claims_of_the_same_candle_yield_exactly_one_winner(make_slot):
    """**이 파일의 핵심.** 두 워커가 같은 순간에 같은 봉을 선점하려 하면 한 쪽만 이긴다.

    샤드 락이 새어 두 프로세스가 같은 슬롯을 잡은 상황이 정확히 이 모양이다. 순차로 부르면
    조건부 UPDATE가 아니라 단순한 "읽고 나서 쓰기"여도 통과하므로, 같은 순간에 들어가야
    원자성이 실제로 검증된다.
    """
    for _ in range(5):
        # 선점은 활성 여부와 무관하다. 반복하려면 비활성이어야 한다 — 유저·코인당 활성 슬롯은
        # 하나뿐이라는 유니크 제약이 있어서다.
        slot_id = make_slot(is_active=False)
        barrier = threading.Barrier(4)
        results: list[bool] = [False] * 4

        def _race(index: int) -> None:
            with session_scope() as db:
                barrier.wait()
                results[index] = slot_state.claim_candle(db, slot_id, CANDLE_AT)

        threads = [threading.Thread(target=_race, args=(i,)) for i in range(len(results))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(results) == 1, f"같은 봉을 {sum(results)}명이 선점했다"


@requires_db
def test_concurrent_claims_of_different_slots_all_succeed(make_slot, test_coin):
    """음성 대조군 — 서로 다른 슬롯은 서로를 막지 않아야 한다.

    이게 없으면 "선점이 통째로 고장나 항상 False"인 구현도 위 테스트를 통과한다.
    """
    slot_ids = [make_slot(is_active=False) for _ in range(4)]
    barrier = threading.Barrier(len(slot_ids))
    results: list[bool] = [False] * len(slot_ids)

    def _race(index: int) -> None:
        with session_scope() as db:
            barrier.wait()
            results[index] = slot_state.claim_candle(db, slot_ids[index], CANDLE_AT)

    threads = [threading.Thread(target=_race, args=(i,)) for i in range(len(slot_ids))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(results), f"서로 다른 슬롯이 서로의 선점을 막았다: {results}"
