"""확장판 8단계 Control 계층 — 관리자 기능 (docs-scale/05-admin.md).

**조회는 쉽고 쓰기는 어렵다** (05 4장). 자금을 건드리는 쓰기 경로는 세 가지를 지킨다.
  1) `balances` 행을 가장 먼저 `FOR UPDATE` — 09-execution-engine.md 3.4절 잠금 순서.
  2) 기존 서비스의 핵심부를 그대로 공유한다 — 관리자 전용 경로를 새로 파면 규칙이 갈라진다.
  3) 감사 로그를 같은 트랜잭션에 남긴다 — 행위는 됐는데 기록은 없는 상태를 만들지 않는다.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, Balance, Holding, Order, StrategySlot, User, WorkerHeartbeat
from app.models.user import ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE, STATUS_SUSPENDED
from app.services import leader, orders, pending_symbols, portfolio, rate_limit, strategy_slots, wallet


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


# ---------------------------------------------------------------- 3-A. 유저 목록·상세 (읽기 전용)

MAX_PAGE_SIZE = 100


def list_users(
    db: Session,
    *,
    status: str | None,
    has_active_slots: bool | None,
    email_query: str | None,
    oldest_first: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    """관리자 유저 목록 (05 3-A). 한 페이지를 **쿼리 3번**으로 만든다.

    유저마다 `portfolio.get_summary`를 부르면 페이지 크기만큼 쿼리가 곱으로 늘어난다. 대신
    목록·카운트를 한 번에 뽑고, 그 페이지 유저들의 보유만 한 번 더 읽어 평가한다. 평가 단가는
    `portfolio._current_price`를 그대로 써서 유저 본인 화면과 같은 값이 나오게 한다.
    """
    active_slots = (
        select(StrategySlot.user_id, func.count().label("active_slot_count"))
        .where(StrategySlot.is_active.is_(True))
        .group_by(StrategySlot.user_id)
        .subquery()
    )
    slot_count = func.coalesce(active_slots.c.active_slot_count, 0)

    conditions = []
    if status is not None:
        conditions.append(User.status == status)
    if has_active_slots is True:
        conditions.append(slot_count > 0)
    elif has_active_slots is False:
        conditions.append(slot_count == 0)
    if email_query:
        conditions.append(User.email.ilike(f"%{_escape_like(email_query)}%", escape="\\"))

    base = (
        select(
            User.id,
            User.email,
            User.role,
            User.status,
            User.created_at,
            func.coalesce(Balance.krw_balance, 0).label("krw_balance"),
            slot_count.label("active_slot_count"),
        )
        .outerjoin(Balance, Balance.user_id == User.id)
        .outerjoin(active_slots, active_slots.c.user_id == User.id)
        .where(*conditions)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    order = (User.created_at.asc(), User.id.asc()) if oldest_first else (User.created_at.desc(), User.id.desc())
    rows = db.execute(base.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()

    coin_valuation = _coin_valuations(db, [row.id for row in rows])
    items = [
        {
            "id": row.id,
            "email": row.email,
            "role": row.role,
            "status": row.status,
            "created_at": row.created_at,
            "active_slot_count": row.active_slot_count,
            "krw_balance": row.krw_balance,
            "total_valuation": row.krw_balance + coin_valuation.get(row.id, Decimal(0)),
        }
        for row in rows
    ]
    return items, total


def _escape_like(value: str) -> str:
    """검색어의 `%`·`_`를 글자 그대로 찾게 한다 — 안 그러면 `_` 하나가 모든 이메일에 걸린다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _coin_valuations(db: Session, user_ids: list[int]) -> dict[int, Decimal]:
    if not user_ids:
        return {}
    holdings = db.scalars(
        select(Holding).where(Holding.user_id.in_(user_ids), Holding.quantity > 0)
    ).all()
    valuations: dict[int, Decimal] = {}
    for holding in holdings:
        valuations[holding.user_id] = valuations.get(holding.user_id, Decimal(0)) + (
            holding.quantity * portfolio._current_price(holding)
        )
    return valuations


RECENT_LIMIT = 20


def get_user_detail(db: Session, user_id: int) -> dict:
    """관리자 유저 상세 (05 3-A). 유저 본인 화면이 쓰는 함수에 user_id만 바꿔 넘긴다."""
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError()

    transactions, _ = wallet.list_transactions(
        db, user_id, type_=None, start=None, end=None, page=1, page_size=RECENT_LIMIT
    )
    return {
        "user": user,
        "summary": portfolio.get_summary(db, user_id),
        "withdrawable_krw": wallet.get_withdrawable_krw(db, user_id),
        "holdings": portfolio.list_holdings(db, user_id),
        "slots": strategy_slots.list_slots(db, user_id),
        "pending_orders": orders.list_pending_orders(db, user_id),
        "recent_orders": orders.list_order_history(db, user_id, limit=RECENT_LIMIT),
        "recent_transactions": transactions,
    }


