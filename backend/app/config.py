"""환경변수 기반 앱 설정.

docs/00-overview.md 2장 기술 스택(PostgreSQL, JWT) 및 01-erd.md 전제 값들을 로드한다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 전역 설정값.

    실제 값은 .env 파일 또는 환경변수로 주입한다 (.env.example 참고).
    """

    database_url: str = "postgresql+psycopg2://localhost:5432/coin_autotrading"
    jwt_secret_key: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_hours: int = 24  # 01-auth.md — Access Token 만료 24시간

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
