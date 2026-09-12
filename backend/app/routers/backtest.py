"""06-backtesting Boundary 계층 — /api/backtest/*. Control(services/backtest.py)만 호출한다."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import BacktestResult as BacktestResultRow
from app.models import BacktestTrade as BacktestTradeRow
from app.schemas.backtest import (
    BacktestMetricsOut,
    BacktestResultDetail,
    BacktestResultSummary,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestSaveRequest,
    BacktestTradeOut,
    EquityPointOut,
)
from app.schemas.strategy_slots import validate_dca_budget, validate_params_for
from app.services.auth import get_current_user
from app.services.backtest import (
    BacktestResultNotFoundError,
    BacktestTimeoutError,
    InvalidDateRangeError,
    NoCandleDataError,
    delete_result,
    execute_backtest,
    get_result_detail,
    list_results,
    save_result,
)
from app.services.candles import (
    CandleRangeTooLongError,
    CoinNotFoundError,
    InvalidCandleRangeError,
)
from app.strategy_engine.metrics import BacktestMetrics

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_PARAM_VALIDATION_ERROR_DETAIL = "기준값은 0~100 사이의 값을 입력해주세요."
_INVALID_INPUT_DETAIL = "올바르게 입력해주세요."
_DATE_RANGE_DETAIL = "종료일은 시작일 이후로 설정해주세요."


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_INVALID_INPUT_DETAIL)


def _require_decimal(value: str) -> Decimal:
    parsed = _parse_decimal(value)
    if parsed is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_INVALID_INPUT_DETAIL)
    return parsed


def _validated_params(strategy_type: str, indicator: str | None, params: dict) -> dict:
    """07 라우터와 같은 방식으로 전략유형×지표 조합별 스키마에 맞춰 검증한다."""
    try:
        return validate_params_for(strategy_type, indicator, params)
    except ValidationError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=_PARAM_VALIDATION_ERROR_DETAIL
        )
    except KeyError:
        # 전략유형과 지표 조합이 아예 없는 경우 (예: 그리드인데 지표를 함께 보냄)
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_INVALID_INPUT_DETAIL)


def _metrics_response(metrics: BacktestMetrics) -> BacktestMetricsOut:
    return BacktestMetricsOut(
        total_return=str(metrics.total_return),
        final_asset=str(metrics.final_asset),
        trade_count=metrics.trade_count,
        win_rate=str(metrics.win_rate),
        mdd=str(metrics.mdd),
        sharpe_ratio=str(metrics.sharpe_ratio),
        benchmark_return=str(metrics.benchmark_return),
        excess_return=str(metrics.excess_return),
    )


@router.post("/run", response_model=BacktestRunResponse)
def post_backtest_run(
    payload: BacktestRunRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> BacktestRunResponse:
    """백테스트를 동기 실행하고 결과만 돌려준다 (저장하지 않는다, 06-backtesting.md 6장)."""
    validated_params = _validated_params(payload.strategy_type, payload.indicator, payload.params)

    initial_capital = _require_decimal(payload.initial_capital)
    fee_rate = _require_decimal(payload.fee_rate)
    slippage_rate = _require_decimal(payload.slippage_rate)

    # 06-backtesting.md 2.4-1절 — "회당 매수금액 × 총 횟수"가 총 상한을 넘지 않아야 한다.
    # 백테스팅에서는 초기 투자금이 그 상한이다 (services/backtest.py의 invest_amount 주석 참고).
    if payload.strategy_type == "dca":
        try:
            validate_dca_budget(validated_params, initial_capital)
        except ValueError as exc:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        result = execute_backtest(
            db,
            coin_symbol=payload.coin_symbol.upper(),
            strategy_type=payload.strategy_type,
            indicator=payload.indicator,
            params=validated_params,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            stop_loss_pct=_parse_decimal(payload.stop_loss_pct),
            take_profit_pct=_parse_decimal(payload.take_profit_pct),
        )
    except (InvalidDateRangeError, InvalidCandleRangeError):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_DATE_RANGE_DETAIL)
    except CoinNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다.")
    except CandleRangeTooLongError as exc:
        # 봉단위별 상한 문구를 예외가 이미 완성해 들고 있다 (services/candles.py).
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=exc.message)
    except NoCandleDataError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="선택한 기간의 시세 데이터가 없습니다."
        )
    except BacktestTimeoutError:
        raise HTTPException(
            status_code=http_status.HTTP_408_REQUEST_TIMEOUT,
            detail="처리 시간이 초과되었습니다. 기간을 단축하거나 다시 시도해주세요.",
        )

    return BacktestRunResponse(
        coin_symbol=payload.coin_symbol.upper(),
        strategy_type=payload.strategy_type,
        indicator=payload.indicator,
        params=validated_params,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_capital=str(initial_capital),
        fee_rate=str(fee_rate),
        slippage_rate=str(slippage_rate),
        metrics=_metrics_response(result.metrics),
        equity_curve=[
            EquityPointOut(at=point.at, asset=str(point.asset)) for point in result.run.equity_curve
        ],
        trades=[
            BacktestTradeOut(
                side=trade.side,
                price=str(trade.price),
                quantity=str(trade.quantity),
                profit=str(trade.profit) if trade.profit is not None else None,
                executed_at=trade.executed_at,
            )
            for trade in result.run.trades
        ],
    )


@router.post("/results", response_model=BacktestResultDetail, status_code=http_status.HTTP_201_CREATED)
def post_backtest_result(
    payload: BacktestSaveRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> BacktestResultDetail:
    """`/run`이 돌려준 결과를 라벨과 함께 저장한다 (수치는 재계산하지 않는다 — services 주석 참고)."""
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="라벨을 입력해주세요.")

    metrics = BacktestMetrics(
        total_return=_require_decimal(payload.metrics.total_return),
        final_asset=_require_decimal(payload.metrics.final_asset),
        trade_count=payload.metrics.trade_count,
        win_rate=_require_decimal(payload.metrics.win_rate),
        mdd=_require_decimal(payload.metrics.mdd),
        sharpe_ratio=_require_decimal(payload.metrics.sharpe_ratio),
        benchmark_return=_require_decimal(payload.metrics.benchmark_return),
    )

    try:
        result = save_result(
            db,
            user_id=current_user.id,
            label=label,
            coin_symbol=payload.coin_symbol.upper(),
            strategy_type=payload.strategy_type,
            indicator=payload.indicator,
            params=payload.params,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_capital=_require_decimal(payload.initial_capital),
            fee_rate=_require_decimal(payload.fee_rate),
            slippage_rate=_require_decimal(payload.slippage_rate),
            equity_curve=[
                {"at": point.at.isoformat(), "asset": point.asset}
                for point in payload.equity_curve
            ],
            trades=[
                {
                    "side": trade.side,
                    "price": _require_decimal(trade.price),
                    "quantity": _require_decimal(trade.quantity),
                    "profit": _parse_decimal(trade.profit),
                    "executed_at": trade.executed_at,
                }
                for trade in payload.trades
            ],
            metrics=metrics,
        )
    except CoinNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다.")

    # 저장된 체결까지 담아 돌려준다 — 프론트가 저장 직후 상세를 다시 조회하지 않아도 되게.
    saved, saved_trades = get_result_detail(db, current_user.id, result.id)
    return _detail_response(saved, saved_trades)


@router.get("/results", response_model=list[BacktestResultSummary])
def get_backtest_results(
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> list[BacktestResultSummary]:
    return [
        BacktestResultSummary(
            id=result.id,
            label=result.label,
            coin_symbol=result.coin_symbol,
            strategy_type=result.strategy_type,
            indicator=result.indicator,
            total_return=str(result.total_return),
            final_asset=str(result.final_asset),
            created_at=result.created_at,
        )
        for result in list_results(db, current_user.id)
    ]


@router.get("/results/{result_id}", response_model=BacktestResultDetail)
def get_backtest_result(
    result_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> BacktestResultDetail:
    try:
        result, trades = get_result_detail(db, current_user.id, result_id)
    except BacktestResultNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 백테스트 결과입니다."
        )
    return _detail_response(result, trades)


@router.delete("/results/{result_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_backtest_result(
    result_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> None:
    try:
        delete_result(db, current_user.id, result_id)
    except BacktestResultNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 백테스트 결과입니다."
        )


def _detail_response(
    result: BacktestResultRow, trades: list[BacktestTradeRow]
) -> BacktestResultDetail:
    return BacktestResultDetail(
        id=result.id,
        label=result.label,
        created_at=result.created_at,
        coin_symbol=result.coin_symbol,
        strategy_type=result.strategy_type,
        indicator=result.indicator,
        params=result.params,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=str(result.initial_capital),
        fee_rate=str(result.fee_rate),
        slippage_rate=str(result.slippage_rate),
        metrics=BacktestMetricsOut(
            total_return=str(result.total_return),
            final_asset=str(result.final_asset),
            trade_count=result.trade_count,
            win_rate=str(result.win_rate),
            mdd=str(result.mdd),
            sharpe_ratio=str(result.sharpe_ratio),
            benchmark_return=str(result.benchmark_return),
            excess_return=str(result.total_return - result.benchmark_return),
        ),
        equity_curve=[
            EquityPointOut(at=point["at"], asset=point["asset"]) for point in result.equity_curve
        ],
        trades=[
            BacktestTradeOut(
                side=trade.side,
                price=str(trade.price),
                quantity=str(trade.quantity),
                profit=str(trade.profit) if trade.profit is not None else None,
                executed_at=trade.executed_at,
            )
            for trade in trades
        ],
    )
