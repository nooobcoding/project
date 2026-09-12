# ERD — 코인 자동매매 프로그램

**상태**: 확정 (구현 시 이 문서를 스키마의 단일 기준으로 삼는다)
**연관 문서**: [00-overview.md](00-overview.md) 5장, `features/01~08.md`의 "데이터 모델" 절

이 문서는 `features/*.md`에 흩어져 있던 데이터 모델을 하나로 합치고, 테이블 간 FK·타입·제약을 확정한다. 기능 문서의 "데이터 모델" 절과 내용이 어긋나면 **이 문서가 우선**이다.

---

## 1. ERD

```mermaid
erDiagram
    USERS ||--|| BALANCES : "1:1"
    USERS ||--o| NOTIFICATION_SETTINGS : "1:1"
    USERS ||--o{ WATCHLISTS : "1:N"
    USERS ||--o{ ORDERS : "1:N"
    USERS ||--o{ HOLDINGS : "1:N"
    USERS ||--o{ DEPOSITS_WITHDRAWALS : "1:N"
    USERS ||--o{ NOTIFICATIONS : "1:N"
    USERS ||--o{ BACKTEST_RESULTS : "1:N"
    USERS ||--o{ STRATEGY_SLOTS : "1:N"

    COINS ||--o{ WATCHLISTS : "symbol"
    COINS ||--o{ ORDERS : "symbol"
    COINS ||--o{ HOLDINGS : "symbol"
    COINS ||--o{ STRATEGY_SLOTS : "symbol"
    COINS ||--o{ CANDLES : "symbol"
    COINS ||--o{ BACKTEST_RESULTS : "symbol"

    STRATEGY_SLOTS ||--o{ ORDERS : "nullable FK"
    STRATEGY_SLOTS ||--o{ NOTIFICATIONS : "nullable FK"
    BACKTEST_RESULTS ||--o{ BACKTEST_TRADES : "1:N"

    USERS {
        bigserial id PK
        varchar email UK
        varchar password_hash
        timestamptz created_at
    }
    BALANCES {
        bigint user_id PK_FK
        numeric_20_4 krw_balance
        timestamptz updated_at
    }
    COINS {
        varchar symbol PK
        varchar market_code
        varchar korean_name
        varchar english_name
        boolean is_active
        timestamptz updated_at
    }
    WATCHLISTS {
        bigserial id PK
        bigint user_id FK
        varchar coin_symbol FK
        smallint sort_order
    }
    ORDERS {
        bigserial id PK
        bigint user_id FK
        varchar coin_symbol FK
        varchar side
        varchar order_type
        numeric_20_8 price
        numeric_28_8 quantity
        varchar status
        varchar source
        bigint strategy_slot_id FK_nullable
        numeric_20_4 realized_profit_nullable
        numeric_20_4 fee
        timestamptz created_at
        timestamptz filled_at
    }
    HOLDINGS {
        bigint user_id PK_FK
        varchar coin_symbol PK_FK
        numeric_28_8 quantity
        numeric_20_8 avg_buy_price
    }
    DEPOSITS_WITHDRAWALS {
        bigserial id PK
        bigint user_id FK
        varchar type
        numeric_20_4 amount
        numeric_20_4 balance_after
        varchar memo_nullable
        timestamptz created_at
    }
    NOTIFICATION_SETTINGS {
        bigint user_id PK_FK
        boolean signal_enabled
        boolean exit_enabled
        boolean error_enabled
    }
    NOTIFICATIONS {
        bigserial id PK
        bigint user_id FK
        varchar type
        text message
        varchar coin_symbol_nullable FK
        bigint strategy_slot_id FK_nullable
        boolean is_read
        timestamptz created_at
    }
    BACKTEST_RESULTS {
        bigserial id PK
        bigint user_id FK
        varchar label
        varchar coin_symbol FK
        varchar strategy_type
        varchar indicator_nullable
        jsonb params
        date start_date
        date end_date
        numeric_20_4 initial_capital
        numeric_6_3 fee_rate
        numeric_6_3 slippage_rate
        numeric_10_4 total_return
        numeric_10_4 mdd
        numeric_6_3 win_rate
        numeric_10_4 sharpe_ratio
        int trade_count
        numeric_20_4 final_asset
        numeric_10_4 benchmark_return
        jsonb equity_curve
        timestamptz created_at
    }
    BACKTEST_TRADES {
        bigserial id PK
        bigint backtest_result_id FK
        varchar side
        numeric_20_8 price
        numeric_28_8 quantity
        numeric_20_4 profit_nullable
        timestamptz executed_at
    }
    STRATEGY_SLOTS {
        bigserial id PK
        bigint user_id FK
        varchar coin_symbol FK
        varchar strategy_type
        varchar indicator_nullable
        jsonb params
        numeric_20_4 invest_amount
        numeric_6_3 stop_loss_pct_nullable
        numeric_6_3 take_profit_pct_nullable
        jsonb state
        boolean is_active
        timestamptz created_at
    }
    CANDLES {
        bigserial id PK
        varchar coin_symbol FK
        varchar interval
        timestamptz opened_at
        numeric_20_8 open
        numeric_20_8 high
        numeric_20_8 low
        numeric_20_8 close
        numeric_28_8 volume
    }
```

