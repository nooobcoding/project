"""Redis 클라이언트 팩토리 — 확장판이 쓰는 Redis 접속을 한 곳에서 만든다.

시세 캐시(price_cache.py)와 틱 발행·구독(tick_bus.py)이 같은 접속 설정을 공유해야 하고,
5·6단계의 `pending_symbols`·토큰 버킷도 여기에 붙는다 (docs-scale/02-market-data.md 2장).

타임아웃을 짧게 못 박는 이유: Redis가 응답 없이 멈추면 시세 수신 루프와 요청 처리가 같이
멈춘다. 무한 대기 대신 예외로 실패시키고, 호출부가 "시세 없음"으로 접는 편이 낫다
(00-architecture.md 3.2절 — Redis에는 잃어버려도 재구성 가능한 것만 둔다).
"""

import logging
from functools import lru_cache

import redis
import redis.asyncio

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 2


@lru_cache
def get_redis() -> redis.Redis:
    """동기 클라이언트 — 시세 캐시 읽기/쓰기와 틱 발행이 쓴다."""
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=TIMEOUT_SECONDS,
        socket_timeout=TIMEOUT_SECONDS,
    )


def create_async_redis() -> redis.asyncio.Redis:
    """비동기 클라이언트 — `api` 역할의 틱 구독 전용.

    구독은 오래 열어두는 연결이라 `socket_timeout`을 걸지 않는다. 걸면 틱이 뜸한 시간대에
    타임아웃이 그대로 연결 끊김이 된다 — 읽기 타임아웃은 여기서만 예외다.
    """
    return redis.asyncio.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=TIMEOUT_SECONDS,
    )
