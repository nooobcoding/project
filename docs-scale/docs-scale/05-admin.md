# 확장판 05 — 관리자 기능

**상태**: 구현 완료 (2026-10-05) — 초안과 달라진 결정은 7장
**화면 ID**: SCR-09 (신규)
**원본 대비**: [`docs/features/01-auth.md`](../docs/features/01-auth.md)에 권한·계정 상태를 추가한다. 그 외 기존 문서는 무변경.

---

## 1. 범위

다중 사용자를 실제로 운영하려면 "누가 무엇을 하고 있는지 보고, 문제가 생긴 계정을 멈출 수 있어야" 한다. 그 최소 집합만 다룬다.

| 넣는다 | 넣지 않는다 |
|---|---|
| 유저 목록·상세 조회 | 유저 대신 로그인(impersonation) |
| 계정 정지·해제 | 비밀번호 강제 변경 |
| 슬롯 강제 OFF | 관리자가 대신 주문 내기 |
| 시스템 지표 대시보드 ([06](06-observability.md)) | 요금·과금 |
| 관리자 행위 감사 로그 | 다단계 권한(운영자/CS/개발자 분리) |

**모의투자 초기화**는 [`docs/01-erd.md`](../docs/01-erd.md) 3.4절이 "추후 관리자 기능으로 다시 설계할 때 확정한다"고 남겨둔 항목이다. 여기서도 **보류**한다 — 자금·주문·슬롯·보유를 한꺼번에 지우는 작업이라 3장의 잠금 규칙을 가장 어렵게 만드는 기능이고, 관리자 기능의 핵심 가치와도 거리가 있다.

---

## 2. 권한 모델

### 2.1 스키마

[`docs/01-erd.md`](../docs/01-erd.md) 2장 `users` 테이블에 컬럼 2개 추가 ([01-carryover-map](01-carryover-map.md) 3.1절).

- `role` — `'user'` | `'admin'`
- `status` — `'active'` | `'suspended'`

**첫 관리자는 마이그레이션이나 CLI로 지정한다.** 화면에서 자기 자신을 관리자로 승격하는 경로는 두지 않는다.

### 2.2 인증 의존성

