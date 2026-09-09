"""04-settings Boundary 계층 — /api/notifications/*. Control(services/notifications.py)만 호출한다."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.notifications import NotificationResponse
from app.services.auth import get_current_user
from app.services.notifications import (
    NotificationNotFoundError,
    list_notifications,
    mark_notification_read,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _to_response(notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type,
        message=notification.message,
        coin_symbol=notification.coin_symbol,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


@router.get("", response_model=list[NotificationResponse])
def get_notifications(
    unread: bool = Query(False),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> list[NotificationResponse]:
    notifications = list_notifications(db, current_user.id, unread_only=unread)
    return [_to_response(n) for n in notifications]


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def patch_notification_read(
    notification_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> NotificationResponse:
    try:
        notification = mark_notification_read(db, current_user.id, notification_id)
    except NotificationNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 알림입니다."
        )
    return _to_response(notification)
