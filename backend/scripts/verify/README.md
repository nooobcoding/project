# 분산 검증 런북

`pytest`로 옮길 수 없는 것만 여기에 둔다.

## 대부분은 여기 없다

확장판 로드맵을 만들 때는 분산 검증을 전부 스크립트로 남길 계획이었지만, 실제로 짜보니
**대부분은 pytest로 충분했다.** PostgreSQL advisory lock은 세션 단위라 한 프로세스 안에서도
커넥션을 따로 열면 그것이 곧 별개의 경쟁자다. 프로세스를 띄우지 않아도 잠금 경합이 그대로
재현된다.

매 실행마다 도는 테스트가 아무도 안 돌리는 런북보다 낫기 때문에, 옮길 수 있는 것은 옮겼다:

| 원래 계획한 스크립트 | 실제 위치 |
|---|---|
| `pool_trap.py` (풀 커넥션의 락 소실) | [`tests/test_leader_db.py`](../../tests/test_leader_db.py) |
| `shard_overlap.py` (중복 평가 방지) | [`tests/test_claim_candle_db.py`](../../tests/test_claim_candle_db.py) |
| `stale_price.py` (시세 정지 시 주문 거부) | [`tests/test_price_cache.py`](../../tests/test_price_cache.py) |
| `crash_reconcile.py` (체결 후 사망 → 복구) | [`tests/test_worker_reconcile_db.py`](../../tests/test_worker_reconcile_db.py) |
| `token_bucket.py` (프로세스 간 버킷 공유) | [`tests/test_rate_limit_redis.py`](../../tests/test_rate_limit_redis.py) |

## 여기 남은 것

### `shard_failover.sh`

**프로세스를 실제로 SIGKILL해야만 확인되는 유일한 항목.** 이 설계가 "페일오버가 공짜로
따라온다"고 말하는 근거는 *정리 코드가 돌 기회조차 없이 죽어도 세션이 끊기며 락이 풀린다*는
점인데, 그 주장은 진짜로 죽여봐야 확인된다.

```bash
docker compose up -d postgres
docker compose stop backend        # 개발 서버가 샤드를 전부 쥐고 있으므로 잠시 멈춘다
bash backend/scripts/verify/shard_failover.sh
docker compose start backend
```

종료 코드: `0` 통과 / `1` 검증 실패 / `2` 환경 문제(컨테이너 없음, 샤드 선점자 있음 등).

**환경 문제를 검증 실패와 구분하는 것이 중요하다** — 개발 backend가 떠 있으면 이 스크립트가
띄운 워커는 샤드를 하나도 못 잡는데, 그걸 코드 결함으로 읽으면 멀쩡한 구현을 뜯어보게 된다.
그래서 사전검사가 exit 2로 먼저 막는다.

#### 이 스크립트가 확인하는 동작

혼자 뜬 워커가 전부 가져가고, 두 번째가 뜨면 **반씩 나눠 갖고**(공정 몫), 하나를 SIGKILL하면
남은 쪽이 전부 넘겨받는다. 실측 예: `SHARD_COUNT=4`에서 `[0 1 2 3]` → `[0 1]`/`[2 3]` →
SIGKILL 9초 뒤 남은 쪽이 `[0 1 2 3]`.

**예전에는 반씩 갈리지 않았다** — 먼저 뜬 쪽이 독식하고 나중 쪽은 대기만 했고, 이 스크립트도
그걸 "의도된 동작"으로 고정하고 있었다. 그러면 워커를 늘려도 처리량이 안 는다. 프로세스를
나누는 목적이 거기 있으므로 공정 몫으로 바꿨다 (03-worker-orchestration.md 2.1절).

## 왜 pytest에 안 넣는가

docker compose 오케스트레이션이 필요해 느리고(분 단위), 개발 서버를 잠시 멈춰야 하며,
컨테이너 기동 시간에 따라 결과가 흔들린다. 릴리스 전이나 샤딩·리더 선출 구조를 건드렸을 때
손으로 돌리는 런북으로 유지한다.
