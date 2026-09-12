# 확장판 01 — 기존 자산 대조표

**상태**: 설계 초안
**목적**: 기존 `docs/` 13개 문서와 현재 코드 중 **무엇이 그대로 살고, 무엇이 바뀌고, 무엇이 폐기되는가**를 한 장에 정리한다. 확장판에 착수할 때 "어디서부터 다시 읽어야 하나"의 답이 여기 있다.

---

## 1. 한 줄 요약

> **도메인 로직과 데이터 계층은 100% 재사용된다. 바뀌는 축은 "프로세스 토폴로지 + 시세 캐시 공유" 하나뿐이다.**

문서 기준으로 13개 중 **7개가 무수정**, 5개가 부분 수정, **1개만 큰 수정**이다. 폐기되는 문서는 없다.

> 초안에서는 큰 수정이 2개였다. 백테스트 잡 큐를 임계 경로에서 빼면서([04](04-async-jobs.md) 2장) `06-backtesting.md`가 부분 수정으로 내려왔고, **프론트엔드 변경이 통째로 사라졌다.**

---

## 2. 문서 대조표

### 2.1 그대로 유효 — 손대지 않는다 (7개)

| 문서 | 왜 그대로인가 |
|---|---|
| [`docs/02-coding-conventions.md`](../docs/02-coding-conventions.md) | 명명·주석·BCE 계층·커밋 규칙은 프로세스 수와 무관. **6장 프로젝트 구조에만 프로세스 엔트리포인트가 추가**되는데, 그건 [00-architecture](00-architecture.md) 2.1절이 대신 정의한다 |
| [`docs/features/02-dashboard.md`](../docs/features/02-dashboard.md) | 화면·API 계약 동일. 시세를 어디서 읽는지만 바뀌는데 `get_cached_price()` 시그니처를 유지하므로 이 문서가 기술하는 범위는 무변경 |
| [`docs/features/03-manual-trading.md`](../docs/features/03-manual-trading.md) | 주문 생성·검증·취소·FR-M10 잠금 전부 동일. 체결 경로가 다른 프로세스로 옮겨가지만 계약은 같다 |
| [`docs/features/04-settings.md`](../docs/features/04-settings.md) | 계정·알림 설정. 영향 없음 |
| [`docs/features/05-deposit-withdraw.md`](../docs/features/05-deposit-withdraw.md) | 입출금. `balances` 행 잠금 규칙을 이미 따르므로 분산에서도 그대로 안전 |
| [`docs/features/08-portfolio.md`](../docs/features/08-portfolio.md) | 집계·CSV. 읽기 전용이라 영향 없음 |
| [`docs/features/06-backtesting-plan.md`](../docs/features/06-backtesting-plan.md) | Phase A~E 구현 계획서 — 이미 완료된 작업의 기록이다. 확장판은 그 결과물(`strategy_engine/`)을 그대로 쓴다 |

### 2.2 부분 수정 (4개)

| 문서 | 그대로인 부분 | 바뀌는 부분 | 대체 문서 |
|---|---|---|---|
| [`docs/00-overview.md`](../docs/00-overview.md) | 1·2·4·5·6장 (프로젝트 성격, 화면 인벤토리, 데이터 모델 개요, **공통 원칙 7개 전부**) | **3장 아키텍처 다이어그램**, 7장 로드맵 | [00-architecture](00-architecture.md), [07-roadmap](07-roadmap.md) |
| [`docs/01-erd.md`](../docs/01-erd.md) | **2장 테이블 정의 13개 전부**, 3.1~3.7절 설계 규칙 **전부** | 테이블 3개 추가 + `users` 컬럼 2개 추가 | 아래 3장 |
| [`docs/features/01-auth.md`](../docs/features/01-auth.md) | 가입·로그인·JWT·시드머니 | 권한(`role`)·계정 상태(`status`) 추가 | [05-admin](05-admin.md) 2장 |
| [`docs/features/09-execution-engine.md`](../docs/features/09-execution-engine.md) | **3.1 중복 체결 방지, 3.2 후처리 순서, 3.3 취소, 3.4 잠금 순서 규칙 — 전부 그대로** | 2장 트리거 위치(시세 루프 안 → 별도 matcher 프로세스) | [02-market-data](02-market-data.md) 4장 |
| [`docs/features/06-backtesting.md`](../docs/features/06-backtesting.md) | **2장 전략 규칙 전부**(지표·그리드·DCA·손절익절·`invest_amount` 의미), 2.6 엔진 구조, 2.7 비대칭, 3장 성과지표, 5장 데이터 모델, **6장 API 계약** | 4장 타임아웃 60초에 **세마포어 대기 시간이 포함**된다는 단서만 추가 | [04-async-jobs](04-async-jobs.md) 2장 |

