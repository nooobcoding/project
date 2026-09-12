"""성과지표 계산 검증 (06 계획 Phase B). 손계산 기댓값과 대조한다 — 특히 MDD·Sharpe.

Sharpe·MDD의 기댓값은 이 파일과 별개로 파이썬 인터프리터에서 손으로 재현해 얻은 값이다(파일
docstring이 아니라 각 테스트 함수 안에 계산 과정을 남긴다).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.strategy_engine.backtest import BacktestRun, BacktestTrade, EquityPoint
from app.strategy_engine.metrics import (
    calc_benchmark_return,
    calc_metrics,
    calc_mdd,
    calc_sharpe_ratio,
    calc_total_return,
    calc_trade_count,
    calc_win_rate,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class Candle:
    opened_at: datetime
    close: Decimal


def _equity(*assets: float, step_hours: int = 1) -> list[EquityPoint]:
    return [
        EquityPoint(at=START + timedelta(hours=index * step_hours), asset=Decimal(str(asset)))
        for index, asset in enumerate(assets)
    ]


def _daily_equity(*assets: float) -> list[EquityPoint]:
    """날짜가 하루씩 넘어가는 자산 곡선 — Sharpe의 "일간" 폴딩을 그대로 통과시키기 위함."""
    return [
        EquityPoint(at=START + timedelta(days=index), asset=Decimal(str(asset)))
        for index, asset in enumerate(assets)
    ]


def _trade(side: str, profit: Decimal | None = None) -> BacktestTrade:
    return BacktestTrade(
        side=side,
        price=Decimal("100"),
        quantity=Decimal("1"),
        amount=Decimal("100"),
        profit=profit,
        executed_at=START,
        reason="",
    )


# ── 총수익률 ───────────────────────────────────────────────────────────────


def test_total_return_percentage():
    assert calc_total_return(Decimal("1000000"), Decimal("1200000")) == Decimal("20.0000")


def test_total_return_negative_on_loss():
    assert calc_total_return(Decimal("1000000"), Decimal("900000")) == Decimal("-10.0000")


def test_total_return_guards_zero_capital():
    assert calc_total_return(Decimal("0"), Decimal("100")) == Decimal(0)


# ── 거래횟수 ───────────────────────────────────────────────────────────────


def test_trade_count_counts_buy_and_sell_separately():
    """매수 1건 + 매도 1건을 각각 1건으로 카운트한다(왕복 세트 아님, 06-backtesting.md 3-B절)."""
    trades = [_trade("buy"), _trade("sell", Decimal("10")), _trade("buy")]

    assert calc_trade_count(trades) == 3


def test_trade_count_zero_when_no_trades():
    assert calc_trade_count([]) == 0


# ── 승률 ───────────────────────────────────────────────────────────────────


def test_win_rate_counts_only_profitable_sells():
    """3매도 중 2건 실현손익>0 → 66.667% (2/3*100을 소수 3자리로 반올림)."""
    trades = [
        _trade("buy"),
        _trade("sell", Decimal("100")),
        _trade("sell", Decimal("-50")),
        _trade("sell", Decimal("30")),
    ]

    assert calc_win_rate(trades) == Decimal("66.667")


def test_win_rate_zero_profit_is_not_a_win():
    """실현손익이 정확히 0이면 승리가 아니다 — "> 0"이 기준이다."""
    trades = [_trade("sell", Decimal("0"))]

    assert calc_win_rate(trades) == Decimal(0)


def test_win_rate_zero_when_no_sells():
    """매도가 한 건도 없으면(진입 후 청산까지 못 간 경우) 승률은 0이다 — 분모 0 방지."""
    assert calc_win_rate([_trade("buy")]) == Decimal(0)
    assert calc_win_rate([]) == Decimal(0)


# ── MDD ────────────────────────────────────────────────────────────────────


def test_mdd_from_hand_calculated_peak_and_trough():
    """자산 곡선 100→120→80→90→150→60.

    누적 최고점 대비 낙폭: 120에서 80으로 (120-80)/120*100=33.33%, 150에서 60으로
    (150-60)/150*100=60% — 후자가 최댓값이므로 MDD=60%.
    """
    curve = _equity(100, 120, 80, 90, 150, 60)

    assert calc_mdd(curve) == Decimal("60.0000")


def test_mdd_rounds_to_four_decimals():
    """133→91: (133-91)/133*100 = 31.578947...% → 31.5789로 반올림 (NUMERIC(10,4))."""
    curve = _equity(133, 91)

    assert calc_mdd(curve) == Decimal("31.5789")


def test_mdd_zero_when_monotonically_rising():
    """계속 오르기만 하면 낙폭이 없다."""
    curve = _equity(100, 110, 120, 130)

    assert calc_mdd(curve) == Decimal(0)


def test_mdd_zero_when_curve_empty():
    assert calc_mdd([]) == Decimal(0)


def test_mdd_single_point_is_zero():
    assert calc_mdd(_equity(100)) == Decimal(0)


# ── Sharpe ─────────────────────────────────────────────────────────────────


def test_sharpe_matches_hand_calculated_value():
    """일간 자산 100,102,101,103,105.

    일간 수익률: [0.02, -0.00980392156862745, 0.019801980198019802, 0.019417475728155338]
    (statistics.mean/stdev로) mean≈0.012353883589386922, stdev(표본)≈0.014773849674109708
    Sharpe = mean/stdev*sqrt(252) ≈ 13.274253261411816 → 반올림 13.2743.
    """
    curve = _daily_equity(100, 102, 101, 103, 105)

    assert calc_sharpe_ratio(curve) == Decimal("13.2743")


def test_sharpe_folds_intraday_points_to_last_value_per_date():
    """하루 안의 여러 봉은 그날의 **마지막 값**만 남기고 접힌다.

    같은 날짜 안에 100→110→105(마지막)를 넣고 다음 날 마지막 값이 106이 되게 하면, 일간
    시계열은 [105, 106]과 동일해야 한다 — 중간값 110은 무시된다.
    """
    curve = [
        EquityPoint(at=START, asset=Decimal("100")),
        EquityPoint(at=START + timedelta(hours=1), asset=Decimal("110")),
        EquityPoint(at=START + timedelta(hours=2), asset=Decimal("105")),
        EquityPoint(at=START + timedelta(days=1), asset=Decimal("106")),
    ]
    folded_equivalent = _daily_equity(105, 106)

    assert calc_sharpe_ratio(curve) == calc_sharpe_ratio(folded_equivalent)


def test_sharpe_zero_when_fewer_than_two_daily_returns():
    """일간 수익률 표본이 2개 미만(=일간 종가 2개 이하)이면 통계적으로 무의미하므로 0."""
    assert calc_sharpe_ratio(_daily_equity(100)) == Decimal(0)
    assert calc_sharpe_ratio(_daily_equity(100, 105)) == Decimal(0)
    assert calc_sharpe_ratio([]) == Decimal(0)


def test_sharpe_zero_when_stdev_is_zero():
    """매일 등락률이 완전히 똑같으면(변동성 0) 나눗셈을 피해 0으로 둔다."""
    curve = _daily_equity(100, 110, 121, 133.1)  # 매일 정확히 +10%

    assert calc_sharpe_ratio(curve) == Decimal(0)


# ── 벤치마크(Buy & Hold) ─────────────────────────────────────────────────


def test_benchmark_return_is_buy_and_hold():
    """(마지막 종가 − 첫 종가) / 첫 종가 × 100 (06-backtesting.md 3-B절)."""
    candles = [Candle(START, Decimal("100")), Candle(START, Decimal("150"))]

    assert calc_benchmark_return(candles) == Decimal("50.0000")


def test_benchmark_return_zero_when_no_candles():
    assert calc_benchmark_return([]) == Decimal(0)


def test_benchmark_return_guards_zero_first_close():
    candles = [Candle(START, Decimal("0")), Candle(START, Decimal("100"))]

    assert calc_benchmark_return(candles) == Decimal(0)


# ── 종합 (calc_metrics) ──────────────────────────────────────────────────


def test_calc_metrics_aggregates_all_seven_stats():
    run = BacktestRun(
        initial_capital=Decimal("1000000"),
        final_asset=Decimal("1200000"),
        cash=Decimal("1200000"),
        position=None,
        trades=[_trade("buy"), _trade("sell", Decimal("100000"))],
        equity_curve=_daily_equity(1000000, 1100000, 1050000, 1200000),
    )
    candles = [Candle(START, Decimal("100")), Candle(START, Decimal("110"))]

    metrics = calc_metrics(run, candles)

    assert metrics.total_return == Decimal("20.0000")
    assert metrics.final_asset == Decimal("1200000")
    assert metrics.trade_count == 2
    assert metrics.win_rate == Decimal("100.000")
    assert metrics.benchmark_return == Decimal("10.0000")
    # 초과수익률 = 총수익률 − 벤치마크 (DB에 저장하지 않는 파생값)
    assert metrics.excess_return == Decimal("10.0000")
