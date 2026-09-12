"""전략유형×지표 8개 조합의 신호 판정을 합성 캔들(종가 시퀀스)로 검증한다 (07 계획 Step 1).

각 조합마다 "신호가 나야 하는 케이스"를 손계산으로 확정하고, 크로스 계열(골든/데드크로스, RSI 50선,
MACD선-시그널선, 볼린저 상하단 돌파, MACD 히스토그램 저점/고점 반전)은 "직전 봉에서 이미 신호가
났으므로 다음 봉에서는 중복 발생하지 않는" 케이스를 짝지어 검증한다 — 중복 신호가 실매매에서 가장
위험한 버그이기 때문이다 (signals.py 모듈 docstring 참고). 레벨 계열(RSI 과매수/과매도, 볼린저 밴드
터치, MA 이격도)은 조건 미충족 시 신호가 없는지를 짝으로 검증한다 — 이 계열은 조건이 유지되는 동안
매 확정봉마다 반복 발생하는 것이 정상 동작이다.
"""

import pandas as pd

from app.strategy_engine.signals import (
    evaluate_counter_trend_bollinger,
    evaluate_counter_trend_ma,
    evaluate_counter_trend_macd,
    evaluate_counter_trend_rsi,
    evaluate_trend_bollinger,
    evaluate_trend_ma,
    evaluate_trend_macd,
    evaluate_trend_rsi,
)


def _closes(*values: float) -> pd.Series:
    return pd.Series([float(v) for v in values])


# ── 1. 추세추종 × MA (골든/데드크로스) ──────────────────────────────────────────


def test_trend_ma_golden_cross_buys():
    """MA2=[.,10,10,12.5], MA3=[.,.,10,11.667] → idx2에서 동률, idx3에서 단기가 장기를 상향 돌파."""
    closes = _closes(10, 10, 10, 15)
    signal = evaluate_trend_ma(closes, {"short_period": 2, "long_period": 3})
    assert signal == "buy"


def test_trend_ma_dead_cross_sells():
    closes = _closes(20, 20, 20, 15)
    signal = evaluate_trend_ma(closes, {"short_period": 2, "long_period": 3})
    assert signal == "sell"


def test_trend_ma_no_duplicate_after_cross():
    """골든크로스 다음 봉에서도 단기>장기가 유지될 뿐 새 교차가 없으면 None이어야 한다."""
    closes = _closes(10, 10, 10, 15, 16)
    signal = evaluate_trend_ma(closes, {"short_period": 2, "long_period": 3})
    assert signal is None


# ── 2. 역추세 × MA (이격도) ─────────────────────────────────────────────────


def test_counter_trend_ma_buys_when_deviation_below_threshold():
    """장기MA(3)=mean(100,100,90)=96.667, 가격 90의 이격도 -6.9% ≤ -5% → buy."""
    closes = _closes(100, 100, 100, 90)
    signal = evaluate_counter_trend_ma(closes, {"long_period": 3, "deviation_pct": 5})
    assert signal == "buy"


def test_counter_trend_ma_sells_when_deviation_above_threshold():
    """MA=mean(100,100,110)=103.333, 가격 110의 이격도 +6.45% ≥ +5% → sell."""
    closes = _closes(100, 100, 100, 110)
    signal = evaluate_counter_trend_ma(closes, {"long_period": 3, "deviation_pct": 5})
    assert signal == "sell"


def test_counter_trend_ma_no_signal_within_threshold():
    """MA=mean(100,100,99)=99.667, 이격도 -0.67%는 기준(5%) 미달 → None."""
    closes = _closes(100, 100, 100, 99)
    signal = evaluate_counter_trend_ma(closes, {"long_period": 3, "deviation_pct": 5})
    assert signal is None


# ── 3. 추세추종 × RSI (50선 돌파) ────────────────────────────────────────────


def test_trend_rsi_crosses_above_50_buys():
    """period=1(alpha=1)은 직전 한 봉의 등락만 반영해 RSI가 0/100을 오간다.
    closes=[10,9,11] → idx1 RSI=0(하락뿐), idx2 RSI=100(상승뿐) → 50선 상향 돌파."""
    closes = _closes(10, 9, 11)
    signal = evaluate_trend_rsi(closes, {"period": 1})
    assert signal == "buy"


def test_trend_rsi_crosses_below_50_sells():
    closes = _closes(10, 11, 9)
    signal = evaluate_trend_rsi(closes, {"period": 1})
    assert signal == "sell"


def test_trend_rsi_no_duplicate_while_staying_above():
    """idx2에서 이미 100(>50)이었고 idx3도 상승이라 RSI가 100에 머무를 뿐 새 돌파가 아니다."""
    closes = _closes(10, 9, 11, 12)
    signal = evaluate_trend_rsi(closes, {"period": 1})
    assert signal is None


# ── 4. 역추세 × RSI (과매수/과매도) ──────────────────────────────────────────


def test_counter_trend_rsi_buys_when_oversold():
    """period=1, closes=[10,9] → 하락뿐이라 RSI=0 ≤ 과매도(30) → buy."""
    closes = _closes(10, 9)
    signal = evaluate_counter_trend_rsi(closes, {"period": 1, "oversold": 30, "overbought": 70})
    assert signal == "buy"


