"""04-settings 요청/응답 DTO — 알림 목록."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    type: Literal["signal", "exit", "error"]
    message: str
    coin_symbol: str | None
    is_read: bool
    created_at: datetime
