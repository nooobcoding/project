"""PostgreSQL advisory lock 기반 리더 선출·샤드 점유 (03-worker-orchestration.md 2.1·2.2절).

**이 모듈이 무너지면 두 프로세스가 동시에 같은 일을 한다** — market-data가 둘이면 틱이 두 번
들어오고, worker가 같은 샤드를 둘이 잡으면 같은 슬롯이 두 번 매수한다. 그런데 지금까지
`leader.py`는 한 번도 검증된 적이 없고, 샤딩 테스트들은 오히려 이걸 monkeypatch로 **꺼두고**
돈다 (그쪽은 샤드 경계 로직이 관심사라 그게 맞다). 그래서 잠금 자체는 여기서만 본다.

**별도 프로세스를 띄우지 않는 이유**: advisory lock은 세션 단위라, 한 프로세스 안에서도
커넥션을 따로 열면 그것이 곧 별개의 경쟁자다. 프로세스를 띄워야만 재현되는 것은 SIGKILL
페일오버 정도이고, 나머지는 여기서 매 실행마다 검증하는 편이 낫다.

**개발 서버와의 충돌을 피하려고 네임스페이스를 갈아끼운다.** 개발용 backend 컨테이너가 떠
있으면 그쪽이 이미 `market-data`/`scheduler` 리더 락을 쥐고 있어서, 진짜 네임스페이스로
테스트하면 개발 서버 기동 여부에 따라 결과가 바뀐다. 검증 대상은 네임스페이스 값이 아니라
잠금 의미론이므로 테스트 전용 값으로 격리한다.
"""

import threading

import pytest
from sqlalchemy import create_engine, text

from app.config import settings
from app.services import leader
from tests.conftest import requires_db

# 앱이 쓰지 않는 번호대 — 개발 서버·다른 테스트와 겹치지 않게 한다.
TEST_ROLE_NAMESPACE = 49001
TEST_SHARD_NAMESPACE_A = 49002
TEST_SHARD_NAMESPACE_B = 49003


@pytest.fixture
def isolated_role_namespace(monkeypatch):
    monkeypatch.setattr(leader, "ROLE_LEADER_NAMESPACE", TEST_ROLE_NAMESPACE)


@pytest.fixture
def leader_locks(isolated_role_namespace):
    """`LeaderLock`을 만들어 주고 끝나면 **반드시** 놓아준다.

    놓지 않으면 그 락이 테스트 세션이 끝날 때까지 남아 뒤따르는 테스트가 리더가 되지 못한다.
    """
    created: list[leader.LeaderLock] = []

    def _make(role: str = "market-data") -> leader.LeaderLock:
        lock = leader.LeaderLock(role)
        created.append(lock)
        return lock

    yield _make

    for lock in created:
        lock.release()


@pytest.fixture
def shard_locks():
    created: list[leader.ShardLocks] = []

    def _make(namespace: int = TEST_SHARD_NAMESPACE_A, shard_count: int = 4, label: str = "test"):
        locks = leader.ShardLocks(namespace, shard_count, label)
        created.append(locks)
        return locks

    yield _make

    for locks in created:
        locks.release_all()


# ---------------------------------------------------------------- 리더 상호배제


@requires_db
def test_only_one_leader_can_hold_a_role(leader_locks):
    """같은 역할을 두 세션이 동시에 쥘 수 없다 — 이것이 무너지면 market-data가 둘이 된다."""
    first = leader_locks()
    second = leader_locks()

    assert first.try_acquire() is True
    assert second.try_acquire() is False, "두 세션이 동시에 리더가 됐다"


@requires_db
def test_release_lets_the_next_candidate_take_over(leader_locks):
    """리더가 물러나면 다음 후보가 이어받는다 (페일오버의 기본형)."""
    first = leader_locks()
    second = leader_locks()
    assert first.try_acquire() is True
    assert second.try_acquire() is False

    first.release()

    assert second.try_acquire() is True


@requires_db
def test_losing_candidate_does_not_hold_a_connection(leader_locks):
    """락을 못 잡은 후보는 커넥션을 놓아야 한다 (00-architecture.md 3.5절 커넥션 예산).

    후보가 여럿인 구성에서 진 쪽이 커넥션을 붙들고 있으면 그만큼 PostgreSQL 커넥션이 논다.
    """
    winner = leader_locks()
    loser = leader_locks()
    assert winner.try_acquire() is True

    assert loser.try_acquire() is False
    assert loser._connection is None, "락을 못 잡았는데 커넥션을 쥐고 있다"


