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

from pydantic import BaseModel, Field, ValidationError, model_validator

Interval = Literal["1m", "10m", "30m", "1h", "1d"]


class _ShortBelowLongMixin(BaseModel):
    """단기 기간은 장기 기간보다 짧아야 한다.

    뒤집으면 "에러 없이 돌지만 신호가 정반대"가 된다 — 같은 가격 흐름에서 정상 설정이 매수를
    내는 봉에 뒤집힌 설정은 매도를 낸다. 자동매매에서는 팔아야 할 때 사는 슬롯이 만들어지고,
    백테스트에서는 그럴듯해 보이는 틀린 결과가 나와 아무도 이상한 줄 모른다.

    같은 기간(`==`)도 막는다 — 단기선과 장기선이 겹쳐 교차가 정의되지 않는다.
    """

    short_period: int = Field(gt=0)
    long_period: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_short_below_long(self) -> "_ShortBelowLongMixin":
        if self.short_period >= self.long_period:
            raise ValueError("단기 기간은 장기 기간보다 짧아야 합니다.")
        return self


class MaTrendParams(_ShortBelowLongMixin):
    """추세추종 × MA: 골든/데드크로스 (06-backtesting.md 2.2절)."""

    interval: Interval


class MaCounterTrendParams(_ShortBelowLongMixin):
    """역추세 × MA: MA(long_period) 대비 이격도(%) (signals.py evaluate_counter_trend_ma)."""

    interval: Interval
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

    # 신호 로직은 "RSI ≤ 과매도면 매수"를 먼저 본다(signals.evaluate_counter_trend_rsi). 뒤집으면
    # (과매도 70 / 과매수 30) RSI 70 이하 **전 구간이 매수**가 되어 관망 구간이 사라진다 —
    # 실측에서 매수 신호가 51건 → 278건으로 늘었다. 같으면 경계값이 매수·매도 양쪽에 걸린다.
    @model_validator(mode="after")
    def validate_oversold_below_overbought(self) -> "RsiCounterTrendParams":
        if self.oversold >= self.overbought:
            raise ValueError("과매도 기준은 과매수 기준보다 작아야 합니다.")
        return self


class MacdParams(BaseModel):
    """MACD — 추세추종/역추세 공통 파라미터 구성 (신호 로직만 signals.py에서 갈라진다)."""

    interval: Interval
    short_period: int = Field(default=12, gt=0)
    long_period: int = Field(default=26, gt=0)
    signal_period: int = Field(default=9, gt=0)

    # 기본값이 있어 한쪽만 보내는 요청이 가능하다 — 보낸 쪽과 기본값이 뒤집히는 경우도 막는다
    # (예: short_period=30만 보내면 long 기본값 26보다 길다). MA와 같은 이유다.
    @model_validator(mode="after")
    def validate_short_below_long(self) -> "MacdParams":
        if self.short_period >= self.long_period:
            raise ValueError("단기 기간은 장기 기간보다 짧아야 합니다.")
        return self


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

    end_condition="budget"이면 invest_amount 자체가 소진 기준이라 횟수 제약이 없다. 다만
    **회당 금액 자체가 투자금보다 크면** 어느 종료 조건이든 한 번도 사지 못한다 — 엔진은
    "지출 + 회당 금액 > 투자금"이면 종료로 보므로(dca.is_finished), 슬롯을 켜도 영원히 아무것도
    안 하는 슬롯이 된다. 초과 지출은 없지만 사용자는 돌고 있다고 믿는다.
    """
    if Decimal(str(params["amount_per_buy"])) > invest_amount:
        raise ValueError("회당 매수금액이 투자금을 초과합니다.")
    if params.get("end_condition") != "count":
        return
    planned = Decimal(str(params["amount_per_buy"])) * Decimal(str(params["max_count"]))
    if planned > invest_amount:
        raise ValueError("회당 매수금액 × 총 횟수가 투자금을 초과합니다.")


def validate_exit_pcts(stop_loss_pct: Decimal | None, take_profit_pct: Decimal | None) -> None:
    """손절·익절 비율의 범위 (`strategy_engine/exits.py`는 둘 다 **양수 퍼센트**를 전제한다).

    엔진은 `수익률 <= -손절`이면 손절, `수익률 >= 익절`이면 익절한다. 그래서:

    - 손절 0 이하 / 익절 음수 → 매수 직후 수익률(수수료만큼 음수)이 바로 조건을 만족해 **다음
      tick에 팔아버린다.** 신호마다 수수료만 내고 사고팔기를 반복한다 (워커로 실측 확인).
    - 손절 100 이상 → 가격이 0 아래로 갈 수 없으니 영원히 발동하지 않는다. 사용자는 손절이
      걸려 있다고 믿는다.

    상한(999.999)은 컬럼 자릿수라 파싱 단계에서 이미 막힌다.
    """
    if stop_loss_pct is not None and not (0 < stop_loss_pct < 100):
        raise ValueError("손절 기준은 0보다 크고 100보다 작은 값을 입력해주세요.")
    if take_profit_pct is not None and take_profit_pct <= 0:
        raise ValueError("익절 기준은 0보다 큰 값을 입력해주세요.")


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


def params_error_message(error: ValidationError, default: str) -> str:
    """검증 실패를 사용자에게 보일 한 줄로 만든다.

    우리가 `model_validator`에서 직접 올린 `ValueError`(예: "단기 기간은 장기 기간보다 짧아야
    합니다.")는 그 문구를 그대로 쓰고, 그 외(타입·범위 위반)는 `default`로 떨어진다. 안 그러면
    모든 검증 실패가 "기준값은 0~100 사이의 값을 입력해주세요."로 나와서, 단기·장기를 뒤집은
    사용자에게 엉뚱한 안내를 하게 된다.
    """
    for detail in error.errors():
        if detail["type"] == "value_error":
            return str(detail["ctx"]["error"])
    return default


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
