"""07-auto-trading Boundary 계층 — /api/strategy-slots/*. Control(services/strategy_slots.py)만 호출한다."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.strategy_slots import (
    SlotDeletionResponse,
    SlotSignalResponse,
    StrategySlotPatchRequest,
    StrategySlotResponse,
    StrategySlotWriteRequest,
    validate_params_for,
)
from app.services.auth import get_current_user
from app.services.strategy_slots import (
    CoinNotFoundError,
    DuplicateActiveSlotError,
    InsufficientAllocatableBalanceError,
    InsufficientBalanceError,
    InvalidSlotInputError,
    SlotActiveError,
    SlotHasPositionError,
    SlotNotFoundError,
    create_slot,
    delete_slot,
    get_slot_signal_status,
    list_slots,
    toggle_slot,
    update_slot,
)

router = APIRouter(prefix="/api/strategy-slots", tags=["strategy-slots"])

_PARAM_VALIDATION_ERROR_DETAIL = "기준값은 0~100 사이의 값을 입력해주세요."


def _to_response(slot) -> StrategySlotResponse:
    return StrategySlotResponse(
        id=slot.id,
        coin_symbol=slot.coin_symbol,
        strategy_type=slot.strategy_type,
        indicator=slot.indicator,
        params=slot.params,
        invest_amount=str(slot.invest_amount),
        stop_loss_pct=str(slot.stop_loss_pct) if slot.stop_loss_pct is not None else None,
        take_profit_pct=str(slot.take_profit_pct) if slot.take_profit_pct is not None else None,
        state=slot.state,
        is_active=slot.is_active,
        created_at=slot.created_at,
    )


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")


@router.post("", response_model=StrategySlotResponse, status_code=http_status.HTTP_201_CREATED)
def post_strategy_slot(
    payload: StrategySlotWriteRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> StrategySlotResponse:
    try:
        validated_params = validate_params_for(payload.strategy_type, payload.indicator, payload.params)
    except ValidationError:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=_PARAM_VALIDATION_ERROR_DETAIL)
    except KeyError:
        # 전략유형과 지표 조합이 아예 없는 경우 (예: 그리드인데 지표를 함께 보냄)
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")

    invest_amount = _parse_decimal(payload.invest_amount)
    stop_loss_pct = _parse_decimal(payload.stop_loss_pct)
    take_profit_pct = _parse_decimal(payload.take_profit_pct)

    try:
        slot = create_slot(
            db,
            user_id=current_user.id,
            coin_symbol=payload.coin_symbol.upper(),
            strategy_type=payload.strategy_type,
            indicator=payload.indicator,
            params=validated_params,
            invest_amount=invest_amount,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
    except CoinNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다.")
    except InvalidSlotInputError:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")
    except InsufficientBalanceError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="보유 원화를 초과하는 금액은 설정할 수 없습니다.",
        )
    return _to_response(slot)


@router.patch("/{slot_id}", response_model=StrategySlotResponse)
def patch_strategy_slot(
    slot_id: int,
    payload: StrategySlotPatchRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> StrategySlotResponse:
    try:
        if payload.is_active is not None:
            slot = toggle_slot(db, current_user.id, slot_id, payload.is_active)
        else:
            # indicator는 필수 항목이 아니다 — 그리드는 지표를 쓰지 않아 항상 None이다.
            if (
                payload.strategy_type is None
                or payload.params is None
                or payload.invest_amount is None
            ):
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST, detail="설정 항목을 모두 입력해주세요."
                )
            try:
                validated_params = validate_params_for(payload.strategy_type, payload.indicator, payload.params)
            except ValidationError:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST, detail=_PARAM_VALIDATION_ERROR_DETAIL
                )
            slot = update_slot(
                db,
                user_id=current_user.id,
                slot_id=slot_id,
                strategy_type=payload.strategy_type,
                indicator=payload.indicator,
                params=validated_params,
                invest_amount=_parse_decimal(payload.invest_amount),
                stop_loss_pct=_parse_decimal(payload.stop_loss_pct),
                take_profit_pct=_parse_decimal(payload.take_profit_pct),
            )
    except SlotNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 전략입니다.")
    except SlotActiveError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="실행 중인 전략은 먼저 OFF한 뒤 수정해주세요.",
        )
    except SlotHasPositionError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="보유 중인 코인이 남아 있는 그리드 전략은 설정을 바꿀 수 없습니다. 전략을 삭제한 뒤 다시 만들어주세요.",
        )
    except InvalidSlotInputError:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")
    except InsufficientBalanceError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="보유 원화를 초과하는 금액은 설정할 수 없습니다.",
        )
    except DuplicateActiveSlotError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="이미 해당 코인에 활성화된 전략이 있습니다.",
        )
    except InsufficientAllocatableBalanceError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="다른 자동매매에 이미 배정된 금액을 제외하면 잔고가 부족합니다.",
        )
    return _to_response(slot)


@router.delete("/{slot_id}", response_model=SlotDeletionResponse)
def delete_strategy_slot(
    slot_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> SlotDeletionResponse:
    try:
        result = delete_slot(db, current_user.id, slot_id)
    except SlotNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 전략입니다.")
    return SlotDeletionResponse(
        coin_symbol=result.coin_symbol,
        korean_name=result.korean_name,
        remaining_quantity=str(result.remaining_quantity),
    )


@router.get("", response_model=list[StrategySlotResponse])
def get_strategy_slots(
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> list[StrategySlotResponse]:
    return [_to_response(slot) for slot in list_slots(db, current_user.id)]


@router.get("/{slot_id}/signals", response_model=SlotSignalResponse)
def get_strategy_slot_signal(
    slot_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> SlotSignalResponse:
    try:
        signal = get_slot_signal_status(db, current_user.id, slot_id)
    except SlotNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 전략입니다.")
    return SlotSignalResponse(signal=signal, evaluated_at=datetime.now(timezone.utc))