@requires_db
def test_is_held_reports_false_for_a_candidate_that_never_acquired(leader_locks):
    assert leader_locks().is_held() is False


@requires_db
def test_is_held_asks_the_database_not_a_local_flag(leader_locks):
    """소유 확인은 애플리케이션 플래그가 아니라 pg_locks를 봐야 한다.

    커넥션이 끊겼다 조용히 재연결되면 로컬 플래그는 그대로인데 락만 사라진다 — 그 상태를
    잡으려고 매번 DB에 되묻는 설계다. 여기서는 락만 몰래 풀어 같은 상황을 만든다.
    """
    lock = leader_locks()
    assert lock.try_acquire() is True
    assert lock.is_held() is True

    lock._connection.execute(
        text("SELECT pg_advisory_unlock(:ns, :lid)"),
        {"ns": TEST_ROLE_NAMESPACE, "lid": leader._ROLE_LOCK_IDS["market-data"]},
    )

    assert lock.is_held() is False, "락이 사라졌는데 여전히 리더라고 답한다"


# ---------------------------------------------------------------- hold()가 존재하는 이유


@requires_db
def test_repeated_try_acquire_stacks_the_lock(leader_locks):
    """같은 세션이 다시 잠그면 PostgreSQL은 **거부하지 않고 참조 횟수를 올린다.**

    `hold()`의 docstring이 "실측 확인"이라고 적어둔 그 성질이다. 이 성질 때문에
    `try_acquire`를 주기적으로 부르면 unlock 한 번으로는 안 풀리는 상태가 쌓인다.
    """
    lock = leader_locks()
    assert lock.try_acquire() is True
    assert lock.try_acquire() is True  # 같은 세션 — 거부되지 않는다

    lock._connection.execute(
        text("SELECT pg_advisory_unlock(:ns, :lid)"),
        {"ns": TEST_ROLE_NAMESPACE, "lid": leader._ROLE_LOCK_IDS["market-data"]},
    )

    assert lock.is_held() is True, "unlock 한 번에 풀렸다면 참조 횟수가 쌓이지 않은 것이다"


@requires_db
def test_hold_is_idempotent_and_stays_releasable(leader_locks):
    """`hold()`는 반복 호출해도 참조 횟수를 쌓지 않아 unlock 한 번으로 풀린다.

    이것이 주기적으로 깨어나는 scheduler가 `try_acquire`가 아니라 `hold`를 쓰는 이유다.
    """
    lock = leader_locks()
    for _ in range(3):
        assert lock.hold() is True

    lock._connection.execute(
        text("SELECT pg_advisory_unlock(:ns, :lid)"),
        {"ns": TEST_ROLE_NAMESPACE, "lid": leader._ROLE_LOCK_IDS["market-data"]},
    )

    assert lock.is_held() is False, "hold()가 참조 횟수를 쌓았다"


@requires_db
def test_hold_acquires_when_not_yet_leader(leader_locks):
    lock = leader_locks()

    assert lock.hold() is True
    assert lock.is_held() is True


# ---------------------------------------------------------------- 풀 함정 (2.2절)


@requires_db
def test_lock_on_a_pooled_connection_silently_vanishes(isolated_role_namespace):
    """**대조군** — 풀에서 꺼낸 커넥션으로 잠그면 락이 조용히 사라질 수 있다.

    이것이 `leader.py`가 NullPool 전용 커넥션을 따로 쓰는 이유다. 풀이 커넥션을 정리하면
    세션이 죽고 락은 사라지는데, 애플리케이션은 여전히 자기가 리더인 줄 안다 — 기동 직후엔
    멀쩡하다가 나중에 깨지는, 재현이 어려운 종류의 사고다.

    앱이 공유하는 엔진을 dispose하면 다른 테스트까지 망가지므로 여기서만 쓰는 엔진을 만든다.
    """
    pooled_engine = create_engine(settings.database_url)
    lock_id = 77

    connection = pooled_engine.connect()
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:ns, :lid)"),
        {"ns": TEST_ROLE_NAMESPACE, "lid": lock_id},
    ).scalar()
    assert acquired is True
    connection.close()  # 풀로 반납 — 세션은 아직 살아 있다

    pooled_engine.dispose()  # 풀이 커넥션을 정리한다 → 세션이 죽고 락도 사라진다

    # 사라졌는지는 "다른 세션이 같은 락을 잡을 수 있는가"로 확인한다.
    with leader._leader_engine().connect() as observer:
        stolen = observer.execute(
            text("SELECT pg_try_advisory_lock(:ns, :lid)"),
            {"ns": TEST_ROLE_NAMESPACE, "lid": lock_id},
        ).scalar()
        observer.execute(
            text("SELECT pg_advisory_unlock(:ns, :lid)"),
            {"ns": TEST_ROLE_NAMESPACE, "lid": lock_id},
        )

    assert stolen is True, (
        "풀 커넥션의 락이 살아남았다 — 이 테스트의 전제(풀 함정)가 더 이상 성립하지 않는다"
    )