---

## 2. 테이블 정의

### `users` — 계정 (`01-auth`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| email | VARCHAR(255) | UNIQUE, NOT NULL | |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

탈퇴(FR-S01) 시 아래 표 "삭제 정책"에 따라 하위 데이터가 함께 삭제된다.

### `balances` — 원화 잔고 (`01-auth`, `05-deposit-withdraw`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| user_id | BIGINT | PK, FK → users.id | |
| krw_balance | NUMERIC(20,4) | NOT NULL DEFAULT 10000000 | 가입 시 시드머니로 생성 |
| updated_at | TIMESTAMPTZ | NOT NULL | |

**가용 잔고는 별도 컬럼을 두지 않고 파생 계산한다** (3장 참조).

### `coins` — 코인 마스터 (신규, 전 기능 공용)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| symbol | VARCHAR(10) | PK | 예: `BTC` |
| market_code | VARCHAR(20) | NOT NULL | Upbit 마켓 코드, 예: `KRW-BTC` |
| korean_name | VARCHAR(50) | NOT NULL | |
| english_name | VARCHAR(50) | NOT NULL | |
| is_active | BOOLEAN | NOT NULL DEFAULT true | 상장폐지 시 false |
| updated_at | TIMESTAMPTZ | NOT NULL | Upbit 마켓 목록 동기화 시각 |

`watchlists`/`orders`/`holdings`/`strategy_slots`/`candles`/`backtest_results`의 `coin_symbol`이 모두 이 테이블을 참조해 심볼 오타·상장폐지 코인 참조를 방지한다.

### `watchlists` — 관심 코인 (`02-dashboard`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| coin_symbol | VARCHAR(10) | FK → coins.symbol | |
| sort_order | SMALLINT | NOT NULL | 탭 표시 순서 |

`UNIQUE (user_id, coin_symbol)`. 최대 5개 제약은 API 레벨에서 검사.