def test_counter_trend_rsi_sells_when_overbought():
    closes = _closes(10, 11)
    signal = evaluate_counter_trend_rsi(closes, {"period": 1, "oversold": 30, "overbought": 70})
    assert signal == "sell"


def test_counter_trend_rsi_no_signal_when_neutral():
    """가격 변화 없음 → RSI=50(중립), 과매수·과매도 어느 쪽도 아니므로 None."""
    closes = _closes(10, 10)
    signal = evaluate_counter_trend_rsi(closes, {"period": 1, "oversold": 30, "overbought": 70})
    assert signal is None


# ── 5. 추세추종 × MACD (골든/데드크로스) ─────────────────────────────────────


def test_trend_macd_line_crosses_above_signal_buys():
    """closes=[1,2], (2,3,2) → macd_line=[0,0.1667], signal_line=[0,0.1111].
    diff=[0, 0.0556] → 0에서 양수로 막 돌파."""
    closes = _closes(1, 2)
    signal = evaluate_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal == "buy"


def test_trend_macd_line_crosses_below_signal_sells():
    closes = _closes(2, 1)
    signal = evaluate_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal == "sell"


def test_trend_macd_no_duplicate_while_diff_stays_positive():
    """closes=[1,2,3] → diff=[0,0.0556,0.0648] 모두 양수. idx1에서 이미 돌파했으므로 idx2는 새 신호가 아니다."""
    closes = _closes(1, 2, 3)
    signal = evaluate_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal is None


# ── 6. 역추세 × MACD (히스토그램 저점 반등/고점 하락전환, 3점 비교) ────────────


def test_counter_trend_macd_buys_on_histogram_rebound():
    """closes=[1,2,1,3] → histogram≈[0,0.0556,-0.0463,0.0879]. 직전(-0.0463)이 국지적 저점이고
    최신(0.0879)이 반등 → buy."""
    closes = _closes(1, 2, 1, 3)
    signal = evaluate_counter_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal == "buy"


def test_counter_trend_macd_sells_on_histogram_turn_down():
    """closes=[1,2,3,4] → histogram≈[0,0.0556,0.0648,0.0509]. 직전(0.0648)이 국지적 고점이고
    최신(0.0509)이 하락전환 → sell."""
    closes = _closes(1, 2, 3, 4)
    signal = evaluate_counter_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal == "sell"


def test_counter_trend_macd_none_when_insufficient_history():
    """3점 비교가 필요한데 2개 봉뿐이면 판정 불가 → None."""
    closes = _closes(1, 2)
    signal = evaluate_counter_trend_macd(closes, {"short_period": 2, "long_period": 3, "signal_period": 2})
    assert signal is None


# ── 7. 추세추종 × 볼린저밴드 (상/하단 돌파) ──────────────────────────────────


def test_trend_bollinger_breaks_above_upper_band_buys():
    """period=2, mult=0.5 — 2점 윈도우에서 upper=(a+3b)/4 공식대로 closes=[10,10,10,14]는
    idx2에서 price(10)<=upper(10), idx3에서 price(14)>upper(13) → buy."""
    closes = _closes(10, 10, 10, 14)
    signal = evaluate_trend_bollinger(closes, {"period": 2, "std_multiplier": 0.5})
    assert signal == "buy"


def test_trend_bollinger_breaks_below_lower_band_sells():
    closes = _closes(14, 14, 14, 10)
    signal = evaluate_trend_bollinger(closes, {"period": 2, "std_multiplier": 0.5})
    assert signal == "sell"


def test_trend_bollinger_no_duplicate_while_staying_above_band():
    """idx3에서 이미 상단 돌파(14>13)했고, idx4도 밴드 밖 유지일 뿐 새 돌파가 아니다."""
    closes = _closes(10, 10, 10, 14, 15)
    signal = evaluate_trend_bollinger(closes, {"period": 2, "std_multiplier": 0.5})
    assert signal is None


# ── 8. 역추세 × 볼린저밴드 (터치·하회/상회) ──────────────────────────────────


def test_counter_trend_bollinger_buys_on_lower_band_touch():
    """period=3, mult=0.3 — closes=[20,20,4]: mean=14.667, std≈7.543, lower≈12.404.
    마지막 가격 4 ≤ 12.404 → buy."""
    closes = _closes(20, 20, 4)
    signal = evaluate_counter_trend_bollinger(closes, {"period": 3, "std_multiplier": 0.3})
    assert signal == "buy"


def test_counter_trend_bollinger_sells_on_upper_band_touch():
    """closes=[4,4,20] (대칭): mean=9.333, std≈7.543, upper≈11.596. 마지막 가격 20 ≥ 11.596 → sell."""
    closes = _closes(4, 4, 20)
    signal = evaluate_counter_trend_bollinger(closes, {"period": 3, "std_multiplier": 0.3})
    assert signal == "sell"


def test_counter_trend_bollinger_no_signal_within_bands():
    """period=3, mult=2.0(기본값) — closes=[8,10,12]: mean=10, std≈1.633, band=[6.734,13.266].
    마지막 가격 12는 밴드 안쪽이라 None."""
    closes = _closes(8, 10, 12)
    signal = evaluate_counter_trend_bollinger(closes, {"period": 3, "std_multiplier": 2.0})
    assert signal is None
