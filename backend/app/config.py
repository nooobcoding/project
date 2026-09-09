"""환경변수 기반 앱 설정.

docs/00-overview.md 2장 기술 스택(PostgreSQL, JWT) 및 01-erd.md 전제 값들을 로드한다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


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
    cors_allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
