"""시세 캐시 — 프로세스 메모리 dict 또는 Redis 중 하나를 백엔드로 쓴다.

`get_cached_price(symbol) -> dict | None` 시그니처는 호출부(라우터·서비스·워커)가
그대로 쓰는 계약이라 백엔드를 바꿔도 호출부는 손대지 않는다 (확장판
docs-scale/02-market-data.md 5장). `PRICE_CACHE_BACKEND=memory`(기본)`|redis`로 고른다
— memory는 지금까지의 `price_stream._price_cache`와 동일하게 동작한다.

**낡은 시세 방어** (같은 문서 3.3절): 틱마다 `received_at`을 함께 저장하고,
`PRICE_MAX_AGE_SECONDS`를 넘긴 값은 "시세 없음"과 동일하게 `None`을 반환한다. 호출부는
이미 전부 `None`을 "아직 시세 없음"으로 처리하고 있으므로(자금 경로는 스킵/거부, 화면
표시는 완화) 이 모듈 하나만 고치면 방어가 전체에 적용된다.

**Redis 장애도 같은 원칙으로 다룬다** (00-architecture.md 3.2절 "잃어버려도 재구성 가능한
것만 Redis에 둔다"): Redis가 안 붙거나 타임아웃 나면 "시세 없음"과 동일하게 처리한다 —
읽기는 `None`, 쓰기는 다음 틱에서 다시 시도하면 되므로 로그만 남기고 삼킨다. 호출부가
이 실패를 서버 오류(500)로 받는 일이 없어야 한다는 게 이 모듈의 핵심 계약이다.
"""

import json
import logging
import time
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)

_memory_cache: dict[str, dict] = {}

# Redis가 응답 없이 멈추면 이 상시 루프도 같이 멈추므로(price_stream.py의 시세 수신 등)
# 소켓 타임아웃을 짧게 못 박는다 — 무한 대기 대신 예외로 실패해 아래에서 "시세 없음"으로
# 접는다.
_REDIS_TIMEOUT_SECONDS = 2


@lru_cache
def _redis_client():
    import redis

    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_TIMEOUT_SECONDS,
    )


def _redis_key(symbol: str) -> str:
    return f"price:{symbol}"


def _is_stale(received_at: float) -> bool:
    return (time.time() - received_at) > settings.price_max_age_seconds


def set_price(symbol: str, tick: dict) -> None:
    """새 틱을 캐시에 반영한다. 지금은 `market-data` 역할(price_stream.py)만 호출한다.

    Upbit WS 수신 루프 안에서 부르므로 여기서 블로킹하면 그 루프 전체가 밀린다 — redis
    클라이언트 I/O는 반드시 `asyncio.to_thread`로 감싸 호출할 것 (price_stream.py 참고).
    """
    payload = {**tick, "received_at": time.time()}
    if settings.price_cache_backend == "redis":
        try:
            _redis_client().set(_redis_key(symbol), json.dumps(payload))
        except Exception:
            logger.warning("시세 캐시 쓰기 실패 (symbol=%s) — 다음 틱에서 재시도", symbol)
    else:
        _memory_cache[symbol] = payload


def delete_price(symbol: str) -> None:
    """캐시에서 심볼 하나를 지운다. 운영 경로에서는 쓰지 않는다 — 테스트가 주입한 값을
    치울 때만 쓴다 (`set_price`처럼 백엔드를 가리지 않아야 테스트가 redis에서도 격리된다)."""
    if settings.price_cache_backend == "redis":
        try:
            _redis_client().delete(_redis_key(symbol))
        except Exception:
            logger.warning("시세 캐시 삭제 실패 (symbol=%s)", symbol)
    else:
        _memory_cache.pop(symbol, None)


def get_cached_price(symbol: str) -> dict | None:
    """호출부는 반환값이 `None`이면 "시세 없음"으로만 처리하면 된다 — Redis 장애도
    포함된 결과다 (자금 경로는 이미 `None`을 스킵/거부로 처리하고 있다)."""
    if settings.price_cache_backend == "redis":
        try:
            raw = _redis_client().get(_redis_key(symbol))
        except Exception:
            logger.warning("시세 캐시 조회 실패 (symbol=%s) — 시세 없음으로 처리", symbol)
            return None
        payload = json.loads(raw) if raw is not None else None
    else:
        payload = _memory_cache.get(symbol)

    if payload is None:
        return None
    if _is_stale(payload["received_at"]):
        return None
    return payload
