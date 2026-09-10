"""07-auto-trading 요청/응답 DTO — 전략 슬롯.

금액 필드는 문자열로 반환한다 (02-coding-conventions.md 9절). `params`는 전략유형×지표
조합마다 필드가 달라 조합별 Pydantic 모델을 두고, 최상위 요청 스키마가 `strategy_type`/
`indicator` 값을 보고 그중 맞는 모델로 검증한다 — RSI 0~100 범위처럼 06-backtesting.md
2.2절에 문서화된 제약을 여기서 강제한다 (07-auto-trading.md 6장 "파라미터 범위 초과").

그리드·DCA는 지표를 쓰지 않아 `indicator`가 None이고, 조합 키도 `(전략유형, None)`이다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Interval = Literal["1m", "10m", "30m", "1h", "1d"]


class MaTrendParams(BaseModel):
    """추세추종 × MA: 골든/데드크로스 (06-backtesting.md 2.2절)."""

    interval: Interval
    short_period: int = Field(gt=0)
    long_period: int = Field(gt=0)


class MaCounterTrendParams(BaseModel):
    """역추세 × MA: MA(long_period) 대비 이격도(%) (signals.py evaluate_counter_trend_ma)."""

    interval: Interval
    short_period: int = Field(gt=0)
    long_period: int = Field(gt=0)
    deviation_pct: float = Field(gt=0)


class RsiTrendParams(BaseModel):
    """추세추종 × RSI: 기준선(기본50) 돌파."""

    interval: Interval
    period: int = Field(default=14, gt=0)
    threshold: float = Field(default=50, ge=0, le=100)


class RsiCounterTrendParams(BaseModel):
    """역추세 × RSI: 과매도(기본30)·과매수(기본70)."""

    interval: Interval
    period: int = Field(default=14, gt=0)
    oversold: float = Field(default=30, ge=0, le=100)
    overbought: float = Field(default=70, ge=0, le=100)


class MacdParams(BaseModel):
    """MACD — 추세추종/역추세 공통 파라미터 구성 (신호 로직만 signals.py에서 갈라진다)."""

    interval: Interval
    short_period: int = Field(default=12, gt=0)
    long_period: int = Field(default=26, gt=0)
    signal_period: int = Field(default=9, gt=0)


class BollingerParams(BaseModel):
    """볼린저밴드 — 추세추종/역추세 공통 파라미터 구성."""

    interval: Interval
    period: int = Field(default=20, gt=0)
    std_multiplier: float = Field(default=2.0, gt=0)


class GridParams(BaseModel):
    """그리드 — 지표 없음 (06-backtesting.md 2.3절).

    문서는 "그리드 간격(%), 상한가, 하한가, 격자 수" 넷을 나열하지만 상한·하한·격자 수가
    정해지면 간격은 종속값이라 넷 다 자유 입력일 수 없다. 입력은 상한/하한/격자 수만 받고
    간격은 화면에서 파생 표시한다 (app/strategy_engine/grid.py 참고).
    """

    interval: Interval
    lower_price: float = Field(gt=0)
    upper_price: float = Field(gt=0)
    grid_count: int = Field(ge=2, le=100)

    @model_validator(mode="after")
    def validate_price_range(self) -> "GridParams":
        if self.upper_price <= self.lower_price:
            raise ValueError("상한가는 하한가보다 높아야 합니다.")
        return self


class DcaParams(BaseModel):
    """DCA/분할매수 — 지표 없음 (06-backtesting.md 2.4절).

    "회당 매수금액 × 총 횟수"가 invest_amount를 넘지 않아야 한다는 규칙(06-backtesting.md
    2.4-1절)은 invest_amount를 함께 봐야 하므로 여기서 검증하지 못한다 — 라우터가
    `validate_dca_budget`로 따로 확인한다.
    """

    interval: Interval
    # RSI/볼린저의 period(숫자)와 이름이 겹치지 않도록 buy_period로 둔다 —
    # 폼 상태가 전략유형별 파라미터를 한 dict에 평평하게 담기 때문에 키가 겹치면 서로 덮어쓴다.
    buy_period: Literal["day", "week", "month"]
    amount_per_buy: float = Field(gt=0)
    end_condition: Literal["count", "budget"]
    # end_condition="count"일 때만 의미가 있다.
    max_count: int = Field(default=10, ge=1, le=1000)
    extra_buy_enabled: bool = False
    extra_buy_drop_pct: float = Field(default=5, gt=0, le=100)


# (strategy_type, indicator) → 해당 조합의 파라미터 스키마. 그리드/DCA는 지표가 없어 키가 None이다.
_PARAM_SCHEMAS: dict[tuple[str, str | None], type[BaseModel]] = {
    ("trend", "ma"): MaTrendParams,
    ("counter_trend", "ma"): MaCounterTrendParams,
    ("trend", "rsi"): RsiTrendParams,
    ("counter_trend", "rsi"): RsiCounterTrendParams,
    ("trend", "macd"): MacdParams,
    ("counter_trend", "macd"): MacdParams,
    ("trend", "bollinger"): BollingerParams,
    ("counter_trend", "bollinger"): BollingerParams,
    ("grid", None): GridParams,
    ("dca", None): DcaParams,
}


def validate_dca_budget(params: dict, invest_amount: Decimal) -> None:
    """"회당 매수금액 × 총 횟수"가 총 상한을 넘지 않는지 (06-backtesting.md 2.4-1절).

    end_condition="budget"이면 invest_amount 자체가 소진 기준이라 횟수 제약이 없다.
    """
    if params.get("end_condition") != "count":
        return
    planned = Decimal(str(params["amount_per_buy"])) * Decimal(str(params["max_count"]))
    if planned > invest_amount:
        raise ValueError("회당 매수금액 × 총 횟수가 투자금을 초과합니다.")


class StrategySlotWriteRequest(BaseModel):
    """슬롯 생성·수정 공용 요청. `params`는 여기서는 원본 dict로만 받고,
    라우터가 `validate_params_for`로 조합별 스키마에 맞춰 다시 검증한다 — Pydantic은
    필드 값(strategy_type/indicator)에 따라 다른 모델로 분기 검증하는 것을 기본 지원하지
    않으므로, 이 구조가 가장 단순하다.

    `indicator`는 그리드에서 None이다 (지표를 쓰지 않는다).
    """

    coin_symbol: str
    strategy_type: Literal["trend", "counter_trend", "grid", "dca"]
    indicator: Literal["ma", "rsi", "macd", "bollinger"] | None = None
    params: dict
    invest_amount: str
    stop_loss_pct: str | None = None
    take_profit_pct: str | None = None


def validate_params_for(strategy_type: str, indicator: str | None, params: dict) -> dict:
    """(strategy_type, indicator) 조합에 맞는 파라미터 스키마로 검증하고 dict로 되돌린다.

    실패 시 pydantic.ValidationError를 그대로 전파한다 — 라우터가 이를 잡아 07 6장
    "기준값은 0~100 사이의 값을 입력해주세요." 같은 메시지로 번역한다. 조합 자체가 없는
    경우(예: 그리드인데 지표를 함께 보낸 경우)는 KeyError가 되므로 라우터가 함께 처리한다.
    """
    schema = _PARAM_SCHEMAS[(strategy_type, indicator)]
    return schema(**params).model_dump()


class StrategySlotResponse(BaseModel):
    id: int
    coin_symbol: str
    strategy_type: str
    indicator: str | None
    params: dict
    invest_amount: str
    stop_loss_pct: str | None
    take_profit_pct: str | None
    state: dict
    is_active: bool
    created_at: datetime


class SlotDeletionResponse(BaseModel):
    """삭제 확인 모달용 — 잔여 포지션이 수동 보유분으로 남는다는 안내에 쓴다 (07 4.2절)."""

    coin_symbol: str
    korean_name: str
    remaining_quantity: str


class SlotSignalResponse(BaseModel):
    signal: Literal["buy", "sell"] | None
    evaluated_at: datetime


class StrategySlotPatchRequest(BaseModel):
    """PATCH 공용 요청 (07 8장). `is_active`만 오면 ON/OFF 토글, 그 외 필드가 오면 설정 수정 —
    두 종류를 한 요청에 섞지 않는다(라우터가 `is_active` 유무로 분기)."""

    is_active: bool | None = None
    strategy_type: Literal["trend", "counter_trend", "grid", "dca"] | None = None
    indicator: Literal["ma", "rsi", "macd", "bollinger"] | None = None
    params: dict | None = None
    invest_amount: str | None = None
    stop_loss_pct: str | None = None
    take_profit_pct: str | None = None
