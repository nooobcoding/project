"""확장판 8단계 Boundary 계층 — /api/admin/*. Control(services/admin.py)만 호출한다.

**권한 검사는 라우터 단위로 건다** (`dependencies=[Depends(require_admin)]`). 엔드포인트마다
의존성을 붙이는 방식이면 하나를 빠뜨리는 순간 일반 유저에게 열린다. 라우터에 걸어 두면
여기에 추가되는 엔드포인트는 빠짐없이 검사를 받는다. 행위자가 필요한 엔드포인트는
`Depends(require_admin)`을 다시 받는데, FastAPI가 요청 안에서 캐시하므로 쿼리는 늘지 않는다.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.routers.orders import _to_response as order_response
from app.routers.portfolio import _holding_item
from app.routers.strategy_slots import _to_response as slot_response
from app.routers.wallet import _to_response as transaction_response
from app.schemas.admin import (
    AdminUserDetailResponse,
    AdminUserItem,
    AdminUserListResponse,
    AdminUserSummary,
)
from app.services import admin as admin_service
from app.services.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

USER_NOT_FOUND = "해당 유저를 찾을 수 없습니다."


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    status: Literal["active", "suspended"] | None = None,
    has_active_slots: bool | None = None,
    q: str | None = Query(default=None, max_length=255),
    sort: Literal["newest", "oldest"] = "newest",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=admin_service.MAX_PAGE_SIZE),
    db: Session = Depends(get_session),
) -> AdminUserListResponse:
    items, total = admin_service.list_users(
        db,
        status=status,
        has_active_slots=has_active_slots,
        email_query=q.strip() if q else None,
        oldest_first=sort == "oldest",
        page=page,
        page_size=page_size,
    )
    return AdminUserListResponse(
        items=[
            AdminUserItem(
                **{k: v for k, v in item.items() if k not in ("krw_balance", "total_valuation")},
                krw_balance=str(item["krw_balance"]),
                total_valuation=str(item["total_valuation"]),
            )
            for item in items
        ],
        total=total,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def get_user(user_id: int, db: Session = Depends(get_session)) -> AdminUserDetailResponse:
    try:
        detail = admin_service.get_user_detail(db, user_id)
    except admin_service.UserNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND)

    user, summary = detail["user"], detail["summary"]
    return AdminUserDetailResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        summary=AdminUserSummary(
            krw_balance=str(summary["krw_balance"]),
            withdrawable_krw=str(detail["withdrawable_krw"]),
            coin_valuation=str(summary["coin_valuation"]),
            total_valuation=str(summary["krw_balance"] + summary["coin_valuation"]),
            net_deposit=str(summary["net_deposit"]),
        ),
        holdings=[_holding_item(item) for item in detail["holdings"]],
        slots=[slot_response(slot) for slot in detail["slots"]],
        pending_orders=[order_response(order) for order in detail["pending_orders"]],
        recent_orders=[order_response(order) for order in detail["recent_orders"]],
        recent_transactions=[transaction_response(tx) for tx in detail["recent_transactions"]],
    )
