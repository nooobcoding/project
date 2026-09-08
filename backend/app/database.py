"""SQLAlchemy engine/session 설정.

engine은 지연 생성한다 — 앱을 임포트·기동하는 시점에는 DB 연결을 시도하지 않고,
실제로 세션이 필요한 요청이 들어올 때 처음 연결한다. DB가 아직 준비되지 않은
상태에서도 (예: 로드맵 0번 착수 전) 서버 자체는 정상 기동해야 하기 때문이다.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


@lru_cache
def get_engine():
    """DB 엔진을 최초 호출 시점에 생성해 캐싱한다."""
    return create_engine(settings.database_url)


def get_session() -> Session:
    """FastAPI 의존성 주입용 세션 팩토리."""
    session_local = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = session_local()
    try:
        yield db
    finally:
        db.close()
