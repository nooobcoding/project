"""환경변수 기반 앱 설정.

docs/00-overview.md 2장 기술 스택(PostgreSQL, JWT) 및 01-erd.md 전제 값들을 로드한다.
"""

from typing import Annotated, Literal, get_args

from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic import field_validator

# 확장판 00-architecture.md 2장 프로세스 역할 5종. 타입으로 못 박아 두면 오타가 기동
# 시점에 걸린다 — `marketdata`처럼 한 글자만 틀려도 그 역할이 통째로 꺼지는데, 증상은
# "시세가 안 들어온다"로만 보여 원인을 찾기 어렵다.
ProcessRole = Literal["api", "market-data", "matcher", "worker", "scheduler"]


class Settings(BaseSettings):
    """앱 전역 설정값.

    실제 값은 .env 파일 또는 환경변수로 주입한다 (.env.example 참고).
    """

    database_url: str = "postgresql+psycopg2://localhost:5432/coin_autotrading"
    # 기본값을 두지 않는다 — 소스코드에 박힌 기본 시크릿은 공개 저장소에서 그대로
    # 노출되므로, 값을 실제로 설정하지 않으면 서버가 기동 자체를 못 하게 막는다.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_hours: int = 24  # 01-auth.md — Access Token 만료 24시간
    # 배포 환경마다 프론트 origin이 다르므로 하드코딩하지 않는다. .env의
    # CORS_ALLOWED_ORIGINS(콤마 구분)로 덮어쓴다 — 기본값은 로컬 개발용.
    # NoDecode: pydantic-settings는 list 타입 env 값을 기본적으로 JSON으로 파싱하려 든다
    # ("api" 같은 콤마 구분 문자열은 유효한 JSON이 아니라 그대로 두면 SettingsError가 난다).
    # NoDecode로 그 시도를 건너뛰고 원본 문자열을 아래 before-validator에 그대로 넘긴다.
    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # 확장판 00-architecture.md 2.1절 — 이 프로세스가 맡을 역할. 기본값은 전 역할 활성이라
    # 로컬 개발은 지금까지와 완전히 동일한 단일 프로세스로 동작한다. 운영에서 역할을 나눌 때만
    # PROCESS_ROLES(콤마 구분)로 부분집합을 지정한다 (07-roadmap.md 1단계).
    process_roles: Annotated[list[ProcessRole], NoDecode] = list(get_args(ProcessRole))
    # 확장판 02-market-data.md 5장 — 시세 캐시 백엔드. memory가 기본값이라 단일 프로세스
    # 로컬 개발은 지금과 완전히 동일하게(Redis 없이) 동작한다.
    price_cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    # 02-market-data.md 3.3절 — 이 값을 넘긴 시세는 "시세 없음"과 동일하게 취급한다
    # (market-data 페일오버 공백 동안 낡은 가격으로 손절·시장가 체결이 나가는 것을 막는다).
    # 초안값 30초 — 워커 tick(10초)보다는 커야 정상 상황에서 오탐이 안 나고, 손절이
    # 늦어지면 안 되므로 너무 크면 안 된다. 확정값은 06-observability.md 실측 후 조정한다.
    price_max_age_seconds: int = 30
    # 확장판 00-architecture.md 3.1절 — matcher(심볼)·worker(유저)가 공유하는 샤드 수.
    # **고정 상수로 다뤄야 한다.** 바꾸면 재해싱이 일어나 롤링 재시작 중 두 프로세스가 서로
    # 다른 소유권을 계산한다. 초안 16이고, 확정은 06-observability.md의 실측 뒤로 미룬다
    # (00-architecture.md 5장 열린 질문 1).
    shard_count: int = 16

    @field_validator("cors_allowed_origins", "process_roles", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
