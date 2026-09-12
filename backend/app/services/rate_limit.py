"""Upbit REST 호출량 통제 — 우선순위 2단 토큰 버킷 (04-async-jobs.md 3.2절).

지금까지 Upbit REST를 부르는 주체는 여럿인데(워커 tick, 백테스트 스레드, coins 동기화,
차트 조회) **호출량 자체를 통제하는 주체가 없었다.** 레이트리밋은 IP 단위로 공유되므로
백테스트 한 번(1분봉 7일 = 51회)이 워커의 캔들 조회와 같은 예산을 쓴다. 429가 나기
시작하면 그 여파를 자동매매가 함께 맞는다.

**버킷을 둘로 나눈다.** 총량을 `high`(scheduler의 캔들 미리 채우기)와 `low`(백테스트)가
나눠 갖는다. 우선순위를 한 버킷 안의 대기열로 구현하지 않고 버킷 자체를 나눈 이유는,
저우선이 아무리 많이 밀려도 고우선의 몫을 **구조적으로** 못 건드리게 하기 위해서다 —
대기열이면 저우선이 먼저 줄을 서 있는 동안 고우선이 뒤에서 기다리게 된다. 워커의 신호
평가가 캔들 채우기에 걸려 있으므로, 굶어야 한다면 백테스트가 굶어야 한다.

**백엔드가 둘인 이유는 price_cache와 같다.** `PRICE_CACHE_BACKEND=redis`면 여러 프로세스가
한 IP를 공유하므로 버킷도 Redis에 있어야 한다. `memory`는 단일 프로세스 롤백 경로라 프로세스
안의 버킷이 곧 전체 버킷이다.

**429 백오프**: `note_throttled()`가 불리면 리필 속도를 절반으로 낮추고 TTL이 지나면
스스로 돌아온다. 우리가 잡은 값이 실제 제한보다 후했다는 신호이므로, 로그로 반드시 남긴다
(조용한 실패 금지 — 429를 먹고도 같은 속도로 계속 두드리면 아무도 모른다).
"""

import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

Priority = Literal["high", "low"]

KEY_PREFIX = "ratelimit:upbit:rest"
PENALTY_KEY = f"{KEY_PREFIX}:penalty"

# 버킷 키는 리필 계산에 쓰는 타임스탬프를 함께 들고 있어서, 오래 안 쓰이면 그냥 지워져도
# 된다(다음 호출이 가득 찬 버킷으로 다시 시작한다). TTL을 두어 Redis에 유령 키가 남지 않게 한다.
BUCKET_TTL_SECONDS = 3600

# 429 백오프 배수의 상한. 무한정 낮추면 회복 불가능한 상태가 된다 — 이 값에 닿았는데도
# 429가 계속 나면 설정값(upbit_rest_tokens_per_second) 자체가 틀린 것이고, 그건 사람이
# 봐야 할 문제다.
MAX_PENALTY = 8.0

# 대기 중 재확인 간격의 상한. 계산된 대기 시간이 이보다 길어도 일단 이만큼만 자고 다시
# 본다 — 그사이 429 백오프가 풀리거나 다른 소비자가 멈춰 토큰이 빨리 찰 수 있다.
MAX_SLEEP_SECONDS = 1.0

_priority: contextvars.ContextVar[Priority] = contextvars.ContextVar(
    "upbit_rest_priority", default="low"
)


class RateLimitTimeout(Exception):
    """토큰을 제한 시간 안에 받지 못했다. 호출부는 이번 호출을 포기하고 기록해야 한다."""


@contextmanager
def priority(value: Priority):
    """이 블록 안의 Upbit 호출을 해당 우선순위로 취급한다.

    호출부(`scheduler` 잡, 백테스트)와 실제 HTTP를 치는 곳(`services/candles.py`) 사이에는
    함수가 네 겹 있다. 우선순위를 인자로 꿰면 그 네 겹이 전부 "쓰지도 않는 값을 넘기기만
    하는" 시그니처가 되므로 컨텍스트로 전달한다. `asyncio.to_thread`와 APScheduler 잡은
    각자 자기 컨텍스트에서 돌기 때문에 스레드끼리 새지 않는다.
    """
    token = _priority.set(value)
    try:
        yield
    finally:
        _priority.reset(token)


def _split(total: float) -> dict[Priority, float]:
    """총량을 우선순위별로 나눈다. 양쪽 다 최소 한 몫은 갖게 한다 — share를 0이나 1로
    잘못 설정하면 그쪽 소비자가 영영 못 부르게 되는데, 증상은 조용한 멈춤이다."""
    share = min(max(settings.upbit_rest_high_share, 0.1), 0.9)
    return {"high": total * share, "low": total * (1 - share)}


def _capacity(prio: Priority) -> float:
    return max(_split(settings.upbit_rest_burst)[prio], 1.0)


def _refill_rate(prio: Priority) -> float:
    return max(_split(settings.upbit_rest_tokens_per_second)[prio], 0.1)


def _enabled() -> bool:
    """Redis 백엔드를 쓰는지. `memory`면 프로세스 안 버킷으로 떨어진다."""
    return settings.price_cache_backend == "redis"


# --- Redis 백엔드 ---------------------------------------------------------

