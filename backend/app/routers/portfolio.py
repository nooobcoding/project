"""08-portfolio Boundary 계층 — /api/portfolio/*. Control(services/portfolio.py)만 호출한다."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.portfolio import (
    CoinRef,
    HoldingItem,
    MonthlyProfit,
    PortfolioReportResponse,
    PortfolioSummaryResponse,
    TradeItem,
    TradeListResponse,
)
from app.services.auth import get_current_user
from app.services.portfolio import (
    InvalidPeriodError,
    export_trades_csv,
    get_report,
    get_summary,
    list_holdings,
    list_trades,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_INVALID_FILTER_DETAIL = "지원하지 않는 조회 조건입니다."
_KST = ZoneInfo("Asia/Seoul")


def _validated_filters(side: str | None, source: str | None) -> None:
    if side is not None and side not in ("buy", "sell"):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_INVALID_FILTER_DETAIL)
    if source is not None and source not in ("manual", "auto"):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_INVALID_FILTER_DETAIL)


@router.get("/summary", response_model=PortfolioSummaryResponse)
def get_portfolio_summary(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> PortfolioSummaryResponse:
    summary = get_summary(db, current_user.id)
    return PortfolioSummaryResponse(
        krw_balance=str(summary["krw_balance"]),
        coin_valuation=str(summary["coin_valuation"]),
        net_deposit=str(summary["net_deposit"]),
    )


@router.get("/holdings", response_model=list[HoldingItem])
def get_portfolio_holdings(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> list[HoldingItem]:
    return [
        HoldingItem(
            coin_symbol=item["coin_symbol"],
            korean_name=item["korean_name"],
            quantity=str(item["quantity"]),
            avg_buy_price=str(item["avg_buy_price"]),
            current_price=str(item["current_price"]),
            valuation=str(item["valuation"]),
            profit=str(item["profit"]),
            profit_pct=str(item["profit_pct"]),
        )
        for item in list_holdings(db, current_user.id)
    ]


@router.get("/trades", response_model=TradeListResponse)
def get_portfolio_trades(
    side: str | None = Query(None),
    source: str | None = Query(None),
    coin_symbol: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> TradeListResponse:
    _validated_filters(side, source)

    items, total, traded_coins = list_trades(
        db,
        current_user.id,
        side=side,
        source=source,
        coin_symbol=coin_symbol.upper() if coin_symbol else None,
        page=page,
        page_size=page_size,
    )
    return TradeListResponse(
        items=[
            TradeItem(
                id=item["id"],
                coin_symbol=item["coin_symbol"],
                korean_name=item["korean_name"],
                side=item["side"],
                source=item["source"],
                price=str(item["price"]),
                quantity=str(item["quantity"]),
                filled_at=item["filled_at"],
            )
            for item in items
        ],
        total=total,
        traded_coins=[CoinRef(symbol=c["symbol"], korean_name=c["korean_name"]) for c in traded_coins],
    )


@router.get("/trades/export")
def get_portfolio_trades_export(
    side: str | None = Query(None),
    source: str | None = Query(None),
    coin_symbol: str | None = Query(None),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> Response:
    """현재 필터 조건의 전체 내역을 CSV 파일로 내려준다 (08-portfolio.md 2-B).

    프론트는 이 GET을 `<a href>`로 열 수 없다 — JWT를 헤더로 실어야 하므로 fetch로 받아
    Blob으로 저장한다 (08-portfolio.md 2-B 구현 노트).
    """
    _validated_filters(side, source)

    csv_text = export_trades_csv(
        db,
        current_user.id,
        side=side,
        source=source,
        coin_symbol=coin_symbol.upper() if coin_symbol else None,
    )
    filename = f"trades_{datetime.now(_KST).strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/report", response_model=PortfolioReportResponse)
def get_portfolio_report(
    period: str = Query("1m"),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> PortfolioReportResponse:
    try:
        report = get_report(db, current_user.id, period)
    except InvalidPeriodError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="지원하지 않는 조회 기간입니다."
        )

    most_traded_coin = report["most_traded_coin"]
    return PortfolioReportResponse(
        start=report["start"],
        end=report["end"],
        most_traded_coin=(
            CoinRef(symbol=most_traded_coin["symbol"], korean_name=most_traded_coin["korean_name"])
            if most_traded_coin
            else None
        ),
        monthly_profits=[
            MonthlyProfit(month=item["month"], profit=str(item["profit"]))
            for item in report["monthly_profits"]
        ],
    )
