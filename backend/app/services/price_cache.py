"""시세 캐시 — 프로세스 메모리 dict 또는 Redis 중 하나를 백엔드로 쓴다.

`get_cached_price(symbol) -> dict | None` 시그니처는 호출부(라우터·서비스·워커)가
그대로 쓰는 계약이라 백엔드를 바꿔도 호출부는 손대지 않는다 (확장판
docs-scale/02-market-data.md 5장). `PRICE_CACHE_BACKEND=memory`(기본)`|redis`로 고른다
— memory는 지금까지의 `price_stream._price_cache`와 동일하게 동작한다.

**낡은 시세 방어** (같은 문서 3.3절): `market-data`가 죽었거나 페일오버 중이면 캐시에는
낡은 값이 그대로 남아 있고, 그걸로 손절이 판정되거나 시장가가 체결되면 자금이 잘못 움직인다.
그래서 시세가 `PRICE_MAX_AGE_SECONDS`보다 오래됐으면 "시세 없음"과 동일하게 `None`을 준다.

**단, 판정 기준은 "그 코인의 마지막 체결"이 아니라 "스트림이 살아 있는가"다.** Upbit ticker는
체결이 있을 때만 프레임을 보내므로, 거래가 뜸한 코인은 스트림이 멀쩡해도 몇 분씩 갱신이
없다. 코인별 나이로 판정하면 그런 코인은 정상 상황에서 주문이 거부되는데, 이는 같은 절이
요구하는 "정상 상황에서 거부되면 안 됨"에 정면으로 어긋난다. 그래서 틱을 받을 때마다
스트림 생존 시각(`market-data:last_tick_at`)을 따로 찍고, **그 값이 낡았을 때만** 전체를
"시세 없음"으로 접는다 — 코인별 `received_at`은 관측용으로 남긴다.

**Redis 장애도 같은 원칙으로 다룬다** (00-architecture.md 3.2절 "잃어버려도 재구성 가능한
것만 Redis에 둔다"): Redis가 안 붙거나 값이 깨져 있으면 "시세 없음"으로 접는다 — 읽기는
`None`, 쓰기는 다음 틱에서 다시 시도하면 된다. 호출부가 이 실패를 서버 오류(500)로 받는
일이 없어야 한다는 게 이 모듈의 핵심 계약이다.
"""

import json
import logging
import time
from typing import Iterable

from app.config import settings
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

# 스트림 생존 시각을 담는 키. 코인별 시세와 달리 하나뿐이라 `price:` 접두사를 쓰지 않는다.
FEED_HEARTBEAT_KEY = "market-data:last_tick_at"

_memory_cache: dict[str, dict] = {}
_memory_last_tick_at = 0.0


def _redis_key(symbol: str) -> str:
    return f"price:{symbol}"


def _is_feed_stale(last_tick_at: float) -> bool:
    """스트림이 끊긴 것으로 볼지 판정한다. 틱을 한 번도 못 받았으면(0.0) 끊긴 것으로 본다."""
    return last_tick_at <= 0 or (time.time() - last_tick_at) > settings.price_max_age_seconds


def set_price(symbol: str, tick: dict) -> None:
    """새 틱을 캐시에 반영한다. 지금은 `market-data` 역할(price_stream.py)만 호출한다.

    Upbit WS 수신 루프 안에서 부르므로 여기서 블로킹하면 그 루프 전체가 밀린다 — redis
    클라이언트 I/O는 반드시 `asyncio.to_thread`로 감싸 호출할 것 (price_stream.py 참고).
    """
    global _memory_last_tick_at

    now = time.time()
    payload = {**tick, "received_at": now}
    if settings.price_cache_backend == "redis":
        try:
            # 시세와 생존 시각을 한 번의 왕복으로 함께 쓴다 — 틱마다 도는 경로다.
            pipeline = get_redis().pipeline()
            pipeline.set(_redis_key(symbol), json.dumps(payload))
            pipeline.set(FEED_HEARTBEAT_KEY, now)
            pipeline.execute()
        except Exception:
            logger.warning("시세 캐시 쓰기 실패 (symbol=%s) — 다음 틱에서 재시도", symbol)
    else:
        _memory_cache[symbol] = payload
        _memory_last_tick_at = now


def delete_price(symbol: str) -> None:
    """캐시에서 심볼 하나를 지운다. 운영 경로에서는 쓰지 않는다 — 테스트가 주입한 값을
    치울 때만 쓴다 (`set_price`처럼 백엔드를 가리지 않아야 테스트가 redis에서도 격리된다)."""
    if settings.price_cache_backend == "redis":
        try:
            get_redis().delete(_redis_key(symbol))
        except Exception:
            logger.warning("시세 캐시 삭제 실패 (symbol=%s)", symbol)
    else:
        _memory_cache.pop(symbol, None)


def get_cached_price(symbol: str) -> dict | None:
    """호출부는 반환값이 `None`이면 "시세 없음"으로만 처리하면 된다 — 스트림 중단도 Redis
    장애도 값 손상도 전부 여기에 접혀 들어온다 (자금 경로는 이미 `None`을 스킵/거부로 처리한다)."""
    return get_cached_prices([symbol]).get(symbol)


def get_cached_prices(symbols: Iterable[str]) -> dict[str, dict]:
    """여러 심볼을 한 번에 읽는다. 시세를 못 주는 심볼은 결과에서 빠진다.

    `/ws/prices`는 접속 한 번에 수백 심볼을 조회하므로, 심볼마다 왕복하면 그 수만큼
    Redis 왕복이 생긴다. 여기서 MGET 한 번으로 묶는다.
    """
    symbol_list = list(symbols)
    if not symbol_list:
        return {}

    if settings.price_cache_backend == "redis":
        try:
            keys = [_redis_key(symbol) for symbol in symbol_list] + [FEED_HEARTBEAT_KEY]
            values = get_redis().mget(keys)
        except Exception:
            logger.warning("시세 캐시 조회 실패 (%d개) — 시세 없음으로 처리", len(symbol_list))
            return {}
        last_tick_at = _parse_float(values[-1])
        raw_payloads = dict(zip(symbol_list, values[:-1]))
    else:
        last_tick_at = _memory_last_tick_at
        raw_payloads = {symbol: _memory_cache.get(symbol) for symbol in symbol_list}

    if _is_feed_stale(last_tick_at):
        # 스트림이 멈췄다 — 남아 있는 값은 전부 낡은 값이다 (market-data 페일오버 중이거나
        # 죽었다). 낡은 가격으로 자금을 움직이는 것보다 멈추는 편이 낫다.
        return {}

    return {
        symbol: payload
        for symbol, payload in ((s, _parse_payload(raw_payloads[s])) for s in symbol_list)
        if payload is not None
    }


def _parse_payload(raw) -> dict | None:
    """Redis 문자열(또는 memory 백엔드의 dict)을 틱으로 되돌린다. 깨져 있으면 None."""
    if raw is None or isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("시세 캐시 값 손상 — 시세 없음으로 처리")
        return None


def _parse_float(raw) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0
