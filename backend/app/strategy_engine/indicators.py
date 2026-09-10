"""기술적 지표 계산 (06-backtesting.md 2.2절, 2.6절 `indicators.py`).

입력은 종가 시퀀스(`pandas.Series`)뿐이며 DB·모델에 의존하지 않는 순수 함수다 — 06-backtesting과
07-auto-trading이 동일한 함수를 공유한다 (06-backtesting.md 2.6절 "runner.py가 06과 07의 공유 지점").

지표 계산은 신호 판정을 위한 분석값이므로 `pandas`의 `float64`를 사용한다. 01-erd.md 3.3절의
"부동소수점을 금액·수량·가격에 사용하지 않는다"는 규칙은 정산(주문·체결·잔고) 값에 적용되는 것이며,
여기서 계산하는 지표값 자체는 저장·정산되지 않고 신호 판정에만 쓰이므로 이 규칙의 적용 대상이 아니다.
"""

import numpy as np
import pandas as pd


def calc_ma(closes: pd.Series, period: int) -> pd.Series:
    """단순이동평균(SMA)을 계산한다. 앞쪽 `period - 1`개는 NaN이다."""
    return closes.rolling(window=period).mean()


def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """RSI(상대강도지수)를 계산한다 (Wilder 평활 방식 — `구현 고정값`).

    평균 상승폭/하락폭을 `alpha = 1/period`인 지수이동평균(EWM)으로 구한다. 이는 Wilder가 원래
    제안한 평활 계수와 동일하며, 이 프로젝트에서 RSI 계산 방식을 이 하나로 고정한다
    (06-backtesting.md 2.2절 "Sharpe Ratio 계산 방법론" 항목과 같은 취지의 구현 고정값).

    경계 처리를 `Series.mask` 대신 `numpy.where`로 하는 이유는 **속도**다 (06 계획 A-0 실측).
    백테스팅은 봉마다 이 함수를 다시 부르므로(1분봉 7일이면 10,080회) 호출당 pandas 오버헤드가
    그대로 총시간이 된다 — mask 체인은 매번 Series를 새로 만들어 호출당 ~2.4ms였고 numpy로
    바꾸면 ~1.0ms다. 계산 결과는 비트 단위로 동일하다(실측 max diff 0.0).
    """
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().to_numpy()

    # avg_gain/avg_loss 둘 다 0(구간 내 가격이 전혀 안 움직임)이면 0/0=NaN이 되므로 별도 처리한다.
    # 하락 없이 상승만 있었으면 100, 상승 없이 하락만 있었으면 0, 둘 다 없었으면 중립 50으로 고정한다.
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))
    rsi = np.where((avg_gain == 0) & (avg_loss == 0), 50.0, rsi)
    rsi = np.where((avg_gain > 0) & (avg_loss == 0), 100.0, rsi)
    rsi = np.where((avg_gain == 0) & (avg_loss > 0), 0.0, rsi)
    return pd.Series(rsi, index=closes.index)


def calc_macd(
    closes: pd.Series, short_period: int = 12, long_period: int = 26, signal_period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD선, 시그널선, 히스토그램을 계산한다.

    Returns:
        (macd_line, signal_line, histogram) — histogram = macd_line - signal_line
    """
    ema_short = closes.ewm(span=short_period, adjust=False).mean()
    ema_long = closes.ewm(span=long_period, adjust=False).mean()
    macd_line = ema_short - ema_long
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(
    closes: pd.Series, period: int = 20, std_multiplier: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """볼린저 밴드(중심선/상단/하단)를 계산한다.

    표준편차는 모집단 표준편차(ddof=0)를 쓴다 — 중심선(SMA) 자체가 해당 구간 전체를 모집단으로
    보는 계산이므로 표준편차도 동일 구간을 모집단으로 취급하는 쪽이 일관적이다.

    Returns:
        (mid, upper, lower)
    """
    mid = calc_ma(closes, period)
    std = closes.rolling(window=period).std(ddof=0)
    upper = mid + std_multiplier * std
    lower = mid - std_multiplier * std
    return mid, upper, lower
