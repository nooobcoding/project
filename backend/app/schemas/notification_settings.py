"""04-settings 요청/응답 DTO — 알림 설정."""

from pydantic import BaseModel


class NotificationSettingsResponse(BaseModel):
    signal_enabled: bool
    exit_enabled: bool
    error_enabled: bool


class NotificationSettingsUpdateRequest(BaseModel):
    signal_enabled: bool | None = None
    exit_enabled: bool | None = None
    error_enabled: bool | None = None
