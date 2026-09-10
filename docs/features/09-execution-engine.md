# 09. 체결 엔진 (공용 인프라)

**상태**: 구현중 (코드 작성 완료, 로컬 DB 마이그레이션·수동 검증 대기)
**화면 ID**: 없음 — 화면을 갖지 않는 백엔드 공용 인프라 문서
**의존성**: `02-dashboard`(시세 스트림 캐시), `03-manual-trading`(`orders` 생성 로직)
**연관 문서**: [00-overview.md](../00-overview.md) 3장(아키텍처), [01-erd.md](../01-erd.md) 3.1~3.2절, `03-manual-trading`, `07-auto-trading`

---

## 1. 목적

`orders.status='pending'`인 지정가 주문을 **체결로 전환시키는 주체**를 정의한다. 03(수동매매)의 지정가 주문·미체결 목록·취소 UI와 05/07/08의 잔고·손익 계산은 모두 이 전환이 일어난다는 전제 위에 서 있지만, 그 실행 주체가 기존 문서 어디에도 없었다. 이 문서가 그 공백을 메운다.

수동매매(03)의 지정가 주문은 2장의 매칭 큐를 거쳐 체결되고, 시장가 주문(03의 시장가 + 07 자동매매 전량 — [07-auto-trading.md](07-auto-trading.md) 4.1절, 워커는 항상 시장가)은 `POST /api/orders` 처리 중 즉시 체결된다. **두 경로 모두 3.2절의 동일한 체결 후처리 절차를 공유**하며, 이것이 `orders`/`holdings`/`balances`를 갱신하는 유일한 지점이다.

---

## 2. 트리거 위치

```
backend/app/services/matcher.py  (구현 시 02-coding-conventions.md 6장 구조에 맞춰 services/ 아래에 둠)
  ← Upbit 시세 스트림 핸들러(02-dashboard에서 구현하는 시세 캐시 갱신 지점)에서 호출
     심볼 X의 현재가 갱신 이벤트 수신
       → orders WHERE coin_symbol=X AND status='pending' AND order_type='limit' 조회
       → 종목당 체결 조건 충족 주문에 한해 3장 절차 수행
```

시장가 주문은 이 큐를 거치지 않는다 — `POST /api/orders` 처리 중 즉시 체결 절차(3장)를 그 자리에서 수행한다.

체결 엔진과 시장가 즉시 체결 모두 **현재가(ticker)만 사용**한다 — 호가(orderbook)는 화면 표시 전용이며 [00-overview.md](../00-overview.md) 3장 시세 구독 정책상 온디맨드로만 구독되므로 항상 값이 있다는 보장이 없다.

---

## 3. 체결 규칙

부분체결은 지원하지 않는다 (전량 1회 체결).

| 주문 | 체결 조건 | 체결가 |
|---|---|---|
| 매수 지정가 | 현재가 ≤ `orders.price` | `orders.price` |
| 매도 지정가 | 현재가 ≥ `orders.price` | `orders.price` |
| 시장가(매수/매도) | 즉시 | 주문 접수 시점 시세 캐시 현재가 |

### 3.1 중복 체결 방지

같은 주문이 여러 시세 이벤트에서 동시에 매칭되는 것을 막기 위해 조건부 갱신으로 선점한다.

```sql
UPDATE orders SET status='filled', filled_at=now()
WHERE id = $1 AND status='pending';
-- rowcount = 0이면 이미 처리된 주문이므로 후속 절차 스킵
```

이 선점이 막는 것은 **같은 주문**의 중복 체결뿐이다. 같은 유저의 **서로 다른 주문 두 건**이 동시에 체결되는 경합은 3.4절의 행 잠금이 막는다.

### 3.2 체결 후처리 순서 (트랜잭션 1개)

매도 체결 시 `realized_profit` 계산은 `holdings` 갱신 **이전** 시점의 `avg_buy_price`를 사용해야 한다 ([01-erd.md](../01-erd.md) 234행 규칙).