@requires_db
def test_lock_engine_does_not_pool_connections():
    """**실험군의 구조적 절반** — 락 전용 엔진은 NullPool이어야 한다.

    위 대조군이 보여준 사고를 구조적으로 막는 것이 이 설정 하나다. 누가 편의를 위해 앱의
    공용 엔진으로 바꾸면 그 순간 대조군과 같은 처지가 되므로 여기서 못박아 둔다.
    """
    from sqlalchemy.pool import NullPool

    assert isinstance(leader._leader_engine().pool, NullPool)


@requires_db
def test_shard_locks_keep_one_session_across_refreshes(shard_locks):
    """**실험군의 행동적 절반** — 주기마다 커넥션을 새로 열면 안 된다.

    `refresh`는 주기적으로 불린다. 매번 커넥션을 새로 열어 쓰고 닫는 구현이었다면 세션이
    바뀌면서 **직전 주기에 잡은 락이 전부 사라진다** — 그러고도 다시 잡으니 겉보기 점유는
    같아서 조용히 넘어가고, 그 틈에 다른 프로세스가 같은 샤드를 가져갈 수 있다.
    """

    def _backend_pid(locks) -> int:
        return locks._connection.execute(text("SELECT pg_backend_pid()")).scalar()

    locks = shard_locks()
    owned = locks.refresh()
    assert owned, "샤드를 하나도 못 잡았다"
    first_pid = _backend_pid(locks)

    for _ in range(3):
        assert locks.refresh() == owned
        assert _backend_pid(locks) == first_pid, "주기마다 세션이 바뀌고 있다"


# ---------------------------------------------------------------- 샤드 점유


@requires_db
def test_shards_are_split_not_shared(shard_locks):
    """두 점유자가 같은 샤드를 동시에 가질 수 없다 — 겹치면 같은 슬롯을 둘이 매수한다."""
    first = shard_locks()
    second = shard_locks()

    first_owned = first.refresh()
    second_owned = second.refresh()

    assert first_owned & second_owned == set(), (
        f"같은 샤드를 둘이 점유했다: {first_owned & second_owned}"
    )
    assert first_owned, "먼저 온 쪽이 아무것도 못 잡았다"


@requires_db
def test_first_claimant_takes_everything_and_later_one_waits(shard_locks):
    """먼저 뜬 프로세스가 전부 가져가고, 나중에 뜬 쪽은 빈 손으로 시작한다 (재균형은 점진적)."""
    first = shard_locks()
    second = shard_locks()

    assert first.refresh() == {0, 1, 2, 3}
    assert second.refresh() == set()


@requires_db
def test_released_shards_are_picked_up_by_the_survivor(shard_locks):
    """점유자가 사라지면 그 샤드를 남은 쪽이 집어간다 — 프로세스 죽음의 페일오버 경로다.

    실제로는 세션이 끊기며 풀리는데, `release_all`도 같은 지점(세션 정리)을 통과한다.
    """
    first = shard_locks()
    second = shard_locks()
    assert first.refresh() == {0, 1, 2, 3}
    assert second.refresh() == set()

    first.release_all()

    assert second.refresh() == {0, 1, 2, 3}


@requires_db
def test_shard_locks_use_a_single_connection_for_all_shards(shard_locks):
    """샤드 수만큼 커넥션을 열면 커넥션 예산이 바로 깨진다 (00-architecture.md 3.5절).

    advisory lock은 세션 단위라 한 세션이 여러 개를 쥘 수 있다는 점을 쓰는 설계다.
    """
    locks = shard_locks(shard_count=4)
    owned = locks.refresh()

    assert len(owned) == 4
    backend_pids = locks._connection.execute(
        text(
            """
            SELECT COUNT(DISTINCT pid) FROM pg_locks
            WHERE locktype = 'advisory' AND classid = :ns AND objsubid = 2 AND granted
            """
        ),
        {"ns": TEST_SHARD_NAMESPACE_A},
    ).scalar()

    assert backend_pids == 1, f"샤드 4개를 {backend_pids}개 세션에 나눠 쥐고 있다"


