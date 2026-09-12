"""06-backtesting Control 계층 — 백테스트 실행·저장·조회.

Boundary(`routers/backtest.py`)만 이 모듈을 호출한다. 파라미터 스키마 검증
(`schemas/strategy_slots.validate_params_for`)은 07과 마찬가지로 라우터 책임이다.

**이 모듈이 직접 계산하는 것은 없다.** 실행은 전부 엔진에 위임한다:

    candles.get_candles_in_range → strategy_engine.backtest.run_backtest → metrics.calc_metrics

여기서 하는 일은 (1) 날짜를 캔들 조회용 시각으로 옮기고 (2) % 단위 비율을 소수로 바꾸고
(3) 처리시간 상한을 걸고 (4) 결과를 DB에 적재하는 것뿐이다.
"""

import concurrent.futures
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

# 엔진의 BacktestTrade(계산 결과 dataclass)와 이름이 같아 DB 행 쪽에 별칭을 붙인다.
from app.models import BacktestResult as BacktestResultRow
from app.models import BacktestTrade as BacktestTradeRow
from app.models import Coin
from app.services import candles as candles_service
from app.strategy_engine import costs
from app.strategy_engine.backtest import BacktestRun, run_backtest
from app.strategy_engine.metrics import BacktestMetrics, calc_metrics
from app.strategy_engine.runner import SlotSpec

# 06-backtesting.md 4장. 실질적 방어는 Phase C의 봉단위별 기간 상한
# (`candles.MAX_RANGE_DAYS`)이고, 이 값은 그 위에 두는 안전망이다.
RUN_TIMEOUT_SECONDS = 60


class InvalidDateRangeError(Exception):
    """종료일이 시작일보다 앞선 경우."""


class NoCandleDataError(Exception):
    """선택한 기간에 캔들이 하나도 없는 경우 (상장 이전 구간 등)."""


class BacktestTimeoutError(Exception):
    """`RUN_TIMEOUT_SECONDS` 안에 시뮬레이션이 끝나지 않은 경우."""


class BacktestResultNotFoundError(Exception):
    """존재하지 않거나 다른 사용자의 결과를 조회한 경우."""


@dataclass
class BacktestRunResult:
    """실행 산출물 — 엔진의 원자료와 그로부터 계산한 성과지표."""

    run: BacktestRun
    metrics: BacktestMetrics


def execute_backtest(
    db: Session,
    *,
    coin_symbol: str,
    strategy_type: str,
    indicator: str | None,
    params: dict[str, Any],
    start_date: date,
    end_date: date,
    initial_capital: Decimal,
    fee_rate: Decimal,
    slippage_rate: Decimal,
    stop_loss_pct: Decimal | None = None,
    take_profit_pct: Decimal | None = None,
) -> BacktestRunResult:
    """백테스트를 동기 실행한다 (저장하지 않는다).

    Args:
        params: `validate_params_for`를 이미 통과한 dict. 최상위 `interval` 키를 포함한다.
        fee_rate / slippage_rate: **% 단위**(예: 0.05 = 0.05%). 엔진에 넘기기 전 소수로 바꾼다.

    Raises:
        InvalidDateRangeError / NoCandleDataError / BacktestTimeoutError: 이 모듈 정의.
        candles.CoinNotFoundError / InvalidCandleRangeError / CandleRangeTooLongError:
            캔들 조회에서 그대로 전파된다 — 라우터가 함께 번역한다.
    """
    if end_date < start_date:
        raise InvalidDateRangeError()

    # 종료일은 그 날 전체를 포함시킨다 — get_candles_in_range가 봉 시작 시각으로 내림하므로,
    # 자정을 넘기면 분봉·시간봉에서 그 날 대부분이 잘려 나간다.
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

    candles = candles_service.get_candles_in_range(db, coin_symbol, params["interval"], start, end)
    if not candles:
        raise NoCandleDataError()

    spec = SlotSpec(
        strategy_type=strategy_type,
        indicator=indicator,
        params=params,
        # 백테스팅은 슬롯 = 전체 시뮬레이션이라 "투자금"과 "초기 자본"이 같은 값이다
        # (06-backtesting.md 2.4-1절·3-A절 — 설정 패널의 금액 입력은 초기 투자금 하나뿐이다).
        invest_amount=initial_capital,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )

    def _run() -> BacktestRun:
        return run_backtest(
            candles,
            spec,
            initial_capital,
            costs.percent_to_decimal(fee_rate),
            costs.percent_to_decimal(slippage_rate),
        )

    run = _run_with_timeout(_run)
    return BacktestRunResult(run=run, metrics=calc_metrics(run, candles))