# ---------------------------------------------------------------- 3-B. 계정 정지·해제


class CannotSuspendSelfError(Exception):
    """본인 계정을 정지하려 했다."""


class CannotSuspendAdminError(Exception):
    """관리자 계정을 정지하려 했다 — 관리자끼리 서로 잠그는 사고를 원천 차단한다.

    관리자를 멈춰야 하면 먼저 CLI로 권한을 회수한다(`scripts/set_admin.py --revoke`).
    """


def set_user_status(db: Session, actor: User, user_id: int, status: str) -> dict:
    """계정을 정지하거나 해제한다 (05 3-B).

    **정지는 트랜잭션 두 개로 나뉜다.** 한 트랜잭션으로 묶으면 체결과 교착한다.

    1단계 — `balances` → `users` → `strategy_slots` 순으로 잠그고 status·슬롯 OFF·감사 로그를
       커밋한다. `balances`를 먼저 잡는 이유: `create_order`가 같은 행을 잠근 **뒤에** status를
       보므로, 정지 직전에 상태를 읽어 둔 요청(진행 중인 HTTP 요청, 정지 전 스냅샷으로 도는 워커
       tick)도 이 커밋 이후에는 주문을 못 낸다. 여기서부터 새 주문은 생기지 않는다.
    2단계 — 남은 pending 주문을 취소한다. 사용자 취소와 같은 `cancel_pending_in_session`이다.
       체결은 `orders(선점) → balances` 순으로 잠그므로, 1단계처럼 `balances`를 쥔 채 주문 행을
       기다리면 그 주문을 체결 중인 matcher와 서로를 기다린다. 2단계는 `balances`를 잡지 않아
       사용자 취소와 똑같이 체결과 경합만 하고(둘 중 하나만 성공), 교착하지 않는다.

    2단계가 실패해도 1단계는 유지된다(새 주문은 이미 막혔다). 같은 요청을 다시 보내면 이미 정지된
    계정이라도 2단계를 다시 돌려 남은 주문을 마저 취소한다.

    해제는 status만 되돌린다. 슬롯을 자동으로 다시 켜지 않는다 — 켜는 건 사용자 몫이다.
    """
    suspend = status == STATUS_SUSPENDED

    # --- 1단계
    db.execute(select(Balance).where(Balance.user_id == user_id).with_for_update())
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        db.rollback()
        raise UserNotFoundError()
    if suspend and user.id == actor.id:
        db.rollback()
        raise CannotSuspendSelfError()
    if suspend and user.role == ROLE_ADMIN:
        db.rollback()
        raise CannotSuspendAdminError()

    changed = user.status != status
    deactivated_slot_ids: list[int] = []
    audit: AuditLog | None = None
    if changed:
        if suspend:
            slots = db.scalars(
                select(StrategySlot)
                .where(StrategySlot.user_id == user_id, StrategySlot.is_active.is_(True))
                .order_by(StrategySlot.id)
                .with_for_update()
            ).all()
            for slot in slots:
                strategy_slots.deactivate_in_session(slot)
            deactivated_slot_ids = [slot.id for slot in slots]

        before = user.status
        user.status = status
        audit = AuditLog(
            actor_user_id=actor.id,
            actor_email=actor.email,
            action="user.suspend" if suspend else "user.unsuspend",
            target_type="user",
            target_id=user_id,
            detail={"before": before, "after": status, "deactivated_slot_ids": deactivated_slot_ids}
            if suspend
            else {"before": before, "after": status},
        )
        db.add(audit)
    db.commit()

    # --- 2단계 (정지일 때만)
    canceled: list[tuple[int, str]] = []
    if suspend:
        canceled = orders.cancel_pending_in_session(db, Order.user_id == user_id)
        canceled_ids = [order_id for order_id, _ in canceled]
        if audit is not None:
            audit.detail = {**audit.detail, "canceled_order_ids": canceled_ids}
        elif canceled:
            # 이전 정지 요청의 2단계가 실패해 남았던 주문을 이번에 마저 치웠다.
            record_audit(
                db, actor, "user.suspend", "user", user_id,
                {"before": status, "after": status, "canceled_order_ids": canceled_ids},
            )
        db.commit()
        for symbol in {symbol for _, symbol in canceled}:
            pending_symbols.discard_if_settled(symbol)

    return {
        "status": status,
        "changed": changed,
        "deactivated_slot_ids": deactivated_slot_ids,
        "canceled_order_ids": [order_id for order_id, _ in canceled],
    }


# ---------------------------------------------------------------- 3-C. 슬롯 강제 OFF


class SlotNotFoundError(Exception):
    """대상 슬롯이 없다."""


