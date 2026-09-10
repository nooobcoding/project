# 06 백테스팅 — 구현 계획

**상태**: 계획 확정 · 구현 전
**성격**: 이 문서는 `06-backtesting.md`(기능 스펙)와 별개로, **실제 구현 순서와 단계별 근거를 담은 작업 계획**이다. 다른 세션에서 이 문서 하나만 보고 이어서 구현을 시작할 수 있도록, 조사 과정에서 나온 판단과 확정된 방침까지 그대로 남긴다.
**연관 문서**: [06-backtesting.md](06-backtesting.md)(스펙), [07-auto-trading.md](07-auto-trading.md), [01-erd.md](../01-erd.md)

---

## Context

07 자동매매(Step 1~5)가 끝나면서 전략 엔진(지표 8조합·그리드·DCA)은 이미 완성돼 있다. 06은 **그 엔진을 과거 데이터에 돌려 성과를 검증하는 화면**이다. 로드맵상 원래 06이 07보다 먼저였지만, "엔진 코어만 먼저 만들고 07로 직행" 방침으로 순서를 바꿔 미뤄둔 것이므로 이제 그 빚을 갚는 단계다.

착수 전 조사에서 확인한 두 가지가 이 계획의 뼈대다.

**① 과거 데이터 조회 기능이 아예 없다.** `services/candles.py`의 `_fetch_upbit_candles`는 Upbit에 `count`만 넘기고 `to`(기준 시점) 파라미터를 쓰지 않는다. 즉 지금은 "최신 200개"만 가져올 수 있고 **기간 지정 조회가 불가능**하다. 1분봉 7일(10,080개)이면 Upbit 호출이 51회 필요하다(200개/회). 이게 06에서 가장 큰 신규 작업이며, 07에는 없던 요구사항이다.

**② 엔진 공유가 절반만 돼 있다.** 백테스팅이 실매매와 같은 답을 내려면 같은 코드를 써야 하는데, 현재 상태는:

| 필요한 로직 | 현재 위치 | 백테스팅이 쓸 수 있나 |
|---|---|---|
| 신호 판정 | `strategy_engine/runner.evaluate` | ✅ 그대로 |
| 포지션 산술(평단·수량) | `services/slot_state.apply_buy/apply_sell` | ✅ 순수 함수라 그대로 |
| 수수료·슬리피지 | `strategy_engine/costs.py` | ✅ 그대로 (슬리피지 인자 이미 있음) |
| **손절·익절 판정** | `worker.py::decide_exit`, `_try_grid_exit`, `_try_dca_exit` | ❌ 워커 private + DB 접근과 얽힘 |
| **그리드 라인 / DCA 진행 갱신** | `worker.py::_mark_grid_line`, `_execute_dca_buy` | ❌ 〃 |

아래 두 줄이 그대로 두면 생기는 문제다: 백테스팅이 이 로직을 **복제**하게 되고, 이후 한쪽만 고치면 "백테스트에선 익절됐는데 실매매에선 안 됨" 같은 조용한 괴리가 생긴다. 그래서 이번에 그 경계를 정리하고 간다 — "엔진 모듈화가 제대로 됐나"에 대한 실제 답이기도 하다.

**확정된 방침**:
1. **범위**: 실행 + 성과지표 + 수익곡선 + 결과 저장/불러오기까지. **"전략 비교 카드"(FR-B09)는 이번 범위에서 제외** — 기본 흐름이 검증된 뒤 별도로 얹는다.
2. **성능**: 미리 최적화하지 않는다. Phase A에서 **실측 먼저**, 30초 목표를 넘길 때만 대응한다.

---

## 전체 단계

| Phase | 범위 | 모델 | 검증 |
|---|---|---|---|
| **A** | **엔진 공유 경계 정리 + 백테스트 시뮬레이터** | **Opus** | pytest (실매매 경로 회귀 포함) |
| B | 성과지표 계산 | Sonnet | pytest (손계산 대조) |
| C | 과거 캔들 기간 조회 (Upbit 페이지네이션 + 캐시) | Sonnet | pytest + 실제 Upbit 호출 |
| D | 스키마·API | Sonnet | pytest + HTTP |
| E | 프론트 화면 `/backtest` | Sonnet | 브라우저 E2E |

### 모델 선택 근거

