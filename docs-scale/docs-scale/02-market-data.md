# 확장판 02 — 시세 캐시 공유

**상태**: 설계 초안
**원본 대비**: [`docs/features/09-execution-engine.md`](../docs/features/09-execution-engine.md) 2장(트리거 위치)을 대체한다. 같은 문서의 **3.1~3.4절 체결 규칙은 무수정으로 그대로 유효**하다.
**해결하는 문제**: [00-architecture](00-architecture.md) 1장의 결합점 ②·③

---

## 1. 목적

`services/price_stream.py`의 `_price_cache`는 프로세스 메모리 dict다. 이걸 읽는 모듈이 7개라 프로세스를 쪼개는 순간 시세를 구독하지 않는 프로세스는 가격을 못 읽는다. 캐시를 프로세스 밖으로 꺼내는 것이 이 문서의 전부다.

**설계 목표는 "호출부를 안 고치는 것"이다.** 7개 호출부를 전부 손대면 확장이 아니라 개편이 된다.

---

## 2. Redis 키 설계

| 키 | 타입 | 내용 | 쓰는 주체 | TTL |
|---|---|---|---|---|
| `price:{symbol}` | String (JSON) | 최신 틱 — 현재 `_to_tick()`이 만드는 dict 그대로 + `received_at` | `market-data` | 없음 |
| `ticks:{symbol}` | Pub/Sub 채널 | 틱 발행 | `market-data` | — |
| `pending_symbols` | Set | pending 주문이 있는 심볼 (4.2절) | `api`(주문 생성/취소), `matcher`(체결) | 없음 |
| `ratelimit:upbit:rest` | String (토큰 버킷) | Upbit REST 호출 토큰 | `scheduler`, `api`(백테스트) | — ([04](04-async-jobs.md) 3.2절) |

**Redis가 비어 있어도 시스템은 동작해야 한다** ([00-architecture](00-architecture.md) 3.2절). `price:{symbol}`이 없으면 "아직 시세 없음"으로 처리하고(현재 `get_cached_price`가 `None`을 반환하는 것과 동일), `pending_symbols`가 비어 있으면 최적화만 꺼진 채 DB를 직접 조회한다.

---

## 3. `market-data` 역할

### 3.1 하는 일

현재 `price_stream.run_price_stream()`과 동일하다. 달라지는 것은 캐시 대상뿐이다.

```
Upbit ticker WS 구독 (coins.is_active=true 전체)
  → 틱 수신
    → Redis SET price:{symbol}       (현재: _price_cache[symbol] = tick)
    → Redis PUBLISH ticks:{symbol}   (현재: await _fan_out(...) + to_thread(matcher))
```

`RESUBSCRIBE_INTERVAL_SECONDS`마다 재연결해 상장/폐지를 반영하는 현재 동작은 그대로 유지한다.

**체결 엔진 호출이 여기서 사라진다.** 지금은 `_stream_once()`가 틱마다 `asyncio.to_thread(_run_matcher_safely, ...)`를 부르는데, 확장판에서는 pub/sub 발행까지만 하고 매칭은 `matcher` 역할이 구독해서 처리한다 (4장).

### 3.2 정확히 1개만 활성

리더 선출은 advisory lock ([00-architecture](00-architecture.md) 3.3절). 여러 프로세스가 Upbit WS에 붙어도 기능적으로 깨지지는 않지만, 같은 틱이 여러 번 발행되어 matcher가 중복으로 도는 낭비가 생긴다.

### 3.3 페일오버 공백과 stale 가격 — **새로 필요한 방어**

리더가 죽고 다음 후보가 승격하기까지 수 초의 공백이 생긴다. 그동안 Redis의 `price:{symbol}`은 **낡은 값을 그대로 들고 있다.** 현재 구조에는 이 개념 자체가 없다 — 프로세스가 죽으면 전부 같이 죽었기 때문이다.

분산에서는 시세만 멈추고 워커·matcher는 살아 있을 수 있고, 그러면 **몇 분 전 가격으로 손절이 판정되거나 시장가 주문이 체결된다.** 자금이 실제로 잘못 움직이는 경로다.

