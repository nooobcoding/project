"""워커 tick의 관측 지표를 worker_heartbeats에 남긴다 (확장판 00단계, docs-scale/06-observability.md).

프로세스 구조를 바꾸지 않고 지금의 단일 프로세스에도 그대로 적용된다. tick이 끝날 때마다
호출돼 (role, shard_id, process_id) 단위로 최신 상태 1행을 UPSERT한다.
"""

import logging
import os
import socket
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import peak_checked_out, session_scope
from app.models import WorkerHeartbeat

logger = logging.getLogger(__name__)

# 프로세스가 여러 개로 늘어나도(로드맵 4·7단계) 호스트명+PID면 충분히 구분된다.
_PROCESS_ID = f"{socket.gethostname()}:{os.getpid()}"[:64]


def record_tick(
    *,
    role: str,
    shard_id: int | None,
    started_at: datetime,
    duration_ms: int,
    budget_ms: int,
    item_count: int,
    error_count: int,
    skip_count: int,
) -> None:
    """tick 1회분 결과를 기록한다. 예산 초과는 경고 로그로도 남긴다 (5장 조용한 실패 금지)."""
    over_budget = duration_ms > budget_ms
    if over_budget:
        logger.warning(
            "%s tick 예산 초과: %dms > %dms (item_count=%d)", role, duration_ms, budget_ms, item_count
        )

    with session_scope() as db:
        shard_filter = (
            WorkerHeartbeat.shard_id.is_(None) if shard_id is None else WorkerHeartbeat.shard_id == shard_id
        )
        row = db.scalar(
            select(WorkerHeartbeat).where(
                WorkerHeartbeat.role == role,
                shard_filter,
                WorkerHeartbeat.process_id == _PROCESS_ID,
            )
        )
        if row is None:
            # 누적 컬럼은 여기서 0으로 시작시킨다 — 모델의 default=0은 flush 시점에야
            # 적용돼서, 방금 만든 객체는 아직 None이다.
            row = WorkerHeartbeat(
                role=role,
                shard_id=shard_id,
                process_id=_PROCESS_ID,
                max_duration_ms=0,
                over_budget_count=0,
                error_count=0,
                skip_count=0,
            )
            db.add(row)

        row.last_tick_at = started_at
        row.last_duration_ms = duration_ms
        row.max_duration_ms = max(row.max_duration_ms, duration_ms)
        row.over_budget_count += 1 if over_budget else 0
        row.item_count = item_count
        row.db_connections = peak_checked_out()
        row.error_count += error_count
        row.skip_count += skip_count
        row.updated_at = datetime.now(timezone.utc)
