"""확장판 8단계 Control 계층 — 관리자 기능 (docs-scale/05-admin.md).

**조회는 쉽고 쓰기는 어렵다** (05 4장). 자금을 건드리는 쓰기 경로는 세 가지를 지킨다.
  1) `balances` 행을 가장 먼저 `FOR UPDATE` — 09-execution-engine.md 3.4절 잠금 순서.
  2) 기존 서비스의 핵심부를 그대로 공유한다 — 관리자 전용 경로를 새로 파면 규칙이 갈라진다.
  3) 감사 로그를 같은 트랜잭션에 남긴다 — 행위는 됐는데 기록은 없는 상태를 만들지 않는다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.models.user import ROLE_ADMIN, ROLE_USER


class UserNotFoundError(Exception):
    """대상 유저가 없다."""


class LastAdminError(Exception):
    """마지막 관리자의 권한을 회수하려 했다 — 그러면 관리자 화면에 들어갈 사람이 없어진다."""


def record_audit(
    db: Session,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: int,
    detail: dict | None = None,
) -> None:
    """감사 로그 한 행을 **현재 트랜잭션에** 추가한다. 커밋은 호출자가 한다.

    `actor=None`은 CLI처럼 로그인한 행위자가 없는 경로다.
    """
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor is not None else None,
            actor_email=actor.email if actor is not None else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )


def set_role(db: Session, email: str, role: str) -> User:
    """관리자 권한을 부여하거나 회수한다 — CLI 전용 (05 2.1절 "화면에서 승격하는 경로는 두지 않는다").

    회수할 때는 관리자 행을 전부 `FOR UPDATE`로 잡고 센다. 잠그지 않으면 관리자 둘이 서로를
    동시에 회수할 때 각자 "나 말고 한 명 더 있다"를 보고 둘 다 통과해 관리자가 0명이 된다.
    """
    if role not in (ROLE_USER, ROLE_ADMIN):
        raise ValueError(f"알 수 없는 role: {role}")

    user = db.execute(select(User).where(User.email == email).with_for_update()).scalar_one_or_none()
    if user is None:
        raise UserNotFoundError()
    if user.role == role:
        return user  # 멱등

    if role == ROLE_USER:
        admin_ids = db.execute(
            select(User.id).where(User.role == ROLE_ADMIN).with_for_update()
        ).scalars().all()
        if len(admin_ids) <= 1:
            raise LastAdminError()

    before = user.role
    user.role = role
    record_audit(
        db,
        None,
        "role.grant" if role == ROLE_ADMIN else "role.revoke",
        "user",
        user.id,
        {"before": before, "after": role},
    )
    db.commit()
    db.refresh(user)
    return user
