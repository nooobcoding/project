"""백테스트 서비스 검증 (06 Phase D). 실제 postgres에 붙는다.

엔진 자체는 `test_backtest.py`(순수 함수)가 이미 검증하므로, 여기서는 **서비스가 엔진과 DB를
잇는 지점**만 본다: 날짜→캔들 시각 변환, % 단위 비율 변환, 오류 분기, 저장·조회 왕복,
그리고 결과를 지웠을 때 체결 상세가 CASCADE로 함께 사라지는지.

Upbit는 부르지 않는다 — `candles` 테이블에 합성 캔들을 직접 심고 `_fetch_upbit_candles`를
막아, 외부 호출 없이 캐시만으로 도는지까지 함께 확인한다.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import session_scope
from app.models import BacktestResult, BacktestTrade
from app.services import backtest as backtest_service
from app.services import candles as candles_service
from app.services.candles import CandleRangeTooLongError, CoinNotFoundError
from app.strategy_engine.metrics import BacktestMetrics

from .conftest import TEST_COIN_SYMBOL, requires_db

pytestmark = requires_db

DAY = timedelta(days=1)
# 오늘보다 확실히 과거이면서 넉넉한 구간 (진행 중인 봉에 걸리지 않게).
FIRST_DAY = date(2026, 1, 1)
LAST_DAY = date(2026, 2, 9)  # 40봉

MA_PARAMS = {"interval": "1d", "short_period": 2, "long_period": 4}


def _seed_daily_candles() -> None:
    """하락 후 반등하는 40일치 일봉 — 골든크로스가 나서 매수가 일어나는 모양이다
    (test_backtest.py의 V_SHAPE와 같은 이유로 단조 상승은 크로스가 없다)."""
    closes = list(range(140, 100, -2)) + list(range(100, 140, 2))
    raw = []
    for offset, close in enumerate(closes):
        opened_at = datetime.combine(FIRST_DAY, datetime.min.time(), tzinfo=timezone.utc) + DAY * offset
        raw.append(
            {
                "candle_date_time_utc": opened_at.strftime("%Y-%m-%dT%H:%M:%S"),
                "opening_price": close,
                "high_price": close + 1,
                "low_price": close - 1,
                "trade_price": close,
                "candle_acc_trade_volume": 1.0,
            }
        )
    with session_scope() as db:
        candles_service._upsert_candles(db, TEST_COIN_SYMBOL, "1d", raw)


def _clear_candles() -> None:
    with session_scope() as db:
        db.execute(
            text("DELETE FROM candles WHERE coin_symbol = :symbol"), {"symbol": TEST_COIN_SYMBOL}
        )


@pytest.fixture
def seeded_candles(monkeypatch, test_coin):
    """합성 캔들을 캐시에 심고 Upbit 호출을 막는다 — 외부 호출이 일어나면 테스트가 실패한다."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("캐시에 있는 기간인데 Upbit를 호출했다")

    _clear_candles()
    _seed_daily_candles()
    monkeypatch.setattr(candles_service, "_fetch_upbit_candles", _forbidden)
    yield
    _clear_candles()


def _execute(**overrides):
    kwargs = {
        "coin_symbol": TEST_COIN_SYMBOL,
        "strategy_type": "trend",
        "indicator": "ma",
        "params": MA_PARAMS,
        "start_date": FIRST_DAY,
        "end_date": LAST_DAY,
        "initial_capital": Decimal("10000000"),
        "fee_rate": Decimal("0.05"),  # % 단위
        "slippage_rate": Decimal("0.1"),  # % 단위
    }
    kwargs.update(overrides)
    with session_scope() as db:
        return backtest_service.execute_backtest(db, **kwargs)


# ── 실행 ───────────────────────────────────────────────────────────────────