### `orders` — 매수/매도 체결 (`03-manual-trading`, `07-auto-trading`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| coin_symbol | VARCHAR(10) | FK → coins.symbol | |
| side | VARCHAR(4) | CHECK IN ('buy','sell') | |
| order_type | VARCHAR(8) | CHECK IN ('limit','market','reserved') | (신규) `reserved`(예약가) — 감시가격 도달 시 `limit`으로 승격만 되고 자체 체결 경로는 없음. 3.7절 참고 |
| price | NUMERIC(20,8) | NOT NULL | limit/reserved: 지정가(주문가격) / market: 체결가(체결 후 기록) |
| quantity | NUMERIC(28,8) | NOT NULL | |
| status | VARCHAR(8) | CHECK IN ('pending','filled','canceled') | |
| source | VARCHAR(6) | CHECK IN ('manual','auto') | |
| strategy_slot_id | BIGINT | FK → strategy_slots.id, NULL 허용 | auto 체결일 때만 값 존재. **(03 구현 시 실제 DB엔 이 컬럼을 아직 추가하지 않음** — `strategy_slots` 테이블이 없어 FK 대상이 없으므로. 07 구현 시 컬럼·FK·인덱스를 함께 추가한다. 그 전까지 이 표는 목표 스키마이며 실제 `orders` 테이블과 다르다) |
| realized_profit | NUMERIC(20,4) | NULL 허용 | (신규) `side='sell'`이 체결될 때, 체결 직전 `holdings.avg_buy_price` 기준 실현손익을 계산해 기록. 매수 행과 미체결 행은 NULL |
| fee | NUMERIC(20,4) | NOT NULL DEFAULT 0 | (신규) 체결 수수료(원화). pending 동안 0, 체결 시 확정. 계산 규칙은 3.2절 |
| trigger_price | NUMERIC(20,8) | NULL 허용 | (신규) 예약가 주문의 감시가격. `order_type='reserved'`가 아니면 항상 NULL |
| trigger_direction | VARCHAR(7) | CHECK IN ('rising','falling'), NULL 허용 | (신규) 주문 생성 시점의 현재가 대비 감시가격 위치로 1회 확정. 3.7절 참고 |
| created_at | TIMESTAMPTZ | NOT NULL | |
| filled_at | TIMESTAMPTZ | NULL | pending 동안 NULL |

인덱스: `(user_id, created_at DESC)`, `(user_id, status)`, `(user_id, source, created_at DESC)`, `(strategy_slot_id)`.

**`realized_profit`을 둔 이유**: `08-portfolio`의 "월별 수익"(FR-P04)은 매도 시점의 실현손익을 기간별로 합산해야 한다. 매도 체결 로직(03/07 공용)이 `holdings`를 갱신하기 직전 시점의 `avg_buy_price`로 `(체결가 × (1 − 수수료율) − avg_buy_price) × 수량`을 계산해 이 컬럼에 남긴다 (3.2절). `backtest_trades.profit`과 동일한 목적의 컬럼을 실거래 쪽에도 대칭으로 둔 것이다.

**`status` 전이 주체**: `pending → filled`/`canceled` 전환은 어느 화면 이벤트에서도 자동으로 일어나지 않으며, [09-execution-engine.md](features/09-execution-engine.md)의 체결 엔진(시세 스트림 훅)과 03의 취소 API가 유일한 실행 주체다.

**가용잔고 잠금은 `order_type` 무관**: 3.1절의 가용 원화/가용 코인 수량 파생식은 `status='pending'`인 모든 매수/매도 주문을 `order_type`과 상관없이 합산한다 — 예약가 주문도 생성 즉시 지정가와 동일하게 잔고를 동결한다(트리거 도달 전이라도).

### `holdings` — 보유 코인 (`03-manual-trading`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| user_id | BIGINT | PK, FK → users.id | |
| coin_symbol | VARCHAR(10) | PK, FK → coins.symbol | |
| quantity | NUMERIC(28,8) | NOT NULL DEFAULT 0 | |
| avg_buy_price | NUMERIC(20,8) | NOT NULL DEFAULT 0 | |

**전량 매도 시 처리**: 행을 삭제하지 않고 `quantity=0`, `avg_buy_price=0`으로 리셋해 유지한다 (재매수 시 이전 평단이 새 매수가에 섞여 오염되는 것을 방지).

### `deposits_withdrawals` — 가상 입출금 내역 (`05-deposit-withdraw`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| type | VARCHAR(8) | CHECK IN ('deposit','withdraw') | |
| amount | NUMERIC(20,4) | NOT NULL | |
| balance_after | NUMERIC(20,4) | NOT NULL | |
| memo | VARCHAR(30) | NULL | |
| created_at | TIMESTAMPTZ | NOT NULL | |

인덱스: `(user_id, created_at DESC)`.

### `notification_settings` — 알림 설정 (`04-settings`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| user_id | BIGINT | PK, FK → users.id | |
| signal_enabled | BOOLEAN | NOT NULL DEFAULT true | |
| exit_enabled | BOOLEAN | NOT NULL DEFAULT true | |
| error_enabled | BOOLEAN | NOT NULL DEFAULT true | (변경) 07의 "잔고 부족으로 매수 스킵" 알림이 `type=error`이므로 기본 OFF면 사용자가 자동매매 중단 사실을 놓친다 |