# 리필·소비·페널티 조회를 한 번에 처리한다. 셋을 따로 하면 두 프로세스가 같은 순간에
# 읽고 각자 소비해 버킷을 초과할 수 있다 (읽기-수정-쓰기 경합).
#
# 현재 시각을 서버(`TIME`)가 아니라 호출자가 넘기는 이유: 스크립트 안에서 `TIME`을 쓰면
# 복제 방식에 따라 쓰기가 거부되는 Redis 버전이 있다. 프로세스 간 시계 차이는 NTP 아래에서
# 밀리초 수준이라 레이트리밋에는 영향이 없고, 시계가 뒤로 튀는 경우는 `elapsed`를 0으로
# 깎아 토큰이 거꾸로 줄어드는 것만 막으면 된다.
_CONSUME_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local penalty = tonumber(redis.call('GET', KEYS[2]))
if penalty == nil or penalty < 1 then penalty = 1 end
refill = refill / penalty

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * refill)

local wait = 0
if tokens >= cost then
  tokens = tokens - cost
else
  wait = (cost - tokens) / refill
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)
return tostring(wait)
"""

_script_lock = threading.Lock()
_registered_script = None


def _consume_script():
    global _registered_script
    with _script_lock:
        if _registered_script is None:
            from app.services.redis_client import get_redis

            _registered_script = get_redis().register_script(_CONSUME_SCRIPT)
        return _registered_script


def _consume_redis(prio: Priority) -> float:
    result = _consume_script()(
        keys=[f"{KEY_PREFIX}:{prio}", PENALTY_KEY],
        args=[
            _capacity(prio),
            _refill_rate(prio),
            1,
            time.time(),
            BUCKET_TTL_SECONDS,
        ],
    )
    return float(result)


# --- 프로세스 안 백엔드 (memory 롤백 경로) --------------------------------


class _LocalBucket:
    def __init__(self) -> None:
        self.tokens: float | None = None
        self.updated_at = 0.0
        self.guard = threading.Lock()


_local_buckets: dict[Priority, _LocalBucket] = {"high": _LocalBucket(), "low": _LocalBucket()}
_local_penalty = 1.0
_local_penalty_until = 0.0


def _local_penalty_factor() -> float:
    return _local_penalty if time.monotonic() < _local_penalty_until else 1.0


def _consume_local(prio: Priority) -> float:
    bucket = _local_buckets[prio]
    capacity = _capacity(prio)
    refill = _refill_rate(prio) / _local_penalty_factor()

    with bucket.guard:
        now = time.monotonic()
        if bucket.tokens is None:
            bucket.tokens = capacity
            bucket.updated_at = now

        bucket.tokens = min(capacity, bucket.tokens + max(now - bucket.updated_at, 0.0) * refill)
        bucket.updated_at = now

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return 0.0
        return (1 - bucket.tokens) / refill


# --- 공개 API -------------------------------------------------------------


def acquire(*, timeout: float | None = None) -> None:
    """Upbit REST 1회분 토큰을 받는다. 받을 때까지 **블로킹**한다.

    Redis가 죽었을 때는 통과시킨다 — 레이트리밋은 보호 장치이지 기능이 아니다. 버킷을
    못 읽는다고 캔들 조회를 통째로 막으면 Redis 장애가 자동매매 정지로 번진다. 대신 그냥
    넘기지 않고 로그를 남긴다.

    Raises:
        RateLimitTimeout: 제한 시간 안에 토큰을 받지 못했다.
    """
    prio = _priority.get()
    limit = settings.upbit_rest_wait_timeout_seconds if timeout is None else timeout
    deadline = time.monotonic() + limit
    waited = False

    while True:
        try:
            wait = _consume_redis(prio) if _enabled() else _consume_local(prio)
        except Exception:
            logger.warning("Upbit 토큰 버킷 조회 실패 — 이번 호출은 제한 없이 통과시킨다")
            return

        if wait <= 0:
            if waited:
                logger.info("Upbit 토큰 대기 종료 (priority=%s)", prio)
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RateLimitTimeout(
                f"Upbit REST 토큰을 {limit:.0f}초 안에 받지 못했다 (priority={prio})"
            )
        waited = True
        time.sleep(min(wait, remaining, MAX_SLEEP_SECONDS))


def note_throttled() -> None:
    """Upbit가 429로 거절했다. 리필 속도를 낮추고 TTL이 지나면 스스로 돌아온다.

    우리가 잡은 속도가 실제 제한보다 후했다는 뜻이므로 **반드시 로그로 남긴다.** 429를 먹고도
    같은 속도로 계속 두드리면 아무도 그 사실을 모른다 (06-observability.md 5장).
    """
    backoff = settings.upbit_rest_throttle_backoff_seconds
    factor = min(_current_penalty() * 2, MAX_PENALTY)
    logger.warning(
        "Upbit 429 — REST 리필 속도를 %.1f배 낮춘다 (%d초 후 자동 복구)", factor, backoff
    )

    if not _enabled():
        global _local_penalty, _local_penalty_until
        _local_penalty = factor
        _local_penalty_until = time.monotonic() + backoff
        return

    try:
        from app.services.redis_client import get_redis

        get_redis().set(PENALTY_KEY, factor, ex=backoff)
    except Exception:
        logger.warning("Upbit 429 백오프 기록 실패 — 이번 429는 반영되지 않는다")


def _current_penalty() -> float:
    if not _enabled():
        return _local_penalty_factor()
    try:
        from app.services.redis_client import get_redis

        raw = get_redis().get(PENALTY_KEY)
    except Exception:
        return 1.0
    return max(float(raw), 1.0) if raw else 1.0


def reset() -> None:
    """테스트용 — 프로세스 안 버킷과 백오프를 초기 상태로 되돌린다."""
    global _local_penalty, _local_penalty_until
    for bucket in _local_buckets.values():
        with bucket.guard:
            bucket.tokens = None
            bucket.updated_at = 0.0
    _local_penalty = 1.0
    _local_penalty_until = 0.0
