"""SQLAlchemy 선언적 모델의 공통 베이스.

01-erd.md 테이블당 모델 1개 원칙에 따라, models/ 아래 각 파일이 이 Base를 상속한다.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
