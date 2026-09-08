"""01-auth Boundary 계층 — /api/auth/*. Control(services/auth.py)만 호출한다."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.auth import EmailAvailabilityResponse, LoginRequest, RegisterRequest, TokenResponse
from app.services.auth import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    authenticate_user,
    create_access_token,
    get_current_user,
    get_user_by_email,
    register_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check-email", response_model=EmailAvailabilityResponse)
def check_email(email: EmailStr, db: Session = Depends(get_session)) -> EmailAvailabilityResponse:
    """01-auth.md 3장 — 회원가입 이메일 입력 blur 시 중복 여부 검증."""
    return EmailAvailabilityResponse(available=get_user_by_email(db, email) is None)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_session)) -> TokenResponse:
    try:
        user = register_user(db, payload.email, payload.password)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="이미 사용 중인 이메일입니다."
        )
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_session)) -> TokenResponse:
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/logout")
def logout(current_user=Depends(get_current_user)) -> dict[str, str]:
    """JWT는 무상태로 검증되므로 서버가 폐기할 상태가 없다 (01-auth.md 7장)."""
    return {"message": "로그아웃 되었습니다."}
