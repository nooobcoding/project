"""백테스트 성과지표 계산 (06-backtesting.md 3-B절 7개 지표).

입력은 `backtest.BacktestRun`(체결 목록·수익 곡선)과 벤치마크 계산에 쓸 캔들 시퀀스뿐이며, DB에
의존하지 않는 순수 함수다. 반환값은 `backtest_results`(01-erd.md) 컬럼과 1:1로 대응하도록
Decimal·NUMERIC 자릿수에 맞춰 반올림한다 — MDD·Sharpe 계산 도중의 통계 연산만 float를 쓴다
(indicators.py와 같은 방침: 저장·정산되는 값이 아니라 분석값이므로 float64가 이 규칙의 적용
대상이 아니다). 최종 반환 직전에 Decimal로 되돌려 자릿수를 맞춘다.
"""

import statistics
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from app.strategy_engine.backtest import BacktestRun, BacktestTrade, EquityPoint
from app.strategy_engine.runner import CandleLike

# 연환산 계수 (06-backtesting.md 3-B절 "Sharpe Ratio 계산 방법론" 구현 고정값).
_TRADING_DAYS_PER_YEAR = 252

_PERCENT_STEP = Decimal("0.0001")  # total_return/mdd/benchmark_return NUMERIC(10,4)
_RATIO_STEP = Decimal("0.001")  # win_rate NUMERIC(6,3)
_SHARPE_STEP = Decimal("0.0001")  # sharpe_ratio NUMERIC(10,4)


@dataclass(frozen=True)
class BacktestMetrics:
    """`backtest_results`(01-erd.md)의 성과지표 컬럼과 1:1 대응하는 값 모음."""

    total_return: Decimal  # %
    final_asset: Decimal
    trade_count: int
    win_rate: Decimal  # %
    mdd: Decimal  # %
    sharpe_ratio: Decimal
    benchmark_return: Decimal  # % — 동일 기간 단순 보유(Buy & Hold) 수익률

    @property
    def excess_return(self) -> Decimal:
        """벤치마크 대비 초과수익률(%) — 화면의 7번째 지표(06-backtesting.md 3-B절).

        DB에는 저장하지 않는다(01-erd.md `backtest_results`에 별도 컬럼 없음) — `total_return`과
        `benchmark_return`의 단순 차이라 저장할 이유가 없고, 호출부(API 응답·프론트)가 그때그때
        계산해 쓰면 된다.
        """
        return self.total_return - self.benchmark_return


def calc_total_return(initial_capital: Decimal, final_asset: Decimal) -> Decimal:
    """총수익률(%) = (최종자산 − 초기자본) / 초기자본 × 100."""
    if initial_capital <= 0:
        return Decimal(0)
    return _round_percent((final_asset - initial_capital) / initial_capital * 100)


def calc_trade_count(trades: Sequence[BacktestTrade]) -> int:
    """총 거래 횟수 — 매수 1건 + 매도 1건을 각각 1건으로 카운트한다(왕복 세트 아님, 06-backtesting.md 3-B절)."""
    return len(trades)


def calc_win_rate(trades: Sequence[BacktestTrade]) -> Decimal:
    """승률(%) = 실현손익 > 0인 매도 비율 (06-backtesting.md 3-B절).

    매도가 한 건도 없으면(신호가 한 번도 청산까지 안 갔거나 거래 자체가 없음) 0으로 둔다 —
    분모가 0인 비율은 정의되지 않으므로.
    """
    sells = [trade for trade in trades if trade.side == "sell"]
    if not sells:
        return Decimal(0)
    wins = sum(1 for trade in sells if trade.profit is not None and trade.profit > 0)
    return _round_ratio(Decimal(wins) / Decimal(len(sells)) * 100)


def calc_mdd(equity_curve: Sequence[EquityPoint]) -> Decimal:
    """MDD(%) — 자산 곡선의 최대 낙폭. 그 시점까지의 최고점 대비 하락폭 중 최댓값이다."""
    if not equity_curve:
        return Decimal(0)

    peak = equity_curve[0].asset
    max_drawdown = Decimal(0)
    for point in equity_curve:
        if point.asset > peak:
            peak = point.asset
        if peak > 0:
            drawdown = (peak - point.asset) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return _round_percent(max_drawdown)


