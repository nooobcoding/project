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
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)

# advisory lock은 (classid, objid) 두 int로 식별한다. 역할 리더용 네임스페이스를 하나 잡아
# 두고, 5·7단계의 샤드 점유(matcher·worker)는 각자 다른 네임스페이스를 쓴다.
ROLE_LEADER_NAMESPACE = 4001
_ROLE_LOCK_IDS = {"market-data": 1}


@lru_cache
def _leader_engine():
    """리더 락 전용 엔진.

    NullPool이라 커넥션을 풀에 반납하지 않는다 — 풀이 재활용하면서 락이 풀리는 사고를
    구조적으로 막는다. AUTOCOMMIT은 이 커넥션이 몇 시간씩 idle in transaction으로 남아
    vacuum을 막는 것을 피하기 위한 것이다 (advisory lock은 트랜잭션이 아니라 세션에
    붙으므로 커밋과 무관하게 유지된다).
    """
    return create_engine(
        settings.database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )


class LeaderLock:
    """역할 하나의 리더십. 획득한 동안 전용 커넥션 하나를 붙잡는다."""

    def __init__(self, role: str) -> None:
        self.role = role
        self._lock_id = _ROLE_LOCK_IDS[role]
        self._connection = None

    def try_acquire(self) -> bool:
        """락을 시도한다. 이미 다른 프로세스가 쥐고 있으면 즉시 False (대기하지 않는다).

        DB가 아직 없거나 접속이 끊긴 경우도 False다 — 호출부는 "지금은 리더가 아니다"로만
        다루고 다음 주기에 다시 시도하면 된다 (DB 없이도 서버는 기동한다, database.py).
        """
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

    def is_held(self) -> bool:
        """이 세션이 실제로 락을 쥐고 있는지 DB에 되묻는다.

        커넥션이 끊겼다 조용히 재연결되는 등으로 락만 사라진 상태를 잡아내기 위한 것이라,
        애플리케이션 쪽 플래그가 아니라 `pg_locks`를 본다.
        """
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
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:
            logger.warning("%s 리더 락 커넥션 정리 실패", self.role)
        finally:
            self._connection = None
