#!/usr/bin/env bash
# 워커 샤드 페일오버 — 프로세스를 **실제로 죽여서** 승계를 확인한다.
#
# 왜 pytest가 아닌가:
#   나머지 분산 검증은 전부 pytest로 옮겼다. advisory lock은 세션 단위라 한 프로세스 안에서도
#   커넥션만 따로 열면 별개의 경쟁자가 되기 때문이다 (tests/test_leader_db.py).
#   하지만 딱 하나, **SIGKILL로 죽을 때 정말 세션이 끊기고 락이 풀리는가**는 죽여봐야 안다.
#   정리 코드가 돌 기회조차 없는 상황이 이 설계가 "페일오버가 공짜"라고 말하는 근거이므로,
#   그 주장을 확인하려면 진짜로 죽여야 한다.
#
#   또 이 스크립트는 docker compose를 부르므로 **호스트에서** 돈다 (컨테이너 안에는 docker가
#   없다). test_matrix.sh와 같은 이유로 bash다.
#
# 확인하는 것:
#   1. 혼자 뜬 워커가 샤드를 **전부** 가져간다
#   2. 두 번째 워커가 뜨면 먼저 뜬 쪽이 초과분을 놓아 **반씩 나눠 갖는다** (공정 몫)
#   3. 먼저 뜬 쪽을 SIGKILL하면 세션이 끊기며 샤드 락과 멤버 락이 함께 풀리고
#   4. 남은 쪽의 몫이 커져 다음 tick 주기 안에 전부 넘겨받는다
#
#   2번은 예전에는 "먼저 뜬 쪽이 독식하고 나중 쪽은 대기"였고 이 스크립트도 그걸 고정했다.
#   그러면 워커를 늘려도 처리량이 안 늘어 프로세스를 나누는 목적이 무너진다 — 그래서 바꿨다
#   (leader.ShardLocks docstring).
#
# 사용법:
#   docker compose up -d postgres
#   bash backend/scripts/verify/shard_failover.sh
#
# 종료 코드: 0 성공 / 1 검증 실패 / 2 환경 문제

set -uo pipefail

cd "$(dirname "$0")/../../.." || exit 2
export MSYS_NO_PATHCONV=1

SHARD_COUNT=4
WORKER_SHARD_NAMESPACE=4003   # services/leader.py와 같아야 한다
SUCCESSION_TIMEOUT=40          # 워커 tick 주기(10초)의 여러 배 — 승계는 다음 tick에 일어난다
NAME_A="shard-failover-a"
NAME_B="shard-failover-b"

fail()  { echo "실패: $*"; exit 1; }
abort() { echo "중단: $*"; exit 2; }

cleanup() {
    docker compose kill -s KILL "$NAME_A" "$NAME_B" >/dev/null 2>&1
    docker rm -f "$NAME_A" "$NAME_B" >/dev/null 2>&1
}
trap cleanup EXIT

require_postgres() {
    # 환경 문제를 검증 실패와 구분한다 — 안 그러면 postgres가 없는 것을 코드 결함으로 읽는다.
    if ! docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep -q "^postgres running$"; then
        abort "postgres 컨테이너가 떠 있지 않다 — 코드 문제가 아니라 환경 문제다.
      docker compose up -d postgres"
    fi
}

start_worker() {
    # 워커 역할만 켠다. API·시세 스트림은 끄고 샤드 점유만 보게 한다.
    docker compose run --rm -d --name "$1" \
        -e PROCESS_ROLES=worker \
        -e "SHARD_COUNT=$SHARD_COUNT" \
        backend uvicorn app.main:app --host 0.0.0.0 --port 8000 >/dev/null 2>&1
}

# 점유 상태를 프로세스가 아니라 **락 쪽**에서 본다 — "세션이 끊기며 락이 풀린다"는 주장을
# 확인하려면 DB가 보는 그림이 기준이어야 한다.
owner_lines() {
    docker compose exec -T postgres \
        psql -U coin_autotrading -d coin_autotrading -t -A -F ' ' -c \
        "SELECT pid, objid FROM pg_locks
          WHERE locktype = 'advisory' AND classid = $WORKER_SHARD_NAMESPACE
            AND objsubid = 2 AND granted
          ORDER BY pid, objid" 2>/dev/null | sed '/^$/d'
}