1. 위 조건부 `UPDATE`로 `orders` 행 선점 (`status`, `filled_at`, `price`, `fee` 확정 — 수수료 계산은 [01-erd.md](../01-erd.md) 3.2절 참조)
2. 해당 유저의 `balances` 행을 `SELECT ... FOR UPDATE`로 잠근다 (3.4절)
3. 매도 주문이면, 갱신 **직전** `holdings.avg_buy_price`로 `realized_profit` 산출 후 `orders.realized_profit`에 기록
4. `holdings` 갱신 (수량·평단 — 매수: 가중평균 재계산 / 매도: 수량 차감, 0이 되면 평단도 0으로 리셋)
5. `balances` 갱신 (매수: 차감 / 매도: 증액)
6. `orders.source='auto'`인 경우: `notifications` 테이블에 체결 이벤트 적재 + 해당 `strategy_slots.state.position` 갱신 ([01-erd.md](../01-erd.md) "strategy_slots.state 스키마" 절, [07-auto-trading.md](07-auto-trading.md) 참조)

**`state.position` 갱신은 이 체결 후처리 절차가 유일한 주체다.** 워커는 신호를 내고 주문을 요청할 뿐 `state.position`을 직접 쓰지 않는다 (워커가 직접 쓰는 것은 `state.last_evaluated_candle_at`, `state.grid.lines`의 라인 점유 표시, `state.dca.next_buy_at` 등 신호 판단용 상태뿐 — [07-auto-trading.md](07-auto-trading.md) 4장).

예외는 슬롯 ON 경로 하나다. OFF인 사이 수동 매도로 사라진 몫이 `state.position`에 남아 있으면 슬롯이 재진입도 청산도 못 하므로, ON 시점에 실제 `holdings.quantity`까지 낮춘다 ([07-auto-trading.md](07-auto-trading.md) 4.2절). 그 경로는 `balances` 행을 `FOR UPDATE`로 잡은 뒤에 쓰는데 모든 체결도 같은 행을 잠그므로(3.4절), 체결과 동시에 실행될 수 없다.

### 3.3 취소

`DELETE /api/orders/{id}` (03) 처리 시 `status='pending' → 'canceled'`로 전환. 체결 엔진과 동일한 조건부 `UPDATE`(`WHERE status='pending'`)로 매칭 경쟁을 방지한다 — 취소 요청과 체결 이벤트가 동시에 들어와도 둘 중 하나만 성공한다.

### 3.4 잠금 순서 규칙

`holdings`·`balances` 갱신은 "현재 값을 읽어 계산한 절대값을 쓰는" 방식이라, 같은 유저의 트랜잭션 두 개가 겹치면 먼저 커밋한 쪽의 증감이 통째로 사라진다(lost update). 그래서 자금을 건드리는 모든 경로는 **`balances` 행을 가장 먼저 잠근다**. 체결·수동주문·입출금·슬롯 ON이 모두 같은 행에서 직렬화되므로, `holdings`는 별도로 잠그지 않아도 함께 보호된다(쓰는 주체가 체결뿐이다). 없는 `holdings` 행은 `FOR UPDATE` 해도 잠기지 않아 동시 INSERT 경합을 막지 못한다는 점도 `balances`를 기준으로 삼는 이유다.

| 트랜잭션 | 잠금 순서 |
|---|---|
| 체결 (`fill_order`) | `orders`(선점) → `balances` → `holdings` → `strategy_slots` |
| 주문 생성 (`create_order`) | `balances` → `holdings`(매도만) → 시장가면 그대로 체결로 이어짐 |
| 입금·출금, 슬롯 ON | `balances` → (슬롯 ON은 `strategy_slots`) |
| 슬롯 삭제 (`delete_slot`) | `orders`·`notifications`(참조 해제) → `strategy_slots` |

슬롯 삭제가 참조를 **먼저** 끊는 이유: FK가 `ON DELETE SET NULL`이라 그냥 지우면 `strategy_slots` → `orders` 순서가 되는데, 체결은 정확히 반대(`orders` → `strategy_slots`)라 그 슬롯의 주문이 체결되는 순간 삭제가 들어오면 교착한다.

시장가 주문은 주문 행 `INSERT`와 체결을 **한 트랜잭션**에서 확정한다. 먼저 커밋하고 체결하면 체결 실패 시 `pending` 시장가 주문이 남는데, 매칭 대상은 지정가뿐이라(3장) 그 주문은 어떤 경로로도 체결되지 않고 가용 원화만 영구히 동결한다.

---

## 4. 관련 요구사항 매핑

이 문서는 신규 FR ID를 갖지 않으며, `03-manual-trading` FR-M07(미체결 관리)과 `07-auto-trading` FR-A07(자동매매 체결 내역)이 전제하는 체결 절차의 구현 근거 문서다.