> **09가 거의 그대로라는 점이 이 확장의 핵심 근거다.** 3.4절 잠금 순서 표(`orders`→`balances`→`holdings`→`strategy_slots`)는 프로세스가 몇 개든 PostgreSQL이 강제하므로 분산 환경에서 **수정 없이 그대로 맞다**. 지난 세션에 커밋 `81cad9b`로 잡은 lost update·교착 수정이 확장판에서도 그대로 유효하다는 뜻이다.

### 2.3 큰 수정 (1개)

| 문서 | 그대로인 부분 | 바뀌는 부분 | 대체 문서 |
|---|---|---|---|
| [`docs/features/07-auto-trading.md`](../docs/features/07-auto-trading.md) | 1·2·3장(슬롯 구조·잔고 검증·화면), 4.1 시장가 원칙, **4.2 청산과 포지션 경계**, 5장 FR-M10 잠금, 6~9장 | **4장 워커 실행 구조** — 단일 tick 순회에서 샤드 기반 분산으로 | [03-worker-orchestration](03-worker-orchestration.md) |

---

## 3. 스키마 델타

[`docs/01-erd.md`](../docs/01-erd.md) 2장의 **기존 13개 테이블은 컬럼 하나도 바뀌지 않는다.** 추가만 있다.

### 3.1 `users` 컬럼 추가

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `role` | VARCHAR(10) | NOT NULL DEFAULT `'user'`, CHECK IN ('user','admin') | 관리자 권한 |
| `status` | VARCHAR(10) | NOT NULL DEFAULT `'active'`, CHECK IN ('active','suspended') | 정지 계정은 로그인·API 호출 차단 |

### 3.2 신규 테이블 2개

| 테이블 | 용도 | 정의 위치 |
|---|---|---|
| `worker_heartbeats` | 샤드별 tick 소요·슬롯 수·커넥션 사용량 관측 | [06-observability](06-observability.md) 2장 |
| `audit_logs` | 관리자 행위 감사 | [05-admin](05-admin.md) 4장 |

> `backtest_jobs`는 초안에 있었으나 잡 큐를 빼면서 함께 사라졌다 ([04](04-async-jobs.md) 2.3절).

### 3.3 스키마 변경 규칙은 그대로

[`docs/00-overview.md`](../docs/00-overview.md) 8장의 **"스키마 변경은 항상 `01-erd.md`를 먼저 고친다"** 규칙은 확장판에도 적용된다. 위 델타는 실제 착수 시 확장판 ERD에 반영한 뒤 코드를 쓴다.

---

## 4. 코드 대조표

