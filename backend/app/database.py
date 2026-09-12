"""SQLAlchemy engine/session 설정.

engine은 지연 생성한다 — 앱을 임포트·기동하는 시점에는 DB 연결을 시도하지 않고,
실제로 세션이 필요한 요청이 들어올 때 처음 연결한다. DB가 아직 준비되지 않은
상태에서도 (예: 로드맵 0번 착수 전) 서버 자체는 정상 기동해야 하기 때문이다.
"""

import threading
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_pool_peak_lock = threading.Lock()
_pool_peak_checked_out = 0


@lru_cache
def get_engine():
    """DB 엔진을 최초 호출 시점에 생성해 캐싱한다."""
    engine = create_engine(settings.database_url)
    pool = engine.pool

    def _track_checkout(dbapi_connection, connection_record, connection_proxy) -> None:
        # 커넥션 예산 실측용 (docs-scale/00-architecture.md 3.5절) — 이 프로세스가 실제로
        # 동시에 물고 있던 최대 커넥션 수를 관측해 풀 크기 설계 근거로 쓴다.
        global _pool_peak_checked_out
        checked_out = pool.checkedout()
        with _pool_peak_lock:
            if checked_out > _pool_peak_checked_out:
                _pool_peak_checked_out = checked_out

    event.listen(engine, "checkout", _track_checkout)
    return engine


def peak_checked_out() -> int:
    """이 프로세스가 기동 이래 동시에 쥐었던 커넥션 수의 최대치 (00-architecture.md 3.5절).

    **읽어도 리셋하지 않는다.** 풀은 역할이 아니라 프로세스 단위라 이 값의 주인도 프로세스다.
    읽을 때 리셋하면 heartbeat를 남기는 역할이 둘 이상이 되는 순간(5단계 matcher) 먼저 부른
    쪽이 값을 가져가고 나머지는 0을 보고하게 된다 — 그것도 아무 표시 없이.
    """
    with _pool_peak_lock:
        return _pool_peak_checked_out


def get_session() -> Session:
    """FastAPI 의존성 주입용 세션 팩토리."""
    session_local = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = session_local()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """요청-응답 사이클 밖(스케줄러 잡 등)에서 세션이 필요할 때 쓰는 컨텍스트 매니저."""
    session_local = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = session_local()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