### `notifications` — 알림 (`04-settings`, `07-auto-trading`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| type | VARCHAR(8) | CHECK IN ('signal','exit','error') | |
| message | TEXT | NOT NULL | |
| coin_symbol | VARCHAR(10) | FK → coins.symbol, NULL 허용 | |
| strategy_slot_id | BIGINT | FK → strategy_slots.id, NULL 허용 | (신규) 어느 슬롯이 발생시켰는지 추적용 |
| is_read | BOOLEAN | NOT NULL DEFAULT false | GNB 배지 카운트 소스 |
| created_at | TIMESTAMPTZ | NOT NULL | |

인덱스: `(user_id, is_read)`.

### `backtest_results` — 백테스팅 결과 (`06-backtesting`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| label | VARCHAR(100) | NOT NULL | 사용자 지정 또는 자동 생성 |
| coin_symbol | VARCHAR(10) | FK → coins.symbol | |
| strategy_type | VARCHAR(20) | CHECK IN ('trend','counter_trend','grid','dca') | |
| indicator | VARCHAR(20) | CHECK IN ('ma','rsi','macd','bollinger'), NULL 허용 | grid/dca는 NULL |
| params | JSONB | NOT NULL | 지표별/그리드/DCA 파라미터 |
| start_date / end_date | DATE | NOT NULL | |
| initial_capital | NUMERIC(20,4) | NOT NULL | |
| fee_rate / slippage_rate | NUMERIC(6,3) | NOT NULL | % 단위 |
| total_return / mdd / benchmark_return | NUMERIC(10,4) | | % 단위 |
| win_rate | NUMERIC(6,3) | | % 단위 |
| sharpe_ratio | NUMERIC(10,4) | | |
| trade_count | INT | | |
| final_asset | NUMERIC(20,4) | | |
| equity_curve | JSONB | NOT NULL | `[{date, asset}]` 시계열 — 수익곡선 차트 렌더링용 |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `backtest_trades` — 백테스팅 체결 상세 (신규, `06-backtesting` FR-B07)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| backtest_result_id | BIGINT | FK → backtest_results.id | |
| side | VARCHAR(4) | CHECK IN ('buy','sell') | |
| price | NUMERIC(20,8) | NOT NULL | |
| quantity | NUMERIC(28,8) | NOT NULL | |
| profit | NUMERIC(20,4) | NULL | 매도 시점의 실현 손익, 매수 행은 NULL |
| executed_at | TIMESTAMPTZ | NOT NULL | |

수익 곡선의 매수/매도 마커 클릭 시 이 테이블에서 체결 상세(체결가/수량/수익)를 조회한다.

### `strategy_slots` — 자동매매 슬롯 (`07-auto-trading`)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| user_id | BIGINT | FK → users.id | |
| coin_symbol | VARCHAR(10) | FK → coins.symbol | |
| strategy_type | VARCHAR(20) | CHECK IN ('trend','counter_trend','grid','dca') | |
| indicator | VARCHAR(20) | NULL 허용 | grid/dca는 NULL |
| params | JSONB | NOT NULL | |
| invest_amount | NUMERIC(20,4) | NOT NULL | |
| stop_loss_pct | NUMERIC(6,3) | NULL 허용 | 전략유형별 의미 다름 (`features/07` 2.5절) |
| take_profit_pct | NUMERIC(6,3) | NULL 허용 | 〃 |
| state | JSONB | NOT NULL DEFAULT '{}' | (신규) 슬롯의 진행 상태 — 포지션·그리드 라인·DCA 진행상태. 스키마는 3.6절. 서버 재시작 후 워커가 이 값으로 이어서 실행 |
| is_active | BOOLEAN | NOT NULL DEFAULT false | |
| created_at | TIMESTAMPTZ | NOT NULL | |

**부분 유니크 인덱스** (코인당 활성 슬롯 1개 제약):

```sql
CREATE UNIQUE INDEX ux_strategy_slots_active_coin
  ON strategy_slots (user_id, coin_symbol)
  WHERE is_active;
```