def _run_with_timeout(work) -> BacktestRun:
    """시뮬레이션을 별도 스레드에서 돌려 처리시간 상한을 건다.

    `with ThreadPoolExecutor(...)`를 쓰면 안 된다 — 블록을 빠져나갈 때 `shutdown(wait=True)`가
    걸려 정작 오래 걸리는 계산이 끝날 때까지 기다리게 되고 타임아웃이 무의미해진다. 그래서
    타임아웃 경로에서는 `wait=False`로 즉시 손을 뗀다.

    버려진 스레드는 계산을 마칠 때까지 계속 돌지만 `run_backtest`는 DB를 건드리지 않는 순수
    함수라 부작용이 없다 — 결과만 버려진다.

    기존 라우터가 전부 동기 `def`라(FastAPI가 이미 스레드풀에서 돌린다) asyncio를 새로 들이지
    않고 같은 동기 스타일을 유지한다.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(work)
    try:
        run = future.result(timeout=RUN_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        executor.shutdown(wait=False)
        raise BacktestTimeoutError()
    executor.shutdown(wait=True)
    return run


def save_result(
    db: Session,
    *,
    user_id: int,
    label: str,
    coin_symbol: str,
    strategy_type: str,
    indicator: str | None,
    params: dict[str, Any],
    start_date: date,
    end_date: date,
    initial_capital: Decimal,
    fee_rate: Decimal,
    slippage_rate: Decimal,
    metrics: BacktestMetrics,
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> BacktestResultRow:
    """실행 결과를 라벨과 함께 저장한다.

    **감수한 트레이드오프**: `/run`이 결과를 저장하지 않고 `/results`가 클라이언트에게 되받는
    구조라, 이론상 조작된 수치를 저장할 수 있다. 저장 시점에 다시 계산하면 백테스트를 두 번
    돌리는 비용이 들어, 개인용 모의투자 도구 범위에서 감수하기로 했다 (06 계획 문서).
    코인 존재 여부만 방어적으로 확인한다.
    """
    if db.get(Coin, coin_symbol) is None:
        raise candles_service.CoinNotFoundError()

    result = BacktestResultRow(
        user_id=user_id,
        label=label,
        coin_symbol=coin_symbol,
        strategy_type=strategy_type,
        indicator=indicator,
        params=params,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        total_return=metrics.total_return,
        mdd=metrics.mdd,
        win_rate=metrics.win_rate,
        sharpe_ratio=metrics.sharpe_ratio,
        trade_count=metrics.trade_count,
        final_asset=metrics.final_asset,
        benchmark_return=metrics.benchmark_return,
        equity_curve=equity_curve,
        created_at=datetime.now(timezone.utc),
    )
    db.add(result)
    db.flush()  # 체결 행이 참조할 id 확보

    for trade in trades:
        db.add(BacktestTradeRow(backtest_result_id=result.id, **trade))

    db.commit()
    db.refresh(result)
    return result


def list_results(db: Session, user_id: int) -> list[BacktestResultRow]:
    """저장된 결과를 최신순으로 반환한다. 개인용 도구 규모라 페이지네이션을 두지 않는다."""
    return list(
        db.scalars(
            select(BacktestResultRow)
            .where(BacktestResultRow.user_id == user_id)
            .order_by(BacktestResultRow.created_at.desc())
        )
    )


def get_result_detail(
    db: Session, user_id: int, result_id: int
) -> tuple[BacktestResultRow, list[BacktestTradeRow]]:
    """결과 1건과 그 체결 목록을 반환한다. 남의 결과는 없는 것과 똑같이 취급한다."""
    result = db.get(BacktestResultRow, result_id)
    if result is None or result.user_id != user_id:
        raise BacktestResultNotFoundError()

    trades = list(
        db.scalars(
            select(BacktestTradeRow)
            .where(BacktestTradeRow.backtest_result_id == result_id)
            .order_by(BacktestTradeRow.executed_at, BacktestTradeRow.id)
        )
    )
    return result, trades
