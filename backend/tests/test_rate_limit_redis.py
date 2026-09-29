"""Upbit 토큰 버킷의 **Redis/Lua 경로** (04-async-jobs.md 3.2절).

`test_rate_limit.py`는 픽스처가 백엔드를 `memory`로 고정해 두어서, 어느 구성으로 돌리든
Lua 스크립트를 **한 번도 실행하지 않는다.** 그런데 여러 프로세스가 한 IP를 공유하는 실제
운영 구성에서 도는 것은 정확히 그 Lua 쪽이다.

**이 파일이 필요한 진짜 이유는 `acquire()`가 예외를 삼키기 때문이다.** 버킷을 못 읽으면
"제한 없이 통과"시키는 것이 의도된 설계인데(레이트리밋은 보호 장치이지 기능이 아니다),
그 말은 곧 **Lua에 문법 오류가 있어도 아무 증상 없이 레이트리밋이 통째로 꺼진다**는 뜻이다.
그 상태를 잡을 수 있는 유일한 방법은 스크립트를 실제로 실행시켜 "제한이 걸리는지" 보는 것뿐이다.

`PRICE_CACHE_BACKEND=redis` 구성에서만 의미가 있으므로 나머지 구성에서는 건너뛴다 —
테스트 매트릭스가 그 구성을 항상 함께 돌린다.
"""

import threading
import time

import pytest

from app.config import settings
from app.services import rate_limit

pytestmark = pytest.mark.redis


@pytest.fixture(autouse=True)
def redis_bucket():
    """이 파일은 진짜 Redis 버킷을 쓴다 — `rate_limit.reset()`은 프로세스 안 버킷만 비우므로
    Redis 키는 직접 지워야 한다. 안 지우면 앞 테스트가 비워 둔 버킷을 물려받는다."""
    if settings.price_cache_backend != "redis":
        pytest.skip("PRICE_CACHE_BACKEND=redis 구성 전용")

    from app.services.redis_client import get_redis

    def _clear() -> None:
        get_redis().delete(
            f"{rate_limit.KEY_PREFIX}:high",
            f"{rate_limit.KEY_PREFIX}:low",
            rate_limit.PENALTY_KEY,
        )

    _clear()
    yield
    _clear()


def _drain(prio: rate_limit.Priority) -> int:
    """버킷이 빌 때까지 뽑아 쓰고 뽑은 횟수를 돌려준다."""
    taken = 0
    with rate_limit.priority(prio):
        while True:
            try:
                rate_limit.acquire(timeout=0)
            except rate_limit.RateLimitTimeout:
                return taken
            taken += 1
            if taken > 1000:  # 제한이 아예 안 걸리는 상태를 무한 루프로 만들지 않는다
                return taken


# ---------------------------------------------------------------- 스크립트가 실제로 도는가


def test_lua_path_actually_limits(redis_bucket):
    """**이 파일에서 가장 중요한 테스트.**

    버킷이 비면 `RateLimitTimeout`이 나야 한다. Lua가 깨져 있으면 `acquire`가 예외를 삼키고
    전부 통과시키므로 여기서 타임아웃이 영영 안 난다 — 그 침묵이 바로 잡으려는 대상이다.
    """
    taken = _drain("high")

    assert taken <= rate_limit._capacity("high") + 1, (
        f"용량({rate_limit._capacity('high')})보다 많이 통과했다 — "
        f"Lua가 실행되지 않고 전부 통과하고 있을 수 있다 (taken={taken})"
    )
    with rate_limit.priority("high"):
        with pytest.raises(rate_limit.RateLimitTimeout):
            rate_limit.acquire(timeout=0)


def test_bucket_state_lives_in_redis_not_in_the_process(redis_bucket):
    """버킷이 Redis에 있어야 여러 프로세스가 한 IP 예산을 나눠 쓴다.

    프로세스 안 버킷으로 떨어지면 프로세스 수만큼 호출량이 배가 된다 — 429의 지름길이다.
    """
    from app.services.redis_client import get_redis

    _drain("high")

    raw = get_redis().hgetall(f"{rate_limit.KEY_PREFIX}:high")

    assert raw, "소진했는데 Redis에 버킷 키가 없다 (프로세스 안 버킷을 쓰고 있다)"
    assert float(raw["tokens"]) < 1


def test_second_consumer_sees_the_drained_bucket(redis_bucket):
    """다른 소비자(=다른 프로세스에 해당)가 이미 비워진 버킷을 그대로 본다.

    스크립트 등록 캐시를 지워 "막 기동한 프로세스"에 가깝게 만든 뒤 다시 시도한다.
    """
    _drain("high")

    rate_limit._registered_script = None  # 새 프로세스가 스크립트를 처음 등록하는 상황

    with rate_limit.priority("high"):
        with pytest.raises(rate_limit.RateLimitTimeout):
            rate_limit.acquire(timeout=0)


# ---------------------------------------------------------------- 우선순위 격리


def test_draining_low_does_not_touch_high(redis_bucket):
    """저우선이 아무리 써도 고우선 몫은 남아 있어야 한다 — 버킷을 나눈 이유 그 자체다.

    굶어야 한다면 백테스트(low)가 굶어야 하고 캔들 채우기(high)는 살아야 한다.
    """
    _drain("low")

    with rate_limit.priority("high"):
        rate_limit.acquire(timeout=0)  # 예외가 나면 실패