### `candles` — OHLCV 캐시 (신규, `06-backtesting`, `03-manual-trading` 차트 조회 겸용)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| coin_symbol | VARCHAR(10) | FK → coins.symbol | |
| interval | VARCHAR(10) | CHECK IN ('1m','10m','30m','1h','1d') | |
| opened_at | TIMESTAMPTZ | NOT NULL | 봉 시작 시각 |
| open / high / low / close | NUMERIC(20,8) | NOT NULL | |
| volume | NUMERIC(28,8) | NOT NULL | |

`UNIQUE (coin_symbol, interval, opened_at)`. 인덱스: `(coin_symbol, interval, opened_at)`.

Upbit는 캔들 API를 1회 최대 200개로 제한하고 레이트리밋이 있어, 백테스팅 30초 목표(FR-B05)를 지키려면 최초 조회 시 DB에 캐싱하고 이후 요청은 캐시를 우선 사용한다. 캐시에 없는 최신 구간만 API로 보충한다.

---

## 3. 설계 규칙

### 3.1 가용 잔고 파생 계산 (컬럼 없음)

미체결 지정가 주문의 동결 잔고는 별도 컬럼(`locked_*`)을 두지 않고 항상 아래 식으로 계산한다. 주문 생성/취소마다 별도 테이블을 동기화할 필요가 없어 정합성이 깨질 여지가 없다.

**두 가지 잔고 개념을 구분한다** — 용도가 다르므로 하나로 합치면 07(자동매매 배정액)과 05(출금)가 서로의 존재를 모른 채 잔고를 초과 사용하는 경로가 생긴다.

```
가용 원화 (주문 검증용)
  = balances.krw_balance
    − SUM(price × quantity × (1 + TRADING_FEE_RATE))
      WHERE orders.side='buy' AND status='pending'      -- 수수료(3.2절)까지 동결

출금 가능액 (05 출금 검증 전용)
  = 가용 원화
    − SUM(invest_amount − 해당 슬롯이 이미 집행한 금액)
      WHERE strategy_slots.is_active = true              -- 활성 슬롯이 앞으로 쓸 배정액까지 제외

가용 코인 수량 = holdings.quantity
              − SUM(quantity) WHERE orders.side='sell' AND coin_symbol=X AND status='pending'
```

**사용처**: `03-manual-trading`의 잔고 표시·주문 검증, `07-auto-trading`의 슬롯 실행 시점 재검증 → **가용 원화**. `05-deposit-withdraw`의 출금 검증, `07-auto-trading`의 슬롯 활성화(ON) 시점 검증 → **출금 가능액**. `08-portfolio`의 요약 카드는 가용 원화 기준.

**동시성 주의**: 위 파생식은 조회 시점 값이라, "조회 → 검증 → INSERT/UPDATE" 사이에 틈이 있으면 동시에 들어온 두 요청이 서로의 동결분을 못 본 채 함께 통과해 잔고를 초과할 수 있다(TOCTOU). `services/orders.py`의 `create_order`는 검증 직전 `balances`(매수) 또는 `holdings`(매도) 행을 `SELECT ... FOR UPDATE`로 잠가 같은 유저의 동시 주문 생성을 직렬화한다 — 이 파생식을 새로 쓰는 05(출금 검증)·07(슬롯 활성화 검증)도 INSERT/UPDATE 직전에 동일하게 대상 행을 잠가야 한다.

### 3.2 체결 비용 규칙 (수수료)

상수 `TRADING_FEE_RATE = 0.0005`(0.05%) — 백테스팅 `fee_rate` 기본값과 동일 **요율**을 쓰되 저장 단위가 다르다.

**단위 규칙 (혼동 방지)**:
- 코드 상수 `TRADING_FEE_RATE = 0.0005` — **소수(비율) 단위**. 아래 매수/매도/실현손익 계산식은 이 소수를 그대로 곱한다.
- DB 컬럼 `backtest_results.fee_rate` / `slippage_rate` (`NUMERIC(6,3)`) — **% 단위**. 화면 입력값(예: `0.05`, `0.1`)을 그대로 저장한 것이므로 0.05%가 `0.050`으로 들어간다.
- 변환은 `06-backtesting`의 `costs.py` 진입점 한 곳에서만 한다: `rate_decimal = fee_rate_column / 100`. 내부 계산은 전부 소수 기준이며, 컬럼값을 소수인 것처럼 그대로 곱하면 **100배 오차**가 난다.

