# 02. 코딩 컨벤션

**상태**: 확정
**연관 문서**: [00-overview.md](00-overview.md) 2장(기술 스택), [01-erd.md](01-erd.md)(명명 규칙의 단일 기준 — 테이블·컬럼명)

이 문서는 팀 공용 코딩 컨벤션(수업 참고자료: 작명·연산자·들여쓰기·띄워쓰기·주석 5개 항목)을 이 프로젝트의 실제 스택 — 백엔드 Python(FastAPI), 프론트 React+TypeScript, DB PostgreSQL — 에 맞게 확장한 것이다.

**자동 포맷터/린터를 도입하지 않는다.** 규칙은 이 문서로만 명문화하고, 각자 작성·PR 리뷰 시 육안으로 확인한다. 도구가 없는 만큼 아래 규칙, 특히 1.2(연산자 공백)·1.3(들여쓰기)은 스스로 챙겨야 한다.

---

## 1. 작명 (Naming)

**공통 원칙**: 이름만으로 역할을 유추할 수 있게 짓는다. 축약어 남용 금지(`qty`보다 `quantity`) — 단 `avg_buy_price`처럼 [01-erd.md](01-erd.md)에 이미 쓰인 축약은 그대로 따라 스키마와 코드의 이름이 어긋나지 않게 한다.

| 대상 | Python | TypeScript/React | SQL |
|---|---|---|---|
| 클래스 | `PascalCase` (예: `StrategySlot`) | `PascalCase` (예: `OrderBookRow`) | — |
| 함수/메서드 | `snake_case`, 동사로 시작 (예: `calculate_realized_profit`) | `camelCase`, 동사로 시작 (예: `calculateRealizedProfit`) | — |
| 변수 | `snake_case` (예: `buffer_size`) | `camelCase` (예: `bufferSize`) | 컬럼명 `snake_case` |
| 상수 | `UPPER_SNAKE_CASE` (예: `TRADING_FEE_RATE`) | `UPPER_SNAKE_CASE` (예: `TRADING_FEE_RATE`) | — |
| React 컴포넌트 함수 | — | `PascalCase`, 파일명과 동일 (`OrderPanel.tsx` → `function OrderPanel()`) | — |
| React 커스텀 훅 | — | `use` + `camelCase` (예: `useOrderBook`) | — |
| 파일명 | `snake_case.py` | 컴포넌트 `PascalCase.tsx`, 그 외 `camelCase.ts` | 마이그레이션 `NNN_설명.sql` |
| 불리언 | `is_`/`has_` 접두 (예: `is_active`) | 동일 (예: `isActive`) | 컬럼도 동일 (ERD 기준) |

---

## 2. 연산자 사용

이항 연산자 앞뒤에 공백을 둔다. 포맷터가 없으므로 특히 아래 두 언어에서 직접 챙긴다.

- **Python**: `price * quantity * (1 + TRADING_FEE_RATE)` — 단항 연산자와 기본 인자의 `=`는 공백 없음 (`def f(x=1)`, `-quantity`)
- **TypeScript**: 동일 규칙 + 삼항 연산자도 앞뒤 공백 (`isActive ? "ON" : "OFF"`)

---

## 3. 들여쓰기 (Indentation)

| 언어 | 들여쓰기 | 비고 |
|---|---|---|
| Python | 공백 4칸 (PEP 8) | 탭 금지 — 팀원 에디터마다 탭 폭이 달라 diff가 깨짐 |
| TypeScript/TSX | 공백 2칸 | React/TS 생태계 관례 |
| SQL | 공백 2칸 | 마이그레이션 파일 기준 |

새 블록이 시작될 때(Python `:`, TS/SQL `{`, `if`/`for`/`while` 등)마다 한 단계 들여쓴다.

---

## 4. 띄워쓰기 (Blank Lines)

논리적으로 하나로 묶이는 부분이 끝나면 한 줄 띄운다.

- Python: 최상위 함수·클래스 사이 빈 줄 2줄 (PEP 8), 클래스 내부 메서드 사이 1줄
- TypeScript: 함수·컴포넌트 사이 1줄, `import` 블록과 본문 사이 1줄
- 함수 내부: "입력 검증 → 계산 → 반환"처럼 의미 단위가 바뀌는 지점에 빈 줄 하나

---

## 5. 주석 (Comment)

함수 / 블록 / 문장 3단계로 구분한다. Python은 docstring, TypeScript는 JSDoc 형식을 쓴다.

### 5.1 함수 주석

Python:
```python
def calculate_realized_profit(sell_price: Decimal, quantity: Decimal, avg_buy_price: Decimal) -> Decimal:
    """매도 체결 시 실현손익을 계산한다.

    Args:
        sell_price: 체결가
        quantity: 체결 수량
        avg_buy_price: 체결 직전 평균매수가 (holdings 갱신 이전 값이어야 함)

    Returns:
        실현손익 (수수료 반영, 01-erd.md 3.2절 규칙)
    """
```

TypeScript (JSDoc):
```typescript
/**
 * 매도 체결 시 실현손익을 계산한다.
 * @param sellPrice 체결가
 * @param quantity 체결 수량
 * @param avgBuyPrice 체결 직전 평균매수가
 * @returns 실현손익 (수수료 반영, 01-erd.md 3.2절 규칙)
 */
```

