"""역할 리더 선출 — PostgreSQL advisory lock.

`market-data`처럼 "정확히 1개만 활성"이어야 하는 역할이 쓴다 (docs-scale/00-architecture.md
3.3절). 별도 코디네이터(etcd·ZooKeeper·Redis lock)를 들이지 않고 이미 있는 PostgreSQL을
쓰며, **세션이 끊기면 락이 자동 해제되므로 페일오버가 공짜로 따라온다** — 프로세스가 죽거나
네트워크가 끊기면 다음 후보가 다음 재시도 주기에 집어간다.

**함정 — advisory lock은 세션 단위다** (03-worker-orchestration.md 2.2절):
SQLAlchemy 커넥션 풀이 커넥션을 반납·재활용하면 락이 풀리고, 그러면 두 프로세스가 동시에
리더가 된다. 기동 직후에는 멀쩡하다가 풀이 커넥션을 재활용하는 순간 깨지는, 재현이 어려운
종류의 사고다. 그래서 여기서는 풀에서 꺼낸 커넥션을 쓰지 않고 **NullPool 엔진의 전용
커넥션 하나를 리더인 동안 계속 붙잡는다.** 이 커넥션이 풀 예산 바깥으로 세어지는 이유이기도
하다 (00-architecture.md 3.5절).

`is_held()`로 소유를 주기적으로 재확인하는 것도 같은 절의 요구사항이다 — 락을 잃은 줄
모르고 계속 리더 행세를 하는 상태를 막는다.
"""

import logging
import threading
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)

# 리더 호스트가 통째로 죽거나 네트워크가 끊기면 FIN이 안 가므로, PostgreSQL은 세션이 죽은
# 줄 모르고 락을 계속 쥐고 있다 — OS 기본 keepalive(리눅스 약 2시간)까지 아무도 승격하지
# 못한다. libpq keepalive를 직접 걸어 1분 안에 끊기게 한다. 프로세스만 죽는 경우는 FIN이
# 가므로 지금도 즉시 풀린다.
_KEEPALIVE_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}

# advisory lock은 (classid, objid) 두 int로 식별한다. 역할 리더용 네임스페이스를 하나 잡아
# 두고, 5·7단계의 샤드 점유(matcher·worker)는 각자 다른 네임스페이스를 쓴다.
ROLE_LEADER_NAMESPACE = 4001
_ROLE_LOCK_IDS = {"market-data": 1, "scheduler": 2}

# 심볼 샤드 점유용 (02-market-data.md 4.3절). 7단계의 worker 샤드는 또 다른 값을 쓴다.
MATCHER_SHARD_NAMESPACE = 4002


@lru_cache
def _leader_engine():
    """리더 락 전용 엔진.

    NullPool이라 커넥션을 풀에 반납하지 않는다 — 풀이 재활용하면서 락이 풀리는 사고를
    구조적으로 막는다. AUTOCOMMIT은 이 커넥션이 몇 시간씩 idle in transaction으로 남아
    vacuum을 막는 것을 피하기 위한 것이다 (advisory lock은 트랜잭션이 아니라 세션에
    붙으므로 커밋과 무관하게 유지된다).
    """
    return create_engine(
        settings.database_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args=_KEEPALIVE_ARGS,
    )


