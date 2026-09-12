"""백테스트 시뮬레이터 검증 (06 계획 A-4). DB·네트워크 없이 합성 캔들로 돈다.

이 파일이 실제로 지키려는 것은 "수익이 났는가"가 아니라 **시뮬레이터가 실매매와 같은 함수로
같은 순서의 판단을 하는가**다 (06 계획의 핵심 위험). 그래서 검증은 세 갈래로 간다:

  1. 비용(수수료·슬리피지)이 실제로 자산에서 빠지는가 — 손계산한 기댓값과 대조한다.
  2. 전략 상태(그리드 라인·DCA 진행)가 워커와 같은 함수로 갱신되는가.
  3. 실매매와 의도적으로 다르게 둔 지점(현금 부족 시 처리)이 의도대로 동작하는가.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.strategy_engine import backtest, dca, exits
from app.strategy_engine.runner import SlotSpec

FEE = Decimal("0.0005")  # 0.05%
SLIPPAGE = Decimal("0.001")  # 0.1%
CAPITAL = Decimal("10000000")
START = datetime(2026, 1, 1, tzinfo=timezone.utc)

GRID_PARAMS = {"lower_price": 100, "upper_price": 200, "grid_count": 4}


@dataclass
class Candle:
    """runner.CandleLike 최소 인터페이스 (opened_at/close)."""

    opened_at: datetime
    close: Decimal


def candles(*closes, minutes: int = 1) -> list[Candle]:
    return [
        Candle(opened_at=START + timedelta(minutes=index * minutes), close=Decimal(str(close)))
        for index, close in enumerate(closes)
    ]


# 단조 상승 구간에는 골든크로스가 없다 — 단기선이 이미 장기선 위에 있어 "교차"가 일어나지
# 않기 때문이다(signals.py는 크로스가 발생한 봉만 신호로 본다). 그래서 매수를 유도하려면 반드시
# 하락 구간이 앞에 와야 한다. 아래 모양들은 전부 140→100 하락으로 시작해 상승 전환에서
# 골든크로스가 나도록 맞춰 뒀다 (short 2 / long 4 기준, 진입가 108).
_DOWN = list(range(140, 96, -4))  # 140, 136, … 100
_UP = list(range(100, 164, 4))  # 100, 104, … 160

V_SHAPE = _DOWN + _UP  # 하락 후 반등 — 매수 1건
V_THEN_PEAK = V_SHAPE + list(range(160, 96, -4))  # 반등 후 재하락 — 데드크로스 매도까지
V_TO_MOON = _DOWN + list(range(100, 404, 4))  # 반등이 계속 — 익절 검증용
V_THEN_CRASH = _DOWN + [100, 104, 108, 112, 80, 80, 80, 80]  # 진입 직후 급락 — 손절 검증용


def spec(strategy_type: str = "trend", indicator: str | None = "ma", **kwargs) -> SlotSpec:
    params = kwargs.pop("params", {"short_period": 2, "long_period": 4})
    return SlotSpec(
        strategy_type=strategy_type,
        indicator=indicator,
        params=params,
        invest_amount=kwargs.pop("invest_amount", CAPITAL),
        **kwargs,
    )


def run(candle_list, slot_spec, *, fee=FEE, slippage=Decimal("0"), capital=CAPITAL):
    return backtest.run_backtest(candle_list, slot_spec, capital, fee, slippage)


# ── 기본 동작 ──────────────────────────────────────────────────────────────


def test_rising_market_profits_with_trend_following():
    """반등 국면에서 추세추종이 골든크로스에 진입해 자산이 늘어야 한다."""
    result = run(candles(*V_SHAPE), spec())

    assert any(trade.side == "buy" for trade in result.trades)
    assert result.final_asset > CAPITAL


def test_equity_curve_has_one_point_per_candle():
    """수익 곡선은 봉마다 한 점씩 쌓인다 — 차트 X축이 캔들 시간축과 같아야 한다."""
    candle_list = candles(*V_SHAPE)

    result = run(candle_list, spec())

    assert len(result.equity_curve) == len(candle_list)
    assert [point.at for point in result.equity_curve] == [c.opened_at for c in candle_list]


def test_flat_market_never_trades_and_preserves_capital():
    """신호가 없으면 거래도 없고 자산은 초기 투자금 그대로다."""
    result = run(candles(*[100] * 30), spec())

    assert result.trades == []
    assert result.final_asset == CAPITAL


def test_no_candles_returns_initial_capital():
    result = run([], spec())

    assert result.final_asset == CAPITAL
    assert result.equity_curve == []


# ── 비용이 실제로 차감되는가 ───────────────────────────────────────────────


def test_fee_and_slippage_reduce_final_asset():
    """같은 시나리오를 비용 있음/없음으로 두 번 돌려, 줄어든 자산이 정말 비용 때문임을 본다.

    수수료 0.05% + 슬리피지 0.1%가 매수·매도 양쪽에 붙으므로 왕복 총 비용은 약 0.3%다.
    """
    candle_list = candles(*V_THEN_PEAK)

    costly = run(candle_list, spec(), fee=FEE, slippage=SLIPPAGE)
    free = run(candle_list, spec(), fee=Decimal("0"), slippage=Decimal("0"))

    assert [t.side for t in costly.trades] == ["buy", "sell"]
    assert costly.final_asset < free.final_asset


def test_slippage_moves_fill_price_against_the_trade():
    """체결가 = 이론가 × (1 ± 슬리피지) — 매수는 비싸게, 매도는 싸게 (06-backtesting.md 3-A)."""
    candle_list = candles(*V_THEN_PEAK)
    result = run(candle_list, spec(), slippage=SLIPPAGE)

    buy, sell = result.trades
    buy_close = next(c.close for c in candle_list if c.opened_at == buy.executed_at)
    sell_close = next(c.close for c in candle_list if c.opened_at == sell.executed_at)

    assert buy.price == buy_close * (1 + SLIPPAGE)
    assert sell.price == sell_close * (1 - SLIPPAGE)


def test_buy_never_spends_more_than_available_cash():
    """수수료까지 포함한 지출이 현금을 넘지 않는다 — 잔고가 음수가 되면 안 된다."""
    result = run(candles(*V_TO_MOON), spec(), slippage=SLIPPAGE)

    assert result.cash >= 0


def test_sell_records_realized_profit_and_buy_does_not():
    """매도 행만 실현손익을 갖는다 (01-erd.md `backtest_trades.profit`)."""
    result = run(candles(*V_THEN_PEAK), spec())

    buy, sell = result.trades
    assert buy.profit is None
    assert sell.profit is not None


# ── 현금 부족 시 처리 (실매매와 의도적으로 다른 지점) ──────────────────────


def test_buy_is_capped_by_remaining_cash_not_skipped():
    """현금이 1회 진입 금액보다 적으면 **있는 만큼** 사서 거래가 계속돼야 한다.

    백테스팅은 초기투자금 = 1회 진입 금액이라, 왕복 한 번에 비용만큼만 줄어도 이후 매수를
    전부 건너뛰면 손실 전략이 "거래 2건"으로 끝난다 (06 계획 A-0 실측에서 발견한 문제).
    """
    # 골든/데드크로스가 여러 번 반복되도록 톱니 모양으로 만든다.
    prices: list[int] = []
    for _ in range(6):
        prices += list(range(100, 140, 4)) + list(range(140, 98, -4))

    result = run(candles(*prices), spec(), slippage=SLIPPAGE)

    assert len(result.trades) > 2
    assert result.cash >= 0


def test_buy_skipped_when_cash_cannot_afford_minimum_unit():
    """현금이 최소 단위(1사토시) 값어치도 안 되면 그 매수는 건너뛴다."""
    result = run(candles(*V_SHAPE), spec(), capital=Decimal("0"))

    assert result.trades == []
    assert result.final_asset == Decimal("0")


# ── 청산 (exits.py와 같은 판정) ────────────────────────────────────────────


def test_take_profit_exits_position():
    """익절 기준을 넘으면 신호와 무관하게 청산한다."""
    result = run(candles(*V_TO_MOON), spec(take_profit_pct=Decimal("10")))

    assert [t.reason for t in result.trades if t.side == "sell"][0] == exits.TAKE_PROFIT


def test_stop_loss_exits_position():
    """진입 직후 급락하면 데드크로스를 기다리지 않고 손절한다."""
    result = run(candles(*V_THEN_CRASH), spec(stop_loss_pct=Decimal("10")))

    assert exits.STOP_LOSS in [t.reason for t in result.trades]


def test_exit_blocks_reentry_on_the_same_candle():
    """청산이 일어난 봉에서는 재진입하지 않는다 (워커가 `_try_exit` 후 return하는 것과 같다)."""
    result = run(candles(*V_TO_MOON), spec(take_profit_pct=Decimal("10")))

    exit_times = [t.executed_at for t in result.trades if t.reason == exits.TAKE_PROFIT]
    buy_times = [t.executed_at for t in result.trades if t.side == "buy"]
    assert not set(exit_times) & set(buy_times)


# ── 그리드 — 라인 상태가 워커와 같은 방식으로 갱신되는가 ───────────────────


def _grid_spec(**kwargs) -> SlotSpec:
    return spec("grid", None, params=dict(GRID_PARAMS), invest_amount=Decimal("1000"), **kwargs)


def test_grid_fills_lines_as_price_falls_through_them():
    """가격이 라인까지 내려오면 그 라인이 채워진다 — 라인가 이하일 때만.

    라인은 [100, 125, 150, 175]. 210·180은 어느 라인에도 닿지 않고, 160→175 라인,
    130→150 라인, 110→125 라인이 차례로 채워진다. 100 라인은 110까지로는 닿지 않는다.
    """
    result = run(candles(210, 180, 160, 130, 110), _grid_spec(), capital=Decimal("1000"))

    assert [t.side for t in result.trades] == ["buy", "buy", "buy"]
    assert [str(t.price) for t in result.trades] == ["160", "130", "110"]
    assert result.position is not None


def test_grid_does_not_buy_below_lower_bound():
    """하한가 아래로 떨어진 뒤에는 매수하지 않는다 (grid.py 모듈 docstring)."""
    result = run(candles(210, 90, 80, 70), _grid_spec(), capital=Decimal("1000"))

    assert result.trades == []


def test_grid_sells_one_step_above_and_frees_the_line():
    """채워진 라인은 한 칸 위에서 실현되고, 비워져서 다시 매수 대상이 된다."""
    result = run(candles(210, 170, 210, 170), _grid_spec(), capital=Decimal("1000"))

    sides = [t.side for t in result.trades]
    assert sides.count("sell") >= 1
    # 매도 후 같은 라인이 다시 채워졌다 = 라인이 비워졌다는 뜻
    assert sides.count("buy") >= 2


def test_grid_breakout_liquidates_and_resets_lines():
    """하한가 이탈 시 전량 청산하고 라인을 전부 비운다 (worker._record_exit과 같은 처리)."""
    result = run(candles(210, 130, 90, 210, 130), _grid_spec(), capital=Decimal("1000"))

    reasons = [t.reason for t in result.trades]
    assert exits.GRID_BREAKOUT in reasons
    # 라인이 리셋됐으므로 가격이 범위로 돌아오면 다시 매수가 일어난다.
    breakout_index = reasons.index(exits.GRID_BREAKOUT)
    assert any(t.side == "buy" for t in result.trades[breakout_index + 1 :])


# ── DCA — 진행 상태가 워커와 같은 함수로 갱신되는가 ────────────────────────


def _dca_spec(**kwargs) -> SlotSpec:
    params = {
        "buy_period": "day",
        "amount_per_buy": "1000000",
        "end_condition": "count",
        "max_count": 3,
        "extra_buy_enabled": False,
    }
    return spec("dca", None, params=params, **kwargs)


def test_dca_buys_on_schedule_and_stops_at_max_count():
    """정기 매수가 주기마다 한 번씩 일어나고 종료조건에서 멈춘다."""
    day_candles = candles(*[100] * 10, minutes=60 * 24)

    result = run(day_candles, _dca_spec())

    buys = [t for t in result.trades if t.side == "buy"]
    assert len(buys) == 3
    assert all(t.reason == dca.SCHEDULED_BUY for t in buys)


def test_dca_spent_amount_includes_fee_and_stays_under_budget():
    """회당 지출은 **수수료를 포함해** 회당 매수금액을 넘지 않는다.

    수수료가 회당 금액 "안"에 들어가야 한다 — 밖에 두면 회차마다 조금씩 예산 상한을 넘는다
    (01-erd.md 3.2절). 그래서 체결액 > 순수 매매대금(가격×수량)이면서 회당 금액 이하여야 한다.
    """
    day_candles = candles(*[100] * 10, minutes=60 * 24)

    result = run(day_candles, _dca_spec())

    buys = [t for t in result.trades if t.side == "buy"]
    assert all(t.amount > t.price * t.quantity for t in buys)  # 수수료가 포함돼 있다
    assert all(t.amount <= Decimal("1000000") for t in buys)  # 회당 금액을 넘지 않는다
    assert sum(t.amount for t in buys) <= Decimal("3000000")


def test_dca_take_profit_ends_the_strategy():
    """목표 수익률 익절 후에는 더 매수하지 않는다 (슬롯 OFF에 해당)."""
    prices = [100] * 3 + [200] * 8
    day_candles = candles(*prices, minutes=60 * 24)

    result = run(day_candles, _dca_spec(take_profit_pct=Decimal("10")))

    reasons = [t.reason for t in result.trades]
    assert exits.DCA_TAKE_PROFIT in reasons
    assert not any(t.side == "buy" for t in result.trades[reasons.index(exits.DCA_TAKE_PROFIT) + 1 :])


def test_dca_budget_cap_is_never_exceeded():
    """종료조건이 예산 소진이어도 invest_amount를 넘겨 쓰지 않는다."""
    params = {
        "buy_period": "day",
        "amount_per_buy": "3000000",
        "end_condition": "budget",
        "extra_buy_enabled": False,
    }
    day_candles = candles(*[100] * 20, minutes=60 * 24)

    result = run(day_candles, spec("dca", None, params=params, invest_amount=Decimal("10000000")))

    spent = sum(t.amount for t in result.trades if t.side == "buy")
    assert spent <= Decimal("10000000")


# ── 호출자의 spec을 건드리지 않는다 ────────────────────────────────────────


def test_run_does_not_mutate_caller_spec():
    """같은 spec으로 두 번 돌리면 같은 결과가 나와야 한다 (전략 비교·재실행 대비)."""
    slot_spec = _grid_spec()
    candle_list = candles(210, 180, 160, 130)

    first = run(candle_list, slot_spec, capital=Decimal("1000"))
    second = run(candle_list, slot_spec, capital=Decimal("1000"))

    assert slot_spec.state == {}
    assert len(first.trades) == len(second.trades)
    assert first.final_asset == second.final_asset


@pytest.mark.parametrize("strategy_type,indicator", [("trend", "ma"), ("counter_trend", "rsi")])
def test_lookback_truncation_does_not_change_results(strategy_type, indicator, monkeypatch):
    """지표 창을 자르는 최적화(A-0)가 매매 판단을 바꾸지 않는지 — 자르지 않은 실행과 대조한다."""
    params = (
        {"short_period": 5, "long_period": 20}
        if indicator == "ma"
        else {"period": 14, "oversold": 30, "overbought": 70}
    )
    wave = candles(*[100 + (index * 7) % 60 for index in range(600)])
    slot_spec = spec(strategy_type, indicator, params=params)

    truncated = run(wave, slot_spec)
    monkeypatch.setattr(backtest, "INDICATOR_LOOKBACK", 10**9)
    full = run(wave, slot_spec)

    assert [(t.side, t.executed_at, t.quantity) for t in truncated.trades] == [
        (t.side, t.executed_at, t.quantity) for t in full.trades
    ]