방어:

- 틱에 `received_at`(수신 시각)을 함께 저장한다.
- `get_cached_price()`가 `PRICE_MAX_AGE_SECONDS`를 넘은 값을 만나면 **`None`을 반환한다** — 호출부 입장에서는 "아직 시세 없음"과 같아서 기존 분기가 그대로 동작한다.
- 자금이 움직이는 경로(시장가 주문 접수, 워커 청산 판정, 매칭)는 `None`이면 **수행하지 않는다.** 화면 표시 경로는 마지막 값을 회색으로 보여주는 등 완화해도 된다.

> **열린 질문**: `PRICE_MAX_AGE_SECONDS`를 얼마로 할 것인가. 워커 tick이 10초이므로 그보다는 커야 하고(정상 상황에서 거부되면 안 됨), 손절이 늦으면 안 되므로 너무 크면 안 된다. 30초를 초안으로 두되 [06](06-observability.md)의 실측 후 확정한다.

---

## 4. `matcher` 역할

### 4.1 트리거 위치가 바뀐다

| | 현재 | 확장판 |
|---|---|---|
| 호출 주체 | 시세 WS 루프 안 `asyncio.to_thread` | `ticks:{symbol}` 구독 |
| 대상 심볼 | 전부 | 자기 샤드(`crc32(symbol) % SHARD_COUNT`)만 — 점유 방식은 4.3절 |
| 체결 절차 | `run_matching_for_symbol` → `_promote_reserved_orders` → `fill_order` | **동일** |

**[`docs/features/09-execution-engine.md`](../docs/features/09-execution-engine.md) 3장의 체결 규칙·후처리 순서·잠금 순서는 한 글자도 바뀌지 않는다.** 누가 부르느냐만 바뀐다.

같은 심볼이 항상 같은 샤드로 가므로 한 심볼 안에서 매칭 순서가 보장된다. 서로 다른 심볼이 같은 유저의 잔고를 동시에 건드리는 것은 [`09`](../docs/features/09-execution-engine.md) 3.4절 행 잠금이 막는다 ([00-architecture](00-architecture.md) 3.1절).

### 4.2 매 틱 DB 조회를 없앤다 — **새로 필요한 최적화**

현재 `run_matching_for_symbol`은 틱마다 무조건 두 가지를 한다:

1. `_promote_reserved_orders(symbol, price)` — DB 조회
2. `SELECT * FROM orders WHERE coin_symbol=? AND status='pending' AND order_type='limit'` — DB 조회

KRW 마켓이 200종 남짓이고 심볼당 초당 여러 틱이 오므로, **pending 주문이 하나도 없어도 초당 수백 번의 DB 왕복이 발생한다.** 지금은 프로세스가 하나라 커넥션 풀이 자연스러운 상한 역할을 해서 티가 안 나지만, matcher를 여러 개 띄우면 이게 DB를 정면으로 때린다.

**방어**: Redis Set `pending_symbols`를 힌트로 둔다.

```
틱 수신
  → SISMEMBER pending_symbols {symbol}
      → false면 즉시 return (DB 왕복 0)
      → true면 기존 절차 그대로
```

갱신 주체:
- 주문 생성(`create_order`)이 pending 행을 남기면 `SADD`
- 취소·체결로 그 심볼의 pending이 0이 되면 `SREM`

**정합성 주의**: 이 Set은 **힌트일 뿐 진실원천이 아니다.** 잘못된 방향의 오차만 허용된다.
- `pending_symbols`에 남아 있는데 실제로는 없음 → DB 한 번 헛조회. 무해.
- **`pending_symbols`에 없는데 실제로는 있음 → 주문이 영영 체결되지 않는다. 치명적.**

따라서 `SREM`은 실패해도 되지만 `SADD`는 실패하면 안 된다. 안전장치로 **주기적 재구성**을 둔다 — `scheduler`가 N분마다 `SELECT DISTINCT coin_symbol FROM orders WHERE status='pending'`으로 Set을 통째로 다시 만든다. Redis가 날아가도 여기서 복구된다.