| 모듈 | 판정 | 비고 |
|---|---|---|
| `app/strategy_engine/` — `indicators` `signals` `intents` `grid` `dca` `exits` `costs` `runner` `metrics` `backtest` | **무수정** | 전부 순수 함수. 확장과 무관 |
| `app/strategy_engine/worker.py` | **재작성** | 슬롯 순회 → 샤드 순회. 슬롯 1개 처리 로직(`process_slot` 이하)은 대부분 유지. **샤드 점유 시 그리드·DCA 재조정 신설** ([03](03-worker-orchestration.md) 2.4절) |
| `app/models/` 12개 | **무수정** (+3개 추가) | |
| `app/services/matcher.py` | **거의 무수정** | `fill_order` 이하 체결 절차는 그대로. 진입점(`run_matching_for_symbol`)의 호출 주체만 바뀜 |
| `app/services/orders.py` | **무수정** | `create_order` 잠금 순서가 이미 올바름 |
| `app/services/slot_state.py` | **무수정 — 그리고 이게 결정적이다** | `jsonb_set`으로 자기 키만 갱신하는 설계는 원래 "행 잠금 없이 경합을 막기 위한" 것이었는데, 프로세스가 갈라지면 **그 설계가 있어야만 동작한다**. 이미 분산 대비가 되어 있는 셈 |
| `app/services/wallet.py` `dashboard.py` `portfolio.py` | **무수정** | |
| `app/services/strategy_slots.py` | **무수정 — 참고 대상** | `_reconcile_phantom_position`이 [03](03-worker-orchestration.md) 2.4절 그리드 재조정의 원형이다. 새로 만들지 말고 이 모양을 따를 것 |
| `app/services/price_stream.py` | **분할** | 구독부 → `market-data` 역할 / 캐시 읽기부 → Redis 어댑터 (`get_cached_price` 시그니처 유지) |
| `app/services/candles.py` | **부분 수정** | Upbit 호출부를 `scheduler` 역할로 이관. 조회 함수는 DB 캐시만 읽도록 |
| `app/services/backtest.py` | **거의 무수정** | 세마포어 한 줄 추가. API 계약·실행 방식 그대로 ([04](04-async-jobs.md) 2.2절) |
| `app/database.py` | **수정** | 역할별 풀 크기 설정 + 리더·샤드 점유용 전용 커넥션 확보 ([00](00-architecture.md) 3.5절) |
| `app/main.py` | **재작성** | `lifespan`에서 역할별 기동으로 |
| `frontend/` 전체 | **무수정 (+관리자 화면)** | 잡 큐를 빼면서 폴링 전환이 사라졌다. 기존 화면은 한 줄도 안 바뀐다 |
| `backend/tests/` 전체(테스트 함수 257개) | **그대로 회귀 게이트로 사용** | 도메인 로직이 안 바뀌므로 전부 통과해야 한다. **하나라도 깨지면 그건 확장이 아니라 변경이라는 신호다** |

---

## 5. 원본 `docs/`의 알려진 갭 — 확장판에서 메운다

2026-09-12 감사에서 나온 것들이다. 확장판 착수 시 함께 처리한다.

| 갭 | 처리 |
|---|---|
| **`services/slot_state.py`의 `jsonb_set` 설계가 어느 문서에도 없다** (코드 헤더에만 존재) | [03-worker-orchestration](03-worker-orchestration.md) 4장에 정식 기술. 분산에서는 이게 없으면 즉시 깨지므로 더 이상 코드 주석에만 둘 수 없다 |
| 07 4장 워커 런타임 규칙 미문서화 (tick 내 순서, `claim_candle` 선점 커밋, DCA 별도 경로, matcher 훅에서 `get_or_create_settings` 금지) | [03-worker-orchestration](03-worker-orchestration.md) 3장에 기술 |
| DCA `params` 키 이름(`buy_period`) 미확정 — RSI `period`와 충돌해 갈랐던 결정이 문서에 없음 | 확장판 착수 시 원본 `docs/features/06-backtesting.md` 2.4절에 **직접 반영**(확장판 고유 사항이 아니라 원본의 누락이므로) |
| 미해결 findings 3건이 문서에 없음 (워커 다중 intent 부분 실패 / 체결 후처리 2트랜잭션 분리 / 수수료 정밀도) | [03-worker-orchestration](03-worker-orchestration.md) 6장 "승계되는 알려진 한계"에 명시. 2번은 분산에서 악화되므로 **[03](03-worker-orchestration.md) 2.4절 샤드 점유 시 재조정으로 해결**한다 |
| 원본 문서 11개 중 7개의 상태 표기가 낡음 | 확장판과 무관한 원본 정비 — 별도로 처리 |

---

## 6. 되돌아갈 지점

확장판 작업이 잘 안 됐을 때 돌아올 기준선을 명시해둔다.

- **기준 커밋**: `c2e1249` (main, 2026-09-12 시점 — 로드맵 0~8 전부 완료, 기존 pytest 스위트 전부 통과)
- **되돌리는 법**: [00-architecture](00-architecture.md) 2.1절의 `PROCESS_ROLES`에 전 역할을 켜면 단일 프로세스 동작으로 복귀한다. 각 로드맵 단계는 이 성질을 유지하도록 설계했다 ([07-roadmap](07-roadmap.md)).
- **판정 기준**: `backend/tests/` 전체(테스트 함수 257개)가 전부 통과하는가. 도메인 로직을 안 건드리는 확장이므로 이게 깨지면 설계가 새는 것이다.