def calc_sharpe_ratio(equity_curve: Sequence[EquityPoint]) -> Decimal:
    """Sharpe Ratio — 무위험수익률 0% 가정, 일간 수익률 평균/표준편차를 연환산(×√252)한다
    (06-backtesting.md 3-B절 "Sharpe Ratio 계산 방법론" 구현 고정값).

    자산 곡선은 봉 단위(분봉이면 하루에 여러 점)일 수 있으므로, 먼저 **날짜별 마지막 값**으로
    접어 일간 시계열을 만든 뒤 그 값들의 등락률로 일간 수익률을 구한다.

    표본(일간 수익률)이 2개 미만이거나 표준편차가 0이면 통계적으로 의미가 없으므로 0으로 둔다.
    """
    daily_closes = _fold_to_daily_closes(equity_curve)
    daily_returns = _period_returns(daily_closes)

    if len(daily_returns) < 2:
        return Decimal(0)

    mean = statistics.mean(daily_returns)
    stdev = statistics.stdev(daily_returns)  # 표본표준편차(ddof=1)
    if stdev == 0:
        return Decimal(0)

    sharpe = mean / stdev * (_TRADING_DAYS_PER_YEAR**0.5)
    return Decimal(str(sharpe)).quantize(_SHARPE_STEP, rounding=ROUND_HALF_UP)


def calc_benchmark_return(candles: Sequence[CandleLike]) -> Decimal:
    """벤치마크 수익률(%) = 동일 기간 단순 보유(Buy & Hold) — (마지막 종가 − 첫 종가) / 첫 종가 × 100
    (06-backtesting.md 3-B절). "그냥 사서 들고 있는 것보다 나은가"를 판단하는 기준선이다.
    """
    if not candles:
        return Decimal(0)
    first_close = candles[0].close
    if first_close <= 0:
        return Decimal(0)
    return _round_percent((candles[-1].close - first_close) / first_close * 100)


def calc_metrics(run: BacktestRun, candles: Sequence[CandleLike]) -> BacktestMetrics:
    """`BacktestRun` 하나로부터 7개 성과지표를 모두 계산한다."""
    return BacktestMetrics(
        total_return=calc_total_return(run.initial_capital, run.final_asset),
        final_asset=run.final_asset,
        trade_count=calc_trade_count(run.trades),
        win_rate=calc_win_rate(run.trades),
        mdd=calc_mdd(run.equity_curve),
        sharpe_ratio=calc_sharpe_ratio(run.equity_curve),
        benchmark_return=calc_benchmark_return(candles),
    )


def _fold_to_daily_closes(equity_curve: Sequence[EquityPoint]) -> list[Decimal]:
    """자산 곡선을 날짜별 마지막 값으로 접는다.

    `equity_curve`는 시간순으로 정렬돼 있다고 전제한다(backtest.py가 그렇게 쌓는다) — 같은
    날짜의 값을 dict에 반복해 덮어쓰면 그 날짜 키는 "마지막으로 쓰인 값"을 갖게 되고, 파이썬
    dict는 삽입 순서를 보존하므로(값을 덮어써도 최초 삽입 위치가 유지된다) 날짜가 앞으로 갈수록
    뒤에 오는 순서도 그대로 유지된다.
    """
    by_date: dict[date, Decimal] = {}
    for point in equity_curve:
        by_date[point.at.date()] = point.asset
    return list(by_date.values())


def _period_returns(closes: Sequence[Decimal]) -> list[float]:
    """연속한 두 값 사이의 등락률(소수 비율, float) 목록."""
    returns: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        if previous <= 0:
            continue
        returns.append(float((current - previous) / previous))
    return returns


def _round_percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_STEP, rounding=ROUND_HALF_UP)


def _round_ratio(value: Decimal) -> Decimal:
    return value.quantize(_RATIO_STEP, rounding=ROUND_HALF_UP)