def test_execute_backtest_runs_over_the_requested_range(seeded_candles):
    result = _execute()

    assert len(result.run.equity_curve) == 40  # 심어 둔 봉 수와 같다
    assert result.run.equity_curve[0].at.date() == FIRST_DAY
    assert result.run.equity_curve[-1].at.date() == LAST_DAY
    assert any(trade.side == "buy" for trade in result.run.trades)


def test_execute_backtest_computes_metrics(seeded_candles):
    result = _execute()

    assert result.metrics.trade_count == len(result.run.trades)
    assert result.metrics.final_asset == result.run.final_asset
    # 벤치마크는 140 → 138로 소폭 하락 (첫 종가 140, 마지막 종가 138)
    assert result.metrics.benchmark_return < 0


def test_percent_rates_are_converted_to_decimal_ratios(seeded_candles):
    """수수료·슬리피지를 % 단위 그대로 엔진에 넘기면 100배로 반영된다 (01-erd.md 3.2절).

    같은 시나리오를 비용 0으로 돌린 것과 비교해, 0.05%/0.1%가 자산을 아주 조금만 깎는지 본다 —
    변환을 빠뜨렸다면 5%/10%가 적용돼 차이가 훨씬 커진다.
    """
    costly = _execute()
    free = _execute(fee_rate=Decimal("0"), slippage_rate=Decimal("0"))

    gap_pct = (free.run.final_asset - costly.run.final_asset) / free.run.final_asset * 100
    assert 0 < gap_pct < 1  # 왕복 비용 0.3% 수준


def test_end_date_includes_the_whole_day(seeded_candles):
    """종료일 당일 봉이 포함돼야 한다 — 자정으로 넘기면 그 날이 통째로 빠진다."""
    result = _execute(end_date=FIRST_DAY + DAY * 4)

    assert result.run.equity_curve[-1].at.date() == FIRST_DAY + DAY * 4


def test_single_day_range_is_allowed(seeded_candles):
    result = _execute(start_date=FIRST_DAY, end_date=FIRST_DAY)

    assert len(result.run.equity_curve) == 1


# ── 오류 ───────────────────────────────────────────────────────────────────


def test_end_before_start_is_rejected(seeded_candles):
    with pytest.raises(backtest_service.InvalidDateRangeError):
        _execute(start_date=LAST_DAY, end_date=FIRST_DAY)


def test_range_without_candles_is_rejected(seeded_candles):
    """심어 둔 구간 밖(캐시도 없고 Upbit도 못 부르는 상황)이면 데이터 없음으로 끝난다."""
    with pytest.raises(AssertionError):  # _forbidden이 먼저 걸린다 = 채우려 시도했다는 뜻
        _execute(start_date=date(2025, 1, 1), end_date=date(2025, 1, 10))


def test_unknown_coin_is_rejected(seeded_candles):
    with pytest.raises(CoinNotFoundError):
        _execute(coin_symbol="NOSUCHCOIN")


def test_interval_limit_is_enforced(seeded_candles):
    """봉단위별 최대 기간은 캔들 서비스가 막고, 그 예외가 그대로 올라온다."""
    with pytest.raises(CandleRangeTooLongError):
        _execute(start_date=date(2020, 1, 1), end_date=date(2026, 2, 9))  # 일봉 5년 초과