**Phase A만 Opus인 이유**: 이 단계는 **살아있는 실매매 경로(worker.py / matcher.py)를 건드린다.** 07에서 검증까지 끝낸 코드에서 로직을 들어내 엔진으로 옮기는 작업이라, 잘못하면 "백테스팅을 만들다가 자동매매를 망가뜨리는" 최악의 결과가 난다. 게다가 시뮬레이터가 실매매와 정말 같은 답을 내는지는 타입 검사나 화면으로 드러나지 않고, 숫자가 조용히 어긋나는 방식으로만 틀린다 — 07 Step 2B와 같은 성격의 위험이다.

**나머지가 Sonnet인 이유**: B는 순수 수학이라 손계산 대조로 즉시 잡히고, C는 페이지네이션 경계값이 까다롭지만 테스트로 드러나며, D는 기존 라우터 패턴 복제, E는 분량은 많아도 화면으로 즉시 검증된다.

전환은 `/model`로 Phase 경계에서만 바꾼다. **A 커밋 직후 Claude가 멈추고 `/model opusplan` 복귀를 안내**한다.

---

## Phase A — 엔진 공유 경계 정리 + 백테스트 시뮬레이터 (Opus)

### A-0. 먼저 성능 실측 (다른 작업 전에)

시뮬레이터 뼈대를 최소한으로 만든 직후, 1분봉 10,080개로 한 번 돌려 시간을 잰다. 판단 기준:
- **30초 이내면 그대로 간다.** 최적화하지 않는다.
- 넘기면 `runner.evaluate`에 넘기는 캔들을 **최근 N봉(300)으로 자른다**. SMA·볼린저는 결과가 완전히 동일하고, RSI·MACD(지수이동평균)만 소수점 아주 아래에서 미세하게 달라진다 — 그 사실을 코드 주석과 06 문서에 남긴다.

### A-1. 손절·익절 판정을 엔진으로 이동

`worker.py`에 흩어진 청산 판정을 `strategy_engine/exits.py`(신규)의 **순수 함수**로 모은다:

```python
def decide_exit(spec: SlotSpec, position: dict, current_price: Decimal) -> TradeIntent | None
```

전략유형별 규칙(06-backtesting.md 2.5절)을 한 곳에서 분기한다 — 추세추종/역추세는 `stop_loss_pct`/`take_profit_pct`, 그리드는 하한가 이탈(`grid.is_below_lower_bound`), DCA는 목표 수익률 익절만. 기존 `worker.decide_exit`는 이리로 흡수한다.

워커는 이 함수를 호출해 의도를 받고, **DB 쓰기(주문·슬롯 OFF·라인 리셋)만 자기가 한다.** 즉 "무엇을 할지"는 엔진, "어떻게 기록할지"는 워커로 갈린다.

### A-2. 전략 진행 상태 갱신을 엔진으로 이동

체결 후 상태를 어떻게 바꿀지도 순수 함수로 뽑는다 (`strategy_engine/` 안, grid.py·dca.py에 각각):

- `grid.mark_line_filled(lines, index, price, quantity)` / `mark_line_empty(lines, index)`
- `dca.advance_after_buy(dca_state, intent, fill_price, spent, now, params)`

워커의 `_mark_grid_line`·`_execute_dca_buy`는 이 함수로 상태를 계산한 뒤 `slot_state.write_*`로 저장만 한다. 백테스팅은 같은 함수로 메모리 상태를 갱신한다.

### A-3. 수수료 계산 일원화

`services/matcher.py`가 `costs.py`를 쓰지 않고 자체 수수료 로직(`_calculate_fee`, `_apply_holdings`의 인라인 계산)을 갖고 있다 — 06 문서 2.6절이 "실체결과 백테스팅이 같은 함수를 쓴다"고 정한 것과 어긋난다. `costs.calc_buy_amount` 등으로 바꾼다. **실매매 체결 경로를 건드리므로 기존 체결 테스트가 전부 통과하는지가 관문이다.**

### A-4. 백테스트 시뮬레이터 — `strategy_engine/backtest.py` (신규)

```python
def run_backtest(candles, spec, initial_capital, fee_rate, slippage_rate) -> BacktestRun
```

캔들을 시간순으로 훑으며 워커의 tick과 **같은 순서**로 처리한다:

