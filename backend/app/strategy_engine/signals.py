"""전략유형×지표 조합별 매수/매도 신호 판정 (06-backtesting.md 2.2절 표를 그대로 구현).

각 함수는 확정봉 종가 시퀀스(오래된 순)와 파라미터를 받아 "buy"/"sell"/None을 반환한다. 크로스 계열
신호(골든/데드크로스, RSI 50선, MACD선-시그널선, 볼린저 상단·하단 돌파)는 직전 확정봉과 최신 확정봉
2개 지표값을 비교해 "그 봉에서 막 교차가 일어났는지"만 판정한다 — 교차 이후에도 조건이 계속 유지되는
매 봉마다 같은 신호가 반복 발생하는 것을 막기 위함이다. 반면 레벨 계열 신호(RSI 과매수·과매도,
볼린저 밴드 터치, MA 이격도)는 도달 여부 자체가 신호이므로 조건이 유지되는 동안 확정봉마다 반복
발생할 수 있다 — 이는 07-auto-trading 워커의 `state.last_evaluated_candle_at` 확정봉 단위 중복
평가 방지(07-auto-trading.md 4장)와는 별개의, 신호 로직 자체의 정상 동작이다.

MACD 역추세(히스토그램 저점 반등/고점 하락전환)만 예외적으로 3개 지표값(직전전·직전·최신)이
필요하다 — "반등/하락전환"이라는 개념 자체가 국지적 저점/고점을 확정하려면 그 앞뒤 값이 있어야
판정 가능하기 때문이다.
"""

from typing import Any, Literal

import pandas as pd

from app.strategy_engine.indicators import calc_bollinger, calc_ma, calc_macd, calc_rsi

Signal = Literal["buy", "sell"]


def evaluate_trend_ma(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """추세추종 × MA: 골든크로스(단기MA↗장기MA)→매수 / 데드크로스→매도."""
    short_ma = calc_ma(closes, params["short_period"])
    long_ma = calc_ma(closes, params["long_period"])
    if pd.isna(short_ma.iloc[-2]) or pd.isna(long_ma.iloc[-2]):
        return None

    prev_short, prev_long = short_ma.iloc[-2], long_ma.iloc[-2]
    curr_short, curr_long = short_ma.iloc[-1], long_ma.iloc[-1]

    if prev_short <= prev_long and curr_short > curr_long:
        return "buy"
    if prev_short >= prev_long and curr_short < curr_long:
        return "sell"
    return None


def evaluate_counter_trend_ma(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """역추세 × MA: 가격이 MA 대비 -X% 이상 이격→매수 / +X% 이상 이격→매도.

    이격도 판정 기준 MA는 `params["long_period"]`(장기 MA)를 쓴다 — 단기선까지 두면 이격도
    기준이 불안정해지므로 추세 판단에 준하는 장기선 하나를 기준선으로 고정한다.
    """
    ma = calc_ma(closes, params["long_period"])
    if pd.isna(ma.iloc[-1]):
        return None

    deviation_pct = params["deviation_pct"]
    price = closes.iloc[-1]
    deviation = (price - ma.iloc[-1]) / ma.iloc[-1] * 100

    if deviation <= -deviation_pct:
        return "buy"
    if deviation >= deviation_pct:
        return "sell"
    return None


def evaluate_trend_rsi(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """추세추종 × RSI: RSI 50선 상향 돌파→매수 / 하향 돌파→매도."""
    rsi = calc_rsi(closes, params.get("period", 14))
    if pd.isna(rsi.iloc[-2]):
        return None

    threshold = params.get("threshold", 50)
    prev, curr = rsi.iloc[-2], rsi.iloc[-1]

    if prev <= threshold and curr > threshold:
        return "buy"
    if prev >= threshold and curr < threshold:
        return "sell"
    return None


def evaluate_counter_trend_rsi(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """역추세 × RSI: RSI≤과매도(기본30)→매수 / RSI≥과매수(기본70)→매도."""
    rsi = calc_rsi(closes, params.get("period", 14))
    if pd.isna(rsi.iloc[-1]):
        return None

    oversold = params.get("oversold", 30)
    overbought = params.get("overbought", 70)
    curr = rsi.iloc[-1]

    if curr <= oversold:
        return "buy"
    if curr >= overbought:
        return "sell"
    return None


def evaluate_trend_macd(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """추세추종 × MACD: MACD선 시그널선 상향 돌파→매수 / 하향 돌파→매도."""
    macd_line, signal_line, _ = calc_macd(
        closes,
        params.get("short_period", 12),
        params.get("long_period", 26),
        params.get("signal_period", 9),
    )
    if pd.isna(macd_line.iloc[-2]) or pd.isna(signal_line.iloc[-2]):
        return None

    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]

    if prev_diff <= 0 and curr_diff > 0:
        return "buy"
    if prev_diff >= 0 and curr_diff < 0:
        return "sell"
    return None


def evaluate_counter_trend_macd(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """역추세 × MACD: MACD 히스토그램 저점 반등→매수 / 고점 하락전환→매도.

    직전전·직전·최신 3개 히스토그램 값으로 직전 값이 국지적 저점/고점이었는지 판정한다
    (모듈 docstring 참고 — 이 조합만 2점이 아닌 3점 비교가 필요한 예외).
    """
    _, _, histogram = calc_macd(
        closes,
        params.get("short_period", 12),
        params.get("long_period", 26),
        params.get("signal_period", 9),
    )
    if len(histogram) < 3 or pd.isna(histogram.iloc[-3]):
        return None

    prev2, prev1, curr = histogram.iloc[-3], histogram.iloc[-2], histogram.iloc[-1]

    if prev2 > prev1 and curr > prev1:
        return "buy"
    if prev2 < prev1 and curr < prev1:
        return "sell"
    return None


def evaluate_trend_bollinger(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """추세추종 × 볼린저밴드: 상단밴드 상향 돌파→매수 / 하단밴드 하향 돌파→매도."""
    _, upper, lower = calc_bollinger(
        closes, params.get("period", 20), params.get("std_multiplier", 2.0)
    )
    if pd.isna(upper.iloc[-2]) or pd.isna(lower.iloc[-2]):
        return None

    prev_price, curr_price = closes.iloc[-2], closes.iloc[-1]

    if prev_price <= upper.iloc[-2] and curr_price > upper.iloc[-1]:
        return "buy"
    if prev_price >= lower.iloc[-2] and curr_price < lower.iloc[-1]:
        return "sell"
    return None


def evaluate_counter_trend_bollinger(closes: pd.Series, params: dict[str, Any]) -> Signal | None:
    """역추세 × 볼린저밴드: 하단밴드 터치·하회→매수 / 상단밴드 터치·상회→매도."""
    _, upper, lower = calc_bollinger(
        closes, params.get("period", 20), params.get("std_multiplier", 2.0)
    )
    if pd.isna(upper.iloc[-1]):
        return None

    price = closes.iloc[-1]

    if price <= lower.iloc[-1]:
        return "buy"
    if price >= upper.iloc[-1]:
        return "sell"
    return None
