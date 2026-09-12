"""`pending_symbols` — 미체결 주문이 있는 심볼 집합 (확장판 02-market-data.md 4.2절).

matcher는 틱마다 도는데, 지금은 틱마다 무조건 DB를 두 번 친다(예약가 승격 + pending 지정가
조회). KRW 마켓 200종에 심볼당 초당 여러 틱이면 **미체결 주문이 하나도 없어도 초당 수백 번의
DB 왕복**이 생긴다. 프로세스가 하나일 때는 커넥션 풀이 상한 노릇을 해서 티가 안 났지만,
matcher를 여러 개 띄우면 그대로 DB를 때린다.

그래서 Redis Set을 힌트로 둔다: 틱을 받으면 먼저 `SISMEMBER`로 물어보고, 없으면 DB를 아예
안 본다.

**이 Set은 힌트일 뿐 진실원천이 아니다.** 틀리는 방향이 한쪽만 허용된다:

| 상태 | 결과 |
|---|---|
| Set에 있는데 실제로는 없음 | DB 한 번 헛조회. 무해 |
| **Set에 없는데 실제로는 있음** | **그 주문은 영영 체결되지 않는다. 치명적** |

따라서 `SREM`은 실패해도 되지만 `SADD`는 실패하면 안 된다. 그런데 Redis 장애로 `SADD`가
실패했다고 주문 접수를 거부할 수는 없으므로(주문 경로가 Redis에 종속된다), 실패는 크게 남기고
**`scheduler`의 주기적 재구성**(`rebuild`)으로 복구한다. Redis가 통째로 날아가도 거기서
복구된다 — Redis에는 잃어버려도 재구성 가능한 것만 둔다는 원칙 그대로다.
"""

import logging

from sqlalchemy import distinct, select

from app.config import settings
from app.database import session_scope
from app.models import Order
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

KEY = "pending_symbols"


def _enabled() -> bool:
    """memory 백엔드면 힌트를 쓰지 않는다 — 단일 프로세스라 Redis가 아예 없을 수 있고,
    그 구성에서는 DB 왕복을 줄일 이유도 없다."""
    return settings.price_cache_backend == "redis"


def add(symbol: str) -> None:
    """미체결 주문이 생겼음을 알린다. 실패하면 그 심볼의 주문이 체결되지 않을 수 있으므로
    조용히 넘기지 않는다 — 복구는 `rebuild`가 한다."""
    if not _enabled():
        return
    try:
        get_redis().sadd(KEY, symbol)
    except Exception:
        logger.error(
            "pending_symbols 등록 실패 (symbol=%s) — 재구성 전까지 이 심볼의 미체결 주문이 "
            "체결되지 않을 수 있다",
            symbol,
        )


def discard_if_settled(symbol: str) -> None:
    """그 심볼에 남은 미체결 주문이 없으면 집합에서 뺀다.

    빼기 전에 DB를 한 번 확인한다 — 같은 심볼에 다른 주문이 아직 남아 있는데 지워버리면
    위 표의 치명적인 쪽(있는데 없다고 함)에 해당한다. 실패해도 무해하다(헛조회만 늘어난다).
    """
    if not _enabled():
        return
    try:
        with session_scope() as db:
            still_pending = db.scalar(
                select(Order.id)
                .where(Order.coin_symbol == symbol, Order.status == "pending")
                .limit(1)
            )
        if still_pending is None:
            get_redis().srem(KEY, symbol)
    except Exception:
        logger.warning("pending_symbols 정리 실패 (symbol=%s) — 헛조회만 늘어난다", symbol)


def has_pending(symbol: str) -> bool:
    """matcher가 DB를 볼지 판단한다. 힌트를 못 쓰는 상황이면 **항상 True** —
    확신이 없으면 조회하는 쪽이 안전하다(헛조회는 무해, 누락은 치명적)."""
    if not _enabled():
        return True
    try:
        return bool(get_redis().sismember(KEY, symbol))
    except Exception:
        logger.warning("pending_symbols 조회 실패 (symbol=%s) — DB를 직접 본다", symbol)
        return True


def rebuild() -> int:
    """DB에서 집합을 통째로 다시 만든다 (`scheduler`가 주기적으로 호출).

    `SADD` 누락과 Redis 유실을 모두 여기서 복구한다. 지우고 다시 채우는 사이에 빈 창이
    생기지 않도록, 새 집합을 임시 키에 쌓고 `RENAME`으로 원자적으로 바꿔치기한다.
    """
    if not _enabled():
        return 0

    with session_scope() as db:
        symbols = list(
            db.scalars(select(distinct(Order.coin_symbol)).where(Order.status == "pending"))
        )

    staging_key = f"{KEY}:rebuilding"
    client = get_redis()
    pipeline = client.pipeline()
    pipeline.delete(staging_key)
    if symbols:
        pipeline.sadd(staging_key, *symbols)
        pipeline.rename(staging_key, KEY)
    else:
        # 미체결이 하나도 없으면 빈 집합이 맞다. Redis에는 빈 Set이 존재할 수 없으므로
        # RENAME 대신 삭제한다 (없는 키의 SISMEMBER는 false라 의미가 같다).
        pipeline.delete(KEY)
    pipeline.execute()
    return len(symbols)