1. `exits.decide_exit(...)` → 청산 의도가 있으면 집행하고 이번 봉은 종료 (워커가 `_try_exit` 후 return하는 것과 동일)
2. 없으면 `runner.evaluate(spec, window, now, current_price=close)` → 의도들을 순서대로 집행
3. 체결 시뮬레이션: `costs.calc_fill_price`(슬리피지) → `costs.calc_buy_amount/calc_sell_amount`(수수료) → `slot_state.apply_buy/apply_sell`(포지션) → A-2 함수로 전략 상태 갱신
4. 매 봉 끝에 `equity_curve`에 `{date, asset}` 적립 (asset = 현금 + 보유수량 × 종가)
5. 매수/매도마다 `trades`에 기록 (매도는 `costs.calc_realized_profit`으로 실현손익 포함)

현금이 부족하면 그 매수만 건너뛴다 — 워커가 `InsufficientBalanceError`에서 하는 것과 같다.

**핵심**: 3번 줄의 모든 함수가 실매매가 쓰는 바로 그 함수다. 시뮬레이터가 자체적으로 계산하는 산술은 "현금 잔고"뿐이다.

### A 테스트

- `tests/test_backtest.py` — 합성 캔들로 시뮬레이터 검증: 상승 일변도면 추세추종이 수익, 수수료·슬리피지가 실제로 차감되는지, 현금 부족 시 스킵, 그리드 라인·DCA 진행이 실매매와 같은 방식으로 갱신되는지
- `tests/test_exits.py` — 전략유형별 청산 판정
- **기존 144개 테스트가 전부 통과해야 한다** (A-1~A-3이 실매매 경로를 건드리므로 이게 사실상 회귀 게이트다)

### A 완료 후 → 커밋 → **여기서 멈추고 `/model opusplan` 복귀 안내**

---

## Phase B — 성과지표 (Sonnet)

`strategy_engine/metrics.py`(신규). 06-backtesting.md 3-B절 7개 지표:

- 총수익률, 최종자산, 거래횟수(매수·매도 각 1건), 승률(실현손익 > 0인 매도 비율)
- **MDD**: 자산 곡선의 최대 낙폭(%)
- **Sharpe**: 무위험수익률 0%, **일간 수익률** 평균/표준편차 → 연환산 ×√252 (문서 고정값). 자산 곡선을 날짜별 마지막 값으로 접어 일간 시계열을 만든 뒤 계산. 표본이 2개 미만이거나 표준편차가 0이면 0으로 둔다(주석 명시)
- **벤치마크 대비 초과수익률**: 동일 기간 단순 보유(Buy & Hold) 수익률 = `(마지막 종가 − 첫 종가) / 첫 종가 × 100`. 초과수익률 = 전략 − 벤치마크

`tests/test_metrics.py` — 손계산 기댓값 대조(특히 MDD·Sharpe).

---

## Phase C — 과거 캔들 기간 조회 (Sonnet)

`services/candles.py`에 추가:

```python
def get_candles_in_range(db, symbol, interval, start, end) -> list[Candle]
```

- `_fetch_upbit_candles`에 **`to` 파라미터를 추가**해 과거로 거슬러 페이지네이션한다 (Upbit는 `to` 이전 캔들을 최신순 200개씩 준다).
- 이미 있는 `candles` 테이블 캐시를 먼저 보고 **모자란 구간만** 채운다. `UNIQUE (coin_symbol, interval, opened_at)` + 기존 `_upsert_candles`를 그대로 재사용 → 같은 기간을 다시 백테스트하면 Upbit 호출이 0이다.
- 레이트리밋 대비 호출 사이 짧은 간격을 둔다.
- 봉단위별 최대 기간(06 2.1-1절 표: 1분=7일 / 10분=1개월 / 30분=3개월 / 1시간=6개월 / 1일=5년)을 넘는 요청은 거부한다.

`tests/test_candles_range.py` — 캐시 히트 시 외부 호출 없음, 경계값(시작/종료 포함 여부), 상한 초과 거부.

---

## Phase D — 스키마·API (Sonnet) — **구현완료**

**마이그레이션 1개** (`down_revision`은 현재 head): `backtest_results` + `backtest_trades`. 컬럼은 01-erd.md 정의 그대로(`equity_curve` JSONB NOT NULL 포함), `backtest_trades.backtest_result_id`는 **ON DELETE CASCADE**(결과를 지우면 체결 상세도 함께 사라져야 한다 — 07에서 배운 FK 삭제 동작 명시).

`services/backtest.py` + `routers/backtest.py` (06 6장):