def test_high_and_low_use_separate_redis_keys(redis_bucket):
    from app.services.redis_client import get_redis

    _drain("high")

    assert get_redis().exists(f"{rate_limit.KEY_PREFIX}:high")
    assert not get_redis().exists(f"{rate_limit.KEY_PREFIX}:low"), (
        "고우선 소비가 저우선 버킷까지 건드렸다"
    )


# ---------------------------------------------------------------- 리필


def test_tokens_refill_over_time(redis_bucket, monkeypatch):
    """시간이 지나면 토큰이 찬다. 실제로 기다리지 않고 시계를 앞으로 돌린다."""
    _drain("high")

    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + 5)

    with rate_limit.priority("high"):
        rate_limit.acquire(timeout=0)  # 5초면 리필되고도 남는다


def test_clock_going_backwards_does_not_create_tokens(redis_bucket, monkeypatch):
    """시계가 뒤로 튀어도 토큰이 거꾸로 줄거나 늘면 안 된다 (Lua의 `elapsed` 하한 처리).

    프로세스마다 시각을 직접 넘기는 구조라 시계 역행이 실제로 가능하다.
    """
    _drain("high")

    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time - 3600)

    with rate_limit.priority("high"):
        with pytest.raises(rate_limit.RateLimitTimeout):
            rate_limit.acquire(timeout=0)


# ---------------------------------------------------------------- 429 백오프


def test_note_throttled_records_penalty_with_ttl(redis_bucket):
    """429를 먹으면 페널티가 Redis에 남고 TTL이 지나면 스스로 풀린다."""
    from app.services.redis_client import get_redis

    rate_limit.note_throttled()

    penalty = get_redis().get(rate_limit.PENALTY_KEY)
    assert penalty is not None, "429를 먹었는데 백오프가 기록되지 않았다"
    assert float(penalty) == 2.0
    assert get_redis().ttl(rate_limit.PENALTY_KEY) > 0, "TTL이 없으면 영영 안 풀린다"


def test_penalty_compounds_up_to_a_ceiling(redis_bucket):
    """429가 반복되면 더 낮추되 상한에서 멈춘다 — 무한정 낮추면 회복 불가능해진다."""
    from app.services.redis_client import get_redis

    for _ in range(10):
        rate_limit.note_throttled()

    assert float(get_redis().get(rate_limit.PENALTY_KEY)) == rate_limit.MAX_PENALTY


def test_penalty_slows_the_refill(redis_bucket, monkeypatch):
    """페널티가 걸리면 같은 시간에 덜 채워진다 — 백오프가 실제로 효과가 있는지 본다."""
    _drain("high")
    rate_limit.note_throttled()  # 리필 속도 1/2

    # 페널티가 없었다면 충분했을 만큼만 시간을 돌린다.
    just_enough = 1.0 / rate_limit._refill_rate("high")
    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + just_enough)

    with rate_limit.priority("high"):
        with pytest.raises(rate_limit.RateLimitTimeout):
            rate_limit.acquire(timeout=0)


# ---------------------------------------------------------------- 장애 시 통과


def test_redis_failure_passes_through_instead_of_blocking(redis_bucket, monkeypatch):
    """Redis가 죽으면 제한 없이 통과시킨다 — 레이트리밋 장애가 자동매매 정지로 번지면 안 된다.

    **의도된 동작**이다. 그리고 이 관대함 때문에 Lua가 깨져도 조용하다는 것이
    `test_lua_path_actually_limits`가 필요한 이유다.
    """
    _drain("high")

    def _boom(*args, **kwargs):
        raise ConnectionError("redis 연결 실패")

    monkeypatch.setattr(rate_limit, "_consume_redis", _boom)

    with rate_limit.priority("high"):
        rate_limit.acquire(timeout=0)  # 비어 있어도 통과해야 한다


# ---------------------------------------------------------------- 동시 소비


def test_concurrent_consumers_never_exceed_capacity(redis_bucket):
    """여러 소비자가 동시에 뽑아도 총합이 용량을 넘으면 안 된다.

    리필·소비·페널티 조회를 Lua 한 번으로 묶은 이유가 이것이다 — 따로 하면 두 소비자가
    같은 값을 읽고 각자 소비해 버킷을 초과한다.
    """
    capacity = rate_limit._capacity("high")
    taken = [0] * 4
    barrier = threading.Barrier(len(taken))

    def _consume(index: int) -> None:
        barrier.wait()
        with rate_limit.priority("high"):
            while True:
                try:
                    rate_limit.acquire(timeout=0)
                except rate_limit.RateLimitTimeout:
                    return
                taken[index] += 1
                if sum(taken) > 1000:
                    return

    threads = [threading.Thread(target=_consume, args=(i,)) for i in range(len(taken))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # 리필이 도는 동안에도 뽑히므로 약간의 여유를 둔다 — 중요한 것은 "몇 배"가 아니라는 점이다.
    assert sum(taken) <= capacity + 2, f"동시 소비가 용량을 넘었다: {sum(taken)} > {capacity}"
