"""04-settings Boundary 계층 — /api/settings/notifications. Control(services/notification_settings.py)만 호출한다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.notification_settings import (
    NotificationSettingsResponse,
    NotificationSettingsUpdateRequest,
)
from app.services.auth import get_current_user
from app.services.notification_settings import get_or_create_settings, update_settings

router = APIRouter(prefix="/api/settings/notifications", tags=["settings"])


def _to_response(setting) -> NotificationSettingsResponse:
    return NotificationSettingsResponse(
        signal_enabled=setting.signal_enabled,
        exit_enabled=setting.exit_enabled,
        error_enabled=setting.error_enabled,
    )


@router.get("", response_model=NotificationSettingsResponse)
def get_notification_settings(
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> NotificationSettingsResponse:
    return _to_response(get_or_create_settings(db, current_user.id))


@router.patch("", response_model=NotificationSettingsResponse)
def patch_notification_settings(
    payload: NotificationSettingsUpdateRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> NotificationSettingsResponse:
    setting = update_settings(
        db,
        current_user.id,
        signal_enabled=payload.signal_enabled,
        exit_enabled=payload.exit_enabled,
        error_enabled=payload.error_enabled,
    )
    return _to_response(setting)
