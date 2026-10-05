"""워커 tick 소요를 프로세스 단위로 모은다.

heartbeat는 **샤드마다** 한 행이라, 프로세스 한 번의 tick 소요는 같은 tick(같은 last_tick_at)에
속한 그 프로세스 샤드들의 합이다. 몇 초마다 훑어 (프로세스, tick)별 합을 모으고 끝나면 분포를
낸다. 같은 tick을 여러 번 보면 큰 값을 쓴다 — 샤드 행을 쓰는 도중에 읽으면 합이 덜 잡힌다.

1분봉 슬롯은 새 봉이 확정되는 tick에 한꺼번에 평가되고 나머지 tick은 거의 빈 손이다. 그래서
평균은 의미가 없고 **최댓값(=봉 경계 tick)이 예산 10초를 넘는가**가 판정 기준이다.

사용법 (컨테이너 안):
    python scripts/load/sample_ticks.py --seconds 180
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import session_scope  # noqa: E402

BUDGET_MS = 10_000


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    since = datetime.now(timezone.utc)
    ticks: dict[tuple[str, str], tuple[int, int]] = {}  # (process, tick) -> (합계 ms, 슬롯 수)
    connections: dict[str, int] = {}
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        with session_scope() as db:
            rows = db.execute(
                text(
                    "SELECT process_id, last_tick_at, SUM(last_duration_ms) AS ms, "
                    "SUM(item_count) AS slots, MAX(db_connections) AS conns "
                    "FROM worker_heartbeats WHERE role = 'worker' AND last_tick_at >= :since "
                    "GROUP BY process_id, last_tick_at"
                ),
                {"since": since},
            ).all()
        for row in rows:
            key = (row.process_id, row.last_tick_at.isoformat())
            ms, slots = ticks.get(key, (0, 0))
            ticks[key] = (max(ms, int(row.ms)), max(slots, int(row.slots)))
            connections[row.process_id] = max(connections.get(row.process_id, 0), int(row.conns))
        time.sleep(args.interval)

    per_process: dict[str, list[tuple[int, int]]] = {}
    for (process, _), value in ticks.items():
        per_process.setdefault(process, []).append(value)

    summary = {"processes": len(per_process), "per_process": {}}
    worst = 0
    for process, values in sorted(per_process.items()):
        durations = [ms for ms, _ in values]
        worst = max(worst, max(durations))
        summary["per_process"][process] = {
            "ticks": len(values),
            "max_ms": max(durations),
            "p95_ms": percentile(durations, 95),
            "p50_ms": percentile(durations, 50),
            "max_slots_in_tick": max(slots for _, slots in values),
            "over_budget_ticks": sum(1 for ms in durations if ms > BUDGET_MS),
            "db_connections_peak": connections.get(process, 0),
        }
    summary["worst_tick_ms"] = worst
    summary["over_budget"] = worst > BUDGET_MS
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
