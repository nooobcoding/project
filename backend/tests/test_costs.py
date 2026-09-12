"""체결 비용 공용 함수 검증 (07 계획 Step 1, 01-erd.md 3.2절 규칙 그대로 손계산 대조)."""

from decimal import Decimal

from app.strategy_engine.costs import (
    calc_buy_amount,
    calc_fill_price,
    calc_realized_profit,
    calc_sell_amount,
    percent_to_decimal,
)


def test_percent_to_decimal_converts_column_unit_to_ratio():
    """DB 컬럼 0.05(%) → 소수 비율 0.0005. 이 변환 누락이 100배 오차의 원인이다 (01-erd.md 3.2절)."""
    assert percent_to_decimal(Decimal("0.05")) == Decimal("0.0005")


def test_calc_fill_price_applies_slippage_unfavorably():
    """매수는 이론가보다 비싸게, 매도는 이론가보다 싸게 슬리피지가 붙어야 한다."""
    theoretical = Decimal("100000")
    slippage = Decimal("0.001")  # 0.1%

    assert calc_fill_price(theoretical, "buy", slippage) == theoretical * Decimal("1.001")
    assert calc_fill_price(theoretical, "sell", slippage) == theoretical * Decimal("0.999")


def test_calc_fill_price_no_slippage_for_real_trades():
    """실체결은 slippage_rate=0(기본값)이라 이론가=체결가여야 한다 (00-overview.md 원칙 7)."""
    theoretical = Decimal("100000")
    assert calc_fill_price(theoretical, "buy") == theoretical
    assert calc_fill_price(theoretical, "sell") == theoretical


def test_calc_buy_amount_includes_fee():
    fee_rate = Decimal("0.0005")
    amount = calc_buy_amount(Decimal("1000"), Decimal("2"), fee_rate)
    assert amount == Decimal("1000") * Decimal("2") * Decimal("1.0005")


def test_calc_sell_amount_deducts_fee():
    fee_rate = Decimal("0.0005")
    amount = calc_sell_amount(Decimal("1000"), Decimal("2"), fee_rate)
    assert amount == Decimal("1000") * Decimal("2") * Decimal("0.9995")


def test_calc_realized_profit_uses_amount_before_holdings_update():
    """실현손익 = 매도 원화 증가액 - 취득원가. avg_buy_price는 갱신 "직전" 값이어야 한다."""
    fee_rate = Decimal("0.0005")
    profit = calc_realized_profit(
        sell_price=Decimal("1100"), quantity=Decimal("1"), avg_buy_price=Decimal("1000"), fee_rate=fee_rate
    )
    expected = Decimal("1100") * Decimal("0.9995") - Decimal("1000")
    assert profit == expected