### 5.2 블록 주석

여러 줄에 걸친 로직 앞에 `#`(Python)/`//`(TS) 한 줄로 의도를 설명한다.

```python
# 활성 슬롯이 앞으로 쓸 배정액까지 제외해야 하므로, 가용 원화에서 한 번 더 차감한다 (01-erd.md 3.1절)
withdrawable = available_krw - sum(slot.remaining_budget() for slot in active_slots)
```

### 5.3 문장 주석

같은 줄 끝에 `#`/`//`로 짧게 단다. 코드만 봐도 자명한 경우엔 달지 않는다 (`# i를 1 증가` 같은 무의미한 주석 금지).

```python
balance_after = krw_balance - amount  # 출금 후 잔고 미리보기 (05-deposit-withdraw 화면 표시용)
```

### 5.4 도메인 근거 주석 (신규 규칙)

금액·비율 계산 코드에는 [01-erd.md](01-erd.md)의 어느 절 규칙을 구현한 것인지 주석에 명시한다 (5.1절 예시처럼 `01-erd.md 3.2절`). 설계 문서와 코드 사이의 근거를 추적하기 위한 규칙이다 — 설계 점검 과정에서 문서 간 수치·단위 불일치가 여러 번 발견됐던 만큼, 코드에서 같은 실수(예: 수수료율 단위 혼동)가 재현되지 않도록 계산식 옆에 근거 절을 남긴다.

---

## 6. 프로젝트 구조

```
backend/
  app/
    routers/          -- FastAPI 라우터 (기능 문서 단위: auth.py, orders.py, ...)
    services/          -- 비즈니스 로직 (matcher.py 등 09-execution-engine 구현 위치)
    models/            -- SQLAlchemy 모델 (01-erd.md 테이블당 1개)
    schemas/           -- Pydantic 요청/응답 스키마
    strategy_engine/   -- 06-backtesting.md 2.6절 구조 그대로 (indicators.py, signals.py, grid.py, dca.py, costs.py, runner.py)
  migrations/          -- 마이그레이션 파일
frontend/
  src/
    pages/             -- 화면 단위 (SCR-01~08)
    components/        -- 재사용 컴포넌트
    hooks/             -- use*.ts
    api/               -- 백엔드 호출 함수
    types/             -- 공용 TS 타입 (ERD 테이블과 1:1 대응 권장)
```

---

## 7. Git 커밋 메시지 컨벤션

`type: 내용` 형식. `type`은 `feat`(기능 추가) / `fix`(버그 수정) / `docs`(문서) / `refactor`(동작 변경 없는 재구성) / `test`(테스트) / `chore`(빌드·설정 등 기타) 중 하나.

```
feat: 회원가입 API 구현
fix: 실현손익 계산 수수료 누락 수정
docs: 06-backtesting 봉단위 상한 표 추가
```

---

## 8. 브랜치 전략

**GitHub Flow**를 따른다 — 정식 배포 주기가 없는 학부 졸프이므로 `develop`/`release`/`hotfix`를 두는 Git Flow는 과한 구조다.

- **`main`**: 항상 기동 가능한 상태로 유지한다. 직접 커밋하지 않고 PR을 통해서만 병합한다.
- **작업 브랜치 명명**: `type/설명` — `type`은 위 7장 커밋 컨벤션과 동일한 `feat`/`fix`/`docs`/`refactor`/`test`/`chore`.
  - 로드맵 기능 단위 작업은 `feat/NN-기능명` 형태로, [00-overview.md](00-overview.md) 7장 로드맵 번호와 `docs/features/` 파일 번호를 그대로 쓴다 (예: `feat/00-bootstrap`, `feat/01-auth`, `feat/03-manual-trading` — `09-execution-engine`은 03과 함께 구현하므로 같은 브랜치에 포함).
  - 그 외 작업은 `fix/설명`, `docs/설명`, `chore/설명`.
- **병합**: PR 생성 → 팀원 최소 1인 리뷰 → **Squash merge**로 `main`에 병합해 기능 하나당 히스토리 1커밋으로 유지. 병합 후 브랜치는 삭제한다.
- **release/hotfix 브랜치는 두지 않는다.** 문제가 생기면 `main`에서 바로 `fix/` 브랜치를 딴다.

---

## 9. TypeScript 타입 ↔ ERD 대응 규칙

금액(`NUMERIC(20,4)`)·수량(`NUMERIC(28,8)`) 컬럼은 JS `number`의 부동소수점 오차를 피하기 위해 **API 응답에서 문자열로 받고, 화면 표시 직전에만 포매팅한다** ([01-erd.md](01-erd.md) 3.6절의 "문자열로 저장" 원칙을 프론트까지 연장). 값 자체로 계산이 필요한 경우 `decimal.js` 등 라이브러리 사용을 권장한다(도구를 강제하지는 않으므로 팀 판단에 따름).

`frontend/src/types/`의 타입은 [01-erd.md](01-erd.md) 2장 테이블 정의와 1:1로 대응시켜, 스키마가 바뀌면 이 타입부터 갱신한다.
