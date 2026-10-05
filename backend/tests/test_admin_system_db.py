"""관리자 시스템 대시보드 (확장판 05-admin.md 3-D, 06-observability.md 3.4절)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, update

from app.config import settings
from app.database import session_scope
from app.models import User, WorkerHeartbeat
from app.models.user import ROLE_ADMIN
from app.services import admin as admin_service
from app.services import rate_limit
from app.services.auth import create_access_token
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def admin_headers(make_user):
    user_id = make_user()
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(role=ROLE_ADMIN))
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _system(client, headers) -> dict:
    response = client.get("/api/admin/system", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- 샤드 커버리지


def test_missing_shards_are_listed(client, admin_headers, monkeypatch):
    """미점유 샤드가 목록으로 나와야 한다 — 이게 이 화면의 존재 이유다.

    `worker_heartbeats`로는 못 찾는다(살아 있는 프로세스만 행을 남긴다). 락을 직접 센 결과를
    그대로 쓰는지 본다.
    """
    monkeypatch.setattr(admin_service.leader, "occupied_shards", lambda namespace: {0})

    body = _system(client, admin_headers)

    assert body["shard_count"] == settings.shard_count
    assert body["worker_coverage"] == {"applicable": True, "missing": list(range(1, settings.shard_count))}


def test_matcher_coverage_only_applies_to_the_redis_layout(client, admin_headers, monkeypatch):
    """memory 구성은 체결을 시세 루프가 직접 해서 matcher 샤드가 없다 — 그걸 '전부 비었다'로 보이면 안 된다."""
    monkeypatch.setattr(admin_service.leader, "occupied_shards", lambda namespace: set())

    coverage = _system(client, admin_headers)["matcher_coverage"]

    if settings.price_cache_backend == "redis":
        assert coverage == {"applicable": True, "missing": list(range(settings.shard_count))}
    else:
        assert coverage == {"applicable": False, "missing": []}


def test_coverage_lookup_failure_reads_as_unknown_not_healthy(client, admin_headers, monkeypatch):
    """조회 실패를 빈 목록으로 내리면 화면에 '전부 점유됨'으로 보인다 — 가장 나쁜 거짓말이다."""

    def boom(namespace):
        raise RuntimeError("pg_locks 조회 실패")

    monkeypatch.setattr(admin_service.leader, "occupied_shards", boom)

    assert _system(client, admin_headers)["worker_coverage"] == {"applicable": True, "missing": None}


def test_real_lock_lookup_runs(client, admin_headers):
    """monkeypatch 없이 실제 pg_locks 조회 경로가 도는지 — 결과는 환경마다 달라 형태만 본다."""
    coverage = _system(client, admin_headers)["worker_coverage"]

    assert coverage["applicable"] is True
    assert set(coverage["missing"]) <= set(range(settings.shard_count))


# ---------------------------------------------------------------- heartbeat


@pytest.fixture
def heartbeat_rows():
    process_id = f"admin-test-{uuid.uuid4().hex[:8]}"

    def _add(role: str, shard_id: int | None, seconds_ago: int) -> None:
        now = datetime.now(timezone.utc)
        with session_scope() as db:
            db.add(
                WorkerHeartbeat(
                    role=role,
                    shard_id=shard_id,
                    process_id=process_id,
                    last_tick_at=now - timedelta(seconds=seconds_ago),
                    last_duration_ms=120,
                    max_duration_ms=900,
                    over_budget_count=2,
                    item_count=7,
                    db_connections=3,
                    error_count=1,
                    skip_count=4,
                    updated_at=now,
                )
            )

    yield process_id, _add
    with session_scope() as db:
        db.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.process_id == process_id))


def test_heartbeat_staleness_uses_each_roles_own_interval(client, admin_headers, heartbeat_rows):
    """락은 쥐었는데 tick이 안 도는 프로세스를 잡는다 (06 3.4절 두 번째 행).

    worker는 10초, matcher는 30초 주기다. 같은 40초 경과라도 worker(한도 30초)는 멈춘 것이고
    matcher(한도 90초)는 정상이다. 숫자 하나로 정하면 둘 중 하나를 틀린다.
    """
    process_id, add = heartbeat_rows
    add("worker", 0, seconds_ago=5)
    add("worker", 1, seconds_ago=40)
    add("matcher", 0, seconds_ago=40)

    rows = [h for h in _system(client, admin_headers)["heartbeats"] if h["process_id"] == process_id]
    stale = {(h["role"], h["shard_id"]): h["stale"] for h in rows}

    assert stale == {("worker", 0): False, ("worker", 1): True, ("matcher", 0): False}
    sample = next(h for h in rows if h["shard_id"] == 1 and h["role"] == "worker")
    assert (sample["error_count"], sample["skip_count"], sample["db_connections"]) == (1, 4, 3)
    assert sample["seconds_since_tick"] >= 40


def test_counts(client, admin_headers, make_user, make_slot):
    before = _system(client, admin_headers)
    suspended = make_user()
    with session_scope() as db:
        db.execute(update(User).where(User.id == suspended).values(status="suspended"))
    make_slot()

    after = _system(client, admin_headers)

    assert after["suspended_users"] == before["suspended_users"] + 1
    assert after["active_slots"] == before["active_slots"] + 1


# ---------------------------------------------------------------- Upbit 토큰 버킷


@pytest.fixture
def fresh_buckets():
    rate_limit.reset()
    if settings.price_cache_backend == "redis":
        from app.services.redis_client import get_redis

        keys = (f"{rate_limit.KEY_PREFIX}:high", f"{rate_limit.KEY_PREFIX}:low", rate_limit.PENALTY_KEY)
        get_redis().delete(*keys)
        yield
        get_redis().delete(*keys)
    else:
        yield
    rate_limit.reset()


def test_peek_reports_consumption_without_consuming(fresh_buckets):
    """대시보드를 열 때마다 토큰이 줄면 관리 화면이 레이트리밋을 갉아먹는다."""
    first = rate_limit.peek()
    for _ in range(20):
        rate_limit.peek()
    capacity = first["buckets"]["low"]["capacity"]
    assert rate_limit.peek()["buckets"]["low"]["tokens"] == capacity

    with rate_limit.priority("low"):
        rate_limit.acquire(timeout=0)
        rate_limit.acquire(timeout=0)

    tokens = rate_limit.peek()["buckets"]["low"]["tokens"]
    assert capacity - 2 <= tokens < capacity - 1.5  # 그사이 리필된 몇 ms 분량만 허용
    assert rate_limit.peek()["buckets"]["high"]["tokens"] == rate_limit.peek()["buckets"]["high"]["capacity"]
    assert first["backend"] == ("redis" if settings.price_cache_backend == "redis" else "memory")


def test_system_endpoint_includes_rate_limit(client, admin_headers, fresh_buckets):
    status = _system(client, admin_headers)["upbit_rate_limit"]

    assert status["penalty"] >= 1
    assert set(status["buckets"]) == {"high", "low"}
