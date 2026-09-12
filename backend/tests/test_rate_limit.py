"""Upbit REST 토큰 버킷 (확장판 6단계, 04-async-jobs.md 3.2절).

버킷이 잘못되면 나타나는 실패는 두 방향이고 **양쪽 다 조용하다**:

- 너무 후하면 429가 나고, 그 여파를 캔들 채우기와 자동매매가 함께 맞는다.
- 너무 빡빡하면 캔들 채우기가 굶고, 워커는 "캔들 없음"으로 조용히 건너뛰기만 한다.

그래서 통과/거절 경계와 우선순위 격리를 숫자로 못 박아 둔다. 여기서는 전부 프로세스 안
버킷(`PRICE_CACHE_BACKEND=memory` 경로)으로 검증한다 — 산술은 Lua 쪽과 같고, Redis
없이도 돌아야 하는 회귀 테스트다.
"""

import threading
import time

import pytest

from app.config import settings
from app.services import rate_limit


@pytest.fixture(autouse=True)
def fresh_bucket(monkeypatch):
    """테스트마다 가득 찬 버킷에서 시작한다. 버킷은 모듈 전역이라 안 비우면 샌다."""
    monkeypatch.setattr(settings, "price_cache_backend", "memory")
    rate_limit.reset()
    yield
    rate_limit.reset()


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
            if taken > 1000:  # 리필이 무한정 통과시키면 여기서 멈춘다
                pytest.fail("버킷이 전혀 고갈되지 않는다")


def test_burst_is_capped():
    """가득 찬 버킷에서 뽑을 수 있는 양은 burst를 넘지 않는다."""
    taken = _drain("high")

    assert 1 <= taken <= settings.upbit_rest_burst


def test_refills_over_time(monkeypatch):
    """비워도 시간이 지나면 다시 통과한다 — 한 번 막히면 영영 막히는 게 아니다."""
    monkeypatch.setattr(settings, "upbit_rest_tokens_per_second", 100.0)
    rate_limit.reset()
    _drain("high")

    time.sleep(0.05)  # 100/s면 5개쯤 찬다

    with rate_limit.priority("high"):
        rate_limit.acquire(timeout=0)  # 예외가 안 나면 통과


def test_priorities_do_not_share_tokens():
    """저우선을 전부 써도 고우선 몫은 남아 있다.

    **이 테스트가 6단계의 핵심 주장이다** — 백테스트가 아무리 많이 돌아도 `scheduler`의
    캔들 채우기는 굶지 않는다 (04-async-jobs.md 3.2절 우선순위).
    """
    _drain("low")

    with rate_limit.priority("high"):
        rate_limit.acquire(timeout=0)


def test_timeout_raises_instead_of_blocking_forever():
    """토큰을 못 받으면 조용히 매달리지 않고 예외로 끝난다.

    무한 대기는 호출 스레드(백테스트·스케줄러 잡)를 통째로 묶어 두는데, 그 상태는 로그에
    아무 흔적도 남기지 않는다.
    """
    _drain("high")

    with rate_limit.priority("high"):
        with pytest.raises(rate_limit.RateLimitTimeout):
            rate_limit.acquire(timeout=0.05)


def test_throttle_backoff_slows_refill():
    """429를 받으면 리필이 느려진다 — 같은 시점에 기다려야 하는 시간이 길어진다."""
    _drain("high")
    wait_before = rate_limit._consume_local("high")

    rate_limit.note_throttled()
    assert rate_limit._local_penalty_factor() == pytest.approx(2.0)
    wait_after = rate_limit._consume_local("high")

    # 페널티 2배면 같은 토큰을 채우는 데 두 배가 걸린다. 벽시계가 사이에 조금 흐르므로
    # 정확한 배수가 아니라 "확실히 길어졌다"로 본다.
    assert wait_after > wait_before * 1.5


def test_throttle_backoff_expires(monkeypatch):
    """백오프는 TTL이 지나면 스스로 풀린다 — 사람이 안 만져도 원래 속도로 돌아온다."""
    monkeypatch.setattr(settings, "upbit_rest_throttle_backoff_seconds", 0)

    rate_limit.note_throttled()

    assert rate_limit._local_penalty_factor() == pytest.approx(1.0)


def test_backoff_is_capped():
    """백오프가 무한정 쌓이지 않는다 — 회복 불가능한 상태를 만들지 않기 위해서다."""
    for _ in range(10):
        rate_limit.note_throttled()

    assert rate_limit._local_penalty_factor() <= rate_limit.MAX_PENALTY


def test_redis_failure_does_not_block_calls(monkeypatch):
    """버킷을 못 읽으면 통과시킨다 — 레이트리밋은 보호 장치이지 기능이 아니다.

    여기서 막으면 Redis 장애가 곧 자동매매 정지로 번진다 (00-architecture.md 3.2절).
    """
    monkeypatch.setattr(settings, "price_cache_backend", "redis")
    monkeypatch.setattr(
        rate_limit, "_consume_redis", lambda prio: (_ for _ in ()).throw(RuntimeError("redis down"))
    )

    rate_limit.acquire(timeout=0)  # 예외가 안 나면 통과


def test_concurrent_acquire_does_not_exceed_burst():
    """여러 스레드가 동시에 달려들어도 burst를 넘겨 통과시키지 않는다.

    백테스트 스레드와 스케줄러 잡이 실제로 서로 다른 스레드에서 부른다.
    """
    granted = []
    guard = threading.Lock()

    def worker() -> None:
        with rate_limit.priority("high"):
            try:
                rate_limit.acquire(timeout=0)
            except rate_limit.RateLimitTimeout:
                return
        with guard:
            granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(granted) <= settings.upbit_rest_burst
