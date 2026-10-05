#!/usr/bin/env bash
# API 처리량 측정 — VU(동시 사용자) 수를 늘려 가며 RPS·p95·실패율을 잰다.
#
# 지금 떠 있는 구성(단일 backend든 scale의 api든)을 그대로 잰다. 비교하려면 구성을 바꿔 두 번 돌린다.
# 유저는 load-<run> 유저의 토큰을 쓴다 (seed.py --tokens).
#
# 사용법:
#   bash backend/scripts/load/bench_api.sh "25 50 100 200"

set -uo pipefail
cd "$(dirname "$0")/../../.." || exit 2
export MSYS_NO_PATHCONV=1

VU_LEVELS="${1:-25 50 100 200}"
RUN="${RUN:-api}"
DURATION="${DURATION:-40s}"
TOKENS="${TOKENS:-200}"
WORK="$(pwd)/backend/scripts/load/.work"
mkdir -p "$WORK"

# 토큰용 유저를 따로 만든다 — 워커 측정용 run과 섞이면 그쪽 슬롯 수가 바뀐다
docker compose run --rm -T --no-deps backend python scripts/load/seed.py \
    --run "$RUN" --users "$TOKENS" --tokens "$TOKENS" 2>/dev/null | tail -1 > "$WORK/users.json"
cp backend/scripts/load/bench_api.js "$WORK/bench_api.js"

for vus in $VU_LEVELS; do
    docker run --rm --network host -v "$WORK:/load" -e VUS="$vus" -e DURATION="$DURATION" \
        grafana/k6:0.54.0 run --quiet --summary-export "/load/summary_$vus.json" /load/bench_api.js \
        >/dev/null 2>&1
    docker run --rm -v "$WORK:/load" python:3.12-slim python -c "
import json
s = json.load(open('/load/summary_$vus.json'))['metrics']
d = s['http_req_duration']; f = s['http_req_failed']
print(f'VU={$vus:>4}  RPS={s[\"http_reqs\"][\"rate\"]:7.1f}  p50={d[\"p(50)\"]:7.1f}ms  p95={d[\"p(95)\"]:7.1f}ms  p99={d[\"p(99)\"]:7.1f}ms  실패율={f[\"value\"]*100:5.2f}%')
"
done

echo "정리: docker compose run --rm -T --no-deps backend python scripts/load/cleanup.py --run $RUN"
