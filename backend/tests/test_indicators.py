"""지표 계산 함수를 손계산 기댓값과 대조한다 (07 계획 Step 1).

각 테스트는 결과 배열 전체가 아니라 특정 인덱스 값만 검증한다 — 값이 정확히 무엇이어야 하는지
주석에 계산 과정을 남겨, 나중에 지표 구현을 바꿀 때 이 기댓값이 왜 그 값인지 바로 알 수 있게 한다.
"""

import pandas as pd
import pytest

from app.strategy_engine.indicators import calc_bollinger, calc_macd, calc_ma, calc_rsi


def test_calc_ma_simple_average():
    """MA(3)은 직전 3개 종가의 단순평균이다."""
    closes = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    ma = calc_ma(closes, period=3)

    assert pd.isna(ma.iloc[0])
    assert pd.isna(ma.iloc[1])
    assert ma.iloc[2] == pytest.approx(2.0)  # mean(1,2,3)
    assert ma.iloc[-1] == pytest.approx(9.0)  # mean(8,9,10)


def test_calc_rsi_wilder_smoothing():
    """RSI(2)를 Wilder 평활(alpha=1/period)로 직접 계산해 대조한다.

    closes=[10,12,11,13,14] → delta=[NaN,2,-1,2,1] → gain=[NaN,2,0,2,1], loss=[NaN,0,1,0,0].
    ewm(alpha=0.5, adjust=False)는 첫 유효값을 시드로 그대로 쓰고 이후 재귀식을 적용한다:
      avg_gain = [NaN, 2.0, 1.0, 1.5, 1.25]
      avg_loss = [NaN, 0.0, 0.5, 0.25, 0.125]
    idx1은 avg_loss=0이라 100으로 마스킹, 이후는 rs=avg_gain/avg_loss로 정상 계산한다.
    """
    closes = pd.Series([10.0, 12.0, 11.0, 13.0, 14.0])
    rsi = calc_rsi(closes, period=2)

    assert pd.isna(rsi.iloc[0])
    assert rsi.iloc[1] == pytest.approx(100.0)
    assert rsi.iloc[2] == pytest.approx(100 - 100 / 3)  # rs=1.0/0.5=2.0
    assert rsi.iloc[3] == pytest.approx(100 - 100 / 7)  # rs=1.5/0.25=6.0
    assert rsi.iloc[4] == pytest.approx(100 - 100 / 11)  # rs=1.25/0.125=10.0


def test_calc_rsi_no_movement_is_neutral_50():
    """가격이 전혀 움직이지 않으면(avg_gain=avg_loss=0) RSI는 중립값 50이어야 한다."""
    closes = pd.Series([10.0, 10.0, 10.0])
    rsi = calc_rsi(closes, period=2)

    assert rsi.iloc[-1] == pytest.approx(50.0)


def test_calc_macd_hand_traced():
    """MACD(2,3,2)를 EMA 재귀식으로 직접 손계산해 대조한다.

    closes=[1,2,3,4], alpha_short=2/3, alpha_long=1/2, alpha_signal=2/3 (모두 ewm span 공식).
    ema_short=[1, 5/3, 23/9, 95/27], ema_long=[1, 1.5, 2.25, 3.125]
    macd_line = ema_short - ema_long → 마지막 값 95/27 - 3.125 ≈ 0.393519
    signal_line은 macd_line을 다시 alpha=2/3로 평활 → 마지막 값 ≈ 0.342593
    histogram = macd_line - signal_line ≈ 0.050926
    """
    closes = pd.Series([1.0, 2.0, 3.0, 4.0])
    macd_line, signal_line, histogram = calc_macd(closes, short_period=2, long_period=3, signal_period=2)

    assert macd_line.iloc[-1] == pytest.approx(0.393519, abs=1e-5)
    assert signal_line.iloc[-1] == pytest.approx(0.342593, abs=1e-5)
    assert histogram.iloc[-1] == pytest.approx(0.050926, abs=1e-5)


def test_calc_bollinger_population_std():
    """볼린저밴드(3, 승수2.0)를 모집단 표준편차로 손계산해 대조한다.

    closes=[1,2,3,4,5]. idx2 윈도우(1,2,3): mean=2, std=sqrt(2/3)≈0.8165 → upper≈3.633, lower≈0.367.
    idx4 윈도우(3,4,5): mean=4, std도 동일(대칭 데이터라 분산 동일) → upper≈5.633, lower≈2.367.
    """
    closes = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    mid, upper, lower = calc_bollinger(closes, period=3, std_multiplier=2.0)

    assert mid.iloc[2] == pytest.approx(2.0)
    assert upper.iloc[2] == pytest.approx(3.632993, abs=1e-5)
    assert lower.iloc[2] == pytest.approx(0.367007, abs=1e-5)

    assert mid.iloc[4] == pytest.approx(4.0)
    assert upper.iloc[4] == pytest.approx(5.632993, abs=1e-5)
    assert lower.iloc[4] == pytest.approx(2.367007, abs=1e-5)
