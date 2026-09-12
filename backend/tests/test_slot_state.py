"""state.position 산술 검증 (07 계획 Step 2B).

포지션 평단은 `holdings.avg_buy_price`와 같은 계산식(수수료 포함 취득원가)이어야 한다
(01-erd.md 3.2절) — 어긋나면 슬롯이 계산하는 손익과 실제 보유분의 손익이 갈라진다.
DB 없이 도는 순수 함수 테스트다.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.services.slot_state import apply_buy, apply_sell, read_position

FEE_RATE = Decimal("0.0005")
FILLED_AT = datetime(2026, 9, 9, 4, 0, tzinfo=timezone.utc)


def test_read_position_treats_empty_state_as_no_position():
    assert read_position(None) is None
    assert read_position({}) is None
    assert read_position({"position": None}) is None


def test_read_position_treats_zero_quantity_as_no_position():
    """전량 청산 후 잔량 0이 남아 있어도 포지션 없음으로 봐야 재진입이 막히지 않는다."""
    assert read_position({"position": {"quantity": "0", "avg_price": "100", "entry_at": "x"}}) is None


def test_apply_buy_from_empty_uses_fee_inclusive_cost():
    """첫 매수: 평단 = 체결가 × (1 + 수수료율). 1000 × 1.0005 = 1000.5"""
    position = apply_buy(None, Decimal("1000"), Decimal("2"), FEE_RATE, FILLED_AT)

    assert position["quantity"] == "2.00000000"
    assert position["avg_price"] == "1000.50000000"
    assert position["entry_at"] == FILLED_AT.isoformat()


def test_apply_buy_accumulates_weighted_average():
    """추가 매수 시 가중평균. (2×1000.5 + 2000×1×1.0005) / 3 = (2001 + 2001) / 3 = 1334"""
    first = apply_buy(None, Decimal("1000"), Decimal("2"), FEE_RATE, FILLED_AT)
    second = apply_buy(first, Decimal("2000"), Decimal("1"), FEE_RATE, FILLED_AT)

    assert second["quantity"] == "3.00000000"
    assert second["avg_price"] == "1334.00000000"


def test_apply_buy_keeps_original_entry_at():
    """entry_at은 포지션을 처음 연 시각이다 — 추가 매수로 갱신되지 않는다 (01-erd.md 3.6절)."""
    first = apply_buy(None, Decimal("1000"), Decimal("1"), FEE_RATE, FILLED_AT)
    later = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)
    second = apply_buy(first, Decimal("1000"), Decimal("1"), FEE_RATE, later)

    assert second["entry_at"] == FILLED_AT.isoformat()


def test_apply_sell_keeps_average_price():
    """일부 매도는 취득원가를 바꾸지 않는다 — 남은 수량이 같은 평단을 그대로 이어받는다."""
    position = apply_buy(None, Decimal("1000"), Decimal("3"), FEE_RATE, FILLED_AT)
    remaining = apply_sell(position, Decimal("1"))

    assert remaining["quantity"] == "2.00000000"
    assert remaining["avg_price"] == position["avg_price"]
    assert remaining["entry_at"] == position["entry_at"]


def test_apply_sell_full_liquidation_returns_none():
    """전량 청산이면 None — 호출자가 state에서 position 키 자체를 지운다."""
    position = apply_buy(None, Decimal("1000"), Decimal("2"), FEE_RATE, FILLED_AT)
    assert apply_sell(position, Decimal("2")) is None


def test_apply_sell_over_quantity_returns_none():
    """보유분보다 많이 팔린 경우(있어선 안 되지만)도 음수 잔량을 남기지 않는다."""
    position = apply_buy(None, Decimal("1000"), Decimal("1"), FEE_RATE, FILLED_AT)
    assert apply_sell(position, Decimal("5")) is None


def test_apply_sell_without_position_returns_none():
    assert apply_sell(None, Decimal("1")) is None