| Method | Path | 비고 |
|---|---|---|
| POST | `/api/backtest/run` | 동기 실행, **저장하지 않고** 결과만 반환 |
| POST | `/api/backtest/results` | 라벨과 함께 저장 |
| GET | `/api/backtest/results` | 목록 |
| GET | `/api/backtest/results/{id}` | 상세 + 체결 목록 |

- 파라미터 검증은 `schemas/strategy_slots.py`의 `validate_params_for`를 **그대로 재사용**한다 (전략유형×지표 조합별 스키마가 이미 있다).
- `/run`이 결과를 저장하지 않고 `/results`가 클라이언트가 돌려준 결과를 받는 구조라, 이론상 클라이언트가 조작한 수치를 저장할 수 있다. 개인용 모의투자 도구 범위에서 감수하고 주석에 남긴다(다시 계산하면 중복 실행 비용이 든다).
- **60초**(사용자 결정으로 30초에서 상향, 2026-09) 초과 시 명확한 오류 메시지(06 4장). 실질적 방어는 Phase C의 기간 상한이다. `services/backtest.py`의 `ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=60)`으로 구현 — `with` 블록으로 감싸면 `shutdown(wait=True)`가 오래 걸리는 계산이 끝날 때까지 블로킹해 타임아웃이 무의미해지므로, 타임아웃 시엔 반드시 `shutdown(wait=False)`로 즉시 손을 뗀다.

**구현 시 확정한 사항** (계획 대비 구체화):
- `invest_amount = initial_capital` — 백테스팅 설정 패널엔 "초기 투자금" 입력 하나뿐이라 전략유형별 `invest_amount` 의미(추세추종=1회 진입액/그리드=격자 총상한/DCA=분할매수 총상한)가 전부 이 값을 가리킨다.
- `equity_curve` 저장 형식을 `{date, asset}` → `{at, asset}`(ISO datetime)로 정정 — 분봉 백테스트는 하루에 여러 점이 나와 날짜로 접으면 곡선이 뭉개진다 (01-erd.md·06-backtesting.md 5장 반영).
- 엔진의 `BacktestTrade`(dataclass)와 모델의 `BacktestTrade`(ORM) 이름이 겹쳐 서비스·라우터에서 임포트 별칭(`BacktestTradeRow`)으로 구분한다.
- 청산 사유(`reason`)는 API에 노출하지 않는다 — DB 컬럼도 없고 화면 스펙도 요구하지 않는다.
- 이 프로젝트에 HTTP `TestClient` 테스트 선례가 없어(07도 서비스 함수 직접 호출 pytest + 실서버 수동 HTTP 검증 병행) 같은 방식을 따랐다: `tests/test_backtest_service_db.py`(서비스 계층, 16개) + 실행 중인 개발 서버 대상 Python 스크립트로 회원가입→BTC 실데이터 실행→저장→목록→상세→에러 케이스 전 구간 HTTP 검증.

---

## Phase E — 프론트 `/backtest` (Sonnet) — **구현완료**

2컬럼 — 설정 패널(260px) / 결과 패널. `.trade-grid`(1fr 260px) 대신 **`.wallet-grid` 배치**(고정폭 왼쪽)를 참고해 `.backtest-*` 접두 블록을 `index.css` 끝에 추가.

- **설정 패널**: 봉단위·기간(`input type="date"`, 봉단위별 `min` 동적 제한)·코인(`CoinSearchList` 재사용)·전략/지표/파라미터. **파라미터 폼은 `SlotFormModal`의 동적 폼 로직을 거의 그대로 재사용**한다 — 이미 06 문서 기준으로 만들어져 있다. 초기투자금·수수료율·슬리피지율 입력.
- **결과 패널**: 성과지표 7개 그리드, 수익 곡선(lightweight-charts v5 `addSeries(LineSeries, ...)` — `CandleChart`의 초기화·resize·cleanup 패턴 복사), 매수/매도 마커(v5는 `createSeriesMarkers` 플러그인 — 이 프로젝트 첫 사용), 마커 클릭 시 체결 상세.
- 실행 중 표시는 기존 관례대로 버튼 라벨 전환 + disabled (Progress Bar 컴포넌트가 프로젝트에 없다).
- 결과 저장(라벨 입력, 기본값 `{전략유형}-{지표}-{코인}-{저장일}`) / 불러오기 목록 팝업 — `dashboard-modal-*` 패턴 재사용.
- `App.tsx`에 `/backtest` 라우트, `Gnb.tsx`의 `isBuilt: true`.

