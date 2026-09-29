#!/usr/bin/env bash
# 테스트 매트릭스 — 지금까지 손으로 돌리던 4개 구성을 한 번에 돌린다.
#
# 구성이 4개인 이유는 각각 **다른 코드 경로**를 타기 때문이다:
#
#   기본(memory)   : 단일 프로세스 롤백 경로. 체결이 시세 루프 안에서 직접 일어난다.
#   redis          : 다중 프로세스 경로. pub/sub·pending_symbols 힌트·토큰 버킷이 여기서만 돈다.
#   SHARD_COUNT=1  : 로드맵이 정의한 워커 샤딩 롤백 구성. "현재 동작과 같아야 한다"의 기준.
#   SHARD_COUNT=4  : 샤드가 실제로 갈리는 구성. 샤드 경계 테스트가 여기서만 의미를 갖는다.
#
# 하나만 돌리고 통과했다고 넘어가면 나머지 셋 중 하나가 깨진 걸 놓친다.
#
# 사용법:
#   backend/scripts/test_matrix.sh              # 전체
#   backend/scripts/test_matrix.sh tests/test_wallet_db.py   # 특정 파일만 4구성으로

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1
export MSYS_NO_PATHCONV=1

TARGET="${*:-}"
REDIS_URL="redis://redis:6379/0"

run_config() {
    local label="$1"; shift
    local env_args=("$@")

    printf '%-18s' "$label"
    local output
    output=$(docker compose run --rm -T "${env_args[@]}" backend pytest -q ${TARGET} 2>&1)
    local status=$?
    local summary
    summary=$(printf '%s\n' "$output" | grep -E "passed|failed|error" | tail -1)

    if [ $status -eq 0 ]; then
        echo "OK   ${summary}"
    else
        echo "FAIL ${summary}"
        printf '%s\n' "$output" | grep -E "^(FAILED|ERROR)" | head -20
        FAILED_CONFIGS+=("$label")
    fi
}

require_service() {
    # 의존 서비스가 안 떠 있으면 테스트가 "실패"로 보이는데 원인은 코드가 아니라 환경이다.
    # 그 둘을 구분해 주지 않으면 매트릭스가 거짓 신호를 내는 셈이라 먼저 막는다.
    local service="$1"
    if ! docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null \
        | grep -q "^${service} running$"; then
        echo "중단: '${service}' 컨테이너가 떠 있지 않다 — 코드 문제가 아니라 환경 문제다."
        echo "      docker compose up -d ${service}"
        exit 2
    fi
}

require_service postgres
require_service redis

FAILED_CONFIGS=()

echo "=== 테스트 매트릭스 ${TARGET:+(대상: $TARGET)} ==="
run_config "기본(memory)"
run_config "redis"          -e PRICE_CACHE_BACKEND=redis -e REDIS_URL="$REDIS_URL"
run_config "SHARD_COUNT=1"  -e SHARD_COUNT=1
run_config "SHARD_COUNT=4"  -e SHARD_COUNT=4

echo
if [ ${#FAILED_CONFIGS[@]} -eq 0 ]; then
    echo "4개 구성 전부 통과"
    exit 0
fi
echo "실패한 구성: ${FAILED_CONFIGS[*]}"
exit 1
