"""02-dashboard Boundary 계층 — /api/dashboard/*, /api/watchlist. Control(services/dashboard.py)만 호출한다."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    RecentTradeResponse,
    WatchlistCreateRequest,
    WatchlistItemResponse,
)
from app.services.auth import get_current_user
from app.services.dashboard import (
    CoinNotFoundError,
    WatchlistFullError,
    WatchlistItemExistsError,
    add_watchlist_item,
    get_dashboard_summary,
    list_recent_trades,
    list_watchlist,
    remove_watchlist_item,
)

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_summary(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> DashboardSummaryResponse:
    summary = get_dashboard_summary(db, current_user.id)
    return DashboardSummaryResponse(
        krw_balance=str(summary["krw_balance"]),
        coin_valuation=str(summary["coin_valuation"]),
        profit_pct=str(summary["profit_pct"]),
    )


@router.get("/watchlist", response_model=list[WatchlistItemResponse])
def get_watchlist(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> list[WatchlistItemResponse]:
    items = list_watchlist(db, current_user.id)
    return [
        WatchlistItemResponse(coin_symbol=item.coin_symbol, sort_order=item.sort_order)
        for item in items
    ]


@router.post("/watchlist", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
def add_watchlist(
    payload: WatchlistCreateRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> WatchlistItemResponse:
    coin_symbol = payload.coin_symbol.upper()
    try:
        item = add_watchlist_item(db, current_user.id, coin_symbol)
    except CoinNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다."
        )
    except WatchlistItemExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 관심 코인으로 등록되어 있습니다."
        )
    except WatchlistFullError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="관심 코인은 최대 5개까지 등록할 수 있습니다.",
        )
    return WatchlistItemResponse(coin_symbol=item.coin_symbol, sort_order=item.sort_order)


@router.delete("/watchlist/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    symbol: str,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> None:
    remove_watchlist_item(db, current_user.id, symbol.upper())


@router.get("/dashboard/recent-trades", response_model=list[RecentTradeResponse])
def get_recent_trades(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> list[RecentTradeResponse]:
    return list_recent_trades(db, current_user.id)
