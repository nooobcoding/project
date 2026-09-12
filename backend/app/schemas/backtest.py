"""06-backtesting 요청/응답 DTO.

금액·수치는 문자열로 주고받는다 (02-coding-conventions.md 9절 — 부동소수점 오차 방지).

**`/run` 응답과 `/results` 저장 요청의 필드가 1:1로 겹치는 이유**: `/run`은 결과를 저장하지 않고
돌려주기만 하고, 사용자가 "저장"을 눌렀을 때 프론트가 받은 결과를 라벨만 붙여 그대로 되보낸다
(06-backtesting.md 6장). 그래서 `BacktestSaveRequest`가 `BacktestRunResponse`를 상속한다 —
두 스키마가 어긋나면 저장이 조용히 실패하므로 구조적으로 묶어 둔다.

파라미터 검증은 `schemas/strategy_slots.py`의 `validate_params_for`를 그대로 재사용한다 —
전략유형×지표 조합별 스키마가 이미 그곳에 있고, 백테스팅과 자동매매가 같은 파라미터를 쓴다.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class BacktestTradeOut(BaseModel):
    """체결 1건 (01-erd.md `backtest_trades`).

    엔진의 `BacktestTrade`에는 청산 사유(`reason`)도 있지만 DB 컬럼이 없고 화면 스펙(3-B절)도
    요구하지 않아 API에 싣지 않는다.
    """

    side: Literal["buy", "sell"]
    price: str
    quantity: str
    # 매도만 값을 갖는다 — 매수는 실현손익이 없다.
    profit: str | None = None
    executed_at: datetime


class EquityPointOut(BaseModel):
    """수익 곡선의 한 점. `at`은 날짜가 아니라 시각이다 (models/backtest_result.py 참고)."""

    at: datetime
    asset: str


class BacktestMetricsOut(BaseModel):
    """성과지표 7개 (06-backtesting.md 3-B절)."""

    total_return: str
    final_asset: str
    trade_count: int
    win_rate: str
    mdd: str
    sharpe_ratio: str
    benchmark_return: str
    # 총수익률 − 벤치마크. DB에는 저장하지 않는 파생값이라 응답에만 싣는다
    # (strategy_engine/metrics.py `BacktestMetrics.excess_return`).
    excess_return: str


class BacktestRunRequest(BaseModel):
    """실행 요청. `params`는 원본 dict로 받고 라우터가 `validate_params_for`로 다시 검증한다
    (`StrategySlotWriteRequest`와 같은 이유 — Pydantic이 필드 값에 따른 분기 검증을 기본
    지원하지 않는다)."""

    coin_symbol: str
    strategy_type: Literal["trend", "counter_trend", "grid", "dca"]
    indicator: Literal["ma", "rsi", "macd", "bollinger"] | None = None
    params: dict
    start_date: date
    end_date: date
    initial_capital: str
    # % 단위로 받는다 (예: "0.05" = 0.05%). 엔진에 넘길 때 소수로 변환한다 (01-erd.md 3.2절).
    fee_rate: str
    slippage_rate: str
    stop_loss_pct: str | None = None
    take_profit_pct: str | None = None


class BacktestRunResponse(BaseModel):
    """실행 결과. 설정값을 그대로 돌려주는 것은 `/results` 저장 요청에 그대로 쓰기 위함이다."""

    coin_symbol: str
    strategy_type: str
    indicator: str | None
    params: dict
    start_date: date
    end_date: date
    initial_capital: str
    fee_rate: str
    slippage_rate: str
    metrics: BacktestMetricsOut
    equity_curve: list[EquityPointOut]
    trades: list[BacktestTradeOut]


class BacktestSaveRequest(BacktestRunResponse):
    """저장 요청 = 실행 결과 + 라벨.

    기본 라벨(`{전략유형}-{지표}-{코인}-{저장일}`) 생성은 설정 패널의 몫이라(06-backtesting.md
    3-A절) 백엔드는 받은 라벨을 그대로 쓴다.
    """

    label: str = Field(min_length=1, max_length=100)


class BacktestResultSummary(BaseModel):
    """저장 목록 한 줄 — 라벨·저장일·요약수익률 (06-backtesting.md 3-A절 불러오기 팝업)."""

    id: int
    label: str
    coin_symbol: str
    strategy_type: str
    indicator: str | None
    total_return: str
    final_asset: str
    created_at: datetime


class BacktestResultDetail(BaseModel):
    """저장된 결과 상세 — 설정값 복원 + 지표·곡선·체결 재현에 필요한 전부."""

    id: int
    label: str
    created_at: datetime
    coin_symbol: str
    strategy_type: str
    indicator: str | None
    params: dict
    start_date: date
    end_date: date
    initial_capital: str
    fee_rate: str
    slippage_rate: str
    metrics: BacktestMetricsOut
    equity_curve: list[EquityPointOut]
    trades: list[BacktestTradeOut]