distinct_owners() { owner_lines | awk '{print $1}' | sort -u; }
shards_of()       { owner_lines | awk -v p="$1" '$1 == p {print $2}' | sort -n | tr '\n' ' '; }
total_shards()    { owner_lines | awk '{print $2}' | sort -un | tr '\n' ' '; }

wait_for() {
    local description="$1" timeout="$2" check="$3"
    local deadline=$(( SECONDS + timeout ))
    while [ $SECONDS -lt $deadline ]; do
        if eval "$check"; then return 0; fi
        sleep 1
    done
    fail "$description — ${timeout}초 안에 일어나지 않았다"
}

require_no_other_shard_holders() {
    # 개발용 backend 컨테이너는 기본 설정(PROCESS_ROLES 전체, SHARD_COUNT=16)으로 뜨면서
    # 워커 샤드를 전부 점유한다. 그 상태에서는 이 스크립트가 띄운 워커가 아무것도 못 잡아
    # "샤드가 안 갈렸다"는 **검증 실패처럼 보이는 환경 문제**가 된다. 미리 구분해 준다.
    local holders
    holders=$(distinct_owners | wc -l)
    if [ "$holders" -ne 0 ]; then
        abort "워커 샤드를 이미 점유한 프로세스가 있다 (pid: $(distinct_owners | tr '\n' ' ')).
      개발용 backend가 떠 있으면 샤드를 전부 쥔다 — 코드 문제가 아니라 환경 문제다.
      docker compose stop backend
      (검증이 끝나면 docker compose start backend)"
    fi
}

require_postgres

echo "=== 워커 샤드 페일오버 검증 (SHARD_COUNT=$SHARD_COUNT) ==="
cleanup
require_no_other_shard_holders

EXPECTED=$(seq 0 $((SHARD_COUNT - 1)) | tr '\n' ' ')

echo "1) 먼저 뜬 워커가 샤드를 전부 가져가는가"
start_worker "$NAME_A"
wait_for "첫 워커가 샤드를 전부 잡지 못했다" 90 '[ "$(total_shards)" = "'"$EXPECTED"'" ]'

FIRST_PID=$(distinct_owners)
[ "$(echo "$FIRST_PID" | wc -l)" -eq 1 ] || fail "점유자가 하나가 아니다: $FIRST_PID"
echo "   pid $FIRST_PID → [$(shards_of "$FIRST_PID")]"

echo "2) 나중에 뜬 워커가 공정 몫을 받는가"
start_worker "$NAME_B"
# 재균형은 두 주기에 걸친다: B가 참여자로 등록 → A가 다음 tick에 초과분을 놓음 → B가 그다음에 집음.
wait_for "두 워커가 샤드를 나눠 갖지 않았다 (공정 몫이 동작하지 않는다)" 60 \
    '[ "$(distinct_owners | wc -l)" -eq 2 ] && [ "$(total_shards)" = "'"$EXPECTED"'" ]'
for pid in $(distinct_owners); do
    count=$(shards_of "$pid" | wc -w)
    [ "$count" -eq $(( SHARD_COUNT / 2 )) ] || fail "몫이 고르지 않다: pid $pid → $count개"
    echo "   pid $pid → [$(shards_of "$pid")]"
done
FIRST_SHARDS=$(shards_of "$FIRST_PID")

echo "3) 먼저 뜬 쪽을 SIGKILL (정리 코드가 돌 기회를 주지 않는다)"
docker compose kill -s KILL "$NAME_A" >/dev/null 2>&1 || docker kill "$NAME_A" >/dev/null 2>&1
KILLED_AT=$SECONDS

echo "4) 남은 워커가 죽은 쪽 몫까지 전부 넘겨받는가"
wait_for "남은 워커가 샤드를 넘겨받지 못했다" "$SUCCESSION_TIMEOUT" \
    '[ "$(total_shards)" = "'"$EXPECTED"'" ] && [ "$(distinct_owners | wc -l)" -eq 1 ] && [ "$(distinct_owners)" != "'"$FIRST_PID"'" ]'

NEW_PID=$(distinct_owners)
echo "   승계 완료 — $(( SECONDS - KILLED_AT ))초 (pid $FIRST_PID 의 [$FIRST_SHARDS] → pid $NEW_PID)"
echo
echo "통과: 두 워커가 샤드를 반씩 나눠 가졌고, 하나가 죽자 남은 쪽이 전부 넘겨받았다"