def test_timeout_raises_backtest_timeout_error(seeded_candles, monkeypatch):
    """처리시간 상한을 넘기면 BacktestTimeoutError. 상한을 아주 짧게 낮춰 재현한다."""
    import time as time_module

    def _slow(*args, **kwargs):
        time_module.sleep(2)

    monkeypatch.setattr(backtest_service, "RUN_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(backtest_service, "run_backtest", _slow)

    with pytest.raises(backtest_service.BacktestTimeoutError):
        _execute()


# ── 저장·조회 ──────────────────────────────────────────────────────────────


def _save(user_id: int, label: str = "테스트-라벨", **overrides):
    metrics = BacktestMetrics(
        total_return=Decimal("12.3456"),
        final_asset=Decimal("11234560.0000"),
        trade_count=2,
        win_rate=Decimal("100.000"),
        mdd=Decimal("3.2100"),
        sharpe_ratio=Decimal("1.5000"),
        benchmark_return=Decimal("5.0000"),
    )
    kwargs = {
        "user_id": user_id,
        "label": label,
        "coin_symbol": TEST_COIN_SYMBOL,
        "strategy_type": "trend",
        "indicator": "ma",
        "params": MA_PARAMS,
        "start_date": FIRST_DAY,
        "end_date": LAST_DAY,
        "initial_capital": Decimal("10000000"),
        "fee_rate": Decimal("0.05"),
        "slippage_rate": Decimal("0.1"),
        "metrics": metrics,
        "equity_curve": [
            {"at": "2026-01-01T00:00:00+00:00", "asset": "10000000"},
            {"at": "2026-01-02T00:00:00+00:00", "asset": "11234560"},
        ],
        "trades": [
            {
                "side": "buy",
                "price": Decimal("100.5"),
                "quantity": Decimal("1.25"),
                "profit": None,
                "executed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "side": "sell",
                "price": Decimal("120.5"),
                "quantity": Decimal("1.25"),
                "profit": Decimal("24.5"),
                "executed_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
        ],
    }
    kwargs.update(overrides)
    with session_scope() as db:
        return backtest_service.save_result(db, **kwargs).id


def test_save_then_list_then_detail_round_trip(test_user, test_coin):
    result_id = _save(test_user)

    with session_scope() as db:
        listed = backtest_service.list_results(db, test_user)
        assert [row.id for row in listed] == [result_id]
        assert listed[0].label == "테스트-라벨"
        assert listed[0].total_return == Decimal("12.3456")

        # 세션이 닫히면 ORM 객체가 detach되므로 필요한 값은 안에서 꺼내 둔다.
        result, trades = backtest_service.get_result_detail(db, test_user, result_id)
        params = dict(result.params)
        start, end = result.start_date, result.end_date
        equity_curve = list(result.equity_curve)
        trade_rows = [(trade.side, trade.profit) for trade in trades]

    assert params == MA_PARAMS
    assert start == FIRST_DAY and end == LAST_DAY
    assert len(equity_curve) == 2
    assert equity_curve[0]["at"] == "2026-01-01T00:00:00+00:00"
    assert [side for side, _ in trade_rows] == ["buy", "sell"]
    assert trade_rows[0][1] is None
    assert trade_rows[1][1] == Decimal("24.5000")


def test_list_is_newest_first(test_user, test_coin):
    older = _save(test_user, label="먼저")
    newer = _save(test_user, label="나중")

    with session_scope() as db:
        assert [row.id for row in backtest_service.list_results(db, test_user)] == [newer, older]


def test_detail_of_another_users_result_is_not_found(test_user, test_coin):
    result_id = _save(test_user)

    with session_scope() as db:
        with pytest.raises(backtest_service.BacktestResultNotFoundError):
            backtest_service.get_result_detail(db, test_user + 999999, result_id)


def test_missing_result_is_not_found(test_user, test_coin):
    with session_scope() as db:
        with pytest.raises(backtest_service.BacktestResultNotFoundError):
            backtest_service.get_result_detail(db, test_user, 999999999)


def test_save_rejects_unknown_coin(test_user, test_coin):
    with pytest.raises(CoinNotFoundError):
        _save(test_user, coin_symbol="NOSUCHCOIN")


def test_deleting_a_result_cascades_to_its_trades(test_user, test_coin):
    """결과를 지우면 체결 상세도 함께 사라져야 한다 (FK ON DELETE CASCADE)."""
    result_id = _save(test_user)

    with session_scope() as db:
        assert db.query(BacktestTrade).filter_by(backtest_result_id=result_id).count() == 2
        db.delete(db.get(BacktestResult, result_id))

    with session_scope() as db:
        assert db.get(BacktestResult, result_id) is None
        assert db.query(BacktestTrade).filter_by(backtest_result_id=result_id).count() == 0
