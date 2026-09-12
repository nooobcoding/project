"""04-settings Control 계층 — 알림 설정 조회/변경."""

from sqlalchemy.orm import Session

from app.models import NotificationSetting


def get_or_create_settings(db: Session, user_id: int) -> NotificationSetting:
    """설정 행이 없는 유저(마이그레이션 이전 가입자 등)에게도 기본값(전부 ON)을 보장한다
    (services/orders.py의 get_available_krw가 Balance 부재를 0으로 방어하는 것과 같은 패턴)."""
    setting = db.get(NotificationSetting, user_id)
    if setting is None:
        setting = NotificationSetting(user_id=user_id)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def update_settings(
    db: Session,
    user_id: int,
    signal_enabled: bool | None = None,
    exit_enabled: bool | None = None,
    error_enabled: bool | None = None,
) -> NotificationSetting:
    """토글 1개씩 즉시 저장하는 화면이라, 값이 주어진 필드만 반영한다 (04-settings.md 3장)."""
    setting = get_or_create_settings(db, user_id)
    if signal_enabled is not None:
        setting.signal_enabled = signal_enabled
    if exit_enabled is not None:
        setting.exit_enabled = exit_enabled
    if error_enabled is not None:
        setting.error_enabled = error_enabled
    db.commit()
    db.refresh(setting)
    return setting