**실체결(수동·자동)에는 수수료만 적용하고 슬리피지는 적용하지 않는다** — 실체결은 실시세로 체결되므로 슬리피지를 더하면 이중 반영이 된다. 슬리피지는 백테스팅에서만 존재하는 비용 항목이며, 이 비대칭은 의도된 설계다 ([00-overview.md](00-overview.md) 6장).

- **매수** 체결: 원화 차감 = `price × quantity × (1 + TRADING_FEE_RATE)`. `holdings.avg_buy_price`는 이 수수료 포함 취득원가 단가로 가중평균한다.
- **매도** 체결: 원화 증가 = `price × quantity × (1 − TRADING_FEE_RATE)`.
- **실현손익**: `realized_profit = price × quantity × (1 − TRADING_FEE_RATE) − avg_buy_price × quantity`. 매수 수수료가 이미 `avg_buy_price`에 녹아 있으므로 이 한 줄로 왕복 수수료가 모두 반영된다.
- `06-backtesting`의 `runner.py`도 이 함수를 그대로 사용하고 슬리피지 항만 추가한다 ([06-backtesting.md](features/06-backtesting.md) 2.6절).

### 3.3 타입 컨벤션

| 대상 | 타입 |
|---|---|
| 금액(원화) | `NUMERIC(20,4)` |
| 코인 수량 | `NUMERIC(28,8)` |
| 코인 가격 | `NUMERIC(20,8)` |
| 비율(%) | `NUMERIC(6,3)` |
| 시각 | `TIMESTAMPTZ` — UTC로 저장, 화면 표시 시 KST 변환 |

부동소수점(`float`/`double`)은 금액·수량·가격에 사용하지 않는다.

### 3.4 삭제 정책

| 이벤트 | 처리 |
|---|---|
| 회원 탈퇴 (`04-settings`) | `users` 행 삭제, 하위 전 테이블 `ON DELETE CASCADE`로 함께 삭제 (하드 삭제) |
| 모의투자 초기화 (`08-portfolio`) | 처리 순서: ① 활성(`is_active=true`) `strategy_slots`를 전부 `is_active=false`로 전환하고 `state`를 `{}`로 리셋 (진행 중이던 그리드/DCA 상태가 초기화된 `holdings`와 어긋나는 것을 방지) → ② `orders` / `holdings` / `deposits_withdrawals` 삭제 → ③ `balances`를 초기 시드머니 값으로 리셋. `users` / `backtest_results`, 그리고 `strategy_slots` 행 자체(설정값)는 보존 — 비활성화만 될 뿐 삭제되지 않는다 |

### 3.5 인덱스 요약

- `orders (user_id, created_at DESC)`
- `orders (user_id, status)`
- `orders (user_id, source, created_at DESC)` — (신규) 07 체결내역·08 거래내역 필터용
- `orders (strategy_slot_id)` — (신규) 슬롯별 체결 조회용
- `notifications (user_id, is_read)`
- `candles (coin_symbol, interval, opened_at)` — UNIQUE
- `deposits_withdrawals (user_id, created_at DESC)`
- `strategy_slots (user_id, coin_symbol) WHERE is_active` — UNIQUE, 코인당 활성 1개 제약 (2장 `strategy_slots` 정의 참조)

### 3.6 `strategy_slots.state` 스키마

자동매매 슬롯은 **자신이 직접 매수한 몫만** 청산 대상으로 관리한다 (사용자가 같은 코인을 수동으로 보유하고 있어도 그 물량은 건드리지 않는다). 이를 위해 `state` JSONB의 구조를 아래로 고정한다.