**구현 시 발견한 실제 버그(z-index)**: `.dashboard-modal-backdrop`(모든 모달의 공용 배경)에
명시적 `z-index`가 없었다. `lightweight-charts`가 내부 캔버스에 `z-index: 1~2`를 직접 지정하는데,
이 화면 전에는 어떤 화면도 차트와 모달을 동시에 쓰지 않아 드러나지 않았던 잠재 버그였다 —
Playwright로 "결과 저장" 모달의 저장 버튼을 클릭했더니 그 아래 차트 캔버스가 클릭을 가로챘다
(`element intercepts pointer events`). `.dashboard-modal-backdrop`에 `z-index: 1000`을 추가해
해결 — 이 클래스를 쓰는 07의 기존 모달들에도 영향 없이 전부 안전해진다(일반적으로 그 값들보다
훨씬 높은 값이라 항상 위에 뜬다). 06이 새로 발견했지만 07까지 함께 고쳐지는 공용 수정.

기타 구현 중 정정: 최종자산 등 원화 표시가 `NUMERIC(20,4)`의 소수 4자리를 그대로 보여주던 것을
`maximumFractionDigits: 0`으로 반올림. 불러오기 시 초기투자금/수수료율/슬리피지율에 저장된
DB 값의 뒤따르는 0(`10000000.0000`, `0.050`)이 그대로 보이던 것을 표시 직전 정리.

**차트 마커 클릭 검증 방법**: `chart.subscribeClick`은 클릭한 x좌표에서 가장 가까운 시간축
값을 반환하며 y좌표(마커를 실제로 맞혔는지)와 무관하다. Playwright로 캔버스 좌표를 추정해
클릭하는 방식은 부정확할 수 있어(시간축이 데이터 인덱스에 정확히 선형 비례하지 않음), 실제
검증은 차트 영역 전체를 촘촘히 스캔해 히트하는 지점을 찾는 방식으로 했다 — 정확한 지점을 찾으면
올바른 체결 정보(매수/매도·가격·수량·시각)가 담긴 팝업이 뜨는 것까지 확인했다.

---

## 검증 방법

**Phase A**: `pytest tests -v`. 기존 144개 전부 통과가 회귀 게이트. 신규 시뮬레이터 테스트에서 **실매매와 같은 함수를 쓰는지**를 확인 — 특히 그리드 라인·DCA 진행 상태가 07 워커 테스트와 같은 결과를 내는지.

**Phase C**: postgres를 띄우고 실제 Upbit에서 BTC 일봉 1년을 받아 365개 내외가 캐시에 쌓이는지, 두 번째 호출은 외부 요청 없이 캐시에서 나오는지 확인.

**Phase D**: `POST /api/backtest/run`으로 실제 과거 데이터 백테스트를 돌려 지표가 상식적인 값인지(총수익률·MDD·승률 범위), 저장→목록→상세 왕복 확인.

**Phase E**: 브라우저(Playwright)로 `/backtest` 진입 → 설정 입력 → 실행 → 지표·차트 렌더 → 저장 → 불러오기까지 콘솔 에러 0건으로 확인. 스크린샷으로 차트·마커 육안 확인.

**교차 검증(이 기능의 핵심)**: 같은 전략·같은 코인으로 **백테스팅 결과와 07 자동매매의 실제 동작이 같은 판단을 하는지** 대조한다. 예: 특정 확정봉에서 백테스팅이 매수했다면, 같은 조건의 슬롯을 07에서 켰을 때도 매수 신호가 나오는지 `/api/strategy-slots/{id}/signals`로 확인.

---

## 문서 갱신 (구현 완료 후)

- `00-overview.md` 7장 로드맵 — 6번 완료 체크
- `06-backtesting.md` — 상태를 "구현완료"로, 2.6절 엔진 구조를 실제 파일 구성에 맞게 갱신(`exits.py`·`backtest.py`·`metrics.py` 추가), A-0에서 lookback을 적용했다면 그 사실과 근거를 명시, "전략 비교 카드"는 미구현으로 표기
- `01-erd.md` — `backtest_trades` FK의 ON DELETE CASCADE 명시
- 이 문서(`06-backtesting-plan.md`)는 구현이 끝나면 상태를 "구현완료"로 바꾸거나, 다음 계획 문서로 대체될 때 삭제해도 된다 — 스펙의 최종 근거는 항상 `06-backtesting.md`와 `01-erd.md`다.
