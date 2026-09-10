"""04-settings Control 계층 — 알림 목록 조회/읽음 처리.

알림 생성(신호/손절익절/오류 발생 시 insert)은 07-auto-trading 구현 시 붙는다
(04-settings.md 1장) — 이 모듈은 조회/읽음 처리만 다룬다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, NotificationSetting


class NotificationNotFoundError(Exception):
    """존재하지 않거나 본인 소유가 아닌 알림을 읽음 처리하려는 경우."""


def is_type_enabled(settings: NotificationSetting | None, type_: str) -> bool:
    """알림 종류별 수신 설정 (04-settings.md 2-B). 알림을 적재하는 쪽(체결 훅·워커)이 공유한다.

    설정 행이 없으면 컬럼 기본값과 동일하게 전부 허용한다. `get_or_create_settings`를 쓰지
    않는 이유: 그 함수는 내부에서 commit을 하는데, 체결 훅은 fill_order의 트랜잭션 한가운데서
    돌기 때문에 여기서 커밋이 일어나면 체결이 미완성 상태로 확정돼 버린다.
    """
    if settings is None:
        return True
    if type_ == "signal":
        return settings.signal_enabled
    if type_ == "exit":
        return settings.exit_enabled
    return settings.error_enabled


def list_notifications(
    db: Session, user_id: int, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    conditions = [Notification.user_id == user_id]
    if unread_only:
        conditions.append(Notification.is_read.is_(False))
    return list(
        db.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def mark_notification_read(db: Session, user_id: int, notification_id: int) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotificationNotFoundError()
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification
