"""01-auth Control 계층 — 비밀번호 해싱, JWT 발급/검증, 가입·로그인 흐름."""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import INITIAL_SEED_KRW
from app.database import get_session
from app.models import Balance, User

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class EmailAlreadyExistsError(Exception):
    """01-auth.md 4장 — 이미 사용 중인 이메일로 가입을 시도한 경우."""


class InvalidCredentialsError(Exception):
    """01-auth.md 4장 — 이메일 또는 비밀번호가 일치하지 않는 경우."""


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def create_access_token(user_id: int) -> str:
    """01-auth.md 8장 — Access Token 만료 24시간 고정 (Refresh Token 없음)."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.jwt_access_token_expire_hours
    )
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def register_user(db: Session, email: str, password: str) -> User:
    """계정 생성 + 초기 시드머니 지급 (01-auth.md 5장)."""
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailAlreadyExistsError()

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()  # balances.user_id FK를 채우기 위해 user.id를 미리 확정한다

    balance = Balance(
        user_id=user.id,
        krw_balance=INITIAL_SEED_KRW,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(balance)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    return user


def get_current_user(
    token: str = Depends(_oauth2_scheme), db: Session = Depends(get_session)
) -> User:
    """보호된 라우트에서 `Depends(get_current_user)`로 사용하는 인증 의존성."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user
