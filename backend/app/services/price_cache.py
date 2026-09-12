"""시세 캐시 — 프로세스 메모리 dict 또는 Redis 중 하나를 백엔드로 쓴다.

`get_cached_price(symbol) -> dict | None` 시그니처는 호출부(라우터·서비스·워커)가
그대로 쓰는 계약이라 백엔드를 바꿔도 호출부는 손대지 않는다 (확장판
docs-scale/02-market-data.md 5장). `PRICE_CACHE_BACKEND=memory`(기본)`|redis`로 고른다
— memory는 지금까지의 `price_stream._price_cache`와 동일하게 동작한다.

**낡은 시세 방어** (같은 문서 3.3절): 틱마다 `received_at`을 함께 저장하고,
`PRICE_MAX_AGE_SECONDS`를 넘긴 값은 "시세 없음"과 동일하게 `None`을 반환한다. 호출부는
이미 전부 `None`을 "아직 시세 없음"으로 처리하고 있으므로(자금 경로는 스킵/거부, 화면
표시는 완화) 이 모듈 하나만 고치면 방어가 전체에 적용된다.
"""

import json
import logging
import time
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)

_memory_cache: dict[str, dict] = {}


@lru_cache
def _redis_client():
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _is_stale(received_at: float) -> bool:
    return (time.time() - received_at) > settings.price_max_age_seconds


def set_price(symbol: str, tick: dict) -> None:
    """새 틱을 캐시에 반영한다. 지금은 `market-data` 역할(price_stream.py)만 호출한다."""
    payload = {**tick, "received_at": time.time()}
    if settings.price_cache_backend == "redis":
        _redis_client().set(f"price:{symbol}", json.dumps(payload))
    else:
        _memory_cache[symbol] = payload


def delete_price(symbol: str) -> None:
    """캐시에서 심볼 하나를 지운다. 운영 경로에서는 쓰지 않는다 — 테스트가 주입한 값을
    치울 때만 쓴다 (`set_price`처럼 백엔드를 가리지 않아야 테스트가 redis에서도 격리된다)."""
    if settings.price_cache_backend == "redis":
        _redis_client().delete(f"price:{symbol}")
    else:
        _memory_cache.pop(symbol, None)


def get_cached_price(symbol: str) -> dict | None:
    if settings.price_cache_backend == "redis":
        raw = _redis_client().get(f"price:{symbol}")
        payload = json.loads(raw) if raw is not None else None
    else:
        payload = _memory_cache.get(symbol)

    if payload is None:
        return None
    if _is_stale(payload["received_at"]):
        return None
    return payload