```jsonc
{
  "position": {                  // 전 전략유형 공통 — 슬롯이 매수해 보유 중인 몫
    "quantity": "0.0125",        // 누적 보유 수량 (문자열 Decimal)
    "avg_price": "95000000",     // 수수료 포함 취득원가 단가
    "entry_at": "2026-09-08T04:00:00Z"
  },
  "last_evaluated_candle_at": "2026-09-08T04:00:00Z",  // 확정봉 중복 평가 방지 (07 4장)
  "grid": { "lines": [{ "price": "...", "filled": true, "quantity": "..." }] },  // strategy_type='grid'일 때만
  "dca":  { "executed_count": 3, "next_buy_at": "...", "last_buy_price": "...", "spent_amount": "..." }  // strategy_type='dca'일 때만
}
```

- `grid`/`dca` 키는 해당 `strategy_type`일 때만 존재한다.
- 모든 수치는 부동소수점 오차 방지를 위해 문자열로 저장한다 (3.3절 타입 컨벤션과 동일 취지).
- 청산(손절·익절·그리드 이탈) 시 매도 수량은 `min(state.position.quantity, holdings.quantity)`로 상한을 건다 — 상세 규칙은 [07-auto-trading.md](features/07-auto-trading.md).
- 슬롯 OFF 시 `state.position`은 유지한다 (재ON 시 이어서 관리). 모의투자 초기화 시에만 `{}`로 리셋한다 (3.4절).

### 3.7 예약가 주문 (`order_type='reserved'`)

업비트의 "예약가 주문"과 동일한 스탑 주문이다. 감시가격(`trigger_price`)에 현재가가 도달하면 주문가격(`price`)으로 지정가 주문이 자동 생성되는 방식 — 새 체결 경로를 만들지 않고 **기존 지정가 체결 인프라를 그대로 재사용**한다.

1. 주문 생성 시점의 현재가와 감시가격을 비교해 `trigger_direction`을 1회 확정한다 — 감시가격이 현재가보다 높으면 `rising`(상승 돌파 대기), 낮으면 `falling`(하락 대기). 같으면 방향이 모호하므로 생성 자체를 거부한다. 이후 이 값을 그대로 쓰며 재계산하지 않는다.
2. [09-execution-engine.md](features/09-execution-engine.md)의 체결 엔진이 매 시세 틱마다, 기존 지정가 매칭보다 먼저 예약가 주문을 검사한다: `rising`이면 현재가≥감시가격, `falling`이면 현재가≤감시가격일 때 조건 충족.
3. 조건 충족 시 조건부 `UPDATE orders SET order_type='limit' WHERE id=... AND status='pending' AND order_type='reserved'`로 **`limit`으로 승격만** 시킨다 (체결 아님, 취소 요청과의 경쟁은 이 조건부 UPDATE로 방지). 승격 직후 같은 틱에서 기존 지정가 매칭이 이어서 실행되므로, 주문가격 조건까지 이미 만족하면 같은 틱에 체결까지 이어질 수 있다.
4. 체결된 뒤에도 `order_type`은 `limit`으로 남고 `trigger_price`/`trigger_direction`은 이력으로 보존된다.

---

## 4. 화면 ↔ 테이블 매핑

| 기능 문서 | 화면 ID | 주로 사용하는 테이블 |
|---|---|---|
| 01-auth | SCR-01 | `users`, `balances` |
| 02-dashboard | SCR-02 | `balances`, `holdings`, `watchlists`, `orders`(최근 5건), `strategy_slots`(상태 카드) |
| 03-manual-trading | SCR-03 | `coins`, `candles`, `orders`, `holdings`, `balances`, `strategy_slots`(잠금 여부) |
| 04-settings | SCR-08 | `users`, `notification_settings`, `notifications` |
| 05-deposit-withdraw | SCR-07 | `balances`, `deposits_withdrawals` |
| 06-backtesting | SCR-05 | `candles`, `backtest_results`, `backtest_trades`, `coins` |
| 07-auto-trading | SCR-04 | `strategy_slots`, `orders`, `notifications`, `candles` |
| 08-portfolio | SCR-06 | `orders`, `holdings`, `balances`, `deposits_withdrawals` |
| 09-execution-engine | 없음(인프라) | `orders`, `holdings`, `balances`, `notifications`, `strategy_slots` |