### 4.3 샤드 점유 — 워커와 같은 방식, 다른 무게

점유 메커니즘은 [03](03-worker-orchestration.md) 2장과 **동일하다**. `pg_try_advisory_lock(MATCHER_NS, shard_id)`로 잡히는 샤드를 전부 점유하고, 프로세스가 죽으면 세션이 끊기며 자동 해제된다. 네임스페이스만 워커와 다르다.

**샤딩 키는 `coin_symbol`을 유지한다.** 워커는 유저로 바꿨지만([00-architecture](00-architecture.md) 3.1절) matcher는 그러면 안 된다 — 틱이 심볼 단위로 오고, 구독 자체가 `ticks:{symbol}` 채널 단위이며, 한 심볼 안에서의 체결 순서를 보장해야 한다.

`crc32` 값이 애플리케이션과 SQL에서 일치해야 하는 문제는 여기 남는다. **심볼→샤드 매핑을 앱에서 계산해 넘기는 방식**을 쓴다 — KRW 마켓이 200종 남짓이라 목록을 넘기는 비용이 무시할 만하다.

#### 겹쳐도 무해하다 — 워커와 결정적으로 다른 점

샤드 재균형 중 잠깐 두 matcher가 같은 심볼을 처리할 수 있다. **그래도 아무 일도 일어나지 않는다.**

[`docs/features/09-execution-engine.md`](../docs/features/09-execution-engine.md) 3.1절의 조건부 갱신이 이미 막고 있기 때문이다.

```sql
UPDATE orders SET status='filled', filled_at=now()
WHERE id = $1 AND status='pending';
-- rowcount = 0이면 이미 처리된 주문이므로 후속 절차 스킵
```

둘 중 하나만 `rowcount=1`을 받고, 나머지는 그대로 스킵한다. 중복 체결이 **구조적으로 불가능**하다.

| | `worker` | `matcher` |
|---|---|---|
| 샤드가 잠깐 겹치면 | 중복 주문 위험 — `claim_candle`이 2차 방어선 ([03](03-worker-orchestration.md) 3.2절) | **무해.** 조건부 `UPDATE`가 1차이자 완결된 방어 |
| 샤드가 비면 | 그 유저의 슬롯이 평가되지 않음 | 그 심볼의 지정가 주문이 체결되지 않음 |
| 검증 무게 | 무겁다 (자금 경로, [07](07-roadmap.md) 7단계) | 가볍다 ([07](07-roadmap.md) 5단계) |

**이 차이가 로드맵의 단계 순서를 정당화한다.** matcher 분리(5단계)를 워커 샤딩(7단계)보다 먼저, 훨씬 가벼운 검증으로 넘어갈 수 있는 근거가 여기 있다.

#### 빈 샤드는 조용한 실패다

위 표의 두 번째 행이 중요하다. **아무도 점유하지 않은 샤드가 생기면 그 심볼의 지정가 주문은 영영 체결되지 않는데, 프로세스는 전부 정상으로 보인다.** 워커도 마찬가지로 그 유저의 슬롯이 통째로 멈춘다.

`worker_heartbeats`는 살아 있는 프로세스만 행을 남기므로 **빈 샤드는 행 자체가 없어서 아무 경고도 안 난다.** 이건 [06](06-observability.md) 5장 "조용한 실패 금지" 규칙에 정면으로 걸린다 — 그래서 **샤드 커버리지 지표**를 별도로 둔다 ([06](06-observability.md) 3.4절).

---

## 5. 호출부를 안 고치는 방법

`get_cached_price(symbol) -> dict | None` 시그니처를 **그대로 유지**하고 구현만 교체한다.

```python
# app/services/price_cache.py (신규) — 인터페이스는 현재 price_stream과 동일
def get_cached_price(symbol: str) -> dict | None:
    """Redis에서 최신 틱을 읽는다. 없거나 PRICE_MAX_AGE_SECONDS를 넘겼으면 None (3.3절)."""
```

이렇게 하면 7개 호출부 — `routers/prices.py`, `services/coins.py`, `services/dashboard.py`, `services/orders.py`, `services/portfolio.py`, `strategy_engine/worker.py` — 가 **import 경로만 바뀌고 로직은 그대로**다.