def deactivate_slot(db: Session, actor: User, slot_id: int) -> StrategySlot:
    """슬롯을 강제로 끈다 (05 3-C). 사용자 OFF와 같은 `deactivate_in_session`을 쓴다.

    사용자 OFF처럼 잠그는 것은 슬롯 행뿐이다 — OFF는 돈을 움직이지 않고 `state`도 건드리지
    않는다. 소유권은 보지 않는다(관리자이므로). 이미 꺼져 있으면 아무것도 남기지 않는다.
    """
    slot = db.execute(
        select(StrategySlot).where(StrategySlot.id == slot_id).with_for_update()
    ).scalar_one_or_none()
    if slot is None:
        db.rollback()
        raise SlotNotFoundError()

    if slot.is_active:
        strategy_slots.deactivate_in_session(slot)
        record_audit(
            db, actor, "slot.deactivate", "strategy_slot", slot.id,
            {"user_id": slot.user_id, "coin_symbol": slot.coin_symbol},
        )
    db.commit()
    db.refresh(slot)
    return slot


# ---------------------------------------------------------------- 3-D. 시스템 대시보드

# heartbeat가 이 배수만큼 tick 주기를 넘기면 "멈춤"으로 본다 (06-observability.md 3.4절 "샤드별
# 마지막 tick 경과" — 락은 쥐고 있는데 tick이 안 도는 프로세스). 역할마다 주기가 달라서 숫자
# 하나로 정하지 않고 각 역할의 실제 주기 상수에서 끌어온다.
STALE_INTERVAL_MULTIPLIER = 3
_FALLBACK_INTERVAL_SECONDS = 30


def _tick_intervals() -> dict[str, int]:
    from app.services.candle_prefill import PREFILL_INTERVAL_SECONDS
    from app.services.matcher_runner import HEARTBEAT_INTERVAL_SECONDS
    from app.strategy_engine.worker import TICK_INTERVAL_SECONDS

    return {
        "worker": TICK_INTERVAL_SECONDS,
        "matcher": HEARTBEAT_INTERVAL_SECONDS,
        "candle-prefill": PREFILL_INTERVAL_SECONDS,
    }


def _shard_coverage(namespace: int, applicable: bool) -> dict:
    """미점유 샤드 목록. `shard_coverage._check`를 쓰지 않는다 — 그쪽은 연속 미점유 횟수를 세고
    경고 로그를 남기는 scheduler 전용 상태라, 대시보드를 열 때마다 그 카운터가 오르면 안 된다.

    조회에 실패하면 `missing=None`이다. 빈 목록으로 내리면 "전부 점유됨"으로 읽힌다.
    """
    if not applicable:
        return {"applicable": False, "missing": []}
    try:
        occupied = leader.occupied_shards(namespace)
    except Exception:
        return {"applicable": True, "missing": None}
    return {
        "applicable": True,
        "missing": sorted(set(range(settings.shard_count)) - occupied),
    }


def get_system_overview(db: Session) -> dict:
    """관리자 시스템 대시보드 (05 3-D). **샤드 커버리지가 맨 위다** — 나머지는 "느린가"를 보지만
    이건 "아예 멈췄는가"를 본다."""
    now = datetime.now(timezone.utc)
    intervals = _tick_intervals()

    heartbeats = []
    for row in db.scalars(
        select(WorkerHeartbeat).order_by(WorkerHeartbeat.role, WorkerHeartbeat.shard_id, WorkerHeartbeat.process_id)
    ):
        interval = intervals.get(row.role, _FALLBACK_INTERVAL_SECONDS)
        age = (now - row.last_tick_at).total_seconds()
        heartbeats.append(
            {
                "role": row.role,
                "shard_id": row.shard_id,
                "process_id": row.process_id,
                "last_tick_at": row.last_tick_at,
                "seconds_since_tick": int(age),
                "stale": age > interval * STALE_INTERVAL_MULTIPLIER,
                "last_duration_ms": row.last_duration_ms,
                "max_duration_ms": row.max_duration_ms,
                "over_budget_count": row.over_budget_count,
                "item_count": row.item_count,
                "db_connections": row.db_connections,
                "error_count": row.error_count,
                "skip_count": row.skip_count,
            }
        )

    user_counts = dict(db.execute(select(User.status, func.count()).group_by(User.status)).all())
    return {
        "shard_count": settings.shard_count,
        "worker_coverage": _shard_coverage(leader.WORKER_SHARD_NAMESPACE, applicable=True),
        # 단일 프로세스(memory) 구성에서는 체결을 시세 루프가 직접 해서 matcher 샤드 점유가 없다
        "matcher_coverage": _shard_coverage(
            leader.MATCHER_SHARD_NAMESPACE, applicable=settings.price_cache_backend == "redis"
        ),
        "heartbeats": heartbeats,
        "active_users": user_counts.get(STATUS_ACTIVE, 0),
        "suspended_users": user_counts.get(STATUS_SUSPENDED, 0),
        "active_slots": db.scalar(
            select(func.count()).select_from(StrategySlot).where(StrategySlot.is_active.is_(True))
        ) or 0,
        "pending_orders": db.scalar(
            select(func.count()).select_from(Order).where(Order.status == "pending")
        ) or 0,
        "upbit_rate_limit": rate_limit.peek(),
    }
