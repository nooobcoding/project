#!/usr/bin/env bash
# 워커 처리 한계 측정 — 워커 프로세스 수 × 활성 슬롯 수 조합마다 tick 소요를 잰다.
#
# 여러 프로세스 구성(docker-compose.scale.yml)이 떠 있어야 한다. 조합마다:
#   1) --scale worker=N 으로 맞추고
#   2) 활성 슬롯이 목표 수가 되도록 load-<run> 유저를 추가하고 (seed.py는 누적이다)
#   3) 재균형·캔들 준비를 기다린 뒤
#   4) 130초(1분봉 경계 두 번) 동안 프로세스별 tick 소요를 모은다 (sample_ticks.py)
#
# 결과는 조합마다 JSON 한 덩어리로 표준출력에 찍힌다. 끝나면 cleanup.py로 지운다.
#
# 사용법:
#   bash backend/scripts/load/bench_worker.sh "1 2 4" "1000 2000 4000"
#   docker compose run --rm -T --no-deps backend python scripts/load/cleanup.py --run bench

set -uo pipefail
cd "$(dirname "$0")/../../.." || exit 2
export MSYS_NO_PATHCONV=1

WORKER_COUNTS="${1:-1 2 4}"
SLOT_TARGETS="${2:-1000 2000 4000}"
RUN="${RUN:-bench}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-130}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.scale.yml)
RUN_TOOL=(docker compose run --rm -T --no-deps backend python)

current_slots() {
    docker compose exec -T postgres psql -U coin_autotrading -d coin_autotrading -t -A -c \
        "SELECT COUNT(*) FROM strategy_slots s JOIN users u ON u.id = s.user_id
          WHERE u.email LIKE 'load-${RUN}-%' AND s.is_active" | tr -d '[:space:]'
}

for target in $SLOT_TARGETS; do
    have=$(current_slots)
    if [ "$have" -lt "$target" ]; then
        "${RUN_TOOL[@]}" scripts/load/seed.py --run "$RUN" --users $(( target - have )) 2>&1 | grep "^run="
    fi
    for workers in $WORKER_COUNTS; do
        "${COMPOSE[@]}" up -d --no-recreate --scale worker="$workers" --scale matcher=2 >/dev/null 2>&1
        # 재균형은 두 tick(10초 주기)에 걸친다. 줄일 때는 사라진 프로세스의 락이 풀려야 한다.
        sleep 35
        echo "=== workers=$workers slots=$(current_slots) ==="
        "${RUN_TOOL[@]}" scripts/load/sample_ticks.py --seconds "$SAMPLE_SECONDS" 2>/dev/null \
            | sed -n '/^{/,$p'
    done
done