로컬 개발에서 Redis를 안 띄우고 싶으면 같은 인터페이스의 인메모리 구현을 남겨두고 설정으로 고른다 (`PRICE_CACHE_BACKEND=memory|redis`). 단일 프로세스로 돌릴 때는 인메모리가 현재와 완전히 동일하게 동작한다.

---

## 6. 프론트 브로드캐스트(`/ws/prices`)

현재는 `_subscribers` dict에 붙은 WebSocket에 같은 프로세스가 직접 팬아웃한다. 확장판에서는 클라이언트가 어느 `api` 프로세스에 붙을지 모르므로, **각 `api` 프로세스가 자기 클라이언트들이 요청한 심볼의 `ticks:{symbol}`을 구독**해 팬아웃한다.

`register()`/`unregister()`의 계약은 그대로고, 내부에서 Redis 구독 심볼 집합을 조정하는 로직만 추가된다. [`docs/features/02-dashboard.md`](../docs/features/02-dashboard.md)가 기술하는 화면 동작은 무변경이다.

**호가(`orderbook_stream.py`)는 손대지 않는다.** 이미 "사용자가 보고 있는 심볼만 온디맨드 구독"이라 클라이언트 범위 상태이고, 프로세스별로 각자 구독해도 정상 동작한다. 프로세스 수만큼 Upbit 호가 연결이 늘어나는 낭비는 있지만, 화면 표시 전용이라 정합성 문제가 없다.

### 6.1 틱 병합 — 필요해지면 여기서 막는다

팬아웃 비용은 `붙은 클라이언트 수 × 초당 틱 수`다. 인기 심볼은 초당 수십 틱이 오므로, 한 `api` 프로세스에 그 심볼을 보는 클라이언트가 수백 명이면 초당 수만 건을 직렬화하게 된다. **`api` 프로세스당 동시 접속 상한이 사실상 여기서 결정된다.**

값싼 완화책이 있다 — **N밀리초(초안 100ms) 단위로 심볼별 최신 틱만 남겨 병합해 보낸다.** 화면 표시 전용 경로이므로 사용자는 차이를 느끼지 못하고, 팬아웃 건수가 심볼당 초당 10건으로 고정된다.

**지금 넣지는 않는다.** 체결·워커는 이 경로를 쓰지 않으므로([00-overview](../docs/00-overview.md) 3장 시세 구독 정책) 정합성과 무관하고, 실제로 부딪히기 전에는 불필요한 복잡도다. [06](06-observability.md)에서 팬아웃 건수를 보다가 필요해지면 켠다.

---

## 7. 검증 방법

1. **단일 프로세스 회귀**: `PROCESS_ROLES` 전부 켜고 `PRICE_CACHE_BACKEND=memory`로 기존 pytest 스위트 전부 통과
2. **Redis 백엔드 회귀**: `PRICE_CACHE_BACKEND=redis`로 같은 스위트 전부 통과
3. **2프로세스 분리**: `market-data`만 있는 프로세스 + `api,matcher,worker` 프로세스로 나눠 기동 → 지정가 주문이 체결되는지, 워커 청산이 도는지
4. **stale 방어**: `market-data`를 강제 종료하고 `PRICE_MAX_AGE_SECONDS` 경과 후 시장가 주문이 거부되는지
5. **`pending_symbols` 오차**: Redis `FLUSHDB` 후 `scheduler` 재구성 주기 안에 미체결 주문이 다시 체결되는지
6. **matcher 중복 점유가 무해한지(4.3절)**: 같은 샤드를 강제로 두 matcher가 점유하게 만들고, 지정가 주문이 **정확히 한 번만** 체결되는지. 조건부 `UPDATE`가 실제로 방어선 역할을 하는지 눈으로 확인하는 절차다
7. **빈 샤드 감지(4.3절)**: matcher 프로세스를 전부 내리고, 샤드 커버리지 경고가 실제로 뜨는지 ([06](06-observability.md) 3.4절)