@requires_db
def test_different_namespaces_do_not_collide(shard_locks):
    """matcher와 worker는 네임스페이스가 달라야 한다 — 같으면 한쪽이 잡은 샤드를 다른 쪽이 못 잡는다.

    코드 주석이 "필수"라고 적어둔 제약이라, 상수가 실제로 다른지와 그 분리가 동작하는지를
    함께 본다.
    """
    assert leader.MATCHER_SHARD_NAMESPACE != leader.WORKER_SHARD_NAMESPACE

    matcher_side = shard_locks(namespace=TEST_SHARD_NAMESPACE_A, label="matcher")
    worker_side = shard_locks(namespace=TEST_SHARD_NAMESPACE_B, label="worker")

    assert matcher_side.refresh() == {0, 1, 2, 3}
    assert worker_side.refresh() == {0, 1, 2, 3}, "네임스페이스가 갈렸는데 서로를 막았다"


@requires_db
def test_occupied_shards_sees_locks_held_by_other_sessions(shard_locks):
    """커버리지 검사는 "아무도 안 잡은 샤드"를 찾아야 하므로 남의 세션 락까지 봐야 한다."""
    locks = shard_locks(namespace=TEST_SHARD_NAMESPACE_B)
    owned = locks.refresh()

    assert leader.occupied_shards(TEST_SHARD_NAMESPACE_B) == owned


@requires_db
def test_refresh_is_safe_to_call_repeatedly(shard_locks):
    """주기적으로 불리는 함수다 — 반복 호출이 참조 횟수를 쌓거나 점유를 바꾸면 안 된다."""
    locks = shard_locks()
    first = locks.refresh()

    for _ in range(3):
        assert locks.refresh() == first

    locks.release_all()

    competitor = shard_locks()
    assert competitor.refresh() == first, "release_all 한 번으로 안 풀렸다 (참조 횟수가 쌓였다)"


@requires_db
def test_owner_never_loses_a_shard_to_a_competitor_across_refreshes(shard_locks):
    """점유자가 주기를 도는 동안 경쟁자가 그 샤드를 가로채면 안 된다.

    앞의 "세션이 유지되는가"는 **원인**을 보고, 이 테스트는 **결과**를 본다. 주기마다
    커넥션을 새로 여는 구현이면 재획득 직전에 락이 비는 순간이 생기는데, 단일 스레드로는
    그 틈에 아무도 없어서 겉보기 점유가 똑같다 — 경쟁자가 실제로 같은 순간에 달려들어야
    드러난다.
    """
    owner = shard_locks(shard_count=4)
    competitor = shard_locks(shard_count=4)

    assert owner.refresh() == {0, 1, 2, 3}

    stolen: list[set[int]] = []
    stop = threading.Event()

    def _keep_trying() -> None:
        while not stop.is_set():
            got = competitor.refresh()
            if got:
                stolen.append(got)

    thief = threading.Thread(target=_keep_trying)
    thief.start()
    try:
        for _ in range(50):
            assert owner.refresh() == {0, 1, 2, 3}, "주기를 도는 사이에 샤드를 잃었다"
    finally:
        stop.set()
        thief.join(timeout=10)

    assert stolen == [], f"경쟁자가 점유 중인 샤드를 가로챘다: {stolen}"


@requires_db
def test_concurrent_refresh_never_double_assigns_a_shard(shard_locks):
    """여러 점유자가 **동시에** 들어와도 샤드가 겹치면 안 된다.

    순차로 부르면 먼저 온 쪽이 다 가져가 경합이 없다. 실제 배포에서는 여러 워커가 같은 순간에
    기동하므로 그 순간을 만들어 본다.
    """
    contenders = [shard_locks(shard_count=8) for _ in range(4)]
    barrier = threading.Barrier(len(contenders))
    results: list[set[int]] = [set()] * len(contenders)

    def _claim(index: int) -> None:
        barrier.wait()
        results[index] = contenders[index].refresh()

    threads = [threading.Thread(target=_claim, args=(i,)) for i in range(len(contenders))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    everything = [shard for owned in results for shard in owned]
    assert len(everything) == len(set(everything)), f"샤드가 중복 배정됐다: {results}"