현재 `get_current_user`는 이미 JWT를 검증한 뒤 **DB에서 User를 읽는다**([`backend/app/services/auth.py:94`](../backend/app/services/auth.py#L94)). 그래서 계정 상태 확인이 추가 쿼리 없이 공짜다.

```python
def get_current_user(...) -> User:
    ...  # 기존 JWT 검증
    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if user.status == "suspended":          # 추가
        raise HTTPException(403, "정지된 계정입니다.")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:   # 신규
    if user.role != "admin":
        raise HTTPException(403, "권한이 없습니다.")
    return user
```

**이 위치가 중요하다.** JWT는 만료 24시간에 무효화 수단이 없으므로([`docs/features/01-auth.md`](../docs/features/01-auth.md) 8장), 토큰만 검사하면 정지된 계정이 하루 동안 계속 API를 쓴다. DB의 `status`를 매 요청 확인하는 방식이라 **정지가 즉시 발효**된다.

### 2.3 프론트

`AdminRoute` 가드를 `ProtectedRoute`와 같은 방식으로 하나 추가하고 `/admin` 이하를 감싼다 ([`frontend/src/App.tsx`](../frontend/src/App.tsx)). GNB에 관리자 메뉴는 `role === 'admin'`일 때만 노출한다.

> 프론트 가드는 편의일 뿐 보안 경계가 아니다. **모든 관리자 API는 서버에서 `require_admin`으로 다시 검사한다.**

---

## 3. 기능

### 3-A. 유저 목록 / 상세

| 항목 | 내용 |
|---|---|
| 목록 | 이메일, 가입일, 상태, 활성 슬롯 수, 원화 잔고, 총 평가금액 |
| 정렬·필터 | 가입일, 상태, 활성 슬롯 보유 여부 |
| 상세 | 잔고·보유코인·활성 슬롯·최근 주문·최근 입출금 |

전부 읽기 전용이고 기존 서비스 함수(`dashboard`, `portfolio`, `strategy_slots`)를 **user_id를 인자로 받도록** 재사용한다. 현재 이 함수들은 `current_user`에서 id를 받으므로, 시그니처가 이미 `user_id`를 받는 형태면 그대로 쓸 수 있다.

> **손익 재구성 주의**: 관리자 통계에서 수수료 합계를 낼 때 `orders.fee` 합을 쓰면 안 된다. 저장값은 4자리 quantize이고 실제 차감은 무반올림 계산식이라 미세하게 다르다 ([03](03-worker-orchestration.md) 6장). 계산식을 쓸 것.

### 3-B. 계정 정지 / 해제

- `PATCH /api/admin/users/{id}/status` — `active` ↔ `suspended`
- 정지 시 **그 유저의 활성 슬롯을 전부 OFF 처리한다.** 안 하면 로그인은 막혔는데 워커는 계속 그 유저의 돈으로 매매한다.
- 정지 해제는 슬롯을 자동으로 되켜지 않는다 (사용자가 직접 켜야 한다).

### 3-C. 슬롯 강제 OFF

- `POST /api/admin/strategy-slots/{id}/deactivate`
- 기존 `strategy_slots.toggle_slot`의 OFF 경로를 그대로 재사용한다. **관리자 전용 경로를 새로 만들지 않는다** — 잔고 검증·`state` 처리 규칙이 갈라지면 그때부터 버그가 난다.

### 3-D. 시스템 대시보드

[06-observability](06-observability.md)가 정의하는 지표를 보여준다. 샤드별 tick 소요, 활성 슬롯 수, Upbit 토큰 잔량, 프로세스별 커넥션 사용량, 최근 오류.

**가장 위에 둘 것은 샤드 커버리지다** ([06](06-observability.md) 3.4절). 나머지는 "느린가"를 보지만 이건 "아예 멈췄는가"를 본다 — 미점유 샤드가 있으면 그 유저들의 자동매매가 통째로 서 있는 상태이므로, 표 안에 섞지 말고 눈에 띄게 노출한다.

---

## 4. 자금을 건드리는 기능의 규칙

관리자 기능 중 **조회는 쉽고 쓰기는 어렵다.** 쓰기 경로는 다음을 반드시 지킨다.

1. **[`docs/features/09-execution-engine.md`](../docs/features/09-execution-engine.md) 3.4절 잠금 순서를 따른다** — `balances` 행을 가장 먼저 `FOR UPDATE`. 관리자 API라고 예외가 아니다. 체결·워커와 같은 DB를 같은 시각에 건드린다.
2. **기존 서비스 함수를 재사용한다.** 관리자용 별도 경로를 파면 검증 규칙이 갈라진다.
3. **감사 로그를 남긴다** (아래).

### `audit_logs` 테이블

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | |
| actor_user_id | BIGINT FK → users.id | 행위한 관리자 |
| action | VARCHAR(40) | `user.suspend`, `slot.deactivate` 등 |
| target_type / target_id | VARCHAR(20) / BIGINT | 대상 |
| detail | JSONB NULL | 변경 전후 값 |
| created_at | TIMESTAMPTZ | |

인덱스: `(created_at DESC)`, `(actor_user_id, created_at DESC)`.

**감사 로그는 대상 유저가 탈퇴해도 남아야 한다.** `target_id`는 FK로 걸지 않는다 (`actor_user_id`만 FK).

---

## 5. 오류 처리

| 상황 | 메시지 |
|---|---|
| 권한 없음 | 권한이 없습니다. |
| 정지된 계정으로 API 호출 | 정지된 계정입니다. 관리자에게 문의해주세요. |
| 자기 자신을 정지 시도 | 본인 계정은 정지할 수 없습니다. |
| 마지막 관리자의 권한 회수 시도 | 관리자가 최소 1명은 있어야 합니다. |

---

## 6. 검증 방법

1. 일반 유저 토큰으로 `/api/admin/*` 전부 403인지
2. 정지 처리 후 **기존 토큰으로** API 호출이 즉시 403인지 (토큰 만료를 기다리지 않는지)
3. 정지 시 활성 슬롯이 실제로 OFF되고 워커가 더 이상 그 슬롯을 평가하지 않는지
4. 강제 OFF가 일반 OFF와 동일한 `state` 처리를 하는지 (포지션 유지)
5. 감사 로그가 남고, 대상 유저 탈퇴 후에도 조회되는지

---

## 7. 구현하면서 바뀐 결정

초안을 코드와 맞춰 보면서 빈 곳을 채웠다. 각 항목은 테스트로 고정돼 있다.

| # | 초안 | 구현 | 이유 |
|---|---|---|---|
| 1 | 정지 시 슬롯만 OFF | **미체결 주문(지정가·예약가)도 전부 취소** | 그대로 두면 정지된 유저는 자기 주문을 취소할 수 없는데 matcher는 계속 체결한다 |
| 2 | 본인만 정지 불가 | **관리자 계정은 화면에서 정지 불가** | 관리자끼리 서로 잠그는 사고 차단. 관리자를 멈추려면 먼저 CLI로 권한을 회수한다 |
| 3 | `get_current_user`만 차단 | **로그인도 거부** (비밀번호가 맞았을 때만 정지 사실을 알린다) | 그대로면 토큰은 발급되는데 모든 API가 403이다. 틀린 비밀번호에 알려주면 계정 상태를 떠볼 수 있다 |
| 4 | `actor_user_id` FK | **`ON DELETE SET NULL` + `actor_email` 스냅샷** | 그냥 FK면 관리자 탈퇴 시 감사 기록이 같이 지워지거나(CASCADE) 탈퇴가 막힌다(RESTRICT) |
| 5 | — | **`GET /api/account`에 `role` 추가** | 프론트가 관리자 메뉴 노출 여부를 알 방법이 없었다 |
| 6 | 마지막 관리자 권한 회수만 차단 | **마지막 관리자의 탈퇴도 차단** | 탈퇴는 권한 회수와 결과가 같다. 두 경로가 `ensure_not_last_admin`을 공유한다 |

### 7.1 정지는 트랜잭션 두 개다

4장 1번("`balances`를 가장 먼저 잠근다")을 한 트랜잭션에 그대로 적용하면 **체결과 교착한다.** 체결은 `orders`(조건부 UPDATE로 선점) → `balances` 순서인데, 정지가 `balances`를 쥔 채 그 주문을 취소하려 하면 서로를 기다린다. 테스트가 이 순간을 재현하고, 한 트랜잭션 버전은 PostgreSQL `DeadlockDetected`로 실패한다.

1. `balances` → `users` → `strategy_slots` 잠금, status·슬롯 OFF·감사 로그 커밋
2. 사용자 취소와 같은 `cancel_pending_in_session`으로 남은 주문 취소 — `balances`를 잡지 않아 체결과는 경합만 한다(둘 중 하나만 성공)

2단계가 실패해도 1단계는 유지되고, 같은 요청을 다시 보내면 남은 주문을 마저 치운다.

**정지 직전에 출발한 주문**: `create_order`가 `balances` 잠금 **뒤에** status를 다시 본다. 정지 1단계가 같은 행을 잡으므로, 인증을 정지 전에 통과한 HTTP 요청이나 정지 전 스냅샷으로 도는 워커 tick도 정지 커밋 뒤에는 주문을 내지 못한다. 워커는 이를 오류가 아니라 스킵(`suspended`)으로 기록한다.

### 7.2 시스템 대시보드의 heartbeat는 (역할, 샤드)마다 최신 행만

`worker_heartbeats`는 지우는 주체가 없어 재기동마다 새 `process_id`로 행이 쌓인다(개발 DB에서 3주에 2,189행, 현역 17행). 시간 창으로 거르면 **락을 쥔 채 멈춘 프로세스가 창 밖으로 밀려나** 가장 보여야 할 행이 사라진다. 최신 행 기준이면 죽은 프로세스는 샤드를 넘겨받은 새 프로세스에 가려지고, 멈춘 프로세스는 락을 놓지 않아 계속 최신으로 남아 stale로 보인다.

오래된 행 자체를 정리하는 잡은 아직 없다. 증가 속도가 느려 당장 문제는 아니지만, 운영 기간이 길어지면 `updated_at` 기준 정리를 scheduler에 붙일 것.

### 7.3 권한 검사는 라우터 단위

`/api/admin` 라우터에 `dependencies=[Depends(require_admin)]`를 건다. 엔드포인트마다 붙이면 하나를 빠뜨리는 순간 열린다. 테스트는 OpenAPI 스키마에서 `/api/admin` 경로를 전부 훑어 일반 유저 403·무토큰 401을 확인하므로, 나중에 추가되는 엔드포인트도 자동으로 검사된다.