class LeaderLock:
    """역할 하나의 리더십. 획득한 동안 전용 커넥션 하나를 붙잡는다.

    세 메서드는 서로 다른 스레드에서 불릴 수 있다 — 호출부가 `asyncio.to_thread`로
    감싸기 때문이고, 특히 종료 시점에는 소유 확인(`is_held`)이 아직 스레드에서 도는 중에
    `release`가 불릴 수 있다. SQLAlchemy Connection은 스레드 안전하지 않으므로 락으로
    직렬화한다.
    """

    def __init__(self, role: str) -> None:
        self.role = role
        self._lock_id = _ROLE_LOCK_IDS[role]
        self._connection = None
        self._guard = threading.Lock()

    def try_acquire(self) -> bool:
        """락을 시도한다. 이미 다른 프로세스가 쥐고 있으면 즉시 False (대기하지 않는다).

        DB가 아직 없거나 접속이 끊긴 경우도 False다 — 호출부는 "지금은 리더가 아니다"로만
        다루고 다음 주기에 다시 시도하면 된다 (DB 없이도 서버는 기동한다, database.py).
        """
        with self._guard:
            try:
                if self._connection is None:
                    self._connection = _leader_engine().connect()
                acquired = bool(
                    self._connection.execute(
                        text("SELECT pg_try_advisory_lock(:namespace, :lock_id)"),
                        {"namespace": ROLE_LEADER_NAMESPACE, "lock_id": self._lock_id},
                    ).scalar()
                )
            except Exception:
                logger.warning("%s 리더 락 시도 실패 — 다음 주기에 재시도한다", self.role)
                self._discard_connection()
                return False

            if not acquired:
                # 대기하는 동안 커넥션을 붙들고 있을 이유가 없다. 후보가 여럿이면 그만큼
                # PostgreSQL 커넥션을 놀리게 된다 (00-architecture.md 3.5절 커넥션 예산).
                self._discard_connection()
            return acquired

    def hold(self) -> bool:
        """지금 이 프로세스가 리더인지 — 아니면 한 번 시도해 본다. **반복 호출해도 안전하다.**

        `try_acquire`를 주기적으로 부르면 안 된다. PostgreSQL advisory lock은 같은 세션이
        다시 잠그면 거부하지 않고 **참조 횟수를 올린다** — 5번 부르면 `pg_advisory_unlock`
        한 번으로는 안 풀린다(실측 확인). 지금은 `release`가 커넥션까지 닫아 세션째 정리하기
        때문에 결과적으로 풀리지만, **락 해제가 unlock이 아니라 커넥션 종료에 의존하는
        상태**를 20초짜리 잡 주기에 얹어 두는 것은 위험하다. `is_held`는 `pg_locks`를 볼 뿐
        잠그지 않으므로 이미 리더인 경우에 부작용이 없고, 쓸데없는 왕복도 한 번 줄어든다.

        `market-data`처럼 리더인 동안 계속 도는 역할이 아니라, `scheduler`처럼 **주기적으로
        깨어나 매번 자격을 확인하는** 역할을 위한 것이다.
        """
        return self.is_held() or self.try_acquire()

    def is_held(self) -> bool:
        """이 세션이 실제로 락을 쥐고 있는지 DB에 되묻는다.

        커넥션이 끊겼다 조용히 재연결되는 등으로 락만 사라진 상태를 잡아내기 위한 것이라,
        애플리케이션 쪽 플래그가 아니라 `pg_locks`를 본다.
        """
        with self._guard:
            if self._connection is None:
                return False
            try:
                return bool(
                    self._connection.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM pg_locks
                                WHERE locktype = 'advisory'
                                  AND classid = :namespace
                                  AND objid = :lock_id
                                  AND objsubid = 2
                                  AND pid = pg_backend_pid()
                                  AND granted
                            )
                            """
                        ),
                        {"namespace": ROLE_LEADER_NAMESPACE, "lock_id": self._lock_id},
                    ).scalar()
                )
            except Exception:
                logger.warning("%s 리더십 확인 실패 — 리더십을 잃은 것으로 간주한다", self.role)
                return False

    def release(self) -> None:
        """락을 풀고 전용 커넥션을 닫는다. 커넥션만 닫아도 서버가 락을 해제하지만,
        명시적으로 풀어 다음 후보의 승격을 앞당긴다."""
        with self._guard:
            if self._connection is None:
                return
            try:
                self._connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
                    {"namespace": ROLE_LEADER_NAMESPACE, "lock_id": self._lock_id},
                )
            except Exception:
                logger.warning("%s 리더 락 해제 실패 — 커넥션을 닫아 세션째 정리한다", self.role)
            finally:
                self._discard_connection()

    def _discard_connection(self) -> None:
        """호출부가 이미 `_guard`를 쥔 상태에서만 부른다 — threading.Lock은 재진입이 안 된다."""
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:
            logger.warning("%s 리더 락 커넥션 정리 실패", self.role)
        finally:
            self._connection = None


class ShardLocks:
    """샤드 집합의 점유. 잡히는 샤드를 전부 가져가고, 못 잡은 것은 다음 주기에 다시 노린다.

    **커넥션은 하나뿐이다.** advisory lock은 세션 단위라 한 세션이 여러 개를 동시에 쥘 수
    있다 — 샤드마다 커넥션을 열면 `SHARD_COUNT`만큼 커넥션이 늘어나 커넥션 예산이 바로
    깨진다 (00-architecture.md 3.5절).

    재균형은 "주기적으로 못 잡은 샤드를 다시 시도"하는 것뿐이다. 프로세스가 죽으면 세션이
    끊기며 그 샤드들이 자동으로 풀리고, 살아 있는 프로세스가 다음 주기에 집어간다. 프로세스를
    추가하면 이미 점유된 샤드는 못 잡으므로 자연히 남은 것만 가져간다
    (03-worker-orchestration.md 2.1절).
    """

    def __init__(self, namespace: int, shard_count: int, label: str) -> None:
        self.namespace = namespace
        self.shard_count = shard_count
        self.label = label
        self._owned: set[int] = set()
        self._connection = None
        self._guard = threading.Lock()

    @property
    def owned(self) -> set[int]:
        return set(self._owned)

    def refresh(self) -> set[int]:
        """못 잡은 샤드를 다시 시도하고, 쥐고 있던 샤드의 소유를 재확인한다.

        DB가 흔들리면 전부 놓은 것으로 보고한다 — 소유를 확신할 수 없는 상태에서 계속
        일하는 것보다, 아무것도 점유하지 않은 상태로 떨어지고 다음 주기에 다시 잡는 편이
        안전하다. 샤드가 비는 것 자체는 커버리지 경고가 잡는다 (06-observability.md 3.4절).
        """
        with self._guard:
            try:
                if self._connection is None:
                    self._connection = _leader_engine().connect()
                self._owned = self._verify_owned()
                for shard_id in range(self.shard_count):
                    if shard_id in self._owned:
                        continue
                    acquired = self._connection.execute(
                        text("SELECT pg_try_advisory_lock(:namespace, :shard_id)"),
                        {"namespace": self.namespace, "shard_id": shard_id},
                    ).scalar()
                    if acquired:
                        self._owned.add(shard_id)
            except Exception:
                logger.warning("%s 샤드 점유 갱신 실패 — 전부 놓은 것으로 본다", self.label)
                self._owned = set()
                self._discard_connection()
            return set(self._owned)

    def _verify_owned(self) -> set[int]:
        """이 세션이 실제로 쥐고 있는 샤드를 DB에 되묻는다. 커넥션이 끊겼다 재연결되면
        애플리케이션 쪽 기록만 남고 락은 사라져 있을 수 있다 (2.2절 함정)."""
        rows = self._connection.execute(
            text(
                """
                SELECT objid FROM pg_locks
                WHERE locktype = 'advisory'
                  AND classid = :namespace
                  AND objsubid = 2
                  AND pid = pg_backend_pid()
                  AND granted
                """
            ),
            {"namespace": self.namespace},
        ).scalars()
        return {int(objid) for objid in rows}

    def release_all(self) -> None:
        with self._guard:
            if self._connection is None:
                return
            try:
                self._connection.execute(
                    text("SELECT pg_advisory_unlock_all()")
                )
            except Exception:
                logger.warning("%s 샤드 락 해제 실패 — 커넥션을 닫아 세션째 정리한다", self.label)
            finally:
                self._owned = set()
                self._discard_connection()

    def _discard_connection(self) -> None:
        """호출부가 이미 `_guard`를 쥔 상태에서만 부른다."""
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:
            logger.warning("%s 샤드 락 커넥션 정리 실패", self.label)
        finally:
            self._connection = None


def occupied_shards(namespace: int) -> set[int]:
    """지금 누군가 점유하고 있는 샤드 전체 (프로세스 무관). 커버리지 검사용이다.

    `worker_heartbeats`로는 빈 샤드를 못 찾는다 — 살아 있는 프로세스만 행을 남기므로
    아무도 점유하지 않은 샤드는 행 자체가 없어서 아무 경고도 안 난다
    (06-observability.md 3.4절). 그래서 락 자체를 직접 센다.
    """
    with _leader_engine().connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT objid FROM pg_locks
                WHERE locktype = 'advisory'
                  AND classid = :namespace
                  AND objsubid = 2
                  AND granted
                """
            ),
            {"namespace": namespace},
        ).scalars()
        return {int(objid) for objid in rows}
