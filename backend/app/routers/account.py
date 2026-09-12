"""04-settings Boundary 계층 — /api/account/*. Control(services/account.py)만 호출한다."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.account import AccountResponse, PasswordChangeRequest
from app.services.account import (
    CurrentPasswordIncorrectError,
    NewPasswordSameAsCurrentError,
    change_password,
    delete_account,
)
from app.services.auth import get_current_user

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("", response_model=AccountResponse)
def get_account(current_user=Depends(get_current_user)) -> AccountResponse:
    """04-settings.md 2-A — 가입 이메일 표시."""
    return AccountResponse(email=current_user.email)


@router.patch("/password")
def patch_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> dict[str, str]:
    try:
        change_password(db, current_user, payload.current_password, payload.new_password)
    except CurrentPasswordIncorrectError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="현재 비밀번호가 올바르지 않습니다.",
        )
    except NewPasswordSameAsCurrentError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호가 현재 비밀번호와 같습니다.",
        )
    return {"message": "비밀번호가 변경되었습니다."}


@router.delete("", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_my_account(
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> None:
    delete_account(db, current_user)
