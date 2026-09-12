"""worker_heartbeats UPSERT 동작 검증 (확장판 00단계, docs-scale/06-observability.md).

`heartbeat.record_tick`을 같은 (role, shard_id, process_id)로 두 번 호출했을 때 행이 늘지
않고 값이 올바르게 갱신·누적되는지가 핵심이다 — 새 프로세스가 뜰 때마다 행이 쌓이면 관측
자체가 무의미해진다.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import session_scope
from app.models import WorkerHeartbeat
from app.services import heartbeat
from tests.conftest import requires_db

ROLE = "worker"
T0 = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _cleanup() -> None:
    with session_scope() as db:
        db.execute(
            delete(WorkerHeartbeat).where(
                WorkerHeartbeat.role == ROLE, WorkerHeartbeat.process_id == heartbeat._PROCESS_ID
            )
        )


def _row() -> WorkerHeartbeat:
    with session_scope() as db:
        row = db.scalar(
            select(WorkerHeartbeat).where(
                WorkerHeartbeat.role == ROLE, WorkerHeartbeat.process_id == heartbeat._PROCESS_ID
            )
        )
        db.expunge(row)
        return row


@requires_db
def test_record_tick_upserts_single_row():
    """같은 프로세스가 tick을 두 번 보고해도 행은 하나만 남는다."""
    _cleanup()
    try:
        heartbeat.record_tick(
            role=ROLE,
            shard_id=None,
            started_at=T0,
            duration_ms=1200,
            budget_ms=10_000,
            item_count=3,
            error_count=0,
            skip_count=1,
        )
        heartbeat.record_tick(
            role=ROLE,
            shard_id=None,
            started_at=T0 + timedelta(seconds=10),
            duration_ms=800,
            budget_ms=10_000,
            item_count=5,
            error_count=1,
            skip_count=2,
        )

        row = _row()
        assert row.last_duration_ms == 800
        assert row.max_duration_ms == 1200  # 더 큰 값을 유지한다
        assert row.item_count == 5  # 최신 값으로 덮어쓴다
        assert row.error_count == 1  # 누적한다
        assert row.skip_count == 3  # 누적한다
        assert row.over_budget_count == 0
    finally:
        _cleanup()


@requires_db
def test_record_tick_counts_budget_overruns():
    """예산(budget_ms) 초과 tick만 over_budget_count가 오른다."""
    _cleanup()
    try:
        heartbeat.record_tick(
            role=ROLE,
            shard_id=None,
            started_at=T0,
            duration_ms=12_000,
            budget_ms=10_000,
            item_count=1,
            error_count=0,
            skip_count=0,
        )
        row = _row()
        assert row.over_budget_count == 1

        heartbeat.record_tick(
            role=ROLE,
            shard_id=None,
            started_at=T0 + timedelta(seconds=10),
            duration_ms=500,
            budget_ms=10_000,
            item_count=1,
            error_count=0,
            skip_count=0,
        )
        row = _row()
        assert row.over_budget_count == 1  # 예산 안이면 늘지 않는다
    finally:
        _cleanup()
